from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import httpx

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator

MANIFEST_PATH = Path(__file__).resolve().parent.parent / "forge-manifest.json"


class ManifestConfigError(RuntimeError):
    """Raised when required configuration or secret environment variables are missing."""


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _require_env(env_name: str) -> str:
    value = os.environ.get(env_name, "").strip()
    if not value:
        raise ManifestConfigError(
            f"Missing required credential environment variable: {env_name}"
        )
    return value


def iter_manifest_auth_env_vars(manifest: dict[str, Any]) -> list[str]:
    """Return all server-bound credential env var names required by active auth schemes."""
    tools = manifest.get("tools", [])
    used_schemes: set[str] = set()
    needs_default = not tools

    for tool in tools:
        if not isinstance(tool, dict):
            continue
        scheme = tool.get("auth_scheme")
        if isinstance(scheme, str) and scheme:
            if scheme.lower() != "none":
                used_schemes.add(scheme)
        else:
            needs_default = True

    configs: list[dict[str, Any]] = []
    if needs_default:
        default_cfg = manifest.get("auth", {"type": "none"})
        if isinstance(default_cfg, dict):
            configs.append(default_cfg)

    named = manifest.get("auth_schemes", {})
    if isinstance(named, dict):
        for name in sorted(used_schemes):
            sub_cfg = named.get(name)
            if isinstance(sub_cfg, dict):
                configs.append(sub_cfg)

    env_vars: list[str] = []
    for cfg in configs:
        for key, val in cfg.items():
            if key.endswith("_env") and isinstance(val, str) and val not in env_vars:
                env_vars.append(val)
    return env_vars


class HeaderTokenAuth(httpx.Auth):
    """Injects Bearer or custom header credentials without logging secret values."""

    def __init__(self, header_name: str, header_value: str) -> None:
        self._header_name = header_name
        self._header_value = header_value

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        request.headers[self._header_name] = self._header_value
        yield request


class QueryApiKeyAuth(httpx.Auth):
    """Injects an API key query parameter."""

    def __init__(self, param_name: str, api_key: str) -> None:
        self._param_name = param_name
        self._api_key = api_key

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        request.url = request.url.copy_merge_params({self._param_name: self._api_key})
        yield request


class OAuth2ClientCredentialsAuth(httpx.Auth):
    """Async OAuth2 Client Credentials flow with in-memory expiry caching."""

    def __init__(
        self, token_url: str, client_id: str, client_secret: str, scope: str = ""
    ) -> None:
        self._token_url = token_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._scope = scope
        self._access_token: str | None = None
        self._expires_at: float = 0.0

    async def _fetch_token(self) -> str:
        payload: dict[str, str] = {"grant_type": "client_credentials"}
        if self._scope:
            payload["scope"] = self._scope
        async with httpx.AsyncClient(timeout=10.0) as token_client:
            resp = await token_client.post(
                self._token_url,
                data=payload,
                auth=(self._client_id, self._client_secret),
            )
            resp.raise_for_status()
            body = resp.json()
            self._access_token = str(body["access_token"])
            expires_in = float(body.get("expires_in", 3600))
            self._expires_at = time.monotonic() + max(expires_in - 60.0, 30.0)
            return self._access_token

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        if not self._access_token or time.monotonic() >= self._expires_at:
            await self._fetch_token()
        request.headers["Authorization"] = f"Bearer {self._access_token}"
        response = yield request
        if response.status_code == 401:
            await self._fetch_token()
            request.headers["Authorization"] = f"Bearer {self._access_token}"
            yield request


def compile_path_template(path_template: str) -> tuple[int, re.Pattern[str]]:
    """Compile an OpenAPI path template into a priority-scored exact relative path regex."""
    segments = [seg for seg in path_template.strip("/").split("/") if seg]
    if not segments:
        return (0, re.compile(r"^/?$"))
    static_count = sum(1 for s in segments if not (s.startswith("{") and s.endswith("}")))
    regex_parts = [
        r"[^/]+" if (s.startswith("{") and s.endswith("}")) else re.escape(s)
        for s in segments
    ]
    return (static_count, re.compile(r"^/" + "/".join(regex_parts) + r"$"))


