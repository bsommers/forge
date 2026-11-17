from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError
from fastmcp.server.context import Context

from src.auth import (
    HeaderTokenAuth,
    ManifestConfigError,
    OAuth2ClientCredentialsAuth,
    QueryApiKeyAuth,
    build_auth_from_manifest,
)
from src.deps import get_http_client, request_json


def test_build_auth_none_and_unsupported() -> None:
    assert build_auth_from_manifest({"auth": {"type": "none"}}) is None
    with pytest.raises(ManifestConfigError, match="Unsupported auth.type"):
        build_auth_from_manifest({"auth": {"type": "mtls"}})


def test_build_auth_missing_env_raises() -> None:
    with pytest.raises(ManifestConfigError, match="MISSING_VAR"):
        build_auth_from_manifest({"auth": {"type": "bearer", "token_env": "MISSING_VAR"}})


def test_build_auth_bearer_header_query_and_basic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_CRED_1", "val-1")
    monkeypatch.setenv("TEST_USER", "alice")
    monkeypatch.setenv("TEST_PASS", "val-2")

    bearer = build_auth_from_manifest({"auth": {"type": "bearer", "token_env": "TEST_CRED_1"}})
    assert isinstance(bearer, HeaderTokenAuth)
    req1 = httpx.Request("GET", "https://api.test.internal/v1/incidents")
    next(bearer.auth_flow(req1))
    assert req1.headers["Authorization"] == "Bearer val-1"

    api_hdr = build_auth_from_manifest(
        {
            "auth": {
                "type": "api_key_header",
                "key_env": "TEST_CRED_1",
                "header_name": "X-Custom-Key",
            }
        }
    )
    assert isinstance(api_hdr, HeaderTokenAuth)
    req2 = httpx.Request("GET", "https://api.test.internal/v1/incidents")
    next(api_hdr.auth_flow(req2))
    assert req2.headers["X-Custom-Key"] == "val-1"

    api_qry = build_auth_from_manifest(
        {
            "auth": {
                "type": "api_key_query",
                "key_env": "TEST_CRED_1",
                "param_name": "key",
            }
        }
    )
    assert isinstance(api_qry, QueryApiKeyAuth)
    req3 = httpx.Request("GET", "https://api.test.internal/v1/incidents")
    next(api_qry.auth_flow(req3))
    assert req3.url.params["key"] == "val-1"

    basic = build_auth_from_manifest(
        {"auth": {"type": "basic", "username_env": "TEST_USER", "password_env": "TEST_PASS"}}
    )
    assert isinstance(basic, httpx.BasicAuth)


@respx.mock
async def test_oauth2_client_credentials_flow_and_401_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OAUTH_URL", "https://auth.test.internal/token")
    monkeypatch.setenv("OAUTH_ID", "cid")
    monkeypatch.setenv("OAUTH_SEC", "csec")

    auth = build_auth_from_manifest(
        {
            "auth": {
                "type": "oauth2_client_credentials",
                "token_url_env": "OAUTH_URL",
                "client_id_env": "OAUTH_ID",
                "client_secret_env": "OAUTH_SEC",
                "scope": "incidents:read",
            }
        }
    )
    assert isinstance(auth, OAuth2ClientCredentialsAuth)

    token_route = respx.post("https://auth.test.internal/token").mock(
        return_value=httpx.Response(200, json={"access_token": "tok-1", "expires_in": 3600})
    )
    api_route = respx.get("https://api.test.internal/v1/ping").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    async with httpx.AsyncClient(auth=auth) as client:
        r1 = await client.get("https://api.test.internal/v1/ping")
        assert r1.status_code == 200
        assert api_route.calls.last.request.headers["Authorization"] == "Bearer tok-1"

        # Second call uses cached token
        r2 = await client.get("https://api.test.internal/v1/ping")
        assert r2.status_code == 200
        assert token_route.call_count == 1

    # Simulate 401 triggering refresh
    respx.post("https://auth.test.internal/token").mock(
        return_value=httpx.Response(200, json={"access_token": "tok-2", "expires_in": 3600})
    )
    calls = 0

    def _side_effect(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(401, json={"error": "expired"})
        return httpx.Response(200, json={"ok": True})

    respx.get("https://api.test.internal/v1/ping").mock(side_effect=_side_effect)
    async with httpx.AsyncClient(auth=auth) as client:
        r3 = await client.get("https://api.test.internal/v1/ping")
        assert r3.status_code == 200
        assert calls == 2


async def test_get_http_client_missing_and_present() -> None:
    bad_ctx = cast(Context, SimpleNamespace(lifespan_context={}))
    with pytest.raises(ToolError, match="unavailable"):
        await get_http_client(bad_ctx)

    http_client = httpx.AsyncClient()
    good_ctx = cast(Context, SimpleNamespace(lifespan_context={"http_client": http_client}))
    assert await get_http_client(good_ctx) is http_client


@respx.mock
async def test_request_json_204_and_errors() -> None:
    respx.delete("https://api.test.internal/v1/item/1").mock(return_value=httpx.Response(204))
    async with httpx.AsyncClient(base_url="https://api.test.internal/v1") as client:
        result = await request_json(client, "DELETE", "/item/1")
    assert result == {"status": "success", "http_status": 204}
