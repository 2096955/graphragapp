"""Benchmark runs survive a crash, retry only what is worth retrying, and never pay twice."""
import json

import httpx
import pytest

from app import evaluation as ev
from app.arize_eval import ArizeEval
from app.decisions import UniformBackend
from app.decisions.base import DecisionError, TransientError
from app.testset import build

ITEMS = build()[:12]


class Counting(UniformBackend):
    """Uniform answers; counts calls and can fail on chosen calls."""

    def __init__(self, crash_at=None, transient_first=0, permanent=False):
        super().__init__()
        self.calls, self.crash_at, self.transient_left, self.permanent = 0, crash_at, transient_first, permanent

    def _decide(self, state, questions):
        self.calls += 1
        if self.crash_at is not None and self.calls == self.crash_at:
            raise RuntimeError("process killed")
        if self.transient_left:
            self.transient_left -= 1
            raise TransientError("HTTP 429 after retries")
        if self.permanent:
            raise DecisionError("HTTP 400: bad request")
        return super()._decide(state, questions)


def test_a_crashed_run_resumes_without_repeating_decisions(tmp_path):
    ckpt = tmp_path / "uniform.progress.jsonl"
    first = Counting(crash_at=5)
    with pytest.raises(RuntimeError):
        ev.run(first, ITEMS, checkpoint=ckpt)
    assert len(ckpt.read_text().splitlines()) == 4
    second = Counting()
    recs = ev.run(second, ITEMS, checkpoint=ckpt)
    assert second.calls == len(ITEMS) - 4
    assert [r["id"] for r in recs] == [it["id"] for it in ITEMS]
    assert all("error" not in r and "model" not in r for r in recs)


def test_checkpoint_ignores_other_models_questions_and_torn_lines(tmp_path):
    ckpt = tmp_path / "p.jsonl"
    ev.run(Counting(), ITEMS[:3], checkpoint=ckpt)
    lines = ckpt.read_text().splitlines()
    other = json.loads(lines[0]) | {"model": "another-model"}
    changed = json.loads(lines[1]) | {"question_key": "an older question"}
    ckpt.write_text("\n".join([json.dumps(other), json.dumps(changed), lines[2], '{"id": "torn'] ) + "\n")
    again = Counting()
    ev.run(again, ITEMS[:3], checkpoint=ckpt)
    assert again.calls == 2


def test_transient_errors_are_retried_with_backoff():
    waits = []
    b = Counting(transient_first=2)
    rec = ev.run(b, ITEMS[:1], sleep=waits.append)[0]
    assert "error" not in rec and b.calls == 3 and waits == [2.0, 4.0]
    b = Counting(transient_first=9)
    rec = ev.run(b, ITEMS[:1], sleep=waits.append)[0]
    assert rec["transient"] and b.calls == ev.RETRIES


def test_permanent_errors_are_not_retried_but_are_tried_again_next_run(tmp_path):
    ckpt = tmp_path / "p.jsonl"
    b = Counting(permanent=True)
    rec = ev.run(b, ITEMS[:1], checkpoint=ckpt, sleep=lambda s: None)[0]
    assert b.calls == 1 and "error" in rec
    fixed = Counting()
    assert "error" not in ev.run(fixed, ITEMS[:1], checkpoint=ckpt)[0] and fixed.calls == 1


def test_arize_export_retries_rate_limits_not_bad_requests():
    replies = []

    def handler(request):
        return httpx.Response(replies.pop(0))

    trace = {"action": "release", "cost_usd": 0, "pattern_id": "p", "backend": "catalogue", "correct": True}
    exporter = ArizeEval("space", "key", transport=httpx.MockTransport(handler), sleep=lambda s: None)
    replies[:] = [503, 429, 200]
    assert exporter._export(trace) == {"ok": True, "status": 200, "attempts": 3}
    replies[:] = [400, 200]
    assert exporter._export(trace) == {"ok": False, "status": 400, "attempts": 1}
