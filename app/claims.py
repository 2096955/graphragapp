"""Claims graph: who said what, where and when, with typed decisions guarding every write.

For each extracted claim, in date order:
1. **Mechanical check.** The quote must appear word for word in the document. If it does not,
   the claim is rejected before any model sees it: an extractor that invents a quote never
   reaches the graph.
2. **supports** (yes/no): does the quote support the claim as stated? No: rejected. Unsure: review.
3. **same_claim** (yes/no), for each earlier claim on the same topic and aspect from another
   document, proposed by the graph. Yes: a SAME_AS edge. Unsure: review.
4. **shift** (choice), against the same person's previous claim on the same aspect: same,
   stronger, weaker or opposite. A confident answer becomes a SHIFT edge. Unsure: review.

Nothing uncertain is written. It waits in the review queue until a person accepts or rejects it.
With the catalogue rules (no keys) every answer is "certain", which is the rules' weakness: they
are never unsure, so nothing reaches a person, and their mistakes go straight into the graph.
"""
from __future__ import annotations

import re
from typing import Any

from .claims_corpus import DOC, DOCUMENTS, EXTRACTED, PEOPLE, PUBLISHERS, TOPICS
from .claims_graph import ClaimsGraph
from .claims_labels import SAME_YES, SHIFT, SUPPORTS
from .decisions.base import Backend

SUPPORTS_Q = {
    "type": "noul",
    "instructions": ("Does the quoted text support the claim exactly as stated? Answer no if the claim overstates, "
                     "weakens, changes or goes beyond what the quote says."),
}
SAME_Q = {
    "type": "noul",
    "instructions": ("Do these two statements make the same claim, even if they are worded differently? A statement "
                     "that goes further, or less far, than the other is not the same claim."),
}
SHIFT_Q = {
    "type": "choice",
    "instructions": "The same person made both statements, the second one later. How did their position change?",
    "criteria": {
        "same": "The later statement keeps the same position.",
        "stronger": "The later statement goes further in the same direction, for example from encouraging something "
                    "to requiring it.",
        "weaker": "The later statement relaxes the earlier position.",
        "opposite": "The later statement takes the opposite position.",
    },
}
QUESTIONS = {"supports": SUPPORTS_Q, "same_claim": SAME_Q, "shift": SHIFT_Q}


# ---------------------------------------------------------------------------- claims and pairs
def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def quote_in_document(quote: str, doc_id: str) -> bool:
    return bool(quote) and _norm(quote) in _norm(DOC[doc_id]["text"])


def claim_records(extracted=None) -> list[dict[str, Any]]:
    """Extracted claims with their speaker and date, oldest document first."""
    out = []
    for cid, doc, topic, aspect, statement, quote in (extracted or EXTRACTED):
        d = DOC[doc]
        out.append({"id": cid, "document": doc, "topic": topic, "aspect": aspect, "statement": statement,
                    "quote": quote, "person": d["person"], "publisher": d["publisher"], "date": d["date"],
                    "title": d["title"]})
    return sorted(out, key=lambda c: (c["date"], c["id"]))


def gold_claims() -> list[dict[str, Any]]:
    return [c for c in claim_records() if SUPPORTS.get(c["id"]) == "yes"]


