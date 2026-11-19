"""Browse: you give the character a web task; it plans, you steer the plan, then it uses a real browser inside its world.
Chrome runs out of sight with its own throwaway profile; its live picture streams onto the screen Dot turns into, its sound plays
from the Mac, and Dot moves to what it clicks. Like the harness cycle: a planner model call writes commands, the checker (plain code)
rejects what cannot work before the run and marks each step done or failed after it, and the run ends with its opinion."""
import base64
import json
import queue
import re
import threading
import time
import urllib.parse
from collections.abc import Callable, Iterator
from typing import Any

from harness_char import char
from shared import db, llm, settings
from pdf_research import jobs

# the commands, as data: name -> (what its argument is, what it does). A new command is a line here and a branch in _step.
COMMANDS = {"open": ("web address", "open a web page"),
            "search": ("words", "type words into this site's search box, or search the web if no page is open"),
            "click": ("what, in words", "click a link or button, said in words, like: the first video"),
            "play": ("", "play the video or song on this page"),
            "wait": ("seconds", "let it play or load, up to 60 seconds"),
            "read": ("words", "read the part of the page about these words"),
            "scroll": ("", "scroll down and read what shows"),
            "opinion": ("", "tell the person what it did and what it thinks")}
MAX_STEPS = 10
MAX_CLICKS = 4
READ_CHARS = 1200  # what one read hands the model
W, H = 1280, 800  # the browser's viewport: boxes go to the page as fractions of it
AIM = 1.0  # seconds between showing what it will click and clicking it, so Dot gets there on the screen first

RUN: dict[str, Any] = {}  # the browse in hand, read by GET /char/browse. shortcut: in memory like the training lanes; a restart forgets it
_lock = threading.Lock()  # one browse at a time
_stop = threading.Event()


def lessons(n: int = 4) -> list[str]:
    """Its last slips while browsing, in words: every plan is told them, so it does not repeat them. The feedbacker (char._fail) keeps
    them as "Fail: browse" rows; after two it drafts a fix for the browse prompt, which reaches the prompt once you approve it in Wiring."""
    con = db.connect()
    rows = con.execute("SELECT content FROM char_memories WHERE source = 'sheet' AND title = 'Fail: browse' AND id > ? ORDER BY id DESC LIMIT ?", (char._start(), n)).fetchall()
    con.close()
    return [r["content"] for r in rows]


def active() -> bool:
    """Planning or browsing: the model is in use. A browser left open playing a song is not."""
    return RUN.get("status") in ("planning", "running")


llm.busy.append(lambda: "It is browsing. Switch when it ends." if active() else "")


# ---- the browser ----
class Driver:
    """Owns Playwright on one thread (its sync API must stay on one): Chrome off screen, its frames kept for the live view.
    Between calls the thread keeps pumping events, so the picture keeps moving while the model thinks."""

    ARGS = ["--window-position=-3000,-3000", f"--window-size={W},{H + 60}", "--autoplay-policy=no-user-gesture-required",
            "--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding", "--disable-background-timer-throttling"]

    def __init__(self) -> None:
        self.q: queue.Queue[tuple[Callable[[Any], Any], dict[str, Any]]] = queue.Queue()
        self.frame, self.n, self.page, self.err = b"", 0, None, ""
        self.closed, ready = threading.Event(), threading.Event()
        self.t = threading.Thread(target=self._loop, args=(ready,), daemon=True, name="browse-chrome")
        self.t.start()
        ready.wait(60)
        if self.err or not self.page:
            raise RuntimeError(f"Chrome would not start: {self.err or 'it took too long'}")

    def alive(self) -> bool:
        return self.t.is_alive() and not self.closed.is_set()

    def _cast(self, page: Any) -> None:
        self.page = page
        cdp = page.context.new_cdp_session(page)

        def frame(e: dict[str, Any]) -> None:
            if page is self.page:
                self.frame, self.n = base64.b64decode(e["data"]), self.n + 1
            cdp.send("Page.screencastFrameAck", {"sessionId": e["sessionId"]})

        cdp.on("Page.screencastFrame", frame)
        cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 60, "maxWidth": W, "maxHeight": H})

    def _loop(self, ready: threading.Event) -> None:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                browser = pw.chromium.launch(channel="chrome", headless=False, args=self.ARGS)  # its own temporary profile, never yours
                ctx = browser.new_context(viewport={"width": W, "height": H})
                ctx.on("page", lambda p: self._cast(p))  # a link that opens a new tab: the screen follows it
                self._cast(ctx.new_page())
                ready.set()
                while not self.closed.is_set():
                    try:
                        fn, box = self.q.get(timeout=0.03)
                    except queue.Empty:
                        self.page.wait_for_timeout(30)  # pumps the screencast
                        continue
                    try:
                        box["ok"] = fn(self.page)
                    except Exception as e:
                        box["err"] = e
                    box["done"].set()
                browser.close()
        except Exception as e:
            self.err = str(e).splitlines()[0][:200]
        finally:
            self.closed.set()
            ready.set()

    def call(self, fn: Callable[[Any], Any], timeout: float = 90) -> Any:
        if not self.alive():
            raise RuntimeError("the browser was closed")
        box: dict[str, Any] = {"done": threading.Event()}
        self.q.put((fn, box))
        if not box["done"].wait(timeout):
            raise RuntimeError("the browser stopped answering")
        if "err" in box:
            raise RuntimeError(str(box["err"]).splitlines()[0][:200])
        return box["ok"]

    def close(self) -> None:
        self.closed.set()


