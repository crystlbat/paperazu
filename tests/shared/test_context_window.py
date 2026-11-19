from fastapi.testclient import TestClient

from shared import llm
import app as main
from shared.settings import Settings


def test_context_window_prefers_the_loaded_window(monkeypatch) -> None:
    def fetch(url, key, timeout):
        assert key == "" and timeout == 5
        if url.endswith("/models"):
            return "ok", {"data": [{"id": "m", "meta": {"n_ctx": 8192, "n_ctx_train": 32768}}]}
        raise AssertionError(url)

    monkeypatch.setattr(llm, "_fetch", fetch)
    out = llm.context_window(Settings(base_url="http://127.0.0.1:9/v1", max_context_tokens=32768))
    assert out == {"ok": True, "tokens": 8192, "kind": "running", "saved": 32768}


def test_context_window_reads_props_when_models_say_nothing(monkeypatch) -> None:
    def fetch(url, key, timeout):
        if url.endswith("/props"):
            return "ok", {"default_generation_settings": {"n_ctx": 4096}}
        return "miss", None

    monkeypatch.setattr(llm, "_fetch", fetch)
    assert llm.context_window(Settings(base_url="http://127.0.0.1:9/v1"))["tokens"] == 4096


def test_context_window_when_the_server_is_down(monkeypatch) -> None:
    monkeypatch.setattr(llm, "_fetch", lambda *a: ("down", None))
    out = llm.context_window(Settings())
    assert out == {"ok": False, "error": "Could not reach the model server. Is Unsloth running?"}


def test_context_window_when_the_server_says_nothing(monkeypatch) -> None:
    monkeypatch.setattr(llm, "_fetch", lambda *a: ("ok", {"data": []}))
    out = llm.context_window(Settings())
    assert out["ok"] is False and "context window" in out["error"]


def test_check_context_route(tmp_path, monkeypatch) -> None:
    from shared import db
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(db, "PAPERS_DIR", tmp_path / "papers")
    db.init()
    monkeypatch.setattr(llm, "context_window", lambda s: {"ok": True, "tokens": 8192, "saved": s.max_context_tokens})
    r = TestClient(main.app).post("/settings/check-context")
    assert r.status_code == 200 and r.json()["tokens"] == 8192
