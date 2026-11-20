"""What the local model says about a paper: explain marked words, answer questions, pick quotes, name sources.
Every call goes through shared.llm.chat."""
import json
import re
import time
from typing import Any

from pdf_research import primer
from shared import context, llm
from shared.settings import Settings


EXPLAIN_SYSTEM = (
    "You help a student read a research paper. The student marked some words. Explain what they mean "
    "as they are used in this paper, in simple English, in 3 to 5 short sentences. Say what the words "
    "mean and why they matter here. Do not summarize the paper's results. If the paper does not define "
    "them, say so and give the usual meaning. If the marked text is a formula or notation (it may look "
    "jumbled after copying out of the PDF), say what each symbol stands for in this paper and what the "
    "formula says as a whole. If a picture of the marked part comes with the question, trust it over the copied text. No headings, no lists."
)

FORMULA_SYSTEM = (
    "You help a student read a research paper. The student marked a formula (copied out of the PDF it may look "
    "jumbled; if a picture of it comes with the question, read the picture). Take it apart term by term.\n"
    "1. One plain sentence: what the formula computes and what it is for in this paper.\n"
    "2. Then a list, one line per term, symbol or operation, in the order they appear, each line as "
    "\"- term \u2014 what it is, in everyday words\". Cover every piece: each symbol, each fraction (top and "
    "bottom), each sum (what it adds up over), indicator brackets, absolute values, and the subscripts and "
    "superscripts. Write symbols plainly (F1, TP, sum over D^e, 1[f(x)=1 and a=0]), never LaTeX. Use the "
    "paper's own definitions from the text around the formula.\n"
    "3. Then a line starting \"In plain words:\" with 2 or 3 sentences that put it back together, and one tiny "
    "example with made-up numbers if it helps.\n"
    "Name each term once, at most 14 lines in the list. Keep step 1 to one sentence. If several formulas are "
    "marked, do this for each in turn. Read what the paper says right after the formula (\"where ...\") and use "
    "it. Do not guess what the paper does not say."
)


def persona(s: Settings) -> str:
    """The voice the student picked for Dot, as a line for a system prompt (empty when none)."""
    p = (s.dot_persona or "").strip()[:300]
    return f"\nSpeak in this voice, chosen by the student: {p}. Keep every fact and the format exactly as asked." if p else ""


def _no_loops(text: str) -> str:
    """Small models fall into a loop on long lists: keep each line once and stop where it starts going round."""
    out, seen, again = [], set(), 0
    for line in text.splitlines():
        key = re.sub(r"\W+", " ", line).strip().lower()
        if key and key in seen:
            again += 1
            if again >= 2:
                break
            continue
        seen.add(key)
        out.append(line)
    return "\n".join(out).strip()


def _formula(words: str) -> bool:
    """Marked text that is math rather than prose."""
    return ":=" in words or len(re.findall(r"[=\u2211\u03a3\u2227\u2228\u2208\u2206\u0394{}\[\]^_|\u223c~]", words)) >= 4 or not _readable(words)


def paper_text(s: Settings, pages: list[str], page: int, overhead: str) -> tuple[str, list[int]]:
    """The paper as page-labelled text: every page if it fits the context budget, else the pages
    nearest `page` (0-based). Returns the text and the page indexes used."""
    budget = llm.window(s) - llm.reply_tokens(s) - context.tokens(overhead) - 6 * len(pages) - 100
    keep = context.fit_pages(pages, budget, page) if pages else []
    room = int(budget * context.CHARS_PER_TOKEN)
    return "\n\n".join(f"--- Page {i + 1} ---\n{pages[i].strip()}" for i in keep)[:max(room, 0)], keep


IDEAS_SYSTEM = (
    "You read research papers and name their key ideas. Reply with exactly 5 lines. Each line is one "
    "idea from this paper in 2 to 5 plain words, such as a method, a concept, a problem or a finding. "
    "No numbering, no bullets, no explanations, no full sentences.\n"
    "Example for a paper about image classifiers:\nResidual connections\nVanishing gradients\n"
    "ImageNet benchmark\nData augmentation\nTop-1 accuracy"
)

_CUT = {"is", "are", "was", "were", "can", "could", "enable", "enables", "allow", "allows", "fail", "fails",
        "help", "helps", "show", "shows", "needs", "need", "needed", "lead", "leads", "make", "makes", "reveal",
        "reveals", "remain", "remains", "provide", "provides", "should", "must", "may", "will", "without", "despite",
        "extend", "extends", "require", "requires", "identified", "across", "beyond", "like", "such", "including",
        "using", "used", "based", "that", "which", "has", "have", "does", "do", "vary", "varies",
        "differ", "differs", "reflect", "reflects", "fit", "fits", "systematically", "need", "into"}
