"""Recompute the dense similarities behind the field guide's Lab 1 (hybrid text retrieval).

    python -m scripts.field_guide_dense            # compare with the values in the page
    python -m scripts.field_guide_dense --write    # write new values into the page

The page cannot run an embedding model, so Lab 1 carries precomputed cosine similarities between
each preset question (the datalist `aQList`) and each node's text, from all-MiniLM-L6-v2. For any
other question the lab falls back to BM25 alone. Needs `pip install -r requirements-local.txt`.
"""
from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "web" / "field-guide.html"
MODEL = "sentence-transformers/all-MiniLM-L6-v2"
NODE = re.compile(r'\{id:"(\w+)",label:"([^"]*)",type:"[^"]*",x:[\d.]+,y:[\d.]+,text:"([^"]*)"\}')


def page_parts(text: str) -> tuple[dict[str, str], list[str], dict]:
    nodes = {m.group(1): m.group(3) for m in NODE.finditer(text)}
    datalist = text[text.index('<datalist id="aQList">'):text.index("</datalist>")]
    questions = [html.unescape(q) for q in re.findall(r'<option value="([^"]*)"', datalist)]
    line = next(x for x in text.splitlines() if x.startswith("const DENSE="))
    current = json.loads(line[len("const DENSE="):].rstrip(";"))
    return nodes, questions, current


def similarities(nodes: dict[str, str], questions: list[str]) -> dict:
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(MODEL, device="cpu")
    ids = list(nodes)
    n = model.encode([nodes[i] for i in ids], normalize_embeddings=True)
    q = model.encode(questions, normalize_embeddings=True)
    sims = q @ n.T
    return {question: {i: round(float(s), 3) for i, s in zip(ids, row)} for question, row in zip(questions, sims)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="write the new values into web/field-guide.html")
    a = ap.parse_args()
    text = PAGE.read_text(encoding="utf-8")
    nodes, questions, current = page_parts(text)
    new = similarities(nodes, questions)
    worst = max((abs(new[q][i] - current.get(q, {}).get(i, 99)) for q in new for i in new[q]), default=0.0)
    print(f"{len(questions)} questions, {len(nodes)} nodes; largest difference from the page: {worst:.3f}")
    if a.write:
        old_line = next(x for x in text.splitlines() if x.startswith("const DENSE="))
        PAGE.write_text(text.replace(old_line, "const DENSE=" + json.dumps(new, separators=(",", ":")) + ";"),
                        encoding="utf-8")
        print("wrote", PAGE.relative_to(ROOT))


if __name__ == "__main__":
    main()
