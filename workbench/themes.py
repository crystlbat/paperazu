"""Themes: your own topic groups. A paper can be in several; the graph clusters papers by them."""
import sqlite3
import uuid
from typing import Any

from . import db

COLORS = 8  # the palette lives in the CSS; a theme stores its slot


def list_all() -> list[dict[str, Any]]:
    con = db.connect()
    rows = con.execute("SELECT t.id, t.name, t.color, count(pt.paper_id) AS papers FROM themes t "
                       "LEFT JOIN paper_themes pt ON pt.theme_id = t.id GROUP BY t.id ORDER BY t.name").fetchall()
    con.close()
    return [dict(r) for r in rows]


def create(name: str) -> dict[str, Any]:
    """Raises ValueError with a message for the user."""
    name = " ".join(name.split())
    if not name:
        raise ValueError("A theme needs a name.")
    if len(name) > 40:
        raise ValueError("Keep the theme name under 40 characters.")
    con = db.connect()
    try:
        with con:
            used = [r[0] for r in con.execute("SELECT color FROM themes")]
            color = min(range(COLORS), key=lambda c: (used.count(c), c))  # least used colour first
            tid = uuid.uuid4().hex[:10]
            con.execute("INSERT INTO themes (id, name, color) VALUES (?, ?, ?)", (tid, name, color))
    except sqlite3.IntegrityError:
        raise ValueError(f'There is already a theme called "{name}".')
    finally:
        con.close()
    return {"id": tid, "name": name, "color": color, "papers": 0}


def delete(theme_id: str) -> bool:
    con = db.connect()
    with con:
        found = con.execute("DELETE FROM themes WHERE id = ?", (theme_id,)).rowcount
    con.close()
    return bool(found)


def set_for_paper(paper_id: str, theme_ids: list[str]) -> bool:
    """Replaces the paper's themes. False if the paper or any theme does not exist."""
    con = db.connect()
    try:
        with con:
            if not con.execute("SELECT 1 FROM papers WHERE id = ?", (paper_id,)).fetchone():
                return False
            con.execute("DELETE FROM paper_themes WHERE paper_id = ?", (paper_id,))
            con.executemany("INSERT INTO paper_themes (paper_id, theme_id) VALUES (?, ?)",
                            [(paper_id, t) for t in dict.fromkeys(theme_ids)])
    except sqlite3.IntegrityError:
        return False
    finally:
        con.close()
    return True
