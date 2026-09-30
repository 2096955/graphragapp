"""Uncertainty and selective-prediction statistics for benchmark records.

Decisions are not independent. One request yields a gate decision and several relevance, level
and group decisions; one source yields several column mappings. So:

- confidence intervals resample whole groups (requests, sources, entity pairs), not decisions;
- every held-out figure uses a threshold chosen on one half of the groups and scored on the
  other half, both ways round, so no request informs the threshold that is then scored on it;
- one split can flatter or harm a model, so held-out figures are averaged over many random
  splits and reported with the range across them;
- calibration error is measured within each task and then weighted by task size. Pooling tasks
  first lets over- and under-confidence in different tasks cancel out.

Thresholds are chosen per task, as a deployment would set them per question type, and then
pooled. None of this is a production error guarantee: it is what this labelled set supports.
"""
from __future__ import annotations

import math
import random
from typing import Callable

RISKS = (0.01, 0.02, 0.05, 0.10)
SPLITS = 50          # random two-way splits for held-out selective figures
SCALING_SPLITS = 10  # random two-way splits for held-out temperature scaling


def _groups(recs: list[dict]) -> dict[str, list[dict]]:
    from .evaluation import group_id
    out: dict[str, list[dict]] = {}
    for i, r in enumerate(recs):
        out.setdefault(group_id(r, i), []).append(r)
    return out


def n_groups(recs: list[dict]) -> int:
    return len(_groups(recs))


def accuracy(recs: list[dict]) -> float | None:
    ok = [r for r in recs if "error" not in r]
    return sum(r["correct"] for r in ok) / len(ok) if ok else None


def bootstrap(recs: list[dict], stat: Callable[[list[dict]], float | None], n: int = 1000, seed: int = 0,
              level: float = 0.95) -> list[float] | None:
    """Percentile interval from resampling whole groups with replacement."""
    groups = _groups(recs)
    keys = sorted(groups)
    if len(keys) < 5:
        return None
    rng = random.Random(seed)
    vals = []
    for _ in range(n):
        sample = [r for k in (rng.choice(keys) for _ in keys) for r in groups[k]]
        v = stat(sample)
        if v is not None and math.isfinite(v):
            vals.append(v)
    if not vals:
        return None
    vals.sort()
    lo = vals[int(round((1 - level) / 2 * (len(vals) - 1)))]
    hi = vals[int(round((1 + level) / 2 * (len(vals) - 1)))]
    return [lo, hi]


def majority(recs: list[dict]) -> float | None:
    """Accuracy of always giving the task's most common gold answer."""
    if not recs:
        return None
    counts: dict[str, int] = {}
    for r in recs:
        counts[r["gold"]] = counts.get(r["gold"], 0) + 1
    return max(counts.values()) / len(recs)


def _held_out(recs: list[dict], risk: float, seed: int, folds: int = 2) -> tuple[int, int]:
    from .evaluation import coverage_at_risk, group_folds
    fold = group_folds(recs, folds, seed)
    accepted = errors = 0
    for f in range(folds):
        select = [r for i, r in enumerate(recs) if fold[i] != f]
        score = [r for i, r in enumerate(recs) if fold[i] == f]
        threshold = coverage_at_risk(select, risk)["threshold"] if select else None
        if threshold is None:
            continue
        taken = [r for r in score if "error" not in r and r["confidence"] >= threshold]
        accepted += len(taken)
        errors += sum(not r["correct"] for r in taken)
    return accepted, errors


def _pctl(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return xs[int(round(q * (len(xs) - 1)))]


def _summary(per_split: list[tuple[int, int]], total: int) -> dict:
    """Mean share decided and pooled error over the splits, with the 10th to 90th percentile range."""
    accepted = sum(a for a, _ in per_split)
    errors = sum(e for _, e in per_split)
    coverages = [a / total for a, _ in per_split] if total else []
    rates = [e / a for a, e in per_split if a]
    return {"coverage": sum(coverages) / len(coverages) if coverages else 0.0,
            "coverage_range": [_pctl(coverages, 0.1), _pctl(coverages, 0.9)],
            "error": errors / accepted if accepted else None,
            "error_range": [_pctl(rates, 0.1), _pctl(rates, 0.9)] if rates else None,
            "accepted": accepted / len(per_split) if per_split else 0.0,
            "errors": errors / len(per_split) if per_split else 0.0,
            "splits": len(per_split)}


def selective(by_task: dict[str, list[dict]], risks: tuple[float, ...] = RISKS, splits: int = SPLITS) -> dict:
    """Share of decisions that clear a per-task confidence threshold, and the error among them.

    in_sample: threshold chosen and scored on the same labels (optimistic).
    held_out:  threshold chosen on half the groups and scored on the other half, both ways,
               averaged over `splits` random splits; error_range is the 10th to 90th percentile
               of the error across splits.
    """
    from .evaluation import coverage_at_risk
    total = sum(len(v) for v in by_task.values())
    out = {}
    for risk in risks:
        tasks, ins_a, ins_e = {}, 0, 0
        overall_splits = [[0, 0] for _ in range(splits)]
        for task, recs in by_task.items():
            if not recs:
                continue
            c = coverage_at_risk(recs, risk)
            ins_a += c["accepted"]
            ins_e += c["errors"]
            per_split = [_held_out(recs, risk, seed) for seed in range(splits)]
            for k, (a, e) in enumerate(per_split):
                overall_splits[k][0] += a
                overall_splits[k][1] += e
            tasks[task] = {"in_sample": {"coverage": c["accepted"] / len(recs), "accepted": c["accepted"],
                                         "errors": c["errors"], "error": c["errors"] / c["accepted"] if c["accepted"] else None},
                           "held_out": _summary(per_split, len(recs))}
        out[f"{risk:g}"] = {
            "risk": risk, "total": total, "tasks": tasks,
            "in_sample": {"coverage": ins_a / total if total else 0.0, "accepted": ins_a, "errors": ins_e,
                          "error": ins_e / ins_a if ins_a else None},
            "held_out": _summary([tuple(x) for x in overall_splits], total),
        }
    return out


def weighted_ece(recs: list[dict]) -> float | None:
    """Calibration error within each task, weighted by the task's share of decisions."""
    from .evaluation import ece
    ok = [r for r in recs if "error" not in r]
    tasks: dict[str, list[dict]] = {}
    for r in ok:
        tasks.setdefault(r["task"], []).append(r)
    if not ok:
        return None
    return sum(len(v) * ece(v) for v in tasks.values()) / len(ok)


def scaled_ece(recs: list[dict], splits: int = SCALING_SPLITS) -> float | None:
    """Calibration error after temperature scaling fitted on the other half of the groups,
    averaged over random splits. `recs` should be one task's decisions."""
    from .evaluation import ece, recalibrated
    ok = [r for r in recs if "error" not in r]
    if len(ok) < 2:
        return None
    vals = []
    for seed in range(splits):
        cal, _ = recalibrated(ok, 2, seed)
        if cal:
            vals.append(ece(cal))
    return sum(vals) / len(vals) if vals else None
