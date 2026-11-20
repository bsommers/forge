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
DATA_CARRIER_EXACT = {
    "rows",
    "columns",
    "series",
    "datapoints",
    "entries",
    "events",
    "results",
    "records",
    "line_items",
    "findings",
    "metrics",
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


def flatten_composed_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Flatten OpenAPI 3.x / JSON Schema 2020-12 allOf and nullable/polymorphic oneOf/anyOf."""
    result: dict[str, Any] = {
        k: v for k, v in schema.items() if k not in {"allOf", "oneOf", "anyOf"}
    }
    raw_props = result.get("properties")
    merged_props: dict[str, Any] = dict(raw_props) if isinstance(raw_props, dict) else {}
    raw_req = result.get("required")
    merged_req: list[str] = [str(r) for r in raw_req] if isinstance(raw_req, list) else []

    if isinstance(schema.get("allOf"), list):
        for sub in schema["allOf"]:
            if isinstance(sub, dict):
                flat_sub = flatten_composed_schema(sub)
                sub_props = flat_sub.get("properties")
                if isinstance(sub_props, dict):
                    merged_props.update(sub_props)
                for req_k in flat_sub.get("required", []):
                    if isinstance(req_k, str) and req_k not in merged_req:
                        merged_req.append(req_k)
        result.setdefault("type", "object")

    for union_kw in ("anyOf", "oneOf"):
        variants = schema.get(union_kw)
        if not isinstance(variants, list) or not variants:
            continue
        non_null = [v for v in variants if isinstance(v, dict) and v.get("type") != "null"]
        has_null = len(non_null) < len(variants)
        if len(non_null) == 1:
            unwrapped = flatten_composed_schema(non_null[0])
            for k, v in unwrapped.items():
                if k not in {"properties", "required"}:
                    result.setdefault(k, v)
            u_props = unwrapped.get("properties")
            if isinstance(u_props, dict):
                merged_props.update(u_props)
            if has_null:
                result["nullable"] = True
        elif len(non_null) > 1:
            for variant in non_null:
                flat_var = flatten_composed_schema(variant)
                v_props = flat_var.get("properties")
                if isinstance(v_props, dict):
                    for pk, pv in v_props.items():
                        merged_props.setdefault(pk, pv)
            result.setdefault("type", "object")

    if merged_props:
        result["properties"] = {
            k: flatten_composed_schema(v) if isinstance(v, dict) else v
            for k, v in merged_props.items()
        }
    if merged_req:
        result["required"] = merged_req
    return result


def _array_type_mapping(prop_schema: dict[str, Any]) -> tuple[str, str, Any]:
    items = prop_schema.get("items")
    if isinstance(items, dict):
        flat_items = flatten_composed_schema(items)
        item_type = str(flat_items.get("type", ""))
        if item_type == "string":
            return ("list[str]", "[]", ["item-1"])
        if item_type == "integer":
            return ("list[int]", "[]", [1])
        if item_type == "number":
            return ("list[float]", "[]", [12.5])
        if item_type == "boolean":
            return ("list[bool]", "[]", [True])
    return ("list[dict[str, Any]]", "[]", [{"id": "INC-1"}])


def _scalar_type_mapping(
    prop_schema: dict[str, Any], *, required: bool
) -> tuple[str, str, Any] | None:
    prop_schema = flatten_composed_schema(prop_schema)
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


def _score_field(
    py_name: str,
    wire_path: tuple[str, ...],
    *,
    is_required: bool,
    is_array: bool = False,
) -> int:
    leaf = wire_path[-1].lower()
    norm = py_name.lower()
    is_nested = len(wire_path) > 1
    if norm in TIER_1_EXACT or (not is_nested and leaf.endswith("_id")):
        return 100
    if norm in TIER_2_EXACT or (not is_nested and leaf in TIER_2_EXACT):
        return 85
    if norm in DATA_CARRIER_EXACT or leaf in DATA_CARRIER_EXACT or is_array:
        return 78
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
    obj_schema = flatten_composed_schema(obj_schema)
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

        raw_sub = flatten_composed_schema(raw_sub)
        if raw_sub.get("x-mcp-cycle-broken") is True:
            continue

        sub_type = raw_sub.get("type")
        is_req = wire_key in req_set

        # Case 0: Data-carrier array field inside a non-envelope resource object
        if sub_type == "array":
            py_name = _safe_py_identifier(wire_key)
            if py_name in used_names:
                continue
            used_names.add(py_name)
            arr_type, arr_default, arr_sample = _array_type_mapping(raw_sub)
            desc = _clean_desc(
                str(raw_sub.get("description") or ""),
                f"Projected {wire_key} collection.",
            )
            pf = ProjectedField(
                py_name=py_name,
                source_path=(wire_key,),
                py_type=arr_type,
                default_repr=arr_default,
                description=desc,
                sample_value=arr_sample,
            )
            score = _score_field(py_name, (wire_key,), is_required=is_req, is_array=True)
            candidates.append((score, py_name, pf))
            continue

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
    response_schema = flatten_composed_schema(response_schema)
    if response_schema.get("type") == "array":
        items = response_schema.get("items")
        if isinstance(items, dict):
            return (None, flatten_composed_schema(items), None)

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
            item_s = flatten_composed_schema(dict(v["items"]))
            # Only treat object-item arrays as collection envelopes; scalar series stay on object
            if item_s.get("type") == "object" or "properties" in item_s:
                array_props.append((str(k), item_s))

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

    response_schema = flatten_composed_schema(response_schema)
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
