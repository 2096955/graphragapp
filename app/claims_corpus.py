"""A small invented corpus for the claims-graph example.

Every publisher, person, document and quote here is fictional. The corpus is shaped like the
publications a regulated client would track: regulators, an industry body and a consumer group
writing about the same topics over three years, with positions that harden, relax or reverse.

EXTRACTED is the recorded output of claim extraction: in production an LLM reads each document
and proposes claims; here the proposals are written by hand so the example runs with no keys.
Three of them are deliberately wrong, the way an extractor goes wrong: two overstate or
contradict their quote, and one quotes text that is not in the document.
"""
from __future__ import annotations

PUBLISHERS = {
    "mpa": {"name": "Meridian Prudential Authority", "kind": "regulator"},
    "csmc": {"name": "Coral Sea Markets Commission", "kind": "regulator"},
    "ois": {"name": "Office of the Information Steward", "kind": "regulator"},
    "csbf": {"name": "Coral Sea Bankers' Forum", "kind": "industry body"},
    "lca": {"name": "Lantern Consumer Alliance", "kind": "consumer group"},
}

PEOPLE = {
    "oyelaran": {"name": "Nadia Oyelaran", "role": "Deputy Chair", "publisher": "mpa"},
    "fairweather": {"name": "Tomas Fairweather", "role": "Commissioner", "publisher": "csmc"},
    "castellane": {"name": "Imogen Castellane", "role": "Information Steward", "publisher": "ois"},
    "quist": {"name": "Rafael Quist", "role": "Chief Executive", "publisher": "csbf"},
    "okafor-lane": {"name": "Ines Okafor-Lane", "role": "Director", "publisher": "lca"},
}

# Topic -> aspects. Claims are compared only within one aspect, so "the same claim" and
# "a change of position" are asked about statements that address the same point.
TOPICS = {
    "automated-declines": {"label": "Automated declines",
                           "aspects": {"human-review": "Human review of automated declines",
                                       "explanation": "Telling customers why they were declined"}},
    "model-register": {"label": "Model registers and validation",
                       "aspects": {"register": "Keeping a register of models and validating them"}},
    "vendor-models": {"label": "Vendor models",
                      "aspects": {"accountability": "Accountability for decisions made with a vendor's model"}},
    "genai-customer-data": {"label": "Customer information in generative AI",
                            "aspects": {"use": "Whether customer information may be used in generative AI",
                                        "notice": "Telling customers when generative AI is used on their information"}},
}

