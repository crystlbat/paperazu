"""Routes for the live character: the Dot space, /char, the harness cycle, training, the verse, and chibi forms."""
import re
import time
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, RedirectResponse


from harness_char import char, chibi, harness, space, train, verse
from shared import llm, settings

router = APIRouter()


@router.get("/space")
def get_space() -> dict[str, Any]:
    return space.state()


@router.get("/space/notes")
def get_space_notes() -> dict[str, Any]:
    return {"notes": space.all_notes()}


@router.post("/space/say")
def space_say(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    text = str(body.get("text") or "").strip()
    if not text:
        raise HTTPException(422, detail="Say something to Dot.")
    return space.say(text)


@router.delete("/space/vars/{var_id}")
def space_remove_var(var_id: int) -> dict[str, Any]:
    if not space.remove_var(var_id):
        raise HTTPException(404, detail="That variable is gone.")
    return space.state()


@router.delete("/space")
def space_clear() -> dict[str, Any]:
    space.clear()
    return space.state()


@router.get("/char")
def char_entry(request: Request) -> Any:
    if "text/html" in request.headers.get("accept", ""):
        return RedirectResponse(url="/#char")
    return char.state()


@router.get("/char/notes")
def get_char_notes() -> dict[str, Any]:
    return {"notes": char.all_notes()}


@router.get("/char/questions")
def get_char_questions() -> dict[str, Any]:
    return {"questions": char.get_questions()}


@router.post("/char/say")
def char_say(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    text = str(body.get("text") or "").strip()
    if not text:
        raise HTTPException(422, detail="Say something to Jarvis.")
    learn_mode = bool(body.get("learn_mode") or False)
    return char.say(text, learn_mode=learn_mode, answering=bool(body.get("answering")))


@router.post("/space/preview")
def space_preview(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """How a rule sentence would be read, without saving it."""
    return {"rules": space.preview(str(body.get("text") or "")[:600])}


@router.post("/char/speak")
def char_speak(body: dict[str, Any] = Body(...)) -> Response:
    try:
        return Response(char.speak(str(body.get("text") or "")), media_type="audio/mpeg")
    except Exception as e:  # e.g. "The loaded model cannot answer in speech."
        raise HTTPException(503, detail=f"No speaking model: {getattr(e, 'read', lambda: str(e).encode())()[:200].decode(errors='ignore')}")


@router.get("/char/mind")
def char_mind() -> dict[str, Any]:
    return char.mind()


@router.get("/char/mesh")
def char_mesh() -> dict[str, Any]:
    return char.mesh()


@router.post("/char/creatures/asker")
def char_asker() -> dict[str, Any]:
    return {"asked": char.asker(), "open": char._open_questions(char._start())}


@router.post("/char/creatures/pruner")
def char_pruner() -> dict[str, Any]:
    return char.pruner()


@router.post("/char/creatures/sorter")
def char_sorter(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    return char.sorter(int(body.get("limit") or 1))


@router.post("/char/reflect")
def char_reflect(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    return char.reflect(on_char=bool(body.get("char")))


@router.get("/char/systems")
def char_systems() -> dict[str, Any]:
    return char.systems()


@router.post("/char/systems")
def char_set_system(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    try:
        char.set_system(int(body.get("id", -1)), bool(body.get("on")))
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    return char.systems()


_model_seen: dict[str, Any] = {}  # the last model status and when, so polling the engines does not list the models each time


def _model() -> tuple[bool, str]:
    if time.time() - _model_seen.get("t", 0) > 10:
        _model_seen.update(llm.model_status(settings.get_all()), t=time.time())
    return _model_seen["status"] == "ready", _model_seen["label"]


@router.get("/char/engines")
def char_engines() -> dict[str, Any]:
    return char.engines(*_model())


@router.post("/char/dial")
def char_dial(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    try:
        return {"dial": char.set_dial(float(body.get("curiosity"))), "disposition": char.disposition()}
    except (TypeError, ValueError):
        raise HTTPException(422, detail="curiosity must be a number from 0 to 3")


@router.get("/char/note/{note_id}")
def char_note(note_id: int) -> dict[str, Any]:
    try:
        return char.note(note_id)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@router.get("/char/journal")
def char_journal() -> dict[str, Any]:
    """Its study journal, newest page first."""
    return {"pages": char.journal()}


@router.get("/char/train")
def char_train() -> dict[str, Any]:
    """The live persona's training runs, newest first, with their logs."""
    return train.status()


@router.post("/char/train")
def char_train_do(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    """start (with minutes, lo, hi, max_steps), pause, resume or stop a training run."""
    action = str(body.get("action") or "start")
    try:
        return train.start(body) if action == "start" else train.control(action)
    except (RuntimeError, KeyError, ValueError) as e:
        raise HTTPException(409, detail=str(e) if not isinstance(e, KeyError) else f"no action {action}")


@router.get("/char/train/{run_id}/snapshots")
def char_train_snaps(run_id: int) -> dict[str, Any]:
    return {"snapshots": train.snapshots(run_id)}


@router.get("/char/train/{run_id}/dataset.jsonl")
def char_train_dataset(run_id: int) -> Response:
    """The run's fine-tuning set: JSONL, one {"system", "messages"} example per line."""
    return Response(train.dataset(run_id), media_type="application/jsonl", headers={"Content-Disposition": f'attachment; filename="{char.get_profile()["name"].replace(" ", "-").lower()}-run-{run_id}.jsonl"'})


@router.post("/char/you")
def char_you(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    """Tell it who you are in your own words (`about`), or make it forget one thing it learned about you (`forget`: name, theirs, mine, role, work)."""
    return {"you": char.set_you(body.get("about") if "about" in body else None, body.get("forget"))}


@router.get("/char/letter")
def char_letter() -> dict[str, Any]:
    return char.letter()


@router.post("/char/letter")
def char_letter_answer(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    """[{id, text, skip}]: your answers to its letter; blank ones wait for the next letter."""
    return char.answer_letter(list(body.get("answers") or []))


@router.get("/char/tools")
def char_tools() -> dict[str, Any]:
    """Its tools as a graph, wired into its mesh: what each step made, which feeds which, and the model they run on."""
    return char.toolnet(char.mesh()["nodes"])


@router.get("/char/life")
def char_life() -> dict[str, Any]:
    """Its needs, mood shifts, wants and trust."""
    return char.life()


@router.post("/char/want/{want_id}")
def char_want(want_id: int, body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    """Give it what it asked for (the gift becomes a note it reads), or let the want go (no gift)."""
    w = char.give_want(want_id, str(body.get("gift") or ""))
    if w is None:
        raise HTTPException(404, detail="no such want")
    return w


@router.get("/char/report")
def char_report() -> dict[str, Any]:
    return {**char.report(*_model()), "harness_loop": harness.totals(), "cycles": harness.cycles(30), "mode": char.mode(), "tracker": char.tracker(),
            "race": verse.live_race(), "train": train.status(), "letter": char.letter(), "now": dict(char.NOW),
            "model_name": (lambda c: c.chat_model or c.model_name or "")(settings.get_all()), "models": _model_seen.get("models", [])}


@router.post("/char/cycle")
def char_cycle(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    try:
        budget = max(1, min(12, int(body.get("budget") or harness.BUDGET)))
    except (TypeError, ValueError):
        raise HTTPException(422, detail="budget must be a whole number")
    try:
        return harness.cycle(budget)
    except RuntimeError as e:
        raise HTTPException(409, detail=str(e))


@router.get("/char/cycles")
def char_cycles(limit: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
    return {"cycles": harness.cycles(limit)}


@router.get("/model/swap")
def model_swap() -> dict[str, Any]:
    return dict(llm.SWAP)


@router.post("/char/rest")
def char_rest(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    if body.get("char") and train.active() and not body.get("only"):  # a training run is driving it: idle learning stands aside, one step at a time
        return {"done": True, "kind": "", "topic": "", "note": "", "why": "a training run is driving it", "training": True, "questions": char._open_questions(char._start())[::-1][:3], "graph": char.graph()}
    if body.get("char") and char.mode() == "planner" and not body.get("only"):  # planner mode: idle time runs one harness cycle instead of the rule loop; a step you ask for by name still runs
        try:
            c = harness.cycle()
        except RuntimeError as e:
            c = {"busy": str(e), "executed": []}
        did = [x for x in c["executed"] if x["outcome"] == "ok"]
        return {"done": not did, "kind": "cycle", "topic": f"cycle {c.get('cycle', '')}".strip(), "note": " · ".join(x["cmd"] for x in did),
                "cycle": c, "questions": char._open_questions(char._start())[::-1][:3], "graph": char.graph()}
    only = body.get("only")
    if only is not None and only not in char.SYS_OF:
        raise HTTPException(422, detail=f"no step called {only}")
    return char.rest(on_char=bool(body.get("char")), n=None if body.get("n") is None else int(body["n"]), force=bool(body.get("force")), only=only)


@router.get("/verse")
def verse_page() -> RedirectResponse:
    return RedirectResponse("/#verse")


@router.get("/verse/personas")
def verse_list() -> dict[str, Any]:
    return verse.personas()


@router.post("/verse/enter")
def verse_enter(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    try:
        p = verse.enter(str(body.get("name") or ""))
    except KeyError:
        raise HTTPException(404, detail="There is no persona by that name.")
    char._engine("persona", "ok", f"entered {p['name']}")
    return verse.personas()


@router.post("/verse/new")
def verse_new(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    who = str(body.get("who") or "").strip()
    if not who:
        raise HTTPException(422, detail="Name who it should become.")
    if who.startswith("/") or not any(c.isalpha() for c in who):  # a slash command typed in the wrong box once made a persona called "/Step"
        raise HTTPException(422, detail="That looks like a command, not someone to become.")
    _, said = char.become_persona(who)  # puts the live one away first, then looks the new one up
    return {**verse.personas(), "said": said}  # says so when the model was down and it got a generic voice


@router.post("/verse/reset")
def verse_reset(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    """Delete every persona and all they learned, then (when `then` names someone) become them fresh."""
    verse.reset_all()
    said = char.become_persona(str(body["then"]))[1] if body.get("then") else "reset"
    for p in verse.personas()["personas"]:  # becoming someone puts the blank placeholder away: it is not a persona of yours
        if not p["live"] and p["name"] == "Dot":
            verse.delete("Dot")
    return {**verse.personas(), "said": said}


@router.delete("/verse/personas/{name:path}")  # :path so a name with a "/" in it can still be deleted
def verse_delete(name: str) -> dict[str, Any]:
    try:
        verse.delete(name)
    except KeyError:
        raise HTTPException(404, detail="There is no persona by that name.")
    except ValueError as e:
        raise HTTPException(409, detail=str(e))
    return verse.personas()


@router.get("/char/chibi/refs")
def char_chibi_refs() -> dict[str, Any]:
    """Chibi pictures of the live persona from an image search, to pour Dot into."""
    p = char.get_profile()
    return {"refs": chibi.find_refs(p["name"], p["persona"])}


@router.post("/char/chibi/pick")
def char_chibi_pick(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    """Pour Dot into the picture at `url` (its `thumb` if the site refuses); an empty url goes back to the drawn look."""
    p = char.get_profile()
    try:
        return chibi.pick(p["name"], str(body.get("url") or ""), str(body.get("thumb") or ""), p["look"])
    except ValueError as e:
        raise HTTPException(422, detail=str(e))


@router.post("/char/chibi/cut")
def char_chibi_cut(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    """Trace round its picture's figure, so the background is left out; no outline goes back to cutting it out by itself."""
    try:
        return chibi.set_cut(char.get_profile()["name"], body.get("outline") or [])
    except ValueError as e:
        raise HTTPException(422, detail=str(e))


@router.post("/char/chibi/eyes")
def char_chibi_eyes(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    """Mark where its picture's eyes are, so it can blink and make faces with them; no eyes goes back to finding them by itself."""
    try:
        return chibi.set_eyes(char.get_profile()["name"], body.get("eyes") or [])
    except ValueError as e:
        raise HTTPException(422, detail=str(e))


@router.get("/char/chibi/saved")
def char_chibi_saved() -> dict[str, Any]:
    """The forms it has learned before, to switch between."""
    return {"refs": chibi.saved()}


@router.get("/char/chibi/image/{name}")
def char_chibi_image(name: str) -> FileResponse:
    if not re.fullmatch(r"[0-9a-f]{16}\.(png|jpg|webp|gif)", name) or not (chibi.image_dir() / name).is_file():
        raise HTTPException(404)
    return FileResponse(chibi.image_dir() / name)


@router.get("/char/chibi")
def char_chibi(name: str = "") -> dict[str, Any]:
    """The look Dot's chibi form takes for a persona (the live one by default), from a reference looked up on the web once and stored."""
    p = char.get_profile()
    if name and name != p["name"]:
        try:
            p = verse.profile(name)
        except KeyError:
            raise HTTPException(404, detail="There is no persona by that name.")
    return chibi.reference(p["name"], p["look"], p["persona"])


@router.get("/char/monitor")
def char_monitor() -> dict[str, Any]:
    return char.monitor()


@router.post("/char/tint")
def char_tint(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    tint = str(body.get("tint") or "")
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", tint):
        raise HTTPException(422, detail="Pick a colour.")
    p = char.get_profile()
    char.update_profile(p["name"], p["persona"], p["look"], tint)
    return char.state()


@router.get("/char/wiring")
def char_wiring() -> dict[str, Any]:
    return char.wiring()


@router.post("/char/wiring")
def char_wire(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    try:
        if body.get("correction"):
            char.set_correction(str(body["correction"]), bool(body.get("accept")))
            return char.wiring()
        if body.get("mode"):
            char.set_mode(str(body["mode"]))
            return char.wiring()
        return char.wire(str(body.get("text") or ""))
    except ValueError as e:
        raise HTTPException(400, detail=str(e))


@router.post("/char/correction")
def char_correction(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    try:
        char.answer_correction(str(body.get("text") or ""))
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    return char.wiring()


@router.post("/char/tracker")
def char_tracker(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    try:
        return char.set_tracker(body.get("sleep_at"), body.get("max"))
    except (TypeError, ValueError):
        raise HTTPException(422, detail="sleep_at and max must be numbers")


@router.delete("/char/correction")
def char_skip_correction() -> dict[str, Any]:
    char.skip_correction()
    return char.wiring()


@router.delete("/char/instructions/{note_id}")
def char_remove_instruction(note_id: int) -> dict[str, Any]:
    if not char.remove_instruction(note_id):
        raise HTTPException(404, detail="No such instruction.")
    return char.wiring()


@router.delete("/char/vars/{var_id}")
def char_remove_var(var_id: int) -> dict[str, Any]:
    if not char.remove_var(var_id):
        raise HTTPException(404, detail="That variable is gone.")
    return char.state()


@router.delete("/char")
def char_clear() -> dict[str, Any]:
    char.clear()
    return char.state()