DRIVER: dict[str, Any] = {}


def launch() -> Any:
    """The browser, started on first use and kept between browses (and after one, so a song keeps playing). Tests replace this."""
    d = DRIVER.get("d")
    if not d or not d.alive():
        d = DRIVER["d"] = Driver()
    return d


def close_browser() -> dict[str, Any]:
    if d := DRIVER.pop("d", None):
        d.close()
    return status()


def frames() -> Iterator[bytes]:
    """The live view as MJPEG: each new frame of the browser, for an <img> on Dot's screen."""
    d, n, t0 = DRIVER.get("d"), -1, time.time()
    while d and d.alive() and time.time() - t0 < 3600:
        if d.n != n and d.frame:
            n = d.n
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + d.frame + b"\r\n"
        time.sleep(0.04)


# page actions: run on the browser's thread, so they take the page
def _settle(p: Any) -> None:
    try:
        p.wait_for_load_state("domcontentloaded", timeout=10000)
    except Exception:
        pass
    p.wait_for_timeout(900)
    for say in ("Reject all", "Reject", "Decline"):  # a cookie wall: the most private choice, as you would
        b = p.locator(f"button:has-text('{say}')")
        if b.count():
            try:
                b.first.click(timeout=2000)
                p.wait_for_timeout(600)
            except Exception:
                pass
            break


def _where(p: Any) -> dict[str, str]:
    return {"url": p.url, "title": p.title()}


def _box(el: Any) -> list[float] | None:
    b = el.bounding_box()
    return [round(b["x"] / W, 4), round(b["y"] / H, 4), round(b["width"] / W, 4), round(b["height"] / H, 4)] if b else None


CLICKABLES = """() => { document.querySelectorAll('[data-dot-i]').forEach((e) => e.removeAttribute('data-dot-i')); const out = []; let i = 0;
  for (const e of document.querySelectorAll('a[href], button, [role=button], [role=link], input[type=submit]')) {
    const r = e.getBoundingClientRect(), s = getComputedStyle(e); if (r.width < 4 || r.height < 4 || r.bottom < 0 || r.top > innerHeight * 2.5 || s.visibility === 'hidden') continue;
    if (e.closest('nav, header, aside, [role=navigation], [role=banner], #guide')) continue;  // menus crowd out what the page is about
    const t = (e.innerText || e.getAttribute('aria-label') || e.title || '').replace(/\\s+/g, ' ').trim(); if (t.length < 2) continue;
    const href = e.href ? new URL(e.href).pathname + new URL(e.href).search : '';
    e.setAttribute('data-dot-i', String(i)); out.push({ i, text: t.slice(0, 100), to: href.slice(0, 60) }); if (++i >= 80) break; }
  return out; }"""
