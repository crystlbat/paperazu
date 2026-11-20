"""An @ai question on a note about a formula takes it apart in small steps instead of searching the paper."""
from types import SimpleNamespace

import pymupdf

from workbench import canvas, db, formula, library, llm, primer
from workbench.settings import Settings


def test_formula_note_is_taken_apart(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(db, "PAPERS_DIR", tmp_path / "papers")
    db.init()
    doc = pymupdf.open()
    pg = doc.new_page()
    pg.insert_text((72, 100), "Proximity is the mean distance from each counterfactual to the input.", fontsize=10)
    pg.insert_text((72, 140), "Proximity := -1/k sum dist(c_i, x) (3)", fontsize=10)
    pg.insert_text((72, 180), "where k is the number of counterfactuals and dist is a distance.", fontsize=10)
    pid = library.create(doc.tobytes(), "p.pdf")
    seen = []

    def create(**kw):
        sys = kw["messages"][0]["content"]
        seen.append((sys, kw["messages"][1]["content"]))
        out = ("Proximity = -(1/k) * sum_{i=1..k} dist(c_i, x)" if sys.startswith("Copy") else
               "1. Take k = 2.\n2. Distances 1 and 3.\nSo the average distance is 2." if "tiny made-up" in sys else
               "Think of it as checking how far your friends stand from you." if "friendly tutor" in sys else "k is how many you make.")
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=out))])

    monkeypatch.setattr(llm, "pick_model", lambda s: "m")
    monkeypatch.setattr(llm, "client", lambda *a, **k: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    monkeypatch.setattr(primer, "_complete", lambda *a, **k: '{"what": "How close the examples are to you.", "pieces": '
                        '[{"piece": "k", "means": "how many examples"}, {"piece": "dist(c_i, x)", "means": "how far one is"}]}')
    s = Settings(dot_persona="jarvis")
    card = canvas.add_card(pid, canvas.CardIn(kind="note", entries=[{"who": "me", "text": "@ai what is k?"}], x=0, y=0, w=240,
                                              page=1, rect=[60, 128, 400, 146]))
    out = canvas.pickup(s, pid, card["id"])
    text = out["card"]["entries"][-1]["text"]
    assert out["ok"] and out["sources"] == []
    assert text.startswith("Your question: k is how many")
    assert "- k — how many examples" in text and "Try it with numbers:" in text and "checking how far" in text
    assert any(isinstance(u, list) for _, u in seen)  # the formula was read off its picture
    assert all("jarvis" in sy for sy, _ in seen if "friendly tutor" in sy or "Answer their question" in sy)


def test_generic_and_simpler_asks() -> None:
    assert formula.GENERIC.match("explain this formula") and formula.GENERIC.match("break it down")
    assert not formula.GENERIC.match("what is Ck?")
    assert formula.EASIER.search("simplify each term")


def test_latex_comes_back_as_plain_text() -> None:
    assert formula._plain(r"\Delta = \frac{1}{\text{choose}(k, 2)} \sum dist, hinge\_yloss, $x_i$ costs $5") == \
        "Δ = (1)/(choose(k, 2)) sum dist, hinge_yloss, x_i costs $5"
