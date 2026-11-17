"""Steering and monitoring from the model's own hidden states (Beaglehole, Radhakrishnan, Boix-Adserà, Belkin, Science 2026):
a Recursive Feature Machine finds one concept direction per layer from labelled prompts; adding eps times it to every layer steers
generation toward the concept (negative eps: away), and projecting onto it reads how much of the concept a text carries.
The model runs in-process on MLX: the HTTP engines never expose hidden states."""
import hashlib
import json
import re
import threading
from pathlib import Path
from typing import Any

import numpy as np

from . import db

MODEL = "mlx-community/Qwen3.5-4B-MLX-4bit"
_M: dict[str, Any] = {}  # loaded model: name, model, tokenizer, layers, and what the taps do this call


def load(name: str = MODEL) -> None:
    _load(name)


def loaded() -> bool:
    return bool(_M.get("name"))


def unload() -> bool:
    """Free the in-process model, so another engine can have the memory. True if one was loaded."""
    if not loaded():
        return False
    import gc

    import mlx.core as mx
    with _gen_lock:
        _M.clear()
        gc.collect()
        (getattr(mx, "clear_cache", None) or mx.metal.clear_cache)()
    return True


def _load(name: str = MODEL) -> dict[str, Any]:
    if _M.get("name") == name:
        return _M
    import mlx.nn as nn
    from mlx_lm import load

    model, tok = load(name)
    inner = model
    for p in ("language_model", "model"):
        inner = getattr(inner, p, inner)

    class Tap(nn.Module):
        """One decoder layer as before, plus: add this call's vector to its output, and keep its last-token state."""
        def __init__(self, layer: Any, i: int):
            super().__init__()
            self.layer, self.i, self.is_linear = layer, i, getattr(layer, "is_linear", False)

        def __getattr__(self, k: str) -> Any:  # a model may read its layers' own fields (Gemma: layer_type)
            try:
                return super().__getattr__(k)
            except AttributeError:
                return getattr(super().__getattr__("layer"), k)

        def __call__(self, x: Any, *a: Any, **kw: Any) -> Any:  # other models pass more than mask and cache
            h = self.layer(x, *a, **kw)
            if (v := _M["add"].get(self.i)) is not None:
                h = h + v
            if _M["grab"] is not None:
                _M["grab"][self.i] = h[:, -1, :]
            return h

    for i, layer in enumerate(inner.layers):  # pipeline_layers is the same list, so both paths see the taps
        inner.layers[i] = Tap(layer, i)
    _M.clear()
    _M.update(name=name, model=model, tok=tok, n=len(inner.layers), add={}, grab=None, norm={})
    return _M


def _prompt(tok: Any, text: str | list[dict[str, str]]) -> str:
    msgs = [{"role": "user", "content": text}] if isinstance(text, str) else text
    try:
        return tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True, enable_thinking=False)
    except TypeError:
        return tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)


def states(texts: list[str], name: str = MODEL) -> np.ndarray:
    """Last-token hidden state after every layer, as [layers, texts, width]."""
    import mlx.core as mx

    m = _load(name)
    out = []
    for t in texts:
        m["grab"] = {}
        ids = mx.array(m["tok"].encode(_prompt(m["tok"], t)))[None]
        m["model"](ids)
        out.append(np.stack([np.array(m["grab"][i][0].astype(mx.float32)) for i in range(m["n"])]))
    m["grab"] = None
    return np.stack(out, axis=1)


def rfm(X: np.ndarray, y: np.ndarray, iters: int = 5, ridge: float = 1e-3) -> tuple[np.ndarray, float]:
    """One concept direction from states X [n, d] and labels y: kernel ridge with a Mahalanobis Laplace kernel, then M := AGOP
    of the fitted predictor, a few times; the direction is M's top eigenvector, signed to correlate with y. Returns (unit v, |corr|).
    shortcut: the bandwidth is the median pairwise distance, not the paper's validation pick from {1, 10, 100}; sweep it if fits are poor."""
    X = X - X.mean(0)
    n, d = X.shape
    y = y.astype(float)
    M = np.eye(d) / d
    for _ in range(iters):
        XM = X @ M
        q = np.einsum("ij,ij->i", XM, X)
        dist = np.sqrt(np.maximum(q[:, None] + q[None, :] - 2 * XM @ X.T, 0))
        bw = np.median(dist[dist > 0]) or 1.0
        K = np.exp(-dist / bw)
        a = np.linalg.solve(K + ridge * np.eye(n), y)
        W = np.where(dist > 0, a[:, None] * K / (bw * np.where(dist > 0, dist, 1)), 0)  # W[i, j]: point i's pull on the gradient at j
        G = -(X * W.sum(0)[:, None] - W.T @ X) @ M  # row j: grad of the predictor at x_j
        M = G.T @ G / n
        M /= np.trace(M) or 1.0
    v = np.random.default_rng(0).standard_normal(d)
    for _ in range(100):  # top eigenvector by power iteration: d x d eigh is slow and only one is needed
        v = M @ v
        v /= np.linalg.norm(v) or 1.0
    r = np.corrcoef(X @ v, y)[0, 1]
    return (v if r >= 0 else -v), float(abs(r))


