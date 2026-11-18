"""Deterministic OpenAPI 2xx response schema ranker and high-signal field projector."""

from __future__ import annotations

import keyword
import re
from dataclasses import dataclass
from typing import Any, Literal

LOW_SIGNAL_NAME_RE = re.compile(
    r"(^_|raw_html|html_body|stack_trace|debug_blob|avatar_b64|binary|metadata_raw|audit_trail_full)",
    re.IGNORECASE,
)

CURSOR_KEYS: tuple[str, ...] = ("next_cursor", "next_page_token", "cursor")
PREFERRED_COLLECTION_KEYS: tuple[str, ...] = ("items", "results", "records", "entries", "data")
NESTED_SCALAR_CANDIDATES: tuple[str, ...] = ("name", "title", "id", "email", "slug")

TIER_1_EXACT = {"id", "uid", "uuid", "key", "slug", "number"}
TIER_2_EXACT = {"title", "name", "summary", "subject", "display_name", "label"}
TIER_3_EXACT = {
    "status",
    "state",
    "phase",
    "severity",
    "priority",
    "outcome",
    "deleted",
    "acknowledged",
}
TIER_4_EXACT = {
    "commander",
    "commander_name",
    "assignee",
    "assignee_name",
    "owner",
    "service",
    "account_id",
    "billing_period",
    "amount",
    "total",
    "total_usd",
    "monthly_limit_usd",
    "current_spend_usd",
    "alert_threshold_pct",
    "currency",
    "count",
}
TIER_5_EXACT = {"updated_at", "created_at", "resolved_at", "due_date", "timestamp"}


@dataclass(frozen=True)
class ProjectedField:
    """Single projected Pydantic output field mapped from an upstream JSON path."""

    py_name: str
    source_path: tuple[str, ...]
    py_type: str
    default_repr: str
    description: str
    sample_value: Any


@dataclass(frozen=True)
class ResponseProjection:
    """Complete output projection strategy for a single MCP tool."""

    kind: Literal["object", "collection", "status_ack", "legacy_fallback"]
    fields: tuple[ProjectedField, ...]
    collection_key: str | None = None
    cursor_key: str | None = None


