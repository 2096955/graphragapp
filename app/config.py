"""Settings, read once from environment variables. See .env.example."""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass


def _list(v: str | None, default: str) -> list[str]:
    return [x.strip() for x in (v if v is not None else default).split(",") if x.strip()]


def _bool(v: str | None, default: bool) -> bool:
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    environment: str
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
    enable_docs: bool
    enable_demo_endpoints: bool
    allow_hosted_compliance: bool
    compliance_hash_key: str
    compliance_hash_key_ephemeral: bool
    compliance_db_path: str | None
    calibration_dir: str
    min_confidence: float
    arize_space_id: str | None
    arize_api_key: str | None
    arize_project: str
    arize_endpoint: str

    @property
    def production(self) -> bool:
        return self.environment == "production"

    @classmethod
    def from_env(cls) -> "Settings":
        e = os.environ.get
        environment = (e("APP_ENV", "development") or "development").strip().lower()
        if environment not in {"development", "test", "production"}:
            raise RuntimeError("APP_ENV must be development, test, or production.")

        production = environment == "production"
        token = (e("API_TOKEN") or "").strip() or None
        configured_hash_key = (e("COMPLIANCE_HASH_KEY") or "").strip() or None

        if production and token is None:
            raise RuntimeError("API_TOKEN is required when APP_ENV=production.")
        if production and (configured_hash_key is None or len(configured_hash_key) < 32):
            raise RuntimeError(
                "COMPLIANCE_HASH_KEY must be set to a random value of at least 32 characters "
                "when APP_ENV=production."
            )

        hash_key = configured_hash_key or secrets.token_urlsafe(32)
        compliance_path = (e("COMPLIANCE_DB_PATH") or "").strip() or (
            "data/compliance.kuzu" if production else None
        )

        return cls(
            environment=environment,
            backends=_list(e("BACKENDS"), "catalogue,laya,anyjev,jev,uniform"),
            api_token=token,
            allowed_origins=_list(e("ALLOWED_ORIGINS"), ""),
            typesafe_api_key=(e("TYPESAFE_API_KEY") or "").strip() or None,
            typesafe_base_url=e("TYPESAFE_BASE_URL", "https://api.typesafe.ai"),
            jev_model=e("JEV_MODEL", "jev-latest"),
            jev_price_per_mtok=float(e("JEV_PRICE_PER_MTOK", "0.042")),
            device=e("DEVICE", "cpu"),
            laya_checkpoint=e("LAYA_CHECKPOINT", "typed-decisions"),
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
            # Benchmark runs mutate result files and can spend hosted-model budget.
            # They are opt-in in every environment, including when an API token is set.
            eval_enabled=_bool(e("EVAL_ENABLED"), False),
            enable_docs=_bool(e("ENABLE_DOCS"), not production),
            enable_demo_endpoints=_bool(e("ENABLE_DEMO_ENDPOINTS"), not production),
            allow_hosted_compliance=_bool(e("ALLOW_HOSTED_COMPLIANCE"), False),
            compliance_hash_key=hash_key,
            compliance_hash_key_ephemeral=configured_hash_key is None,
            compliance_db_path=compliance_path,
            calibration_dir=e("CALIBRATION_DIR", "calibration"),
            min_confidence=float(e("MIN_CONFIDENCE", "0.8")),
            arize_space_id=(e("ARIZE_SPACE_ID") or e("ARIZE_SPACE_KEY") or "").strip() or None,
            arize_api_key=(e("ARIZE_API_KEY") or "").strip() or None,
            arize_project=(e("ARIZE_PROJECT_NAME") or e("ARIZE_PROJECT") or "graphrag-compliance").strip(),
            arize_endpoint=e("ARIZE_OTLP_ENDPOINT", "https://otlp.arize.com/v1/traces"),
        )
