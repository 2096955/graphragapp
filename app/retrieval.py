"""Retrieval over the claims corpus: BM25, dense, hybrid, and the claims graph, on the same questions.

Passages are sentences, each prefixed with its publisher, speaker, date and title, as a careful
RAG system would do, so the text methods can match names and dates too.

- BM25: Okapi BM25 over the passage words. No dependencies.
- Dense: a small open embedding model (sentence-transformers/all-MiniLM-L6-v2, Apache 2.0) with
  cosine similarity. Needs `pip install -r requirements-local.txt`; skipped without it.
- Hybrid: reciprocal rank fusion of BM25 and dense, the usual production default.
- Graph: the question is parsed into a person, publisher, aspect and date with plain rules, then
  answered by a Cypher query over the claims graph. It returns claims, and their passages, in
  date order with who said them. It only knows what extraction put into the graph.

In production, use a vector store for the text methods (Qdrant does dense and sparse, pgvector
keeps vectors next to the rows); here everything fits in memory.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from functools import lru_cache
from typing import Any

from .claims_corpus import DOCUMENTS, PEOPLE, PUBLISHERS, TOPICS
from .claims_labels import QUESTIONS

EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
K = 10
STOP = set("""a an and are as at be been being but by can do does for from had has have how i if in into is it its
of on or our so than that the their them then there these they this those to was we were what when where which who
whom why will with would you your any all each every about has have said anything""".split())


# ---------------------------------------------------------------------------- passages
def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", text) if s.strip()]


@lru_cache(maxsize=1)
def passages() -> tuple[dict[str, Any], ...]:
    out = []
    for d in DOCUMENTS:
        who = PEOPLE[d["person"]]["name"] if d["person"] else PUBLISHERS[d["publisher"]]["name"]
        header = f"{PUBLISHERS[d['publisher']]['name']}; {who}; {d['date']}; {d['title']}."
        for i, s in enumerate(_sentences(d["text"]), 1):
            out.append({"id": f"{d['id']}.{i}", "document": d["id"], "date": d["date"], "text": s,
                        "indexed": f"{header} {s}"})
    return tuple(out)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def claim_passages(quote: str, document: str) -> list[str]:
    """The passages a claim's quote comes from (a quote can span two sentences)."""
    q = _norm(quote)
    return [p["id"] for p in passages() if p["document"] == document
            and (_norm(p["text"]).rstrip(".") in q or any(part and part in _norm(p["text"])
                                                           for part in (x.strip() for x in q.split(". "))))]


# ---------------------------------------------------------------------------- BM25
def _tokens(text: str) -> list[str]:
    out = []
    for w in re.findall(r"[a-z0-9][a-z0-9'-]*", text.lower()):
        w = w.strip("'-")
        if w in STOP or len(w) < 2:
            continue
        for suffix in ("ing", "ers", "ed", "es", "s"):
            if w.endswith(suffix) and len(w) - len(suffix) >= 4:
                w = w[: -len(suffix)]
                break
        out.append(w)
    return out


