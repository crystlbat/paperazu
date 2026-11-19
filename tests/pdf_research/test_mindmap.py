"""The paper as a mind map, made in steps in the background: themes first, then the points under each theme. Every
node explains itself and points at a page that exists; a step that fails is marked, Stop stops, a dead model says so."""
import json
import time
from types import SimpleNamespace

import pymupdf
import pytest
from fastapi.testclient import TestClient

import app as main
from pdf_research import library, mindmap, primer
from shared import db, llm


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(db, "PAPERS_DIR", tmp_path / "papers")
    db.init()
    monkeypatch.setattr(mindmap.llm, "pick_model", lambda s: "m")
    mindmap._runs.clear()


def _paper(name: str = "p.pdf") -> str:
    doc = pymupdf.open()
    for t in ("Wearables collect heart rate all day.", f"Consent is rarely explicit. {name}"):
        doc.new_page().insert_text((72, 100), t, fontsize=10)
    return library.create(doc.tobytes(), name)


def _model(monkeypatch, replies):
    """Each model call takes the next reply: a string, an exception to raise, or a function of watch."""
    it, sent = iter(replies), []
    def complete(s, msgs, schema, name, watch=None):
        sent.append(msgs[1]["content"])
        r = next(it)
        if isinstance(r, Exception):
            raise r
        return r(watch) if callable(r) else r
    monkeypatch.setattr(primer, "_complete", complete)
    return sent


def _wait(c, pid):
    for _ in range(200):
        out = c.get(f"/papers/{pid}/mindmap").json()
        if out["run"]["state"] != "making":
            return out
        time.sleep(0.02)
    raise AssertionError("the run never ended")


OUTLINE = json.dumps({"label": "AI wearables: risks", "say": "What can go wrong.", "children": [
    {"label": "Privacy", "say": "Data is collected all the time.", "page": 1},
    {"label": "Consent", "say": "Rarely asked for.", "page": 9},  # no page 9: the page goes, the theme stays
    {"label": " ", "say": "no label", "page": 1}]})  # no label: dropped
POINTS = json.dumps({"points": [{"label": "Passive monitoring", "say": "Heart rate is logged all day.", "page": 1}]})


def test_a_map_is_made_theme_by_theme_and_a_theme_that_fails_is_marked(monkeypatch):
    sent = _model(monkeypatch, [OUTLINE, "```json\n" + POINTS + "\n```", "not json", "not json either"])
    pid, c = _paper(), TestClient(main.app)
    assert c.get(f"/papers/{pid}/mindmap").json() == {"tree": None, "run": None}
    assert c.post(f"/papers/{pid}/mindmap").json()["run"]["state"] == "making"
    out = _wait(c, pid)
    tree = out["tree"]
    assert out["run"]["state"] == "done" and out["run"]["step"] == out["run"]["of"] == 3 and out["run"]["failed"] == ["Consent"]
    assert [(b["label"], b["page"]) for b in tree["children"]] == [("Privacy", 1), ("Consent", None)]
    assert tree["children"][0]["children"][0]["say"] == "Heart rate is logged all day." and tree["children"][1]["missing"]
    assert out["model"] == "m" and out["run"]["tree"] == tree
    assert sent[1].startswith(sent[0][:sent[0].index("</paper>")])  # every step sends the same paper first: the cache holds
    assert 'theme "Consent"' in sent[2] and "Privacy" in sent[2]  # the theme, and the others to leave out


def test_stop_cuts_the_model_off_and_keeps_the_old_map(monkeypatch):
    def endless(watch):
        while watch("{"):
            time.sleep(0.01)
        raise primer.PrimerError("Stopped.")
    _model(monkeypatch, [OUTLINE, POINTS, POINTS, OUTLINE, endless])
    pid, c = _paper(), TestClient(main.app)
    c.post(f"/papers/{pid}/mindmap"); old = _wait(c, pid)["tree"]
    c.post(f"/papers/{pid}/mindmap")  # make it again, and stop it while the model writes
    time.sleep(0.05)
    assert c.post(f"/papers/{pid}/mindmap/stop").json() == {"stopped": True}
    out = _wait(c, pid)
    assert out["run"]["state"] == "stopped" and out["tree"] == old
    assert c.post(f"/papers/{pid}/mindmap/stop").json() == {"stopped": False}


