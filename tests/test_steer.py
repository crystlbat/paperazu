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
