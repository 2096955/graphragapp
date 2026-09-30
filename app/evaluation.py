"""Benchmark runs and their metrics.

Accuracy says how often the top answer is right. Calibration says whether a stated confidence
can be trusted: of the answers given at 0.9, about 90% should be right. The thresholds in the
pipeline only work if the second is true, so both are measured, per task and overall.
"""
from __future__ import annotations

import json
import math
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .decisions import Backend, DecisionError, TransientError
from .testset import TASKS
from .calibration import question_key

EPS = 1e-6


RETRIES = 3            # attempts for a transient failure within one run
BACKOFF_S = 2.0        # doubled after each attempt


def load_checkpoint(path: str | Path | None, backend: Backend, items: list[dict]) -> dict[str, dict]:
    """Decisions already made in an interrupted run, by item id. A line counts only if it came from
    the same model and asked the item's current question; failed decisions are tried again."""
    if not path or not Path(path).exists():
        return {}
    keys = {it["id"]: question_key(it["questions"][it["question"]]) for it in items}
    done = {}
    for line in Path(path).read_text().splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue           # a line cut short by the crash
        if rec.get("model") == backend.model and keys.get(rec.get("id")) == rec.get("question_key") \
                and "error" not in rec:
            done[rec["id"]] = rec
    return done


def run(backend: Backend, items: list[dict], progress: Callable[[int, int], None] | None = None,
        should_stop: Callable[[], bool] | None = None, checkpoint: str | Path | None = None,
        sleep: Callable[[float], None] = time.sleep) -> list[dict]:
    """One decision per item, sequentially, so latency is per decision on this hardware.

    With a checkpoint file, each decision is appended as it is made, and a rerun skips the items
    already decided, so a crash halfway through a paid run costs only the decision in flight.
    Transient failures (timeouts, rate limits, server errors) are retried with backoff; other
    errors are recorded once and tried again on the next run."""
    done = load_checkpoint(checkpoint, backend, items)
    log = open(checkpoint, "a", encoding="utf-8") if checkpoint else None
    records = []
    try:
        for i, it in enumerate(items):
            if should_stop and should_stop():
                break
            if it["id"] in done:
                records.append({k: v for k, v in done[it["id"]].items() if k != "model"})
                if progress:
                    progress(i + 1, len(items))
                continue
            meta = it.get("meta", {})
            rec = {"id": it["id"], "task": it["task"], "gold": it["gold"],
                   "group": meta.get("request") or meta.get("source_id") or it["id"],
                   "question_key": question_key(it["questions"][it["question"]])}
            for attempt in range(RETRIES):
                try:
                    res = backend.decide(it["state"], it["questions"], calibrate=False)
                    ans = res.answers[it["question"]]
                    rec.update(probs={k: round(v, 5) for k, v in ans.probabilities.items()}, top=ans.top,
                               confidence=round(ans.confidence, 5), correct=ans.top == it["gold"],
                               latency_ms=round(res.latency_ms, 1), tokens=res.input_tokens, cost_usd=res.cost_usd)
                    break
                except TransientError as e:
                    if attempt == RETRIES - 1:
                        rec.update(error=str(e)[:300], transient=True)
                    else:
                        sleep(BACKOFF_S * 2 ** attempt)
                except DecisionError as e:
                    rec.update(error=str(e)[:300])
                    break
            records.append(rec)
            if log:
                log.write(json.dumps({**rec, "model": backend.model}) + "\n")
                log.flush()
            if progress:
                progress(i + 1, len(items))
    finally:
        if log:
            log.close()
    return records


# ------------------------------------------------------------------------------------ metrics
def _bins(recs: list[dict], n: int = 10) -> list[dict]:
    out = []
    for b in range(n):
        lo, hi = b / n, (b + 1) / n
        sel = [r for r in recs if (lo < r["confidence"] <= hi) or (b == 0 and r["confidence"] <= hi)]
        if sel:
            out.append({"lo": lo, "hi": hi, "n": len(sel),
                        "confidence": sum(r["confidence"] for r in sel) / len(sel),
                        "accuracy": sum(r["correct"] for r in sel) / len(sel)})
        else:
            out.append({"lo": lo, "hi": hi, "n": 0, "confidence": None, "accuracy": None})
    return out


def ece(recs: list[dict], n: int = 10) -> float:
    """Expected calibration error on the top answer, equal-width bins."""
    if not recs:
        return float("nan")
    return sum(b["n"] * abs(b["accuracy"] - b["confidence"]) for b in _bins(recs, n) if b["n"]) / len(recs)


def brier(recs: list[dict]) -> float:
    """Mean squared error of the whole probability vector against the one-hot gold."""
    if not recs:
        return float("nan")
    return sum(sum((p - (1.0 if k == r["gold"] else 0.0)) ** 2 for k, p in r["probs"].items()) for r in recs) / len(recs)


def nll(recs: list[dict]) -> float:
    if not recs:
        return float("nan")
    return -sum(math.log(max(r["probs"].get(r["gold"], 0.0), EPS)) for r in recs) / len(recs)


