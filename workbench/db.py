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
CREATE TABLE IF NOT EXISTS concept_links (
    concept_id TEXT NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
    paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    page INTEGER NOT NULL,
    snippet TEXT NOT NULL,
    score REAL NOT NULL,
    PRIMARY KEY (concept_id, paper_id)
);
CREATE TABLE IF NOT EXISTS checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    step_id TEXT NOT NULL,
    notes TEXT NOT NULL,
    result TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
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