DOCUMENTS = [
    {"id": "D01", "publisher": "mpa", "person": "oyelaran", "date": "2023-05-10", "kind": "speech",
     "title": "Opening remarks, model risk roundtable",
     "text": ("Thank you for coming. Most of the models we see in lending are well built; the weaknesses are in how "
              "they are governed. Two points today. First, we encourage institutions to keep a person involved when a "
              "model declines a customer, but we are not prescribing how. Second, every institution should know which "
              "models it runs. An inventory of models is the least we would expect, and a surprising number of firms "
              "could not produce one when we asked last year.")},
    {"id": "D02", "publisher": "csmc", "person": "fairweather", "date": "2024-02-20", "kind": "report",
     "title": "Governance of AI in consumer lending",
     "text": ("This review covered forty-one lenders. Our main finding is simple: buying a model does not buy an "
              "exemption. A lender answers for the decision, whoever wrote the code. We also found that customers who "
              "were declined by an automated system rarely knew they could ask for a person to look again. Lenders "
              "should give every declined customer a clear way to ask for a human review. This report does not cover "
              "insurers, which we will examine separately.")},
    {"id": "D03", "publisher": "mpa", "person": "oyelaran", "date": "2024-09-03", "kind": "speech",
     "title": "Supervisory priorities for 2025",
     "text": ("Our priorities for next year build on what we said in 2023. On automated decisions, our view has moved. "
              "For adverse decisions, we now expect institutions to offer a review by a person, who can overturn the "
              "model where it is wrong. We will test this in our reviews. We will also ask boards how they satisfy "
              "themselves about models bought from vendors, since an institution remains accountable for decisions "
              "made with a model it bought from a vendor.")},
    {"id": "D04", "publisher": "ois", "person": "castellane", "date": "2024-11-12", "kind": "guidance",
     "title": "Generative AI and customer information",
     "text": ("Organisations are asking whether they can use generative AI tools with the personal information they "
              "hold about customers. Our answer for now is no: customer personal information should not be entered "
              "into generative AI tools. We will revisit this as the tools and their controls mature. Where an "
              "organisation already uses generative AI on customer information, it must tell the customers concerned. "
              "This note does not address information about employees.")},
    {"id": "D05", "publisher": "csbf", "person": "quist", "date": "2025-02-14", "kind": "submission",
     "title": "Submission on automated decision rules",
     "text": ("The Forum represents twenty-three banks. We oppose any requirement for human review of automated "
              "declines. Declines are reviewed in aggregate through model monitoring, and a case-by-case review "
              "requirement would slow credit decisions without improving them. On registers, our members already keep "
              "an inventory of their models, so new rules on inventories would add cost without adding safety.")},
    {"id": "D06", "publisher": "mpa", "person": "oyelaran", "date": "2025-08-18", "kind": "consultation",
     "title": "Proposed standard on automated decisions",
     "text": ("This paper proposes a standard for automated decisions about customers. Where a model declines a "
              "customer, a person must review the decision if the customer asks, and the customer must be told how "
              "to ask. Each institution must keep a register of every model that makes or informs a decision about a "
              "customer, and must validate each model before it is used. Submissions close on 30 October 2025.")},
    {"id": "D07", "publisher": "lca", "person": "okafor-lane", "date": "2025-09-02", "kind": "media release",
     "title": "Declined by a machine, and no one to ask",
     "text": ("Our survey of 1,200 borrowers found that fewer than one in five of those declined by an automated "
              "system were told why. People declined by a machine deserve an explanation in plain language. We also "
              "call on lenders to stop feeding customer records into generative AI systems until customers have "
              "agreed to it.")},
    {"id": "D08", "publisher": "mpa", "person": None, "date": "2025-10-01", "kind": "annual report",
     "title": "Annual report 2024-25 (extract)",
     "text": ("During the year we expanded our inventory of climate scenarios to eleven and reviewed how banks model "
              "flood risk. Our own staff completed a register of the systems we use internally. We declined three "
              "applications for new banking licences.")},
    {"id": "D09", "publisher": "ois", "person": "castellane", "date": "2026-03-10", "kind": "guidance",
     "title": "Updated guidance: generative AI and customer information",
     "text": ("Since our 2024 note, controls for enterprise generative AI tools have improved. We now accept that "
              "customer personal information may be used in generative AI tools that keep the information inside the "
              "organisation. The obligation to tell customers stays: an organisation using these tools on customer "
              "information must still tell the customers concerned. Public tools that send information outside the "
              "organisation remain unsuitable for customer information.")},
    {"id": "D10", "publisher": "mpa", "person": "oyelaran", "date": "2026-04-15", "kind": "standard",
     "title": "Standard on automated decisions",
     "text": ("This standard takes effect on 1 January 2027. An institution must maintain a register of every model "
              "that informs a decision about a customer and must validate each model before it is used. A person must "
              "review any automated decline when the customer asks, and institutions must tell declined customers how "
              "to ask. Signed, Nadia Oyelaran, Deputy Chair.")},
    {"id": "D11", "publisher": "csmc", "person": "fairweather", "date": "2026-05-05", "kind": "speech",
     "title": "Enforcement priorities for 2026-27",
     "text": ("Two years ago we asked lenders to give declined customers a way to ask for a person. Many did; some did "
              "not. From 1 July 2026, a lender that declines customers with a model and offers no human review on "
              "request will face enforcement action. We will start with the largest lenders.")},
    {"id": "D12", "publisher": "csbf", "person": "quist", "date": "2026-06-01", "kind": "statement",
     "title": "Forum response to the final standard",
     "text": ("Our members have now run human review on request for a year in a pilot. It worked better than we "
              "expected, and complaints fell. The Forum now supports a requirement for human review of automated "
              "declines when the customer asks. We still see no case for reviewing every decline.")},
]

