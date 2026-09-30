"""Dataset discovery: a request in, ranked and explained dataset solutions out.

Stage       Who decides                      Paper (Diamantini et al. 2026)
checks      catalogue facts (request.py)     validation against the knowledge graph
gate        decision model (choice)          Table 1's "Not sure" and invalid cases
enrich      graph narrows, model decides     Algorithm 1, lines 1-2 (KG context)
query       model picks levels (choice)      Algorithm 1 (well-defined query, Definition 5)
discover    graph only                       Algorithm 2, lines 2-9; Definition 7
rank        model scores each solution       Algorithm 2, lines 10-11
explain     template, or an LLM if set       Section 4.4

Who wins when they disagree:
- Catalogue facts stop a request outright: years or granularity the catalogue does not hold,
  pollutants it does not hold, places it does not know.
- Where the request states something in catalogue terms (a named pollutant or group, "by
  country", "Germany", "2020"), that is used, and a model that disagrees sends the result to review.
- Everything else is the model's decision. Below the acceptance threshold it goes to review.
- Review does not stop the run once the gate says answer: the result is complete but marked
  provisional, so a person checks a proposal instead of starting again. If the gate leans towards
  clarify or reject without enough confidence, the run stops there for a person to decide.
- Words the checks cannot place are listed for review: one of them may name a pollutant, place
  or period the result would otherwise leave out.
- Clarify ends the run even when earlier decisions were uncertain. Nothing under review is
  reported as an answer, and "no data" is reported only when no decision was uncertain.

The decision model never writes text, and the LLM (when used) never makes a decision: it is
given the scores and asked to explain them.
"""
from __future__ import annotations

import re
import time

from . import domain as d
from . import tasks as t
from .decisions import Backend
from .explain import Explainer
from .graph import Graph
from .request import resolve

PIPELINE_VERSION = "1.2.0"
RELEVANCE_THRESHOLD = 0.5
MAX_CANDIDATES = 8
MAX_RANKED = 6


def _norm(s: str) -> str:
    s = s.lower().replace("sulfur", "sulphur")
    s = re.sub(r"pm\s*2[.,]?\s*5", "pm2.5", s)
    s = re.sub(r"pm\s*10", "pm10", s)
    return s


_STOP = {"of", "and", "the", "matter", "oxides", "oxide", "carbon", "organic", "compounds", "particles"}


def lexical_candidates(request: str, limit: int = MAX_CANDIDATES) -> list[tuple[str, float]]:
    """Pollutants whose names or aliases appear in the request. The graph's cheap first cut,
    so the model only has to decide about a handful of nodes rather than all 24."""
    text = _norm(request)
    words = set(re.findall(r"[a-z0-9.]+", text))
    scored = []
    for p in d.POLLUTANTS:
        best = 0.0
        for name in (p.label.lower(), p.id.lower(), *p.aliases):
            n = _norm(name)
            if re.search(r"(?<![a-z0-9])" + re.escape(n) + r"(?![a-z0-9])", text):
                best = 1.0
                break
            toks = [w for w in re.findall(r"[a-z0-9.]+", n) if w not in _STOP]
            if len(toks) > 1 or (toks and len(toks[0]) > 3):
                share = sum(w in words for w in toks) / len(toks) if toks else 0
                best = max(best, 0.5 * share if share >= 0.5 else 0.0)
        if best > 0:
            scored.append((p.id, best))
    scored.sort(key=lambda x: -x[1])
    return scored[:limit]


def _range(vals: list[str]) -> str:
    return vals[0] if len(vals) == 1 else f"{vals[0]} to {vals[-1]}"


def summarise(sol: dict, pollutants: list[str]) -> str:
    """Plain-text profile of one solution: what the ranking question sees."""
    parts = ["Sources: " + "; ".join(f"{s['name']} ({s['publisher']}, updated {s['updated']})" for s in sol["sources"]) + "."]
    for key, prof in sol["profiles"].items():
        dim, lvl = key.split(".")
        mems = list(prof)
        if not mems:
            parts.append(f"No {lvl} is covered by every source.")
        elif dim == "TIME":
            parts.append(f"{lvl.capitalize()}s: {_range(mems)} ({len(mems)} covered).")
        else:
            shown = ", ".join(mems[:8]) + (f" and {len(mems) - 8} more" if len(mems) > 8 else "")
            parts.append(f"{d.plural(lvl, len(mems))}: {shown}.")
    parts.append("Pollutants: " + ", ".join(d.POLLUTANT[p].label for p in pollutants[:8])
                 + (f" and {len(pollutants) - 8} more" if len(pollutants) > 8 else "") + ".")
    parts += [n + "." for n in sol["notes"]]
    return " ".join(parts)


DIM_LABEL = {"GEO": "Geography", "TIME": "Time", "SECTOR": "Sector"}


def _names(ids: list[str]) -> str:
    labels = [d.POLLUTANT[p].label for p in ids]
    return ", ".join(labels[:5]) + (f" and {len(labels) - 5} more" if len(labels) > 5 else "")


