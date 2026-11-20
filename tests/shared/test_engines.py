"""Engines: named model setups on Model connection. Picking one writes its URL, key and models into the live
settings; edits to the one in use stay with it; switching waits for swaps and model work; keys never go to the page."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app as main
from shared import db, engines, llm, settings


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(db, "PAPERS_DIR", tmp_path / "papers")
    monkeypatch.setattr(settings, "read_env", lambda *a: {})
    db.init()
    settings.update({"base_url": "http://127.0.0.1:8080/v1", "model_name": "dory", "api_key": "sk-secret", "max_context_tokens": 64640})
    # Unsloth answers with two models, one loaded; Dory's server is down
    def client(s, timeout=None):
        if "8080" in s.base_url:
            raise llm.APIConnectionError(request=SimpleNamespace(method="GET", url=s.base_url))  # type: ignore[arg-type]
        models = [SimpleNamespace(id="qwen", loaded=True), SimpleNamespace(id="gemma", loaded=False)]
        return SimpleNamespace(models=SimpleNamespace(list=lambda: models))
    monkeypatch.setattr(llm, "client", client)
    monkeypatch.setattr(llm, "busy", [])


def test_the_first_engines_are_this_macs_and_the_live_one_keeps_what_was_typed():
    r = TestClient(main.app).get("/settings/engines").json()
    by = {e["id"]: e for e in r["engines"]}
    assert r["active"] == "dory" and set(by) == {"dory", "unsloth"}
    assert by["dory"]["values"]["max_context_tokens"] == 64640 and by["dory"]["status"] == "not_running"
    assert by["unsloth"]["status"] == "ready" and by["unsloth"]["loaded"] == ["qwen"] and by["unsloth"]["models"] == ["qwen", "gemma"]
    assert "sk-secret" not in str(r) and by["unsloth"]["has_key"]  # the key stays on the server


def test_picking_an_engine_loads_its_values_and_clears_the_other_servers_models():
    c = TestClient(main.app)
    settings.update({"planner_model": "big-planner"})  # set while Dory is in use: Dory keeps it
    r = c.post("/settings/engines/unsloth/use").json()
    s = settings.get_all()
    assert (s.base_url, s.model_name, s.planner_model, s.engine) == ("http://127.0.0.1:8888/v1", "", "", "unsloth")
    assert "Dory keeps its model in memory" in r["note"]
    settings.update({"model_name": "qwen"})  # edits follow the engine in use
    c.post("/settings/engines/dory/use")
    s = settings.get_all()
    assert (s.base_url, s.model_name, s.planner_model, s.max_context_tokens) == ("http://127.0.0.1:8080/v1", "dory", "big-planner", 64640)
    c.post("/settings/engines/unsloth/use")
    assert settings.get_all().model_name == "qwen"


def test_switching_waits_for_a_swap_and_for_model_work(monkeypatch):
    c = TestClient(main.app)
    with llm._swap_lock:
        r = c.post("/settings/engines/unsloth/use")
    assert r.status_code == 409 and "swap" in r.json()["detail"]
    llm.busy.append(lambda: "A mind map is being made.")
    assert c.post("/settings/engines/unsloth/use").json()["detail"] == "A mind map is being made."
    assert settings.get_all().engine == "dory" and c.post("/settings/engines/nope/use").status_code == 404


def test_a_new_engine_can_be_added_changed_and_removed():
    c = TestClient(main.app)
    e = c.post("/settings/engines", json={"name": "Steer (MLX)", "kind": "openai", "values": {"base_url": "http://127.0.0.1:9090/v1", "api_key": "k2"}}).json()
    assert e["id"] == "steer-mlx" and e["has_key"] and "api_key" not in e["values"]
    c.post("/settings/engines", json={"id": "steer-mlx", "name": "Steer", "kind": "openai", "values": {"base_url": "http://127.0.0.1:9091/v1", "api_key": ""}})
    kept = next(x for x in settings.get_all().engines if x["id"] == "steer-mlx")
    assert kept["values"] == {"base_url": "http://127.0.0.1:9091/v1", "api_key": "k2"}  # an empty key keeps the old one
    assert c.post("/settings/engines", json={"name": "Bad", "values": {"base_url": "ftp://x"}}).status_code == 422
    assert c.post("/settings/engines", json={"name": "Bad", "values": {"temperature": 1}}).status_code == 422
    assert c.post("/settings/engines", json={"name": "No URL", "values": {}}).status_code == 422
    assert c.delete("/settings/engines/dory").status_code == 409  # in use
    assert c.delete("/settings/engines/steer-mlx").json() == {"ok": True} and c.delete("/settings/engines/steer-mlx").status_code == 404


def test_settings_pointing_elsewhere_become_an_engine_of_their_own():
    settings.update({"base_url": "http://10.0.0.5:1234/v1"})
    r = TestClient(main.app).get("/settings/engines").json()
    assert r["active"] == "mine" and {e["id"] for e in r["engines"]} == {"dory", "unsloth", "mine"}
