"""Talk to the Unsloth (llama-server) OpenAI-compatible endpoint."""
import json
import re
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

from openai import APIConnectionError, APIError, APIStatusError, AuthenticationError, OpenAI

from shared import context
from shared.settings import Settings


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
# who hears about each model swap: (kind, outcome, detail). harness_char sets it to char._engine.
on_engine: Callable[[str, str, str], None] = lambda kind, outcome, detail="": None
_swap_lock = threading.Lock()  # one model at a time, process wide
# each part of the app that can be in the middle of model work adds a check here: () -> why switching engines now would
# hurt it, or "". The engine switcher asks them all, so a new part only has to add its own.
busy: list[Callable[[], str]] = []


def swap_locked() -> bool:
    return _swap_lock.locked()


def forget() -> None:
    """Drop what was learned about the server, after the settings point at another one."""
    _picked.clear()


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
    if not model:
        return None
    with _swap_lock:
        try:
            st = _api(s, "GET", "status")
        except Exception as e:
            on_engine("model", "skipped", f"status unreachable: {e}")
            return None
        if not isinstance(st, dict) or "active_model" not in st or not isinstance(st.get("loaded"), list):
            on_engine("model", "skipped", "unknown status shape")
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
        on_engine("model", "ok" if ok else "failed", f"{cur or 'nothing'} → {model} in {secs:.0f}s" + ("" if ok else f" ({why})"))
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


# thinking models (Gemma 4, Qwen 3) spend the whole reply budget reasoning on short structured jobs; servers that
# do not know the switch ignore it
NO_THINK = {"chat_template_kwargs": {"enable_thinking": False}}


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


def _gather(stream: Any, watch: Callable[[str], bool]) -> Any:
    """A streamed reply put back together in the shape of a whole one, stopping when watch says so."""
    parts: list[str] = []
    finish = None
    try:
        for chunk in stream:
            if not chunk.choices:
                continue
            c = chunk.choices[0]
            parts.append(getattr(c.delta, "content", None) or "")
            finish = c.finish_reason or finish
            if not watch("".join(parts)):
                raise ModelError("Stopped.")
    finally:
        stream.close()  # a stop closes the connection, and the model server stops writing
    msg = SimpleNamespace(content="".join(parts))
    return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason=finish)])


def chat(s: Settings, messages: list[dict[str, Any]], *, max_tokens: int | None = None, temperature: float | None = None,
         response_format: dict[str, Any] | None = None, trim: bool = True, _again: bool = False,
         watch: Callable[[str], bool] | None = None) -> str:
    """One reply from the local model with thinking removed. Every model call in the app goes through here.

    A request longer than the window is cut in its longest message first. When the server says its loaded
    window is smaller than the setting, that window is remembered and (with `trim`) the request is cut and sent
    once more. With `watch`, the reply streams in and watch(text so far) is called as it grows: it can show progress, and
    returning False stops the model at once (the connection closes) with ModelError("Stopped."). Raises ModelError."""
    out = reply_tokens(s, max_tokens)
    if trim:
        learned = _windows.get((s.base_url, s.model_name))
        messages = _trim(messages, window(s) - out - 64, min(context.CHARS_PER_TOKEN, learned[2] if learned else 99))
    extra: dict[str, Any] = {"response_format": response_format} if response_format else {}
    try:
        r = client(s).chat.completions.create(
            model=pick_model(s) or "default", messages=messages, max_tokens=out,  # type: ignore[arg-type]
            temperature=s.temperature if temperature is None else temperature, extra_body=NO_THINK, stream=watch is not None, **extra)
        if watch is not None:
            r = _gather(r, watch)
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
                        temperature=temperature, response_format=response_format, _again=True, watch=watch)
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