class Pipeline:
    def __init__(self, graph: Graph, explainer: Explainer | None = None, min_confidence: float = 0.8):
        if not 0 <= min_confidence <= 1:
            raise ValueError("MIN_CONFIDENCE must be in [0, 1].")
        self.graph = graph
        self.explainer = explainer or Explainer()
        self.min_confidence = min_confidence

    def run(self, backend: Backend, request: str, preference: str | None = None, use_llm: bool = False) -> dict:
        started = time.perf_counter()
        stages, totals = [], {"decisions": 0, "calls": 0, "latency_ms": 0.0, "cost_usd": 0.0}
        review: list[str] = []   # why a person must check this before it is used
        notes: list[str] = []    # facts the user should see either way

        def ask(name, state, questions):
            res = backend.decide(state, questions)
            totals["calls"] += 1
            totals["decisions"] += len(questions)
            totals["latency_ms"] += res.latency_ms
            totals["cost_usd"] += res.cost_usd
            return res

        def threshold(name, question):
            # With a calibration file, only thresholds validated for this exact question count.
            if backend.calibration:
                spec = backend.calibration.spec(name, question)
                return spec.get("threshold") if spec else None
            return self.min_confidence

        def unsure(name, question, answer):
            limit = threshold(name, question)
            return limit is None or answer.confidence < limit

        parsed = resolve(request)
        out = {"request": request, "preference": preference or "", "backend": backend.name, "backend_label": backend.label,
               "model": backend.model, "residency": backend.residency, "stages": stages, "review": review, "notes": notes,
               "policy": {"min_confidence": self.min_confidence, "calibration_loaded": backend.calibration is not None,
                          "validated_risk_guarantee": False, "time_anchor": parsed["time_anchor"]},
               "checks": {k: parsed[k] for k in ("named", "groups", "levels", "filters", "unheld", "unknown",
                                                 "issues", "hard_reject")}}
        if parsed["unheld"]:
            notes.append(f"{' and '.join(parsed['unheld'])} {'is' if len(parsed['unheld']) == 1 else 'are'} "
                         "not held in the catalogue, so the result leaves it out.")
        if parsed["time_anchor"]:
            notes.append(f"Relative periods count back from {parsed['time_anchor']}, the latest year in the catalogue.")

        # 1. Gate, after the catalogue checks
        state, qs = t.gate(request)
        r = ask("gate", state, qs)
        gate = r.answers["gate"]
        stages.append({"stage": "gate", "title": "Answer, clarify or reject", "latency_ms": r.latency_ms,
                       "question": qs["gate"], "answer": gate.to_dict()})
        if parsed["hard_reject"]:
            return self._finish(out, "reject", parsed["hard_reject"], totals, started)
        if gate.top == "reject" and not unsure("gate", qs["gate"], gate):
            # Asking the user to fix a request that is out of scope anyway helps no one.
            return self._finish(out, "reject", "The catalogue does not hold what this request needs.", totals, started)
        if parsed["issues"]:
            return self._finish(out, "clarify", " ".join(parsed["issues"]), totals, started)
        if gate.top != "answer":
            if unsure("gate", qs["gate"], gate):
                review.append(f"The model leans towards {gate.top} at {gate.confidence:.2f}, below the acceptance threshold.")
                return self._finish(out, "review", "A person should decide whether to answer, clarify or reject this request.",
                                    totals, started)
            msg = ("The request needs more detail: name a pollutant (or ask for emissions in general) and a breakdown such as "
                   "country and year." if gate.top == "clarify" else
                   "The catalogue does not hold what this request needs.")
            return self._finish(out, gate.top, msg, totals, started)
        if unsure("gate", qs["gate"], gate):
            review.append(f"Gate: answer at {gate.confidence:.2f}, below the acceptance threshold.")
        if parsed["unknown"]:
            review.append(f"Words the catalogue checks could not place: {', '.join(parsed['unknown'])}. "
                          "If one names a pollutant, place or period, the result leaves it out.")

        # 2. Enrich: the graph proposes candidate nodes, the model decides which are relevant
        cands = {f"group:{g}": meta["describe"] for g, meta in d.GROUPS.items()}
        lex = lexical_candidates(request)
        for pid, _ in lex:
            cands[f"pollutant:{pid}"] = d.POLLUTANT[pid].describe
        state, qs = t.relevance_many(request, cands)
        r = ask("relevance", state, qs)
        p_yes = {k: r.answers[k].probabilities["yes"] for k in cands}
        model_groups = [k[6:] for k in cands if k.startswith("group:") and p_yes[k] >= RELEVANCE_THRESHOLD]
        model_singles = [k[10:] for k in cands if k.startswith("pollutant:") and p_yes[k] >= RELEVANCE_THRESHOLD]
        order = [p.id for p in d.POLLUTANTS]
        model_set = sorted(set(model_singles) | set(self.graph.expand_groups(model_groups)), key=order.index)
        explicit = parsed["pollutants"]
        if explicit:
            pollutants, groups, by = explicit, parsed["groups"], "request"
            missing = [p for p in explicit if p not in model_set]
            extra = [p for p in model_set if p not in explicit]
            if missing or extra:
                said = " and ".join(x for x in (f"left out {_names(missing)}" if missing else "",
                                                f"added {_names(extra)}" if extra else "") if x)
                review.append(f"Pollutants: the model {said}. The pollutants named in the request are used.")
        else:
            pollutants, groups, by = model_set, model_groups, "model"
            low = [k for k in cands if unsure(k, qs[k], r.answers[k])]
            if low:
                review.append(f"Pollutants: {len(low)} of {len(cands)} relevance decisions are below the acceptance threshold.")
        rel = [{"node": k, "label": (d.GROUPS[k[6:]]["label"] if k.startswith("group:") else d.POLLUTANT[k[10:]].label),
                "kind": k.split(":")[0], "p": p_yes[k], "model": p_yes[k] >= RELEVANCE_THRESHOLD,
                "selected": (k[6:] in groups) if k.startswith("group:") else (k[10:] in pollutants)} for k in cands]
        stages.append({"stage": "enrich", "title": "Pollutants", "latency_ms": r.latency_ms, "threshold": RELEVANCE_THRESHOLD,
                       "graph_candidates": [p for p, _ in lex], "nodes": rel, "groups_expanded": groups,
                       "pollutants": pollutants, "by": by})

        # 3. Query: one breakdown level per dimension
        state, qs = t.levels(request)
        r = ask("levels", state, qs)
        levels, level_by = {}, {}
        for dim, a in r.answers.items():
            stated = parsed["levels"].get(dim)
            if stated:
                levels[dim], level_by[dim] = stated, "request"
                if a.top != stated:
                    review.append(f"{DIM_LABEL[dim]}: the model chose {a.top}, the request says {stated}. The request is used.")
                continue
            level_by[dim] = "model"
            if a.top != "none":
                levels[dim] = a.top
            if unsure(dim, qs[dim], a):
                review.append(f"{DIM_LABEL[dim]}: {a.top} at {a.confidence:.2f}, below the acceptance threshold.")
        filters = parsed["filters"]
        query = {"pollutants": pollutants, "levels": levels, "filters": filters}
        stages.append({"stage": "query", "title": "Breakdown", "latency_ms": r.latency_ms,
                       "answers": {dim: a.to_dict() for dim, a in r.answers.items()}, "by": level_by, "query": query})
        out["query"] = query
        if not pollutants or not levels:
            missing = "a pollutant" if not pollutants else "a breakdown"
            return self._finish(out, "clarify", f"No {missing} could be established. Ask the user for {missing}.", totals, started)

        # 4. Discover: graph only, no model
        t0 = time.perf_counter()
        sols = self.graph.discover(pollutants, levels, filters=filters)
        stages.append({"stage": "discover", "title": "Discovery", "latency_ms": (time.perf_counter() - t0) * 1000,
                       "solutions": len(sols)})
        if not sols:
            out["subgraph"] = self.graph.subgraph(pollutants, levels, [])
            if review:   # "no data" is only as good as the decisions that built the query
                return self._finish(out, "review", "No combination of sources holds this query, but the query rests on "
                                    "the decisions below. Check them before telling the user there is no data.", totals, started)
            return self._finish(out, "no_data", "No combination of sources holds these pollutants at these levels.", totals, started)

        # 5. Rank: the model scores each solution against the preference
        ranked, low_fit = [], 0
        for i, sol in enumerate(sols):
            sol["id"] = chr(65 + i)
            sol["summary"] = summarise(sol, pollutants)
            if preference:
                state, qs = t.fit(preference, sol["summary"], sol)
                r = ask("fit", state, qs)
                sol["fit"] = r.answers["fit"].to_dict()
                low_fit += unsure("fit", qs["fit"], r.answers["fit"])
            ranked.append(sol)
        if preference:
            ranked.sort(key=lambda s: (-s["fit"]["score"], -s["cells"]))
        else:
            ranked.sort(key=lambda s: -s["cells"])
        ranked = ranked[:MAX_RANKED]
        if low_fit:
            review.append(f"Ranking: {low_fit} of {len(sols)} preference scores are below the acceptance threshold.")
        stages.append({"stage": "rank", "title": "Ranking", "by": "preference fit" if preference else "coverage (no preference given)",
                       "order": [s["id"] for s in ranked]})
        out["solutions"] = ranked
        out["subgraph"] = self.graph.subgraph(pollutants, levels, sorted({s["id"] for sol in ranked for s in sol["sources"]}))

        # 6. Explain
        t0 = time.perf_counter()
        out["explanation"] = self.explainer.explain(request, preference, pollutants, levels, ranked, use_llm=use_llm)
        stages.append({"stage": "explain", "title": "Explanation", "latency_ms": (time.perf_counter() - t0) * 1000,
                       "by": out["explanation"]["by"]})
        if review:
            return self._finish(out, "review", "Provisional: a person should check the points below before this is used.",
                                totals, started)
        return self._finish(out, "answer", None, totals, started)

    @staticmethod
    def _finish(out, outcome, message, totals, started):
        out["outcome"] = outcome
        out["message"] = message
        out["totals"] = {**totals, "latency_ms": round(totals["latency_ms"], 1), "wall_ms": round((time.perf_counter() - started) * 1000, 1)}
        return out
