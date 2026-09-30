from app import evaluation as ev
from app import stats
from app.calibration import question_key
from app.testset import build


def _rec(group, i, correct, confidence=0.9):
    return {"id": f"rel-{group}-{i}", "task": "relevance", "group": group, "gold": "yes",
            "top": "yes" if correct else "no", "correct": correct, "confidence": confidence,
            "probs": {"yes": confidence if correct else 1 - confidence, "no": 1 - confidence if correct else confidence},
            "latency_ms": 1.0}


def test_bootstrap_resamples_whole_groups():
    # Six requests, each entirely right or entirely wrong: 60 decisions, but only six independent units.
    recs = [_rec(f"R{g}", i, g % 2 == 0) for g in range(6) for i in range(10)]
    lo, hi = stats.bootstrap(recs, stats.accuracy)
    assert hi - lo > 0.3            # resampling decisions instead would give roughly +/- 0.13


def test_selective_counts_are_consistent_and_perfect_answers_cost_nothing():
    recs = [_rec(f"R{g}", i, True, 0.6 + g / 100) for g in range(10) for i in range(4)]
    sel = stats.selective({"relevance": recs})
    for risk, s in sel.items():
        ho = s["held_out"]
        assert 0 < ho["coverage"] <= 1 and ho["errors"] == 0 and ho["accepted"] <= s["total"]


def test_held_out_threshold_can_miss_its_target():
    # One request holds five confident mistakes. Chosen and scored on the same labels, a threshold
    # meets the 5% target; chosen on the other requests, it lets those mistakes through.
    recs = [_rec(f"R{g}", i, not (g == 0 and i < 5), 0.99 if i < 5 else 0.6) for g in range(10) for i in range(10)]
    sel = stats.selective({"relevance": recs})["0.05"]
    assert sel["in_sample"]["error"] <= 0.05
    assert sel["held_out"]["error"] > 0.05


def test_majority_baseline():
    recs = [{"gold": "no"}] * 9 + [{"gold": "yes"}]
    assert stats.majority(recs) == 0.9


def test_refresh_rescores_against_current_labels_and_flags_changed_questions():
    items = build()
    recs = [{"id": it["id"], "question_key": question_key(it["questions"][it["question"]]), "top": it["gold"],
             "confidence": 0.9, "probs": {it["gold"]: 0.9}, "correct": False, "latency_ms": 1.0} for it in items]
    data = ev.refresh({"records": recs}, items)
    assert data["current"] and data["metrics"]["overall"]["accuracy"] == 1.0   # stale "correct" flags replaced
    recs[0] = {**recs[0], "question_key": "changed"}
    data = ev.refresh({"records": recs}, items)
    assert not data["current"] and data["stale"] == 1
    data = ev.refresh({"records": recs[1:]}, items)
    assert not data["current"] and data["missing"] == 1
