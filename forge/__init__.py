"""MCP Server Forge host pipeline package (MCP 2026-07-28)."""

from __future__ import annotations

__version__ = "1.3.0"

__all__ = [
    "__version__",
    "ProjectedField",
    "ResponseProjection",
    "SpecNormalizationError",
    "TamperDetectionError",
    "normalize_openapi_to_manifest",
    "plan_openapi_shards",
    "project_response_schema",
    "run_sharded_forge_pipeline",
]

from forge.ingest_openapi import (
    SpecNormalizationError,
    normalize_openapi_to_manifest,
    plan_openapi_shards,
)
from forge.orchestrator import TamperDetectionError, run_sharded_forge_pipeline
from forge.projection import ProjectedField, ResponseProjection, project_response_schema
