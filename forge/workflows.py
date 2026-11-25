"""Composite Intent Workflow Compiler & Active Toolset Profile Planner (Pattern MCP-005)."""

from __future__ import annotations

import json
import keyword
import re
from pathlib import Path
from typing import Any

import yaml

MAX_WORKFLOW_STEPS = 8
MAX_TOOLSET_BUDGET = 15
STEP_REF_RE = re.compile(
    r"^\$steps\.([a-z][a-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)$"
)
INPUT_REF_RE = re.compile(r"^\$inputs\.([a-z][a-z0-9_]*)$")
SNAKE_ID_RE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")


def _workflow_error(msg: str) -> ValueError:
    from forge.ingest_openapi import SpecNormalizationError

    return SpecNormalizationError(msg)


def _to_snake_id(raw: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", raw)
    s1 = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", cleaned)
    snake = re.sub(r"_+", "_", s1).strip("_").lower()
    if not snake or not snake[0].isalpha():
        snake = f"wf_{snake}".rstrip("_")
    if keyword.iskeyword(snake):
        snake = f"{snake}_field"
    return snake[:64]


def load_workflows_definitions(
    resolved_spec: dict[str, Any],
    workflows_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Load declarative workflow definitions from OpenAPI x-mcp-workflows and/or sidecar file."""
    combined: list[dict[str, Any]] = []

    spec_wfs = resolved_spec.get("x-mcp-workflows")
    if spec_wfs is not None:
        if not isinstance(spec_wfs, list):
            raise _workflow_error("OpenAPI root 'x-mcp-workflows' must be a list of workflows.")
        for item in spec_wfs:
            if not isinstance(item, dict):
                raise _workflow_error("Each entry in 'x-mcp-workflows' must be an object.")
            combined.append(dict(item))

    if workflows_path is not None:
        resolved_wf = workflows_path.resolve()
        if not resolved_wf.is_file():
            raise _workflow_error(f"Workflows file does not exist: {workflows_path}")
        raw_text = resolved_wf.read_text(encoding="utf-8")
        loaded: Any = (
            json.loads(raw_text)
            if resolved_wf.suffix.lower() == ".json"
            else yaml.safe_load(raw_text)
        )
        entries: Any = loaded.get("workflows") if isinstance(loaded, dict) else loaded
        if not isinstance(entries, list):
            raise _workflow_error(
                f"Workflows file {workflows_path.name} must contain a 'workflows' list."
            )
        for item in entries:
            if not isinstance(item, dict):
                raise _workflow_error("Each sidecar workflow definition must be an object.")
            combined.append(dict(item))

    return combined


def _infer_projected_field_spec(
    out_name: str,
    step_op: dict[str, Any],
    field_path: tuple[str, ...],
) -> dict[str, Any]:
    """Infer Python type, default repr, and sample value for a workflow projected field."""
    from forge.projection import (
        DATA_CARRIER_EXACT,
        PREFERRED_COLLECTION_KEYS,
        flatten_composed_schema,
    )

    resp_schema = step_op.get("response_schema")
    node: dict[str, Any] | None = (
        flatten_composed_schema(resp_schema) if isinstance(resp_schema, dict) else None
    )

    # Support `$steps.timeline.items` matching collection envelope keys (`items`, `events`, etc.)
    if (
        isinstance(node, dict)
        and len(field_path) == 1
        and field_path[0] == "items"
        and "items" not in (node.get("properties") or {})
    ):
        props = node.get("properties")
        if isinstance(props, dict):
            for cand_key in (*PREFERRED_COLLECTION_KEYS, *sorted(DATA_CARRIER_EXACT)):
                cand_val = props.get(cand_key)
                if isinstance(cand_val, dict) and cand_val.get("type") == "array":
                    node = flatten_composed_schema(cand_val)
                    field_path = ()
                    break
        elif node.get("type") == "array":
            field_path = ()

    for seg in field_path:
        if not isinstance(node, dict):
            node = None
            break
        node = flatten_composed_schema(node)
        props = node.get("properties")
        if isinstance(props, dict) and seg in props and isinstance(props[seg], dict):
            node = flatten_composed_schema(props[seg])
        else:
            node = None
            break

    desc = f"Projected {out_name} from step output."
    if isinstance(node, dict):
        if isinstance(node.get("description"), str) and node["description"].strip():
            desc = node["description"].strip()[:80]
        raw_t = node.get("type", "string")
        s_type = (
            str([t for t in raw_t if t != "null"][0])
            if isinstance(raw_t, list) and [t for t in raw_t if t != "null"]
            else str(raw_t or "string")
        )
        if s_type == "integer":
            return {
                "name": out_name,
                "py_type": "int",
                "default_repr": "0",
                "sample": 1,
                "description": desc,
            }
        if s_type == "number":
            return {
                "name": out_name,
                "py_type": "float",
                "default_repr": "0.0",
                "sample": 1.5,
                "description": desc,
            }
        if s_type == "boolean":
            return {
                "name": out_name,
                "py_type": "bool",
                "default_repr": "False",
                "sample": True,
                "description": desc,
            }
        if s_type == "array":
            items = node.get("items")
            item_t = str(items.get("type", "object")) if isinstance(items, dict) else "object"
            if item_t == "string":
                return {
                    "name": out_name,
                    "py_type": "list[str]",
                    "default_repr": "[]",
                    "sample": ["evt-1"],
                    "description": desc,
                }
            if item_t == "integer":
                return {
                    "name": out_name,
                    "py_type": "list[int]",
                    "default_repr": "[]",
                    "sample": [1],
                    "description": desc,
                }
            if item_t == "number":
                return {
                    "name": out_name,
                    "py_type": "list[float]",
                    "default_repr": "[]",
                    "sample": [1.5],
                    "description": desc,
                }
            return {
                "name": out_name,
                "py_type": "list[dict[str, Any]]",
                "default_repr": "[]",
                "sample": [{"id": "evt-1", "summary": "event"}],
                "description": desc,
            }

    if len(field_path) == 1 and field_path[0] in {"items", "events", "entries", "rows", "results"}:
        return {
            "name": out_name,
            "py_type": "list[dict[str, Any]]",
            "default_repr": "[]",
            "sample": [{"id": "evt-1", "summary": "event"}],
            "description": desc,
        }

    return {
        "name": out_name,
        "py_type": "str",
        "default_repr": '""',
        "sample": f"{out_name}-1",
        "description": desc,
    }


def _compute_execution_waves(steps: list[dict[str, Any]], wf_name: str) -> list[list[str]]:
    """Partition workflow step IDs into topological waves; fail closed on cycles."""
    step_ids = [str(s["id"]) for s in steps]
    id_set = set(step_ids)
    deps_map: dict[str, set[str]] = {}

    for s in steps:
        sid = str(s["id"])
        s_deps: set[str] = set()
        for binding in s.get("bindings", []):
            if binding["kind"] == "step_ref":
                dep_id = str(binding["source_step"])
                if dep_id not in id_set:
                    raise _workflow_error(
                        f"Workflow '{wf_name}' step '{sid}' references unknown step '{dep_id}'."
                    )
                if dep_id == sid:
                    raise _workflow_error(
                        f"Workflow '{wf_name}' step '{sid}' cannot depend on itself."
                    )
                s_deps.add(dep_id)
        deps_map[sid] = s_deps

    completed: set[str] = set()
    waves: list[list[str]] = []
    remaining = list(step_ids)

    while remaining:
        ready = [sid for sid in remaining if deps_map[sid].issubset(completed)]
        if not ready:
            cycle_nodes = ", ".join(remaining)
            raise _workflow_error(
                f"Cyclic workflow step dependency detected in '{wf_name}': {cycle_nodes}"
            )
        waves.append(ready)
        completed.update(ready)
        remaining = [sid for sid in remaining if sid not in completed]

    return waves


def _extract_op_all_params(op_tool: dict[str, Any]) -> list[dict[str, Any]]:
    from forge.codegen import _collect_tool_params

    return _collect_tool_params(op_tool)


def compile_workflows(
    raw_workflows: list[dict[str, Any]],
    operation_lookup: dict[str, tuple[str, dict[str, Any]]],
    *,
    existing_tool_names: set[str],
    tag_filter: str | None = None,
    max_output_fields: int = 8,
) -> list[tuple[str, dict[str, Any]]]:
    """Validate and compile declarative workflow definitions into normalized manifest tools."""
    compiled: list[tuple[str, dict[str, Any]]] = []
    used_names = set(existing_tool_names)

    for raw_wf in raw_workflows:
        raw_name = str(raw_wf.get("name", "")).strip()
        wf_name = _to_snake_id(raw_name)
        if not raw_name or not SNAKE_ID_RE.match(wf_name):
            raise _workflow_error(f"Invalid workflow name: {raw_name!r}")
        if wf_name in used_names:
            raise _workflow_error(f"Duplicate workflow/tool name '{wf_name}'.")

        raw_steps = raw_wf.get("steps")
        if not isinstance(raw_steps, list) or not (1 <= len(raw_steps) <= MAX_WORKFLOW_STEPS):
            raise _workflow_error(
                f"Workflow '{wf_name}' must declare between 1 and {MAX_WORKFLOW_STEPS} steps."
            )

        normalized_steps: list[dict[str, Any]] = []
        steps_by_id: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
        workflow_inputs: dict[str, dict[str, Any]] = {}
        first_tag = "general"

        for idx, raw_step in enumerate(raw_steps):
            if not isinstance(raw_step, dict):
                raise _workflow_error(f"Workflow '{wf_name}' step #{idx + 1} must be an object.")
            step_id = str(raw_step.get("id", "")).strip()
            if not step_id or not re.match(r"^[a-z][a-z0-9_]*$", step_id):
                raise _workflow_error(
                    f"Workflow '{wf_name}' has invalid snake_case step id: {step_id!r}"
                )
            if step_id in steps_by_id:
                raise _workflow_error(f"Workflow '{wf_name}' has duplicate step id '{step_id}'.")

            op_ref = str(raw_step.get("operationId", "")).strip()
            lookup_hit = operation_lookup.get(op_ref) or operation_lookup.get(_to_snake_id(op_ref))
            if lookup_hit is None:
                raise _workflow_error(
                    f"Workflow '{wf_name}' step '{step_id}' references unknown "
                    f"operationId '{op_ref}'."
                )
            op_tag, op_tool = lookup_hit
            if idx == 0:
                first_tag = op_tag

            raw_step_params = raw_step.get("params") or {}
            if not isinstance(raw_step_params, dict):
                raise _workflow_error(
                    f"Workflow '{wf_name}' step '{step_id}' params must be a mapping."
                )

            op_params = _extract_op_all_params(op_tool)
            op_param_by_key: dict[str, dict[str, Any]] = {}
            for p in op_params:
                op_param_by_key[str(p["name"])] = p
                op_param_by_key[str(p["wire_name"])] = p

            bindings: list[dict[str, Any]] = []
            bound_param_names: set[str] = set()

            for raw_k, raw_v in raw_step_params.items():
                p_meta = op_param_by_key.get(str(raw_k)) or op_param_by_key.get(
                    _to_snake_id(str(raw_k))
                )
                target_name = str(p_meta["name"]) if p_meta else _to_snake_id(str(raw_k))
                wire_name = str(p_meta["wire_name"]) if p_meta else str(raw_k)
                loc = (
                    str(p_meta["in"])
                    if p_meta
                    else ("path" if f"{{{target_name}}}" in str(op_tool["path"]) else "query")
                )
                bound_param_names.add(target_name)

                if isinstance(raw_v, str) and raw_v.startswith("$"):
                    m_step = STEP_REF_RE.match(raw_v.strip())
                    m_in = INPUT_REF_RE.match(raw_v.strip())
                    if m_step:
                        bindings.append(
                            {
                                "param_name": target_name,
                                "wire_name": wire_name,
                                "in": loc,
                                "kind": "step_ref",
                                "source_step": m_step.group(1),
                                "source_path": list(m_step.group(2).split(".")),
                            }
                        )
                    elif m_in:
                        in_name = m_in.group(1)
                        if in_name not in workflow_inputs:
                            workflow_inputs[in_name] = {
                                "name": in_name,
                                "wire_name": in_name,
                                "in": "query",
                                "required": bool(p_meta["required"]) if p_meta else True,
                                "description": (
                                    str(p_meta["description"])
                                    if p_meta
                                    else f"Workflow input {in_name}."
                                ),
                                "schema": dict(p_meta["schema"])
                                if p_meta and isinstance(p_meta.get("schema"), dict)
                                else {"type": "string"},
                            }
                        bindings.append(
                            {
                                "param_name": target_name,
                                "wire_name": wire_name,
                                "in": loc,
                                "kind": "input_ref",
                                "input_name": in_name,
                            }
                        )
                    else:
                        raise _workflow_error(
                            f"Workflow '{wf_name}' step '{step_id}' invalid expression {raw_v!r}."
                        )
                else:
                    bindings.append(
                        {
                            "param_name": target_name,
                            "wire_name": wire_name,
                            "in": loc,
                            "kind": "literal",
                            "value": raw_v,
                        }
                    )

            # Lift unbound required operation parameters to workflow inputs automatically
            for p_meta in op_params:
                p_name = str(p_meta["name"])
                if p_name in bound_param_names or not p_meta.get("required", False):
                    continue
                if p_name not in workflow_inputs:
                    workflow_inputs[p_name] = {
                        "name": p_name,
                        "wire_name": str(p_meta["wire_name"]),
                        "in": str(p_meta["in"]),
                        "required": True,
                        "description": str(p_meta["description"]),
                        "schema": dict(p_meta["schema"])
                        if isinstance(p_meta.get("schema"), dict)
                        else {"type": "string"},
                    }
                bindings.append(
                    {
                        "param_name": p_name,
                        "wire_name": str(p_meta["wire_name"]),
                        "in": str(p_meta["in"]),
                        "kind": "input_ref",
                        "input_name": p_name,
                    }
                )

            step_entry: dict[str, Any] = {
                "id": step_id,
                "operation": str(op_tool["name"]),
                "method": str(op_tool["method"]),
                "path": str(op_tool["path"]),
                "bindings": bindings,
            }
            if "auth_scheme" in op_tool:
                step_entry["auth_scheme"] = op_tool["auth_scheme"]

            normalized_steps.append(step_entry)
            steps_by_id[step_id] = (step_entry, op_tool)

        raw_tags = raw_wf.get("tags")
        wf_tags = (
            [str(t) for t in raw_tags if str(t).strip()]
            if isinstance(raw_tags, list) and raw_tags
            else [first_tag]
        )
        if tag_filter and tag_filter not in wf_tags:
            continue

        waves = _compute_execution_waves(normalized_steps, wf_name)

        raw_project = raw_wf.get("project")
        if not isinstance(raw_project, dict) or not raw_project:
            raise _workflow_error(
                f"Workflow '{wf_name}' must declare a non-empty 'project' mapping."
            )
        if len(raw_project) > max(max_output_fields, 20):
            raise _workflow_error(
                f"Workflow '{wf_name}' projects {len(raw_project)} fields (exceeds safety cap)."
            )

        projected_fields: list[dict[str, Any]] = []
        for out_raw, expr_raw in raw_project.items():
            out_name = _to_snake_id(str(out_raw))
            if not isinstance(expr_raw, str):
                raise _workflow_error(
                    f"Workflow '{wf_name}' project field '{out_raw}' must use '$steps.<id>.<path>'."
                )
            m_proj = STEP_REF_RE.match(expr_raw.strip())
            if not m_proj:
                raise _workflow_error(
                    f"Workflow '{wf_name}' invalid project expression {expr_raw!r}."
                )
            src_step_id = m_proj.group(1)
            src_path = tuple(m_proj.group(2).split("."))
            if src_step_id not in steps_by_id:
                raise _workflow_error(
                    f"Workflow '{wf_name}' project references unknown step '{src_step_id}'."
                )
            _, ref_op = steps_by_id[src_step_id]
            inferred = _infer_projected_field_spec(out_name, ref_op, src_path)
            inferred["source_step"] = src_step_id
            inferred["source_path"] = list(src_path)
            projected_fields.append(inferred)

        all_get = all(s["method"] == "GET" for s in normalized_steps)
        any_delete = any(s["method"] == "DELETE" for s in normalized_steps)
        all_idem = all(s["method"] in {"GET", "PUT", "DELETE"} for s in normalized_steps)

        if raw_wf.get("readOnlyHint") is True and not all_get:
            raise _workflow_error(
                f"Workflow '{wf_name}' declares readOnlyHint=true "
                "but invokes non-GET upstream step."
            )

        read_only = bool(raw_wf.get("readOnlyHint", all_get))
        destructive = bool(raw_wf.get("destructiveHint", any_delete))
        idempotent = bool(raw_wf.get("idempotentHint", all_idem))
        primary_method = (
            "GET"
            if all_get
            else ("DELETE" if any_delete else str(normalized_steps[0]["method"]))
        )

        desc = str(
            raw_wf.get("description")
            or f"Execute composite {len(normalized_steps)}-step {wf_name} workflow."
        ).strip()
        if len(desc) < 15:
            desc = f"{desc} Composite MCP 2026-07-28 workflow."

        in_params_list = list(workflow_inputs.values())
        req_params = [str(p["name"]) for p in in_params_list if p.get("required", False)]

        wf_tool_entry: dict[str, Any] = {
            "name": wf_name,
            "title": str(raw_wf.get("title") or wf_name.replace("_", " ").title())[:80],
            "method": primary_method,
            "path": f"/workflows/{wf_name}",
            "description": desc[:400],
            "annotations": {
                "readOnlyHint": read_only,
                "destructiveHint": destructive,
                "idempotentHint": idempotent,
                "openWorldHint": True,
            },
            "required_params": req_params,
            "parameters": in_params_list,
            "request_body_schema": None,
            "max_output_fields": max_output_fields,
            "workflow": {
                "steps": normalized_steps,
                "waves": waves,
                "project": projected_fields,
            },
        }
        used_names.add(wf_name)
        compiled.append((wf_tags[0], wf_tool_entry))

    return compiled


def build_client_profiles(
    shard_manifests: list[dict[str, Any]],
    mcp_servers: dict[str, Any],
    *,
    suite_name: str,
    toolset_budget: int = MAX_TOOLSET_BUDGET,
) -> list[dict[str, Any]]:
    """Group forged shards into role-scoped Client Profiles with <= toolset_budget active tools."""
    if not (1 <= toolset_budget <= MAX_TOOLSET_BUDGET):
        raise _workflow_error(
            f"toolset_budget must be between 1 and {MAX_TOOLSET_BUDGET}, got {toolset_budget}."
        )

    readonly_shards: list[dict[str, Any]] = []
    mutating_shards: list[dict[str, Any]] = []
    for manifest in shard_manifests:
        tools = manifest.get("tools", [])
        is_ro = all(
            bool(t.get("annotations", {}).get("readOnlyHint", False)) for t in tools
        )
        if is_ro:
            readonly_shards.append(manifest)
        else:
            mutating_shards.append(manifest)

    profiles: list[dict[str, Any]] = []
    for role_slug, is_ro_group, group in (
        ("readonly", True, readonly_shards),
        ("ops", False, mutating_shards),
    ):
        bins: list[list[dict[str, Any]]] = []
        bin_counts: list[int] = []
        for shard in group:
            t_count = len(shard.get("tools", []))
            placed = False
            for idx, current_count in enumerate(bin_counts):
                if current_count + t_count <= toolset_budget:
                    bins[idx].append(shard)
                    bin_counts[idx] += t_count
                    placed = True
                    break
            if not placed:
                bins.append([shard])
                bin_counts.append(t_count)

        for idx, packed_shards in enumerate(bins, start=1):
            suffix = f"{role_slug}-{idx}" if len(bins) > 1 else role_slug
            prof_name = f"{suite_name}-{suffix}"
            shard_names = [str(s["server_name"]) for s in packed_shards]
            prof_servers = {
                s_name: mcp_servers[s_name] for s_name in shard_names if s_name in mcp_servers
            }
            profiles.append(
                {
                    "profile_name": prof_name,
                    "role": "read-only" if is_ro_group else "mutating-ops",
                    "read_only": is_ro_group,
                    "shards": shard_names,
                    "total_tools": sum(len(s.get("tools", [])) for s in packed_shards),
                    "toolset_budget": toolset_budget,
                    "mcpServers": prof_servers,
                }
            )

    return profiles
