import json

from fastapi.testclient import TestClient

import app as main
from shared import settings, websearch
from shared.settings import Settings

SAMPLE = (
    "Title: Printing press\n"
    "URL: https://en.wikipedia.org/wiki/Printing_press\n"
    "Snippet: A machine for printing text.\n"
    "\n---\n\n"
    "Title: Johannes Gutenberg\n"
    "URL: https://example.com/gutenberg\n"
    "Snippet: Goldsmith who built a press.\n"
    "\n---\n\n"
    "IMPORTANT: These are only short snippets.\n"
)


def test_results_keep_title_link_and_snippet() -> None:
    out = websearch.results_from_tool(SAMPLE)
    assert out["note"] == ""
    assert out["results"] == [
        {"title": "Printing press", "url": "https://en.wikipedia.org/wiki/Printing_press",
         "snippet": "A machine for printing text."},
        {"title": "Johannes Gutenberg", "url": "https://example.com/gutenberg",
         "snippet": "Goldsmith who built a press."},
    ]


def test_wikipedia_fallback_is_named() -> None:
    text = "These are Wikipedia-only encyclopedia results.\n\n" + SAMPLE
    out = websearch.results_from_tool(text)
    assert out["results"] and "Wikipedia" in out["note"] and "—" not in out["note"]


def test_empty_search_is_not_invented() -> None:
    assert websearch.results_from_tool("No results found.")["results"] == []


def test_a_failed_search_is_an_error() -> None:
    try:
        websearch.results_from_tool("Search failed: the search engines are rate limiting this machine.")
    except RuntimeError as e:
        assert "busy" in str(e)
    else:
        raise AssertionError("a failed search must not look like results")


