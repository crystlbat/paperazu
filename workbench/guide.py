"""Guided reading: for each reading step, the places in this paper to read, taken from its headings.
`stops` makes no model call: it matches the step's look_in names against the paper's own headings.
`stages` is the tour Dot walks: abstract, then conclusion, then figures, then the other sections that matter.
The local model only picks those other sections and says why; without it the paper's own headings are used."""
import json
import re
from typing import Any

from . import db, framework, library, primer

_NUM = re.compile(r"^\s*(?:\d+(?:\.\d+)*\.?|[IVX]+\.)\s+")


def stops(paper_id: str) -> list[dict[str, Any]] | None:
    """Each stop: the step, the heading to go to ('' when none matched) and its 1-based page.
    At most two places per step, in page order. None if the paper is not there."""
    con = db.connect()
    row = con.execute("SELECT template FROM papers WHERE id = ?", (paper_id,)).fetchone()
    con.close()
    pages = library.page_texts(paper_id)
    if row is None or pages is None:
        return None
    heads = library.headings(paper_id)
    out = []
    for st in primer.steps_for(framework.load_template(row["template"])):
        want = [w.lower() for w in st.look_in]
        hits = [(p, _NUM.sub("", t)) for _, t, p in heads if any(w in t.lower() for w in want)][:2]
        if not hits:
            hits = [(primer._fallback(st, len(pages))[0] + 1, "")]
        base = {"step_id": st.id, "n": st.n, "title": st.title, "minutes": st.minutes, "look_in": st.look_in,
                "look_for": [f.label for f in st.fields][:3]}
        out += [{**base, "heading": head, "page": page} for page, head in hits]
    return out


# ---------- stages: abstract, conclusion, figures, then the sections that matter ----------
_SKIP = re.compile(r"^(references?|bibliography|acknowledg\w*|appendix|appendices|supplement\w*|ethic\w*|author\w*|contents)\b", re.I)
_CONCLUSION = re.compile(r"\b(conclusions?|concluding|summary|discussion)\b", re.I)
_FIGURE = re.compile(r"^\s*(Figure|Fig\.|Table)\s+(\d+)\s*([:.])\s*(.*)", re.I | re.M)


def figures(pages: list[str]) -> list[dict[str, Any]]:
    """Each figure and table once, in page order: {label, page, caption}. A caption ("Figure 4: ...") wins over a
    sentence that starts by naming one ("Fig. 4. We plot ..."), which is taken only when no caption is found."""
    found: dict[tuple[str, int], tuple[bool, int, int, str]] = {}
    for i, text in enumerate(pages):
        for m in _FIGURE.finditer(text):
            key = ("Table" if m.group(1).lower() == "table" else "Figure", int(m.group(2)))
            caption = m.group(3) == ":"
            if key not in found or (caption and not found[key][0]):
                found[key] = (caption, i + 1, m.start(), m.group(4).strip())
    in_order = sorted(found.items(), key=lambda kv: kv[1][1:3])  # page, then place on the page
    return [{"label": f"{k[0]} {k[1]}", "page": pg, "caption": cap[:140]} for k, (_, pg, _, cap) in in_order]
_MAX_OTHER = 4
_PICK = {
    "type": "object",
    "properties": {"stages": {"type": "array", "items": {
        "type": "object", "properties": {"n": {"type": "integer"}, "why": {"type": "string"}}, "required": ["n", "why"]}}},
    "required": ["stages"],
}


def _clean(title: str) -> str:
    return _NUM.sub("", title).strip()


