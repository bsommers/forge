from __future__ import annotations

from typing import Annotated

from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from src.deps import ApiClient, request_json

VALID_SEVERITIES: frozenset[str] = frozenset({"sev1", "sev2", "sev3", "sev4"})


class CreatedIncidentResult(BaseModel):
    """Concise representation of a newly created operational incident."""

    id: str = Field(description="Unique identifier assigned to the new incident.")
    title: str = Field(description="Short human-readable summary of the incident.")
    severity: str = Field(description="Validated severity tier (sev1-sev4).")
    status: str = Field(description="Initial incident lifecycle status.")
    created_at: str | None = Field(
        default=None, description="ISO-8601 timestamp when the incident was created."
    )


def _opt_str(value: object) -> str | None:
    return str(value) if value is not None else None


@tool(
    name="create_incident",
    title="Create Operational Incident",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=True,
    ),
)
async def create_incident(
    title: Annotated[
        str,
        Field(
            min_length=3,
            max_length=200,
            description="Short human-readable summary of the incident.",
        ),
    ],
    severity: Annotated[
        str,
        Field(description="Severity tier: sev1, sev2, sev3, or sev4."),
    ],
    client: ApiClient,
    service: Annotated[
        str | None,
        Field(
            default=None,
            max_length=120,
            description="Optional affected service or component name.",
        ),
    ] = None,
    summary: Annotated[
        str | None,
        Field(
            default=None,
            max_length=2000,
            description="Optional detailed description of impact and symptoms.",
        ),
    ] = None,
    idempotency_key: Annotated[
        str,
        Field(
            default="",
            max_length=128,
            description="Optional client idempotency key.",
            json_schema_extra={"x-mcp-header": "Idempotency-Key"},
        ),
    ] = "",
) -> CreatedIncidentResult:
    """Create a new operational incident with a validated severity tier."""
    normalized_severity = severity.strip().lower()
    if normalized_severity not in VALID_SEVERITIES:
        raise ToolError(
            f"Invalid severity '{severity}'. Must be one of: sev1, sev2, sev3, sev4."
        )

    cleaned_title = title.strip()
    if len(cleaned_title) < 3:
        raise ToolError("Incident title must contain at least 3 non-whitespace characters.")

    body: dict[str, str] = {
        "title": cleaned_title,
        "severity": normalized_severity,
    }
    if service is not None:
        body["service"] = service
    if summary is not None:
        body["summary"] = summary
    if idempotency_key:
        body["idempotency_key"] = idempotency_key

    data = await request_json(client, "POST", "/incidents", json_body=body)
    if not isinstance(data, dict):
        raise ToolError("Unexpected upstream response format when creating incident.")

    return CreatedIncidentResult(
        id=str(data.get("id", "")),
        title=str(data.get("title", cleaned_title)),
        severity=str(data.get("severity", normalized_severity)),
        status=str(data.get("status", "investigating")),
        created_at=_opt_str(data.get("created_at")),
    )
