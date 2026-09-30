"""Backends: TypeSafe Jev (hosted), Laya and AnyJev (local), and a uniform baseline."""
from __future__ import annotations

import json
import math
import threading
import time
from typing import Any

import httpx

from .base import Backend, DecisionError, TransientError, from_wire


def _clean(q: dict) -> dict:
    """Question in Jev's wire format, without empty fields."""
    out = {"type": q["type"]}
    if q.get("instructions"):
        out["instructions"] = q["instructions"]
    if q.get("criteria") is not None:
        out["criteria"] = q["criteria"]
    return out


# Jev is served by TypeSafe's own API and by OpenRouter's Decisions API, with the same request and
# answers. Ten levels of Jev (github.com/disler/ten-levels-of-jev) reaches it both ways.
JEV_ENDPOINTS = {"typesafe": "/v1/systemone", "openrouter": "https://openrouter.ai/api/alpha/decisions"}
JEV_DEFAULT_MODELS = {"typesafe": "jev-latest", "openrouter": "~typesafe/jev-latest"}
JEV_KEY_ENV = {"typesafe": "TYPESAFE_API_KEY", "openrouter": "OPENROUTER_API_KEY"}
RETRY_STATUSES = (429, 500, 502, 503, 504, 529)


def _reported_cost(usage: dict) -> float | None:
    """The provider's own cost, when it sends one that is a finite, non-negative number."""
    cost = usage.get("cost")
    if isinstance(cost, bool) or not isinstance(cost, (int, float)) or not math.isfinite(cost) or cost < 0:
        return None
    return float(cost)


class JevBackend(Backend):
    name = "jev"
    label = "TypeSafe Jev"
    residency = "hosted"
    description = "Hosted System One model. The state is sent to TypeSafe's API."

    def __init__(self, api_key: str | None, base_url: str = "https://api.typesafe.ai", model: str | None = None,
                 price_per_mtok: float = 0.042, timeout: float = 15.0, transport: httpx.BaseTransport | None = None,
                 provider: str = "typesafe"):
        if provider not in JEV_ENDPOINTS:
            raise ValueError(f"Unknown Jev provider {provider!r}; use typesafe or openrouter")
        super().__init__(model or JEV_DEFAULT_MODELS[provider])
        self.provider = provider
        self._key = (api_key or "").strip()
        self.price_per_mtok = price_per_mtok
        self._url = base_url.rstrip("/") + JEV_ENDPOINTS[provider] if provider == "typesafe" else JEV_ENDPOINTS[provider]
        self._client = httpx.Client(timeout=timeout, transport=transport, follow_redirects=False)
        if provider == "openrouter":
            self.description = "TypeSafe's Jev through OpenRouter's Decisions API. The state is sent to OpenRouter."

    def available(self):
        return (True, "") if self._key else (False, f"Set {JEV_KEY_ENV[self.provider]} on the server to enable Jev.")

    def _decide(self, state, questions):
        body = {"state": state, "model": self.model, "questions": {n: _clean(q) for n, q in questions.items()}}
        headers = {"Authorization": f"Bearer {self._key}"}
        resp = None
        for attempt in range(3):
            try:
                resp = self._client.post(self._url, json=body, headers=headers)
            except httpx.HTTPError as e:
                if attempt == 2:
                    raise TransientError(f"Could not reach the Jev API: {type(e).__name__}") from None
                time.sleep(0.5 * (attempt + 1))
                continue
            if resp.status_code in RETRY_STATUSES and attempt < 2:
                time.sleep(_retry_after(resp.headers.get("retry-after"), 0.5 * (attempt + 1)))
                continue
            break
        if resp.status_code in RETRY_STATUSES:
            raise TransientError(f"Jev returned HTTP {resp.status_code} after retries")
        if resp.status_code >= 400:
            hint = {401: f" Check {JEV_KEY_ENV[self.provider]}.", 402: " Check the account's credits."}.get(resp.status_code, "")
            raise DecisionError(f"Jev returned HTTP {resp.status_code}.{hint} {resp.text[:300]}".rstrip())
        data = resp.json()
        answers = {n: from_wire(questions[n], data["answers"][n]) for n in questions if n in data.get("answers", {})}
        usage = data.get("usage") or {}
        tokens = int(usage.get("input_tokens") or 0)
        reported = _reported_cost(usage)
        cost = reported if reported is not None else tokens * self.price_per_mtok / 1e6
        return answers, tokens, cost, {"served_by": data.get("model"), "via": self.provider,
                                       "cost_source": "reported" if reported is not None else "estimated"}


