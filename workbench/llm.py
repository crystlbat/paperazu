"""Talk to the Unsloth (llama-server) OpenAI-compatible endpoint."""
import json
import re
import time
import urllib.error
import urllib.request
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


# The loaded window first. n_ctx_train is how big the model can be, not how it was started.
_CTX_KEYS = ("n_ctx", "max_model_len", "context_length", "max_context_length", "n_ctx_train")


def _fetch(url: str, key: str, timeout: float) -> tuple[str, Any]:
    """("ok", json) from a local server URL, ("miss", None) if that URL has nothing,
    ("key", None) if the key is refused, ("down", None) if the server cannot be reached."""
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"} if key else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — the URL is the user's own server
            raw = r.read().decode()
    except urllib.error.HTTPError as e:
        return ("key", None) if e.code in (401, 403) else ("miss", None)
    except (urllib.error.URLError, TimeoutError, OSError):
        return "down", None
    try:
        return "ok", json.loads(raw or "null")
    except json.JSONDecodeError:
        return "miss", None


def _note_ctx(node: Any, found: dict[str, int]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if k in _CTX_KEYS and isinstance(v, (int, float)) and not isinstance(v, bool) and int(v) >= 256:
                found.setdefault(k, int(v))
            else:
                _note_ctx(v, found)
    elif isinstance(node, list):
        for item in node:
            _note_ctx(item, found)


def context_window(s: Settings) -> dict[str, Any]:
    """How many tokens the local server can hold, from its own report. No chat call.

    A running window (n_ctx, or the same idea under another name) wins over n_ctx_train,
    which is only how large the model can be, not how it was started.
    """
    root = s.base_url.removesuffix("/v1").rstrip("/")
    found: dict[str, int] = {}
    saw = False
    refused = False
    reached = False
    for url in (f"{s.base_url.rstrip('/')}/models", f"{root}/props", f"{root}/slots"):
        status, data = _fetch(url, s.api_key, 5)
        if status == "key":
            refused = True
            reached = True
            continue
        if status == "down":
            continue
        reached = True
        if status != "ok":
            continue
        saw = True
        _note_ctx(data, found)
        if any(k in found for k in _CTX_KEYS[:4]):
            break
    if not saw and refused:
        return {"ok": False, "error": "Wrong API key."}
    if not reached:
        return {"ok": False, "error": "Could not reach the model server. Is Unsloth running?"}
    running = next((found[k] for k in _CTX_KEYS[:4] if k in found), None)
    if running is not None:
        return {"ok": True, "tokens": running, "kind": "running", "saved": s.max_context_tokens}
    if "n_ctx_train" in found:
        return {"ok": True, "tokens": found["n_ctx_train"], "kind": "trained", "saved": s.max_context_tokens}
    return {"ok": False, "error": "The server did not say how big its context window is."}


EXPLAIN_SYSTEM = (
    "You help a student read a research paper. The student marked some words. Explain what they mean "
    "as they are used in this paper, in simple English, in 3 to 5 short sentences. Say what the words "
    "mean and why they matter here. Do not summarize the paper's results. If the paper does not define "
    "them, say so and give the usual meaning. If the marked text is a formula or notation (it may look "
    "jumbled after copying out of the PDF), say what each symbol stands for in this paper and what the "
    "formula says as a whole. If a picture of the marked part comes with the question, trust it over the copied text. No headings, no lists."
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


ASK_SYSTEM = (
    "You help a student read a research paper. Answer the student's question using this paper, in simple "
    "English, in at most 6 short sentences. Name the page when you use one. If the paper does not answer "
    "it, say so and give the usual answer. No headings."
)


def _answer(s: Settings, system: str, question: str, title: str, pages: list[str], page: int,
            image: str | None = None) -> dict[str, Any]:
    """One question to the local model with the paper (or what fits) as context. `page` is 0-based.
    `image` is a data: URL sent with the question; if the server will not take images, it asks again without."""
    page = min(max(page, 0), max(len(pages) - 1, 0))
    paper, keep = paper_text(s, pages, page, system + question + title)
    start = time.perf_counter()
    prompt = f"Paper: {title}\n\n<paper>\n{paper}\n</paper>\n\n{question}"
    content: Any = [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": image}}] if image else prompt
    try:
        try:
            r = client(s).chat.completions.create(
                model=pick_model(s) or "default",
                messages=[{"role": "system", "content": system}, {"role": "user", "content": content}],
                max_tokens=s.max_output_tokens, temperature=s.temperature,
            )
        except APIStatusError as e:
            if not image or e.status_code not in (400, 415, 422, 500, 501):
                raise
            return _answer(s, system, question, title, pages, page)  # a text-only model: ask without the picture
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


def explain(s: Settings, words: str, title: str, pages: list[str], page: int, image: str | None = None) -> dict[str, Any]:
    """Explain marked words with the whole paper as context (or as much as fits the budget), and a picture of them if given."""
    page = min(max(page, 0), max(len(pages) - 1, 0))
    question = f'Words I marked on page {page + 1}: "{words}"\nWhat do they mean in this paper?'
    return _answer(s, EXPLAIN_SYSTEM, question, title, pages, page, image)


def ask(s: Settings, question: str, title: str, pages: list[str], page: int) -> dict[str, Any]:
    """Answer a free question about the paper. `page` is the 0-based page the student is looking at."""
    page = min(max(page, 0), max(len(pages) - 1, 0))
    return _answer(s, ASK_SYSTEM, f"I am looking at page {page + 1}. My question: {question}", title, pages, page)


BOX_SYSTEM = (
    "You help a student read a research paper. The student drew a box round part of a page and asked about it. "
    "You get the text inside the box (formulas may look jumbled after copying out of the PDF) and, when possible, "
    "a picture of the box: trust the picture for formulas. Answer in simple English, in 2 to 5 short sentences, "
    "about the boxed part as it is used in this paper. For a formula, say what each symbol stands for."
)


def ask_box(s: Settings, question: str, boxed: str, image: str | None, title: str, pages: list[str], page: int) -> dict[str, Any]:
    """Answer a question about a boxed part of a page, with a picture of the box. `page` is 0-based."""
    page = min(max(page, 0), max(len(pages) - 1, 0))
    q = f'The box I drew on page {page + 1} holds this text:\n"""\n{boxed[:3000]}\n"""\nMy question: {question}'
    return _answer(s, BOX_SYSTEM, q, title, pages, page, image)


NOTE_SYSTEM = (
    "You help a student inside their own note about a part of a research paper. You get the text of the part the "
    "note is about (formulas may look jumbled after copying out of the PDF) and, when possible, a picture of it: "
    "trust the picture for formulas. The note so far is given as earlier lines. Answer the last question in simple "
    "English, in 2 to 5 short sentences. For a formula, say what each symbol stands for."
)


def note_reply(s: Settings, lines: list[dict[str, Any]], boxed_text: str, image: str | None, title: str, pages: list[str],
               page: int) -> dict[str, Any]:
    """Dot's answer to the last `me` line of a note. `lines` are the note's entries ({who, text}); `page` is 0-based.
    Without a box (`boxed_text` empty, no `image`) it answers from the paper alone."""
    page = min(max(page, 0), max(len(pages) - 1, 0))
    last = max((i for i, e in enumerate(lines) if e["who"] == "me"), default=None)
    if last is None:
        return {"ok": False, "error": "There is no question to answer."}
    question = lines[last]["text"].strip()
    question = question[3:].strip() if question.startswith("@ai") else question
    earlier = "".join(f"{'Student' if e['who'] == 'me' else 'Dot'}: {e['text'][:1000]}\n" for e in lines[:last])
    q = (f'The note is about this part of page {page + 1}:\n"""\n{boxed_text[:3000]}\n"""\n' if boxed_text else f"I am looking at page {page + 1}.\n")
    q += (f"The note so far:\n{earlier}\n" if earlier else "") + f"My question: {question}"
    return _answer(s, NOTE_SYSTEM, q, title, pages, page, image)


HIGHLIGHT_SYSTEM = (
    "You help a student read a research paper. You get one part of a page. Pick only the most important parts "
    "the student should remember (a key claim, a definition, a main result). Copy each one word for word from the "
    "text. Give at most 3, each at most 25 words, never a whole paragraph. Fewer is better. "
    'Reply with JSON only: {"quotes": ["..."]}.'
)
_QUOTES = {"type": "object", "properties": {"quotes": {"type": "array", "items": {"type": "string"}}},
           "required": ["quotes"], "additionalProperties": False}


def pick_quotes(s: Settings, text: str, title: str) -> list[str]:
    """Quotes worth highlighting in `text`. Raises primer.PrimerError for the user; broken JSON is asked twice, then []."""
    from . import primer  # primer imports this module
    msgs = [{"role": "system", "content": HIGHLIGHT_SYSTEM},
            {"role": "user", "content": f"Paper: {title}\n\nText:\n\"\"\"\n{text[:6000]}\n\"\"\""}]
    for _ in range(2):
        try:
            out = json.loads(primer._complete(s, msgs, _QUOTES, "quotes"))["quotes"]
            return [q.strip() for q in out if isinstance(q, str) and q.strip()][:3]
        except (ValueError, KeyError, TypeError):
            continue
    return []


SOURCES_SYSTEM = (
    "You help a student read a research paper. Answer the question in simple English, in at most 6 short sentences. "
    "You get the paper's paragraphs, each with an id like p3-b7. Name only ids from that list as sources, at most 4, "
    "each with a gist of at most 12 words. Name only paragraphs that really answer the question. "
    'Return JSON: {"answer": "...", "sources": [{"block": "p3-b7", "gist": "..."}]}.'
)


def ask_with_sources(s: Settings, question: str, title: str, paras: list[tuple[str, int, list[float], str]],
                     context: str = "") -> dict[str, Any]:
    """Answer and name the paragraphs that back it up. Each para is (id, page, rect, text)."""
    from pydantic import BaseModel, ValidationError

    from . import primer

    class Src(BaseModel):
        block: str
        gist: str

    class Reply(BaseModel):
        answer: str
        sources: list[Src] = []

    ids = [p[0] for p in paras]
    schema = {"type": "object", "required": ["answer", "sources"], "properties": {
        "answer": {"type": "string"},
        "sources": {"type": "array", "items": {"type": "object", "required": ["block", "gist"], "properties": {
            "block": {"type": "string", "enum": ids}, "gist": {"type": "string"}}}}}}
    listing = "\n\n".join(f"{i} (page {pg}): {t[:700]}" for i, pg, _, t in paras)
    messages = [{"role": "system", "content": SOURCES_SYSTEM},
                {"role": "user", "content": f"Paper: {title}\n\n<paragraphs>\n{listing}\n</paragraphs>\n\n"
                                            f"{context}My question: {question}\n\nReturn the JSON."}]
    try:
        for _ in range(2):
            reply = primer._complete(s, messages, schema, "sources")
            a, b = reply.find("{"), reply.rfind("}")
            try:
                out = Reply.model_validate_json(reply[a:b + 1] if a >= 0 else reply)
            except ValidationError as e:
                messages += [{"role": "assistant", "content": reply},
                             {"role": "user", "content": f"That answer was not valid: {str(e)[:300]}\nReturn only JSON."}]
                continue
            by = {p[0]: p for p in paras}
            src = [{"page": by[x.block][1], "rect": by[x.block][2], "gist": x.gist.strip()[:120]}
                   for x in out.sources if x.block in by]
            return {"ok": True, "text": out.answer.strip(), "sources": src[:4]}
    except primer.PrimerError as e:
        return {"ok": False, "error": str(e)}
    pages = [""] * max(p[1] for p in paras)  # paragraph text by page, for the plain answer
    for _, pg, _, t in paras:
        pages[pg - 1] += t + "\n\n"
    plain = ask(s, context + question, title, pages, min(p[1] for p in paras) - 1)
    return {"ok": True, "text": plain["text"], "sources": []} if plain["ok"] else plain