PLAY = """async () => { const v = [...document.querySelectorAll('video')].sort((a, b) => b.clientWidth - a.clientWidth)[0]; if (!v) return null;
  v.muted = false; try { await v.play(); } catch (e) { return { err: String(e) }; } return { ok: true }; }"""
PLAYING = """() => { const v = [...document.querySelectorAll('video')].sort((a, b) => b.clientWidth - a.clientWidth)[0];
  return v ? { playing: !v.paused && v.currentTime > 0, ad: !!document.querySelector('.ad-showing') } : null; }"""


def _search_box(p: Any) -> Any:
    el = p.locator("input[type=search], input[name=search_query], input[name=q], input[name=search], input[aria-label*='Search' i], textarea[name=q]")
    return el.first if el.count() else None


def _chunks(text: str) -> list[str]:
    out, cur = [], ""
    for ln in (x.strip() for x in text.splitlines()):
        if not ln:
            continue
        if len(cur) + len(ln) > READ_CHARS and cur:
            out.append(cur.strip())
            cur = ""
        cur += ln + "\n"
    return out + ([cur.strip()] if cur.strip() else [])


# ---- recipes: how to do things on a site, written down. It writes one when a browse works; you can read, change or teach them ----
def site_of(text: str) -> str:
    """youtube.com from https://www.youtube.com/watch?v=x, or from "youtube.com"."""
    return urllib.parse.urlparse(_url(text)).netloc.lower().removeprefix("www.")


def recipes() -> list[dict[str, Any]]:
    con = db.connect()
    rows = con.execute("SELECT id, title, content, created_at FROM char_memories WHERE source = 'sheet' AND title LIKE 'Recipe: %' AND id > ? ORDER BY id DESC", (char._start(),)).fetchall()
    con.close()
    out: dict[str, dict[str, Any]] = {}
    for r in rows:  # the newest row of a site is its recipe
        out.setdefault(r["title"].removeprefix("Recipe: "), {"site": r["title"].removeprefix("Recipe: "), "at": r["created_at"], **json.loads(r["content"])})
    return list(out.values())


def _forget(site: str) -> int:
    con = db.connect()
    with con:
        n = con.execute("DELETE FROM char_memories WHERE source = 'sheet' AND title = ? AND id > ?", (f"Recipe: {site}", char._start())).rowcount
    con.close()
    return n


def save_recipe(site: str, steps: str, by: str = "you", task: str = "", worked: int = 0) -> dict[str, Any]:
    """A recipe is checked like a plan: its steps must be commands it knows. Yours are never overwritten by what it learns."""
    if not (host := site_of(site)):
        raise ValueError("Say which site it is for, like youtube.com.")
    from harness_char import harness
    cmds, bad = harness.parse(steps or "")
    plan, rejected = validate([{"name": c["name"], "arg": c["arg"]} for c in cmds], need_page=False)
    plan = [p for p in plan if p["name"] != "opinion"]
    if bad or rejected or not plan:
        why = "; ".join([f"{r['cmd']} ({r['why']})" for r in rejected] + [f"{b} (not a command)" for b in bad]) or "it has no steps"
        raise ValueError(f"I can't follow that recipe: {why}. Steps it knows: {', '.join(COMMANDS)}.")
    _forget(host)
    rec = {"steps": plan_text(plan), "by": by, "task": task[:200], "worked": worked}
    char.add_memory(f"Recipe: {host}", json.dumps(rec), source="sheet")
    return {"site": host, **rec}


def forget_recipe(site: str) -> bool:
    return bool(_forget(site_of(site) or site))


def recipes_for(task: str) -> list[dict[str, Any]]:
    """The recipes for the sites a task names: "youtube" in the task finds youtube.com."""
    t = task.lower()
    return [r for r in recipes() if r["site"] in t or r["site"].split(".")[-2 if r["site"].count(".") else 0] in t]


