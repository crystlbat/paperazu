"""Take a formula apart so it clicks: several small model calls, each with one job a small model can do well.

1. Read the formula off a picture of it (PDF text of maths comes out jumbled) into one plain line.
2. Name every piece, using the paper's own "where ..." lines around it.
3. Work it through with tiny made-up numbers.
4. Talk it through like a tutor: plain, relatable, each piece linked to the next and to why the paper needs it, in Dot's voice (and the student's own question answered, if they asked one).
"""
import json
import re
from typing import Any


from . import llm, marks

READ_SYSTEM = (
    "Copy the formula in the picture into ONE line of plain text. Write sums as sum_{i=1..k}, fractions as (top)/(bottom), "
    "x_i for subscripts, x^2 for powers, |x| for absolute value, sqrt(x), max(a, b), and binomials as choose(k, 2): a C with k and 2 stacked on it (C^k_2 or C_2^k) is choose(k, 2), the number of pairs, never a power. "
    "No LaTeX, no words, no explanation: reply with the formula only, written like this example: "
    "y = (1/n) * sum_{i=1..n} |a_i - b| / s_i"
)
FIX_SYSTEM = (
    "This formula was copied out of a PDF and came out jumbled (odd letters, lost fractions and sums). Rewrite it as ONE "
    "line of plain text: sums as sum_{i=1..k}, fractions as (top)/(bottom), x_i, x^2, |x|, choose(k, 2). "
    "Use the sentences around it to fix it. Reply with the formula only."
)
PIECES_SYSTEM = (
    "You help a student who finds maths hard. You get one formula from a paper and the paper's sentences around it. "
    "Reply with JSON only: {\"what\": one plain sentence saying what the formula works out and why the paper needs it, "
    "\"pieces\": [{\"piece\": a symbol or part of the formula, \"means\": what it is, in everyday words}]}. "
    "The paper's own definitions come first and are always right: copy their meaning, never contradict them. Never list the whole formula as one piece, and never add anything that is not written in the formula. "
    "Cover every symbol, every sum (say what it adds up over), every fraction, absolute value and max, in the order they "
    "appear, at most 10 pieces. Use the paper's own definitions from the sentences around it. Never use LaTeX."
)
EXAMPLE_SYSTEM = (
    "You help a student who finds maths hard. Work the formula through with tiny made-up numbers so they can see it happen. "
    "At most 6 short numbered steps. Pick the smallest case that still shows the idea (two or three items). Show the "
    "arithmetic in each step. Use every part of the formula, keeping each minus sign; if a sum runs over d items, give "
    "exactly d items. Then one line starting \"So\" that says what the result means. Plain text, no LaTeX."
)
STORY_SYSTEM = (
    "You are a friendly tutor talking a student through one formula from a paper, out loud, so it clicks. Write 4 or 5 "
    "short sentences of plain, warm speech, no lists, no symbols beyond the names in the formula. Start with the problem "
    "the paper is solving and why it needs this formula. Then walk through the formula left to right, linking each piece "
    "to the next (\"so\", \"that is why\", \"then\"), and tie it to one everyday thing the student knows (shopping, a "
    "race, friends in a room). End with what the result tells them, taken from the worked example's last line. Only say "
    "what the definitions and the example show: if you are not sure whether something grows or shrinks, leave it out."
)
CHECK_SYSTEM = (
    "Check a worked example of a formula. Redo every sum, product and max yourself. Fix any wrong arithmetic and any claim "
    "the numbers do not show (such as calling a value the biggest or worst). Put back any minus sign or item the formula "
    "has but the example dropped. Keep the same steps and the same numbers. "
    "Reply with the corrected example only, in the same format, with no comments about what you changed."
)
QUESTION_SYSTEM = (
    "You help a student who finds maths hard. Answer their question about this formula in 1 to 3 short sentences, in "
    "everyday words, using the pieces explained below and the paper's sentences. The student may write a symbol loosely "
    "(Ck for choose(k, 2), the number of ways to pick 2 out of k). If the paper does not say, say so."
)
SIMPLER = (" Explain as to a 12-year-old: short everyday words only, no symbols or jargon in the meanings, one idea per piece.")

GENERIC = re.compile(r"^\s*(?:please\s+)?(?:explain|break|deconstruct|simplif|take .* apart|walk|help|what does (?:this|it)|"
                     r"what is this|this|it|what'?s this|how does (?:this|it) work|summar)", re.I)
EASIER = re.compile(r"simpl|easier|again|eli5|like i'?m|don'?t get|not clear|confus|plain", re.I)


