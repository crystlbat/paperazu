"""Dot's chibi form: a reference for the live persona, fetched from the web once, and the look it picks from it.

The reference is what Wikipedia says about the character (its article, or the article that mentions it, such as the game
it is from), plus a web search's snippets when one answers. Only the sentences that name the character are kept, and from
those come a kind of body (mech, humanoid, creature), up to two colours and a few features (hair, visor, optic, ears...).
Each persona's reference is stored, so it is looked up once. Only the persona's name is sent.
"""
from __future__ import annotations

import base64
import hashlib
import html
import ipaddress
import json
import re
import socket
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


# ---------- outfits from chat: "wear a red cape", "put on goggles", "take off the helmet", "back to your usual look" ----------
WEAR = {"cape": r"capes?|cloaks?|robes?|gowns?", "helmet": r"helmets?|hats?|caps?|hoods?", "visor": r"visors?|goggles|sunglasses|glasses|shades",
        "suit": r"suits?|tuxedos?|tailcoats?|blazers?", "bowtie": r"bow ?ties?|ties?", "wings": r"wings?", "horns": r"horns?", "ears": r"(?:cat |fox |bunny )?ears",
        "antenna": r"antennae?|antennas", "tail": r"tails?", "moustache": r"mo?ustaches?", "hair_long": r"long hair|ponytails?|braids?",
        "hair_short": r"short hair", "grey_hair": r"gr[ae]y hair|white hair", "circuits": r"circuits?|glyphs?", "holo": r"holograms?|hologram look"}
ON_MECH = {"cape", "helmet", "visor", "wings", "horns", "ears", "antenna", "tail", "circuits"}  # what a machine body can show (see drawChibi)
ASK = re.compile(r"(?i)(?:^|[.!?]\s+|\b(?:please|can you|could you|would you|now|go|you should)\s+)(wear|put on|try on|dress (?:up )?(?:in|as|with)|take off|remove (?:your|the)|lose the)\s+(.{2,80})"
                 r"|\b(change|switch) (?:your )?(?:outfit|clothes|look)(?: to| into)?\s*(.{0,80})|\b(back to your (?:usual|normal|old|own) (?:look|outfit|self|clothes))")
NOUNS = "capes, hats, goggles, suits, bow ties, wings, horns, ears, antennae, tails, moustaches and hair"


def dress(name: str, text: str) -> dict[str, Any] | None:
    """Change the persona's chibi outfit when you ask it to; None when the message asks for no change. Pure on the stored look: no web, no model."""
    m = ASK.search(text)
    if not m or (spec := cached(name)) is None:
        return None
    base = spec.setdefault("base", {"features": list(spec.get("features", [])), "colours": list(spec.get("colours", []))})
    verb, what = (m.group(1) or m.group(3) or "").lower(), (m.group(2) or m.group(4) or "")
    if m.group(5) or re.search(r"(?i)\b(?:usual|normal|original|default|old)\b", what):
        spec.update(features=list(base["features"]), colours=list(base["colours"]))
        spec.pop("silhouette", None); spec.pop("silhouette_from", None)  # out of the picture it was poured into, too
        _save(name, spec)
        return {"spec": spec, "said": "Back to my usual look."}
    off = verb.startswith(("take", "remove", "lose"))
    items = [f for f, p in WEAR.items() if re.search(rf"(?i)\b(?:{p})\b", what)]
    cols = list(dict.fromkeys(hx for w, hx in COLOURS.items() if re.search(rf"(?i)\b{w}\b", what)))
    if not items and not cols:
        return {"spec": None, "said": f"I have nothing like that to wear. I can wear {NOUNS}, in any colour."}
    shows = items if spec.get("kind") != "mech" else [f for f in items if f in ON_MECH]
    cant = [f for f in items if f not in shows]
    feats = [f for f in spec.get("features", []) if not (off and f in items)] + ([] if off else [f for f in shows if f not in spec.get("features", [])])
    if "hair_short" in shows and not off:
        feats = [f for f in feats if f != "hair_long"]
    if "hair_long" in shows and not off:
        feats = [f for f in feats if f != "hair_short"]
    spec.update(features=feats, colours=(cols + [c for c in spec.get("colours", []) if c not in cols])[:2] if cols and not off else spec.get("colours", []))
    _save(name, spec)
    say = lambda fs: ", ".join({"bowtie": "bow tie", "hair_long": "long hair", "hair_short": "short hair", "grey_hair": "grey hair"}.get(f, f) for f in fs)
    said = (f"Took off the {say(items)}." if off else (f"Done: I'm wearing the {say(shows)}" if shows else "Done: a new colour") + (f", in {' and '.join(w for w in COLOURS if re.search(rf'(?i)\b{w}\b', what))}" if cols else "") + ".")
    if cant:
        said += f" A body like mine can't show {say(cant)}."
    return {"spec": spec, "said": said}


