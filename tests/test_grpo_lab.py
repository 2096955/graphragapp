"""CPU checks for labs/text2cypher-grpo: the graph, the split and the reward. No GPU needed."""
import sys
from pathlib import Path

import pytest

LAB = Path(__file__).resolve().parents[1] / "labs" / "text2cypher-grpo"
sys.path.insert(0, str(LAB))
graphlab = pytest.importorskip("graphlab")


@pytest.fixture(scope="module")
def lab(tmp_path_factory):
    path = tmp_path_factory.mktemp("grpo") / "graph.kuzu"
    data = graphlab.make_graph_data()
    graphlab.build_db(path, data)
    conn = graphlab.open_readonly(path)
    tasks = graphlab.make_tasks(conn, data)
    return conn, tasks


def test_splits_keep_test_entities_out_of_training(lab):
    _, tasks = lab
    splits = {t.split for t in tasks}
    assert splits == {"train", "test_seen", "test_unseen"}
    train_questions = {t.question for t in tasks if t.split == "train"}
    assert not train_questions & {t.question for t in tasks if t.split == "test_seen"}
    trained_templates = {t.template for t in tasks if t.split == "train"}
    assert not trained_templates & {t.template for t in tasks if t.split == "test_unseen"}


def test_reference_queries_score_one(lab):
    conn, tasks = lab
    for t in tasks[:60]:
        assert graphlab.score(f"```cypher\n{t.gold_cypher}\n```", t.gold_rows, conn) == (1.0, "correct")


def test_reward_tiers(lab):
    conn, tasks = lab
    t = tasks[0]
    assert graphlab.score("no code block here", t.gold_rows, conn) == (0.0, "no query")
    assert graphlab.score("```cypher\nMATCH (p:Person) DETACH DELETE p\n```", t.gold_rows, conn) == (-1.0, "write blocked")
    assert graphlab.score("```cypher\nMATCH (x:Nope) RETURN x\n```", t.gold_rows, conn) == (0.1, "error")
    wrong = graphlab.score("```cypher\nMATCH (c:Company) RETURN c.name\n```", t.gold_rows, conn)
    assert wrong[1] == "wrong rows" and 0.3 <= wrong[0] <= 0.7
