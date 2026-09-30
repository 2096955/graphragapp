"""Run the labelled test set against one backend and save the results.

    python -m scripts.run_benchmark --backend laya
    python -m scripts.run_benchmark --backend anyjev --tasks gate,entity --limit 40
    python -m scripts.run_benchmark --backend jev          # needs TYPESAFE_API_KEY

Results go to results/<backend>.json; the page reads them from there.
"""
from __future__ import annotations

import argparse
import os
import platform
import sys
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import evaluation as ev  # noqa: E402
from app.config import Settings  # noqa: E402
from app.decisions import build_backends  # noqa: E402
from app.testset import build  # noqa: E402


def hardware() -> str:
    cpu = platform.processor() or platform.machine()
    try:
        for line in open("/proc/cpuinfo"):
            if line.startswith("model name"):
                cpu = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    try:
        import torch
        if torch.cuda.is_available():
            return f"GPU: {torch.cuda.get_device_name(0)}"
    except ImportError:
        pass
    return f"CPU only: {os.cpu_count()} vCPU, {cpu}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", required=True)
    ap.add_argument("--tasks", default="")
    ap.add_argument("--limit", type=int, default=0, help="items per task, 0 for all")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    settings = replace(Settings.from_env(), backends=[a.backend])
    backend = build_backends(settings)[a.backend]
    ok, why = backend.available()
    if not ok:
        sys.exit(why)

    items = build()
    if a.tasks:
        keep = set(a.tasks.split(","))
        items = [i for i in items if i["task"] in keep]
    if a.limit:
        seen: dict[str, int] = {}
        items = [i for i in items if seen.setdefault(i["task"], 0) < a.limit and not seen.__setitem__(i["task"], seen[i["task"]] + 1)]

    t = time.perf_counter()
    backend.warm_up()
    print(f"{backend.label}: loaded in {time.perf_counter() - t:.1f}s; {len(items)} items", flush=True)

    def progress(i, n):
        if i % 25 == 0 or i == n:
            print(f"  {i}/{n}", flush=True)

    recs, secs = ev.timed_run(backend, items, progress=progress)
    out = a.out or os.path.join(settings.results_dir, f"{a.backend}.json")
    res = ev.save(out, backend, recs, hardware(), secs)
    m = res["metrics"]["overall"]
    print(f"accuracy {m['accuracy']:.3f}  ECE {m['ece']:.3f} -> {m['ece_recalibrated']:.3f} after temperature scaling  "
          f"p50 {m['latency_ms_p50']:.0f} ms  saved {out}")
    for task, tm in res["metrics"]["tasks"].items():
        if tm["n"]:
            print(f"  {task:10s} n={tm['n']:3d} acc {tm['accuracy']:.3f} ece {tm['ece']:.3f} cov@5% {tm['coverage_at_5']['coverage']:.2f}")


if __name__ == "__main__":
    main()
