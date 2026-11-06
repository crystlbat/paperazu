"""Talk to the Unsloth (llama-server) OpenAI-compatible endpoint."""
import re
import time
from typing import Any

from openai import APIConnectionError, APIError, APIStatusError, AuthenticationError, OpenAI

from . import context
from .settings import Settings


def client(s: Settings, timeout: float | None = None) -> OpenAI:
    return OpenAI(base_url=s.base_url, api_key=s.api_key or "none",
                  timeout=timeout or s.timeout_s, max_retries=0)


def model_status(s: Settings) -> dict[str, Any]:
    try:
        models = [m.id for m in client(s, timeout=5).models.list()]
    except AuthenticationError:
        return {"status": "wrong_key", "label": "Wrong API key", "models": []}
    except APIConnectionError:  # also covers timeouts
        return {"status": "not_running", "label": "Model not running", "models": []}
    except APIStatusError as e:
        return {"status": "error", "label": f"Server error {e.status_code}", "models": []}
    return {"status": "ready", "label": "Model ready", "models": models}


def pick_model(s: Settings) -> str:
    if s.model_name:
        return s.model_name
    models = model_status(s)["models"]
    return models[0] if models else ""


def test_connection(s: Settings) -> dict[str, Any]:
    start = time.perf_counter()
    try:
        r = client(s, timeout=min(s.timeout_s, 60)).chat.completions.create(
            model=pick_model(s) or "default",
            messages=[{"role": "user", "content": "Reply with the word OK."}],
            max_tokens=16, temperature=0,
        )
    except AuthenticationError:
        return {"ok": False, "error": "Wrong API key."}
    except APIConnectionError:
        return {"ok": False, "error": "Could not reach the model server. Is Unsloth running?"}
    except APIError as e:
        return {"ok": False, "error": e.message}
    return {"ok": True, "model": r.model, "reply": (r.choices[0].message.content or "").strip(),
            "seconds": round(time.perf_counter() - start, 2)}


EXPLAIN_SYSTEM = (
    "You help a student read a research paper. The student marked some words. Explain what they mean "
    "as they are used in this paper, in simple English, in 3 to 5 short sentences. Say what the words "
    "mean and why they matter here. Do not summarize the paper's results. If the paper does not define "
    "them, say so and give the usual meaning. No headings, no lists."
)


