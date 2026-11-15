"""Dot's chibi form: a reference for the live persona, fetched from the web once, and the look it picks from it.

The reference is what Wikipedia says about the character (its article, or the article that mentions it, such as the game
it is from), plus a web search's snippets when one answers. Only the sentences that name the character are kept, and from
those come a kind of body (mech, humanoid, creature), up to two colours and a few features (hair, visor, optic, ears...).
Each persona's reference is stored, so it is looked up once. Only the persona's name is sent.
"""
from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

from . import db, websearch

SCHEMA = "CREATE TABLE IF NOT EXISTS char_chibi (name TEXT PRIMARY KEY, data TEXT NOT NULL, created_at TEXT DEFAULT (datetime('now')))"
_UA = "PaperWorkbench/1.0 (local research app)"

COLOURS = {"navy": "#2a3f8f", "blue": "#4f8cff", "cyan": "#4ff0ff", "teal": "#2bb3a3", "lavender": "#b49cff", "purple": "#9b5cff",
           "violet": "#8a5cff", "magenta": "#e04fd0", "pink": "#ff7ab6", "red": "#e5484d", "crimson": "#c0283c", "orange": "#ff8f3a",
           "yellow": "#ffd84a", "gold": "#e8b931", "green": "#4cc46a", "olive": "#7a8450", "brown": "#8a5a3c", "white": "#eef1f5",
           "black": "#2a2d35", "grey": "#8c949c", "gray": "#8c949c", "silver": "#c3cad2"}
KINDS = {"mech": r"titan|mech|mecha|robot|android|droid|cyborg|exosuit|vanguard|machine",
         "creature": r"animal|creature|beast|dragon|cat|fox|dog|wolf|bird|owl|fairy|alien|monster|pok[eé]mon",
         "humanoid": r"woman|man|girl|boy|human|person|her|his|she|he"}
FEATURES = {"hair_short": r"short hair|close-cropped|cropped hair|crew cut|bob\b", "hair_long": r"long hair|ponytail|braid",
            "visor": r"visor|goggles", "helmet": r"helmet", "cape": r"cape|cloak|gown|robe", "ears": r"ears\b",
            "horns": r"horn", "antenna": r"antenna", "optic": r"optic|single eye|one eye|cyclop|lens",
            "circuits": r"circuit|glyph|lines of code|data stream", "holo": r"hologra|artificial(?:ly)? intelligen|a\.i\.(?=\s)",  # not "projects": every biography has one "tail": r"tails?\b",
            "wings": r"wings?\b", "bowtie": r"bow ?tie|butler|tuxedo|tailcoat",
            "suit": r"butler|valet|tuxedo|tailcoat|suit\b|majordomo", "moustache": r"mo?ustache|whiskers", "grey_hair": r"gr[ae]y hair|white hair|bald|balding|elderly|aging|older man"}


def _get(url: str, timeout: int = 15) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — fixed hosts, only the persona name in the query
        return json.loads(resp.read().decode("utf-8", "replace"))


def _wiki(name: str, where: str = "") -> dict[str, Any]:
    """The Wikipedia article that best matches the character: its text, lead image and link."""
    api, flat = "https://en.wikipedia.org/w/", re.sub(r"(?i)\s+from\s+.*$", "", name.replace(".", ""))  # "Alfred From Batman": search "Alfred", the work goes in `where`
    hits = _get(api + "rest.php/v1/search/page?" + urllib.parse.urlencode({"q": f"{flat} {where} fictional character", "limit": 6})).get("pages") or []
    first = flat.split()[0].lower() if flat.split() else ""
    hits.sort(key=lambda x: first not in x["title"].lower())  # the character's own article ("Alfred Pennyworth") before the work that mentions it ("Batman (serial)")
    for hit in hits:
        if "disambiguation" in hit["title"].lower() or "same term" in (hit.get("description") or ""):
            continue
        q = urllib.parse.urlencode({"action": "query", "prop": "extracts|pageimages", "explaintext": 1, "piprop": "thumbnail", "pithumbsize": 400,
                                    "redirects": 1, "format": "json", "titles": hit["title"]})
        page = next(iter(_get(api + "api.php?" + q).get("query", {}).get("pages", {}).values()), {})
        text = page.get("extract") or ""
        if _about(name, text):
            return {"text": text, "image": (page.get("thumbnail") or {}).get("source", ""), "url": "https://en.wikipedia.org/wiki/" + urllib.parse.quote(hit["key"])}
    return {"text": "", "image": "", "url": ""}


