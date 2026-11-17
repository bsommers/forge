from __future__ import annotations

import json

import httpx
import pytest
import respx
from fastmcp import Client
from fastmcp.exceptions import ToolError

from src.server import mcp


@pytest.fixture(autouse=True)
def _mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACME_BASE_URL", "https://api.test.internal/v1")
    monkeypatch.setenv("ACME_API_TOKEN", "unit-test-bearer-val")


@respx.mock
async def test_get_incident_happy_path_dict_and_string_commander() -> None:
    route = respx.get("https://api.test.internal/v1/incidents/INC-101").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "INC-101",
                "title": "Checkout latency spike",
                "severity": "sev1",
                "status": "investigating",
                "commander": {"name": "Alice Chen", "email": "alice@acme.internal"},
                "updated_at": "2026-11-17T01:00:00Z",
                "raw_stack_trace": "ignored-large-payload",
            },
        )
    )

    async with Client(mcp) as client:
        result = await client.call_tool("get_incident", {"incident_id": "INC-101"})

    assert route.called
    assert result.is_error is False
    assert result.structured_content == {
        "id": "INC-101",
        "title": "Checkout latency spike",
        "severity": "sev1",
        "status": "investigating",
        "commander": "Alice Chen",
        "updated_at": "2026-11-17T01:00:00Z",
    }

    respx.get("https://api.test.internal/v1/incidents/INC-102").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "INC-102",
                "title": "Cache miss storm",
                "severity": "sev2",
                "status": "monitoring",
                "commander": "Bob",
            },
        )
    )

    async with Client(mcp) as client:
        result2 = await client.call_tool("get_incident", {"incident_id": "INC-102"})

    assert result2.structured_content is not None
    assert result2.structured_content["commander"] == "Bob"
    assert result2.structured_content["updated_at"] is None


@respx.mock
async def test_get_incident_unexpected_shape_and_http_errors() -> None:
    respx.get("https://api.test.internal/v1/incidents/INC-BAD").mock(
        return_value=httpx.Response(200, json=["not-a-dict"])
    )
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="Unexpected upstream response format"):
            await client.call_tool("get_incident", {"incident_id": "INC-BAD"})

    for status_code in (401, 403, 404, 429, 500):
        headers = {"Retry-After": "12"} if status_code == 429 else {}
        respx.get("https://api.test.internal/v1/incidents/INC-ERR").mock(
            return_value=httpx.Response(status_code, headers=headers, text="upstream failure")
        )
        async with Client(mcp) as client:
            with pytest.raises(ToolError):
                await client.call_tool("get_incident", {"incident_id": "INC-ERR"})


@respx.mock
async def test_get_incident_network_exceptions() -> None:
    respx.get("https://api.test.internal/v1/incidents/INC-TIMEOUT").mock(
        side_effect=httpx.TimeoutException("timed out")
    )
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="timed out"):
            await client.call_tool("get_incident", {"incident_id": "INC-TIMEOUT"})

    respx.get("https://api.test.internal/v1/incidents/INC-CONN").mock(
        side_effect=httpx.ConnectError("connection refused")
    )
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="network error"):
            await client.call_tool("get_incident", {"incident_id": "INC-CONN"})


