"""Run the example requests through the pipeline and save the traces for the page's
recorded mode.

    python -m scripts.record_examples --backend laya --backend anyjev
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings  # noqa: E402
from app.decisions import build_backends  # noqa: E402
from app.evaluation import clean  # noqa: E402
from app.graph import Graph  # noqa: E402
from app.pipeline import PIPELINE_VERSION, Pipeline  # noqa: E402

EXAMPLES = [
    ("I want to analyse particulate matter (PM2.5 and PM10) by country and year", "European countries, last 3 years"),
    ("Greenhouse gas emissions from road transport by country and month", "The most recent data available"),
    ("Ammonia from agriculture by country and year", "As many countries as possible"),
    ("Monthly NOx emissions by region for the last five years", "Italian regions"),
    ("Compare methane emissions across continents by year", "Official sources only"),
    ("Emissions data please", ""),
    ("Daily PM2.5 for Milan", ""),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", action="append", required=True)
    a = ap.parse_args()
    settings = replace(Settings.from_env(), backends=a.backend)
    pipe = Pipeline(Graph(), min_confidence=settings.min_confidence)
    for name, backend in build_backends(settings).items():
        ok, why = backend.available()
        if not ok:
            print(f"skip {name}: {why}")
            continue
        backend.warm_up()
        runs = []
        for request, pref in EXAMPLES:
            out = pipe.run(backend, request, pref or None)
            runs.append(out)
            print(f"{name}: {out['outcome']:8s} {out['totals']['latency_ms']:8.0f} ms  {request}")
        path = Path(settings.results_dir) / f"examples-{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(clean({"backend": name, "label": backend.label, "model": backend.model,
                                         "pipeline_version": PIPELINE_VERSION, "runs": runs}), indent=1))
        print("saved", path)


if __name__ == "__main__":
    main()
