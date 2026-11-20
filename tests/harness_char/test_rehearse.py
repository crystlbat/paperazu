from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from harness_char import char, harness, rehearse, train
from shared import llm
from pdf_research import jobs
import app as main

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    char.init_db()
    char.update_profile("BT", "You are BT.", [], "")
    char.add_memory("Resting: char BT", "0", source="sheet")
    char.add_memory("Var: direction", "Speak with thou and thee.", source="sheet")
    loaded = []
    monkeypatch.setattr(llm, "ensure", lambda s, m, **k: loaded.append(m))
    monkeypatch.setattr(llm, "client", lambda s, timeout=None: SimpleNamespace(models=SimpleNamespace(list=lambda: [SimpleNamespace(id="bt-tuned")])))
    return loaded


def _model(s, m, **k):
    sys_, user = m[0]["content"], m[1]["content"]
    if "grade a reply against numbered traits" in sys_:  # the grown voice is missed off its home ground (pizza) and without "thou"
        held = "thou" in user.split("Reply:")[1].lower() and "pizza" not in user
        return "\n".join(f"{n} {'YES' if held or 'thou' not in trait else 'NO'}" for n, trait in
                         ((int(x.split('.')[0]), x) for x in user.split("Question it answered")[0].splitlines()[1:]))
    if "tone section" in sys_:
        return "Use thou and thee in every line."
    if sys_ == "You are BT.":  # the trained take: no persona, so plain voice
        return "I am a titan."
    return "Thou art kind, pilot." if "Tell me" not in user else "I am BT, thou knowest."


def test_rehearsal_compares_the_prompted_and_trained_takes_and_feeds_planner_tune_and_training(monkeypatch, setup):
    monkeypatch.setattr(jobs, "complete", _model)
    r = client.post("/char/rehearse", json={"model": "bt-tuned"}).json()
    p, t = r["takes"]["prompted"], r["takes"]["trained"]
    assert len(p["answers"]) == len(rehearse.PROBES) and p["score"] > t["score"] == 0.5  # the voice lives in the prompt, not the weights
    assert t["traits"]["Speak with thou and thee."] == 0 and p["traits"]["You are BT."] == 1
    assert "bt-tuned" in setup  # the trained model was loaded for its take
    assert client.get("/char/rehearse").json()["id"] == r["id"]
    client.post("/char/rehearse", json={"model": "bt-tuned"})
    g = client.get("/char/monitor").json()["growth"]  # the growth line: one point per rehearsal, oldest first
    assert [(x["prompted"], x["trained"], x["model"]) for x in g] == [(1.0, 0.5, "bt-tuned")] * 2

    line = "\n".join(x["content"] for x in harness.prompt())
    assert "last personality rehearsal" in line and "held-out: prompted 1.0, trained 0.5 (bt-tuned)" in line and "every trait held" in line  # pizza is practice, not scored

    note = char.rest(True, None, only="tune")["note"]  # no chat to tune on: it works on the pizza answer that missed
    assert "new tone scored" in note or "scored 0.5" in note

    snap = train.snapshot(0, 1, "test")
    assert any(e["kind"] == "rehearsal" and e["user"] == "Tell me about yourself." for e in snap["examples"])
    assert any("pizza" in f for f in snap["fails"]["rehearsal misses"])
    assert not any(e["user"] in {q for q, held in rehearse.PROBES if held} for e in snap["examples"])  # held-out answers are never taught


def test_a_trained_model_the_server_does_not_list_is_refused(monkeypatch):
    monkeypatch.setattr(jobs, "complete", _model)
    r = client.post("/char/rehearse", json={"model": "not-there"})
    assert r.status_code == 409 and "does not list not-there" in r.json()["detail"]


@pytest.mark.parametrize("held_reply, adopted", [("No.", False), ("Thou art grand.", True)])
def test_tune_keeps_a_new_tone_only_when_the_held_out_rehearsal_does_not_fall(monkeypatch, held_reply, adopted):
    held = {q for q, h in rehearse.PROBES if h}

    def model(s, m, **k):
        sys_, user = m[0]["content"], m[1]["content"]
        if "grade a reply against numbered traits" in sys_:
            ok = "thou" in user.split("Reply:")[1].lower()
            return "\n".join(f"{line.split('.')[0]} {'YES' if ok or 'thou' not in line else 'NO'}"
                             for line in user.split("Question it answered")[0].splitlines()[1:])
        if "tone section" in sys_:
            return "Use thou only."
        if "Use thou only." in sys_:  # the new tone: wins the practice reply; the held-out answers depend on the case
            return held_reply if user in held else "Thou art fine."
        return "Thou art kind." if user in held else "Plain."  # the old tone: held-out fine, practice plain
    monkeypatch.setattr(jobs, "complete", model)
    rehearse.run()
    note = char.rest(True, None, only="tune")["note"]
    assert ("is now in its prompt" in note) == adopted
    assert (char._tone() == "Use thou only.") == adopted
    if not adopted:
        assert "held-out rehearsal fell from 1.0 to 0.5" in note