def _retry_after(header: str | None, default: float) -> float:
    """Seconds from a Retry-After header, capped at 8; the default when it is missing or not a number."""
    try:
        return min(8.0, max(0.0, float(header))) if header else default
    except ValueError:
        return default


class LayaBackend(Backend):
    name = "laya"
    label = "Laya"
    residency = "local"
    description = "Open 421M-parameter decision model (Apache 2.0). Runs on CPU or GPU where the backend runs."

    def __init__(self, checkpoint: str = "english", device: str = "cpu", max_len: int | None = None,
                 name: str | None = None, label: str | None = None):
        # "english" is Laya's own default. "typed-decisions" is fine-tuned on four unrelated workflows
        # (invoice, security, customer service, agent traces); Laya advises against using it silently.
        super().__init__(f"convaiinnovations/laya ({checkpoint})")
        self.checkpoint, self.device, self.max_len = checkpoint, device, max_len
        if name:
            self.name = name
        if label:
            self.label = label
        self._router = None
        self._lock = threading.Lock()

    def available(self):
        try:
            from laya.agent import Agent  # noqa: F401 - check inference dependencies, not just the lazy router
            return True, ""
        except ImportError:
            return False, "Laya inference dependencies are missing (pip install -r requirements-local.txt)."

    def loaded(self):
        return self._router is not None

    def warm_up(self):
        with self._lock:
            self._ensure()
            self._router.predict({"x": "warm up"}, {"q": {"type": "noul", "instructions": "Is this a test?"}}, model=self.checkpoint)

    def _ensure(self):
        if self._router is None:
            from laya import Router
            self._router = Router(device=self.device)

    def _decide(self, state, questions):
        with self._lock:
            self._ensure()
            out = self._router.predict(state, {n: _clean(q) for n, q in questions.items()}, model=self.checkpoint,
                                       max_len=self.max_len)
        answers = {n: from_wire(questions[n], out["answers"][n]) for n in questions if n in out.get("answers", {})}
        usage = out.get("usage", {})
        detail = {"checkpoint": out.get("routing", {}).get("model"), "truncated": bool(usage.get("truncated"))}
        return answers, usage.get("input_tokens"), 0.0, detail


