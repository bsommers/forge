from __future__ import annotations

from typing import Annotated

from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from src.deps import ApiClient, request_json


class IncidentSummary(BaseModel):
    """Concise, context-safe representation of an operational incident."""

    id: str = Field(description="Unique incident identifier.")
    title: str = Field(description="Short human-readable summary of the incident.")
    severity: str = Field(description="Severity tier (e.g., sev1, sev2, sev3, sev4).")
    status: str = Field(
        description="Lifecycle state (investigating, identified, monitoring, resolved)."
    )
    commander: str | None = Field(default=None, description="Assigned incident commander name.")
    updated_at: str | None = Field(default=None, description="ISO-8601 timestamp of last update.")


def _opt_str(value: object) -> str | None:
    return str(value) if value is not None else None


@tool(
    name="get_incident",
    title="Get Incident Summary",
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    ),
)
async def get_incident(
    incident_id: Annotated[
        str,
        Field(
            min_length=1,
            max_length=64,
            pattern=r"^[A-Za-z0-9_-]+$",
            description="Unique identifier of the incident (e.g., 'INC-1042').",
        ),
    ],
    client: ApiClient,
) -> IncidentSummary:
    """Fetch concise details and current operational status for a single incident by ID."""
    data = await request_json(client, "GET", f"/incidents/{incident_id}")
    if not isinstance(data, dict):
        raise ToolError("Unexpected upstream response format when fetching incident.")

    commander_obj = data.get("commander")
    if isinstance(commander_obj, dict):
        commander_name = _opt_str(commander_obj.get("name"))
    else:
        commander_name = _opt_str(commander_obj)

    return IncidentSummary(
        id=str(data.get("id", incident_id)),
        title=str(data.get("title", "Untitled")),
        severity=str(data.get("severity", "unknown")),
        status=str(data.get("status", "unknown")),
        commander=commander_name,
        updated_at=_opt_str(data.get("updated_at")),
    )