def _learn() -> str:
    """A browse that worked end to end becomes its site's recipe, with the words of this task left as blanks to fill next time."""
    steps = [s for s in RUN["steps"] if s["cmd"] != "opinion"]
    opened = next((p["arg"] for p in RUN["plan"] if p["name"] == "open"), "")
    if RUN["status"] != "done" or not opened or any(s["status"] != "ok" for s in steps):
        return ""
    host = site_of(opened)
    old = next((r for r in recipes() if r["site"] == host), None)
    if old and old["by"] == "you":  # your recipe stays as you wrote it; it only counts that it worked
        save_recipe(host, old["steps"], "you", old.get("task", ""), old.get("worked", 0) + 1)
        return host
    blank = {"search": "<what you want>", "read": "<what you want>"}
    lines = [f"{p['name']} {blank.get(p['name'], p['arg'])}".strip() for p in RUN["plan"] if p["name"] != "opinion"]
    save_recipe(host, "\n".join(lines), "learned", RUN["task"], (old or {}).get("worked", 0) + 1)
    return host


# ---- the checker, before the run ----
def _url(arg: str) -> str:
    """The web address in the words, wherever it sits ("a web address: open youtube.com"); a bare "youtube.com" means https."""
    m = re.search(r"https?://[^\s<>\"']+|\b[\w-]+(?:\.[\w-]+)*\.[a-z]{2,}\b(?:/[^\s<>\"']*)?", arg or "")
    a = m[0].rstrip(",;)") if m else ""
    return a if a.startswith("http") else f"https://{a}" if a else ""


def home(url: str) -> str:
    m = re.match(r"(https?://[^/]+)", url)
    return (m[1] if m else url) + "/"


def validate(cmds: list[dict[str, str]], need_page: bool = True) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """No model: each command must exist, have what it needs, fit the budget; opinion goes last, once. Returns (plan, rejected with why)."""
    plan: list[dict[str, str]] = []
    rejected: list[dict[str, str]] = []
    clicks = 0
    for c in cmds:
        name, arg, why = c["name"], c.get("arg", "") if c["name"] == "open" else re.split(r"[\"']?\s*:\s", c.get("arg", ""))[0].strip("\"' "), ""  # repair, as the harness does: a small planner glues its explanation after the argument
        if name not in COMMANDS:
            why = "unknown command"
        elif name == "opinion":
            continue  # added at the end, always
        elif name == "open" and not (arg := _url(arg)):
            why = "no web address to open"
        elif name in ("search", "click") and not arg:
            why = f"{name} needs {COMMANDS[name][0]}"
        elif name == "wait" and not (arg := str(max(1, min(60, int(m[0])))) if (m := re.search(r"\d+", arg or "5")) else ""):
            why = "wait needs a number of seconds"
        elif name == "click" and (clicks := clicks + 1) > MAX_CLICKS:
            why = f"at most {MAX_CLICKS} clicks per browse"
        elif need_page and name in ("click", "play", "read", "scroll") and not any(p["name"] in ("open", "search") for p in plan):
            why = "no page is open yet"
        elif len(plan) >= MAX_STEPS - 1:
            why = f"over budget ({MAX_STEPS} steps)"
        if why:
            rejected.append({"cmd": _text(c), "why": why})
        else:
            plan.append({"name": name, "arg": arg})
    return plan + [{"name": "opinion", "arg": ""}], rejected


def _text(c: dict[str, str]) -> str:
    return c["name"] + (f" {c['arg']}" if c.get("arg") else "")


def plan_text(plan: list[dict[str, str]]) -> str:
    return "\n".join(_text(p) for p in plan)


# ---- model calls ----
def _complete(messages: list[dict[str, str]], max_tokens: int, kind: str) -> str:
    try:
        out = (jobs.complete(settings.get_all(), messages, max_tokens=max_tokens) or "").strip()
    except Exception as e:
        char._log(f"browse {kind}", messages, f"(failed: {e})")
        raise RuntimeError(f"I can't reach the model: {e}") from None
    char._log(f"browse {kind}", messages, out)
    return out


