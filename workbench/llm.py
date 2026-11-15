"""Talk to the Unsloth (llama-server) OpenAI-compatible endpoint."""
import json
import re
import threading
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


_picked: dict[str, tuple[str, float]] = {}  # base_url -> (model, when), so each call does not list the models again


def pick_model(s: Settings) -> str:
    """The model setting, else a chat model the server lists: one already loaded first, never an embedding model."""
    if s.model_name:
        return s.model_name
    got = _picked.get(s.base_url)
    if got and time.time() - got[1] < 30:
        return got[0]
    try:
        listed = list(client(s, timeout=5).models.list())
    except APIError:
        return ""
    chat = [m for m in listed if "embed" not in m.id.lower()] or listed
    best = next((m.id for m in chat if getattr(m, "loaded", False)), chat[0].id if chat else "")
    _picked[s.base_url] = (best, time.time())
    return best


def test_connection(s: Settings) -> dict[str, Any]:
    start = time.perf_counter()
    try:
        r = client(s, timeout=min(s.timeout_s, 60)).chat.completions.create(
            model=pick_model(s) or "default",
            messages=[{"role": "user", "content": "Reply with the word OK."}],
            max_tokens=16, temperature=0, extra_body=NO_THINK,
        )
    except AuthenticationError:
        return {"ok": False, "error": "Wrong API key."}
    except APIConnectionError:
        return {"ok": False, "error": "Could not reach the model server. Is Unsloth running?"}
    except APIError as e:
        return {"ok": False, "error": e.message}
    return {"ok": True, "model": r.model, "reply": (r.choices[0].message.content or "").strip(),
            "seconds": round(time.perf_counter() - start, 2)}


SWAP: dict[str, Any] = {"busy": False, "from": "", "to": "", "phase": "", "fraction": 0.0, "started": ""}  # the live model swap, for GET /model/swap
_swap_lock = threading.Lock()  # one model at a time, process wide