class BM25:
    def __init__(self, docs: list[str], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.toks = [_tokens(d) for d in docs]
        self.avg = sum(len(t) for t in self.toks) / max(1, len(self.toks))
        df = Counter(w for t in self.toks for w in set(t))
        n = len(self.toks)
        self.idf = {w: math.log(1 + (n - f + 0.5) / (f + 0.5)) for w, f in df.items()}

    def scores(self, query: str) -> list[float]:
        q = _tokens(query)
        out = []
        for t in self.toks:
            tf, s = Counter(t), 0.0
            for w in q:
                if w in tf:
                    s += self.idf[w] * tf[w] * (self.k1 + 1) / (tf[w] + self.k1 * (1 - self.b + self.b * len(t) / self.avg))
            out.append(s)
        return out


@lru_cache(maxsize=1)
def _bm25() -> BM25:
    return BM25([p["indexed"] for p in passages()])


def bm25(query: str, k: int = K) -> list[str]:
    ps, sc = passages(), _bm25().scores(query)
    order = sorted(range(len(ps)), key=lambda i: (-sc[i], i))
    return [ps[i]["id"] for i in order[:k] if sc[i] > 0]


# ---------------------------------------------------------------------------- dense
def dense_available() -> tuple[bool, str]:
    try:
        import sentence_transformers  # noqa: F401
        return True, ""
    except ImportError:
        return False, "Dense retrieval needs sentence-transformers (pip install -r requirements-local.txt)."


@lru_cache(maxsize=1)
def _encoder():
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(EMBED_MODEL, device="cpu")
    vectors = model.encode([p["indexed"] for p in passages()], normalize_embeddings=True)
    return model, vectors


def dense(query: str, k: int = K) -> list[str]:
    model, vectors = _encoder()
    q = model.encode([query], normalize_embeddings=True)[0]
    sims = vectors @ q
    order = sorted(range(len(sims)), key=lambda i: (-float(sims[i]), i))
    return [passages()[i]["id"] for i in order[:k]]


def hybrid(query: str, k: int = K, rrf_k: int = 60) -> list[str]:
    """Reciprocal rank fusion of BM25 and dense rankings."""
    score: dict[str, float] = {}
    for ranking in (bm25(query, k=50), dense(query, k=50)):
        for rank, pid in enumerate(ranking, 1):
            score[pid] = score.get(pid, 0.0) + 1.0 / (rrf_k + rank)
    return [pid for pid, _ in sorted(score.items(), key=lambda x: (-x[1], x[0]))[:k]]


# ---------------------------------------------------------------------------- graph
PUBLISHER_WORDS = {"information steward": "ois", "bankers": "csbf", "consumer alliance": "lca", "lantern": "lca",
                   "prudential authority": "mpa", "meridian": "mpa", "markets commission": "csmc"}
ASPECT_WORDS = [("human review", ("automated-declines", "human-review")),
                ("register", ("model-register", "register")), ("inventor", ("model-register", "register")),
                ("accountable", ("vendor-models", "accountability")), ("vendor", ("vendor-models", "accountability")),
                ("told why", ("automated-declines", "explanation")), ("explanation", ("automated-declines", "explanation")),
                ("generative ai", ("genai-customer-data", None))]


def plan(question: str) -> dict[str, Any]:
    """Parse a question with plain rules: person, publisher, aspect, date. A typed decision or an
    LLM would do this in production, and its mistakes would cost the graph recall."""
    q = question.lower()
    out: dict[str, Any] = {"kind": "claims"}
    for pid, p in PEOPLE.items():
        if p["name"].lower() in q or p["name"].split()[-1].lower() in q:
            out["person"] = pid
    for words, pub in PUBLISHER_WORDS.items():
        if words in q:
            out["publisher"] = pub
    if "regulator" in q:
        out["publisher_kind"] = "regulator"
    for words, (topic, aspect) in ASPECT_WORDS:
        if words in q:
            out["topic"], out["aspect"] = topic, aspect
            break
    m = re.search(r"as of (the start of |the end of )?(\d{4})", q)
    if m:
        out["not_after"] = f"{m.group(2)}-01-01" if m.group(1) == "the start of " else f"{m.group(2)}-12-31"
    if re.search(r"\bchanged?\b|\bview\b|\bposition\b", q) and (out.get("person") or out.get("publisher")):
        out["kind"] = "timeline"
    return out


def graph(question: str, lab, k: int = K) -> dict[str, Any]:
    """Claims answering the question, oldest first, and their passages."""
    p = plan(question)
    if not any(p.get(x) for x in ("topic", "aspect", "person", "publisher")):
        return {"plan": p, "claims": [], "passages": []}
    claims = lab.store.claims(topic=p.get("topic"), aspect=p.get("aspect"), person=p.get("person"),
                              publisher=p.get("publisher"), publisher_kind=p.get("publisher_kind"),
                              not_after=p.get("not_after"))
    ids, pids = [], []
    for c in claims:
        ids.append(c["id"])
        for pid in claim_passages(c["quote"], c["document"]):
            if pid not in pids:
                pids.append(pid)
    return {"plan": p, "claims": ids, "passages": pids[:k]}


# ---------------------------------------------------------------------------- comparison
def _gold_passages(q: dict[str, Any], quotes: dict[str, tuple[str, str]]) -> dict[str, list[str]]:
    if "claims" in q:
        return {cid: claim_passages(*quotes[cid]) for cid in q["claims"]}
    return {phrase: [p["id"] for p in passages() if phrase in p["text"]] for phrase in q["passages"]}


def compare(graphs: dict[str, Any], k: int = K, with_dense: bool | None = None) -> dict[str, Any]:
    """Recall at k on every question for BM25, dense, hybrid and each graph given."""
    from .claims import claim_records
    quotes = {c["id"]: (c["quote"], c["document"]) for c in claim_records()}
    dates = {p["id"]: p["date"] for p in passages()}
    use_dense = dense_available()[0] if with_dense is None else with_dense
    methods: dict[str, Any] = {"BM25": lambda q: bm25(q, k)}
    if use_dense:
        methods["Dense"] = lambda q: dense(q, k)
        methods["Hybrid"] = lambda q: hybrid(q, k)
    for name, lab in graphs.items():
        methods[name] = (lambda lab_: (lambda q: graph(q, lab_, k)["passages"]))(lab)
    rows = []
    for q in QUESTIONS:
        gold = _gold_passages(q, quotes)
        row = {"id": q["id"], "kind": q["kind"], "question": q["question"], "methods": {}}
        for name, fn in methods.items():
            got = fn(q["question"])
            found = [g for g, ps in gold.items() if any(p in got for p in ps)]
            entry = {"recall": round(len(found) / len(gold), 3), "found": found, "retrieved": got}
            if q.get("not_after"):
                entry["later_than_as_of"] = sum(1 for p in got if dates[p] > q["not_after"])
            row["methods"][name] = entry
        rows.append(row)
    summary = {name: round(sum(r["methods"][name]["recall"] for r in rows) / len(rows), 3) for name in methods}
    by_kind = {}
    for name in methods:
        for kind in sorted({r["kind"] for r in rows}):
            rs = [r for r in rows if r["kind"] == kind]
            by_kind.setdefault(kind, {})[name] = round(sum(r["methods"][name]["recall"] for r in rs) / len(rs), 3)
    return {"k": k, "embed_model": EMBED_MODEL if use_dense else None, "methods": list(methods), "summary": summary,
            "by_kind": by_kind, "questions": rows}
