"""The paper as a mind map, like NotebookLM's, but every node says in a line or two what it means in this paper and
which page says it.

The local model makes it in steps, in the background: first the paper's main themes, then the points under each
theme, one theme a step. Each step is small (a small model keeps up), shows as progress, and is tried twice; a theme
that still fails is kept, marked as missing, and the rest of the map goes on. Stop closes the model's reply at once.
Every step sends the same paper first, so the model server reuses its cache and only reads the paper once. One map is
made at a time, so two runs never fight over the one model. The finished map is kept until you make it again."""
import json
import re
import logging
import threading
import time
from typing import Any

from shared import db, llm
from shared.settings import Settings
from pdf_research import answers, primer

log = logging.getLogger(__name__)

SYSTEM = ("You turn a research paper into a mind map for a student. Use simple English and the paper's own facts. "
          "Reply with JSON only.")
_SAY = ("say: one or two short sentences (at most 45 words) that explain it as this paper makes it, with a number, a name or a result "
        "from the paper when there is one, never just repeating the label; page: the number from the --- Page N --- "
        "line where the paper says it.")
OUTLINE = ("Give the root: label, what the paper is about in 3 to 10 words; say, the paper's main claim in one or two "
           "sentences. Then 4 to 6 branches: the paper's main themes, in the order a reader meets them (for example "
           f"the problem, the method, the data, the findings, the limits). Each branch: label, 2 to 6 plain words; {_SAY}")
POINTS = ('For the theme "{label}" ({say}), give 2 to 4 points under it: the concrete things the paper says about it. '
          f"Each point: label, 2 to 7 plain words; {_SAY} Leave out what belongs to the other themes: {{others}}.")

GROW = ('Go one level deeper on the point "{point}" ({say}), under the theme "{theme}". Give 2 to 4 finer points: the '
        "details, steps, numbers or examples the paper gives for it. Each point: label, 2 to 7 plain words; "
        f"{_SAY} Do not repeat these: {{others}}.")

_LEAF = {"type": "object", "properties": {"label": {"type": "string"}, "say": {"type": "string"}, "page": {"type": "integer"}},
         "required": ["label", "say", "page"], "additionalProperties": False}
OUTLINE_SCHEMA = {"type": "object", "properties": {"label": {"type": "string"}, "say": {"type": "string"},
                                                   "children": {"type": "array", "items": _LEAF}},
                  "required": ["label", "say", "children"], "additionalProperties": False}
POINTS_SCHEMA = {"type": "object", "properties": {"points": {"type": "array", "items": _LEAF}},
                 "required": ["points"], "additionalProperties": False}

TRIES = 2


class Stopped(Exception):
    pass


def _trim(text: str, most: int = 420) -> str:
    """Whole sentences up to `most` characters; a sentence never ends mid-word."""
    text = " ".join(text.split())
    if len(text) <= most:
        return text
    cut = text[:most]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return cut[:end + 1] if end > most // 3 else cut[:cut.rfind(" ")].rstrip(",;:") + "…"


def node(raw: Any, pages: int) -> dict[str, Any] | None:
    """A node the reader can trust: words trimmed, a page that exists or none. No label, no node."""
    if not isinstance(raw, dict) or not isinstance(raw.get("label"), str) or not raw["label"].strip():
        return None
    page = raw.get("page")
    label = re.sub(r"^(title|label|theme|point)\s*:\s*", "", " ".join(raw["label"].split()), flags=re.I)
    return {"label": label if len(label) <= 90 else label[:label.rfind(" ", 0, 90)] + "…", "say": _trim(str(raw.get("say") or "")),
            "page": page if isinstance(page, int) and not isinstance(page, bool) and 1 <= page <= pages else None,
            "children": []}


def load(paper_id: str) -> dict[str, Any] | None:
    con = db.connect()
    try:
        r = con.execute("SELECT tree, model, created_at FROM mind_maps WHERE paper_id = ?", (paper_id,)).fetchone()
        return {"tree": json.loads(r["tree"]), "model": r["model"], "made": r["created_at"]} if r else None
    finally:
        con.close()