def fit(concept: str, pos: list[str], neg: list[str], name: str = MODEL) -> dict[str, Any]:
    """Learn the concept from texts that show it (pos) and texts that do not (neg); saved under data/steer/<concept>.npz.
    The per-layer mean state norm is kept too, so eps is a fraction of a layer's own scale."""
    S = states(pos + neg, name)
    y = np.array([1] * len(pos) + [0] * len(neg))
    vs, rs = zip(*(rfm(S[i], y) for i in range(1, S.shape[0])))  # layer 0 sits on the embeddings: the paper starts at block 2
    V = np.vstack([np.zeros(S.shape[2]), *vs])
    norms = np.linalg.norm(S, axis=2).mean(1)
    path = _dir() / f"{concept}.npz"
    np.savez(path, v=V, corr=np.array([0.0, *rs]), norm=norms)
    return {"concept": concept, "path": str(path), "corr": [round(r, 3) for r in rs]}


def _dir() -> Path:
    p = Path(db.DB_PATH).parent / "steer"
    p.mkdir(parents=True, exist_ok=True)
    return p


def vectors(concept: str) -> dict[str, np.ndarray]:
    z = np.load(_dir() / f"{concept}.npz")
    return {k: z[k] for k in z.files}


def generate(text: str | list[dict[str, str]], steer: dict[str, float] | None = None, max_tokens: int = 120, temp: float = 0.0, name: str = MODEL) -> str:
    """A reply (to a text, or to chat messages) with each concept in steer added at every layer, eps times that layer's mean state norm
    (negative: away from it). On Qwen3.5-4B: 0.01-0.02 shifts the tone, 0.04 writes in the concept, 0.1 and up breaks into repeated tokens
    (it adds at all 31 layers)."""
    import mlx.core as mx
    from mlx_lm import generate as gen
    from mlx_lm.sample_utils import make_sampler

    m = _load(name)
    add: dict[int, Any] = {}
    for concept, eps in (steer or {}).items():
        z = vectors(concept)
        for i in range(1, m["n"]):
            add[i] = add.get(i, 0) + mx.array((eps * z["norm"][i] * z["v"][i]).astype(np.float32))
    with _gen_lock:
        m["add"] = add
        try:
            return gen(m["model"], m["tok"], _prompt(m["tok"], text), max_tokens=max_tokens, sampler=make_sampler(temp=temp))
        finally:
            m["add"] = {}


ON: dict[str, float] = {}  # what the character's own steps are steered by right now; the harness sets it around its executor, so the planner and judge never are
_gen_lock = threading.Lock()  # one generation at a time: the taps read one shared vector set
GENERIC = """What should I eat for breakfast?|How do I fix a leaky tap?|Tell me about the weather today.|What is a good way to learn a language?|Describe your favourite place.|How do birds migrate?|What makes a good friend?|Explain how a car engine works.|What did you do last weekend?|How do I start running?|Why is the sky blue?|What is the best way to save money?|Tell me a short story.|How are mountains formed?|What do you think about music?|How do I make coffee?|What is your job like?|Describe the night sky.|What is the history of your town?|How do I grow tomatoes?|What scares you the most?|Who is your hero?|What would you do with a free day?|How does electricity work?|What is the meaning of home?|Describe a battle you remember.|How do you stay safe when travelling?|What tools do you carry?|What is the oldest thing you know of?|How do you deal with loss?|What is a moon made of?|Tell me about your neighbours.|What happens when we die?|What is the strongest material?|How do you pick a leader?|What languages do you speak?|What is the biggest threat to people?|How do you heal an injury?|What do you do at night?|Who built the ancient ruins?""".split("|")


OTHER_WORLDS = (
    "You live in Middle-earth, among hobbits and elves. Answer as someone from there. ",
    "You live in the Star Wars galaxy, among Jedi and droids. Answer as someone from there. ",
    "You live at Hogwarts, among wizards and owls. Answer as someone from there. ",
    "You live in a medieval fantasy tavern town, among knights and bards. Answer as someone from there. ",
)
MIN_FACTS = 12  # fewer kept facts, or fewer negatives, and a fitted direction would only be noise
TRUTH_EPS = 0.02  # the fixed push for the truth concept, beside the world's (up to 0.03): together under 0.06, where the model breaks


