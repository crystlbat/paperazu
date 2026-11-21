import threading
from typing import Any

import pytest
from fastapi.testclient import TestClient

from harness_char import browse, char
from shared import db, llm
from pdf_research import jobs
import app as main

client = TestClient(main.app)

SITE = {"https://www.youtube.com/": {"title": "YouTube", "search": True, "links": [("Home", "https://www.youtube.com/")], "text": "Home\nShorts"},
        "https://www.youtube.com/results": {"title": "lofi song - YouTube", "search": True,
                                            "links": [("Filters", "https://www.youtube.com/results"), ("lofi hip hop radio beats to relax", "https://www.youtube.com/watch")], "text": "Filters\nlofi hip hop radio"},
        "https://www.youtube.com/watch": {"title": "lofi hip hop radio - YouTube", "search": True, "video": True, "links": [], "text": "lofi hip hop radio\nLofi Girl\n15.8M subscribers"},
        "https://en.wikipedia.org/wiki/JARVIS": {"title": "J.A.R.V.I.S. - Wikipedia", "links": [("Vision", "https://en.wikipedia.org/wiki/Vision")],
                                                 "text": "J.A.R.V.I.S.\n" + "Intro words. " * 120 + "\nDevelopment\nStark built it after his butler Edwin Jarvis.\n" + "More words. " * 120}}


class Loc:
    def __init__(self, page: "Page", sel: str) -> None:
        self.page, self.sel, self.first = page, sel, self

    def count(self) -> int:
        here = self.page.here()
        if self.sel.startswith("button:has-text"):
            return 0
        if self.sel.startswith("input"):
            return int(bool(here.get("search")))
        if self.sel == "video":
            return int(bool(here.get("video")))
        return 1

    def bounding_box(self) -> dict[str, float]:
        return {"x": 128, "y": 80, "width": 256, "height": 40}

    def scroll_into_view_if_needed(self, **k: Any) -> None:
        pass

    def click(self, **k: Any) -> None:
        if self.sel.startswith("[data-dot-i"):
            self.page.goto(self.page.here()["links"][int(self.sel.split('"')[1])][1])

    def fill(self, text: str, **k: Any) -> None:
        self.page.typed = text

    def press(self, key: str) -> None:
        self.page.url = "https://www.youtube.com/results?search_query=" + self.page.typed.replace(" ", "+")


class Page:
    def __init__(self) -> None:
        self.url, self.typed = "about:blank", ""
        self.mouse = type("M", (), {"wheel": lambda *a: None})()

    def here(self) -> dict[str, Any]:
        return SITE.get(self.url.split("?")[0], {})

    def goto(self, url: str, **k: Any) -> Any:
        if "nowhere" in url:
            raise Exception("net::ERR_NAME_NOT_RESOLVED at " + url)
        self.url = url
        return type("R", (), {"status": 200 if url.split("?")[0] in SITE else 404})()

    def title(self) -> str:
        return self.here().get("title", "")

    def wait_for_load_state(self, *a: Any, **k: Any) -> None:
        pass

    def wait_for_timeout(self, ms: float) -> None:
        pass

    def locator(self, sel: str) -> Loc:
        return Loc(self, sel)

    def evaluate(self, script: str) -> Any:
        if script == browse.CLICKABLES:
            return [{"i": i, "text": t, "to": u.split("youtube.com")[-1]} for i, (t, u) in enumerate(self.here()["links"])]
        if script == browse.PLAY:
            return {"ok": True} if self.here().get("video") else None
        if script == browse.PLAYING:
            return {"playing": True, "ad": True} if self.here().get("video") else None
        return self.here().get("text", "")


