from __future__ import annotations

from typing import Annotated

from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from src.deps import ApiClient, request_json


class IncidentSummaryItem(BaseModel):
    """Concise summary item for an operational incident in a list response."""

    id: str = Field(description="Unique incident identifier.")
    title: str = Field(description="Short human-readable summary of the incident.")
    severity: str = Field(description="Severity tier (e.g., sev1, sev2, sev3, sev4).")
    status: str = Field(
        description="Lifecycle state (investigating, identified, monitoring, resolved)."
    )
    updated_at: str | None = Field(default=None, description="ISO-8601 timestamp of last update.")


class IncidentListResponse(BaseModel):
    """Paginated list of operational incident summaries."""

    incidents: list[IncidentSummaryItem] = Field(description="Matching operational incidents.")
    next_cursor: str | None = Field(
        default=None, description="Opaque cursor to retrieve the next page of results."
    )
    total_returned: int = Field(description="Count of incident records returned in this response.")


def _opt_str(value: object) -> str | None:
    return str(value) if value is not None else None


@tool(
    name="list_incidents",
    title="List Operational Incidents",
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    ),
)
async def list_incidents(
    client: ApiClient,
    status: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Optional lifecycle status filter "
                "(e.g., investigating, identified, monitoring, resolved)."
            ),
        ),
    ] = None,
    severity: Annotated[
        str | None,
        Field(
            default=None,
            description="Optional severity tier filter (e.g., sev1, sev2, sev3, sev4).",
        ),
    ] = None,
    limit: Annotated[
        int,
        Field(
            default=25,
            ge=1,
            le=100,
            description="Maximum number of incidents to return (1-100).",
        ),
    ] = 25,
    cursor: Annotated[
        str | None,
        Field(
            default=None,
            max_length=256,
            description="Opaque pagination cursor returned by a previous list call.",
        ),
    ] = None,
) -> IncidentListResponse:
    """List operational incidents with optional status, severity, limit, and cursor filters."""
    payload = await request_json(
        client,
        "GET",
        "/incidents",
        params={
            "status": status,
            "severity": severity,
            "limit": limit,
            "cursor": cursor,
        },
    )

    if isinstance(payload, list):
        raw_items = payload
        next_cursor: str | None = None
    elif isinstance(payload, dict):
        raw_items_val = payload.get("incidents", payload.get("items", []))
        if not isinstance(raw_items_val, list):
            raise ToolError("Unexpected upstream response: 'incidents' field must be a list.")
        raw_items = raw_items_val
        next_cursor = _opt_str(payload.get("next_cursor"))
    else:
        raise ToolError("Unexpected upstream response format when listing incidents.")

    incidents = [
        IncidentSummaryItem(
            id=str(item.get("id", "")),
            title=str(item.get("title", "Untitled")),
            severity=str(item.get("severity", "unknown")),
            status=str(item.get("status", "unknown")),
            updated_at=_opt_str(item.get("updated_at")),
        )
        for item in raw_items[:limit]
        if isinstance(item, dict)
    ]

    return IncidentListResponse(
        incidents=incidents,
        next_cursor=next_cursor,
        total_returned=len(incidents),
    )
