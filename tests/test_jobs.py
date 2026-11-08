"""Creatures: the routes the screen calls, and one run walked without a real model."""
import json
from types import SimpleNamespace

import pymupdf
import pytest
from fastapi.testclient import TestClient

from workbench import db, jobs, library, llm, main
from workbench.settings import Settings

STEP = {"scope": "page", "prompt": "Say the claim of this page.", "model": ""}


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(db, "PAPERS_DIR", tmp_path / "papers")
    jobs.pause.set()  # the worker must not take a run while a test is looking at it
    jobs._stopping.clear()
    db.init()


def _headed() -> str:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 80), "Introduction\nWe study fairness in machine learning models today.", fontsize=12)
    doc.new_page().insert_text((72, 80), "Method\nWe train one model and measure the gap carefully.", fontsize=12)
    doc.set_toc([[1, "Introduction", 1], [1, "Method", 2]])
    return library.create(doc.tobytes(), "h.pdf")


def _sentence() -> str:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 80), "The model finds this exact sentence here.", fontsize=12)
    return library.create(doc.tobytes(), "q.pdf")


def test_references_start_at_the_heading_not_the_top_of_the_page() -> None:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "8 Conclusion\nWe stop here.\nReferences\n[1] Ada Lovelace. 1843. Notes on the engine.\n[2] Alan Turing. 1950. Computing machinery.", fontsize=11)
    doc.new_page().insert_text((72, 72), "[3] Grace Hopper. 1952. The compiler.", fontsize=11)
    doc.set_toc([[1, "8 Conclusion", 1], [1, "References", 1]])
    pid = library.create(doc.tobytes(), "refs.pdf")
    chunks = dict(jobs._sections(pid))
    assert "We stop here" not in chunks["References"]
    assert "Ada Lovelace" in chunks["References"] and "Grace Hopper" in chunks["References"]
    units = jobs._units({"scope": "references", "prompt": "List them."}, [pid], None, None, "", "", pid)
    assert len(units) == 1 and "Alan Turing" in units[0].text and "We stop here" not in units[0].text


def test_references_are_copied_into_the_note_without_asking_the_model(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: object, **_k: object) -> str:
        raise AssertionError("model")

    monkeypatch.setattr(jobs, "complete", boom)
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "8 Conclusion\nWe stop here.\nReferences\n[1] Ada Lovelace. 1843. Notes on the engine.\n[2] Alan Turing. 1950. Computing machinery.", fontsize=11)
    doc.new_page().insert_text((72, 72), "[3] Grace Hopper. 1952. The compiler.", fontsize=11)
    doc.set_toc([[1, "8 Conclusion", 1], [1, "References", 1]])
    pid = library.create(doc.tobytes(), "refs.pdf")
    con = db.connect()
    con.execute("UPDATE papers SET note = ? WHERE id = ?", ("My own line.", pid))
    con.commit()
    con.close()
    with TestClient(main.app) as c:
        job = c.post("/jobs", json={"name": "Reference list", "output": "note", "steps": [
            {"scope": "references", "prompt": "List the papers.", "model": ""}]}).json()
        run = c.post(f"/jobs/{job['id']}/run", json={"paper_id": pid}).json()
        jobs.execute(run["id"])
        note = c.get(f"/papers/{pid}/note").json()["text"]
    assert note.startswith("My own line.")
    assert "[1] Ada Lovelace" in note and "[3] Grace Hopper" in note
    assert "We stop here" not in note