class FakeDriver:
    def __init__(self) -> None:
        self.page, self.n, self.frame = Page(), 0, b""

    def alive(self) -> bool:
        return True

    def call(self, fn: Any, timeout: float = 90) -> Any:
        try:
            return fn(self.page)
        except Exception as e:
            raise RuntimeError(str(e)) from None

    def close(self) -> None:
        pass


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    char.init_db()
    char.set_mode("curious")
    char.update_profile("Jarvis", "an AI butler", [], "#fff")
    browse.RUN.clear()
    browse.DRIVER.clear()
    browse._stop.clear()
    monkeypatch.setattr(browse, "AIM", 0)
    monkeypatch.setattr(llm, "_api", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no HTTP to the model server in tests")))
    d = FakeDriver()
    monkeypatch.setattr(browse, "launch", lambda: browse.DRIVER.setdefault("d", d))
    yield
    browse.RUN.clear()  # a browse left planning would hold idle learning in the other test files
    browse.DRIVER.clear()


def _model(monkeypatch, plan: str, fail: bool = False) -> list[list[dict[str, Any]]]:
    calls: list[list[dict[str, Any]]] = []

    def complete(s: Any, messages: list[dict[str, Any]], **kw: Any) -> str:
        calls.append(messages)
        if fail:
            raise llm.ModelError("connection refused")
        sys_msg = messages[0]["content"]
        if "about to use a web browser" in sys_msg:
            return plan
        if "pick what to click" in sys_msg:
            return "Number 1."
        if "what you did and what you think" in sys_msg:
            return "I put on lofi hip hop radio from Lofi Girl, after an ad."
        return "Stark built it after his butler."

    monkeypatch.setattr(jobs, "complete", complete)
    return calls


def _wait() -> dict[str, Any]:
    if t := browse.RUN.get("thread"):
        t.join(5)
    return client.get("/char/browse").json()


def _run(plan_text: str | None = None) -> dict[str, Any]:
    _wait()
    client.post("/char/browse", json={"action": "go", **({"plan": plan_text} if plan_text else {})})
    return _wait()


def test_checker_rejects_with_reasons_and_puts_opinion_last():
    plan, rejected = browse.validate([{"name": "click", "arg": "x"}, {"name": "dance", "arg": ""}, {"name": "opinion", "arg": ""},
                                      {"name": "open", "arg": "not a url"}, {"name": "open", "arg": "youtube.com"}, {"name": "search", "arg": ""},
                                      {"name": "wait", "arg": "999 seconds"}, {"name": "play", "arg": "the video: play the song on the page"}, *[{"name": "click", "arg": "the first video"}] * 5])
    assert plan == [{"name": "open", "arg": "https://youtube.com"}, {"name": "wait", "arg": "60"}, {"name": "play", "arg": "the video"}, *[{"name": "click", "arg": "the first video"}] * 3,
                    {"name": "opinion", "arg": ""}]
    why = {r["cmd"]: r["why"] for r in rejected}
    assert why["click x"] == "no page is open yet"
    assert why["dance"] == "unknown command"
    assert why["open not a url"] == "no web address to open"
    assert why["search"] == "search needs what to search for" or why["search"].startswith("search needs")
    assert [r["why"] for r in rejected if r["cmd"] == "click the first video"] == ["at most 4 clicks per browse"] * 2


def test_youtube_story_plans_waits_then_searches_clicks_and_plays(monkeypatch):
    calls = _model(monkeypatch, "Intent: I'll open YouTube, search lofi and play the first video.\nopen https://www.youtube.com/\nsearch lofi song\n"
                                "click the first video\nplay\nwait 2\nopinion")
    r = client.post("/char/browse", json={"action": "start", "task": "go to youtube and play a song you like"}).json()
    assert r["status"] == "planning" and r["live"] is False
    r = _wait()
    assert r["status"] == "waiting" and r["intent"].startswith("I'll open YouTube")
    r = _run()
    assert r["status"] == "done", r
    assert [(s["cmd"], s["status"]) for s in r["steps"]] == [("open https://www.youtube.com/", "ok"), ("search lofi song", "ok"), ("click the first video", "ok"),
                                                             ("play", "ok"), ("wait 2", "ok"), ("opinion", "ok")]
    assert r["steps"][2]["detail"] == "clicked “lofi hip hop radio beats to relax”"  # the model picked item 1 from the page's own list
    assert r["steps"][2]["box"] == [0.1, 0.1, 0.2, 0.05]  # where Dot goes on the screen before it clicks
    assert r["steps"][3]["detail"] == "playing “lofi hip hop radio - YouTube” (an ad plays first)"
    assert r["url"] == "https://www.youtube.com/watch" and r["live"] is True
    assert any("1. lofi hip hop radio beats to relax" in m[-1]["content"] for m in calls)
    con = db.connect()
    note = con.execute("SELECT title, content FROM char_memories WHERE id = ?", (r["note"],)).fetchone()
    con.close()
    assert note["title"] == "Reflection: lofi hip hop radio - YouTube" and note["content"] == r["opinion"]
    assert not browse.active() and not any(f() for f in llm.busy)  # the song plays on, but the model is free


def test_steered_plan_reads_and_repairs_plainly(monkeypatch):
    _model(monkeypatch, "Intent: x\nopen https://en.wikipedia.org/wiki/JARVIS\nopinion")
    client.post("/char/browse", json={"action": "start", "task": "check about jarvis"})
    r = _run("open en.wikipedia.org/wiki/JARVIS\nread butler Edwin\nread Ultron\nscroll\nfly away")
    assert r["status"] == "done", r
    assert [s["status"] for s in r["steps"]] == ["ok"] * 5
    assert r["steps"][1]["thought"] == "Stark built it after his butler."
    assert r["steps"][2]["detail"].startswith("nothing about “Ultron”, so it reads on.")
    assert r["rejected"] == [{"cmd": "fly away", "why": "unknown command"}]


def test_an_error_page_is_a_failed_open_with_a_lesson(monkeypatch):
    calls = _model(monkeypatch, "Intent: x\nopen https://www.youtube.com/playlist?list=PLYourSongList\nplay\nopinion")
    client.post("/char/browse", json={"action": "start", "task": "play a song"})
    r = _run()
    assert r["steps"][0]["status"] == "failed" and r["steps"][0]["detail"].startswith("that address does not exist (the site said 404)")
    assert "open https://www.youtube.com/ and search there instead" in browse.lessons()[0]


def test_page_that_will_not_load_is_said_plainly_and_fed_to_the_next_plan(monkeypatch):
    calls = _model(monkeypatch, "Intent: open it.\nopen https://nowhere.example/page\nplay\nopinion")
    client.post("/char/browse", json={"action": "start", "task": "check nowhere"})
    r = _run()
    assert r["status"] == "failed"
    assert r["steps"][0]["detail"].startswith("the browser could not do it: net::ERR_NAME_NOT_RESOLVED")
    assert r["steps"][1]["detail"] == "there is no video or song on this page"
    assert r["steps"][2]["detail"] == "nothing worked, so it has nothing to say"
    client.post("/char/browse", json={"action": "start", "task": "check nowhere"})
    _wait()
    assert "What went wrong before" in calls[-1][-1]["content"] and "ERR_NAME_NOT_RESOLVED" in calls[-1][-1]["content"]  # the lesson reaches the next plan
    assert not [c for c in char.corrections() if c["kind"] == "browse"]  # one slip is a lesson, not yet a fix
    client.post("/char/browse", json={"action": "go"})
    _wait()
    fix = next(c for c in char.corrections() if c["kind"] == "browse")  # two slips: the feedbacker drafts a fix for the browse prompt
    assert fix["state"] == "proposed" and fix["fails"] == 2
    assert fix["text"] not in calls[-1][0]["content"]  # nothing reaches the prompt until you approve it
    char.set_correction("browse", True)
    client.post("/char/browse", json={"action": "start", "task": "check nowhere"})
    _wait()
    assert fix["text"] in calls[-1][0]["content"]  # approved: on trial in the planner's prompt


def test_model_down_and_chrome_down_are_said_plainly(monkeypatch):
    _model(monkeypatch, "", fail=True)
    client.post("/char/browse", json={"action": "start", "task": "jarvis"})
    r = _wait()
    assert r["status"] == "failed" and r["error"].startswith("I can't reach the model")
    _model(monkeypatch, "Intent: x\nopen https://www.youtube.com/\nopinion")
    monkeypatch.setattr(browse, "launch", lambda: (_ for _ in ()).throw(RuntimeError("Chrome would not start: no Chrome found")))
    client.post("/char/browse", json={"action": "start", "task": "jarvis"})
    r = _run()
    assert r["status"] == "failed" and r["error"] == "Chrome would not start: no Chrome found"


def test_stop_drops_the_plan_and_refuses_bad_actions(monkeypatch):
    _model(monkeypatch, "Intent: x\nsearch jarvis\nopinion")
    assert client.post("/char/browse", json={"action": "start", "task": " "}).status_code == 422
    assert client.post("/char/browse", json={"action": "go"}).status_code == 409
    assert client.post("/char/browse", json={"action": "fly"}).status_code == 422
    client.post("/char/browse", json={"action": "start", "task": "jarvis"})
    _wait()
    assert client.post("/char/browse", json={"action": "start", "task": "again"}).status_code == 409  # one at a time
    assert client.post("/char/browse", json={"action": "stop"}).json()["status"] == "stopped"
    assert client.post("/char/browse", json={"action": "go"}).status_code == 409


def test_stop_mid_run_skips_the_rest_and_close_shuts_the_browser(monkeypatch):
    _model(monkeypatch, "Intent: x\nopen https://www.youtube.com/\nsearch lofi\nopinion")
    client.post("/char/browse", json={"action": "start", "task": "jarvis"})
    real = browse._step

    def step_then_stop(*a: Any) -> None:
        real(*a)
        browse._stop.set()

    monkeypatch.setattr(browse, "_step", step_then_stop)
    r = _run()
    assert r["status"] == "stopped"
    assert [s["status"] for s in r["steps"]] == ["ok", "skipped", "skipped"]
    assert r["live"] is True
    assert client.post("/char/browse", json={"action": "close"}).json()["live"] is False


def test_idle_learning_and_engine_switch_wait_while_it_plans(monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(browse, "_planner", lambda note="": gate.wait(5))
    client.post("/char/browse", json={"action": "start", "task": "jarvis"})
    try:
        assert client.post("/char/rest", json={"char": True}).json()["why"] == "it is browsing"
        assert any(f() for f in llm.busy)
    finally:
        gate.set()
        _wait()


def test_a_browse_that_works_writes_a_recipe_the_next_plan_follows(monkeypatch):
    calls = _model(monkeypatch, "Intent: x\nopen https://www.youtube.com/\nsearch lofi song\nclick the first video\nplay\nopinion")
    client.post("/char/browse", json={"action": "start", "task": "play a lofi song on youtube"})
    r = _run()
    assert r["learned"] == "youtube.com"
    rec = client.get("/char/browse/recipes").json()["recipes"]
    assert [(x["site"], x["by"], x["worked"]) for x in rec] == [("youtube.com", "learned", 1)]
    assert rec[0]["steps"] == "open https://www.youtube.com/\nsearch <what you want>\nclick the first video\nplay"  # this task's words left as a blank
    client.post("/char/browse", json={"action": "start", "task": "find a jazz song on YouTube"})
    _wait()
    assert "Your recipe for youtube.com (it worked 1 times" in calls[-1][-1]["content"]
    assert browse.recipes_for("check about jarvis") == []  # only the sites a task names


def test_you_can_teach_change_and_forget_a_recipe_and_yours_is_kept(monkeypatch):
    bad = client.post("/char/browse/recipes", json={"site": "youtube.com", "steps": "open youtube\ndance"})
    assert bad.status_code == 422 and "dance (unknown command)" in bad.json()["detail"]
    assert client.post("/char/browse/recipes", json={"site": "", "steps": "play"}).status_code == 422
    got = client.post("/char/browse/recipes", json={"site": "https://www.youtube.com/", "steps": "open https://www.youtube.com/\nsearch <what you want>\nclick the first video\nplay\nwait 30"}).json()
    assert got["site"] == "youtube.com" and got["by"] == "you"
    _model(monkeypatch, "Intent: x\nopen https://www.youtube.com/\nsearch lofi\nclick the first video\nplay\nopinion")
    client.post("/char/browse", json={"action": "start", "task": "play lofi on youtube"})
    _run()
    rec = browse.recipes()[0]
    assert (rec["by"], rec["worked"]) == ("you", 1) and rec["steps"].endswith("wait 30")  # it worked, and your words stay yours
    assert client.delete("/char/browse/recipes/youtube.com").json() == {"ok": True}
    assert client.delete("/char/browse/recipes/youtube.com").status_code == 404


def test_it_looks_at_the_screen_and_takes_the_form_of_a_picture_of_itself_by_itself(monkeypatch):
    from harness_char import chibi
    SITE["https://img.test/"] = {"title": "Jarvis pictures", "text": "Images", "links": [],
                                 "images": [{"i": 0, "alt": "Iron Man suit", "src": "https://img.test/suit.png"},
                                            {"i": 1, "alt": "Jarvis robot butler chibi", "src": "https://img.test/jarvis.png"}]}
    monkeypatch.setattr(Page, "screenshot", lambda self, **k: b"screen", raising=False)
    monkeypatch.setattr(Loc, "screenshot", lambda self, **k: self.sel.encode(), raising=False)
    monkeypatch.setattr(Page, "evaluate", lambda self, s: self.here().get("images", []) if s == browse.IMAGES else self.here().get("text", ""))
    monkeypatch.setattr(chibi, "_image", lambda url: "/char/chibi/image/" + url.rsplit("/", 1)[-1])
    seen: list[str] = []

    def complete(s: Any, messages: list[dict[str, Any]], **kw: Any) -> str:
        first = messages[0]["content"]
        ask = first if isinstance(first, str) else first[0]["text"]
        if not isinstance(first, str):
            seen.append(first[1]["image_url"]["url"])
        if "about to use a web browser" in ask:
            return "Intent: find myself\nopen https://img.test/\nlook\nbecome the picture of the butler\nopinion"
        if "pick what to click" in ask:
            return "0"  # its pick is the suit: looking at it must turn it down
        if ask.startswith("Describe this picture"):
            return "One small robot butler in a bow tie." if "data-dot-img=\"1\"" in __import__("base64").b64decode(first[1]["image_url"]["url"].split(",")[1]).decode() else "A red armoured suit."
        if "You judge whether a picture shows a character" in ask:
            return "me" if "robot butler" in messages[1]["content"] else "no"
        if "what you see on this screen" in ask:
            return "Two pictures: a red suit and a little robot butler."
        return "I found a picture of myself and took its form."

    monkeypatch.setattr(jobs, "complete", complete)
    browse.start("find yourself a new form", auto=True)
    for _ in range(2):  # the planner thread starts the run thread by itself: no Go
        _wait()
    r = _wait()
    assert r["status"] == "done", r
    assert [(s["cmd"], s["status"]) for s in r["steps"]] == [("open https://img.test/", "ok"), ("look", "ok"),
                                                             ("become the picture of the butler", "ok"), ("opinion", "ok")]
    assert r["steps"][1]["thought"] == "Two pictures: a red suit and a little robot butler."
    assert r["steps"][2]["detail"] == "changed form into “Jarvis robot butler chibi” (itself)"
    assert r["form"]["silhouette"] == "/char/chibi/image/jarvis.png" and chibi.cached("Jarvis")["silhouette"] == r["form"]["silhouette"]
    assert seen[0] == "data:image/jpeg;base64," + __import__("base64").b64encode(b"screen").decode()  # the model saw the screenshot itself
    del SITE["https://img.test/"]


def test_become_and_look_need_a_page_open():
    plan, rejected = browse.validate([{"name": "look", "arg": ""}, {"name": "become", "arg": "me"}])
    assert [r["why"] for r in rejected] == ["no page is open yet"] * 2 and plan == [{"name": "opinion", "arg": ""}]


def test_a_planner_that_writes_the_word_command_first_is_read_anyway():
    plan, rejected = browse.validate([{"name": "command", "arg": "open https://www.bing.com/images/search?q=sagira"}, {"name": "command", "arg": "look"}])
    assert [p["name"] for p in plan] == ["open", "look", "opinion"] and not rejected


def test_a_given_plan_runs_without_asking_the_planner(monkeypatch):
    calls = _model(monkeypatch, "Intent: never asked")
    browse.start("check about jarvis", auto=True, plan="open en.wikipedia.org/wiki/JARVIS\nread butler Edwin")
    for _ in range(2):
        _wait()
    r = _wait()
    assert [s["cmd"] for s in r["steps"]] == ["open https://en.wikipedia.org/wiki/JARVIS", "read butler Edwin", "opinion"] and r["status"] == "done"
    assert not any("about to use a web browser" in m[0]["content"] for m in calls)


def test_a_plan_that_stops_at_search_goes_on_until_the_song_plays(monkeypatch):
    calls = _model(monkeypatch, "Intent: open YouTube and search.\nopen https://www.youtube.com/\nsearch lofi song\nopinion")
    complete = jobs.complete

    def more(s: Any, messages: list[dict[str, Any]], **kw: Any) -> str:
        if "plan ran out" in messages[0]["content"]:
            calls.append(messages)
            return "click lofi hip hop radio beats to relax\nplay"
        return complete(s, messages, **kw)

    monkeypatch.setattr(jobs, "complete", more)
    client.post("/char/browse", json={"action": "start", "task": "play a song you like on youtube"})
    r = _run()
    assert r["status"] == "done", r
    assert [(s["cmd"], s["status"]) for s in r["steps"]] == [("open https://www.youtube.com/", "ok"), ("search lofi song", "ok"),
                                                             ("click lofi hip hop radio beats to relax", "ok"), ("play", "ok"), ("opinion", "ok")]
    asked = next(m for m in calls if "plan ran out" in m[0]["content"])
    assert "nothing is playing yet" in asked[0]["content"] and "lofi hip hop radio beats to relax" in asked[1]["content"]  # it saw what it could click


def test_a_run_that_never_plays_is_not_a_recipe_that_worked(monkeypatch):
    browse.save_recipe("youtube.com", "open https://www.youtube.com/\nsearch <what you want>", "you", worked=5)
    monkeypatch.setattr(browse, "MORE_ROUNDS", 0)
    _model(monkeypatch, "Intent: x\nopen https://www.youtube.com/\nsearch lofi song\nopinion")
    client.post("/char/browse", json={"action": "start", "task": "play a song you like on youtube"})
    r = _run()
    assert r["learned"] == "" and next(x for x in browse.recipes() if x["site"] == "youtube.com")["worked"] == 5


def test_with_no_picture_of_itself_it_takes_one_that_fits_its_look_and_says_so(monkeypatch):
    from harness_char import chibi
    SITE["https://img.test/"] = {"title": "Ghosts", "text": "Images", "links": [],
                                 "images": [{"i": 0, "alt": "Guardians group", "src": "https://img.test/group.png"},
                                            {"i": 1, "alt": "a ghost shell", "src": "https://img.test/ghost.png"}]}
    monkeypatch.setattr(Page, "screenshot", lambda self, **k: b"screen", raising=False)
    monkeypatch.setattr(Loc, "screenshot", lambda self, **k: self.sel.encode(), raising=False)
    monkeypatch.setattr(Page, "evaluate", lambda self, s: self.here().get("images", []) if s == browse.IMAGES else self.here().get("text", ""))
    monkeypatch.setattr(chibi, "_image", lambda url: "/char/chibi/image/" + url.rsplit("/", 1)[-1])
    judged: list[str] = []

    def complete(s: Any, messages: list[dict[str, Any]], **kw: Any) -> str:
        first = messages[0]["content"]
        ask = first if isinstance(first, str) else first[0]["text"]
        if ask.startswith("Describe this picture"):
            return "A small floating robot shell with one eye." if "data-dot-img=\"1\"" in __import__("base64").b64decode(first[1]["image_url"]["url"].split(",")[1]).decode() else "Three armoured warriors."
        if "You judge whether a picture shows a character" in ask:
            judged.append(messages[1]["content"])
            return "style" if "robot shell" in messages[1]["content"] else "no"
        return "ok"

    monkeypatch.setattr(jobs, "complete", complete)
    browse.start("find yourself a new form", auto=True, plan="open https://img.test/\nbecome me")
    for _ in range(3):
        _wait()
    r = _wait()
    assert r["steps"][1]["status"] == "ok" and r["steps"][1]["detail"] == "changed form into “a ghost shell” (not itself, but its kind and look)"
    assert "You are Jarvis" in judged[0]  # it is judged against who it is, not just its name
    del SITE["https://img.test/"]


def test_what_it_had_to_add_to_your_recipe_becomes_the_recipe_it_learned(monkeypatch):
    browse.save_recipe("youtube.com", "open https://www.youtube.com/\nsearch <what you want>", "you", worked=5)
    _model(monkeypatch, "Intent: x\nopen https://www.youtube.com/\nsearch lofi song\nopinion")
    complete = jobs.complete
    monkeypatch.setattr(jobs, "complete", lambda s, m, **kw: "click lofi hip hop radio beats to relax\nplay" if "plan ran out" in m[0]["content"] else complete(s, m, **kw))
    client.post("/char/browse", json={"action": "start", "task": "play a song you like on youtube"})
    r = _run()
    rec = next(x for x in browse.recipes() if x["site"] == "youtube.com")
    assert r["learned"] == "youtube.com" and rec["by"] == "learned"
    assert rec["steps"] == "open https://www.youtube.com/\nsearch <what you want>\nclick <what fits the task>\nplay"


def test_play_with_a_song_title_means_click_it_then_play():
    plan, rejected = browse.validate([{"name": "open", "arg": "youtube.com"}, {"name": "play", "arg": "Des Rocs - Used to the Darkness"}, {"name": "play", "arg": "the video"}])
    assert [(p["name"], p["arg"]) for p in plan] == [("open", "https://youtube.com"), ("click", "Des Rocs - Used to the Darkness"), ("play", ""),
                                                     ("play", "the video"), ("opinion", "")] and not rejected
