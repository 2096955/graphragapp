"""Frozen, model-specific serving temperatures and acceptance thresholds."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path


def question_key(question: dict) -> str:
    return hashlib.sha256(json.dumps(question, sort_keys=True).encode()).hexdigest()


def task_for(name: str, question: dict) -> str:
    if name == "gate":
        return "gate"
    if name in ("GEO", "TIME", "SECTOR"):
        return "level"
    if name.startswith("group:"):
        return "group"
    if name == "maps_to":
        return "mapping"
    if name == "same":
        return "entity"
    return "fit" if question["type"] == "score" else "relevance"


class Calibration:
    def __init__(self, path: str | Path, model: str):
        self.data = json.loads(Path(path).read_text())
        if self.data.get("version") != 1 or self.data.get("model") != model:
            raise ValueError("Calibration artifact version/model does not match this backend.")
        for spec in self.data.get("tasks", {}).values():
            t = spec["temperature"]
            if not isinstance(t, (int, float)) or not math.isfinite(t) or t <= 0:
                raise ValueError("Calibration temperatures must be positive and finite.")
            threshold = spec.get("threshold")
            if threshold is not None and not 0 <= threshold <= 1:
                raise ValueError("Calibration thresholds must be in [0, 1].")

    def spec(self, name: str, question: dict) -> dict | None:
        spec = self.data.get("tasks", {}).get(task_for(name, question))
        return spec if spec and question_key(question) in spec.get("questions", []) else None

    def apply(self, name: str, question: dict, probs: dict) -> dict:
        spec = self.spec(name, question)
        if spec is None:
            return probs
        logs = {k: math.log(max(p, 1e-12)) / spec["temperature"] for k, p in probs.items()}
        highest = max(logs.values())
        values = {k: math.exp(v - highest) for k, v in logs.items()}
        total = sum(values.values())
        return {k: v / total for k, v in values.items()}