def _api(s: Settings, method: str, path: str, body: dict[str, Any] | None = None, timeout: float = 10) -> Any:
    """One call to the Unsloth inference API at the server root (not /v1). Tests replace this. Raises on HTTP or network errors."""
    req = urllib.request.Request(f"{s.base_url.removesuffix('/v1').rstrip('/')}/api/inference/{path}", method=method,
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {s.api_key}"} if s.api_key else {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — the URL is the user's own server
        raw = r.read().decode()
    try:
        return json.loads(raw or "null")
    except json.JSONDecodeError:  # load/unload answer padded streams; only status and progress need a body
        return raw


def ensure(s: Settings, model: str, timeout: float = 600, poll: float = 1.0) -> dict[str, Any] | None:
    """Make `model` the loaded one: unload the current, load it, poll until it is active. None when nothing had to change.
    Every swap (and every skip) is a "model" engine row: from, to, seconds, ok/failed."""
    from . import char  # char imports llm
    if not model:
        return None
    with _swap_lock:
        try:
            st = _api(s, "GET", "status")
        except Exception as e:
            char._engine("model", "skipped", f"status unreachable: {e}")
            return None
        if not isinstance(st, dict) or "active_model" not in st or not isinstance(st.get("loaded"), list):
            char._engine("model", "skipped", "unknown status shape")
            return None
        cur = st.get("active_model") or ""
        if cur == model:
            return None
        t0 = time.time()
        SWAP.update(busy=True, **{"from": cur}, to=model, phase="unloading" if cur else "loading", fraction=0.0, started=time.strftime("%H:%M:%S"))
        ok, why = False, "timed out"
        try:
            if cur:
                _api(s, "POST", "unload", {"model_path": cur}, timeout=timeout)
            SWAP["phase"] = "loading"
            _api(s, "POST", "load", {"model_path": model}, timeout=timeout)
            while time.time() - t0 < timeout:
                st = _api(s, "GET", "status")
                if isinstance(st, dict) and st.get("active_model") == model and model not in (st.get("loading") or []):
                    ok = True
                    break
                p = _api(s, "GET", "load-progress")
                if isinstance(p, dict):
                    SWAP.update(phase=p.get("phase") or "loading", fraction=float(p.get("fraction") or 0))
                time.sleep(poll)
        except Exception as e:
            why = str(e)[:120]
        secs = round(time.time() - t0, 1)
        SWAP.update(busy=False, phase="ready" if ok else "failed", fraction=1.0 if ok else SWAP["fraction"])
        _picked.clear()  # the cached pick may name the model that just left
        char._engine("model", "ok" if ok else "failed", f"{cur or 'nothing'} → {model} in {secs:.0f}s" + ("" if ok else f" ({why})"))
        return {"from": cur, "to": model, "seconds": secs, "ok": ok}


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

FORMULA_SYSTEM = (
    "You help a student read a research paper. The student marked a formula (copied out of the PDF it may look "
    "jumbled; if a picture of it comes with the question, read the picture). Take it apart term by term.\n"
    "1. One plain sentence: what the formula computes and what it is for in this paper.\n"
    "2. Then a list, one line per term, symbol or operation, in the order they appear, each line as "
    "\"- term \u2014 what it is, in everyday words\". Cover every piece: each symbol, each fraction (top and "
    "bottom), each sum (what it adds up over), indicator brackets, absolute values, and the subscripts and "
    "superscripts. Write symbols plainly (F1, TP, sum over D^e, 1[f(x)=1 and a=0]), never LaTeX. Use the "
    "paper's own definitions from the text around the formula.\n"
    "3. Then a line starting \"In plain words:\" with 2 or 3 sentences that put it back together, and one tiny "
    "example with made-up numbers if it helps.\n"
    "Name each term once, at most 14 lines in the list. Keep step 1 to one sentence. If several formulas are "
    "marked, do this for each in turn. Read what the paper says right after the formula (\"where ...\") and use "
    "it. Do not guess what the paper does not say."
)


# thinking models (Gemma 4, Qwen 3) spend the whole reply budget reasoning on short structured jobs; servers that
# do not know the switch ignore it
NO_THINK = {"chat_template_kwargs": {"enable_thinking": False}}


def persona(s: Settings) -> str:
    """The voice the student picked for Dot, as a line for a system prompt (empty when none)."""
    p = (s.dot_persona or "").strip()[:300]
    return f"\nSpeak in this voice, chosen by the student: {p}. Keep every fact and the format exactly as asked." if p else ""


def _no_loops(text: str) -> str:
    """Small models fall into a loop on long lists: keep each line once and stop where it starts going round."""
    out, seen, again = [], set(), 0
    for line in text.splitlines():
        key = re.sub(r"\W+", " ", line).strip().lower()
        if key and key in seen:
            again += 1
            if again >= 2:
                break
            continue
        seen.add(key)
        out.append(line)
    return "\n".join(out).strip()


def _formula(words: str) -> bool:
    """Marked text that is math rather than prose."""
    return ":=" in words or len(re.findall(r"[=\u2211\u03a3\u2227\u2228\u2208\u2206\u0394{}\[\]^_|\u223c~]", words)) >= 4 or not _readable(words)


def _strip_thinking(text: str) -> str | None:
    """Drop <think> blocks some models print. None if the model never finished thinking."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    return None if "<think>" in text else text.strip()


_WINDOW = re.compile(r"(?:(\d+) tokens )?exceeds the (\d+)-token context window")
ROOM = "The model ran out of room before it answered. Raise Max output tokens in Settings."


class ModelError(RuntimeError):
    """A message the user can act on. `status` is the server's HTTP status when it refused the request."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


# (base_url, model setting) -> (tokens, when, characters a token): the loaded window, when the server said it is
# smaller than the setting, and how densely it counted our text.
# shortcut: forgotten after 10 minutes in case the model was reloaded bigger; ask /props for n_ctx if servers start reporting it.
_windows: dict[tuple[str, str], tuple[int, float, float]] = {}


def window(s: Settings) -> int:
    """Tokens one request may hold: the setting, or the smaller window the server last said it has."""
    got = _windows.get((s.base_url, s.model_name))
    return min(s.max_context_tokens, got[0]) if got and time.time() - got[1] < 600 else s.max_context_tokens


def reply_tokens(s: Settings, want: int | None = None) -> int:
    """Room kept for the reply. A window smaller than the setting gives at most a quarter of itself to the reply."""
    want = want or s.max_output_tokens
    win = window(s)
    return want if win >= s.max_context_tokens else min(want, max(64, win // 4))


def _text(m: dict[str, Any]) -> str:
    c = m.get("content")
    return c if isinstance(c, str) else "".join(x.get("text", "") for x in c or [] if isinstance(x, dict))


def _trim(messages: list[dict[str, Any]], keep: int, chars_per_token: float) -> list[dict[str, Any]]:
    """Cut the middle out of the longest message so the request is about `keep` tokens. Its start (the
    instruction) and its end (the question) stay."""
    sizes = [len(_text(m)) for m in messages]
    over = sum(sizes) - int(max(keep, 0) * chars_per_token)
    if over <= 0 or not messages:
        return messages
    i = max(range(len(messages)), key=sizes.__getitem__)
    t = _text(messages[i])
    left = max(len(t) - over, 0)
    cut = t[:left // 2] + "\n[... cut to fit the model ...]\n" + (t[len(t) - (left - left // 2):] if left - left // 2 else "")
    c = messages[i]["content"]
    new = cut if isinstance(c, str) else [{**x, "text": cut} if isinstance(x, dict) and x.get("type") == "text" else x for x in c]
    return [*messages[:i], {**messages[i], "content": new}, *messages[i + 1:]]


def _window_of(e: APIStatusError) -> tuple[int | None, int] | None:
    """(tokens sent, window) from a "too long for the window" refusal: Unsloth's message or llama-server's n_ctx."""
    if m := _WINDOW.search(e.message or ""):
        return (int(m[1]) if m[1] else None), int(m[2])
    body = getattr(e, "body", None)
    err = body.get("error", body) if isinstance(body, dict) else None
    if isinstance(err, dict) and isinstance(err.get("n_ctx"), int) and "context" in str(err.get("message", "")).lower():
        return err.get("n_prompt_tokens"), err["n_ctx"]
    return None


def chat(s: Settings, messages: list[dict[str, Any]], *, max_tokens: int | None = None, temperature: float | None = None,
         response_format: dict[str, Any] | None = None, trim: bool = True, _again: bool = False) -> str:
    """One reply from the local model with thinking removed. Every model call in the app goes through here.

    A request longer than the window is cut in its longest message first. When the server says its loaded
    window is smaller than the setting, that window is remembered and (with `trim`) the request is cut and sent
    once more. Raises ModelError."""
    out = reply_tokens(s, max_tokens)
    if trim:
        learned = _windows.get((s.base_url, s.model_name))
        messages = _trim(messages, window(s) - out - 64, min(context.CHARS_PER_TOKEN, learned[2] if learned else 99))
    extra: dict[str, Any] = {"response_format": response_format} if response_format else {}
    try:
        r = client(s).chat.completions.create(
            model=pick_model(s) or "default", messages=messages, max_tokens=out,  # type: ignore[arg-type]
            temperature=s.temperature if temperature is None else temperature, extra_body=NO_THINK, **extra)
    except AuthenticationError:
        raise ModelError("Wrong API key. Check it in Settings.")
    except APIConnectionError:
        raise ModelError("Could not reach the model. Is Unsloth running?")
    except APIStatusError as e:
        found = _window_of(e)
        if not found:
            raise ModelError(e.message or "The model call failed.", e.status_code)
        sent, size = found
        ratio = 0.95 * (sum(len(_text(m)) for m in messages) / sent if sent else context.CHARS_PER_TOKEN * 0.8)
        _windows[(s.base_url, s.model_name)] = (size, time.time(), ratio)
        if trim and not _again:
            return chat(s, _trim(messages, size - reply_tokens(s, max_tokens) - 64, ratio), max_tokens=max_tokens,
                        temperature=temperature, response_format=response_format, _again=True)
        raise ModelError(f"The loaded model holds only {size} tokens, less than the {s.max_context_tokens} set in Settings. "
                         "Load it with a bigger context window, or lower Max context tokens in Settings.")
    except APIError as e:
        raise ModelError(e.message or "The model call failed.")
    choice = r.choices[0]
    text = _strip_thinking(choice.message.content or "")
    cut_off = getattr(choice, "finish_reason", None) == "length"
    if text is None or (cut_off and (not text or response_format)):  # half a JSON object is no use
        raise ModelError(ROOM)
    if not text:
        raise ModelError("The model gave an empty answer. Try again.")
    return text


def paper_text(s: Settings, pages: list[str], page: int, overhead: str) -> tuple[str, list[int]]:
    """The paper as page-labelled text: every page if it fits the context budget, else the pages
    nearest `page` (0-based). Returns the text and the page indexes used."""
    budget = window(s) - reply_tokens(s) - context.tokens(overhead) - 6 * len(pages) - 100
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
    text = chat(s, [{"role": "system", "content": IDEAS_SYSTEM},
                    {"role": "user", "content": f"Paper: {title}\n\n<paper>\n{paper}\n</paper>\n\nThe 5 key ideas:"}])
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
            image: str | None = None, _again: bool = False) -> dict[str, Any]:
    """One question to the local model with the paper (or what fits) as context. `page` is 0-based.
    `image` is a data: URL sent with the question; if the server will not take images, it asks again without.
    A window smaller than the setting is remembered and the pages nearest `page` are picked again to fit it."""
    page = min(max(page, 0), max(len(pages) - 1, 0))
    paper, keep = paper_text(s, pages, page, system + question + title)
    start = time.perf_counter()
    prompt = f"Paper: {title}\n\n<paper>\n{paper}\n</paper>\n\n{question}"
    content: Any = [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": image}}] if image else prompt
    before = window(s)
    try:
        text = chat(s, [{"role": "system", "content": system + persona(s)}, {"role": "user", "content": content}], trim=_again)
    except ModelError as e:
        if window(s) < before:  # the loaded window is smaller than the setting: ask again with the pages that fit it
            return _answer(s, system, question, title, pages, page, image, _again=True)  # cut to fit if still too long
        if image and e.status in (400, 415, 422, 500, 501):  # a text-only model: ask without the picture
            return _answer(s, system, question, title, pages, page, _again=_again)
        return {"ok": False, "error": str(e)}
    return {"ok": True, "text": text, "pages": [keep[0] + 1, keep[-1] + 1] if keep else [],
            "whole": len(keep) == len(pages), "total": len(pages), "seconds": round(time.perf_counter() - start, 1)}


def explain(s: Settings, words: str, title: str, pages: list[str], page: int, image: str | None = None,
            near: tuple[str, str] = ("", "")) -> dict[str, Any]:
    """Explain marked words with the whole paper as context (or as much as fits the budget), and a picture of them if given."""
    page = min(max(page, 0), max(len(pages) - 1, 0))
    if _formula(words):
        setup = (f"The paper just before it: \"{near[0]}\"\n" if near[0] else "") + (f"The paper just after it: \"{near[1]}\"\n" if near[1] else "")
        question = f'{setup}The formula I marked on page {page + 1}: "{words}"\nTake it apart term by term, then simplify it.'
        got = _answer(s, FORMULA_SYSTEM, question, title, pages, page, image)
        return {**got, "text": _no_loops(got["text"])} if got.get("ok") and got.get("text") else got
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
    if m := re.search(r"(?im)^\s*@ai\b[\s:,-]*(.*)$", question):  # "@ai" may start any line of the entry
        question = m[1].strip() or "Explain this part in simple words."
    earlier = "".join(f"{'Student' if e['who'] == 'me' else 'Dot'}: {e['text'][:1000]}\n" for e in lines[:last])
    q = (f'The note is about this part of page {page + 1}:\n"""\n{boxed_text[:3000]}\n"""\n' if boxed_text else f"I am looking at page {page + 1}.\n")
    q += (f"The note so far:\n{earlier}\n" if earlier else "") + f"My question: {question}"
    return _answer(s, NOTE_SYSTEM, q, title, pages, page, image)


HIGHLIGHT_SYSTEM = (
    "You help a student read a research paper. You get one part of a page. Pick only the most important parts "
    "the student should remember (a key claim, a definition, a main result). Copy each one word for word from the "
    "text. Give at most {most}, each at most 25 words, never a whole paragraph. Look through the whole text, from its "
    "first sentence to its last, not only the start. "
    'Reply with JSON only: {{"quotes": ["..."]}}.'
)
_QUOTES = {"type": "object", "properties": {"quotes": {"type": "array", "items": {"type": "string"}}},
           "required": ["quotes"], "additionalProperties": False}


def pick_quotes(s: Settings, text: str, title: str, focus: str = "") -> list[str]:
    """Quotes worth highlighting in `text`, about `focus` if the student said what to look for. Raises
    primer.PrimerError for the user; broken JSON is asked twice, then []."""
    from . import primer  # primer imports this module
    most = max(2, min(6, len(re.findall(r"[.!?](?:\s|$)", text)) // 2 + 1))  # a long paragraph gets more than a short one
    want = (f"\n\nThe student wants you to highlight: {focus}\nPick only parts about that. If nothing in the text "
            'is about it, reply {"quotes": []}.') if focus else ""
    msgs = [{"role": "system", "content": HIGHLIGHT_SYSTEM.format(most=most)},
            {"role": "user", "content": f"Paper: {title}\n\nText:\n\"\"\"\n{text[:6000]}\n\"\"\"{want}"}]
    for _ in range(2):
        try:
            reply = primer._complete(s, msgs, _QUOTES, "quotes")
            out = json.loads(reply[reply.find("{"):reply.rfind("}") + 1])["quotes"]  # some models wrap the JSON in words or fences
            out = [out] if isinstance(out, str) else out  # one quote as a plain string, not a list of letters
            return [q.strip() for q in out if isinstance(q, str) and len(q.split()) >= 3][:most]
        except (ValueError, KeyError, TypeError):
            continue
    return []


SOURCES_SYSTEM = (
    "You help a student read a research paper. Do exactly what the student asks, from the paragraphs you are given, in "
    "simple English. The request may be an instruction, not a question: \"simplify this\", \"go term by term\", "
    "\"in more detail\", \"give an example\". Then do that to the part they selected, or to the earlier answer if they "
    "selected nothing. Never answer an instruction with \"Yes\" or by repeating the earlier answer: a follow-up must add something new. Simplify means everyday words with no symbols, subscripts or LaTeX, and one small example. Elaborate means explain each part and why it is there. Term by term means "
    "one short line per symbol or term: what it stands for and why it is there. Keep a plain question to at most 6 "
    "short sentences; when they ask for detail or steps, use up to 14 short lines. Say what this paper says, in its "
    "own terms, not general knowledge. If the paragraphs do not answer it, say so in one sentence. Each paragraph has an id like p3-b7. As sources, name the ids of the "
    "paragraphs your answer uses, best first, at most 4, each paragraph once. For each one write a gist: what that "
    "paragraph says, in your own plain words, at most 12 words. Never copy a formula or symbols into a gist (formulas "
    "look jumbled after copying out of the PDF); say what the formula is for instead. "
    'Return JSON only: {"answer": "...", "sources": [{"block": "p3-b7", "gist": "..."}]}.'
)

_STOP = {"this", "that", "with", "from", "their", "they", "them", "these", "those", "which", "what", "when", "where",
         "have", "been", "were", "will", "would", "could", "should", "about", "into", "than", "then", "also", "such",
         "more", "most", "some", "other", "paper", "page", "does", "each", "only", "very", "much", "many", "there"}


def _stems(text: str) -> set[str]:
    """Content words cut to 6 letters, so "randomness" and "random" meet."""
    return {w[:6] for w in re.findall(r"[a-z]{4,}", text.lower()) if w not in _STOP}


def _readable(text: str) -> bool:
    """Mostly plain words? Formulas copied out of a PDF are not ("F1(f, D) := 2TP P+ PP=")."""
    toks = text.split()
    word = re.compile(r"\(?(?:[A-Za-z][A-Za-z'-]*|\d+(?:\.\d+)?%?)[.,;:!?)]*")
    return bool(toks) and sum(bool(word.fullmatch(t)) for t in toks) >= 0.75 * len(toks)


def _short(text: str, most: int = 14) -> str:
    words = text.split()
    return " ".join(words[:most]) + ("..." if len(words) > most else "")


def _block_id(b: Any) -> str:
    """The model's id in our form: "P3_B7", "p3 - b7" and "p3-b7 (page 3)" all mean p3-b7."""
    m = re.search(r"p\s*(\d+)\s*[-_ ]?\s*b\s*(\d+)", str(b), re.I)
    return f"p{m[1]}-b{m[2]}" if m else str(b).strip()


def _best_sentence(answer: str, para: str) -> tuple[int, str]:
    """The answer sentence that shares the most words with a paragraph, and how many it shares."""
    p = _stems(para)
    return max(((len(_stems(x) & p), x) for x in re.split(r"(?<=[.!?])\s+", answer) if x.strip()), default=(0, ""))


def _gist(gist: str, answer: str, page: int, para: str) -> str:
    """A short readable line for a source card. A copied formula is swapped for words."""
    gist = " ".join(gist.split())
    if gist and _readable(gist):
        return _short(gist, 16)
    hit, sent = _best_sentence(answer, para)
    if hit >= 2:
        return _short(sent)
    return _short(para) if _readable(para) else f"A formula on page {page}"


def _match(answer: str, paras: list[tuple[str, int, list[float], str]], most: int = 4) -> list[dict[str, Any]]:
    """When the model names no usable paragraph: the paragraphs the answer's sentences clearly come from."""
    stems = {p[0]: _stems(p[3]) for p in paras}
    out: list[dict[str, Any]] = []
    for sent in re.split(r"(?<=[.!?])\s+", answer) if paras else []:
        sw = _stems(sent)
        if len(sw) < 4:
            continue
        best = max(paras, key=lambda p: len(sw & stems[p[0]]))
        hit = len(sw & stems[best[0]])
        if hit >= 3 and hit >= 0.4 * len(sw):
            out.append({"block": best[0], "page": best[1], "rect": best[2], "gist": _short(sent)})
    return out[:most]


def _dedupe(src: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One card per paragraph, and none that says the same as another on its page."""
    def same(a: str, b: str) -> bool:
        x, y = _stems(a), _stems(b)
        return bool(x | y) and len(x & y) >= 0.6 * len(x | y)
    out: list[dict[str, Any]] = []
    for x in src:
        if not any(o["block"] == x["block"] or (o["page"] == x["page"] and same(o["gist"], x["gist"])) for o in out):
            out.append(x)
    return out


def _fit(s: Settings, paras: list[tuple[str, int, list[float], str]], overhead: str) -> list[tuple[str, int, list[float], str]]:
    """The paragraphs that fit the context budget, taken in the order given (best pages first), then in page order."""
    room = int((window(s) - reply_tokens(s) - context.tokens(overhead) - 300) * context.CHARS_PER_TOKEN)
    out, used = [], 0
    for p in paras:
        used += len(p[3][:1500]) + 24
        if used > room and out:
            break
        out.append(p)
    return sorted(out, key=lambda p: p[1])  # stable: paragraphs keep their order inside a page


def ask_with_sources(s: Settings, question: str, title: str, paras: list[tuple[str, int, list[float], str]],
                     earlier: str = "") -> dict[str, Any]:
    """Answer and name the paragraphs that back it up. Each para is (id, page, rect, text), best pages first."""
    from pydantic import BaseModel, ValidationError

    from . import primer

    class Src(BaseModel):
        block: str | int
        gist: str = ""

    class Reply(BaseModel):
        answer: str
        sources: list[Src | str] | None = None

    had = len(paras)
    paras = _fit(s, paras, SOURCES_SYSTEM + title + earlier + question)
    by = {p[0]: p for p in paras}
    trace = [f"{len(paras)} paragraphs fit the model" + (f" ({had - len(paras)} cut for room)" if had > len(paras) else "")]
    schema = {"type": "object", "required": ["answer", "sources"], "properties": {
        "answer": {"type": "string"},
        "sources": {"type": "array", "items": {"type": "object", "required": ["block", "gist"], "properties": {
            "block": {"type": "string", "enum": list(by)}, "gist": {"type": "string"}}}}}}
    listing = "\n\n".join(f"{i} (page {pg}): {t[:1500]}" for i, pg, _, t in paras)
    messages = [{"role": "system", "content": SOURCES_SYSTEM + persona(s)},
                {"role": "user", "content": f"Paper: {title}\n\n<paragraphs>\n{listing}\n</paragraphs>\n\n"
                                            f"{earlier}My question: {question}\n\nReturn the JSON."}]
    try:
        for _ in range(2):
            reply = primer._complete(s, messages, schema, "sources")
            a, b = reply.find("{"), reply.rfind("}")
            try:
                out = Reply.model_validate_json(reply[a:b + 1] if a >= 0 else reply)
            except ValidationError as e:
                trace.append("reply was not valid JSON, asked again")
                messages += [{"role": "assistant", "content": reply},
                             {"role": "user", "content": f"That answer was not valid: {str(e)[:300]}\nReturn only JSON."}]
                continue
            text = out.answer.strip()
            named = [Src(block=x) if isinstance(x, str) else x for x in out.sources or []]
            src = [{"block": k, "page": by[k][1], "rect": by[k][2], "gist": _gist(x.gist, text, by[k][1], by[k][3])}
                   for x in named if (k := _block_id(x.block)) in by]
            trace.append(f"model named {len(src)} of its sources" if src else "model named no valid paragraph, matched by shared words")
            return {"ok": True, "text": text, "sources": _dedupe(src or _match(text, paras))[:4], "trace": trace}
    except primer.PrimerError as e:
        return {"ok": False, "error": str(e), "trace": trace + [f"model error: {str(e)[:120]}"]}
    trace.append("JSON failed twice, plain answer, matched by shared words")
    pages = [""] * max(p[1] for p in paras)  # paragraph text by page, for the plain answer
    for _, pg, _, t in paras:
        pages[pg - 1] += t + "\n\n"
    plain = ask(s, earlier + question, title, pages, min(p[1] for p in paras) - 1)
    return {**plain, "sources": _dedupe(_match(plain["text"], paras)) if plain["ok"] else [], "trace": trace}