def _plan(task: str, note: str = "") -> tuple[str, list[dict[str, str]], list[dict[str, str]]]:
    who = char.get_profile()["name"]
    cat = "\n".join(f"- {k}{' <' + a + '>' if a else ''}: {d}" for k, (a, d) in COMMANDS.items())
    msgs = [{"role": "system", "content": f"You are {who}. You are about to use a web browser for the person's task. First line: Intent: one sentence on what you "
                                          f"will open, what you will do there and why. Then at most {MAX_STEPS} commands, one per line: the command name, a space, "
                                          "then its argument. End with opinion. No other text." + char._fix("browse")},
            {"role": "user", "content": f"Task: {task}\n\nCommands:\n{cat}" + (f"\n\nThe person steers you: {note}" if note else "") +
                                        ("".join(f"\n\nYour recipe for {r['site']} (it worked {r['worked']} times; follow it, filling in the <...>):\n{r['steps']}" for r in recipes_for(task)[:3])) +
                                        ("\n\nWhat went wrong before (do not repeat it):\n" + "\n".join(f"- {x}" for x in lessons()) if lessons() else "")}]
    said = _complete(msgs, 220, "plan")
    intent = next((m[1].strip() for m in re.finditer(r"(?im)^\W*intent\W+(.+)$", said)), "")
    from harness_char import harness  # harness imports char; parse is the same lenient reader the cycle uses
    cmds, bad = harness.parse("\n".join(ln for ln in said.splitlines() if not re.match(r"(?i)^\W*intent\b", ln)))
    plan, rejected = validate([{"name": c["name"], "arg": c["arg"]} for c in cmds])
    return intent or f"I'll look into: {task}", plan, rejected + [{"cmd": b, "why": "could not read it as a command"} for b in bad]


def _pick(want: str, items: list[dict[str, Any]]) -> int | None:
    """Which of the page's links and buttons it means: by its words when they match, else the model picks from the list."""
    w = want.lower().strip()
    for it in items:
        if it["text"].lower() == w:
            return it["i"]
    if len(w) > 3:
        for it in items:
            if w in it["text"].lower():
                return it["i"]
    msgs = [{"role": "system", "content": "You pick what to click on a web page. Each item is its words, then where it leads. Reply with the number of the item only."},
            {"role": "user", "content": f"Task: {RUN.get('task', '')}\nClick: {want}\n\n" + "\n".join(f"{it['i']}. {it['text']}" + (f" → {it['to']}" if it.get("to") else "") for it in items)}]
    said = _complete(msgs, 8, "click")
    m = re.search(r"\d+", said)
    return int(m[0]) if m and any(it["i"] == int(m[0]) for it in items) else None


def _think(sec: str) -> str:
    who = char.get_profile()["name"]
    msgs = [{"role": "system", "content": f"You are {who}, using a web browser for the person. In one or two short sentences, in your own voice, say what you "
                                          "notice here that matters for the task. Only what the text says." + char._fix("browse")},
            {"role": "user", "content": f"Task: {RUN.get('task', '')}\nPage: {RUN.get('title', '')}\n\n{sec[:READ_CHARS]}"}]
    return _complete(msgs, 120, "read")


def _opinion(task: str, read: list[dict[str, str]]) -> str:
    who = char.get_profile()["name"]
    did = "\n".join(f"- {s['cmd']}: {s['status']}, {s['detail']}" for s in RUN["steps"] if s["status"] in ("ok", "failed"))
    msgs = [{"role": "system", "content": f"You are {who}. Tell the person, in three or four sentences in your own voice, what you did and what you think, "
                                          "from what happened only. If it did not work, say so." + char._fix("browse")},
            {"role": "user", "content": f"Task: {task}\n\nWhat you did:\n{did}\n\nWhat you read:\n" +
                                        ("\n".join(f"- {r['page']}: {r['thought']}\n  ({r['text'][:400]})" for r in read) or "- nothing")}]
    return _complete(msgs, 220, "opinion")


def grounding(opinion: str, seen: str) -> float:
    """The share of the opinion's names that what it saw also has: a name from nowhere is the model making it up (as reflect scores a note)."""
    named = set(re.findall(r"(?<=[a-z,;] )[A-Z][a-z]{2,}", opinion))
    return round(sum(n in seen for n in named) / len(named), 2) if named else 1.0


# ---- the run ----
def _set_step(i: int, **kw: Any) -> None:
    RUN["steps"][i].update(kw)


def _at(d: Any) -> None:
    RUN.update(d.call(_where))


def _aim(i: int, box: list[float] | None, what: str) -> None:
    """Shows where it will act, then waits a beat so Dot can get there on the screen."""
    if box:
        _set_step(i, box=box, detail=what)
        time.sleep(AIM)


