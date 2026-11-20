"""Guided reading finds a whole section from the PDF itself: outline or fonts, columns, reading order."""
import pymupdf
import pytest

from workbench import db, sections


def _paper(tmp_path, monkeypatch, toc: bool) -> str:
    """Two pages, two columns. Page 1: title, authors; left column "1 Introduction"; right column carries the
    introduction on, then "2 Method" with "2.1 Setup"; page 2 left column carries 2.1 on, then "3 Results"."""
    monkeypatch.setattr(db, "PAPERS_DIR", tmp_path)
    doc = pymupdf.open()
    doc.new_page(); doc.new_page()
    p1, p2 = doc[0], doc[1]

    def put(pg, x, y, text, size=9, bold=False):
        font = "hebo" if bold else "helv"
        for i, line in enumerate(text.split("\n")):
            pg.insert_text((x, y + i * size * 1.25), line, fontsize=size, fontname=font)
        return y + len(text.split("\n")) * size * 1.25

    put(p1, 120, 70, "A Paper About Seeds", size=18, bold=True)
    put(p1, 60, 100, "Ada Lovelace", size=12)
    put(p1, 360, 100, "Alan Turing", size=12)
    y = put(p1, 54, 150, "1 Introduction", size=11, bold=True)
    for _ in range(8):
        y = put(p1, 54, y + 2, "Seeds change fairness scores a lot between runs.\nThe data order matters most of all here.")
    y = 150
    for _ in range(4):
        y = put(p1, 318, y + 2, "More introduction text about the variance we\nsee across many runs of the same model.")
    y = put(p1, 318, y + 14, "2 Method", size=11, bold=True)
    y = put(p1, 318, y + 4, "We train many models with different seeds and\nrecord the fairness of each one carefully.")
    y = put(p1, 318, y + 14, "2.1 Setup", size=11, bold=True)
    for _ in range(4):
        y = put(p1, 318, y + 2, "The setup uses a small network and one dataset\nwith a fixed split for every single run.")
    y = 80
    for _ in range(3):
        y = put(p2, 54, y + 2, "The setup goes on here with the learning rate\nand the batch size kept the same for all.")
    y = put(p2, 54, y + 14, "3 Results", size=11, bold=True)
    put(p2, 54, y + 4, "Data order explains most of the variance we\nfound in the fairness of the trained models.")
    if toc:
        doc.set_toc([[1, "1 Introduction", 1], [1, "2 Method", 1], [2, "2.1 Setup", 1], [1, "3 Results", 2]])
    doc.save(tmp_path / "abc123.pdf")
    sections._read.cache_clear()
    return "abc123"


@pytest.mark.parametrize("toc", [True, False])
def test_introduction_runs_down_the_left_then_the_right_column(tmp_path, monkeypatch, toc) -> None:
    pid = _paper(tmp_path, monkeypatch, toc)
    out = sections.find(pid, "Introduction", 1)
    assert out["heading"]["page"] == 1 and out["heading"]["box"][0] < 100
    segs = out["segments"]
    assert [s["page"] for s in segs] == [1, 1]
    left, right = segs[0]["box"], segs[1]["box"]
    assert left[2] < 306 and right[0] > 306  # one stretch per column
    assert right[1] > 120  # the right column starts under the authors, not at them
    assert right[3] < 260  # and stops before "2 Method"


@pytest.mark.parametrize("toc", [True, False])
def test_a_section_takes_in_its_subsections_and_runs_on_to_the_next_page(tmp_path, monkeypatch, toc) -> None:
    pid = _paper(tmp_path, monkeypatch, toc)
    out = sections.find(pid, "Method", 1)
    assert out["subs"] == ["2.1 Setup"]
    pages = [s["page"] for s in out["segments"]]
    assert pages[0] == 1 and pages[-1] == 2
    assert out["segments"][-1]["box"][3] < 200  # page 2 stops before "3 Results"


def test_unknown_heading_or_paper_is_none(tmp_path, monkeypatch) -> None:
    pid = _paper(tmp_path, monkeypatch, True)
    assert sections.find(pid, "Nothing like this", 1) is None
    assert sections.find("nope", "Introduction", 1) is None


def test_a_figure_stage_finds_its_caption(tmp_path, monkeypatch) -> None:
    pid = _paper(tmp_path, monkeypatch, True)
    doc = pymupdf.open(tmp_path / "abc123.pdf")
    doc[1].insert_text((54, 400), "Figure 1: Fairness across seeds.", fontsize=9, fontname="helv")
    doc[1].insert_text((54, 411), "Each bar is one training run.", fontsize=9, fontname="helv")
    doc.saveIncr()
    sections._read.cache_clear()
    out = sections.find(pid, "Figure 1", 1)
    assert out["heading"]["page"] == 2 and out["segments"][0]["box"][3] > 405