def test_a_note_creature_saves_the_papers_and_keeps_the_rest_of_the_note(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[int] = []

    def fake(s: Settings, messages: list[dict[str, str]]) -> str:
        seen.append(s.max_output_tokens)
        return "Ada Lovelace. 1843. Notes on the engine.\nAlan Turing. 1950. Computing machinery."

    monkeypatch.setattr(jobs, "complete", fake)
    pid = _headed()
    con = db.connect()
    con.execute("UPDATE papers SET note = ? WHERE id = ?", ("My own line.", pid))
    con.commit()
    con.close()
    body = {"name": "Reference list", "output": "note", "steps": [
        {"scope": "page", "prompt": "List the papers.", "model": ""}]}
    with TestClient(main.app) as c:
        job = c.post("/jobs", json=body).json()
        run = c.post(f"/jobs/{job['id']}/run", json={"paper_id": pid}).json()
        jobs.execute(run["id"])
        again = c.post(f"/jobs/{job['id']}/run", json={"paper_id": pid}).json()
        jobs.execute(again["id"])
        note = c.get(f"/papers/{pid}/note").json()["text"]
    assert seen[0] >= 4096
    assert note.startswith("My own line.")
    assert note.count("Ada Lovelace") == 1 and "Alan Turing" in note
    assert "Papers mentioned" in note


def test_starters_are_added_once_and_a_shape_can_be_deleted() -> None:
    with TestClient(main.app) as c:
        assert c.get("/jobs").json() == {"jobs": []}
        first = c.post("/jobs/starters").json()["jobs"]
        assert [j["name"] for j in first] == [j["name"] for j in jobs.STARTER_JOBS]
        brief = next(j for j in first if j["name"] == "Research brief")
        assert brief["template_id"] and brief["steps"][0]["scope"] == "template"
        again = c.post("/jobs/starters").json()["jobs"]
        assert [j["id"] for j in again] == [j["id"] for j in first]
        bad = c.post("/jobs", json={"name": "  ", "steps": [{"scope": "page", "prompt": "x", "model": ""}]})
        assert bad.status_code == 422 and "name" in bad.json()["detail"]["errors"][0]["message"]
        tpl = next(t for t in c.get("/templates").json()["templates"] if t["name"] == "Research brief")
        assert c.delete(f"/templates/{tpl['id']}").json() == {"ok": True}
        left = next(j for j in c.get("/jobs").json()["jobs"] if j["name"] == "Research brief")
        assert left["template_id"] is None


def test_a_run_walks_each_section_with_the_step_before(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake(s: Settings, messages: list[dict[str, str]]) -> str:
        calls.append((s.model_name, messages[1]["content"]))
        return f"out-{len(calls)}"

    monkeypatch.setattr(jobs, "complete", fake)
    pid = _headed()
    with TestClient(main.app) as c:
        job = c.post("/jobs", json={"name": "Outline", "steps": [
            {"scope": "page", "prompt": "Name the claim.", "model": "tiny-brain"},
            {"scope": "sections", "prompt": "Outline this section.", "model": ""},
        ]}).json()
        run = c.post(f"/jobs/{job['id']}/run", json={"paper_id": pid, "page": 1})
        assert run.status_code == 201
        jobs.execute(run.json()["id"])
        got = c.get(f"/runs/{run.json()['id']}").json()
    assert got["status"] == "done" and got["total"] == 3 and got["done"] == 3
    assert calls[0][0] == "tiny-brain" and "out-1" not in calls[0][1] and "fairness" in calls[0][1]
    assert calls[1][0] == "" and "out-1" in calls[1][1] and "fairness" in calls[1][1] and "gap" not in calls[1][1]
    assert "out-1" in calls[2][1] and "gap" in calls[2][1]
    assert got["result"]["sections"] == [["Introduction", "out-2"], ["Method", "out-3"]]


def test_queue_stops_duplicates_and_a_restart(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jobs, "complete", lambda *a, **k: "no")
    pid = _headed()
    with TestClient(main.app) as c:
        job = c.post("/jobs", json={"name": "One", "steps": [STEP]}).json()
        first = c.post(f"/jobs/{job['id']}/run", json={"paper_id": pid})
        again = c.post(f"/jobs/{job['id']}/run", json={"paper_id": pid})
        assert first.status_code == 201 and again.status_code == 200 and first.json()["id"] == again.json()["id"]
        assert c.post(f"/jobs/{job['id']}/run", json={}).status_code == 422
        assert c.post("/jobs/999/run", json={"paper_id": pid}).status_code == 422
        assert c.post(f"/runs/{first.json()['id']}/stop").json()["status"] == "stopped"
        jobs.execute(first.json()["id"])
        assert c.get(f"/runs/{first.json()['id']}").json()["status"] == "stopped"
        for i in range(jobs.MAX_QUEUED):
            other = c.post("/jobs", json={"name": f"Q{i}", "steps": [STEP]}).json()
            assert c.post(f"/jobs/{other['id']}/run", json={"paper_id": pid}).status_code == 201
        extra = c.post("/jobs", json={"name": "Too many", "steps": [STEP]}).json()
        full = c.post(f"/jobs/{extra['id']}/run", json={"paper_id": pid})
        assert full.status_code == 429 and full.json()["detail"] == "Too many jobs waiting."
        jobs.fail_interrupted()
        runs = c.get("/runs?limit=100").json()["runs"]
        assert sum(r["status"] == "failed" for r in runs) == jobs.MAX_QUEUED
        assert any(r["status"] == "stopped" for r in runs)
        assert all("restarted" in r["error"] for r in runs if r["status"] == "failed")


def test_a_failed_model_fails_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(s: Settings, messages: list[dict[str, str]]) -> str:
        raise RuntimeError("Could not reach the model. Is Unsloth running?")

    monkeypatch.setattr(jobs, "complete", boom)
    pid = _headed()
    with TestClient(main.app) as c:
        job = c.post("/jobs", json={"name": "Quiet", "steps": [STEP]}).json()
        run = c.post(f"/jobs/{job['id']}/run", json={"paper_id": pid}).json()
        jobs.execute(run["id"])
        got = c.get(f"/runs/{run['id']}").json()
    assert got["status"] == "failed" and "Unsloth" in got["error"]


def test_highlight_output_marks_a_real_quote(monkeypatch: pytest.MonkeyPatch) -> None:
    sentence = "The model finds this exact sentence here."

    def fake(s: Settings, messages: list[dict[str, str]]) -> str:
        return f"Look here.\nQUOTES:\n{sentence}"

    monkeypatch.setattr(jobs, "complete", fake)
    pid = _sentence()
    with TestClient(main.app) as c:
        job = c.post("/jobs", json={"name": "Marker", "output": "highlight", "steps": [
            {"scope": "page", "prompt": "Mark the sentence that matters.", "model": ""}]}).json()
        run = c.post(f"/jobs/{job['id']}/run", json={"paper_id": pid, "page": 1}).json()
        jobs.execute(run["id"])
        got = c.get(f"/runs/{run['id']}").json()
        marks = c.get(f"/papers/{pid}/highlights").json()["highlights"]
    assert got["status"] == "done" and "QUOTES" not in got["result"]["text"]
    assert got["result"]["highlights"][0]["page"] == 1
    assert marks[0]["kind"] == "dot" and sentence in marks[0]["text"]


def test_talk_returns_a_draft_and_does_not_save_it(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(s: Settings, messages: list[dict[str, str]]) -> str:
        return json.dumps({"reply": "A quiz creature.", "job": {
            "name": "Quiz", "color": 4, "trigger": "dwell", "every": 180, "output": "ask",
            "papers": [], "template_id": None, "on": True,
            "steps": [{"scope": "page", "prompt": "Ask one question about this page.", "model": ""}]}})

    monkeypatch.setattr(jobs, "complete", fake)
    with TestClient(main.app) as c:
        short = c.post("/dot/talk", json={"messages": [{"role": "user", "content": "Hi"}]})
        assert short.json()["job"] is None and "creature" in short.json()["reply"]
        drafted = c.post("/dot/talk", json={"messages": [{"role": "user", "content": "Quiz me when I stay"}]})
        assert drafted.json()["job"]["name"] == "Quiz" and drafted.json()["job"]["output"] == "ask"
        assert c.get("/jobs").json()["jobs"] == []


def test_complete_sends_no_think(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class Fake:
        def __init__(self) -> None:
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        def create(self, **kw: object) -> SimpleNamespace:
            captured.update(kw)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="hi"))])

    monkeypatch.setattr(llm, "client", lambda *a, **k: Fake())
    assert jobs.complete(Settings(model_name="m"), [{"role": "user", "content": "Hello"}]) == "hi"
    assert captured["extra_body"] == llm.NO_THINK and captured["model"] == "m"
