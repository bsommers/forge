from __future__ import annotations

from typing import Annotated

from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from src.deps import ApiClient, request_json

VALID_STATUSES: frozenset[str] = frozenset(
    {"investigating", "identified", "monitoring", "resolved"}
)


class IncidentStatusUpdateResult(BaseModel):
    """Result returned after updating an operational incident status."""

    id: str = Field(description="Unique identifier of the updated incident.")
    status: str = Field(description="Updated lifecycle status.")
    note: str | None = Field(default=None, description="Optional timeline update note.")
    updated_at: str | None = Field(
        default=None, description="ISO-8601 timestamp of the status update."
    )


def _opt_str(value: object) -> str | None:
    return str(value) if value is not None else None


@tool(
    name="update_incident_status",
    title="Update Incident Status",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    ),
)
async def update_incident_status(
    incident_id: Annotated[
        str,
        Field(
            min_length=1,
            max_length=64,
            pattern=r"^[A-Za-z0-9_-]+$",
            description="Unique identifier of the incident to update.",
        ),
    ],
    status: Annotated[
        str,
        Field(
            description=(
                "Target lifecycle status: investigating, identified, monitoring, or resolved."
            )
        ),
    ],
    client: ApiClient,
    note: Annotated[
        str | None,
        Field(
            default=None,
            max_length=500,
            description="Optional status update note for the incident timeline.",
        ),
    ] = None,
) -> IncidentStatusUpdateResult:
    """Update the lifecycle status of an existing operational incident."""
    normalized_status = status.strip().lower()
    if normalized_status not in VALID_STATUSES:
        raise ToolError(
            f"Invalid status '{status}'. "
            "Must be one of: investigating, identified, monitoring, resolved."
        )

    body: dict[str, str] = {"status": normalized_status}
    if note is not None:
        body["note"] = note

    data = await request_json(
        client,
        "PUT",
        f"/incidents/{incident_id}/status",
        json_body=body,
    )
    if not isinstance(data, dict):
        raise ToolError("Unexpected upstream response format when updating incident status.")

    return IncidentStatusUpdateResult(
        id=str(data.get("id", incident_id)),
        status=str(data.get("status", normalized_status)),
        note=_opt_str(data.get("note", note)),
        updated_at=_opt_str(data.get("updated_at")),
    )
