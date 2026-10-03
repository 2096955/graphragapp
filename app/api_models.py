"""Pydantic request models for the HTTP API.

Keeping transport schemas out of app.main makes the API surface easy to review and
keeps business logic importable without pulling route declarations into tests.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DecideIn(BaseModel):
    backend: str
    state: Any
    questions: dict[str, dict]


class CompareIn(BaseModel):
    backends: list[str] = Field(min_length=1, max_length=4)
    state: Any
    questions: dict[str, dict]


class PipelineIn(BaseModel):
    backend: str
    request: str = Field(min_length=1, max_length=500)
    preference: str | None = Field(default=None, max_length=300)
    use_llm: bool = False


class EvalIn(BaseModel):
    backend: str
    tasks: list[str] | None = None
    limit: int = Field(default=0, ge=0, le=500)


class ComplianceFilterIn(BaseModel):
    backend: str = "catalogue"
    payload: str = Field(min_length=1, max_length=2000)


class ComplianceExampleIn(BaseModel):
    backend: str = "catalogue"
