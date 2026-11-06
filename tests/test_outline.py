from pathlib import Path
from typing import Any

import pymupdf
import pytest

from workbench import db, library


@pytest.fixture(autouse=True)
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(db, "PAPERS_DIR", tmp_path / "papers")
    db.init()


def _doc(lines: list[list[tuple[str, float, str]]]) -> pymupdf.Document:
    """Pages of (text, size, font) lines."""
    doc = pymupdf.open()
    for page_lines in lines:
        page = doc.new_page()
        y = 72
        for text, size, font in page_lines:
            page.insert_text((72, y), text, fontsize=size, fontname=font)
            y += size * 1.8
    return doc


def _titles(node: dict[str, Any]) -> list[tuple[int, str]]:
    return [(node["level"], node["title"])] + [t for c in node["children"] for t in _titles(c)]


BODY = ("Some ordinary body text that goes on for a while to set the size.", 10, "helv")


def test_uses_pdf_outline_and_hangs_figures() -> None:
    doc = _doc([[BODY], [BODY, ("Figure 1: A map of the city streets.", 9, "helv")], [BODY, ("Table 2. Results by group.", 9, "helv")]])
    doc.set_toc([[1, "1 Introduction", 1], [1, "2 Method", 2], [2, "2.1 Data", 2], [3, "2.1.1 Cameras", 3]])
    pid = library.create(doc.tobytes(), "p.pdf")
    out = library.outline(pid, "My paper")
    assert out is not None and out["source"] == "outline" and out["pages"] == 3
    assert _titles(out["tree"]) == [(1, "My paper"), (2, "1 Introduction"), (2, "2 Method"), (3, "2.1 Data"),
                                    (4, "2.1.1 Cameras"), (4, "Figure 1: A map of the city streets."), (4, "Table 2: Results by group.")]


def test_guesses_headings_without_outline() -> None:
    doc = _doc([[("1 Introduction", 13, "hebo"), BODY, BODY, ("2 Our Method", 13, "hebo"), ("2.1 Setup Details", 11, "hebo"), BODY],
                [("References", 12, "hebo"), BODY, ("3 is not a heading in body text", 10, "helv")]])
    pid = library.create(doc.tobytes(), "p.pdf")
    out = library.outline(pid, "T")
    assert out is not None and out["source"] == "guessed"
    assert _titles(out["tree"])[1:] == [(2, "1 Introduction"), (2, "2 Our Method"), (3, "2.1 Setup Details"), (2, "References")]


def test_missing_paper() -> None:
    assert library.outline("abc123", "T") is None
