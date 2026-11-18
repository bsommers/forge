"""Stage 1: OpenAPI 3.x Normalizer for MCP Server Forge (MCP 2026-07-28)."""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

MAX_TOOLS_PER_SERVER = 15
DEFAULT_MAX_OUTPUT_FIELDS = 8
MIN_MAX_OUTPUT_FIELDS = 1
MAX_MAX_OUTPUT_FIELDS = 20
HTTP_METHODS = ("get", "post", "put", "patch", "delete")
X_MCP_FIELD_PATH_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")


class SpecNormalizationError(ValueError):
    """Raised when an input OpenAPI specification violates Forge or MCP 2026-07-28 constraints."""


def _to_snake_case(raw: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", raw)
    s1 = re.sub(
        r"([a-z0-9])([A-Za-z])",
        lambda m: f"{m.group(1)}_{m.group(2)}" if m.group(2).isupper() else m.group(0),
        cleaned,
    )
    snake = re.sub(r"_+", "_", s1).strip("_").lower()
    if not snake or not snake[0].isalpha():
        snake = f"op_{snake}".rstrip("_")
    return snake[:64]


def _resolve_local_refs(node: Any, root: dict[str, Any], depth: int = 0) -> Any:  # noqa: ANN401
    """Inline internal #/components/... $refs and reject external URIs per MCP 2026-07-28."""
    if depth > 25:
        raise SpecNormalizationError("OpenAPI schema $ref nesting depth exceeds safety limit (25).")
    if isinstance(node, dict):
        if "$ref" in node and isinstance(node["$ref"], str):
            ref = node["$ref"]
            if not ref.startswith("#/"):
                raise SpecNormalizationError(
                    f"External $ref URIs are forbidden by MCP 2026-07-28 security guidelines: {ref}"
                )
            target: Any = root
            for part in ref[2:].split("/"):
                part_unescaped = part.replace("~1", "/").replace("~0", "~")
                if not isinstance(target, dict) or part_unescaped not in target:
                    raise SpecNormalizationError(f"Unresolvable internal $ref: {ref}")
                target = target[part_unescaped]
            resolved_target = _resolve_local_refs(copy.deepcopy(target), root, depth + 1)
            if isinstance(resolved_target, dict) and len(node) > 1:
                sibling_overrides = {
                    k: _resolve_local_refs(v, root, depth + 1)
                    for k, v in node.items()
                    if k != "$ref"
                }
                return {**resolved_target, **sibling_overrides}
            return resolved_target
        return {k: _resolve_local_refs(v, root, depth + 1) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve_local_refs(item, root, depth + 1) for item in node]
    return node


def _extract_auth_config(spec: dict[str, Any], env_prefix: str) -> dict[str, Any]:
    schemes = spec.get("components", {}).get("securitySchemes", {})
    if not schemes:
        return {"type": "none"}

    _, first_scheme = next(iter(schemes.items()))
    scheme_type = str(first_scheme.get("type", "")).lower()

    if scheme_type == "http":
        http_scheme = str(first_scheme.get("scheme", "bearer")).lower()
        if http_scheme == "bearer":
            return {"type": "bearer", "token_env": f"{env_prefix}_API_TOKEN"}
        if http_scheme == "basic":
            return {
                "type": "basic",
                "username_env": f"{env_prefix}_USERNAME",
                "password_env": f"{env_prefix}_PASSWORD",
            }
    if scheme_type == "apikey":
        location = str(first_scheme.get("in", "header")).lower()
        param_name = str(first_scheme.get("name", "X-API-Key"))
        if location == "query":
            return {
                "type": "api_key_query",
                "key_env": f"{env_prefix}_API_KEY",
                "param_name": param_name,
            }
        return {
            "type": "api_key_header",
            "key_env": f"{env_prefix}_API_KEY",
            "header_name": param_name,
        }
    if scheme_type == "oauth2":
        flows = first_scheme.get("flows", {})
        cc_flow = flows.get("clientCredentials", {})
        scopes = " ".join(cc_flow.get("scopes", {}).keys())
        return {
            "type": "oauth2_client_credentials",
            "token_url_env": f"{env_prefix}_OAUTH_TOKEN_URL",
            "client_id_env": f"{env_prefix}_CLIENT_ID",
            "client_secret_env": f"{env_prefix}_CLIENT_SECRET",
            "scope": scopes,
        }
    return {"type": "bearer", "token_env": f"{env_prefix}_API_TOKEN"}


def _infer_annotations(method: str) -> dict[str, bool]:
    m = method.upper()
    return {
        "readOnlyHint": m == "GET",
        "destructiveHint": m == "DELETE",
        "idempotentHint": m in {"GET", "PUT", "DELETE"},
        "openWorldHint": True,
    }


def _extract_response_schema(op: dict[str, Any]) -> dict[str, Any] | None:
    """Extract the primary 2xx application/json response schema (if declared)."""
    responses = op.get("responses")
    if not isinstance(responses, dict):
        return None

    str_keyed = {str(k): v for k, v in responses.items()}
    ordered_codes = ["200", "201", "202"] + sorted(
        code for code in str_keyed if code.startswith("2") and code not in {"200", "201", "202"}
    )
    for code in ordered_codes:
        resp_obj = str_keyed.get(code)
        if not isinstance(resp_obj, dict):
            continue
        content = resp_obj.get("content")
        if not isinstance(content, dict):
            continue
        json_media = content.get("application/json")
        if isinstance(json_media, dict) and isinstance(json_media.get("schema"), dict):
            return dict(json_media["schema"])
    return None


def _extract_x_mcp_fields(op: dict[str, Any], tool_name: str) -> list[str] | None:
    """Validate optional x-mcp-fields dotted-path allowlist on an operation."""
    if "x-mcp-fields" not in op:
        return None
    raw = op["x-mcp-fields"]
    if not isinstance(raw, list) or not raw:
        raise SpecNormalizationError(
            f"Operation '{tool_name}': x-mcp-fields must be a non-empty list of field paths."
        )
    cleaned: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not X_MCP_FIELD_PATH_RE.match(item.strip()):
            raise SpecNormalizationError(
                f"Operation '{tool_name}': invalid x-mcp-fields entry {item!r}."
            )
        field_path = item.strip()
        if field_path not in cleaned:
            cleaned.append(field_path)
    return cleaned


def normalize_openapi_to_manifest(
    spec_path: Path,
    server_name: str,
    tag_filter: str | None = None,
    max_output_fields: int = DEFAULT_MAX_OUTPUT_FIELDS,
) -> dict[str, Any]:
    """Parse an OpenAPI 3.x file into a deterministic forge-manifest.json dictionary."""
    if not (MIN_MAX_OUTPUT_FIELDS <= max_output_fields <= MAX_MAX_OUTPUT_FIELDS):
        raise SpecNormalizationError(
            f"max_output_fields must be between {MIN_MAX_OUTPUT_FIELDS} and "
            f"{MAX_MAX_OUTPUT_FIELDS}, got {max_output_fields}."
        )
    raw_text = spec_path.read_text(encoding="utf-8")
    loaded_spec: Any = (
        json.loads(raw_text) if spec_path.suffix.lower() == ".json" else yaml.safe_load(raw_text)
    )
    if not isinstance(loaded_spec, dict):
        raise SpecNormalizationError("OpenAPI root document must be a mapping/object.")
    raw_spec: dict[str, Any] = loaded_spec
    resolved_spec: dict[str, Any] = _resolve_local_refs(raw_spec, raw_spec)

    env_prefix = re.sub(r"[^A-Z0-9]+", "_", server_name.upper()).strip("_")
    servers = resolved_spec.get("servers", [])
    default_base_url = (
        str(servers[0].get("url", "https://localhost")) if servers else "https://localhost"
    )

    tools: list[dict[str, Any]] = []
    seen_names: set[str] = set()

    for path_str, path_item in sorted(resolved_spec.get("paths", {}).items()):
        if not isinstance(path_item, dict):
            continue
        path_level_params = path_item.get("parameters", [])

        for method in HTTP_METHODS:
            op = path_item.get(method)
            if not isinstance(op, dict):
                continue
            if tag_filter and tag_filter not in op.get("tags", []):
                continue

            raw_op_id = op.get("operationId") or f"{method}_{path_str}"
            tool_name = _to_snake_case(str(raw_op_id))
            if tool_name in seen_names:
                tool_name = _to_snake_case(f"{method}_{tool_name}")
            seen_names.add(tool_name)

            merged_params = [*path_level_params, *op.get("parameters", [])]
            required_params: list[str] = []
            parameter_specs: list[dict[str, Any]] = []
            for p in merged_params:
                if not isinstance(p, dict) or "name" not in p:
                    continue
                p_name = _to_snake_case(str(p["name"]))
                is_req = bool(p.get("required", False) or p.get("in") == "path")
                if is_req and p_name not in required_params:
                    required_params.append(p_name)
                p_schema = p.get("schema", {"type": "string"})
                param_entry: dict[str, Any] = {
                    "name": p_name,
                    "wire_name": str(p["name"]),
                    "in": str(p.get("in", "query")),
                    "required": is_req,
                    "description": str(p.get("description") or f"Parameter {p['name']}"),
                    "schema": p_schema,
                }
                x_header = p.get("x-mcp-header")
                if not isinstance(x_header, str) and isinstance(p_schema, dict):
                    x_header = p_schema.get("x-mcp-header")
                if isinstance(x_header, str) and x_header:
                    param_entry["x-mcp-header"] = x_header
                parameter_specs.append(param_entry)

            req_body_schema: dict[str, Any] | None = None
            if "requestBody" in op and isinstance(op["requestBody"], dict):
                content = op["requestBody"].get("content", {})
                json_media = content.get("application/json", {})
                if isinstance(json_media, dict) and "schema" in json_media:
                    req_body_schema = json_media["schema"]

            resp_schema = _extract_response_schema(op)
            x_mcp_fields = _extract_x_mcp_fields(op, tool_name)

            summary = str(
                op.get("summary") or op.get("description") or f"{method.upper()} {path_str}"
            ).strip()
            if len(summary) < 15:
                summary = f"Execute {method.upper()} request on {path_str} endpoint."

            tool_entry: dict[str, Any] = {
                "name": tool_name,
                "title": str(op.get("summary") or tool_name.replace("_", " ").title())[:80],
                "method": method.upper(),
                "path": path_str,
                "description": summary[:400],
                "annotations": _infer_annotations(method),
                "required_params": required_params,
                "parameters": parameter_specs,
                "request_body_schema": req_body_schema,
                "response_schema": resp_schema,
                "max_output_fields": max_output_fields,
            }
            if x_mcp_fields is not None:
                tool_entry["x_mcp_fields"] = x_mcp_fields
            tools.append(tool_entry)

    if not tools:
        raise SpecNormalizationError("Zero HTTP operations matched in the OpenAPI specification.")
    if len(tools) > MAX_TOOLS_PER_SERVER:
        raise SpecNormalizationError(
            f"Spec yielded {len(tools)} tools (max {MAX_TOOLS_PER_SERVER}). "
            "Re-run with --tag-filter to split into domain-scoped MCP servers."
        )

    info = resolved_spec.get("info", {})
    return {
        "protocol_revision": "2026-07-28",
        "server_name": server_name,
        "title": str(info.get("title", server_name)),
        "version": str(info.get("version", "1.0.0")),
        "description": str(
            info.get("description") or f"Stateless MCP 2026-07-28 server for {server_name}."
        )[:500],
        "upstream": {
            "base_url_env": f"{env_prefix}_BASE_URL",
            "default_base_url": default_base_url,
            "timeout_seconds": 15.0,
            "max_response_bytes": 32768,
        },
        "auth": _extract_auth_config(resolved_spec, env_prefix),
        "tools": tools,
    }


def main(argv: list[str] | None = None) -> None:
    """CLI entrypoint for standalone OpenAPI -> forge-manifest.json normalization."""
    parser = argparse.ArgumentParser(
        description="Stage 1 OpenAPI 3.x Normalizer for MCP Server Forge (MCP 2026-07-28)"
    )
    parser.add_argument("--spec", type=Path, required=True, help="OpenAPI 3.x YAML/JSON file")
    parser.add_argument("--name", type=str, required=True, help="Kebab-case MCP server name")
    parser.add_argument("--tag-filter", type=str, default=None, help="Optional OpenAPI tag slice")
    parser.add_argument(
        "--max-output-fields",
        type=int,
        default=DEFAULT_MAX_OUTPUT_FIELDS,
        help="Maximum high-signal fields projected per tool outputSchema (1..20, default 8)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional output path for forge-manifest.json (defaults to stdout)",
    )
    args = parser.parse_args(argv)

    manifest = normalize_openapi_to_manifest(
        spec_path=args.spec,
        server_name=args.name,
        tag_filter=args.tag_filter,
        max_output_fields=args.max_output_fields,
    )
    serialized = json.dumps(manifest, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    else:
        sys.stdout.write(serialized)


if __name__ == "__main__":
    main()