def _safe_py_identifier(raw: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", raw).strip("_").lower()
    if not cleaned or not cleaned[0].isalpha():
        cleaned = f"field_{cleaned}".rstrip("_")
    if keyword.iskeyword(cleaned) or cleaned.startswith("model_") or cleaned in {"schema", "copy"}:
        cleaned = f"field_{cleaned}"
    return cleaned[:48]


def _clean_desc(raw: str, fallback: str) -> str:
    text = " ".join(raw.replace('"""', "'''").replace("\\", "/").split()).strip()
    if not text:
        text = fallback
    return text[:90]


def _scalar_type_mapping(
    prop_schema: dict[str, Any], *, required: bool
) -> tuple[str, str, Any] | None:
    raw_type = prop_schema.get("type")
    if isinstance(raw_type, list):
        non_null = [t for t in raw_type if t != "null"]
        schema_type = str(non_null[0]) if non_null else "string"
        nullable = "null" in raw_type
    else:
        schema_type = str(raw_type or "string")
        nullable = bool(prop_schema.get("nullable", False))

    if schema_type == "integer":
        if required and not nullable:
            return ("int", "0", 1)
        return ("int | None", "None", 1)
    if schema_type == "number":
        if required and not nullable:
            return ("float", "0.0", 12.5)
        return ("float | None", "None", 12.5)
    if schema_type == "boolean":
        if required and not nullable:
            return ("bool", "False", True)
        return ("bool | None", "None", True)
    if schema_type == "string":
        if required and not nullable:
            return ('str', '""', "INC-1")
        return ("str | None", "None", "INC-1")
    return None


def _score_field(py_name: str, wire_path: tuple[str, ...], *, is_required: bool) -> int:
    leaf = wire_path[-1].lower()
    norm = py_name.lower()
    is_nested = len(wire_path) > 1
    if norm in TIER_1_EXACT or (not is_nested and leaf.endswith("_id")):
        return 100
    if norm in TIER_2_EXACT or (not is_nested and leaf in TIER_2_EXACT):
        return 85
    if norm in TIER_3_EXACT or (not is_nested and leaf in TIER_3_EXACT):
        return 75
    if norm in TIER_4_EXACT or leaf in TIER_4_EXACT or norm.endswith(("_usd", "_pct", "_count")):
        return 60
    if norm in TIER_5_EXACT or leaf.endswith(("_at", "_date", "_time")):
        return 45
    return 30 if is_required else 15


def _extract_candidate_fields(
    obj_schema: dict[str, Any],
    *,
    exclude_keys: set[str] | None = None,
) -> list[tuple[int, str, ProjectedField]]:
    props = obj_schema.get("properties")
    if not isinstance(props, dict):
        return []
    req_set = {str(r) for r in obj_schema.get("required", []) if isinstance(r, str)}
    excluded = exclude_keys or set()

    candidates: list[tuple[int, str, ProjectedField]] = []
    used_names: set[str] = set()

    for prop_name, raw_sub in props.items():
        wire_key = str(prop_name)
        if wire_key in excluded or LOW_SIGNAL_NAME_RE.search(wire_key):
            continue
        if not isinstance(raw_sub, dict):
            continue

        sub_type = raw_sub.get("type")
        is_req = wire_key in req_set

        # Case 1: 1-level nested object flattening (e.g. commander -> commander.name)
        if sub_type == "object" or ("properties" in raw_sub and sub_type is None):
            nested_props = raw_sub.get("properties")
            if isinstance(nested_props, dict):
                for nested_key in NESTED_SCALAR_CANDIDATES:
                    nested_schema = nested_props.get(nested_key)
                    if not isinstance(nested_schema, dict):
                        continue
                    mapped = _scalar_type_mapping(nested_schema, required=False)
                    if mapped is None:
                        continue
                    flat_raw = (
                        wire_key if nested_key == "name" and wire_key in {"commander", "assignee"}
                        else f"{wire_key}_{nested_key}"
                    )
                    py_name = _safe_py_identifier(flat_raw)
                    if py_name in used_names:
                        continue
                    used_names.add(py_name)
                    py_type, default_repr, sample_val = mapped
                    desc = _clean_desc(
                        str(nested_schema.get("description") or raw_sub.get("description") or ""),
                        f"Flattened {wire_key}.{nested_key} value.",
                    )
                    pf = ProjectedField(
                        py_name=py_name,
                        source_path=(wire_key, nested_key),
                        py_type=py_type,
                        default_repr=default_repr,
                        description=desc,
                        sample_value=sample_val,
                    )
                    score = _score_field(py_name, (wire_key, nested_key), is_required=is_req)
                    candidates.append((score, py_name, pf))
                    break
            continue

        # Case 2: Scalar field
        mapped = _scalar_type_mapping(raw_sub, required=is_req)
        if mapped is None:
            continue
        py_name = _safe_py_identifier(wire_key)
        if py_name in used_names:
            continue
        used_names.add(py_name)
        py_type, default_repr, sample_val = mapped
        desc = _clean_desc(str(raw_sub.get("description") or ""), f"Projected {wire_key} field.")
        pf = ProjectedField(
            py_name=py_name,
            source_path=(wire_key,),
            py_type=py_type,
            default_repr=default_repr,
            description=desc,
            sample_value=sample_val,
        )
        score = _score_field(py_name, (wire_key,), is_required=is_req)
        candidates.append((score, py_name, pf))

    candidates.sort(key=lambda item: (-item[0], item[1]))
    return candidates


def _resolve_explicit_fields(
    obj_schema: dict[str, Any],
    x_mcp_fields: list[str],
    max_output_fields: int,
) -> list[ProjectedField]:
    props = obj_schema.get("properties") if isinstance(obj_schema, dict) else None
    props_dict = props if isinstance(props, dict) else {}
    req_set = {str(r) for r in obj_schema.get("required", []) if isinstance(r, str)}

    selected: list[ProjectedField] = []
    used_names: set[str] = set()
    for raw_path in x_mcp_fields[:max_output_fields]:
        parts = tuple(p for p in raw_path.split(".") if p)
        if not parts:
            continue
        node: Any = props_dict.get(parts[0], {"type": "string"})
        for sub in parts[1:]:
            if isinstance(node, dict) and isinstance(node.get("properties"), dict):
                node = node["properties"].get(sub, {"type": "string"})
            else:
                node = {"type": "string"}
        leaf_schema = node if isinstance(node, dict) else {"type": "string"}
        is_req = len(parts) == 1 and parts[0] in req_set
        mapped = _scalar_type_mapping(leaf_schema, required=is_req) or (
            "str | None",
            "None",
            "INC-1",
        )
        py_name = _safe_py_identifier("_".join(parts))
        if py_name in used_names:
            continue
        used_names.add(py_name)
        py_type, default_repr, sample_val = mapped
        desc = _clean_desc(
            str(leaf_schema.get("description") or ""),
            f"Projected {'.'.join(parts)} field.",
        )
        selected.append(
            ProjectedField(
                py_name=py_name,
                source_path=parts,
                py_type=py_type,
                default_repr=default_repr,
                description=desc,
                sample_value=sample_val,
            )
        )
    return selected


def _detect_collection_envelope(
    response_schema: dict[str, Any],
) -> tuple[str | None, dict[str, Any], str | None] | None:
    """Return (collection_key, item_schema, cursor_key) when schema represents a list."""
    if response_schema.get("type") == "array":
        items = response_schema.get("items")
        if isinstance(items, dict):
            return (None, items, None)

    props = response_schema.get("properties")
    if not isinstance(props, dict):
        return None

    cursor_key: str | None = None
    for ck in CURSOR_KEYS:
        if ck in props:
            cursor_key = ck
            break

    array_props: list[tuple[str, dict[str, Any]]] = []
    for k, v in props.items():
        if isinstance(v, dict) and v.get("type") == "array" and isinstance(v.get("items"), dict):
            array_props.append((str(k), dict(v["items"])))

    if not array_props:
        return None

    for pref in PREFERRED_COLLECTION_KEYS:
        for k, item_schema in array_props:
            if k == pref:
                return (k, item_schema, cursor_key)

    # Single array property alongside optional cursor/count metadata -> collection envelope
    non_meta_scalars = [
        k
        for k, v in props.items()
        if k not in CURSOR_KEYS
        and k not in {"total", "count", "total_count", "has_more"}
        and not (isinstance(v, dict) and v.get("type") == "array")
    ]
    if len(array_props) == 1 and len(non_meta_scalars) <= 1:
        k, item_schema = array_props[0]
        return (k, item_schema, cursor_key)

    return None


def project_response_schema(
    response_schema: dict[str, Any] | None,
    *,
    method: str,
    x_mcp_fields: list[str] | None = None,
    max_output_fields: int = 8,
    has_schema_key: bool = True,
) -> ResponseProjection:
    """Compute a deterministic, context-bounded output projection for a tool."""
    cap = max(1, min(max_output_fields, 20))
    upper_method = method.upper()

    if response_schema is None:
        if upper_method == "DELETE":
            return ResponseProjection(
                kind="status_ack",
                fields=(
                    ProjectedField(
                        "id", ("id",), "str", '""', "Target resource identifier.", "INC-1"
                    ),
                    ProjectedField(
                        "deleted", ("deleted",), "bool", "True", "Whether deletion succeeded.", True
                    ),
                    ProjectedField(
                        "status", ("status",), "str", '"deleted"', "Operation status.", "deleted"
                    ),
                ),
            )
        if not has_schema_key:
            return ResponseProjection(kind="legacy_fallback", fields=())
        return ResponseProjection(
            kind="status_ack",
            fields=(
                ProjectedField("id", ("id",), "str", '""', "Primary resource identifier.", "INC-1"),
                ProjectedField("status", ("status",), "str", '"ok"', "Operational status.", "ok"),
            ),
        )

    envelope = _detect_collection_envelope(response_schema)
    if envelope is not None:
        coll_key, item_schema, cursor_key = envelope
        if x_mcp_fields:
            item_fields = _resolve_explicit_fields(item_schema, x_mcp_fields, cap)
        else:
            ranked = _extract_candidate_fields(item_schema)
            item_fields = [pf for _, _, pf in ranked[:cap]]
        if not item_fields:
            item_fields = [
                ProjectedField("id", ("id",), "str", '""', "Item identifier.", "INC-1"),
                ProjectedField("status", ("status",), "str", '"ok"', "Item status.", "ok"),
            ]
        return ResponseProjection(
            kind="collection",
            fields=tuple(item_fields),
            collection_key=coll_key,
            cursor_key=cursor_key or "next_cursor",
        )

    if x_mcp_fields:
        obj_fields = _resolve_explicit_fields(response_schema, x_mcp_fields, cap)
    else:
        ranked_obj = _extract_candidate_fields(response_schema)
        obj_fields = [pf for _, _, pf in ranked_obj[:cap]]

    if not obj_fields:
        return ResponseProjection(
            kind="status_ack",
            fields=(
                ProjectedField("id", ("id",), "str", '""', "Primary resource identifier.", "INC-1"),
                ProjectedField("status", ("status",), "str", '"ok"', "Operational status.", "ok"),
            ),
        )

    return ResponseProjection(kind="object", fields=tuple(obj_fields))