def _save(paper_id: str, tree: dict[str, Any], model: str) -> None:
    con = db.connect()
    try:
        with con:
            con.execute("INSERT OR REPLACE INTO mind_maps (paper_id, tree, model, created_at) VALUES (?, ?, ?, datetime('now'))",
                        (paper_id, json.dumps(tree), model))
    finally:
        con.close()


# ---------- the run ----------
_runs: dict[str, dict[str, Any]] = {}  # paper id -> its latest run (in memory: a restart forgets a run, never a kept map)
_lock = threading.Lock()


def _busy() -> str:
    return "A mind map is being made. Stop it on the Map, or wait for it, then switch." if any(r["state"] == "making" for r in _runs.values()) else ""


llm.busy.append(_busy)


def status(paper_id: str) -> dict[str, Any] | None:
    """The run as the reader sees it: state (making, done, stopped, failed), step of steps, what it is on, how much
    the model has written in this step, the map so far, and what failed."""
    r = _runs.get(paper_id)
    if not r:
        return None
    with _lock:
        return {k: (json.loads(json.dumps(v)) if k == "tree" else v) for k, v in r.items() if k != "stop"} | \
               {"seconds": round((r.get("ended") or time.time()) - r["started"])}


def start(s: Settings, paper_id: str, title: str, pages: list[str], grow: tuple[str, str] | None = None) -> dict[str, Any]:
    """Starts a run unless one is going: the whole map, or with grow=(theme, point) one level deeper under that point
    of the kept map. Raises ValueError if another map is being made, LookupError if there is no such point."""
    tree = None
    if grow:
        tree = (load(paper_id) or {}).get("tree")
        if not _point(tree, *grow):
            raise LookupError("That point is not on the map any more. Open the map again.")
    with _lock:
        busy = next((p for p, r in _runs.items() if r["state"] == "making"), None)
        if busy and busy != paper_id:
            raise ValueError("A mind map for another paper is being made. Stop it first, or wait for it.")
        if busy and grow:
            raise ValueError("Dot is still working on this map. Wait for it, or stop it.")
        if not busy:
            _runs[paper_id] = {"state": "making", "step": 0, "of": 1, "doing": grow[1] if grow else "Finding the paper's main themes",
                               "written": 0, "tree": tree, "grow": list(grow) if grow else None, "failed": [], "error": "",
                               "started": time.time(), "ended": None, "stop": threading.Event()}
            work = _grow if grow else _run
            threading.Thread(target=_guard, args=(work, s, paper_id, title, pages, _runs[paper_id]), daemon=True).start()
    return status(paper_id) or {}