def coverage_at_risk(recs: list[dict], risk: float = 0.05) -> dict:
    """Descriptive in-sample threshold search, not a production error guarantee."""
    ordered = sorted((r for r in recs if "error" not in r), key=lambda r: -r["confidence"])
    best, threshold, wrong = 0, None, 0
    for i, r in enumerate(ordered, 1):
        wrong += 0 if r["correct"] else 1
        if wrong / i <= risk and (i == len(ordered) or ordered[i]["confidence"] < r["confidence"]):
            best, threshold = i, r["confidence"]
    accepted = ordered[:best]
    errors = sum(not r["correct"] for r in accepted)
    return {"risk": risk, "coverage": best / len(recs) if recs else 0.0, "threshold": threshold,
            "accepted": best, "errors": errors, "observed_risk": errors / best if best else None,
            "method": "empirical_in_sample", "validated_risk_guarantee": False}


def group_id(record: dict, index: int = 0) -> str:
    if record.get("group"):
        return str(record["group"])
    parts = record.get("id", "").split("-")
    if parts and parts[0] in ("gate", "rel", "lvl", "grp") and len(parts) > 1:
        return parts[1]
    if parts and parts[0] == "map" and len(parts) > 1:
        return parts[1]
    return record.get("id", f"item-{index}")


def group_folds(recs: list[dict], folds: int = 2, seed: int = 0) -> dict[int, int]:
    """Assign whole groups (requests, sources, name pairs) to folds. Different seeds give
    different splits; one split alone can flatter or harm a model, so report several."""
    groups = sorted({group_id(r, i) for i, r in enumerate(recs)})
    random.Random(seed).shuffle(groups)
    assigned = {group: i % folds for i, group in enumerate(groups)}
    return {i: assigned[group_id(r, i)] for i, r in enumerate(recs)}


def evaluate_threshold(recs: list[dict], threshold: float | None, risk: float = 0.05) -> dict:
    accepted = [r for r in recs if "error" not in r and threshold is not None and r["confidence"] >= threshold]
    errors = sum(not r["correct"] for r in accepted)
    return {"target_risk": risk, "threshold": threshold, "total": len(recs), "accepted": len(accepted),
            "errors": errors, "coverage": len(accepted) / len(recs) if recs else 0.0,
            "observed_risk": errors / len(accepted) if accepted else None, "validated_risk_guarantee": False}


def heldout_coverage(recs: list[dict], risk: float = 0.05) -> dict:
    folds = group_folds(recs)
    selection = [r for i, r in enumerate(recs) if folds[i] == 0]
    evaluation = [r for i, r in enumerate(recs) if folds[i] == 1]
    threshold = coverage_at_risk(selection, risk)["threshold"]
    return {**evaluate_threshold(evaluation, threshold, risk), "method": "grouped_holdout",
            "selection_groups": sorted({group_id(r) for r in selection}),
            "evaluation_groups": sorted({group_id(r) for r in evaluation})}


def _temper(probs: dict[str, float], temp: float) -> dict[str, float]:
    logs = {k: math.log(max(v, EPS)) / temp for k, v in probs.items()}
    m = max(logs.values())
    ex = {k: math.exp(v - m) for k, v in logs.items()}
    z = sum(ex.values())
    return {k: v / z for k, v in ex.items()}


def _fit_temperature(recs: list[dict]) -> float:
    grid = [math.exp(x / 20) for x in range(-60, 61)]      # 0.05 to 20
    def loss(tmp):
        return -sum(math.log(max(_temper(r["probs"], tmp).get(r["gold"], 0.0), EPS)) for r in recs)
    return min(grid, key=loss)


def recalibrated(recs: list[dict], folds: int = 2, seed: int = 0) -> tuple[list[dict], list[float]]:
    """Temperature scaling with k-fold cross-fitting: each record is rescaled by a temperature
    fitted on the other folds only. This is what calibrating on your own labels buys."""
    out, temps = [], []
    fold = group_folds(recs, folds, seed)
    for f in range(folds):
        train = [r for i, r in enumerate(recs) if fold[i] != f]
        test = [r for i, r in enumerate(recs) if fold[i] == f]
        if not train or not test:
            continue
        tmp = _fit_temperature(train)
        temps.append(tmp)
        for r in test:
            p = _temper(r["probs"], tmp)
            top = max(p, key=p.get)
            out.append({**r, "probs": p, "top": top, "confidence": p[top], "correct": top == r["gold"]})
    return out, temps


def _pct(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]


