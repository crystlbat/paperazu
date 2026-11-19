"""The context-window check reads what the local server reports. It never sends the paper."""
import json
import urllib.error
from io import BytesIO

from shared import llm
from shared.settings import Settings

S = Settings(base_url="http://127.0.0.1:9/v1", api_key="k", max_context_tokens=32768)


class _Body:
    def __init__(self, payload: object) -> None:
        self.raw = json.dumps(payload).encode()

    def read(self) -> bytes:
        return self.raw

    def __enter__(self) -> "_Body":
        return self

    def __exit__(self, *a: object) -> bool:
        return False


def _pages(monkeypatch, pages: dict[str, object], down: set[str] | None = None) -> None:
    missing = down or set()

    def fake(req: object, timeout: float = 5) -> _Body:
        url = str(getattr(req, "full_url", req))
        name = url.rsplit("/", 1)[-1]
        if name in missing:
            raise urllib.error.URLError("nope")
        if name not in pages:
            raise urllib.error.HTTPError(url, 404, "missing", {}, BytesIO(b""))
        return _Body(pages[name])

    monkeypatch.setattr(llm.urllib.request, "urlopen", fake)


def test_unsloth_reports_the_loaded_models_context_length(monkeypatch) -> None:
    _pages(monkeypatch, {"models": {"data": [
        {"id": "other", "loaded": False},
        {"id": "LiquidAI/LFM3-Omni-2B-GGUF", "loaded": True, "context_length": 52992, "native_context_length": 128000},
    ]}})
    out = llm.context_window(S)
    assert out["ok"] and out["kind"] == "running" and out["tokens"] == 52992


def test_a_running_window_beats_the_trained_size(monkeypatch) -> None:
    _pages(monkeypatch, {
        "models": {"data": [{"meta": {"n_ctx_train": 131072}}]},
        "props": {"default_generation_settings": {"n_ctx": 8192}},
    })
    out = llm.context_window(S)
    assert out == {"ok": True, "tokens": 8192, "kind": "running", "saved": 32768}


def test_only_the_trained_size_is_labelled_as_such(monkeypatch) -> None:
    _pages(monkeypatch, {"models": {"data": [{"meta": {"n_ctx_train": 131072}}]}})
    out = llm.context_window(S)
    assert out["ok"] and out["kind"] == "trained" and out["tokens"] == 131072


def test_a_slot_answers_when_props_does_not(monkeypatch) -> None:
    _pages(monkeypatch, {"models": {"data": [{}]}, "slots": [{"id": 0, "n_ctx": 4096}]}, down={"props"})
    out = llm.context_window(S)
    assert out["tokens"] == 4096 and out["kind"] == "running"


def test_a_refused_models_list_still_reads_props(monkeypatch) -> None:
    def fake(req: object, timeout: float = 5) -> _Body:
        url = str(getattr(req, "full_url", req))
        if url.endswith("/models"):
            raise urllib.error.HTTPError(url, 401, "no", {}, BytesIO(b""))
        if url.endswith("/props"):
            return _Body({"default_generation_settings": {"n_ctx": 65536}})
        raise urllib.error.HTTPError(url, 404, "missing", {}, BytesIO(b""))

    monkeypatch.setattr(llm.urllib.request, "urlopen", fake)
    out = llm.context_window(S)
    assert out["tokens"] == 65536 and out["kind"] == "running"


def test_a_dead_server_is_a_clear_error(monkeypatch) -> None:
    _pages(monkeypatch, {}, down={"models", "props", "slots"})
    assert llm.context_window(S) == {"ok": False, "error": "Could not reach the model server. Is Unsloth running?"}


def test_a_refused_key_is_a_clear_error(monkeypatch) -> None:
    def fake(req: object, timeout: float = 5) -> _Body:
        raise urllib.error.HTTPError(str(req), 401, "no", {}, BytesIO(b""))

    monkeypatch.setattr(llm.urllib.request, "urlopen", fake)
    assert llm.context_window(S) == {"ok": False, "error": "Wrong API key."}
