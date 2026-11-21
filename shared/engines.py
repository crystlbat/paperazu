"""Engines: the ways this Mac runs models (Dory on its own llama.cpp build, Unsloth Studio, and whatever comes next),
listed on Model connection. Picking one writes its URL, key, models and role models into the live settings.

Picking is refused while a model swap runs (the swap lock in llm) or while a part of the app is in the middle of
model work (each part says so through llm.busy). A llama.cpp server keeps its model in memory after you switch
away, so the reply says so: only one model should be loaded at a time."""
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from openai import APIConnectionError, APIStatusError, AuthenticationError

from shared import llm, settings, steer
from shared.settings import ENGINE_KEYS, PER_SERVER, Engine, Settings


class Busy(Exception):
    """Switching now would pull the model from under running work. The message says what is running."""


def _seeds(s: Settings) -> list[dict[str, Any]]:
    """The first engines: the two setups on this Mac. The one the settings point at takes the live values."""
    seeds = [
        Engine(id="dory", name="Dory", kind="llama.cpp", note="Your own llama.cpp build (~/llama.cpp-dory). One model per server.",
               values={"base_url": "http://127.0.0.1:8080/v1", "model_name": "dory"}),
        Engine(id="unsloth", name="Unsloth Studio", kind="unsloth", note="Loads and swaps models on demand. Role models swap here.",
               values={"base_url": "http://127.0.0.1:8888/v1", "api_key": s.api_key}),
        *([_mlx(s)] if steer.available() else []),
    ]
    out = [e.model_dump() for e in seeds]
    live = {k: getattr(s, k) for k in ENGINE_KEYS}
    here = next((e for e in out if e["values"]["base_url"] == s.base_url), None)
    if here:
        here["values"] = live
    else:  # settings pointing somewhere else become an engine of their own, so nothing typed is lost
        out.append(Engine(id="mine", name="My server", values=live).model_dump())
    return out


def _mlx(s: Settings) -> Engine:
    return Engine(id="mlx", name="Steer (MLX)", kind="mlx", note="Runs in this process, so its hidden states can be steered. Embeddings stay on Unsloth.",
                  values={"base_url": "http://127.0.0.1:8888/v1", "api_key": s.api_key, "model_name": llm.STEER})


def ensure_seeded() -> Settings:
    s = settings.get_all()
    if s.engines:
        if steer.available() and not any(e.get("kind") == "mlx" for e in s.engines):
            # shortcut: engines saved before the mlx kind get it added once; removing it brings it back, add a "dismissed" list if that annoys
            s = settings.update({"engines": [*s.engines, _mlx(s).model_dump()]})
        return s
    seeds = _seeds(s)
    here = next(e["id"] for e in seeds if e["values"].get("base_url") == s.base_url)
    return settings.update({"engines": seeds, "engine": here})


def _probe(s: Settings, e: dict[str, Any]) -> dict[str, Any]:
    """Is the engine's server up, and what does it have loaded? Never raises."""
    if e["kind"] == "mlx":  # no server to ask: it is ready when MLX is installed, loaded once a call needs it
        name = e["values"].get("model_name") or llm.STEER
        on = steer.loaded() and llm.mlx_loaded() == name
        return {"status": "ready", "label": "Loaded" if on else "Loads when needed", "models": [name], "loaded": [name] if on else []}
    t = s.model_copy(update=e["values"])
    try:
        listed = list(llm.client(t, timeout=3).models.list())
    except AuthenticationError:
        return {"status": "wrong_key", "label": "Wrong API key", "models": [], "loaded": []}
    except APIConnectionError:
        return {"status": "not_running", "label": "Not running", "models": [], "loaded": []}
    except APIStatusError as ex:
        return {"status": "error", "label": f"Server error {ex.status_code}", "models": [], "loaded": []}
    except Exception:
        return {"status": "error", "label": "Could not ask the server", "models": [], "loaded": []}
    ids = [m.id for m in listed]
    loaded = [m.id for m in listed if getattr(m, "loaded", False)] if e["kind"] == "unsloth" else ids
    return {"status": "ready", "label": f"{len(loaded)} loaded" if e["kind"] == "unsloth" else "Running", "models": ids, "loaded": loaded}


