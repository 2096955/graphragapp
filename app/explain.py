"""Explanations. A template by default; any OpenAI-compatible chat endpoint if configured.

The LLM is only asked to put decisions already made into words. It receives the scores and
profiles and is told not to change the order.
"""
from __future__ import annotations

import httpx

from . import domain as d

LEVEL_WORD = {"region": "region", "country": "country", "continent": "continent", "month": "month", "year": "year",
              "subsector": "subsector", "macrosector": "macrosector"}


def _cover(sol: dict) -> str:
    bits = []
    for key, prof in sol["profiles"].items():
        dim, lvl = key.split(".")
        mems = list(prof)
        if dim == "TIME" and mems:
            bits.append(f"{mems[0]} to {mems[-1]}" if len(mems) > 1 else mems[0])
        else:
            bits.append(d.plural(lvl, len(mems)))
    return ", ".join(bits)


class Explainer:
    def __init__(self, base_url: str | None = None, api_key: str | None = None, model: str | None = None, timeout: float = 30.0):
        self.base_url, self.api_key, self.model, self.timeout = base_url, api_key, model, timeout

    @property
    def llm_available(self) -> bool:
        return bool(self.base_url and self.model)

    def explain(self, request, preference, pollutants, levels, ranked, use_llm=False) -> dict:
        text = self.template(preference, pollutants, levels, ranked)
        if use_llm and self.llm_available:
            try:
                return {"by": f"LLM ({self.model})", "text": self._llm(request, preference, ranked, text)}
            except Exception as e:  # noqa: BLE001 - fall back to the template, but say why
                return {"by": "template", "text": text, "llm_error": f"{type(e).__name__}: {str(e)[:200]}"}
        return {"by": "template", "text": text}

    @staticmethod
    def template(preference, pollutants, levels, ranked) -> str:
        names = ", ".join(d.POLLUTANT[p].label for p in pollutants[:6]) + (f" and {len(pollutants) - 6} more" if len(pollutants) > 6 else "")
        by = " and ".join(LEVEL_WORD[v] for v in levels.values())
        lines = [f"{len(ranked)} solution{'s' if len(ranked) != 1 else ''} hold {names} by {by}."]
        for i, sol in enumerate(ranked):
            srcs = " + ".join(s["name"] for s in sol["sources"])
            line = f"{'First' if i == 0 else 'Then'}: {sol['id']}, {srcs}, covering {_cover(sol)}."
            if preference and "fit" in sol:
                f = sol["fit"]
                line += f" Preference fit {f['score']:.1f} of 3 ({f['confidence']:.0%} confident in its most likely level)."
            if sol["notes"]:
                line += " Caution: " + "; ".join(sol["notes"]) + "."
            lines.append(line)
            if i == 2 and len(ranked) > 3:
                lines.append(f"{len(ranked) - 3} more solution{'s' if len(ranked) - 3 != 1 else ''} rank lower.")
                break
        return "\n".join(lines)

    def _llm(self, request, preference, ranked, draft) -> str:
        facts = "\n".join(f"{s['id']}: {s['summary']}" + (f" Preference fit {s['fit']['score']:.2f} of 3." if 'fit' in s else "")
                          for s in ranked)
        prompt = (f"A user asked a dataset catalogue: {request!r}. Their preference: {preference or 'none given'}.\n"
                  f"The solutions below are already ranked, best first. Do not change the order or the numbers.\n{facts}\n\n"
                  "In under 120 words of plain British English, explain why the first solution ranks first and what the "
                  "user gives up with each alternative. No headings, no bullet points.")
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        r = httpx.post(self.base_url.rstrip("/") + "/chat/completions", headers=headers, timeout=self.timeout,
                       json={"model": self.model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.2})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