class RouteDispatchAuth(httpx.Auth):
    """Per-operation httpx.Auth router honoring OpenAPI security overrides."""

    def __init__(
        self,
        default_auth: httpx.Auth | None,
        scheme_handlers: dict[str, httpx.Auth | None],
        route_overrides: list[tuple[str, re.Pattern[str], str]],
        base_path: str = "",
    ) -> None:
        self._default_auth = default_auth
        self._scheme_handlers = scheme_handlers
        self._route_overrides = route_overrides
        self._base_path = base_path.rstrip("/")

    def _normalize_rel_path(self, raw_path: str) -> str:
        if self._base_path and raw_path.startswith(self._base_path):
            stripped = raw_path[len(self._base_path) :]
            return stripped if stripped.startswith("/") else f"/{stripped}"
        return raw_path or "/"

    def _resolve_handler(self, request: httpx.Request) -> httpx.Auth | None:
        ext_scheme = request.extensions.get("forge_auth_scheme")
        if isinstance(ext_scheme, str) and ext_scheme:
            if ext_scheme.lower() == "none":
                return None
            return self._scheme_handlers.get(ext_scheme, self._default_auth)

        method = request.method.upper()
        rel_path = self._normalize_rel_path(request.url.path)
        for ov_method, pattern, scheme_name in self._route_overrides:
            if ov_method == method and pattern.match(rel_path):
                if scheme_name.lower() == "none":
                    return None
                return self._scheme_handlers[scheme_name]
        return self._default_auth

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        handler = self._resolve_handler(request)
        if handler is None:
            yield request
            return

        gen = handler.async_auth_flow(request)
        try:
            req = await gen.__anext__()
            while True:
                response = yield req
                req = await gen.asend(response)
        except StopAsyncIteration:
            return
        finally:
            await gen.aclose()


def build_auth_handler(auth_cfg: dict[str, Any]) -> httpx.Auth | None:
    """Build a single httpx.Auth instance from a declarative auth configuration mapping."""
    auth_type = str(auth_cfg.get("type", "none")).lower()

    if auth_type == "none":
        return None
    if auth_type == "bearer":
        token = _require_env(str(auth_cfg["token_env"]))
        return HeaderTokenAuth("Authorization", f"Bearer {token}")
    if auth_type == "api_key_header":
        key = _require_env(str(auth_cfg["key_env"]))
        header_name = str(auth_cfg.get("header_name", "X-API-Key"))
        return HeaderTokenAuth(header_name, key)
    if auth_type == "api_key_query":
        key = _require_env(str(auth_cfg["key_env"]))
        param_name = str(auth_cfg.get("param_name", "api_key"))
        return QueryApiKeyAuth(param_name, key)
    if auth_type == "basic":
        username = _require_env(str(auth_cfg["username_env"]))
        password = _require_env(str(auth_cfg["password_env"]))
        return httpx.BasicAuth(username=username, password=password)
    if auth_type == "oauth2_client_credentials":
        token_url = _require_env(str(auth_cfg["token_url_env"]))
        client_id = _require_env(str(auth_cfg["client_id_env"]))
        client_secret = _require_env(str(auth_cfg["client_secret_env"]))
        scope = str(auth_cfg.get("scope", ""))
        return OAuth2ClientCredentialsAuth(token_url, client_id, client_secret, scope)

    raise ManifestConfigError(f"Unsupported auth.type in forge-manifest.json: {auth_type}")


def build_auth_from_manifest(manifest: dict[str, Any]) -> httpx.Auth | None:
    auth_cfg: dict[str, Any] = manifest.get("auth", {"type": "none"})
    tools = manifest.get("tools", [])
    raw_schemes = manifest.get("auth_schemes", {})
    named_cfgs: dict[str, Any] = raw_schemes if isinstance(raw_schemes, dict) else {}

    scored_overrides: list[tuple[int, str, re.Pattern[str], str]] = []
    referenced_schemes: set[str] = set()
    needs_default = not tools

    for tool in tools:
        if not isinstance(tool, dict):
            continue
        scheme = tool.get("auth_scheme")
        if isinstance(scheme, str) and scheme:
            static_score, pattern = compile_path_template(str(tool.get("path", "/")))
            scored_overrides.append(
                (static_score, str(tool.get("method", "GET")).upper(), pattern, scheme)
            )
            if scheme.lower() != "none":
                referenced_schemes.add(scheme)
        else:
            needs_default = True

    if not scored_overrides:
        return build_auth_handler(auth_cfg)

    default_handler = build_auth_handler(auth_cfg) if needs_default else None
    scheme_handlers: dict[str, httpx.Auth | None] = {"none": None}
    for scheme_name in sorted(referenced_schemes):
        sub_cfg = named_cfgs.get(scheme_name)
        if not isinstance(sub_cfg, dict):
            raise ManifestConfigError(
                f"Tool references unknown auth_scheme '{scheme_name}' in forge-manifest.json"
            )
        scheme_handlers[scheme_name] = build_auth_handler(sub_cfg)

    scored_overrides.sort(key=lambda item: -item[0])
    ordered_overrides = [(m, pat, s) for _, m, pat, s in scored_overrides]

    upstream = manifest.get("upstream", {})
    base_url_env = str(upstream.get("base_url_env", ""))
    effective_base_url = (
        os.environ.get(base_url_env, "").strip() if base_url_env else ""
    ) or str(upstream.get("default_base_url", ""))
    base_path = urlparse(effective_base_url).path if effective_base_url else ""

    return RouteDispatchAuth(
        default_auth=default_handler,
        scheme_handlers=scheme_handlers,
        route_overrides=ordered_overrides,
        base_path=base_path,
    )