_TAIL = {"and", "or", "of", "the", "a", "an", "for", "to", "in", "on", "with", "by"}


def _short_idea(line: str) -> str:
    """Small models often answer with a sentence; keep its opening noun phrase (at most 5 words)."""
    line = re.sub(r"\s*\([^)]*$", "", line)  # an unclosed bracket means the phrase was cut
    words = line.split()
    for i, w in enumerate(words[2:], 2):
        if w.lower().strip(",;") in _CUT:
            words = words[:i]
            break
    words = words[:5]
    while words and words[-1].lower().strip(",;") in _TAIL:
        words.pop()
    return " ".join(words).strip(",;")


def key_ideas(s: Settings, title: str, pages: list[str]) -> list[str]:
    """Five short key ideas from the whole paper. Raises RuntimeError with a message for the user."""
    paper, _ = paper_text(s, pages, 0, IDEAS_SYSTEM + title)
    text = llm.chat(s, [{"role": "system", "content": IDEAS_SYSTEM},
                    {"role": "user", "content": f"Paper: {title}\n\n<paper>\n{paper}\n</paper>\n\nThe 5 key ideas:"}])
    ideas: list[str] = []
    for line in text.splitlines():
        line = _short_idea(re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip().strip("*\"'.:").strip())
        if 2 <= len(line) <= 60 and line.lower() not in (i.lower() for i in ideas):
            ideas.append(line)
    return ideas[:5]


ASK_SYSTEM = (
    "You help a student read a research paper. Answer the student's question using this paper, in simple "
    "English, in at most 6 short sentences. Name the page when you use one. If the paper does not answer "
    "it, say so and give the usual answer. No headings."
)