@respx.mock
async def test_list_incidents_dict_and_raw_list_payloads() -> None:
    route_dict = respx.get("https://api.test.internal/v1/incidents").mock(
        return_value=httpx.Response(
            200,
            json={
                "incidents": [
                    {
                        "id": "INC-1",
                        "title": "API 502s",
                        "severity": "sev1",
                        "status": "investigating",
                        "updated_at": "2026-11-17T00:10:00Z",
                    }
                ],
                "next_cursor": "cursor-page-2",
            },
        )
    )

    async with Client(mcp) as client:
        res = await client.call_tool(
            "list_incidents",
            {
                "status": "investigating",
                "severity": "sev1",
                "limit": 10,
                "cursor": "cursor-page-1",
            },
        )

    assert route_dict.called
    req = route_dict.calls.last.request
    assert req.url.params["status"] == "investigating"
    assert req.url.params["severity"] == "sev1"
    assert req.url.params["limit"] == "10"
    assert req.url.params["cursor"] == "cursor-page-1"
    assert res.structured_content == {
        "incidents": [
            {
                "id": "INC-1",
                "title": "API 502s",
                "severity": "sev1",
                "status": "investigating",
                "updated_at": "2026-11-17T00:10:00Z",
            }
        ],
        "next_cursor": "cursor-page-2",
        "total_returned": 1,
    }

    respx.get("https://api.test.internal/v1/incidents").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": "INC-2", "title": "Queue lag", "severity": "sev3", "status": "monitoring"},
                "ignore-non-dict",
                {"id": "INC-3", "title": "Disk full", "severity": "sev2", "status": "resolved"},
            ],
        )
    )

    async with Client(mcp) as client:
        res_list = await client.call_tool("list_incidents", {})

    assert res_list.structured_content is not None
    assert res_list.structured_content["total_returned"] == 2
    assert res_list.structured_content["next_cursor"] is None


@respx.mock
async def test_list_incidents_error_branches() -> None:
    respx.get("https://api.test.internal/v1/incidents").mock(
        return_value=httpx.Response(200, json={"incidents": "invalid"})
    )
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="must be a list"):
            await client.call_tool("list_incidents", {})

    respx.get("https://api.test.internal/v1/incidents").mock(
        return_value=httpx.Response(200, json="unexpected-scalar")
    )
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="Unexpected upstream response format"):
            await client.call_tool("list_incidents", {})

    respx.get("https://api.test.internal/v1/incidents").mock(
        return_value=httpx.Response(500, text="internal error")
    )
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="HTTP 500"):
            await client.call_tool("list_incidents", {})


@respx.mock
async def test_create_incident_happy_paths_and_validation() -> None:
    post_route = respx.post("https://api.test.internal/v1/incidents").mock(
        return_value=httpx.Response(
            201,
            json={
                "id": "INC-200",
                "title": "Primary DB failover",
                "severity": "sev1",
                "status": "investigating",
                "created_at": "2026-11-17T02:00:00Z",
            },
        )
    )

    async with Client(mcp) as client:
        res = await client.call_tool(
            "create_incident",
            {
                "title": "Primary DB failover",
                "severity": " SEV1 ",
                "service": "postgres-core",
                "summary": "Write latency exceeded 5s.",
                "idempotency_key": "idem-12345",
            },
        )

    assert post_route.called
    sent_body = json.loads(post_route.calls.last.request.content.decode("utf-8"))
    assert sent_body == {
        "title": "Primary DB failover",
        "severity": "sev1",
        "service": "postgres-core",
        "summary": "Write latency exceeded 5s.",
        "idempotency_key": "idem-12345",
    }
    assert res.structured_content == {
        "id": "INC-200",
        "title": "Primary DB failover",
        "severity": "sev1",
        "status": "investigating",
        "created_at": "2026-11-17T02:00:00Z",
    }

    # Minimal parameters without optional fields
    async with Client(mcp) as client:
        res_min = await client.call_tool(
            "create_incident",
            {"title": "Minor alert", "severity": "sev4"},
        )
    assert res_min.is_error is False
    sent_min = json.loads(post_route.calls.last.request.content.decode("utf-8"))
    assert sent_min == {"title": "Minor alert", "severity": "sev4"}


@respx.mock
async def test_create_incident_validation_and_upstream_errors() -> None:
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="Invalid severity"):
            await client.call_tool(
                "create_incident", {"title": "Bad severity", "severity": "critical"}
            )

        with pytest.raises(ToolError, match="at least 3 non-whitespace"):
            await client.call_tool("create_incident", {"title": "   ", "severity": "sev2"})

    respx.post("https://api.test.internal/v1/incidents").mock(
        return_value=httpx.Response(200, json=["not-a-dict"])
    )
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="Unexpected upstream response format"):
            await client.call_tool(
                "create_incident", {"title": "Valid title", "severity": "sev2"}
            )

    respx.post("https://api.test.internal/v1/incidents").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "30"}, text="rate limited")
    )
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="429"):
            await client.call_tool(
                "create_incident", {"title": "Valid title", "severity": "sev2"}
            )


