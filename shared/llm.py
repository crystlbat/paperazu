"""Talk to the Unsloth (llama-server) OpenAI-compatible endpoint."""
import json
import os
import re
import shlex
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

from openai import APIConnectionError, APIError, APIStatusError, AuthenticationError, OpenAI

from shared import context, db, steer
from shared.settings import Settings

STEER = "steer (mlx)"  # the model name that means the steer engine: Qwen3.5-4B in this process, its hidden states read and steered
MLX = "mlx:"  # "mlx:<repo>": any other local MLX model, run in this process like the steer engine, with concepts fitted on it


def is_steer(model: str) -> bool:
    """In-process MLX: the steer engine or another local MLX model."""
    return model == STEER or model.startswith(MLX)


def _mlx_name(model: str) -> str:
    return steer.MODEL if model == STEER else model.removeprefix(MLX)


def mlx_loaded() -> str:
    """The model name of the in-process MLX model now loaded (the steer engine if none)."""
    return STEER if steer.current() == steer.MODEL else MLX + steer.current()


def client(s: Settings, timeout: float | None = None, base_url: str | None = None) -> OpenAI:
    return OpenAI(base_url=base_url or s.base_url, api_key=s.api_key or "none",
                  timeout=timeout or s.timeout_s, max_retries=0)


def model_status(s: Settings) -> dict[str, Any]:
    got = _model_status(s)
    if steer.available():  # always on offer: it needs no server
        got["models"] = [*got["models"], STEER, *dict.fromkeys(m for m in (s.model_name, s.chat_model) if m.startswith(MLX))]
        if is_steer(s.model_name):
            got.update(status="ready", label=("steer engine" if s.model_name == STEER else s.model_name) + (" loaded" if steer.loaded() else " (loads when needed)"))
    return got