def _tokens(name: str) -> list[str]:
    flat = name.replace(".", "")  # "J.A.R.V.I.S." is written "JARVIS" too
    words = [w for w in flat.split() if len(w) >= 2]
    return list(dict.fromkeys([name, flat, *words[:1]]))


def where_from(persona: str) -> str:
    """The work a persona sheet says the character is from ("... from The Flash"), to tell one Gideon from another."""
    m = re.search(r"\bfrom (?:the )?((?:[A-Z][\w:'-]*\s?){1,4})", persona or "")
    return m.group(1).strip() if m else ""


def _about(name: str, text: str) -> list[str]:
    """The sentences that name the character: on a game's page, only those are about it."""
    pat = re.compile("|".join(rf"(?<!\w){re.escape(t)}(?!\w)" for t in _tokens(name)), re.I)  # not \b: "J.A.R.V.I.S." ends in a dot
    return [s for s in re.split(r"(?<!\b[A-Z]\.)(?<=[.!?])\s+|\n+", text) if pat.search(s)]  # no split after an initial: "J.A.R.V.I.S. is" is one sentence


def spec_from(name: str, text: str, look: list[str] | None = None) -> dict[str, Any]:
    """The chibi's look from what the reference says about the character. Pure: no web, no database."""
    said = " ".join(_about(name, text)).lower()
    counts = {k: len(re.findall(rf"\b(?:{p})s?\b", said)) for k, p in KINDS.items()}
    h = counts["humanoid"]  # people's articles say he/she/his on every line: a stray "robot" must not turn Alfred into a mech
    kind = "mech" if counts["mech"] and counts["mech"] * 4 >= h and counts["mech"] >= counts["creature"] else "creature" if counts["creature"] and counts["creature"] * 4 >= h else "humanoid"
    found = sorted(((said.count(w), -said.find(w), hx) for w, hx in COLOURS.items() if re.search(rf"\b{w}\b", said)), reverse=True)
    colours = list(dict.fromkeys(hx for _, _, hx in found))[:2]
    feats = [f for f, p in FEATURES.items() if re.search(rf"\b(?:{p})", said)] + [f for f in (look or []) if f in FEATURES]
    if kind == "mech" and "optic" not in feats and not re.search(r"\beyes\b", said):
        feats.append("optic")  # a titan or a robot without eyes in its description looks out through one lens
    if "suit" in feats:  # a butler's tailcoat, not a cape; and a man in a suit, whatever AI his article mentions
        feats = [x for x in feats if x not in ("cape", "holo")]
    if "hair_short" in feats and "hair_long" in feats:
        feats.remove("hair_long")
    return {"name": name, "kind": kind, "colours": colours, "features": list(dict.fromkeys(feats))}


def _con() -> Any:
    con = db.connect()
    con.execute(SCHEMA)
    return con


def cached(name: str) -> dict[str, Any] | None:
    con = _con()
    row = con.execute("SELECT data FROM char_chibi WHERE name = ?", (name,)).fetchone()
    con.close()
    return json.loads(row["data"]) if row else None


def reference(name: str, look: list[str] | None = None, persona: str = "", fetch: Callable[[str, str], dict[str, Any]] | None = None) -> dict[str, Any]:
    """The persona's chibi reference: stored after the first look-up. When the web gives nothing it is not stored, so it is tried again."""
    if (got := cached(name)) is not None:
        return got
    ref = (fetch or _fetch)(name, where_from(persona))
    out = {**spec_from(name, ref["text"], look), "image": ref.get("image", ""), "source": ref.get("url", ""),
           "about": " ".join(_about(name, ref["text"]))[:600]}
    if ref["text"]:
        con = _con()
        with con:
            con.execute("INSERT OR REPLACE INTO char_chibi (name, data) VALUES (?, ?)", (name, json.dumps(out)))
        con.close()
    return out


def _fetch(name: str, where: str = "") -> dict[str, Any]:
    """Wikipedia first, then a web search's snippets on top; either may be unreachable."""
    ref = {"text": "", "image": "", "url": ""}
    try:
        ref = _wiki(name, where)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError):
        pass
    try:
        hits = websearch._web(f"{name} {where} character appearance")["results"]
        ref["text"] += "\n" + "\n".join(html.unescape(f"{r['title']}. {r['snippet']}") for r in hits)
        ref["url"] = ref["url"] or (hits[0]["url"] if hits else "")
    except RuntimeError:
        pass
    ref["text"] = ref["text"].strip()
    return ref


def forget(name: str) -> None:
    con = _con()
    with con:
        con.execute("DELETE FROM char_chibi WHERE name = ?", (name,))
    con.close()