def test_search_uses_unsloth_web_tool(monkeypatch) -> None:
    seen: dict = {}

    class Resp:
        def __init__(self) -> None:
            self.buf = b'data: {"type":"tool_end","tool_name":"web_search","result":' + json.dumps(SAMPLE).encode() + b"}\n\n"

        def read(self, n: int) -> bytes:
            chunk, self.buf = self.buf[:n], self.buf[n:]
            return chunk

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["timeout"] = timeout
        seen["body"] = json.loads(req.data.decode())
        seen["events"] = req.get_header("X-unsloth-events")
        return Resp()

    monkeypatch.setattr(websearch.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(websearch, "pick_model", lambda s: "local")
    out = websearch.search(Settings(base_url="http://127.0.0.1:9/v1", api_key="k", timeout_s=30), "  printing   press ")
    body = seen["body"]
    assert seen["url"] == "http://127.0.0.1:9/v1/chat/completions"
    assert seen["events"] == "1"
    assert body["enabled_tools"] == ["web_search"]
    assert body["tool_choice"]["function"]["name"] == "web_search"
    assert body["permission_mode"] == "off"
    assert body["messages"] == [
        {"role": "system", "content": websearch._SYSTEM},
        {"role": "user", "content": "printing press"},
    ]
    assert "paper" not in json.dumps(body["messages"]).lower()
    assert out["results"][0]["title"] == "Printing press"


def test_html_results_unwrap_the_real_link() -> None:
    page = (
        '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpress&amp;rut=1">'
        "Printing press</a>"
        '<a class="result__snippet" href="x">A machine for books.</a>'
    )
    assert websearch.pages_from_html(page) == [
        {"title": "Printing press", "url": "https://example.com/press", "snippet": "A machine for books."}
    ]


def test_when_the_model_skips_the_tool_the_web_is_searched(monkeypatch) -> None:
    page = (
        '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpress">'
        "Printing press</a><a class=\"result__snippet\" href=\"y\">A machine.</a>"
    )
    seen: list[str] = []

    class Resp:
        def __init__(self, body: bytes) -> None:
            self.buf = body

        def read(self, n: int = -1) -> bytes:
            if n < 0:
                chunk, self.buf = self.buf, b""
                return chunk
            chunk, self.buf = self.buf[:n], self.buf[n:]
            return chunk

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout):
        seen.append(req.full_url)
        if "chat/completions" in req.full_url:
            return Resp(b'data: {"object":"chat.completion.chunk"}\n\ndata: [DONE]\n')
        return Resp(page.encode())

    monkeypatch.setattr(websearch.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(websearch, "pick_model", lambda s: "local")
    out = websearch.search(Settings(base_url="http://127.0.0.1:9/v1", api_key="k"), "printing press")
    assert any("chat/completions" in u for u in seen)
    assert any("duckduckgo.com" in u for u in seen)
    assert out["results"][0]["url"] == "https://example.com/press"


def test_web_route(tmp_path, monkeypatch) -> None:
    from shared import db
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(db, "PAPERS_DIR", tmp_path / "papers")
    db.init()
    monkeypatch.setattr(settings, "get_all", lambda: Settings())
    monkeypatch.setattr(websearch, "search", lambda s, q: {"results": [{"title": q, "url": "https://example.com", "snippet": "A page."}], "note": ""})
    r = TestClient(main.app).post("/library/web", json={"q": "printing press"})
    assert r.status_code == 200 and r.json()["results"][0]["url"] == "https://example.com"
    bad = TestClient(main.app).post("/library/web", json={"q": "  "})
    assert bad.status_code == 422


def test_glued_titles_are_cut_apart() -> None:
    text = ("Title: arXiv paper 2023[2106.04554] A Survey of Transformers - arXiv.orgTop Research Papers on Transformers\n"
            "URL: https://arxiv.org/pdf/1\nSnippet: Attention maps queries. See full list on arxiv.org More.\n\n---\n\n"
            "Title: [2106.04554] A Survey of Transformers - arXiv.orgTop Research Papers on Transformers\n"
            "URL: https://arxiv.org/abs/2\nSnippet: A survey.\n\n---\n\n"
            "Title: Top Research Papers on Transformers\nURL: https://example.com/3\nSnippet: A list.\n")
    out = websearch.results_from_tool(text)["results"]
    assert [r["title"] for r in out] == ["arXiv paper 2023", "[2106.04554] A Survey of Transformers - arXiv.org",
                                         "Top Research Papers on Transformers"]
    assert out[0]["snippet"] == "Attention maps queries. More."


def test_html_snippet_keeps_text_after_bold_words() -> None:
    page = ('<a class="result__a" href="https://en.wikipedia.org/wiki/T">T</a> '
            '<a class="result__snippet" href="x"><b>Transformers</b> is a series of films.</a>')
    assert websearch.pages_from_html(page)[0]["snippet"] == "Transformers is a series of films."


def test_a_blocked_provider_falls_through_to_the_next_and_is_skipped_while_it_cools(monkeypatch) -> None:
    import base64
    import urllib.error
    real = "https://www.bungie.net/osiris"
    bing = ('<li class="b_algo"><h2><a href="https://www.bing.com/ck/a?!&amp;u=a1' + base64.urlsafe_b64encode(real.encode()).decode().rstrip("=")
            + '&amp;ntb=1">Osiris <b>lore</b></a></h2><div><p>The Warlock who walked the Infinite Forest.</p></div></li>')
    seen: list[str] = []

    def get(url, timeout):
        seen.append(url.split("/")[2])
        if "duckduckgo" in url:
            raise urllib.error.URLError("timed out")
        return bing if "bing" in url else '{"query": {"search": []}}'

    monkeypatch.setattr(websearch, "_get", get)
    out = websearch._web("Osiris")
    assert out["via"] == "bing" and out["results"] == [{"title": "Osiris lore", "url": real, "snippet": "The Warlock who walked the Infinite Forest."}]
    websearch._web("Osiris again")
    assert seen == ["html.duckduckgo.com", "www.bing.com", "www.bing.com"]  # duckduckgo is not tried again while it cools


def test_wikipedia_answers_when_the_others_find_nothing(monkeypatch) -> None:
    wiki = '{"query": {"search": [{"title": "Destiny 2", "snippet": "Named Curse of <span class=\\"searchmatch\\">Osiris</span>"}]}}'
    monkeypatch.setattr(websearch, "_get", lambda url, timeout: wiki if "wikipedia" in url else "<html>no hits</html>")
    out = websearch._web("Osiris")
    assert out["via"] == "wikipedia" and out["results"] == [{"title": "Destiny 2", "url": "https://en.wikipedia.org/wiki/Destiny_2", "snippet": "Named Curse of Osiris"}]


def test_no_provider_reachable_says_so(monkeypatch) -> None:
    import urllib.error
    monkeypatch.setattr(websearch, "_get", lambda url, timeout: (_ for _ in ()).throw(urllib.error.URLError("down")))
    try:
        websearch._web("Osiris")
    except RuntimeError as e:
        assert "could not reach the web" in str(e)
    else:
        raise AssertionError("expected RuntimeError")
