"""Settings, read once from environment variables. See .env.example."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _list(v: str | None, default: str) -> list[str]:
    return [x.strip() for x in (v if v is not None else default).split(",") if x.strip()]


def _bool(v: str | None, default: bool) -> bool:
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    backends: list[str]
    api_token: str | None
    allowed_origins: list[str]
    typesafe_api_key: str | None
    typesafe_base_url: str
    jev_model: str
    jev_price_per_mtok: float
    device: str
    laya_checkpoint: str
    anyjev_model: str
    anyjev_dtype: str
    anyjev_level: str
    preload: bool
    llm_base_url: str | None
    llm_api_key: str | None
    llm_model: str | None
    results_dir: str
    max_state_chars: int
    rate_limit_per_minute: int
    eval_enabled: bool
    calibration_dir: str
    min_confidence: float
    arize_space_id: str | None
    arize_api_key: str | None
    arize_project: str
    arize_endpoint: str
    jev_provider: str = "typesafe"
    openrouter_api_key: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        e = os.environ.get
        token = (e("API_TOKEN") or "").strip() or None
        typesafe_key = (e("TYPESAFE_API_KEY") or "").strip() or None
        openrouter_key = (e("OPENROUTER_API_KEY") or "").strip() or None
        # Jev through TypeSafe's own API, or through OpenRouter's Decisions API when only that key is set.
        provider = ((e("JEV_PROVIDER") or "").strip().lower()
                    or ("openrouter" if openrouter_key and not typesafe_key else "typesafe"))
        model = (e("JEV_MODEL") or "").strip()
        if provider == "openrouter":
            # A TypeSafe model name (the old .env.example set jev-latest) becomes OpenRouter's.
            model = "~typesafe/jev-latest" if model in ("", "jev-latest") else model if "/" in model else f"typesafe/{model}"
        return cls(
            backends=_list(e("BACKENDS"), "laya,laya-typed,anyjev,jev,catalogue,uniform"),
            api_token=token,
            allowed_origins=_list(e("ALLOWED_ORIGINS"), ""),
            typesafe_api_key=typesafe_key,
            typesafe_base_url=e("TYPESAFE_BASE_URL", "https://api.typesafe.ai"),
            jev_model=model or "jev-latest",
            jev_price_per_mtok=float(e("JEV_PRICE_PER_MTOK", "0.042")),
            device=e("DEVICE", "cpu"),
            laya_checkpoint=e("LAYA_CHECKPOINT", "english"),
            anyjev_model=e("ANYJEV_MODEL", "Qwen/Qwen3-1.7B"),
            anyjev_dtype=e("ANYJEV_DTYPE", "bfloat16"),
            anyjev_level=e("ANYJEV_LEVEL", "L0"),
            preload=_bool(e("PRELOAD"), False),
            llm_base_url=(e("LLM_BASE_URL") or "").strip() or None,
            llm_api_key=(e("LLM_API_KEY") or "").strip() or None,
            llm_model=(e("LLM_MODEL") or "").strip() or None,
            results_dir=e("RESULTS_DIR", "results"),
            max_state_chars=int(e("MAX_STATE_CHARS", "4000")),
            rate_limit_per_minute=int(e("RATE_LIMIT_PER_MINUTE", "120")),
            # Benchmark runs are long and, with Jev, cost money: only with a token unless forced on.
            eval_enabled=_bool(e("EVAL_ENABLED"), token is not None),
            calibration_dir=e("CALIBRATION_DIR", "calibration"),
            min_confidence=float(e("MIN_CONFIDENCE", "0.8")),
            arize_space_id=(e("ARIZE_SPACE_ID") or e("ARIZE_SPACE_KEY") or "").strip() or None,
            arize_api_key=(e("ARIZE_API_KEY") or "").strip() or None,
            arize_project=(e("ARIZE_PROJECT_NAME") or e("ARIZE_PROJECT") or "graphrag-compliance").strip(),
            arize_endpoint=e("ARIZE_OTLP_ENDPOINT", "https://otlp.arize.com/v1/traces"),
            jev_provider=provider,
            openrouter_api_key=openrouter_key,
        )