def test_a_model_that_is_down_is_said_plainly_and_not_asked_again(monkeypatch):
    sent = _model(monkeypatch, [primer.PrimerError("Could not reach the model. Is Unsloth running?")])
    pid, c = _paper(), TestClient(main.app)
    c.post(f"/papers/{pid}/mindmap")
    out = _wait(c, pid)
    assert out["run"]["state"] == "failed" and "Unsloth" in out["run"]["error"] and len(sent) == 1 and out["tree"] is None


def test_every_theme_failing_fails_the_run_and_a_bug_does_not_hang_it(monkeypatch):
    _model(monkeypatch, [OUTLINE, primer.PrimerError("The model call failed."), primer.PrimerError("The model call failed."),
                         primer.PrimerError("x"), primer.PrimerError("x")])
    pid, c = _paper(), TestClient(main.app)
    c.post(f"/papers/{pid}/mindmap")
    assert _wait(c, pid)["run"]["state"] == "failed"
    _model(monkeypatch, [KeyError("a bug")])
    c.post(f"/papers/{pid}/mindmap")
    assert _wait(c, pid)["run"]["error"].startswith("Something went wrong")


def test_one_map_at_a_time(monkeypatch):
    def slow(watch):
        while watch("{"):
            time.sleep(0.01)
        raise primer.PrimerError("Stopped.")
    _model(monkeypatch, [slow])
    a, b, c = _paper("a.pdf"), _paper("b.pdf"), TestClient(main.app)
    c.post(f"/papers/{a}/mindmap")
    assert c.post(f"/papers/{b}/mindmap").status_code == 409
    assert c.post(f"/papers/{a}/mindmap").json()["run"]["state"] == "making"  # asking again joins the run going
    c.post(f"/papers/{a}/mindmap/stop"); _wait(c, a)
    assert c.post("/papers/nope/mindmap").status_code == 404


def test_a_streamed_reply_stops_when_asked_and_closes_the_connection():
    closed = []
    chunk = lambda t, end=None: SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=t), finish_reason=end)])
    class Stream:
        def __iter__(self):
            return iter([chunk("{"), chunk('"a"'), chunk(": 1}", "stop")])
        def close(self):
            closed.append(True)
    seen = []
    whole = llm._gather(Stream(), lambda t: seen.append(t) or True)
    assert whole.choices[0].message.content == '{"a": 1}' and whole.choices[0].finish_reason == "stop" and seen[-1] == '{"a": 1}'
    with pytest.raises(llm.ModelError, match="Stopped"):
        llm._gather(Stream(), lambda t: len(t) < 2)
    assert closed == [True, True]


def test_long_say_ends_on_a_whole_sentence():
    from pdf_research.mindmap import _trim
    long = "The paper proposes a framework. " * 20
    assert _trim(long).endswith("framework.") and len(_trim(long)) <= 420
    assert _trim("word " * 200).endswith("…")
    assert _trim("Short one.") == "Short one."


def test_label_drops_prefix_and_ends_on_a_word():
    from pdf_research.mindmap import node
    n = node({"label": "Title: " + "Explaining classifiers through diverse counterfactual explanations " * 3, "say": "", "page": 1}, 3)
    assert not n["label"].startswith("Title") and n["label"].endswith("…") and len(n["label"]) <= 91


def test_grow_adds_finer_points_under_one_point_and_keeps_the_rest(monkeypatch):
    finer = json.dumps({"points": [{"label": "Every 5 minutes", "say": "The watch samples heart rate every 5 minutes.", "page": 1}]})
    sent = _model(monkeypatch, [OUTLINE, POINTS, POINTS, finer])
    pid, c = _paper(), TestClient(main.app)
    c.post(f"/papers/{pid}/mindmap"); before = _wait(c, pid)["tree"]
    assert c.post(f"/papers/{pid}/mindmap/grow", json={"theme": "Privacy", "point": "Nope"}).status_code == 404
    assert c.post(f"/papers/{pid}/mindmap/grow", json={"theme": "Privacy", "point": "Passive monitoring"}).json()["run"]["grow"] == ["Privacy", "Passive monitoring"]
    out = _wait(c, pid)
    assert out["run"]["state"] == "done"
    assert out["tree"]["children"][0]["children"][0]["children"][0]["label"] == "Every 5 minutes"
    assert out["tree"]["children"][1] == before["children"][1]  # the other themes are untouched
    assert '"Passive monitoring"' in sent[-1] and sent[-1].startswith(sent[0][:sent[0].index("</paper>")])  # same paper first: the cache holds
