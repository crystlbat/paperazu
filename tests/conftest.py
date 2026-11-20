import pytest

from shared import db, llm


@pytest.fixture(autouse=True)
def _never_the_real_database(tmp_path, monkeypatch) -> None:
    """Every test gets its own empty database. A test file that forgets its own fixture must not reach data/workbench.db."""
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(db, "PAPERS_DIR", tmp_path / "papers")
    db.init()


@pytest.fixture(autouse=True)
def _fresh_model_memory() -> None:
    """The window a server reported and the model picked are remembered per process; each test starts clean."""
    llm._windows.clear()
    llm._picked.clear()


@pytest.fixture(autouse=True)
def _no_reply_grading(monkeypatch) -> None:
    """Grading each reply is one more model call; tests that count calls would see it. A test about grading turns it back on."""
    from harness_char import char
    monkeypatch.setattr(char, "GRADE_REPLIES", False)
