import json

from fastapi.testclient import TestClient

from workbench import main, websearch
from workbench.settings import Settings

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
    from workbench import db
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(db, "PAPERS_DIR", tmp_path / "papers")
    db.init()
    monkeypatch.setattr(main.settings, "get_all", lambda: Settings())
    monkeypatch.setattr(main.websearch, "search", lambda s, q: {"results": [{"title": q, "url": "https://example.com", "snippet": "A page."}], "note": ""})
    r = TestClient(main.app).post("/library/web", json={"q": "printing press"})
    assert r.status_code == 200 and r.json()["results"][0]["url"] == "https://example.com"
    bad = TestClient(main.app).post("/library/web", json={"q": "  "})
    assert bad.status_code == 422
