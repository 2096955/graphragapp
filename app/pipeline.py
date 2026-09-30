"""Dataset discovery: a request in, ranked and explained dataset solutions out.

Stage       Who decides                      Paper (Diamantini et al. 2026)
gate        decision model (choice)          Table 1's "Not sure" and invalid cases
enrich      graph narrows, model decides     Algorithm 1, lines 1-2 (KG context)
query       model picks levels (choice)      Algorithm 1 (well-defined query, Definition 5)
discover    graph only                       Algorithm 2, lines 2-9; Definition 7
rank        model scores each solution       Algorithm 2, lines 10-11
explain     template, or an LLM if set       Section 4.4

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
from .request import requested_groups, resolve

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

        def ask(name, state, questions):
            res = backend.decide(state, questions)
            totals["calls"] += 1
            totals["decisions"] += len(questions)
            totals["latency_ms"] += res.latency_ms
            totals["cost_usd"] += res.cost_usd
            return res

        out = {"request": request, "preference": preference or "", "backend": backend.name, "backend_label": backend.label,
               "model": backend.model, "residency": backend.residency, "stages": stages}
        parsed = resolve(request)
        out["policy"] = {"min_confidence": self.min_confidence, "validated_risk_guarantee": False,
                         "calibration_loaded": backend.calibration is not None,
                         "time_anchor": parsed["time_anchor"]}

        def uncertain(name, question, answer):
            spec = backend.calibration.spec(name, question) if backend.calibration else None
            if backend.calibration and spec is None:
                return True
            threshold = spec.get("threshold") if spec else self.min_confidence
            return threshold is None or answer.confidence < threshold

        # 1. Gate
        state, qs = t.gate(request)
        r = ask("gate", state, qs)
        gate = r.answers["gate"]
        stages.append({"stage": "gate", "title": "Answer, clarify or reject", "latency_ms": r.latency_ms,
                       "question": qs["gate"], "answer": gate.to_dict()})
        if parsed["gate"] == "reject":
            return self._finish(out, "reject", "The request requires unsupported data, granularity or years outside 2015-2025.", totals, started)
        if parsed["issues"]:
            return self._finish(out, "clarify", " ".join(parsed["issues"]), totals, started)
        if uncertain("gate", qs["gate"], gate):
            return self._finish(out, "review", "Gate confidence is below the acceptance threshold. Review or clarify the request.", totals, started)
        if gate.top != "answer":
            msg = ("The request needs more detail: name a pollutant (or ask for emissions in general) and a breakdown such as "
                   "country and year." if gate.top == "clarify" else
                   "The catalogue does not hold what this request needs.")
            return self._finish(out, gate.top, msg, totals, started)

        # 2. Enrich: the graph proposes candidate nodes, the model decides which are relevant
        cands = {f"group:{g}": meta["describe"] for g, meta in d.GROUPS.items()}
        lex = lexical_candidates(request)
        for pid, _ in lex:
            cands[f"pollutant:{pid}"] = d.POLLUTANT[pid].describe
        state, qs = t.relevance_many(request, cands)
        r = ask("relevance", state, qs)
        explicit_groups = requested_groups(request)
        rel = [{"node": k, "label": (d.GROUPS[k[6:]]["label"] if k.startswith("group:") else d.POLLUTANT[k[10:]].label),
                "kind": k.split(":")[0], "p": r.answers[k].probabilities["yes"],
                "selected": k[6:] in explicit_groups if k.startswith("group:") else r.answers[k].probabilities["yes"] >= RELEVANCE_THRESHOLD,
                "by": "explicit catalogue group" if k.startswith("group:") else "model"} for k in cands]
        groups = [x["node"][6:] for x in rel if x["selected"] and x["kind"] == "group"]
        singles = [x["node"][10:] for x in rel if x["selected"] and x["kind"] == "pollutant"]
        order = [p.id for p in d.POLLUTANTS]
        pollutants = sorted(set(singles) | set(self.graph.expand_groups(groups)), key=order.index)
        stages.append({"stage": "enrich", "title": "Pollutants", "latency_ms": r.latency_ms, "threshold": RELEVANCE_THRESHOLD,
                       "graph_candidates": [p for p, _ in lex], "nodes": rel, "groups_expanded": groups,
                       "pollutants": pollutants})
        if any(uncertain(k, qs[k], r.answers[k]) for k in cands if k.startswith("pollutant:")):
            return self._finish(out, "review", "A pollutant relevance decision is below the acceptance threshold.", totals, started)
        if parsed["pollutants"] and set(pollutants) != set(parsed["pollutants"]):
            return self._finish(out, "review", "Model pollutants conflict with explicit catalogue terms; review the query.", totals, started)

        # 3. Query: one breakdown level per dimension
        state, qs = t.levels(request)
        r = ask("levels", state, qs)
        levels = {dim: a.top for dim, a in r.answers.items() if a.top != "none"}
        filters = parsed["filters"]
        stages.append({"stage": "query", "title": "Breakdown", "latency_ms": r.latency_ms,
                       "answers": {dim: a.to_dict() for dim, a in r.answers.items()},
                       "query": {"pollutants": pollutants, "levels": levels, "filters": filters}})
        out["query"] = {"pollutants": pollutants, "levels": levels, "filters": filters}
        if any(uncertain(dim, qs[dim], a) for dim, a in r.answers.items()):
            return self._finish(out, "review", "A breakdown-level decision is below the acceptance threshold.", totals, started)
        if any(dim not in levels for dim in filters):
            return self._finish(out, "review", "The extracted levels omit a named member constraint.", totals, started)
        if parsed["levels"] and any(levels.get(dim) != lvl for dim, lvl in parsed["levels"].items()):
            return self._finish(out, "review", "Model levels conflict with explicit catalogue terms; review the query.", totals, started)
        if not pollutants or not levels:
            missing = "a pollutant" if not pollutants else "a breakdown"
            return self._finish(out, "clarify", f"The gate said answer, but no {missing} passed the threshold. Ask the user for {missing}.",
                                totals, started)

        # 4. Discover: graph only, no model
        t0 = time.perf_counter()
        sols = self.graph.discover(pollutants, levels, filters=filters)
        stages.append({"stage": "discover", "title": "Discovery", "latency_ms": (time.perf_counter() - t0) * 1000,
                       "solutions": len(sols)})
        if not sols:
            out["subgraph"] = self.graph.subgraph(pollutants, levels, [])
            return self._finish(out, "no_data", "No combination of sources holds these pollutants at these levels.", totals, started)

        # 5. Rank: the model scores each solution against the preference
        ranked = []
        rank_uncertain = False
        for i, sol in enumerate(sols):
            sol["id"] = chr(65 + i)
            sol["summary"] = summarise(sol, pollutants)
            if preference:
                state, qs = t.fit(preference, sol["summary"], sol)
                r = ask("fit", state, qs)
                sol["fit"] = r.answers["fit"].to_dict()
                rank_uncertain |= uncertain("fit", qs["fit"], r.answers["fit"])
            ranked.append(sol)
        if preference:
            ranked.sort(key=lambda s: (-s["fit"]["score"], -s["cells"]))
        else:
            ranked.sort(key=lambda s: -s["cells"])
        ranked = ranked[:MAX_RANKED]
        stages.append({"stage": "rank", "title": "Ranking", "by": "preference fit" if preference else "coverage (no preference given)",
                       "order": [s["id"] for s in ranked]})
        out["solutions"] = ranked
        out["subgraph"] = self.graph.subgraph(pollutants, levels, sorted({s["id"] for sol in ranked for s in sol["sources"]}))
        if rank_uncertain:
            return self._finish(out, "review", "Preference scores are uncertain. Candidate datasets are returned for review, not approved automatically.", totals, started)

        # 6. Explain
        t0 = time.perf_counter()
        out["explanation"] = self.explainer.explain(request, preference, pollutants, levels, ranked, use_llm=use_llm)
        stages.append({"stage": "explain", "title": "Explanation", "latency_ms": (time.perf_counter() - t0) * 1000,
                       "by": out["explanation"]["by"]})
        return self._finish(out, "answer", None, totals, started)

    @staticmethod
    def _finish(out, outcome, message, totals, started):
        out["outcome"] = outcome
        out["message"] = message
        out["totals"] = {**totals, "latency_ms": round(totals["latency_ms"], 1), "wall_ms": round((time.perf_counter() - started) * 1000, 1)}
        return out
