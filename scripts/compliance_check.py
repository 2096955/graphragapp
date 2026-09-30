"""Score decision backends on the 30 hand-labelled compliance payloads.

    python -m scripts.compliance_check --backend catalogue --backend laya --backend anyjev

Writes results/compliance-check.json. Nothing is written to the compliance graph. Thirty
payloads is a check, not a benchmark: use it to see where each backend fails, not to rank them.
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.compliance import check  # noqa: E402
from app.config import Settings  # noqa: E402
from app.decisions import build_backends  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", action="append", required=True)
    a = ap.parse_args()
    settings = replace(Settings.from_env(), backends=a.backend)
    path = Path(settings.results_dir) / "compliance-check.json"
    saved = json.loads(path.read_text()) if path.exists() else {"backends": {}}
    for name, backend in build_backends(settings).items():
        ok, why = backend.available()
        if not ok:
            print(f"skip {name}: {why}")
            continue
        backend.warm_up()
        res = check(backend.fork_for_benchmark())
        res["label"] = backend.label
        res["finished"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        res["hardware"] = f"{platform.machine()} {settings.device}"
        saved["backends"][name] = res
        wrong = [r["id"] for r in res["rows"] if r["action"] != r["gold"]]
        print(f"{name}: {res['right']}/{res['n']} right, {res['released_when_it_should_not']} released that "
              f"should not have been; wrong: {', '.join(wrong) or 'none'}")
    saved["note"] = ("Thirty hand-labelled payloads (app/compliance_labels.py). A check, not a benchmark. "
                     "Final actions after the fail-closed rules: a redact decision with nothing to remove is blocked.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(saved, indent=1))
    print("saved", path)


if __name__ == "__main__":
    main()
