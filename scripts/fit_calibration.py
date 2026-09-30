"""Fit frozen serving temperatures with separate grouped fit/select/test partitions."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app import evaluation as ev


def fit(data: dict, risk: float = 0.05) -> dict:
    if not 0 <= risk <= 1:
        raise ValueError("Risk must be in [0, 1].")
    artifact = {"version": 1, "model": data["model"], "tasks": {},
                "method": "grouped_fit_selection_test", "validated_risk_guarantee": False}
    for task in sorted({r["task"] for r in data["records"]}):
        recs = [r for r in data["records"] if r["task"] == task]
        folds = ev.group_folds(recs, 3)
        partitions = [[r for i, r in enumerate(recs) if folds[i] == f] for f in range(3)]
        train = [r for r in partitions[0] if "error" not in r]
        if not train or not partitions[1] or not partitions[2]:
            continue
        temp = ev._fit_temperature(train)
        def transform(records):
            out = []
            for r in records:
                if "error" in r:
                    out.append(r)
                    continue
                p = ev._temper(r["probs"], temp)
                top = max(p, key=p.get)
                out.append({**r, "probs": p, "top": top, "confidence": p[top], "correct": top == r["gold"]})
            return out
        selected = ev.coverage_at_risk(transform(partitions[1]), risk)
        keys = []
        for r in recs:
            key = r.get("question_key")
            if key:
                keys.append(key)
        # Legacy result files did not record question signatures; do not apply them to changed prompts.
        if not keys:
            continue
        artifact["tasks"][task] = {"temperature": temp, "threshold": selected["threshold"],
                                  "questions": sorted(set(keys)), "selection": selected,
                                  "holdout": ev.evaluate_threshold(transform(partitions[2]), selected["threshold"], risk),
                                  "partition_groups": [sorted({ev.group_id(r) for r in p}) for p in partitions]}
    if not artifact["tasks"]:
        raise ValueError("No eligible tasks with current question signatures and three independent groups. Run a fresh benchmark first.")
    return artifact


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("results")
    parser.add_argument("--out", required=True)
    parser.add_argument("--risk", type=float, default=0.05)
    args = parser.parse_args()
    data = json.loads(Path(args.results).read_text())
    artifact = fit(data, args.risk)
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, indent=2))
    print(f"Saved {path}; held-out risk is reported, not guaranteed. Restart the server to load it.")


if __name__ == "__main__":
    main()
