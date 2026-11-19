"""Context budget: how much of the paper fits in one model request."""
from collections.abc import Iterator

# shortcut: a rough count (English text runs about 3.5 to 4 characters per token). It errs on the
# side of sending less. Switch to the server's /tokenize if requests start overflowing.
CHARS_PER_TOKEN = 3.5


def tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN) + 1


def _outward(around: int, n: int) -> Iterator[int]:
    """around, around+1, around-1, around+2, ... within 0..n-1."""
    yield around
    for d in range(1, n):
        for i in (around + d, around - d):
            if 0 <= i < n:
                yield i


def fit_pages(pages: list[str], budget: int, around: int = 0) -> list[int]:
    """Page indexes to send, in page order. Every page if the paper fits; otherwise the pages
    nearest `around`, added outward until the next one would pass the budget."""
    if sum(tokens(p) for p in pages) <= budget:
        return list(range(len(pages)))
    chosen: list[int] = []
    used = 0
    for i in _outward(around, len(pages)):
        t = tokens(pages[i])
        if used + t > budget:
            if not chosen:
                chosen.append(i)  # the marked page always goes; the caller cuts it to size
            break
        chosen.append(i)
        used += t
    return sorted(chosen)