SHOW = re.compile(r"(?i)\b(?:show|find|get|pull up|look up|search(?: for)?)\b.{0,20}\bchibi\b.{0,12}\b(?:references?|refs?|images?|pictures?|pics?|art|looks?)\b")
MAX_IMAGE = 4_000_000


def find_refs(name: str, persona: str = "", fetch: Callable[[str], str] | None = None) -> list[dict[str, str]]:
    """Chibi pictures of the persona from an image search: a thumbnail to show and the full image to pour Dot into. Empty when offline."""
    flat = re.sub(r"(?i)\s+from\s+.*$", "", name.replace(".", ""))
    q = f"{flat} {where_from(persona) or name.removeprefix(flat).replace(' From ', ' ').strip()} chibi"
    try:
        page = (fetch or _page)("https://www.bing.com/images/search?" + urllib.parse.urlencode({"q": q, "form": "HDRSC2"}))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return []
    out = []
    for m in re.finditer(r'\bm="(\{[^"]+\})"', page):  # each result carries its image (murl), thumbnail (turl), title and page
        try:
            j = json.loads(html.unescape(m.group(1)))
        except ValueError:
            continue
        if str(j.get("murl", "")).startswith(("http://", "https://")) and str(j.get("turl", "")).startswith("https://"):
            out.append({"url": j["murl"], "thumb": j["turl"], "title": html.unescape(j.get("t", ""))[:120], "page": j.get("purl", "")})
        if len(out) == 12:
            break
    return out


def _page(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh) PaperWorkbench/1.0", "Accept-Language": "en"})
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 — a fixed host, only the persona name in the query
        return resp.read().decode("utf-8", "replace")


def _public(url: str) -> bool:
    """Only a public web image: no local or private addresses, so a search result can't make the app fetch something on your network."""
    u = urllib.parse.urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        return False
    try:
        return all(ipaddress.ip_address(a[4][0]).is_global for a in socket.getaddrinfo(u.hostname, None))
    except (OSError, ValueError):
        return False


EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}


def image_dir() -> Any:
    return db.DATA_DIR / "chibi"


def _image(url: str) -> str:
    """Saves the picture under data/chibi and returns the app's own link to it, so the canvas can read its pixels without the other site's permission.
    A data: URL is a picture you uploaded yourself; anything else is fetched from the public web."""
    local = re.fullmatch(r"/char/chibi/image/([0-9a-f]{16}\.(?:png|jpg|webp|gif))", url)
    if local and (image_dir() / local[1]).is_file():
        return url  # one it learned before: already here
    if url.startswith("data:"):
        head, _, b64 = url.partition(",")
        kind = head[5:].split(";")[0]
        if kind not in EXT or ";base64" not in head:
            raise ValueError(f"not a picture ({kind or 'unknown'})")
        if len(b64) > MAX_IMAGE * 4 // 3 + 4:
            raise ValueError("picture too big")
        data = base64.b64decode(b64, validate=True)  # a bad encoding raises binascii.Error, a ValueError
    else:
        if not _public(url):
            raise ValueError("not a public web address")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh) PaperWorkbench/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 — checked public above
            kind = resp.headers.get_content_type()
            if kind not in EXT:
                raise ValueError(f"not a picture ({kind})")
            data = resp.read(MAX_IMAGE + 1)
    if len(data) > MAX_IMAGE:
        raise ValueError("picture too big")
    name = f"{hashlib.sha1(data).hexdigest()[:16]}.{EXT[kind]}"
    image_dir().mkdir(parents=True, exist_ok=True)
    (image_dir() / name).write_bytes(data)
    return f"/char/chibi/image/{name}"