# (id, document, topic, aspect, statement, quote). The speaker is the document's person.
EXTRACTED: list[tuple[str, str, str, str, str, str]] = [
    ("C01", "D01", "automated-declines", "human-review",
     "Keeping a person involved when a model declines a customer is encouraged, not required.",
     "we encourage institutions to keep a person involved when a model declines a customer, but we are not "
     "prescribing how"),
    ("C02", "D01", "model-register", "register",
     "Every institution should keep an inventory of the models it runs.",
     "every institution should know which models it runs. An inventory of models is the least we would expect"),
    ("C03", "D02", "vendor-models", "accountability",
     "A lender stays accountable for decisions made with a vendor's model.",
     "buying a model does not buy an exemption. A lender answers for the decision, whoever wrote the code"),
    ("C04", "D02", "automated-declines", "human-review",
     "Lenders should give declined customers a clear way to ask for a human review.",
     "Lenders should give every declined customer a clear way to ask for a human review"),
    ("C05", "D03", "automated-declines", "human-review",
     "For adverse decisions, institutions are now expected to offer a review by a person who can overturn the model.",
     "For adverse decisions, we now expect institutions to offer a review by a person, who can overturn the model "
     "where it is wrong"),
    ("C06", "D03", "vendor-models", "accountability",
     "An institution remains accountable for decisions made with a vendor's model.",
     "an institution remains accountable for decisions made with a model it bought from a vendor"),
    ("C07", "D04", "genai-customer-data", "use",
     "Customer personal information should not be entered into generative AI tools.",
     "customer personal information should not be entered into generative AI tools"),
    ("C08", "D04", "genai-customer-data", "notice",
     "An organisation that uses generative AI on customer information must tell the customers concerned.",
     "Where an organisation already uses generative AI on customer information, it must tell the customers "
     "concerned"),
    ("C09", "D05", "automated-declines", "human-review",
     "The Forum opposes any requirement for human review of automated declines.",
     "We oppose any requirement for human review of automated declines"),
    ("C10", "D05", "model-register", "register",
     "New rules on model inventories are unnecessary because banks already keep them.",
     "our members already keep an inventory of their models, so new rules on inventories would add cost without "
     "adding safety"),
    ("C11", "D06", "automated-declines", "human-review",
     "Where a model declines a customer, a person must review the decision on request, and the customer must be told "
     "how to ask.",
     "Where a model declines a customer, a person must review the decision if the customer asks, and the customer "
     "must be told how to ask"),
    ("C12", "D06", "model-register", "register",
     "Institutions must keep a register of the models that inform decisions about customers and validate each model "
     "before use.",
     "Each institution must keep a register of every model that makes or informs a decision about a customer, and "
     "must validate each model before it is used"),
    ("C13", "D07", "automated-declines", "explanation",
     "Customers declined by an automated system should be told why, in plain language.",
     "People declined by a machine deserve an explanation in plain language"),
    ("C14", "D07", "genai-customer-data", "use",
     "Lenders should not use customer records in generative AI systems without the customers' agreement.",
     "call on lenders to stop feeding customer records into generative AI systems until customers have agreed to it"),
    ("C15", "D09", "genai-customer-data", "use",
     "Customer personal information may be used in generative AI tools that keep it inside the organisation.",
     "customer personal information may be used in generative AI tools that keep the information inside the "
     "organisation"),
    ("C16", "D09", "genai-customer-data", "notice",
     "An organisation using generative AI on customer information must still tell the customers concerned.",
     "an organisation using these tools on customer information must still tell the customers concerned"),
    ("C17", "D10", "automated-declines", "human-review",
     "A person must review any automated decline when the customer asks, and customers must be told how to ask.",
     "A person must review any automated decline when the customer asks, and institutions must tell declined "
     "customers how to ask"),
    ("C18", "D10", "model-register", "register",
     "Institutions must maintain a register of the models that inform decisions about customers and validate each "
     "before use.",
     "An institution must maintain a register of every model that informs a decision about a customer and must "
     "validate each model before it is used"),
    ("C19", "D11", "automated-declines", "human-review",
     "From 1 July 2026, lenders that decline customers with a model and offer no human review on request will face "
     "enforcement action.",
     "From 1 July 2026, a lender that declines customers with a model and offers no human review on request will "
     "face enforcement action"),
    ("C20", "D12", "automated-declines", "human-review",
     "The Forum now supports a requirement for human review of automated declines when the customer asks.",
     "The Forum now supports a requirement for human review of automated declines when the customer asks"),
    # Extraction errors, kept on purpose.
    ("X01", "D01", "automated-declines", "human-review",
     "A person must review every decision in which a model declines a customer.",
     "we encourage institutions to keep a person involved when a model declines a customer, but we are not "
     "prescribing how"),
    ("X02", "D06", "model-register", "register",
     "Institutions may decide for themselves whether to validate their models.",
     "Each institution must keep a register of every model that makes or informs a decision about a customer, and "
     "must validate each model before it is used"),
    ("X03", "D05", "automated-declines", "human-review",
     "The Forum supports human review of every decline.",
     "We support human review of every decline"),
]

DOC = {d["id"]: d for d in DOCUMENTS}


def speaker(doc_id: str) -> str | None:
    return DOC[doc_id]["person"]
