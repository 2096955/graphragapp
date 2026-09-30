"""Fold a partial rerun into a full result file, replacing records by item id.

    python -m scripts.merge_results results/laya.json results/laya-relevance.json --reason "..."

The merged file records which tasks were rerun, when and why, and its metrics are recomputed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import evaluation as ev  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("full")
    ap.add_argument("partial")
    ap.add_argument("--reason", required=True)
    a = ap.parse_args()
    full, part = json.loads(Path(a.full).read_text()), json.loads(Path(a.partial).read_text())
    if full["backend"] != part["backend"] or full["model"] != part["model"]:
        sys.exit("The two files are for different backends or models.")
    new = {r["id"]: r for r in part["records"]}
    tasks = sorted({r["task"] for r in part["records"]})
    before = ev.metrics(full["records"])["tasks"]
    full["records"] = [new.get(r["id"], r) for r in full["records"]]
    full.setdefault("reruns", []).append({
        "tasks": tasks, "items": len(new), "finished": part["finished"], "seconds": part["seconds"], "reason": a.reason,
        "before": {t: {"accuracy": before[t]["accuracy"], "ece": before[t]["ece"]} for t in tasks}})
    full["metrics"] = ev.metrics(full["records"])
    Path(a.full).write_text(json.dumps(ev.clean(full), indent=1))
    print(f"{a.full}: replaced {len(new)} records ({', '.join(tasks)})")


if __name__ == "__main__":
    main()
