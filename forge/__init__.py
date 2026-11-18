"""MCP Server Forge host pipeline package (MCP 2026-07-28)."""

from __future__ import annotations

__version__ = "1.0.0"

__all__ = [
    "__version__",
    "SpecNormalizationError",
    "normalize_openapi_to_manifest",
]

from forge.ingest_openapi import SpecNormalizationError, normalize_openapi_to_manifest
