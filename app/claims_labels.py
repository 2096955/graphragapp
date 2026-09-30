"""Hand-written labels for the claims-graph example. Policy: LABELLING.md, section 9.

Nothing in the application generates these. They were written from the corpus, and every backend,
including the rules, is scored against them the same way.
"""
from __future__ import annotations

# Does the quote support the claim exactly as stated? X03 is not here: its quote is not in the
# document, so the mechanical check rejects it before any model is asked.
SUPPORTS: dict[str, str] = {**{f"C{i:02d}": "yes" for i in range(1, 21)}, "X01": "no", "X02": "no"}

# Pairs that make the same claim. Every other candidate pair (same topic and aspect, different
# documents) is labelled "no": a statement that goes further, or less far, is a different claim.
SAME_YES: set[frozenset[str]] = {
    frozenset({"C03", "C06"}),   # a lender or institution stays accountable for a vendor's model
    frozenset({"C08", "C16"}),   # tell customers when generative AI is used on their information
    frozenset({"C11", "C17"}),   # human review on request, proposed then final
    frozenset({"C12", "C18"}),   # register and validate models, proposed then final
}

# How the same person's position changed between consecutive statements on the same aspect.
SHIFT: dict[tuple[str, str], str] = {
    ("C01", "C05"): "stronger",   # encouraged -> expected
    ("C05", "C11"): "stronger",   # expected -> must (proposed)
    ("C11", "C17"): "same",       # proposed -> final, same rule
    ("C02", "C12"): "stronger",   # should know its models -> must keep a register and validate
    ("C12", "C18"): "same",
    ("C04", "C19"): "stronger",   # should offer a way to ask -> enforcement action
    ("C07", "C15"): "weaker",     # should not be used -> may be used inside the organisation
    ("C08", "C16"): "same",
    ("C09", "C20"): "opposite",   # opposes any requirement -> supports a requirement
}

# Questions for the retrieval comparison. Gold is the set of claims whose passages answer the
# question, or, for questions no claim answers, a phrase from the passage that does.
QUESTIONS: list[dict] = [
    {"id": "R01", "kind": "who", "question": "Who has said anything about human review of automated declines?",
     "claims": ["C01", "C04", "C05", "C09", "C11", "C17", "C19", "C20"]},
    {"id": "R02", "kind": "timeline", "question": "How has Nadia Oyelaran's view on human review of declines changed?",
     "claims": ["C01", "C05", "C11", "C17"]},
    {"id": "R03", "kind": "publisher",
     "question": "What has the Office of the Information Steward said about customer information in generative AI?",
     "claims": ["C07", "C08", "C15", "C16"]},
    {"id": "R04", "kind": "as_of",
     "question": "As of the start of 2025, what was the Information Steward's position on customer information in "
                 "generative AI?",
     "claims": ["C07", "C08"], "not_after": "2025-01-01"},
    {"id": "R05", "kind": "same", "question": "Who says an organisation stays accountable for decisions made with a "
                                             "vendor's model?",
     "claims": ["C03", "C06"]},
    {"id": "R06", "kind": "who", "question": "What have regulators said about keeping a register of models?",
     "claims": ["C02", "C12", "C18"]},
    {"id": "R07", "kind": "timeline", "question": "Has the Coral Sea Bankers' Forum changed its position on human "
                                                  "review?",
     "claims": ["C09", "C20"]},
    {"id": "R08", "kind": "who", "question": "Who has asked for declined customers to be told why?",
     "claims": ["C13"]},
    {"id": "R09", "kind": "content", "question": "What did the Lantern Consumer Alliance's survey of borrowers find?",
     "passages": ["fewer than one in five"]},
    {"id": "R10", "kind": "content", "question": "How many climate scenarios does the Meridian Prudential Authority use?",
     "passages": ["climate scenarios to eleven"]},
]