def _strip_thinking(text: str) -> str | None:
    """Drop <think> blocks some models print. None if the model never finished thinking."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    return None if "<think>" in text else text.strip()


def paper_text(s: Settings, pages: list[str], page: int, overhead: str) -> tuple[str, list[int]]:
    """The paper as page-labelled text: every page if it fits the context budget, else the pages
    nearest `page` (0-based). Returns the text and the page indexes used."""
    budget = (s.max_context_tokens - s.max_output_tokens
              - context.tokens(overhead) - 64 * len(pages) - 200)
    keep = context.fit_pages(pages, budget, page) if pages else []
    room = int(budget * context.CHARS_PER_TOKEN)
    return "\n\n".join(f"--- Page {i + 1} ---\n{pages[i].strip()}" for i in keep)[:max(room, 0)], keep


IDEAS_SYSTEM = (
    "You read research papers and name their key ideas. Reply with exactly 5 lines. Each line is one "
    "idea from this paper in 2 to 5 plain words, such as a method, a concept, a problem or a finding. "
    "No numbering, no bullets, no explanations, no full sentences.\n"
    "Example for a paper about image classifiers:\nResidual connections\nVanishing gradients\n"
    "ImageNet benchmark\nData augmentation\nTop-1 accuracy"
)

_CUT = {"is", "are", "was", "were", "can", "could", "enable", "enables", "allow", "allows", "fail", "fails",
        "help", "helps", "show", "shows", "needs", "need", "needed", "lead", "leads", "make", "makes", "reveal",
        "reveals", "remain", "remains", "provide", "provides", "should", "must", "may", "will", "without", "despite",
        "extend", "extends", "require", "requires", "identified", "across", "beyond", "like", "such", "including",
        "using", "used", "based", "that", "which", "has", "have", "does", "do", "vary", "varies",
        "differ", "differs", "reflect", "reflects", "fit", "fits", "systematically", "need", "into"}
_TAIL = {"and", "or", "of", "the", "a", "an", "for", "to", "in", "on", "with", "by"}


def _short_idea(line: str) -> str:
    """Small models often answer with a sentence; keep its opening noun phrase (at most 5 words)."""
    line = re.sub(r"\s*\([^)]*$", "", line)  # an unclosed bracket means the phrase was cut
    words = line.split()
    for i, w in enumerate(words[2:], 2):
        if w.lower().strip(",;") in _CUT:
            words = words[:i]
            break
    words = words[:5]
    while words and words[-1].lower().strip(",;") in _TAIL:
        words.pop()
    return " ".join(words).strip(",;")


def key_ideas(s: Settings, title: str, pages: list[str]) -> list[str]:
    """Five short key ideas from the whole paper. Raises RuntimeError with a message for the user."""
    paper, _ = paper_text(s, pages, 0, IDEAS_SYSTEM + title)
    try:
        r = client(s).chat.completions.create(
            model=pick_model(s) or "default",
            messages=[{"role": "system", "content": IDEAS_SYSTEM},
                      {"role": "user", "content": f"Paper: {title}\n\n<paper>\n{paper}\n</paper>\n\nThe 5 key ideas:"}],
            max_tokens=s.max_output_tokens, temperature=s.temperature,
        )
    except AuthenticationError:
        raise RuntimeError("Wrong API key. Check it in Settings.")
    except APIConnectionError:
        raise RuntimeError("Could not reach the model. Is Unsloth running?")
    except APIError as e:
        raise RuntimeError(e.message)
    text = _strip_thinking(r.choices[0].message.content or "")
    if text is None:
        raise RuntimeError("The model ran out of room before it answered. Raise Max output tokens in Settings.")
    ideas: list[str] = []
    for line in text.splitlines():
        line = _short_idea(re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip().strip("*\"'.:").strip())
        if 2 <= len(line) <= 60 and line.lower() not in (i.lower() for i in ideas):
            ideas.append(line)
    return ideas[:5]


def explain(s: Settings, words: str, title: str, pages: list[str], page: int) -> dict[str, Any]:
    """Explain marked words with the whole paper as context (or as much as fits the budget).
    `page` is the 0-based page the words were marked on."""
    page = min(max(page, 0), max(len(pages) - 1, 0))
    question = f'Words I marked on page {page + 1}: "{words}"\nWhat do they mean in this paper?'
    paper, keep = paper_text(s, pages, page, EXPLAIN_SYSTEM + question + title)
    start = time.perf_counter()
    try:
        r = client(s).chat.completions.create(
            model=pick_model(s) or "default",
            messages=[{"role": "system", "content": EXPLAIN_SYSTEM},
                      {"role": "user", "content": f"Paper: {title}\n\n<paper>\n{paper}\n</paper>\n\n{question}"}],
            max_tokens=s.max_output_tokens, temperature=s.temperature,
        )
    except AuthenticationError:
        return {"ok": False, "error": "Wrong API key. Check it in Settings."}
    except APIConnectionError:
        return {"ok": False, "error": "Could not reach the model. Is Unsloth running?"}
    except APIError as e:
        return {"ok": False, "error": e.message}
    text = _strip_thinking(r.choices[0].message.content or "")
    if not text:
        return {"ok": False, "error": "The model ran out of room before it answered. Raise Max output tokens in Settings."}
    return {"ok": True, "text": text, "pages": [keep[0] + 1, keep[-1] + 1] if keep else [],
            "whole": len(keep) == len(pages), "total": len(pages), "seconds": round(time.perf_counter() - start, 1)}