def saved() -> list[dict[str, str]]:
    """Every picture it has learned a form from, newest first: its wardrobe."""
    d = image_dir()
    files = sorted((f for f in d.glob("*") if re.fullmatch(r"[0-9a-f]{16}\.(png|jpg|webp|gif)", f.name)), key=lambda f: f.stat().st_mtime, reverse=True) if d.is_dir() else []
    return [{"url": f"/char/chibi/image/{f.name}", "thumb": f"/char/chibi/image/{f.name}", "title": ""} for f in files]


def pick(name: str, url: str, thumb: str = "", look: list[str] | None = None, load: Callable[[str], str] | None = None) -> dict[str, Any]:
    """Pour Dot into the picture you chose: it is kept with the persona's look, and an empty url takes it back off."""
    spec = cached(name) or spec_from(name, "", look)
    if not url:
        spec.pop("silhouette", None); spec.pop("silhouette_from", None)
    else:
        err = None
        for u in (url, thumb):  # the full image, or its thumbnail when the site refuses
            try:
                spec["silhouette"], spec["silhouette_from"] = (load or _image)(u), "uploaded" if url.startswith("data:") else url  # never keep a whole upload in the record
                break
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
                err = e
        else:
            raise ValueError(f"could not load that picture: {err}")
    _save(name, spec)
    return spec


def set_eyes(name: str, eyes: Any) -> dict[str, Any]:
    """Where its picture's eyes are, as you marked them: two circles, in fractions of the picture (x, y from its top left, r of its width).
    Kept per picture, so each learned form keeps its own; an empty list goes back to finding them by itself."""
    spec = cached(name)
    if not spec or not spec.get("silhouette"):
        raise ValueError("it has no picture form to mark")
    if eyes:
        if not isinstance(eyes, list) or len(eyes) != 2 or not all(isinstance(e, dict) for e in eyes):
            raise ValueError("mark two eyes")
        try:
            eyes = [{k: round(float(e[k]), 4) for k in ("x", "y", "r")} for e in eyes]
        except (KeyError, TypeError, ValueError):
            raise ValueError("each eye needs x, y and r") from None
        if not all(0 <= e["x"] <= 1 and 0 <= e["y"] <= 1 and 0.003 <= e["r"] <= 0.3 for e in eyes):
            raise ValueError("an eye is off the picture")
        eyes.sort(key=lambda e: e["x"])
    marks = dict(spec.get("eyes") or {})
    if eyes:
        marks[spec["silhouette"]] = eyes
    else:
        marks.pop(spec["silhouette"], None)
    spec["eyes"] = marks
    _save(name, spec)
    return spec


def set_cut(name: str, outline: Any) -> dict[str, Any]:
    """The figure as you traced it: a closed outline of [x, y] points, in fractions of the picture from its top left.
    Kept per picture; everything outside it is background. An empty list goes back to cutting it out by itself."""
    spec = cached(name)
    if not spec or not spec.get("silhouette"):
        raise ValueError("it has no picture form to trace")
    if outline:
        if not isinstance(outline, list) or not 3 <= len(outline) <= 600:
            raise ValueError("trace round the figure")
        try:
            outline = [[round(float(x), 4), round(float(y), 4)] for x, y in outline]
        except (TypeError, ValueError):
            raise ValueError("each point needs x and y") from None
        if not all(0 <= x <= 1 and 0 <= y <= 1 for x, y in outline):
            raise ValueError("a point is off the picture")
    cuts = dict(spec.get("cuts") or {})
    if outline:
        cuts[spec["silhouette"]] = outline
    else:
        cuts.pop(spec["silhouette"], None)
    spec["cuts"] = cuts
    _save(name, spec)
    return spec


def _save(name: str, spec: dict[str, Any]) -> None:
    con = _con()
    with con:
        con.execute("INSERT OR REPLACE INTO char_chibi (name, data) VALUES (?, ?)", (name, json.dumps(spec)))
    con.close()
