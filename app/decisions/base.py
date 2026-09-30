"""One decision interface in front of several backends.

Questions use Jev's wire format, which Laya also accepts:

    {"type": "noul",   "instructions": "...", "criteria": {"true": "...", "false": "..."}}
    {"type": "choice", "instructions": "...", "criteria": {"label": "description or null", ...}}
    {"type": "score",  "instructions": "...", "criteria": ["level 0", "level 1", ...]}

Every backend returns the same normalised answer: a probability for each label, where noul
labels are "yes"/"no", choice labels are the criteria keys and score labels are "0", "1", ...
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

QUESTION_TYPES = ("noul", "choice", "score")
MAX_OPTIONS = 26          # AnyJev's letter readout limit; applied to every backend for comparability
MAX_SCORE_LEVELS = 10


class DecisionError(Exception):
    """A request the backend could not answer."""


class BackendUnavailable(DecisionError):
    """The backend is not configured or not installed."""


def validate_questions(questions: dict[str, Any], max_questions: int = 32) -> None:
    if not isinstance(questions, dict) or not questions:
        raise DecisionError("questions must be a non-empty object keyed by question name")
    if len(questions) > max_questions:
        raise DecisionError(f"at most {max_questions} questions per request")
    for name, q in questions.items():
        if not isinstance(name, str) or not name or len(name) > 64:
            raise DecisionError("question names must be strings of 1 to 64 characters")
        if not isinstance(q, dict) or q.get("type") not in QUESTION_TYPES:
            raise DecisionError(f"question {name!r}: type must be one of {QUESTION_TYPES}")
        ins = q.get("instructions")
        if ins is not None and not isinstance(ins, str):
            raise DecisionError(f"question {name!r}: instructions must be text")
        crit = q.get("criteria")
        if q["type"] == "choice":
            if not isinstance(crit, dict) or not 2 <= len(crit) <= MAX_OPTIONS:
                raise DecisionError(f"question {name!r}: a choice needs 2 to {MAX_OPTIONS} options in criteria")
            if any(not isinstance(k, str) or not k for k in crit):
                raise DecisionError(f"question {name!r}: option names must be non-empty text")
            if any(v is not None and not isinstance(v, str) for v in crit.values()):
                raise DecisionError(f"question {name!r}: option descriptions must be text or null")
        elif q["type"] == "score":
            if not isinstance(crit, list) or not 2 <= len(crit) <= MAX_SCORE_LEVELS or not all(isinstance(x, str) for x in crit):
                raise DecisionError(f"question {name!r}: a score needs 2 to {MAX_SCORE_LEVELS} level descriptions")
        elif crit is not None:
            if not isinstance(crit, dict) or set(crit) - {"true", "false"}:
                raise DecisionError(f"question {name!r}: noul criteria may only have 'true' and 'false'")


def labels(q: dict) -> list[str]:
    if q["type"] == "noul":
        return ["yes", "no"]
    if q["type"] == "choice":
        return list(q["criteria"].keys())
    return [str(i) for i in range(len(q["criteria"]))]


def normalise(q: dict, probs: dict[str, float]) -> dict[str, float]:
    """Every label present, finite, non-negative, summing to 1."""
    out = {}
    for lab in labels(q):
        v = probs.get(lab, 0.0)
        v = float(v) if v is not None and math.isfinite(float(v)) else 0.0
        out[lab] = max(0.0, v)
    total = sum(out.values())
    if total <= 0:
        return {lab: 1.0 / len(out) for lab in out}
    return {lab: v / total for lab, v in out.items()}


@dataclass
class Answer:
    type: str
    probabilities: dict[str, float]
    levels: list[str] | None = None      # score only: descriptions, for display

    @property
    def top(self) -> str:
        return max(self.probabilities, key=self.probabilities.get)

    @property
    def confidence(self) -> float:
        return max(self.probabilities.values())

    def to_dict(self) -> dict:
        out: dict[str, Any] = {"type": self.type, "probabilities": {k: round(v, 5) for k, v in self.probabilities.items()},
                               "top": self.top, "confidence": round(self.confidence, 5)}
        if self.type == "noul":
            out["noul"] = round(self.probabilities["yes"], 5)
        if self.type == "score":
            out["score"] = round(sum(int(k) * v for k, v in self.probabilities.items()), 4)
            out["legend"] = {str(i): lvl for i, lvl in enumerate(self.levels or [])}
        return out


@dataclass
class DecisionResult:
    backend: str
    model: str
    answers: dict[str, Answer]
    latency_ms: float
    input_tokens: int | None = None
    cost_usd: float = 0.0
    residency: str = "local"
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"backend": self.backend, "model": self.model, "latency_ms": round(self.latency_ms, 1),
                "input_tokens": self.input_tokens, "cost_usd": self.cost_usd, "residency": self.residency,
                "detail": self.detail, "answers": {k: a.to_dict() for k, a in self.answers.items()}}


class Backend:
    """Base class. Subclasses implement _decide(state, questions) -> (answers, tokens, cost, detail)."""

    name = "base"
    label = "Base"
    residency = "local"           # "local": data stays where the backend runs; "hosted": sent to a vendor
    description = ""

    def __init__(self, model: str = ""):
        self.model = model
        self.calibration = None

    def status(self) -> dict:
        ok, why = self.available()
        return {"name": self.name, "label": self.label, "model": self.model, "residency": self.residency,
                "description": self.description, "available": ok, "reason": why, "loaded": self.loaded()}

    def available(self) -> tuple[bool, str]:
        return True, ""

    def loaded(self) -> bool:
        return True

    def warm_up(self) -> None:
        """Load weights or open connections ahead of the first request."""

    def fork_for_benchmark(self):
        return self

    def decide(self, state: Any, questions: dict[str, dict], *, calibrate: bool = True) -> DecisionResult:
        ok, why = self.available()
        if not ok:
            raise BackendUnavailable(why)
        validate_questions(questions)
        t = time.perf_counter()
        raw, tokens, cost, detail = self._decide(state, questions)
        ms = (time.perf_counter() - t) * 1000
        answers = {}
        calibrated = []
        for name, q in questions.items():
            if name not in raw:
                raise DecisionError(f"{self.label} returned no answer for {name!r}")
            probs = normalise(q, raw[name])
            if calibrate and self.calibration and self.calibration.spec(name, q):
                probs = self.calibration.apply(name, q, probs)
                calibrated.append(name)
            answers[name] = Answer(q["type"], probs, q["criteria"] if q["type"] == "score" else None)
        detail = {**detail, "calibrated_questions": calibrated}
        return DecisionResult(self.name, self.model, answers, ms, tokens, cost, self.residency, detail)

    def _decide(self, state, questions):  # pragma: no cover - abstract
        raise NotImplementedError


def from_wire(q: dict, a: dict) -> dict[str, float]:
    """Convert a Jev- or Laya-style answer to label probabilities."""
    if q["type"] == "noul":
        p = float(a["noul"])
        return {"yes": p, "no": 1.0 - p}
    return {str(k): float(v) for k, v in (a.get("probabilities") or {}).items()}