def stages(paper_id: str, s: Any = None) -> dict[str, Any] | None:
    """The tour, in order: abstract, conclusion, figures, then up to four other sections.
    Each stage: id, kind, title, heading ('' to go to the top of the page), page, why.
    `source` is "model" when the local model chose the other sections, else "headings".
    `s` (the settings) switches the model on; None keeps it off. None if the paper is not there."""
    pages = library.page_texts(paper_id)
    if pages is None:
        return None
    heads = [(lvl, _clean(t), p) for lvl, t, p in library.headings(paper_id) if _clean(t)]
    out: list[dict[str, Any]] = []

    ab = next((h for h in heads if h[1].lower().startswith("abstract")), None)
    out.append({"id": "abstract", "kind": "abstract", "title": "Abstract", "heading": ab[1] if ab else "Abstract",
                "page": ab[2] if ab else 1, "why": "Read the summary first. It tells you what the paper claims."})
    used = {ab[1]} if ab else set()

    # the conclusion is the last matching heading (a "Discussion" near the start is not the end)
    cons = [h for h in heads if _CONCLUSION.search(h[1]) and not _SKIP.match(h[1])]
    if cons:
        c = cons[-1]
        used.add(c[1])
        out.append({"id": "conclusion", "kind": "conclusion", "title": c[1] if c[1].lower().startswith(("conclusion", "concluding")) else "Conclusion",
                    "heading": c[1], "page": c[2], "why": "Now the end. It shows what the authors say they found."})

    figs = figures(pages)
    if figs:
        first, tables = figs[0], sum(f["label"].startswith("Table") for f in figs)
        n_fig = len(figs) - tables
        what = " and ".join(x for x in (f"{n_fig} figure{'s' * (n_fig != 1)}" if n_fig else "",
                                         f"{tables} table{'s' * (tables != 1)}" if tables else "") if x)
        out.append({"id": "figures", "kind": "figures", "title": "Figures and tables" if tables else "Figures",
                    "heading": first["label"], "page": first["page"], "items": figs,
                    "why": f"Look at the {'figures and tables' if tables else 'figures'}. {what} in all, the first on page {first['page']}."
                           + (f" {first['label']}: {first['caption'][:90]}" if first["caption"] else "")})

    counts: dict[int, int] = {}
    for h in heads:
        counts[h[0]] = counts.get(h[0], 0) + 1
    # the level that holds the paper's sections: the highest one with a few headings (not the lone title)
    top = min((lv for lv, n in counts.items() if n >= 3), default=min(counts, default=1))
    rest = [h for h in heads if h[1] not in used and not _SKIP.match(h[1]) and h[0] == top]
    source, note = "headings", ""
    picked: list[tuple[tuple[int, str, int], str]] = []
    if s is not None and rest:
        try:
            listing = "\n".join(f"{i + 1}. {h[1]} (page {h[2]})" for i, h in enumerate(rest[:30]))
            raw = primer._complete(s, [
                {"role": "system", "content": "You help a student read a research paper in stages. They have read the abstract, the "
                 f"conclusion and the figures. From the list, choose at most {_MAX_OTHER} sections that matter most, in reading order, "
                 "and give one plain sentence (under 18 words) on what to look for in each. Reply with JSON only: "
                 '{"stages":[{"n":<number from the list>,"why":"..."}]}'},
                {"role": "user", "content": listing}], _PICK, "guide")
            for it in json.loads(raw).get("stages", []):
                n = int(it.get("n", 0))
                if 1 <= n <= len(rest[:30]) and rest[n - 1] not in [p[0] for p in picked] and str(it.get("why", "")).strip():
                    picked.append((rest[n - 1], str(it["why"]).strip()[:160]))
            picked = picked[:_MAX_OTHER]
            if picked:
                source = "model"
        except (primer.PrimerError, ValueError, TypeError, AttributeError) as e:
            note = str(e) if isinstance(e, primer.PrimerError) else "The model gave an answer I could not read."
    if not picked:  # no model, or it said nothing usable: the paper's own headings, in page order
        picked = [(h, "Read this part and see how it fits.") for h in rest[:_MAX_OTHER]]
    for h, why in picked:
        out.append({"id": f"s{len(out)}", "kind": "section", "title": h[1], "heading": h[1], "page": h[2], "why": why})
    return {"stages": out, "source": source, "note": note}