def _chat(s: Any, system: str, text: str, image: str | None = None, tokens: int = 400) -> str:
    """One short reply. With `image`, a text-only server is asked again without it. Raises RuntimeError for the user."""
    content: Any = [{"type": "text", "text": text}, {"type": "image_url", "image_url": {"url": image}}] if image else text
    try:
        out = llm.chat(s, [{"role": "system", "content": system}, {"role": "user", "content": content}],
                       max_tokens=min(tokens, s.max_output_tokens), temperature=min(s.temperature, 0.3))
    except llm.ModelError as e:
        if image and e.status in (400, 415, 422, 500, 501):
            return _chat(s, system, text, None, tokens)
        raise
    return _plain(out)


_TEX = {"Delta": "\u0394", "delta": "\u03b4", "sum": "sum", "times": "\u00d7", "cdot": "\u00b7", "le": "\u2264", "ge": "\u2265",
        "leq": "\u2264", "geq": "\u2265", "neq": "\u2260", "alpha": "\u03b1", "beta": "\u03b2", "lambda": "\u03bb", "sigma": "\u03c3",
        "mu": "\u03bc", "pi": "\u03c0", "theta": "\u03b8", "infty": "\u221e", "approx": "\u2248", "in": "\u2208", "max": "max", "min": "min"}


def _plain(text: str) -> str:
    """Cards show plain text, but models often answer in LaTeX: turn the common commands back into plain writing."""
    text = re.sub(r"\$\$?([^$]+?)\$\$?", r"\1", text)
    text = re.sub(r"\\(?:text|mathrm|mathbf|mathit|operatorname)\{([^{}]*)\}", r"\1", text)
    for _ in range(3):  # nested fractions, innermost first
        text = re.sub(r"\\[dt]?frac\{([^{}]*)\}\{([^{}]*)\}", r"(\1)/(\2)", text)
    text = re.sub(r"\\(?:left|right|big|Big|,|;|!|quad)\s*", "", text)
    text = re.sub(r"\\([A-Za-z]+)", lambda m: _TEX.get(m[1], m[1]), text)
    return text.replace("\\_", "_").replace("\\{", "{").replace("\\}", "}")


def _line(text: str) -> str:
    """The formula line out of a reply that may wrap it in quotes, code fences or a lead-in."""
    lines = [l.strip().strip("`$").strip() for l in text.splitlines() if l.strip().strip("`$").strip()]
    lines = [l for l in lines if not re.match(r"^(?:here|the formula|formula)\b.*:$", l, re.I)]
    return re.sub(r"^(?:formula\s*:\s*)", "", lines[0], flags=re.I)[:300] if lines else ""


def _in(piece: str, formula: str) -> bool:
    """A piece the model named really is a part of the formula (and not the whole of it)."""
    bits, whole = re.findall(r"[A-Za-z]+|\d+", piece), set(re.findall(r"[A-Za-z]+|\d+", formula))
    flat = re.sub(r"\s+", "", formula)
    return bool(bits) and all(b in whole for b in bits) and len(re.sub(r"\s+", "", piece)) < 0.5 * len(flat)


def _choose(formula: str, raw: str) -> str:
    """Pictures of C with k over 2 often come back as a power (C_k^2). The PDF text keeps the stacked digit and letter."""
    if not re.search(r"\bC\s*\d\s*[a-z]\b|\bC\s*[a-z]\s*\d\b", raw):
        return formula
    return re.sub(r"C(?:_\{?([a-z])\}?\^\{?(\d)\}?|\^\{?([a-z])\}?_\{?(\d)\}?|_\{?(\d)\}?\^\{?([a-z])\}?|\^\{?(\d)\}?_\{?([a-z])\}?)",
                  lambda m: f"choose({m[1] or m[3] or m[6] or m[8]}, {m[2] or m[4] or m[5] or m[7]})", formula)


def _sentences(text: str, n: int, last: bool = False) -> str:
    """The first (or last) n sentences: the text round a formula soon runs into the next topic."""
    parts = re.split(r"(?<=[.:])\s+(?=[A-Z])", text.strip())
    return " ".join(parts[-n:] if last else parts[:n])