def world_concept() -> str:
    """The concept of the character's own world, fitted the first time it is asked for and again whenever what is known of the world changes:
    generic questions asked inside its world (named from its sheet and the names its world is made of) against the same questions asked
    inside other fictional worlds, so the direction means this world and not "being in a story".
    Empty when too little is known of its world to name it."""
    from . import char, chibi

    p, words = char.get_profile(), sorted(char.world_words())
    if not words:
        return ""
    work = chibi.where_from(p["persona"])
    pre = f"You live in the world of {work or p['name']}, among {', '.join(words[:10])}. Answer as someone from there. "
    concept = "world-" + hashlib.sha1(("v2|" + pre).encode()).hexdigest()[:10]  # v2: the contrast changed, so old vectors are not reused
    if not (_dir() / f"{concept}.npz").exists():
        fit(concept, [pre + q for q in GENERIC], [OTHER_WORLDS[i % len(OTHER_WORLDS)] + q for i, q in enumerate(GENERIC)])
    return concept


def facts() -> tuple[list[str], list[str]]:
    """The claim sentences the pruner kept and dropped for the live persona, oldest first, each once."""
    from . import char

    con = db.connect()
    rows = con.execute("SELECT title, content FROM char_memories WHERE source = 'sheet' AND title LIKE 'Claims: %' AND id > ? ORDER BY id", (char._start(),)).fetchall()
    live = {r["id"] for r in con.execute("SELECT id FROM char_memories WHERE source = 'reflection' AND id > ?", (char._start(),))}  # a rejected note is a sheet row now
    dead = {r["title"].removeprefix("Checked: ") for r in con.execute("SELECT title FROM char_memories WHERE title LIKE 'Checked: %' AND content = 'drop' AND id > ?", (char._start(),))}
    con.close()
    kept, dropped = [], []
    for r in rows:
        c, i = json.loads(r["content"]), r["title"].removeprefix("Claims: ")
        good = int(i) in live and i not in dead  # claims of a note that was turned away are not facts
        kept += c["kept"] if good else []
        dropped += c["dropped"] + ([] if good else c["kept"])
    return list(dict.fromkeys(kept)), list(dict.fromkeys(dropped))


def truth_concept() -> str:
    """The "true about its world" concept: kept facts against dropped claims and against copies of the kept facts with one world name
    swapped for another, so it tells a fact from a wrong one, not a world from another. Empty until there are MIN_FACTS of each.
    The name hashes its texts, so new facts give a new name, and that is the refit."""
    from . import char

    kept, dropped = facts()
    words = sorted(char.world_words())
    bad = []
    for f in kept:
        m = next((m for m in re.finditer(r"[A-Z][\w'-]*", f) if m.group() in words), None)  # capitalised only: "of" and "the" are never swapped
        if m:  # a fact naming nothing of its world has nothing to swap
            bad.append(f[:m.start()] + words[(words.index(m.group()) + 1) % len(words)] + f[m.end():])
    pos, neg = [f"Note: {s}" for s in kept], [f"Note: {s}" for s in dropped + bad]
    if len(pos) < MIN_FACTS or len(neg) < MIN_FACTS:
        return ""
    concept = "truth-" + hashlib.sha1(json.dumps([sorted(pos), sorted(neg)]).encode()).hexdigest()[:10]
    if not (_dir() / f"{concept}.npz").exists():
        fit(concept, pos, neg)
    return concept


LEVELS = (0.0, 0.01, 0.02, 0.03)  # eps the controller chooses between: off, a hint, a shifted tone, writing in its world; 0.04 invents facts, 0.06 breaks


def available() -> bool:
    import importlib.util
    return importlib.util.find_spec("mlx_lm") is not None


def score(texts: list[str], concept: str, name: str = MODEL) -> list[float]:
    """How much of the concept each text carries: its projection on the concept, summed over layers weighted by how well each layer fit.
    shortcut: a fixed weighted sum, not the paper's trained predictor over all layers; train one once there are labels to train it on."""
    z = vectors(concept)
    S = states(texts, name)
    w = z["corr"] / (z["corr"].sum() or 1.0)
    return [float(sum(w[i] * (S[i, j] @ z["v"][i]) / (z["norm"][i] or 1.0) for i in range(S.shape[0]))) for j in range(S.shape[1])]
