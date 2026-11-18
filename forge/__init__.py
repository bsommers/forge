"""MCP Server Forge host pipeline package (MCP 2026-07-28)."""

from __future__ import annotations

__version__ = "1.2.0"

__all__ = [
    "__version__",
    "ProjectedField",
    "ResponseProjection",
    "SpecNormalizationError",
    "TamperDetectionError",
    "normalize_openapi_to_manifest",
    "project_response_schema",
]

from forge.ingest_openapi import SpecNormalizationError, normalize_openapi_to_manifest
from forge.orchestrator import TamperDetectionError
from forge.projection import ProjectedField, ResponseProjection, project_response_schema