@respx.mock
async def test_update_incident_status_happy_and_error_paths() -> None:
    put_route = respx.put("https://api.test.internal/v1/incidents/INC-300/status").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "INC-300",
                "status": "monitoring",
                "note": "Traffic shifted to replica.",
                "updated_at": "2026-11-17T02:15:00Z",
            },
        )
    )

    async with Client(mcp) as client:
        res = await client.call_tool(
            "update_incident_status",
            {
                "incident_id": "INC-300",
                "status": " Monitoring ",
                "note": "Traffic shifted to replica.",
            },
        )

    assert put_route.called
    assert json.loads(put_route.calls.last.request.content.decode("utf-8")) == {
        "status": "monitoring",
        "note": "Traffic shifted to replica.",
    }
    assert res.structured_content == {
        "id": "INC-300",
        "status": "monitoring",
        "note": "Traffic shifted to replica.",
        "updated_at": "2026-11-17T02:15:00Z",
    }

    # Without optional note
    async with Client(mcp) as client:
        res2 = await client.call_tool(
            "update_incident_status",
            {"incident_id": "INC-300", "status": "resolved"},
        )
    assert res2.is_error is False
    assert json.loads(put_route.calls.last.request.content.decode("utf-8")) == {
        "status": "resolved"
    }

    # Domain validation error
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="Invalid status"):
            await client.call_tool(
                "update_incident_status",
                {"incident_id": "INC-300", "status": "closed"},
            )

    # Unexpected non-dict response
    respx.put("https://api.test.internal/v1/incidents/INC-300/status").mock(
        return_value=httpx.Response(200, json=["bad"])
    )
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="Unexpected upstream response format"):
            await client.call_tool(
                "update_incident_status",
                {"incident_id": "INC-300", "status": "resolved"},
            )

    # HTTP 404 error
    respx.put("https://api.test.internal/v1/incidents/INC-404/status").mock(
        return_value=httpx.Response(404, text="not found")
    )
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="404"):
            await client.call_tool(
                "update_incident_status",
                {"incident_id": "INC-404", "status": "identified"},
            )


@respx.mock
async def test_delete_incident_204_200_and_error_paths() -> None:
    del_route = respx.delete("https://api.test.internal/v1/incidents/INC-500").mock(
        return_value=httpx.Response(204)
    )

    async with Client(mcp) as client:
        res_204 = await client.call_tool("delete_incident", {"incident_id": "INC-500"})

    assert del_route.called
    assert res_204.structured_content == {
        "id": "INC-500",
        "deleted": True,
        "message": "Incident INC-500 deleted.",
    }

    respx.delete("https://api.test.internal/v1/incidents/INC-501").mock(
        return_value=httpx.Response(
            200, json={"id": "INC-501", "deleted": True, "message": "Purged from Acme."}
        )
    )
    async with Client(mcp) as client:
        res_200 = await client.call_tool("delete_incident", {"incident_id": "INC-501"})

    assert res_200.structured_content == {
        "id": "INC-501",
        "deleted": True,
        "message": "Purged from Acme.",
    }

    respx.delete("https://api.test.internal/v1/incidents/INC-BAD").mock(
        return_value=httpx.Response(200, json=["invalid"])
    )
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="Unexpected upstream response format"):
            await client.call_tool("delete_incident", {"incident_id": "INC-BAD"})

    respx.delete("https://api.test.internal/v1/incidents/INC-404").mock(
        return_value=httpx.Response(404, text="not found")
    )
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="404"):
            await client.call_tool("delete_incident", {"incident_id": "INC-404"})