def summarise(recs: list[dict]) -> dict:
    from . import stats
    ok = [r for r in recs if "error" not in r]
    lat = [r["latency_ms"] for r in ok]
    cost = sum(r.get("cost_usd") or 0.0 for r in ok)
    cal, temps = recalibrated(ok)
    return {
        "n": len(recs), "errors": len(recs) - len(ok), "groups": stats.n_groups(recs),
        "accuracy": sum(r["correct"] for r in ok) / len(ok) if ok else None,
        "accuracy_ci": stats.bootstrap(recs, stats.accuracy), "majority": stats.majority(recs),
        "ece": ece(ok), "brier": brier(ok), "nll": nll(ok),
        "mean_confidence": sum(r["confidence"] for r in ok) / len(ok) if ok else None,
        "coverage_at_5": coverage_at_risk(recs, 0.05),
        "attempted_accuracy": sum(r.get("correct", False) for r in recs) / len(recs) if recs else None,
        "ece_recalibrated": ece(cal), "temperatures": temps, "coverage_at_5_recalibrated": coverage_at_risk(cal, 0.05),
        "reliability": _bins(ok), "reliability_recalibrated": _bins(cal),
        "latency_ms_p50": _pct(lat, 0.5), "latency_ms_p95": _pct(lat, 0.95),
        "cost_usd": cost, "cost_usd_per_1k": cost / len(ok) * 1000 if ok else None,
    }


def metrics(recs: list[dict]) -> dict:
    """Per task and overall.

    Calibration error: per task, then weighted by task size for the overall figure (`ece`), so
    errors in different tasks cannot cancel. `ece_pooled` pools all decisions first, which is what
    the overall reliability diagram shows. `ece_recalibrated` is after temperature scaling fitted
    on the other half of the requests, averaged over random splits.
    `selective`: coverage and error at several target error rates, thresholds chosen per task,
    in sample and held out over many random splits (see stats.py)."""
    from . import stats
    by_task = {task: [r for r in recs if r["task"] == task] for task in TASKS}
    per_task = {task: summarise(v) for task, v in by_task.items()}
    for task, summary in per_task.items():
        summary["ece_recalibrated"] = stats.scaled_ece(by_task[task]) if by_task[task] else None
    overall = summarise(recs)
    ok = [r for r in recs if "error" not in r]
    overall["majority"] = None            # one most-common answer across different tasks means nothing
    overall["ece_pooled"] = overall["ece"]
    overall["ece"] = stats.weighted_ece(ok)
    sized = [(len([r for r in by_task[t] if "error" not in r]), per_task[t]["ece_recalibrated"]) for t in TASKS]
    sized = [(n, e) for n, e in sized if n and e is not None]
    overall["ece_recalibrated"] = sum(n * e for n, e in sized) / sum(n for n, _ in sized) if sized else None
    selective = stats.selective({task: v for task, v in by_task.items() if v})
    overall["selective"] = selective
    for task, summary in per_task.items():
        summary["selective"] = {risk: s["tasks"][task] for risk, s in selective.items() if task in s["tasks"]}
    # One split of per-task temperature scaling, pooled: what the overall reliability diagram shows.
    pooled = []
    for task in TASKS:
        pooled += recalibrated([r for r in recs if r["task"] == task and "error" not in r])[0]
    overall["ece_pooled_recalibrated"] = ece(pooled)
    overall["reliability_recalibrated"] = _bins(pooled)
    overall["coverage_at_5_recalibrated"] = coverage_at_risk(pooled, 0.05)
    overall["temperatures"] = {task: summary["temperatures"] for task, summary in per_task.items()}
    overall["calibration_method"] = "per_task_temperature_grouped_cross_fit"
    return {"overall": overall, "tasks": per_task}


def save(path: str | Path, backend: Backend, recs: list[dict], hardware: str, seconds: float) -> dict:
    out = {
        "backend": backend.name, "label": backend.label, "model": backend.model, "residency": backend.residency,
        "hardware": hardware, "finished": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seconds": round(seconds, 1), "metrics": metrics(recs), "records": recs,
        "benchmark_scope": "typed decisions, not end-to-end request success",
    }
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(clean(out), indent=1))
    return out


def refresh(data: dict, items: list[dict]) -> dict:
    """Score a saved run against the current labels. A run is current when it covers every
    current item and asked each one exactly the current question; labels may have changed since."""
    by_id = {it["id"]: it for it in items}
    keys = {it["id"]: question_key(it["questions"][it["question"]]) for it in items}
    recs, stale = [], 0
    for i, r in enumerate(data.get("records", [])):
        it = by_id.get(r["id"])
        if it is None:
            continue
        meta = it.get("meta", {})
        r = {**r, "task": it["task"], "gold": it["gold"],
             "group": r.get("group") or meta.get("request") or meta.get("source_id") or it["id"]}
        if "error" not in r:
            r["correct"] = r["top"] == it["gold"]
        stale += r.get("question_key") != keys[it["id"]]
        recs.append(r)
    out = {**data, "records": recs, "stale": stale, "missing": len(items) - len(recs)}
    out["current"] = stale == 0 and out["missing"] == 0
    out["metrics"] = metrics(recs)
    return out


def clean(x):
    """JSON has no NaN: replace it with null, recursively."""
    if isinstance(x, float) and not math.isfinite(x):
        return None
    if isinstance(x, dict):
        return {k: clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    return x


def timed_run(backend: Backend, items: list[dict], **kw) -> tuple[list[dict], float]:
    t = time.perf_counter()
    recs = run(backend, items, **kw)
    return recs, time.perf_counter() - t
