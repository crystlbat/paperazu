"""Guided reading: for each reading step, the places in this paper to read, taken from its headings.
No model call: it matches the step's look_in names against the paper's own headings."""
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