def _step(i: int, p: dict[str, str], read: list[dict[str, str]], d: Any) -> None:
    """Run one command and check it: the step ends ok or failed, with why. Raises RuntimeError only when the model is down."""
    name, arg = p["name"], p["arg"]
    try:
        if name == "open":
            _set_step(i, detail=f"opening {arg}", url=arg)
            code = d.call(lambda pg: ((r := pg.goto(arg, wait_until="domcontentloaded", timeout=30000)), _settle(pg))[0] and r.status)
            _at(d)
            RUN["chunks"], RUN["done"] = None, []
            if (code or 0) >= 400 or re.search(r"\b(?:404|not found)\b", RUN["title"], re.I):  # an error page is not the page it meant
                return _set_step(i, status="failed", detail=f"that address does not exist (the site said {code or 404}): open {home(arg)} and search there instead", url=RUN["url"])
            return _set_step(i, status="ok", detail=f"opened “{RUN['title'] or RUN['url']}”", url=RUN["url"])
        if name == "search":
            box = d.call(lambda pg: (b := _search_box(pg)) and _box(b)) if RUN.get("url") else None
            if not box:  # no page, or a page with no search box: the web's own search
                url = "https://duckduckgo.com/?q=" + "+".join(arg.split())
                _set_step(i, detail=f"searching the web for “{arg}”", url=url)
                d.call(lambda pg: (pg.goto(url, wait_until="domcontentloaded", timeout=30000), _settle(pg)))
            else:
                _aim(i, box, f"typing “{arg}” into the search box")
                before = RUN["url"]
                d.call(lambda pg: (b := _search_box(pg), b.click(timeout=5000), b.fill(arg, timeout=5000), b.press("Enter"), _settle(pg)))
                _at(d)
                if RUN["url"] == before:
                    return _set_step(i, status="failed", detail="it typed the search, but the page did not change")
            _at(d)
            RUN["chunks"], RUN["done"] = None, []
            return _set_step(i, status="ok", detail=f"searched for “{arg}”: {RUN['title']}", url=RUN["url"])
        if name == "click":
            items = []
            for _ in range(10):  # a page that draws itself after loading (YouTube's results) is empty for a moment
                if items := d.call(lambda pg: pg.evaluate(CLICKABLES)):
                    break
                d.call(lambda pg: pg.wait_for_timeout(600))
            if not items:
                return _set_step(i, status="failed", detail="nothing to click on this page")
            k = _pick(arg, items)
            if k is None:
                return _set_step(i, status="failed", detail=f"nothing on the page looks like “{arg}”")
            text = next(it["text"] for it in items if it["i"] == k)
            el = lambda pg: pg.locator(f'[data-dot-i="{k}"]').first
            box = d.call(lambda pg: (el(pg).scroll_into_view_if_needed(timeout=4000), _box(el(pg)))[1])
            _aim(i, box, f"clicking “{text}”")
            before = RUN["url"]
            d.call(lambda pg: (el(pg).click(timeout=6000), _settle(pg)))
            _at(d)
            RUN["chunks"], RUN["done"] = None, []
            return _set_step(i, status="ok", detail=f"clicked “{text}”" + ("" if RUN["url"] != before else " (same page)"), url=RUN["url"])
        if name == "play":
            box = d.call(lambda pg: (v := pg.locator("video").first).count() and _box(v))
            if not box:
                return _set_step(i, status="failed", detail="there is no video or song on this page")
            _aim(i, box, "pressing play")
            got = d.call(lambda pg: (r := pg.evaluate(PLAY), pg.wait_for_timeout(2500), r, pg.evaluate(PLAYING))[2:])
            tried, now = got
            if tried and tried.get("err"):
                return _set_step(i, status="failed", detail=f"the browser would not play it: {tried['err'][:120]}")
            if not now or not now["playing"]:
                return _set_step(i, status="failed", detail="it pressed play, but nothing is playing")
            return _set_step(i, status="ok", detail=f"playing “{RUN['title']}”" + (" (an ad plays first)" if now["ad"] else ""))
        if name == "wait":
            n = int(arg or 5)
            for k in range(n * 2):
                if _stop.is_set():
                    break
                _set_step(i, detail=f"waiting {n - k // 2} s")
                time.sleep(0.5)
            return _set_step(i, status="ok", detail=f"waited {n} s")
        # read and scroll: the page's words, a piece at a time
        if not RUN.get("url"):
            return _set_step(i, status="failed", detail="no page is open, so there is nothing to read")
        if name == "scroll":
            d.call(lambda pg: (pg.mouse.wheel(0, 700), pg.wait_for_timeout(700)))
        if RUN.get("chunks") is None:
            RUN["chunks"] = _chunks(d.call(lambda pg: pg.evaluate("document.body.innerText")))
        chunks, done = RUN["chunks"], RUN["done"]
        words = [w for w in arg.lower().split() if len(w) > 2] if name == "read" else []
        at = next((k for k, c in enumerate(chunks) if k not in done and words and all(w in c.lower() for w in words)), None)
        repaired = f"nothing about “{arg}”, so it reads on. " if words and at is None else ""
        at = at if at is not None else next((k for k in range(len(chunks)) if k not in done), None)
        if at is None:
            return _set_step(i, status="failed", detail="it has read all of this page")
        done.append(at)
        head = chunks[at].splitlines()[0][:60]
        _set_step(i, detail=f"{repaired}reading “{head}”")
        thought = _think(chunks[at])
        if not thought:
            return _set_step(i, status="failed", detail="the model said nothing about it")
        read.append({"page": RUN.get("title", ""), "thought": thought, "text": chunks[at]})
        _set_step(i, status="ok", detail=f"{repaired}read “{head}”", thought=thought)
    except RuntimeError as e:
        if str(e).startswith("I can't reach the model"):
            raise
        _set_step(i, status="failed", detail=f"the browser could not do it: {e}")