def _point(tree: dict[str, Any] | None, theme: str, point: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    b = next((x for x in (tree or {}).get("children", []) if x["label"] == theme), None)
    p = next((x for x in (b or {}).get("children", []) if x["label"] == point), None)
    return (b, p) if p else None


def stop(paper_id: str) -> bool:
    r = _runs.get(paper_id)
    if not r or r["state"] != "making":
        return False
    r["stop"].set()
    return True


def _ask(s: Settings, r: dict[str, Any], paper: str, task: str, schema: dict[str, Any], name: str) -> dict[str, Any]:
    """One step: the paper, then the task. Broken JSON is asked once more. Raises Stopped or primer.PrimerError."""
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": f"{paper}\n\n{task}"}]

    def watch(text: str) -> bool:
        r["written"] = len(text)
        return not r["stop"].is_set()
    last = "The model's answer was not a mind map."
    for _ in range(TRIES):
        r["written"] = 0
        try:
            reply = primer._complete(s, msgs, schema, name, watch)
            return json.loads(reply[reply.find("{"):reply.rfind("}") + 1])
        except primer.PrimerError as e:
            if r["stop"].is_set():
                raise Stopped from e
            last = str(e)
            if "reach the model" in last or "API key" in last or "holds only" in last:
                break  # asking again cannot help
        except ValueError:
            continue
    raise primer.PrimerError(last)


def _paper(s: Settings, title: str, pages: list[str]) -> str:
    longest = OUTLINE + POINTS + GROW + " " * 400
    body, _ = answers.paper_text(s, pages, 0, SYSTEM + title + longest)  # the same text every step: the server's cache
    return f"Paper: {title}\n\n<paper>\n{body}\n</paper>"


def _guard(work: Any, s: Settings, paper_id: str, title: str, pages: list[str], r: dict[str, Any]) -> None:
    """Every run ends: done, stopped or failed, with words the reader can act on."""
    try:
        work(s, paper_id, title, pages, r)
        with _lock:
            r.update(state="done", step=r["of"], doing="", written=0)
    except Stopped:
        with _lock:
            r.update(state="stopped", doing="")
    except primer.PrimerError as e:
        with _lock:
            r.update(state="failed", error=str(e), doing="")
    except Exception:  # a bug must not leave the reader waiting on a run that never ends
        log.exception("mind map for %s", paper_id)
        with _lock:
            r.update(state="failed", error="Something went wrong while making the map. Try again.", doing="")
    finally:
        r["ended"] = time.time()


def _grow(s: Settings, paper_id: str, title: str, pages: list[str], r: dict[str, Any]) -> None:
    theme, point = r["grow"]
    b, p = _point(r["tree"], theme, point) or (None, None)
    if not p:
        raise primer.PrimerError("That point is not on the map any more.")
    others = "; ".join([point, *(x["label"] for x in b["children"] if x is not p)])
    got = _ask(s, r, _paper(s, title, pages), GROW.format(point=point, say=p["say"] or "no detail", theme=theme, others=others),
               POINTS_SCHEMA, "mind_map_grow")
    kids = [k for raw in (got.get("points") or [])[:4] if (k := node(raw, len(pages)))]
    if not kids:
        raise primer.PrimerError("The model gave no finer points for this. Try Grow again.")
    with _lock:
        p["children"] = kids
    _save(paper_id, r["tree"], llm.pick_model(s))


def _run(s: Settings, paper_id: str, title: str, pages: list[str], r: dict[str, Any]) -> None:
    def check() -> None:
        if r["stop"].is_set():
            raise Stopped
    paper = _paper(s, title, pages)
    got = _ask(s, r, paper, OUTLINE, OUTLINE_SCHEMA, "mind_map_outline")
    root = node(got, len(pages)) or {"label": title, "say": "", "page": None, "children": []}
    root["label"] = root["label"] or title
    root["children"] = [b for raw in (got.get("children") or [])[:6] if (b := node(raw, len(pages)))]
    if not root["children"]:
        raise primer.PrimerError("The model did not find the paper's main themes. Try again, or try a larger model.")
    with _lock:
        r.update(tree=root, step=1, of=1 + len(root["children"]))
    errors = []
    for i, b in enumerate(root["children"]):
        check()
        with _lock:
            r.update(step=i + 1, doing=b["label"], written=0)
        others = "; ".join(x["label"] for x in root["children"] if x is not b)
        try:
            got = _ask(s, r, paper, POINTS.format(label=b["label"], say=b["say"] or "no detail", others=others),
                       POINTS_SCHEMA, "mind_map_points")
            kids = [k for raw in (got.get("points") or [])[:4] if (k := node(raw, len(pages)))]
            if not kids:
                raise primer.PrimerError("The model gave no points for this theme.")
        except primer.PrimerError as e:
            errors.append(str(e))
            with _lock:
                b["missing"] = True
                r["failed"].append(b["label"])
            continue
        with _lock:
            b["children"] = kids
    if len(errors) == len(root["children"]):
        raise primer.PrimerError(errors[-1])  # nothing filled in: most likely the model went away
    _save(paper_id, root, llm.pick_model(s))