def _model_status(s: Settings) -> dict[str, Any]:
    if is_dory(s, s.model_name):  # the dory engine starts on first use, so it counts as ready while Unsloth or its command is there
        try:
            models = [m.id for m in client(s, timeout=5).models.list()]
        except APIError:
            models = []
        return {"status": "ready", "label": "dory engine" + (" running" if _up(s.dory_url, 2) else " (starts when needed)"), "models": [DORY, *models]}
    try:
        models = [m.id for m in client(s, timeout=5).models.list()]
        models += [DORY] if s.dory_cmd.strip() else []
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
        m = pick_model(s) or "default"
        _engine_for(s, m)
        r = client(s, timeout=min(s.timeout_s, 60), base_url=url_for(s, m)).chat.completions.create(
            model=m,
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


DORY = "dory"  # the model name that means the dory engine, as its llama-server is started with --alias dory
_dory: dict[str, Any] = {"proc": None}  # the dory llama-server this app started, so only that one is stopped
# shortcut: dory is started by name from the dory_cmd setting, beside the engine presets; fold the start command into a llama.cpp engine's values when a second such server appears


def is_dory(s: Settings, model: str) -> bool:
    return bool(s.dory_cmd.strip()) and model == DORY


def url_for(s: Settings, model: str) -> str:
    """The server that runs `model`: the dory engine for dory, the settings' server for the rest."""
    return s.dory_url if is_dory(s, model) else s.base_url


def _up(url: str, timeout: float = 3) -> bool:
    try:
        with urllib.request.urlopen(f"{url.rstrip('/')}/models", timeout=timeout):  # noqa: S310 — the user's own server
            return True
    except Exception:
        return False


def _dory_ours() -> bool:
    p = _dory["proc"]
    return p is not None and p.poll() is None


def stop_dory() -> bool:
    """Stop the dory llama-server this app started (never one you started yourself). True if one was stopped."""
    p, _dory["proc"] = _dory["proc"], None
    if p is None or p.poll() is not None:
        return False
    p.terminate()
    try:
        p.wait(timeout=15)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait(timeout=5)
    return True


def _to_dory(s: Settings, timeout: float, poll: float) -> dict[str, Any] | None:
    """The dory engine on: Unsloth's model unloaded to free the memory, the dory llama-server started, waited on until it answers."""
    if _up(s.dory_url):
        return None
    t0, cur, ok, why = time.time(), "", False, "timed out"
    SWAP.update(busy=True, **{"from": "unsloth"}, to=DORY, phase="unloading", fraction=0.0, started=time.strftime("%H:%M:%S"))
    try:
        st = _api(s, "GET", "status")
        cur = (st.get("active_model") or "") if isinstance(st, dict) else ""
        if cur:
            _api(s, "POST", "unload", {"model_path": cur}, timeout=timeout)
    except Exception:
        pass  # Unsloth down or busy: dory may still fit
    SWAP["phase"] = "loading"
    try:
        db.DATA_DIR.mkdir(parents=True, exist_ok=True)
        log = open(db.DATA_DIR / "dory.log", "ab")  # noqa: SIM115 — the child keeps it open
        _dory["proc"] = subprocess.Popen(shlex.split(os.path.expanduser(s.dory_cmd)), stdout=log, stderr=subprocess.STDOUT)  # same process group: killed with the app even when it gets no clean shutdown
        while time.time() - t0 < timeout:
            if _up(s.dory_url):
                ok = True
                break
            if not _dory_ours():
                why = "the dory server exited: see data/dory.log"
                break
            time.sleep(poll)
    except Exception as e:
        why = str(e)[:120]
    if not ok:
        stop_dory()
        if cur:  # put Unsloth's model back rather than leave both engines empty
            try:
                _api(s, "POST", "load", {"model_path": cur}, timeout=timeout)
                why += f"; {cur} loaded back"
            except Exception as e:
                why += f"; could not load {cur} back: {str(e)[:80]}"
    secs = round(time.time() - t0, 1)
    SWAP.update(busy=False, phase="ready" if ok else "failed", fraction=1.0 if ok else 0.0)
    on_engine("model", "ok" if ok else "failed", f"unsloth ({cur or 'nothing'}) → dory engine in {secs:.0f}s" + ("" if ok else f" ({why})"))
    return {"from": cur or "unsloth", "to": DORY, "seconds": secs, "ok": ok}


def _engine_for(s: Settings, model: str) -> None:
    """Before a call: swap engines only when the call crosses them (dory wanted and not up, or a server model while our dory or an MLX model runs)."""
    if (is_dory(s, model) and not (_dory_ours() or _up(s.dory_url, 1))) or (not is_dory(s, model) and _dory_ours()) or steer.loaded():
        ensure(s, model)


def _to_mlx(s: Settings, model: str, timeout: float) -> dict[str, Any] | None:
    """The in-process MLX model on, one model in memory at a time: another MLX model, our dory and Unsloth's model out first."""
    if steer._M.get("name") == _mlx_name(model):
        return None
    t0, cur = time.time(), ""
    if steer.unload():
        cur = "mlx"
    SWAP.update(busy=True, **{"from": "unsloth"}, to=model, phase="unloading", fraction=0.0, started=time.strftime("%H:%M:%S"))
    if stop_dory():
        cur = DORY
    try:
        st = _api(s, "GET", "status")
        if isinstance(st, dict) and (cur := st.get("active_model") or cur) and cur != DORY:
            _api(s, "POST", "unload", {"model_path": cur}, timeout=timeout)
    except Exception:
        pass  # Unsloth down: nothing of it to unload
    SWAP["phase"] = "loading"
    try:
        steer.load(_mlx_name(model))
        ok, why = True, ""
    except Exception as e:
        ok, why = False, f" ({str(e)[:120]})"
    secs = round(time.time() - t0, 1)
    SWAP.update(busy=False, phase="ready" if ok else "failed", fraction=1.0 if ok else 0.0)
    _picked.clear()
    on_engine("model", "ok" if ok else "failed", f"{cur or 'nothing'} → {'steer engine' if model == STEER else model} in {secs:.0f}s{why}")
    return {"from": cur, "to": model, "seconds": secs, "ok": ok}


def ensure(s: Settings, model: str, timeout: float = 600, poll: float = 1.0) -> dict[str, Any] | None:
    """Make `model` the one that runs, on its engine. An MLX model: in this process, everything else out first. dory: Unsloth's
    model out, the dory llama-server up. Any other: the dory server this app started stopped, then in Unsloth the current model
    unloaded and this one loaded, polled until active. None when nothing had to change.
    Every swap (and every skip) is a "model" engine row: from, to, seconds, ok/failed."""
    if not model:
        return None
    with _swap_lock:
        if is_steer(model):
            return _to_mlx(s, model, timeout)
        if steer.unload():  # leaving the steer engine: its model out of memory before another loads
            on_engine("model", "ok", "steer engine unloaded")
        if is_dory(s, model):
            return _to_dory(s, timeout, poll)
        if stop_dory():  # the two engines do not share the memory: dory leaves before Unsloth loads
            on_engine("model", "ok", "dory engine stopped for Unsloth")
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
        if not ok and cur:  # the old one is already unloaded: put it back, or the server is left with no model at all
            try:
                _api(s, "POST", "load", {"model_path": cur}, timeout=timeout)
                why += f"; {cur} loaded back"
            except Exception as e:
                why += f"; could not load {cur} back: {str(e)[:80]}"
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
    if is_steer(s.model_name):  # in-process, with the concept vectors the harness set for this step (none outside its executor)
        name = _mlx_name(s.model_name)
        if steer._M.get("name") != name:
            ensure(s, s.model_name)  # the other engines' models out first
        try:
            text = _strip_thinking(steer.generate(messages, steer.ON, name=name, max_tokens=max_tokens or s.max_output_tokens,
                                                  temp=s.temperature if temperature is None else temperature))
        except Exception as e:
            raise ModelError(f"The steer engine failed: {str(e)[:200]}")
        if not text:
            raise ModelError(ROOM if text is None else "The model gave an empty answer. Try again.")
        if watch is not None and not watch(text):
            raise ModelError("Stopped.")
        return text
    out = reply_tokens(s, max_tokens)
    if trim:
        learned = _windows.get((s.base_url, s.model_name))
        messages = _trim(messages, window(s) - out - 64, min(context.CHARS_PER_TOKEN, learned[2] if learned else 99))
    extra: dict[str, Any] = {"response_format": response_format} if response_format else {}
    try:
        m = pick_model(s) or "default"
        _engine_for(s, m)
        r = client(s, base_url=url_for(s, m)).chat.completions.create(
            model=m, messages=messages, max_tokens=out,  # type: ignore[arg-type]
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
