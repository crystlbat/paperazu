"""Self-improvement memory: a step that slips gets a drafted fix, an approved fix runs on trial, and plain counts admit or
roll it back. A fix proven on one model is re-tested on another."""
import json

import pytest

from harness_char import char
from pdf_research import jobs
from shared import db, settings


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(db, "PAPERS_DIR", tmp_path / "papers")
    db.init()
    char.init_db()
    char.update_profile("Sherlock", "a detective", [], "#fff")
    monkeypatch.setattr(jobs, "complete", lambda s, m, **kw: "not json")  # drafts fall back to the written fix unless a test says otherwise


def _runs(kind: str, n: int, slips: int = 0) -> None:
    for i in range(n):
        if i < slips:
            char._fail(kind, f"slip {i}")
        char._engine(kind, "ok", "")


def _fix_of(kind: str) -> dict:
    return next(c for c in char.corrections() if c["kind"] == kind)


def test_the_verifier_drafts_a_fix_from_the_record(monkeypatch):
    seen = []
    def complete(s, m, **kw):
        seen.append(m[1]["content"])
        return '{"text": "Ask about one thing only.", "why": "it lists the question words", "expect": "one question per reply"}'
    monkeypatch.setattr(jobs, "complete", complete)
    char._fail("wonder", "Who, What, Where")
    char._fail("wonder", "Who, What")
    fix = _fix_of("wonder")
    assert (fix["state"], fix["text"], fix["why"], fix["expect"]) == ("proposed", "Ask about one thing only.", "it lists the question words", "one question per reply")
    assert "Who, What, Where" in seen[0] and char._fix("wonder") == ""  # it saw how it slipped; nothing is in the prompt until approved


def test_a_fix_that_cuts_slips_is_admitted_after_its_trial():
    _runs("reflect", 4, slips=2)
    char.set_correction("reflect", True)
    assert _fix_of("reflect")["state"] == "trial" and char._fix("reflect").strip() == char.CORRECTIONS["reflect"]  # live during the trial
    _runs("reflect", char.TRIAL_RUNS - 1)
    assert _fix_of("reflect")["trial"] == [char.TRIAL_RUNS - 1, char.TRIAL_RUNS]
    _runs("reflect", 1)
    fix = _fix_of("reflect")
    assert fix["state"] == "on" and fix["verdict"].startswith(f"slipped 0 of {char.TRIAL_RUNS} runs") and "2 of 4 before" in fix["verdict"]


def test_a_fix_that_does_not_help_is_rolled_back_and_the_next_draft_is_different(monkeypatch):
    _runs("plan", 4, slips=2)
    char.set_correction("plan", True)
    _runs("plan", char.TRIAL_RUNS, slips=3)
    fix = _fix_of("plan")
    assert fix["state"] == "rolled_back" and char._fix("plan") == ""
    seen = []
    monkeypatch.setattr(jobs, "complete", lambda s, m, **kw: seen.append(m[1]["content"]) or json.dumps({"text": char.CORRECTIONS["plan"]}))
    _runs("plan", 2, slips=2)  # two slips after the rollback: a new draft, which may not repeat the failed fix
    fix = _fix_of("plan")
    assert fix["state"] == "proposed" and f"{char.CORRECTIONS['plan']} (why" in seen[-1] and "rolled_back" in seen[-1]
    assert [a["state"] for a in fix["tried"]] == ["rolled_back"]


def test_a_fix_that_makes_another_step_worse_is_rolled_back():
    _runs("reflect", 4, slips=2)
    _runs("goal", char.TRIAL_RUNS)  # goal never slipped before the trial
    char.set_correction("reflect", True)
    _runs("goal", char.TRIAL_RUNS, slips=char.TRIAL_RUNS)
    _runs("reflect", char.TRIAL_RUNS)
    fix = _fix_of("reflect")
    assert fix["state"] == "rolled_back" and "goal got worse" in fix["verdict"]


def test_skipped_runs_do_not_count_toward_a_trial():
    _runs("reflect", 4, slips=2)
    char.set_correction("reflect", True)
    for _ in range(char.TRIAL_RUNS):
        char._engine("reflect", "skipped", "nothing to do")
    assert _fix_of("reflect")["trial"] == [0, char.TRIAL_RUNS]


def test_an_admitted_fix_goes_back_on_trial_on_another_model():
    settings.update({"model_name": "small-a"})
    _runs("reflect", 4, slips=2)
    char.set_correction("reflect", True)
    _runs("reflect", char.TRIAL_RUNS)
    assert _fix_of("reflect")["state"] == "on" and _fix_of("reflect")["model"] == "small-a"
    settings.update({"model_name": "small-b"})
    assert char._fix("reflect")  # still in the prompt while it is re-tested
    fix = _fix_of("reflect")
    assert fix["state"] == "trial" and fix["model"] == "small-b" and fix["verdict"] == "re-testing on small-b, proven on small-a"


def test_a_fix_from_before_the_record_is_kept_and_re_tested():
    char.add_memory("Correction: goal", f"on|{char.CORRECTIONS['goal']}", source="sheet")
    assert char._fix("goal").strip() == char.CORRECTIONS["goal"]
    assert _fix_of("goal")["state"] == "trial"


def test_removing_a_live_fix_closes_it():
    _runs("reflect", 4, slips=2)
    char.set_correction("reflect", True)
    char.set_correction("reflect", False)
    assert _fix_of("reflect")["state"] == "removed" and char._fix("reflect") == ""
    with pytest.raises(ValueError):
        char.set_correction("fill", True)