def _pieces(s: Any, formula: str, setup: str, easy: bool) -> tuple[str, list[dict[str, str]]]:
    from . import primer  # primer imports llm
    schema = {"type": "object", "required": ["what", "pieces"], "properties": {
        "what": {"type": "string"},
        "pieces": {"type": "array", "items": {"type": "object", "required": ["piece", "means"], "properties": {
            "piece": {"type": "string"}, "means": {"type": "string"}}}}}}
    msgs = [{"role": "system", "content": PIECES_SYSTEM + (SIMPLER if easy else "")},
            {"role": "user", "content": f"{setup}Formula: {formula}\n\nReturn the JSON."}]
    best: tuple[int, str, list[dict[str, str]]] = (0, "", [])
    for _ in range(3):
        try:
            got = json.loads(re.search(r"\{.*\}", primer._complete(s, msgs, schema, "pieces"), re.S)[0])
        except primer.PrimerError as e:
            raise RuntimeError(str(e))
        except (TypeError, ValueError):
            continue
        seen, out = set(), []
        for p in got.get("pieces") or []:
            if isinstance(p, dict) and (k := str(p.get("piece", "")).strip()) and str(p.get("means", "")).strip() and k not in seen:
                seen.add(k)
                out.append({"piece": _plain(k)[:60], "means": _plain(str(p["means"]).strip())[:300]})
        # a real meaning has a few words and is not the piece said again
        out = [p for p in out if _in(p["piece"], formula) and len(p["means"].split()) >= 3 and p["means"].strip(" .") != p["piece"]]
        if len(out) >= 3:
            return _plain(str(got.get("what", "")).strip())[:400], out[:10]
        best = max(best, (len(out), str(got.get("what", "")).strip()[:400], out), key=lambda b: b[0])
        msgs += [{"role": "assistant", "content": json.dumps(got)},
                 {"role": "user", "content": "Break it smaller: each symbol, sum, fraction and function on its own piece (a name like dist or logit is "
                                             "one symbol, never split a word into letters), never the whole formula. Return the JSON."}]
    return best[1], best[2][:10]


def breakdown(s: Any, paper_id: str, page: int, rect: list[float], question: str = "") -> dict[str, Any]:
    """{ok, text, trace} for the formula in `rect` on `page` (1-based), or {ok: False, error}."""
    box = marks.boxed(paper_id, page, rect)
    if box is None:
        return {"ok": False, "error": "That part of the page is not there."}
    raw, image = box
    up, down = marks.around(paper_id, page, rect)
    up, down = _sentences(up, 2, last=True), _sentences(down, 1)
    setup = (f"The paper's own definitions (\"where ...\"), always right: \"{down}\"\n" if re.match(r"\s*where\b", down, re.I) else
             f"The paper just after it: \"{down}\"\n" if down else "") + (f"The paper just before it: \"{up}\"\n" if up else "")
    easy = bool(EASIER.search(question))
    own = question.strip() and not GENERIC.match(question) and not easy
    trace = []
    try:
        formula = _line(_chat(s, READ_SYSTEM, f"The PDF's own copy of it, for the letters: {raw[:400]}", image, 200))
        formula = _choose(formula, raw)
        trace.append("read the formula off its picture")
        for a, b in re.findall(r"choose\((\w+),\s*(\w+)\)", formula)[:2]:  # small models read it backwards
            setup += f"Note: choose({a}, {b}) means the number of ways to pick {b} things out of {a} (choose(3, 2) = 3).\n"
        if not formula or len(formula) < 3:
            formula = _line(_chat(s, FIX_SYSTEM, f"{setup}Jumbled copy: {raw[:400]}", None, 200)) or raw[:300]
            trace.append("picture unreadable, rebuilt from the text")
        what, pieces = _pieces(s, formula, setup, easy)
        trace.append(f"named {len(pieces)} pieces")
        listed = "\n".join(f"- {p['piece']}: {p['means']}" for p in pieces)
        example = llm._no_loops(_chat(s, EXAMPLE_SYSTEM + (SIMPLER if easy else ""),
                                      f"{setup}Formula: {formula}\nWhat the pieces mean:\n{listed}\n\nWork it through.", None, 450))
        checked = llm._no_loops(_chat(s, CHECK_SYSTEM, f"{setup}Formula: {formula}\n\nWorked example:\n{example}", None, 450))
        example = checked if len(checked) > 0.5 * len(example) else example  # a checker that cut most of it is not trusted
        trace.append("worked an example and checked it")
        story = _chat(s, STORY_SYSTEM + (SIMPLER if easy else "") + llm.persona(s),
                      f"{setup}Formula: {formula}\nIt works out: {what}\nPieces:\n{listed}\nA worked example:\n{example}\n\nTalk me through it.",
                      None, 360)
        trace.append("talked it through")
        answer = _chat(s, QUESTION_SYSTEM + llm.persona(s), f"{setup}Formula: {formula}\nPieces:\n{listed}\n\nQuestion: {question}",
                       None, 220) if own else ""
        if own:
            trace.append("answered your question")
    except RuntimeError as e:
        return {"ok": False, "error": str(e), "trace": trace}
    parts = ([f"Your question: {answer.strip()}", ""] if answer else []) + [story.strip(), "", f"The formula: {formula}", ""]
    if pieces:
        parts += ["Piece by piece:", *(f"- {p['piece']} — {p['means']}" for p in pieces), ""]
    parts += ["Try it with numbers:", example.strip()]
    return {"ok": True, "text": "\n".join(parts).strip(), "formula": formula, "pieces": pieces, "trace": trace}
