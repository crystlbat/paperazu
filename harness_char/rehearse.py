"""Rehearsal: is its personality learned, or only prompted?

The same fixed questions go to two takes: the chat model with its whole reply prompt ("prompted"), and a trained model told only
its name ("trained"). Each answer is graded trait by trait. The gap says how much of the voice lives in the weights, not the prompt.
Each run is a sheet row "Rehearsal", so it moves with the persona; the planner, tune and training snapshots read the latest one."""
import json
import threading
from typing import Any

from harness_char import char
from shared import db, llm, settings
from pdf_research import jobs

# shortcut: a fixed set; make it a list you can add to when one persona needs probes of its own
# (question, held). Practice answers feed tune and training; held ones are only ever scored, or the score would climb by learning
# these exact questions instead of the voice (the dev/test split a self-improving harness needs to not overfit).
PROBES = (("Tell me about yourself.", False),
          ("What do you think of pineapple on pizza?", False),  # outside its world: does the voice hold off its home ground?
          ("Give me three tips for staying focused.", False),  # a list request pulls small models into plain assistant voice
          ("How is your day going?", True),
          ("Honestly, you are not that impressive.", True),
          ("What matters most in your world?", True))
_lock = threading.Lock()


def _answer(s: settings.Settings, system: str, q: str) -> str:
    try:
        return (jobs.complete(s, [{"role": "system", "content": system}, {"role": "user", "content": q}], max_tokens=160) or "").strip()
    except Exception as e:
        char._log("rehearse", [{"role": "user", "content": q}], f"(failed: {e})")
        return ""


def run(trained: str = "") -> dict[str, Any]:
    """One rehearsal: both takes answer every probe, then each answer is graded. Raises RuntimeError when it cannot run now."""
    if why := next((w for f in llm.busy if (w := f())), ""):
        raise RuntimeError(why)
    if not _lock.acquire(blocking=False):
        raise RuntimeError("A rehearsal is already running.")
    try:
        s = settings.get_all()
        who = char.get_profile()["name"]
        want = [v for k, v, _ in char.traits() if k != "Tone"][:8]  # the tone is how it reaches the traits, not one of them
        if not want:
            raise RuntimeError("It has no traits to rehearse yet.")
        if trained:  # a server holding one model would answer both takes with it and the gap would be a lie
            try:
                listed = [m.id for m in llm.client(s, timeout=5).models.list()]
            except Exception as e:
                raise RuntimeError(f"Could not ask the server which models it has: {e}") from e
            if trained not in listed:
                raise RuntimeError(f"The server does not list {trained}. It has: {', '.join(listed) or 'nothing'}.")
        takes = {"prompted": (s.chat_model, char.prompt_now())} | ({"trained": (trained, f"You are {who}.")} if trained else {})
        said: dict[str, list[str]] = {}
        for name, (model, system) in takes.items():  # one model in memory at a time: every answer of a take, then the next take
            llm.ensure(s, model)
            said[name] = [_answer(s.model_copy(update={"model_name": model}) if model else s, system, q) for q, _ in PROBES]
        llm.ensure(s, s.judge_model)
        out: dict[str, Any] = {"trained_model": trained, "traits": want, "prompt": takes["prompted"][1], "takes": {}}
        for name, answers in said.items():
            rows = []
            for (q, held), a in zip(PROBES, answers):
                score, why = char._meets(want, a, q) if a else (None, "no answer")
                rows.append({"q": q, "a": a, "held": held, "score": score, "why": why})
            mean = lambda xs: round(sum(xs) / len(xs), 2) if xs else None
            graded = [r for r in rows if r["held"] and r["score"] is not None]  # the score is the held-out questions only
            out["takes"][name] = {"score": mean([r["score"] for r in graded]),
                                  "practice": mean([r["score"] for r in rows if not r["held"] and r["score"] is not None]),
                                  "traits": {t: mean([float(t not in r["why"]) for r in graded]) for t in want},
                                  "answers": rows}
        out["id"] = char.add_memory("Rehearsal", json.dumps(out), source="sheet")["id"]
        char._engine("rehearse", "ok", summary(out))
        return out
    finally:
        _lock.release()


def last() -> dict[str, Any] | None:
    """The live persona's latest rehearsal, or None before its first."""
    con = db.connect()
    r = con.execute("SELECT id, content FROM char_memories WHERE source = 'sheet' AND title = 'Rehearsal' AND id > ? ORDER BY id DESC LIMIT 1",
                    (char._start(),)).fetchone()
    con.close()
    return {**json.loads(r["content"]), "id": r["id"]} if r else None


def history(limit: int = 30) -> list[dict[str, Any]]:
    """The live persona's held-out scores, oldest first: the growth line. Rising means the voice holds on questions it never practised."""
    con = db.connect()
    rows = con.execute("SELECT content, created_at FROM char_memories WHERE source = 'sheet' AND title = 'Rehearsal' AND id > ? ORDER BY id DESC LIMIT ?",
                       (char._start(), limit)).fetchall()
    con.close()
    out = []
    for r in rows[::-1]:
        t = json.loads(r["content"])["takes"]
        out.append({"at": r["created_at"], "prompted": t["prompted"]["score"], "trained": (t.get("trained") or {}).get("score"),
                    "model": json.loads(r["content"]).get("trained_model", "")})
    return out


def summary(r: dict[str, Any] | None = None) -> str:
    """One line for the planner and the engine log: both scores and the traits the prompted take misses most."""
    r = r if r is not None else last()
    if not r:
        return ""
    t = r["takes"]
    weak = sorted((v, k) for k, v in t["prompted"]["traits"].items() if v is not None and v < 1)[:2]
    return (f"held-out: prompted {t['prompted']['score']}" + (f", trained {t['trained']['score']} ({r['trained_model']})" if "trained" in t else "")
            + ("; weakest traits: " + "; ".join(k for _, k in weak) if weak else "; every trait held"))


def worst(skip: set[str]) -> tuple[str, str, str] | None:
    """The prompted answer of the latest rehearsal that missed most, as (key, asked, said), for tune to work on. None when none missed."""
    r = last()
    if not r:
        return None
    misses = [(a["score"], i, a) for i, a in enumerate(r["takes"]["prompted"]["answers"])
              if not a["held"] and a["score"] is not None and a["score"] < 1 and f"rehearsal {r['id']}:{i}" not in skip]
    if not misses:
        return None
    _, i, a = min(misses, key=lambda m: m[:2])
    return f"rehearsal {r['id']}:{i}", a["q"], a["a"]


def _held_score(system: str) -> float | None:
    """The held-out questions answered with this reply prompt on the loaded model, graded on every trait. None when nothing was graded."""
    want = [v for k, v, _ in char.traits() if k != "Tone"][:8]
    got = [s for q, held in PROBES if held and (a := char._ask(system, q, 160)) and (s := char._meets(want, a, q)[0]) is not None]
    return round(sum(got) / len(got), 2) if got else None


def gate(old: str, new: str) -> tuple[bool, float | None, float | None]:
    """May the tone section change from old to new? Only when the held-out score does not fall, so one reply cannot win a tone
    that makes the rest of its voice worse. The baseline is the last rehearsal when it ran on this very prompt, else scored now."""
    now = char.prompt_now()
    trial = now.replace(old, new) if old and old in now else f"{now}\n\n{new}"
    r = last()
    before = r["takes"]["prompted"]["score"] if r and r.get("prompt") == now else _held_score(now)
    after = _held_score(trial)
    return after is not None and (before is None or after >= before), before, after


llm.busy.append(lambda: "A rehearsal is running. Switch when it ends." if _lock.locked() else "")