def public(e: dict[str, Any]) -> dict[str, Any]:
    """An engine for the page: its key is never sent back, only whether it has one."""
    v = {k: x for k, x in e["values"].items() if k != "api_key"}
    return {**e, "values": v, "has_key": bool(e["values"].get("api_key"))}


def listing() -> dict[str, Any]:
    s = ensure_seeded()
    with ThreadPoolExecutor(max_workers=max(1, len(s.engines))) as ex:
        states = list(ex.map(lambda e: _probe(s, e), s.engines))
    return {"active": s.engine, "busy": busy(),
            "swap": {**llm.SWAP, "locked": llm.swap_locked()},
            "engines": [{**public(e), **st} for e, st in zip(s.engines, states)]}


def busy() -> str:
    """Why switching now would hurt, or "" if it would not."""
    if llm.swap_locked():
        return f"A model swap is going on ({llm.SWAP.get('from') or 'nothing'} to {llm.SWAP.get('to')}). Switch when it ends."
    return next((why for check in llm.busy if (why := check())), "")


def use(eid: str) -> dict[str, Any]:
    """Make an engine the live one. Raises KeyError (no such engine) or Busy."""
    s = ensure_seeded()
    e = next((x for x in s.engines if x["id"] == eid), None)
    if not e:
        raise KeyError(eid)
    if why := busy():
        raise Busy(why)
    before = next((x for x in s.engines if x["id"] == s.engine), None)
    patch = {**{k: "" for k in PER_SERVER}, **e["values"], "engine": eid}
    new = settings.update(patch)
    llm.forget()
    note = ""
    if before and before["id"] != eid and before["kind"] == "mlx" and steer.unload():  # its model leaves memory with it
        llm.on_engine("model", "ok", "steer engine unloaded")
    if before and before["id"] != eid and before["kind"] == "llama.cpp":
        note = f"{before['name']} keeps its model in memory until you stop its server. Stop it before loading a model on {e['name']}."
    return {"settings": new.model_dump(), "note": note}


def save(body: dict[str, Any]) -> dict[str, Any]:
    """Add an engine, or change one (same id). An empty key keeps the key it had. Raises ValueError or ValidationError."""
    s = ensure_seeded()
    body = dict(body)
    body.setdefault("id", re.sub(r"[^a-z0-9]+", "-", str(body.get("name", "")).lower()).strip("-")[:32] or "engine")
    old = next((x for x in s.engines if x["id"] == body["id"]), None)
    values = {k: v for k, v in (body.get("values") or {}).items()}
    if not values.get("api_key") and old and old["values"].get("api_key"):
        values["api_key"] = old["values"]["api_key"]
    body["values"] = {k: v for k, v in values.items() if v not in ("", None)}
    if "base_url" not in body["values"]:
        raise ValueError("An engine needs a URL.")
    e = Engine(**body).model_dump()
    Settings(**{**s.model_dump(), **e["values"]})  # its values must be valid settings
    engines = [e if x["id"] == e["id"] else x for x in s.engines] if old else [*s.engines, e]
    patch: dict[str, Any] = {"engines": engines}
    if s.engine == e["id"]:  # the engine in use changed: the live values follow
        patch.update({**{k: "" for k in PER_SERVER}, **e["values"]})
    settings.update(patch)
    llm.forget()
    return public(e)


def remove(eid: str) -> bool:
    s = ensure_seeded()
    if eid == s.engine:
        raise ValueError("This engine is in use. Pick another one first.")
    if not any(x["id"] == eid for x in s.engines):
        return False
    settings.update({"engines": [x for x in s.engines if x["id"] != eid]})
    return True
