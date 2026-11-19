"""Web search for the Library.

Unsloth Studio searches the web with its web_search tool. This asks for that tool and
reads the titles, links and snippets it returns. The loaded model often answers from
memory instead of calling the tool, so a direct DuckDuckGo lookup is the fallback.
Only the query is sent. Paper text never goes in the request.
"""
import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from shared.llm import pick_model
from shared.settings import Settings

_SYSTEM = (
    "Call the web_search tool once. Set query to the user's words. "
    "Do not pass a url. Do not answer from memory."
)
_HIT = re.compile(r"Title: (.*?)\nURL: (\S+)\nSnippet: (.*?)(?=\n\n---|\Z)", re.S)
_MAX = 6


def results_from_tool(text: str) -> dict[str, Any]:
    """Titles, links and snippets from a web_search tool result. Raises RuntimeError for a failed search."""
    text = text or ""
    if "Search failed" in text and "Title:" not in text:
        low = text.lower()
        if "rate limiting" in low:
            raise RuntimeError("The search engines are busy. Wait a minute and try again.")
        if "could not be reached" in low or "blocked" in low:
            raise RuntimeError("I could not reach the web from here.")
        if "did not respond" in low:
            raise RuntimeError("The search took too long. Try again.")
        raise RuntimeError("The web search failed. Try again.")
    note = ""
    if "Wikipedia-only" in text:
        note = "The wider web did not answer, so these are from Wikipedia."
    results: list[dict[str, str]] = []
    for hit in _HIT.finditer(text):
        title, url, snippet = (part.strip() for part in hit.groups())
        if not url.startswith(("http://", "https://")):
            continue
        results.append({
            "title": title[:180] or url,
            "url": url,
            "snippet": " ".join(snippet.split())[:280],
        })
        if len(results) == _MAX:
            break
    _unglue(results)
    if not results:
        note = note or "Nothing came back for that."
    return {"results": results, "note": note}


def _unglue(results: list[dict[str, str]]) -> None:
    """The search tool sometimes runs the next results' titles into one title; cut each where another one starts."""
    heads = [r["title"][:20] for r in results if len(r["title"]) >= 20]
    for r in results:
        cuts = [i for h in heads if (i := r["title"].find(h)) > 0]
        if cuts:
            r["title"] = r["title"][:min(cuts)].strip()
        r["snippet"] = re.sub(r"\s*See full list on \S+", "", r["snippet"]).strip()


def _tool_result(resp: Any) -> str:
    """The web_search tool_end text. The stream is read to the end so the model server is not cut off."""
    buf = b""
    while True:
        chunk = resp.read(65536)
        if not chunk:
            break
        buf += chunk
    found = ""
    for line in buf.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            event = json.loads(data)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "tool_end" and event.get("tool_name") == "web_search":
            result = event.get("result")
            if isinstance(result, str):
                found = result
            break
    return found


def search(s: Settings, query: str) -> dict[str, Any]:
    """Ask Unsloth to run web_search and return the pages it found."""
    query = " ".join(query.split())
    if not query:
        raise RuntimeError("Tell me what to look up.")
    body = {
        "model": pick_model(s) or "default",
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": query},
        ],
        "temperature": 0,
        "max_tokens": 80,
        "stream": True,
        "enable_thinking": False,
        "reasoning_effort": "none",
        "enable_tools": True,
        "enabled_tools": ["web_search"],
        "permission_mode": "off",
        "tool_choice": {"type": "function", "function": {"name": "web_search"}},
        "max_tool_calls_per_message": 1,
    }
    payload = json.dumps(body).encode()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {s.api_key}" if s.api_key else "",
        "X-Unsloth-Events": "1",
    }
    raw = ""
    try:
        req = urllib.request.Request(
            s.base_url.rstrip("/") + "/chat/completions", data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=min(s.timeout_s, 45)) as resp:  # noqa: S310 — the user's own server
            raw = _tool_result(resp)
    except (urllib.error.URLError, TimeoutError, OSError):
        raw = ""
    if raw and "Title:" in raw:
        try:
            found = results_from_tool(raw)
        except RuntimeError:
            found = {"results": [], "note": ""}
        if found["results"]:
            return found
    return _web(query)


_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
_HTML_HIT = re.compile(
    r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?class="result__snippet"[^>]*>(.*?)</a>',
    re.S,
)


def _plain(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def _direct_url(href: str) -> str:
    href = html.unescape(href)
    if href.startswith("//"):
        href = "https:" + href
    parsed = urllib.parse.urlparse(href)
    target = urllib.parse.parse_qs(parsed.query).get("uddg", [""])[0]
    return target or href


def pages_from_html(page: str) -> list[dict[str, str]]:
    """Titles, links and snippets from a DuckDuckGo HTML results page."""
    out: list[dict[str, str]] = []
    for hit in _HTML_HIT.finditer(page):
        href, title, snippet = hit.groups()
        url = _direct_url(href)
        if not url.startswith(("http://", "https://")):
            continue
        out.append({"title": _plain(title)[:180] or url, "url": url, "snippet": _plain(snippet)[:280]})
        if len(out) == _MAX:
            break
    return out


def _web(query: str) -> dict[str, Any]:
    """A real web search when Unsloth's tool does not run. Raises RuntimeError if the web cannot be reached."""
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "text/html"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 — the query the user just typed
            page = resp.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError):
        raise RuntimeError("I could not reach the web from here.")
    results = pages_from_html(page)
    return {"results": results, "note": "" if results else "Nothing came back for that."}
