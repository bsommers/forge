from __future__ import annotations

from typing import Annotated

from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from src.deps import ApiClient, request_json


class DeleteIncidentResult(BaseModel):
    """Confirmation payload returned after deleting an operational incident."""

    id: str = Field(description="Unique identifier of the deleted incident.")
    deleted: bool = Field(description="Whether the incident was deleted upstream.")
    message: str = Field(description="Human-readable deletion confirmation message.")


@tool(
    name="delete_incident",
    title="Delete Operational Incident",
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=True,
        open_world_hint=True,
    ),
)
async def delete_incident(
    incident_id: Annotated[
        str,
        Field(
            min_length=1,
            max_length=64,
            pattern=r"^[A-Za-z0-9_-]+$",
            description="Unique identifier of the incident to permanently delete.",
        ),
    ],
    client: ApiClient,
) -> DeleteIncidentResult:
    """Permanently delete an operational incident record by ID."""
    data = await request_json(client, "DELETE", f"/incidents/{incident_id}")
    if not isinstance(data, dict):
        raise ToolError("Unexpected upstream response format when deleting incident.")

    return DeleteIncidentResult(
        id=str(data.get("id", incident_id)),
        deleted=bool(data.get("deleted", True)),
        message=str(data.get("message", f"Incident {incident_id} deleted.")),
    )
