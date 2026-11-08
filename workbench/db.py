"""SQLite storage: one file in ./data/."""
import json
import sqlite3
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "workbench.db"
PAPERS_DIR = DATA_DIR / "papers"

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL  -- JSON
);
CREATE TABLE IF NOT EXISTS papers (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    authors TEXT NOT NULL DEFAULT '',
    venue TEXT NOT NULL DEFAULT '',
    presenters TEXT NOT NULL DEFAULT '',
    presentation_date TEXT,
    course TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '[]',
    reflection_no INTEGER,
    reflection_done INTEGER NOT NULL DEFAULT 0,
    primer_status TEXT NOT NULL DEFAULT 'not_made',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_opened TEXT
);
CREATE TABLE IF NOT EXISTS pages (
    paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    n INTEGER NOT NULL,
    text TEXT NOT NULL,
    PRIMARY KEY (paper_id, n)
);
CREATE TABLE IF NOT EXISTS sections (
    paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    idx INTEGER NOT NULL,
    name TEXT NOT NULL,
    start_page INTEGER NOT NULL,
    end_page INTEGER NOT NULL,
    text TEXT NOT NULL,
    PRIMARY KEY (paper_id, idx)
);
CREATE TABLE IF NOT EXISTS notes (
    paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    step_id TEXT NOT NULL,
    data TEXT NOT NULL DEFAULT '{}',        -- JSON: field values, gate ticks
    seconds INTEGER NOT NULL DEFAULT 0,     -- step timer
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (paper_id, step_id)
);
CREATE TABLE IF NOT EXISTS primers (
    paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    step_id TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (paper_id, step_id)
);
CREATE VIRTUAL TABLE IF NOT EXISTS papers_fts USING fts5(
    paper_id UNINDEXED, title, authors, tags, notes,
    tokenize = 'unicode61 remove_diacritics 2'
);
-- graph: paper text split into passages, each with a unit-length embedding (float32 bytes)
CREATE TABLE IF NOT EXISTS chunks (
    paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    idx INTEGER NOT NULL,
    page INTEGER NOT NULL,
    text TEXT NOT NULL,
    vec BLOB NOT NULL,
    model TEXT NOT NULL,
    PRIMARY KEY (paper_id, idx)
);
CREATE TABLE IF NOT EXISTS concepts (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
-- papers the model has already picked key ideas from, so it does not repeat (or undo a dismiss)
CREATE TABLE IF NOT EXISTS suggest_runs (
    paper_id TEXT PRIMARY KEY REFERENCES papers(id) ON DELETE CASCADE
);
-- themes: your own topic groups; a paper can be in several
CREATE TABLE IF NOT EXISTS themes (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    color INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS paper_themes (
    paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    theme_id TEXT NOT NULL REFERENCES themes(id) ON DELETE CASCADE,
    PRIMARY KEY (paper_id, theme_id)
);
CREATE TABLE IF NOT EXISTS concept_links (
    concept_id TEXT NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
    paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    page INTEGER NOT NULL,
    snippet TEXT NOT NULL,
    score REAL NOT NULL,
    PRIMARY KEY (concept_id, paper_id)
);
-- margin notes: a paragraph Dot traced (its box in PDF points, top-left origin) and what you wrote beside it
CREATE TABLE IF NOT EXISTS marks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    page INTEGER NOT NULL,
    x0 REAL NOT NULL, y0 REAL NOT NULL, x1 REAL NOT NULL, y1 REAL NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
-- saved highlights: kind 'me' (yellow) or 'dot' (blue, a suggestion); rects is a JSON list of line rects in PDF points
CREATE TABLE IF NOT EXISTS highlights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    page INTEGER NOT NULL,
    kind TEXT NOT NULL DEFAULT 'me',
    text TEXT NOT NULL DEFAULT '',
    rects TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
-- the canvas: cards (answer, source, note) placed freely; entries is a JSON list of {who, text}; hidden = "put away"
CREATE TABLE IF NOT EXISTS canvas_cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    question TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL DEFAULT '',
    entries TEXT NOT NULL DEFAULT '[]',
    x REAL NOT NULL, y REAL NOT NULL, w REAL NOT NULL,
    page INTEGER, x0 REAL, y0 REAL, x1 REAL, y1 REAL,
    parent INTEGER REFERENCES canvas_cards(id) ON DELETE SET NULL,
    hidden INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS canvas_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    from_card INTEGER NOT NULL REFERENCES canvas_cards(id) ON DELETE CASCADE,
    to_card INTEGER NOT NULL REFERENCES canvas_cards(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS shelf_names (  -- Dot's name for a group of similar papers; key = sha1 of its sorted ids
    key TEXT PRIMARY KEY,
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    step_id TEXT NOT NULL,
    notes TEXT NOT NULL,
    result TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
-- creatures: a job is a trigger, a short chain of steps, and an output. A run is one time it worked.
CREATE TABLE IF NOT EXISTS job_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    sections TEXT NOT NULL DEFAULT '[]'   -- JSON [{title, ask}]
);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    color INTEGER NOT NULL DEFAULT 0,
    trigger TEXT NOT NULL DEFAULT 'manual',
    every INTEGER NOT NULL DEFAULT 120,
    output TEXT NOT NULL DEFAULT 'doc',
    papers TEXT NOT NULL DEFAULT '[]',    -- JSON paper ids; [] = whichever paper is open
    template_id INTEGER REFERENCES job_templates(id) ON DELETE SET NULL,
    steps TEXT NOT NULL DEFAULT '[]',     -- JSON [{scope, prompt, model}]
    awake INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS job_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER,
    job_name TEXT NOT NULL,
    paper_id TEXT NOT NULL,
    paper TEXT NOT NULL DEFAULT '',
    paper_ids TEXT NOT NULL DEFAULT '[]', -- the papers this run actually reads
    page INTEGER,
    selection TEXT NOT NULL DEFAULT '',
    output TEXT NOT NULL DEFAULT 'doc',
    steps TEXT NOT NULL DEFAULT '[]',     -- copied at queue time, so an edit does not change a run already waiting
    template_json TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'queued',
    done INTEGER NOT NULL DEFAULT 0,
    total INTEGER NOT NULL DEFAULT 1,
    label TEXT NOT NULL DEFAULT '',
    result TEXT NOT NULL DEFAULT '{}',
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT
);
"""


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def init() -> None:
    con = connect()
    with con:
        con.executescript(SCHEMA)
        cols = {r["name"] for r in con.execute("PRAGMA table_info(concepts)")}
        if "kind" not in cols:  # added with AI-suggested ideas: 'kept' or 'suggested'
            con.execute("ALTER TABLE concepts ADD COLUMN kind TEXT NOT NULL DEFAULT 'kept'")
        cols = {r["name"] for r in con.execute("PRAGMA table_info(papers)")}
        if "template" not in cols:  # '' = not picked yet; library.pick_missing_templates() fills it in
            con.execute("ALTER TABLE papers ADD COLUMN template TEXT NOT NULL DEFAULT ''")
        if "note" not in cols:  # the plain note, written next to the paper instead of the steps
            con.execute("ALTER TABLE papers ADD COLUMN note TEXT NOT NULL DEFAULT ''")
    con.close()


def get_settings() -> dict[str, Any]:
    con = connect()
    rows = con.execute("SELECT key, value FROM settings").fetchall()
    con.close()
    return {r["key"]: json.loads(r["value"]) for r in rows}


def set_settings(values: dict[str, Any]) -> None:
    con = connect()
    with con:
        con.executemany(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            [(k, json.dumps(v)) for k, v in values.items()],
        )
    con.close()