class AnyJevBackend(Backend):
    name = "anyjev"
    label = "AnyJev"
    residency = "local"
    description = "Nokia's training-free layer over an open LLM (Apache 2.0). Reads calibrated probabilities from next-token logits."

    def __init__(self, model: str = "Qwen/Qwen3-1.7B", device: str = "cpu", dtype: str = "bfloat16", level: str = "L0"):
        if level not in ("raw", "L0"):
            raise ValueError("ANYJEV_LEVEL must be raw or L0. Use CALIBRATION_DIR for frozen serving calibration.")
        super().__init__(f"{model} ({level})")
        self.hf_model, self.device, self.dtype, self.level = model, device, dtype, level
        self._decider = None
        self._questions: dict[str, Any] = {}
        self._lock = threading.Lock()

    def available(self):
        try:
            import anyjev  # noqa: F401
            import torch  # noqa: F401
            import transformers  # noqa: F401
            return True, ""
        except ImportError:
            return False, "AnyJev is not installed on the server (pip install -r requirements-local.txt)."

    def loaded(self):
        return self._decider is not None

    def warm_up(self):
        with self._lock:
            self._ensure()

    def fork_for_benchmark(self):
        from anyjev import Decider
        with self._lock:
            self._ensure()
            clone = AnyJevBackend(self.hf_model, self.device, self.dtype, self.level)
            clone._decider = Decider(self._decider.backend, level=self.level)
            clone._lock = self._lock
        return clone

    def _ensure(self):
        if self._decider is None:
            from anyjev import Decider
            from anyjev.backends.hf import HFBackend
            self._decider = Decider(HFBackend(self.hf_model, device=self.device, dtype=self.dtype), level=self.level)

    def _question(self, name: str, q: dict):
        """AnyJev question for a wire-format question. Cached, so its running label prior persists."""
        from anyjev import Question
        key = name + "|" + json.dumps(_clean(q), sort_keys=True)
        if key not in self._questions:
            text = q.get("instructions") or ""
            crit = q.get("criteria")
            if q["type"] == "noul":
                if crit:
                    extra = []
                    if crit.get("true"):
                        extra.append(f"Answer Yes if: {crit['true']}")
                    if crit.get("false"):
                        extra.append(f"Answer No if: {crit['false']}")
                    text = " ".join([text] + extra)
                self._questions[key] = Question.noul(text, name=name)
            elif q["type"] == "choice":
                options = [f"{k}: {v}" if v else k for k, v in crit.items()]
                self._questions[key] = Question.choice(text, options, name=name)
            else:
                self._questions[key] = Question.score(text, levels=crit, name=name)
        return self._questions[key]

    def _decide(self, state, questions):
        with self._lock:
            self._ensure()
            qs = [self._question(n, q) for n, q in questions.items()]
            ds = self._decider.decide(state, qs)
        answers = {}
        for (name, q), aq in zip(questions.items(), qs):
            probs = list(ds[aq.id].probs)
            if q["type"] == "noul":
                answers[name] = {"yes": probs[0], "no": probs[1]}      # AnyJev noul options are (Yes, No)
            elif q["type"] == "choice":
                answers[name] = dict(zip(q["criteria"].keys(), probs))
            else:
                answers[name] = {str(i): p for i, p in enumerate(probs)}
        return answers, None, 0.0, {"level": ds.level}


class CatalogueBackend(Backend):
    name = "catalogue"
    label = "Catalogue rules"
    description = "Exact catalogue terms and explicit preferences; no weights, no API calls."

    def __init__(self):
        super().__init__("catalogue-rules-v1")

    def _decide(self, state, questions):
        from .. import domain as d
        from ..request import preference_score, resolve
        from .base import labels
        parsed = resolve(state.get("request", ""))
        answers = {}
        for name, q in questions.items():
            if name == "gate":
                gold = parsed["gate"]
            elif name in d.DIMENSIONS:
                gold = parsed["levels"].get(name, "none")
            elif name.startswith("group:"):
                gold = "yes" if name.split(":", 1)[1] in parsed["groups"] else "no"
            elif name.startswith("pollutant:"):
                gold = "yes" if name.split(":", 1)[1] in parsed["pollutants"] else "no"
            elif name == "relevant":
                gold = "yes" if any(p in parsed["pollutants"] and d.POLLUTANT[p].describe in q["instructions"] for p in d.POLLUTANT) else "no"
            elif name == "fit" and "solution" in state:
                score = preference_score(state["preference"], state["solution"])
                if score is None:
                    answers[name] = {k: 1 / len(labels(q)) for k in labels(q)}
                    continue
                gold = str(score)
            else:
                raise DecisionError("Catalogue rules support pipeline extraction and explicit preferences only.")
            answers[name] = {k: float(k == gold) for k in labels(q)}
        return answers, None, 0.0, {"by": "catalogue rules", "calibration": "not a model probability"}


class UniformBackend(Backend):
    name = "uniform"
    label = "Uniform baseline"
    residency = "local"
    description = "Equal probability for every option. The floor any model has to beat."

    def __init__(self):
        super().__init__("none")

    def _decide(self, state, questions):
        from .base import labels
        return {n: {lab: 1.0 / len(labels(q)) for lab in labels(q)} for n, q in questions.items()}, None, 0.0, {}