def _run() -> None:
    read: list[dict[str, str]] = []
    try:
        d = launch()
        for i, p in enumerate(RUN["plan"]):
            if _stop.is_set():
                for j in range(i, len(RUN["plan"])):
                    _set_step(j, status="skipped", detail="stopped before it ran")
                RUN["status"] = "stopped"
                break
            _set_step(i, status="doing")
            if p["name"] == "opinion":
                if not any(s["status"] == "ok" for s in RUN["steps"]):
                    _set_step(i, status="failed", detail="nothing worked, so it has nothing to say")
                    continue
                RUN["opinion"] = _opinion(RUN["task"], read)
                seen = " ".join([r["text"] for r in read] + [s["detail"] for s in RUN["steps"]] + [RUN.get("title", "")])
                RUN["grounding"] = grounding(RUN["opinion"], seen)
                _set_step(i, status="ok" if RUN["opinion"] else "failed",
                          detail=f"grounded {RUN['grounding']:.2f}: the share of its names it really saw" if RUN["opinion"] else "the model said nothing")
                continue
            _step(i, p, read, d)
        else:
            RUN["status"] = "done" if RUN.get("opinion") else "failed"
            if not RUN.get("opinion"):
                RUN["error"] = "It finished without an opinion: " + "; ".join(s["detail"] for s in RUN["steps"] if s["status"] == "failed")
    except RuntimeError as e:  # the model is down or Chrome would not start: say so and stop, the rest would fail the same way
        RUN.update(status="failed", error=str(e))
        for s in RUN["steps"]:
            if s["status"] in ("doing", "waiting"):
                s.update(status="failed" if s["status"] == "doing" else "skipped", detail=str(e) if s["status"] == "doing" else "not run")
    if slips := [f"{s['cmd']}: {s['detail']}" for s in RUN["steps"] if s["status"] == "failed" and s["cmd"] != "opinion"]:
        char._fail("browse", "; ".join(slips))  # the feedbacker: a lesson for the next plan, and two of these draft a fix
    RUN["learned"] = _learn()
    if RUN.get("opinion"):
        saved = char.add_memory(f"Reflection: {RUN.get('title') or RUN['task']}"[:80], RUN["opinion"], source="reflection")  # a note like a look-up's, so its checker can verify it too
        char.add_memory(f"Sources: {saved['id']}", json.dumps([{"title": r["page"], "url": RUN.get("url", ""), "snippet": r["text"][:280]} for r in read]), source="sheet")
        RUN["note"] = saved["id"]
    char._engine("browse", "ok" if RUN["status"] == "done" else RUN["status"], f"{RUN['task'][:60]}: {RUN['status']}")