def candidate_pairs(claims: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """(earlier, later) pairs on the same topic and aspect from different documents."""
    pairs = []
    for i, a in enumerate(claims):
        for b in claims[i + 1:]:
            if (a["topic"], a["aspect"]) == (b["topic"], b["aspect"]) and a["document"] != b["document"]:
                pairs.append((a["id"], b["id"]))
    return pairs


def shift_pairs(claims: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """(earlier, later) consecutive claims by the same person on the same aspect."""
    last: dict[tuple[str, str], dict] = {}
    pairs = []
    for c in claims:
        key = (c["person"], c["aspect"])
        prev = last.get(key)
        if prev is not None and prev["document"] != c["document"]:
            pairs.append((prev["id"], c["id"]))
        last[key] = c
    return pairs


def states(kind: str, a: dict[str, Any], b: dict[str, Any] | None = None) -> dict[str, Any]:
    """What the decision model sees for each question."""
    if kind == "supports":
        return {"kind": "extracted_claim", "claim": a["statement"], "quote": a["quote"]}
    if kind == "same_claim":
        return {"kind": "statement_pair", "statement A": a["statement"], "statement B": b["statement"]}
    return {"kind": "position_change", "earlier": f"{a['date']}: {a['statement']}",
            "later": f"{b['date']}: {b['statement']}"}


# ---------------------------------------------------------------------------- catalogue rules
STOP = set("""a an and are as at be been being but by can do does for from had has have he her his i if in into is it
its of on or our so than that the their them then there these they this those to under until was we were what when
where which while who will with would you your any all each every there here also still now""".split())
# How strongly a statement commits, from permissive to mandatory: the ordinary English words of
# obligation and permission. Negation: the usual negation cues. No word here was chosen from this
# corpus. An earlier version also counted words that appear in it ("enforcement", "deserve",
# "support", "oppose", "unnecessary", "stop") and scored three more of the 70 decisions right,
# which is what rules written with the test text in view do.
LEVELS = [
    (3, r"\bmust\b|\bshall\b|\brequired?\b|\brequires\b|\brequirements?\b|\bmandatory\b|\bobliged\b|\bobligations?\b"),
    (2, r"\bshould\b|\bought\b|\bexpect(ed|s)?\b|\brecommend(ed|s)?\b"),
    (1, r"\bmay\b|\bcan\b|\bcould\b|\bencourage(d|s)?\b"),
]
NEGATIVE = r"\bnot\b|\bno\b|\bnever\b|\bnone\b|\bwithout\b|\bcannot\b|n't\b"


def _words(text: str) -> set[str]:
    out = set()
    for w in re.findall(r"[a-z][a-z'-]+", text.lower()):
        w = w.strip("'-")
        if w in STOP or len(w) < 3:
            continue
        for suffix in ("ing", "ers", "ed", "es", "s"):
            if w.endswith(suffix) and len(w) - len(suffix) >= 4:
                w = w[: -len(suffix)]
                break
        out.add(w)
    return out


def strength(text: str) -> int:
    t = text.lower()
    for level, pattern in LEVELS:
        if re.search(pattern, t):
            return level
    return 0


def negative(text: str) -> bool:
    return bool(re.search(NEGATIVE, text.lower()))


def rule_answer(kind: str, state: dict[str, Any]) -> str:
    """Exact rules: word overlap plus how strongly each statement commits. No weights."""
    if kind == "supports":
        claim, quote = _words(state["claim"]), _words(state["quote"])
        overlap = len(claim & quote) / max(1, len(claim))
        same_force = strength(state["claim"]) == strength(state["quote"])
        return "yes" if overlap >= 0.5 and same_force and negative(state["claim"]) == negative(state["quote"]) else "no"
    if kind == "same_claim":
        a, b = state["statement A"], state["statement B"]
        wa, wb = _words(a), _words(b)
        jaccard = len(wa & wb) / max(1, len(wa | wb))
        return "yes" if jaccard >= 0.5 and strength(a) == strength(b) and negative(a) == negative(b) else "no"
    earlier, later = state["earlier"].split(": ", 1)[1], state["later"].split(": ", 1)[1]
    if negative(earlier) != negative(later):
        return "opposite"
    diff = strength(later) - strength(earlier)
    if negative(earlier):
        diff = -diff
    return "stronger" if diff > 0 else "weaker" if diff < 0 else "same"


class LabelsBackend(Backend):
    """Answers from the hand-written labels. Builds the graph as it would be if every decision
    were right: the upper bound for the retrieval comparison, not a model."""

    name = "labels"
    label = "Hand-written labels"

    def __init__(self):
        super().__init__("hand-written labels")

    def _decide(self, state, questions):  # pragma: no cover - answered in ask(), which knows the claim ids
        raise NotImplementedError


def label_answer(kind: str, ids: list[str]) -> str:
    if kind == "supports":
        return SUPPORTS[ids[0]]
    if kind == "same_claim":
        return "yes" if frozenset(ids) in SAME_YES else "no"
    return SHIFT[(ids[0], ids[1])]


def ask(backend: Backend, kind: str, state: dict[str, Any], ids: list[str] | None = None) -> dict[str, Any]:
    """One typed decision. Returns the answer, its confidence and the probabilities."""
    q = QUESTIONS[kind]
    options = ["yes", "no"] if q["type"] == "noul" else list(q["criteria"])
    if backend.name in ("catalogue", "labels"):
        top = rule_answer(kind, state) if backend.name == "catalogue" else label_answer(kind, ids or [])
        probs = {o: float(o == top) for o in options}
        return {"answer": top, "confidence": 1.0, "probabilities": probs, "latency_ms": 0.0,
                "by": "catalogue rules" if backend.name == "catalogue" else "labels"}
    result = backend.decide(state, {kind: q})
    a = result.answers[kind]
    return {"answer": a.top, "confidence": a.confidence, "probabilities": a.probabilities,
            "latency_ms": result.latency_ms, "by": result.model}


# ---------------------------------------------------------------------------- building the graph
class ClaimsLab:
    """Builds the claims graph with one backend and keeps the review queue.

    A person's answer to a review item is kept, and the graph is rebuilt with it, so whatever the
    answer unlocks is asked too: an accepted claim gets its own same-claim and position-change
    questions, and later claims see it as a candidate. The backend's answers from the build are
    reused, so a rebuild asks it only the new questions.
    """

    def __init__(self, store: ClaimsGraph | None = None):
        self.store = store or ClaimsGraph()
        self.review: list[dict[str, Any]] = []
        self.last: dict[str, Any] | None = None
        self.person: dict[tuple[str, tuple[str, ...]], str | None] = {}   # None: no change written
        self._answers: dict[tuple[str, tuple[str, ...]], dict[str, Any]] = {}
        self._setup: tuple | None = None

    def build(self, backend: Backend, threshold: float = 0.8, extracted=None) -> dict[str, Any]:
        """A fresh build with one backend. Forgets earlier answers, a person's included."""
        self.person, self._answers = {}, {}
        return self._build(backend, threshold, extracted)

    def _build(self, backend: Backend, threshold: float, extracted) -> dict[str, Any]:
        self._setup = (backend, threshold, extracted)
        s = self.store
        s.reset()
        self.review = []
        for pid, p in PUBLISHERS.items():
            s.add_publisher(pid, p["name"], p["kind"])
        for pid, p in PEOPLE.items():
            s.add_person(pid, p["name"], p["role"], p["publisher"])
        for tid, t in TOPICS.items():
            s.add_topic(tid, t["label"])
        for d in DOCUMENTS:
            s.add_document(d["id"], d["title"], d["date"], d["kind"], d["publisher"])
        decisions, rejected = [], []
        for c in claim_records(extracted):
            if not quote_in_document(c["quote"], c["document"]):
                rejected.append({"claim": c["id"], "why": "the quote is not in the document"})
                decisions.append({"kind": "quote_check", "claims": [c["id"]], "answer": "not found", "action": "rejected"})
                continue
            d = self._decide(backend, "supports", c, None, threshold)
            decisions.append(d)
            if d["action"] == "review":
                continue
            if d["answer"] == "no":
                rejected.append({"claim": c["id"], "why": "the quote does not support the claim as stated" +
                                 (", decided by a person" if d["by"] == "person" else "")})
                continue
            self._write_claim(c)
            # Candidates come from the graph: earlier claims on the same topic and aspect, other documents.
            for other in s.claims(topic=c["topic"], aspect=c["aspect"]):
                if other["id"] == c["id"] or other["document"] == c["document"]:
                    continue
                d = self._decide(backend, "same_claim", other, c, threshold)
                decisions.append(d)
                if d["action"] == "written" and d["answer"] == "yes":
                    s.add_same(c["id"], other["id"], d["confidence"], d["by"])
            earlier = [o for o in s.claims(person=c["person"], aspect=c["aspect"])
                       if o["date"] < c["date"] and o["document"] != c["document"]]
            if earlier:
                prev = earlier[-1]
                d = self._decide(backend, "shift", prev, c, threshold)
                decisions.append(d)
                if d["action"] == "written":
                    s.add_shift(c["id"], prev["id"], d["answer"], d["confidence"], d["by"])
        self.last = {"backend": backend.name, "model": backend.model, "threshold": threshold, "engine": s.detail,
                     "decisions": decisions, "rejected": rejected, "review": list(self.review), "counts": s.counts(),
                     "decided_by_a_person": len(self.person)}
        return self.last

    def _write_claim(self, c: dict[str, Any]) -> None:
        self.store.add_claim(c["id"], c["statement"], c["quote"], c["date"], c["aspect"], c["topic"],
                             c["person"], c["document"])

    def _decide(self, backend: Backend, kind: str, a: dict, b: dict | None, threshold: float) -> dict[str, Any]:
        state = states(kind, a, b)
        ids = [a["id"]] if b is None else [a["id"], b["id"]]
        key = (kind, tuple(ids))
        if key in self.person:
            answer = self.person[key]
            return {"kind": kind, "claims": ids, "state": state, "answer": answer, "confidence": 1.0,
                    "probabilities": {}, "latency_ms": 0.0, "by": "person",
                    "action": "written" if answer is not None else "dropped"}
        out = self._answers.get(key)
        if out is None:
            try:
                out = ask(backend, kind, state, ids)
                self._answers[key] = out          # reused by a rebuild; a failed decision is asked again
            except Exception as exc:  # noqa: BLE001 - a failed decision is never written
                out = {"answer": None, "confidence": 0.0, "probabilities": {}, "latency_ms": 0.0,
                       "by": backend.name, "error": type(exc).__name__}
        action = "written" if out["confidence"] >= threshold else "review"
        record = {"kind": kind, "claims": ids, "state": state, **out, "action": action}
        if action == "review":
            self.review.append({"id": f"{kind}:{':'.join(ids)}", **record})
        return record

    def resolve(self, item_id: str, accept: bool, label: str | None = None) -> dict[str, Any]:
        """A person's answer to a review item. The answer is kept and the graph rebuilt with it.

        Quote support: accept writes the claim, reject rejects it. Same claim: accept links the two
        claims, reject records that they differ. Position change: accept writes `label`, or the
        model's answer when there is no label; reject writes no change.
        """
        item = next((r for r in self.review if r["id"] == item_id), None)
        if item is None:
            raise KeyError(item_id)
        if item["kind"] == "shift":
            chosen = label or item["answer"]
            if accept and chosen not in SHIFT_Q["criteria"]:
                raise ValueError("label must be one of " + ", ".join(SHIFT_Q["criteria"]))
            answer = chosen if accept else None
        else:
            answer = "yes" if accept else "no"
        if self._setup is None:
            raise RuntimeError("Build the graph before resolving review items.")
        self.person[(item["kind"], tuple(item["claims"]))] = answer
        self._build(*self._setup)
        return {"resolved": item_id, "accepted": accept, "review": len(self.review), "counts": self.store.counts()}

    # ------------------------------------------------------------------------ questions
    def who(self, topic: str | None = None, aspect: str | None = None, publisher_kind: str | None = None) -> list[dict]:
        """Everyone with a claim on the topic, with their claims and sources."""
        people: dict[str, dict] = {}
        for c in self.store.claims(topic=topic, aspect=aspect, publisher_kind=publisher_kind):
            p = people.setdefault(c["person"], {"person": c["person"], "name": c["person_name"],
                                                "publisher": c["publisher_name"], "kind": c["publisher_kind"],
                                                "claims": []})
            p["claims"].append(_cite(c))
        return sorted(people.values(), key=lambda p: p["claims"][0]["date"])

    def timeline(self, person: str, aspect: str, not_after: str | None = None) -> dict[str, Any]:
        """One person's claims on one aspect, oldest first, with how each changed the position."""
        claims = self.store.claims(person=person, aspect=aspect, not_after=not_after)
        shifts = {s["later"]: s for s in self.store.shifts()}
        steps = []
        for c in claims:
            s = shifts.get(c["id"])
            steps.append({**_cite(c), "change": s["label"] if s else None,
                          "from": s["earlier"] if s else None, "confidence": s["confidence"] if s else None})
        as_of = not_after or (claims[-1]["date"] if claims else None)
        return {"person": person, "aspect": aspect, "as_of": as_of, "steps": steps}

    def same_as(self) -> list[dict[str, Any]]:
        return self.store.same_pairs()

    def snapshot(self) -> dict[str, Any]:
        claims = self.store.claims()
        return {"engine": self.store.detail, "counts": self.store.counts(), "claims": [_cite(c) for c in claims],
                "same_as": self.store.same_pairs(), "shifts": self.store.shifts(), "review": self.review}


def _cite(c: dict[str, Any]) -> dict[str, Any]:
    return {"id": c["id"], "statement": c["statement"], "quote": c["quote"], "date": c["date"],
            "aspect": c["aspect"], "topic": c["topic"], "person": c["person"], "person_name": c["person_name"],
            "publisher": c["publisher_name"], "publisher_kind": c["publisher_kind"], "document": c["document"],
            "title": c["title"]}


# ---------------------------------------------------------------------------- labelled check
def check(backend: Backend, threshold: float = 0.8) -> dict[str, Any]:
    """Score a backend on every labelled decision. Nothing is written to the graph."""
    recs = {c["id"]: c for c in claim_records()}
    items = [("supports", recs[cid], None, gold) for cid, gold in SUPPORTS.items()]
    good = gold_claims()
    items += [("same_claim", recs[a], recs[b], "yes" if frozenset({a, b}) in SAME_YES else "no")
              for a, b in candidate_pairs(good)]
    items += [("shift", recs[a], recs[b], SHIFT[(a, b)]) for a, b in shift_pairs(good)]
    rows = []
    for kind, a, b, gold in items:
        try:
            out = ask(backend, kind, states(kind, a, b), [a["id"]] + ([b["id"]] if b else []))
        except Exception as exc:  # noqa: BLE001
            out = {"answer": None, "confidence": 0.0, "error": type(exc).__name__}
        rows.append({"kind": kind, "claims": [a["id"]] + ([b["id"]] if b else []),
                     "answer": out["answer"], "confidence": round(float(out["confidence"]), 4)})
    return {"backend": backend.name, "model": backend.model, **score(rows, threshold)}


def score(rows: list[dict[str, Any]], threshold: float = 0.8) -> dict[str, Any]:
    """Score answers against the current labels. Saved runs are rescored with this, not re-run.

    Every decision ends one of four ways. Below the threshold it goes to a person. At or above it,
    it is right, or it writes something false (an unsupported claim, a false merge or a wrong
    change label), or it leaves out something true (a supported claim rejected, a true merge
    missed). A wrong change label is always written, so it is always false, never left out.
    """
    out_rows = []
    for x in rows:
        gold = label_answer(x["kind"], x["claims"])
        right, decided = x["answer"] == gold, x["confidence"] >= threshold
        wrote_false = decided and not right and (x["kind"] == "shift" or x["answer"] == "yes")
        out_rows.append({**x, "gold": gold, "right": right, "decided": decided,
                         "outcome": ("to review" if not decided else "right" if right
                                     else "wrote something false" if wrote_false else "left out something true")})
    summary = {}
    for kind in QUESTIONS:
        r = [x for x in out_rows if x["kind"] == kind]
        decided = [x for x in r if x["decided"]]
        summary[kind] = {"n": len(r), "right": sum(x["right"] for x in r), "decided": len(decided),
                         "wrong_decided": sum(not x["right"] for x in decided)}
    count = lambda outcome: sum(x["outcome"] == outcome for x in out_rows)  # noqa: E731
    return {"threshold": threshold, "n": len(out_rows), "right": sum(x["right"] for x in out_rows),
            "summary": summary, "decided_right": count("right"), "written_wrongly": count("wrote something false"),
            "left_out_wrongly": count("left out something true"), "to_review": count("to review"),
            "rows": out_rows}


def most_common_baseline() -> dict[str, Any]:
    """Right answers from always giving each question's most common label."""
    kinds: dict[str, list[str]] = {"supports": list(SUPPORTS.values())}
    good = gold_claims()
    kinds["same_claim"] = ["yes" if frozenset(p) in SAME_YES else "no" for p in candidate_pairs(good)]
    kinds["shift"] = [SHIFT[p] for p in shift_pairs(good)]
    out = {}
    for kind, labels in kinds.items():
        top = max(set(labels), key=labels.count)
        out[kind] = {"answer": top, "right": labels.count(top), "n": len(labels)}
    return {"by_kind": out, "right": sum(v["right"] for v in out.values()), "n": sum(v["n"] for v in out.values())}