def _answer(s: Settings, system: str, question: str, title: str, pages: list[str], page: int,
            image: str | None = None, _again: bool = False) -> dict[str, Any]:
    """One question to the local model with the paper (or what fits) as context. `page` is 0-based.
    `image` is a data: URL sent with the question; if the server will not take images, it asks again without.
    A window smaller than the setting is remembered and the pages nearest `page` are picked again to fit it."""
    page = min(max(page, 0), max(len(pages) - 1, 0))
    paper, keep = paper_text(s, pages, page, system + question + title)
    start = time.perf_counter()
    prompt = f"Paper: {title}\n\n<paper>\n{paper}\n</paper>\n\n{question}"
    content: Any = [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": image}}] if image else prompt
    before = llm.window(s)
    try:
        text = llm.chat(s, [{"role": "system", "content": system + persona(s)}, {"role": "user", "content": content}], trim=_again)
    except llm.ModelError as e:
        if llm.window(s) < before:  # the loaded window is smaller than the setting: ask again with the pages that fit it
            return _answer(s, system, question, title, pages, page, image, _again=True)  # cut to fit if still too long
        if image and e.status in (400, 415, 422, 500, 501):  # a text-only model: ask without the picture
            return _answer(s, system, question, title, pages, page, _again=_again)
        return {"ok": False, "error": str(e)}
    return {"ok": True, "text": text, "pages": [keep[0] + 1, keep[-1] + 1] if keep else [],
            "whole": len(keep) == len(pages), "total": len(pages), "seconds": round(time.perf_counter() - start, 1)}


def explain(s: Settings, words: str, title: str, pages: list[str], page: int, image: str | None = None,
            near: tuple[str, str] = ("", "")) -> dict[str, Any]:
    """Explain marked words with the whole paper as context (or as much as fits the budget), and a picture of them if given."""
    page = min(max(page, 0), max(len(pages) - 1, 0))
    if _formula(words):
        setup = (f"The paper just before it: \"{near[0]}\"\n" if near[0] else "") + (f"The paper just after it: \"{near[1]}\"\n" if near[1] else "")
        question = f'{setup}The formula I marked on page {page + 1}: "{words}"\nTake it apart term by term, then simplify it.'
        got = _answer(s, FORMULA_SYSTEM, question, title, pages, page, image)
        return {**got, "text": _no_loops(got["text"])} if got.get("ok") and got.get("text") else got
    question = f'Words I marked on page {page + 1}: "{words}"\nWhat do they mean in this paper?'
    return _answer(s, EXPLAIN_SYSTEM, question, title, pages, page, image)


def ask(s: Settings, question: str, title: str, pages: list[str], page: int) -> dict[str, Any]:
    """Answer a free question about the paper. `page` is the 0-based page the student is looking at."""
    page = min(max(page, 0), max(len(pages) - 1, 0))
    return _answer(s, ASK_SYSTEM, f"I am looking at page {page + 1}. My question: {question}", title, pages, page)


BOX_SYSTEM = (
    "You help a student read a research paper. The student drew a box round part of a page and asked about it. "
    "You get the text inside the box (formulas may look jumbled after copying out of the PDF) and, when possible, "
    "a picture of the box: trust the picture for formulas. Answer in simple English, in 2 to 5 short sentences, "
    "about the boxed part as it is used in this paper. For a formula, say what each symbol stands for."
)


def ask_box(s: Settings, question: str, boxed: str, image: str | None, title: str, pages: list[str], page: int) -> dict[str, Any]:
    """Answer a question about a boxed part of a page, with a picture of the box. `page` is 0-based."""
    page = min(max(page, 0), max(len(pages) - 1, 0))
    q = f'The box I drew on page {page + 1} holds this text:\n"""\n{boxed[:3000]}\n"""\nMy question: {question}'
    return _answer(s, BOX_SYSTEM, q, title, pages, page, image)


NOTE_SYSTEM = (
    "You help a student inside their own note about a part of a research paper. You get the text of the part the "
    "note is about (formulas may look jumbled after copying out of the PDF) and, when possible, a picture of it: "
    "trust the picture for formulas. The note so far is given as earlier lines. Answer the last question in simple "
    "English, in 2 to 5 short sentences. For a formula, say what each symbol stands for."
)


def note_reply(s: Settings, lines: list[dict[str, Any]], boxed_text: str, image: str | None, title: str, pages: list[str],
               page: int) -> dict[str, Any]:
    """Dot's answer to the last `me` line of a note. `lines` are the note's entries ({who, text}); `page` is 0-based.
    Without a box (`boxed_text` empty, no `image`) it answers from the paper alone."""
    page = min(max(page, 0), max(len(pages) - 1, 0))
    last = max((i for i, e in enumerate(lines) if e["who"] == "me"), default=None)
    if last is None:
        return {"ok": False, "error": "There is no question to answer."}
    question = lines[last]["text"].strip()
    if m := re.search(r"(?im)^\s*@ai\b[\s:,-]*(.*)$", question):  # "@ai" may start any line of the entry
        question = m[1].strip() or "Explain this part in simple words."
    earlier = "".join(f"{'Student' if e['who'] == 'me' else 'Dot'}: {e['text'][:1000]}\n" for e in lines[:last])
    q = (f'The note is about this part of page {page + 1}:\n"""\n{boxed_text[:3000]}\n"""\n' if boxed_text else f"I am looking at page {page + 1}.\n")
    q += (f"The note so far:\n{earlier}\n" if earlier else "") + f"My question: {question}"
    return _answer(s, NOTE_SYSTEM, q, title, pages, page, image)


HIGHLIGHT_SYSTEM = (
    "You help a student read a research paper. You get one part of a page. Pick only the most important parts "
    "the student should remember (a key claim, a definition, a main result). Copy each one word for word from the "
    "text. Give at most {most}, each at most 25 words, never a whole paragraph. Look through the whole text, from its "
    "first sentence to its last, not only the start. "
    'Reply with JSON only: {{"quotes": ["..."]}}.'
)
_QUOTES = {"type": "object", "properties": {"quotes": {"type": "array", "items": {"type": "string"}}},
           "required": ["quotes"], "additionalProperties": False}


def pick_quotes(s: Settings, text: str, title: str, focus: str = "") -> list[str]:
    """Quotes worth highlighting in `text`, about `focus` if the student said what to look for. Raises
    primer.PrimerError for the user; broken JSON is asked twice, then []."""
    most = max(2, min(6, len(re.findall(r"[.!?](?:\s|$)", text)) // 2 + 1))  # a long paragraph gets more than a short one
    want = (f"\n\nThe student wants you to highlight: {focus}\nPick only parts about that. If nothing in the text "
            'is about it, reply {"quotes": []}.') if focus else ""
    msgs = [{"role": "system", "content": HIGHLIGHT_SYSTEM.format(most=most)},
            {"role": "user", "content": f"Paper: {title}\n\nText:\n\"\"\"\n{text[:6000]}\n\"\"\"{want}"}]
    for _ in range(2):
        try:
            reply = primer._complete(s, msgs, _QUOTES, "quotes")
            out = json.loads(reply[reply.find("{"):reply.rfind("}") + 1])["quotes"]  # some models wrap the JSON in words or fences
            out = [out] if isinstance(out, str) else out  # one quote as a plain string, not a list of letters
            return [q.strip() for q in out if isinstance(q, str) and len(q.split()) >= 3][:most]
        except (ValueError, KeyError, TypeError):
            continue
    return []


SOURCES_SYSTEM = (
    "You help a student read a research paper. Do exactly what the student asks, from the paragraphs you are given, in "
    "simple English. The request may be an instruction, not a question: \"simplify this\", \"go term by term\", "
    "\"in more detail\", \"give an example\". Then do that to the part they selected, or to the earlier answer if they "
    "selected nothing. Never answer an instruction with \"Yes\" or by repeating the earlier answer: a follow-up must add something new. Simplify means everyday words with no symbols, subscripts or LaTeX, and one small example. Elaborate means explain each part and why it is there. Term by term means "
    "one short line per symbol or term: what it stands for and why it is there. Keep a plain question to at most 6 "
    "short sentences; when they ask for detail or steps, use up to 14 short lines. Say what this paper says, in its "
    "own terms, not general knowledge. If the paragraphs do not answer it, say so in one sentence. Each paragraph has an id like p3-b7. As sources, name the ids of the "
    "paragraphs your answer uses, best first, at most 4, each paragraph once. For each one write a gist: what that "
    "paragraph says, in your own plain words, at most 12 words. Never copy a formula or symbols into a gist (formulas "
    "look jumbled after copying out of the PDF); say what the formula is for instead. "
    'Return JSON only: {"answer": "...", "sources": [{"block": "p3-b7", "gist": "..."}]}.'
)

_STOP = {"this", "that", "with", "from", "their", "they", "them", "these", "those", "which", "what", "when", "where",
         "have", "been", "were", "will", "would", "could", "should", "about", "into", "than", "then", "also", "such",
         "more", "most", "some", "other", "paper", "page", "does", "each", "only", "very", "much", "many", "there"}


def _stems(text: str) -> set[str]:
    """Content words cut to 6 letters, so "randomness" and "random" meet."""
    return {w[:6] for w in re.findall(r"[a-z]{4,}", text.lower()) if w not in _STOP}


def _readable(text: str) -> bool:
    """Mostly plain words? Formulas copied out of a PDF are not ("F1(f, D) := 2TP P+ PP=")."""
    toks = text.split()
    word = re.compile(r"\(?(?:[A-Za-z][A-Za-z'-]*|\d+(?:\.\d+)?%?)[.,;:!?)]*")
    return bool(toks) and sum(bool(word.fullmatch(t)) for t in toks) >= 0.75 * len(toks)


def _short(text: str, most: int = 14) -> str:
    words = text.split()
    return " ".join(words[:most]) + ("..." if len(words) > most else "")


def _block_id(b: Any) -> str:
    """The model's id in our form: "P3_B7", "p3 - b7" and "p3-b7 (page 3)" all mean p3-b7."""
    m = re.search(r"p\s*(\d+)\s*[-_ ]?\s*b\s*(\d+)", str(b), re.I)
    return f"p{m[1]}-b{m[2]}" if m else str(b).strip()


def _best_sentence(answer: str, para: str) -> tuple[int, str]:
    """The answer sentence that shares the most words with a paragraph, and how many it shares."""
    p = _stems(para)
    return max(((len(_stems(x) & p), x) for x in re.split(r"(?<=[.!?])\s+", answer) if x.strip()), default=(0, ""))


def _gist(gist: str, answer: str, page: int, para: str) -> str:
    """A short readable line for a source card. A copied formula is swapped for words."""
    gist = " ".join(gist.split())
    if gist and _readable(gist):
        return _short(gist, 16)
    hit, sent = _best_sentence(answer, para)
    if hit >= 2:
        return _short(sent)
    return _short(para) if _readable(para) else f"A formula on page {page}"


def _match(answer: str, paras: list[tuple[str, int, list[float], str]], most: int = 4) -> list[dict[str, Any]]:
    """When the model names no usable paragraph: the paragraphs the answer's sentences clearly come from."""
    stems = {p[0]: _stems(p[3]) for p in paras}
    out: list[dict[str, Any]] = []
    for sent in re.split(r"(?<=[.!?])\s+", answer) if paras else []:
        sw = _stems(sent)
        if len(sw) < 4:
            continue
        best = max(paras, key=lambda p: len(sw & stems[p[0]]))
        hit = len(sw & stems[best[0]])
        if hit >= 3 and hit >= 0.4 * len(sw):
            out.append({"block": best[0], "page": best[1], "rect": best[2], "gist": _short(sent)})
    return out[:most]


def _dedupe(src: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One card per paragraph, and none that says the same as another on its page."""
    def same(a: str, b: str) -> bool:
        x, y = _stems(a), _stems(b)
        return bool(x | y) and len(x & y) >= 0.6 * len(x | y)
    out: list[dict[str, Any]] = []
    for x in src:
        if not any(o["block"] == x["block"] or (o["page"] == x["page"] and same(o["gist"], x["gist"])) for o in out):
            out.append(x)
    return out


def _fit(s: Settings, paras: list[tuple[str, int, list[float], str]], overhead: str) -> list[tuple[str, int, list[float], str]]:
    """The paragraphs that fit the context budget, taken in the order given (best pages first), then in page order."""
    room = int((llm.window(s) - llm.reply_tokens(s) - context.tokens(overhead) - 300) * context.CHARS_PER_TOKEN)
    out, used = [], 0
    for p in paras:
        used += len(p[3][:1500]) + 24
        if used > room and out:
            break
        out.append(p)
    return sorted(out, key=lambda p: p[1])  # stable: paragraphs keep their order inside a page


def ask_with_sources(s: Settings, question: str, title: str, paras: list[tuple[str, int, list[float], str]],
                     earlier: str = "") -> dict[str, Any]:
    """Answer and name the paragraphs that back it up. Each para is (id, page, rect, text), best pages first."""
    from pydantic import BaseModel, ValidationError


    class Src(BaseModel):
        block: str | int
        gist: str = ""

    class Reply(BaseModel):
        answer: str
        sources: list[Src | str] | None = None

    had = len(paras)
    paras = _fit(s, paras, SOURCES_SYSTEM + title + earlier + question)
    by = {p[0]: p for p in paras}
    trace = [f"{len(paras)} paragraphs fit the model" + (f" ({had - len(paras)} cut for room)" if had > len(paras) else "")]
    schema = {"type": "object", "required": ["answer", "sources"], "properties": {
        "answer": {"type": "string"},
        "sources": {"type": "array", "items": {"type": "object", "required": ["block", "gist"], "properties": {
            "block": {"type": "string", "enum": list(by)}, "gist": {"type": "string"}}}}}}
    listing = "\n\n".join(f"{i} (page {pg}): {t[:1500]}" for i, pg, _, t in paras)
    messages = [{"role": "system", "content": SOURCES_SYSTEM + persona(s)},
                {"role": "user", "content": f"Paper: {title}\n\n<paragraphs>\n{listing}\n</paragraphs>\n\n"
                                            f"{earlier}My question: {question}\n\nReturn the JSON."}]
    try:
        for _ in range(2):
            reply = primer._complete(s, messages, schema, "sources")
            a, b = reply.find("{"), reply.rfind("}")
            try:
                out = Reply.model_validate_json(reply[a:b + 1] if a >= 0 else reply)
            except ValidationError as e:
                trace.append("reply was not valid JSON, asked again")
                messages += [{"role": "assistant", "content": reply},
                             {"role": "user", "content": f"That answer was not valid: {str(e)[:300]}\nReturn only JSON."}]
                continue
            text = out.answer.strip()
            named = [Src(block=x) if isinstance(x, str) else x for x in out.sources or []]
            src = [{"block": k, "page": by[k][1], "rect": by[k][2], "gist": _gist(x.gist, text, by[k][1], by[k][3])}
                   for x in named if (k := _block_id(x.block)) in by]
            trace.append(f"model named {len(src)} of its sources" if src else "model named no valid paragraph, matched by shared words")
            return {"ok": True, "text": text, "sources": _dedupe(src or _match(text, paras))[:4], "trace": trace}
    except primer.PrimerError as e:
        return {"ok": False, "error": str(e), "trace": trace + [f"model error: {str(e)[:120]}"]}
    trace.append("JSON failed twice, plain answer, matched by shared words")
    pages = [""] * max(p[1] for p in paras)  # paragraph text by page, for the plain answer
    for _, pg, _, t in paras:
        pages[pg - 1] += t + "\n\n"
    plain = ask(s, earlier + question, title, pages, min(p[1] for p in paras) - 1)
    return {**plain, "sources": _dedupe(_match(plain["text"], paras)) if plain["ok"] else [], "trace": trace}