def _planner(note: str = "") -> None:
    try:
        intent, plan, rejected = _plan(RUN["task"], note)
    except RuntimeError as e:
        RUN.update(status="failed", error=str(e))
        return
    if _stop.is_set():
        RUN["status"] = "stopped"
        return
    RUN.update(status="waiting", intent=intent, plan=plan, plan_text=plan_text(plan), rejected=rejected)


def _go(target: Any, *args: Any) -> None:
    RUN["thread"] = threading.Thread(target=target, args=args, daemon=True, name="browse")
    RUN["thread"].start()


def _model_free() -> str:
    from harness_char import harness, train
    if harness._lock.locked():
        return "A harness cycle is using the model. Try again when it ends."
    if train.active():
        return "A training run is using the model. Pause or stop it first."
    if char.mode() == "sleeping":
        return "It is asleep, so it does not call the model. Type /wake first."
    return ""


def start(task: str) -> dict[str, Any]:
    """Plan a browse for the task; the plan then waits for you to steer it or press Go."""
    task = " ".join((task or "").split())[:500]
    if not task:
        raise ValueError("Tell it what to do on the web, like: go to youtube and play a song you like.")
    with _lock:
        if RUN.get("status") in ("waiting", "planning", "running"):
            raise RuntimeError("It is already browsing. Stop that one first.")
        if why := _model_free():
            raise RuntimeError(why)
        _stop.clear()
        keep = {k: RUN[k] for k in ("url", "title") if k in RUN and DRIVER.get("d") and DRIVER["d"].alive()}  # the browser stays where it was
        RUN.clear()
        RUN.update({"task": task, "status": "planning", "intent": "", "plan": [], "plan_text": "", "rejected": [], "steps": [], "url": "", "title": "",
                    "chunks": None, "done": [], "opinion": "", "grounding": None, "error": "", "note": None} | keep)
        _go(_planner)
    return status()


def replan(note: str) -> dict[str, Any]:
    """Steer by words: it plans again with your note."""
    with _lock:
        if RUN.get("status") != "waiting":
            raise RuntimeError("There is no plan waiting to steer.")
        RUN.update(status="planning")
        _go(_planner, " ".join((note or "").split())[:300])
    return status()


def go(text: str | None = None) -> dict[str, Any]:
    """Run the plan, as you left it: edited commands are read and checked again first."""
    with _lock:
        if RUN.get("status") != "waiting":
            raise RuntimeError("There is no plan waiting to run.")
        if why := _model_free():
            raise RuntimeError(why)
        if text is not None and text.strip() != RUN["plan_text"].strip():
            from harness_char import harness
            cmds, bad = harness.parse(text)
            RUN["plan"], rejected = validate([{"name": c["name"], "arg": c["arg"]} for c in cmds])
            RUN["rejected"] = rejected + [{"cmd": b, "why": "could not read it as a command"} for b in bad]
            RUN["plan_text"] = plan_text(RUN["plan"])
        RUN["steps"] = [{"cmd": _text(p), "status": "waiting", "detail": "", "thought": "", "box": None, "url": ""} for p in RUN["plan"]]
        RUN["status"] = "running"
        _go(_run)
    return status()


def stop() -> dict[str, Any]:
    """Stop lands between steps: a model call in flight finishes first. A plan still waiting is just dropped. The browser stays open: close it apart."""
    _stop.set()
    if RUN.get("status") == "waiting":
        RUN["status"] = "stopped"
    return status()


def status() -> dict[str, Any]:
    out = {k: v for k, v in RUN.items() if k not in ("thread", "chunks", "done")}
    out["active"] = active() or RUN.get("status") == "waiting"
    out["live"] = bool(DRIVER.get("d") and DRIVER["d"].alive())
    out["commands"] = [{"name": k, "arg": a, "does": d} for k, (a, d) in COMMANDS.items()]
    return out
