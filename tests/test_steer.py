import json
import numpy as np

from workbench import steer


def test_rfm_finds_the_direction_the_labels_hang_on():
    rng = np.random.default_rng(1)
    n, d = 120, 64
    true = rng.standard_normal(d)
    true /= np.linalg.norm(true)
    y = np.array([1] * (n // 2) + [0] * (n // 2))
    X = rng.standard_normal((n, d)) + np.outer(y * 3.0, true)  # the concept shifts its texts along one direction, the rest is noise
    v, r = steer.rfm(X, y)
    assert abs(np.linalg.norm(v) - 1) < 1e-6
    assert v @ true > 0.8 and r > 0.7  # found it, and signed toward the concept
    v2, _ = steer.rfm(X, 1 - y)
    assert v2 @ true < -0.8  # flip the labels and the direction flips


def test_the_steer_engine_is_a_model_like_dory_and_unsloth(monkeypatch):
    from workbench import llm, settings
    got = {}

    def gen(messages, on, max_tokens=0, temp=0.0, **k):
        got.update(messages=messages, on=dict(on))
        return "<think>hm</think>Guardian reporting."

    monkeypatch.setattr(steer, "generate", gen)
    s = settings.get_all().model_copy(update={"model_name": llm.STEER})
    assert llm.chat(s, [{"role": "user", "content": "hi"}]) == "Guardian reporting."  # no server: in-process, thinking stripped
    assert got["on"] == {}  # outside the harness's executor nothing is steered
    monkeypatch.setattr(steer, "available", lambda: True)
    monkeypatch.setattr(llm, "_model_status", lambda s: {"status": "not_running", "label": "Model not running", "models": []})
    st = llm.model_status(s)
    assert llm.STEER in st["models"] and st["status"] == "ready"  # on offer even with Unsloth down


def test_only_one_engine_holds_a_model_at_a_time(monkeypatch):
    from workbench import llm, settings
    calls, state, active = [], {"loaded": False}, ["unsloth/Qwen"]

    def api(s, method, path, body=None, timeout=10):
        calls.append((method, path, body))
        if path == "load":
            active[0] = body["model_path"]
        return {"active_model": active[0], "loaded": [active[0]], "loading": []} if path == "status" else {}

    monkeypatch.setattr(llm, "_api", api)
    monkeypatch.setattr(steer, "loaded", lambda: state["loaded"])
    monkeypatch.setattr(steer, "load", lambda name=steer.MODEL: state.update(loaded=True))
    monkeypatch.setattr(steer, "unload", lambda: (was := state["loaded"], state.update(loaded=False))[0])
    s = settings.get_all()
    got = llm.ensure(s, llm.STEER)
    assert got["ok"] and state["loaded"] and ("POST", "unload", {"model_path": "unsloth/Qwen"}) in calls  # Unsloth's model left first
    calls.clear()
    llm.ensure(s, "unsloth/Other")
    assert not state["loaded"] and ("POST", "load", {"model_path": "unsloth/Other"}) in calls  # and the steer engine leaves before Unsloth loads


def _claims(kept, dropped=(), source="reflection", checked=""):
    from workbench import char
    i = char.add_memory("Reflection: t", "a note", source=source)["id"] if kept or dropped else 0
    if checked:
        char.add_memory(f"Checked: {i}", checked, source="sheet")
    char.add_memory(f"Claims: {i}", json.dumps({"kept": list(kept), "dropped": list(dropped)}), source="sheet")


def test_facts_reads_kept_and_dropped_once_each_oldest_first():
    _claims(["a", "b"], ["x"])
    _claims(["b", "c"], ["x", "y"])
    assert steer.facts() == (["a", "b", "c"], ["x", "y"])


def test_facts_count_kept_claims_only_of_notes_still_admitted():
    _claims(["good"], ["bad"])
    _claims(["turned away"], source="sheet")  # the intake gate made it a sheet row
    _claims(["unchecked"], checked="drop")  # the Verifier dropped it
    _claims(["verified"], checked="keep")
    assert steer.facts() == (["good", "verified"], ["bad", "turned away", "unchecked"])


def test_truth_concept_waits_for_enough_facts_then_names_its_data(monkeypatch, tmp_path):
    from workbench import char
    monkeypatch.setattr(steer, "_dir", lambda: tmp_path)
    monkeypatch.setattr(char, "world_words", lambda: {"Alpha", "Beta", "Gamma"})
    fitted = []
    monkeypatch.setattr(steer, "fit", lambda c, pos, neg: fitted.append((c, pos, neg)) or (tmp_path / f"{c}.npz").touch())
    _claims([f"Alpha holds gate {i}." for i in range(11)], [f"junk {i}" for i in range(12)])
    assert steer.truth_concept() == "" and not fitted  # 11 kept: too few
    _claims(["Gamma rules the sea."])  # the last world word wraps round to the first
    _claims(["The sea is wide."])  # names nothing of its world: no corrupted copy
    _claims(["The Alpha of the sea."])  # only world words are swapped, never "of" or "the"
    c1 = steer.truth_concept()
    _, pos, neg = fitted[0]
    assert c1.startswith("truth-") and len(pos) == 14 and len(neg) == 12 + 13  # 12 dropped + 13 copies, not 14
    assert "Note: Beta holds gate 0." in neg and "Note: Alpha rules the sea." in neg and "Note: The Beta of the sea." in neg and "Note: Alpha holds gate 0." in pos
    assert steer.truth_concept() == c1 and len(fitted) == 1  # same data, already fitted
    _claims(["Beta guards the keep."])
    assert steer.truth_concept() != c1 and len(fitted) == 2  # a new fact is a new name, and a refit


def test_world_concept_contrasts_its_world_with_the_other_worlds(monkeypatch, tmp_path):
    from workbench import char, chibi
    monkeypatch.setattr(steer, "_dir", lambda: tmp_path)
    monkeypatch.setattr(char, "world_words", lambda: {"Alpha", "Beta", "Gamma"})
    monkeypatch.setattr(chibi, "where_from", lambda persona: "Zed")
    got = []
    monkeypatch.setattr(steer, "fit", lambda c, pos, neg: got.append((pos, neg)))
    steer.world_concept()
    pos, neg = got[0]
    assert all(p.startswith("You live in the world of Zed") for p in pos)
    assert [n[:len(steer.OTHER_WORLDS[i % 4])] for i, n in enumerate(neg)] == [steer.OTHER_WORLDS[i % 4] for i in range(len(neg))]
    assert [n.removeprefix(steer.OTHER_WORLDS[i % 4]) for i, n in enumerate(neg)] == steer.GENERIC
