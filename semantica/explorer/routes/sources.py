"""Read-only original material and exact evidence alignment for graph selections."""

import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from ..dependencies import get_session
from ..candidate_provenance import is_evidence_link, is_source_link
from ..session import GraphSession
from ..source_resources import SourceResourceRegistry

router = APIRouter(prefix="/api/sources", tags=["sources"])
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_RULE_COMPONENT_TYPES = {
    "hasActor": "Role",
    "hasRecipient": "Role",
    "hasActivity": "Activity",
    "hasApprovalGroup": "ApprovalGroup",
    "hasCondition": "Condition",
    "requiresDocument": "RequiredDocument",
    "hasDeadline": "RelativeDeadline",
}


def _string(value) -> Optional[str]:
    return value if isinstance(value, str) else None


def _properties(node: Optional[dict]) -> dict:
    properties = (node or {}).get("properties")
    return properties if isinstance(properties, dict) else {}


def _read_node(session: GraphSession, node_id: str) -> Optional[dict]:
    node = session.graph.find_node(node_id)
    return session.normalize_node(node) if node is not None else None


def _evidence_role(properties: dict, rule: dict) -> str:
    clause_id = properties.get("clause_id")
    if isinstance(clause_id, str):
        if clause_id == rule.get("source_clause_id"):
            return "primary"
        supporting = rule.get("supporting_clause_ids")
        if isinstance(supporting, list) and clause_id in supporting:
            return "supporting"
    return "unknown"


def _evidence_entry(evidence_id, node: Optional[dict], rule: dict) -> dict:
    properties = _properties(node)
    return {
        "id": _string(evidence_id) or "(invalid evidence reference)",
        "clause_id": _string(properties.get("clause_id")),
        "role": _evidence_role(properties, rule),
        "quote": _string(properties.get("quote")),
        "start_char": properties.get("start_char")
        if type(properties.get("start_char")) is int
        else None,
        "end_char": properties.get("end_char")
        if type(properties.get("end_char")) is int
        else None,
        "source_id": _string(properties.get("source_id")),
        "source_sha256": _string(properties.get("source_sha256")),
        "status": "invalid_evidence",
        "reason": None,
        "fact_status": _string(properties.get("fact_status")),
        "review_status": _string(properties.get("review_status")),
    }


def _validate_evidence(
    entry: dict,
    node: Optional[dict],
    edges: list,
    session: GraphSession,
    source: Optional[dict],
) -> None:
    if node is None or node.get("type") != "Evidence":
        entry[
            "reason"
        ] = "The explicit evidence reference is missing or is not an Evidence node."
        return
    if (
        not entry["source_id"]
        or not entry["source_sha256"]
        or not _SHA256.fullmatch(entry["source_sha256"])
        or entry["quote"] is None
    ):
        entry[
            "reason"
        ] = "Evidence requires a source identity, valid SHA-256, and a text quote."
        return
    for edge in edges:
        if not is_source_link(edge["type"], session.graph) or edge["source"] != entry["id"]:
            continue
        linked = _read_node(session, edge["target"])
        linked_properties = _properties(linked)
        if (
            linked is None
            or linked.get("type") != "SourceDocument"
            or linked_properties.get("source_id") != entry["source_id"]
            or linked_properties.get("source_sha256") != entry["source_sha256"]
        ):
            entry.update(
                status="source_mismatch",
                reason=(
                    "The fromSource relationship does not agree with this "
                    "evidence's source identity and SHA-256."
                ),
            )
            return
    if source is None or source["status"] != "available":
        entry.update(
            status=source["status"] if source else "source_missing",
            reason=source["reason"]
            if source
            else "Original material is not registered.",
        )
        return
    start, end = entry["start_char"], entry["end_char"]
    text = source["text"]
    if start is None or end is None or not 0 <= start < end <= len(text):
        entry.update(
            status="invalid_offsets",
            reason=(
                "Evidence offsets must be integers with "
                "0 <= start < end <= the Unicode character count."
            ),
        )
    elif text[start:end] != entry["quote"]:
        entry.update(
            status="quote_mismatch",
            reason=(
                "The original material at these offsets does not match "
                "the evidence quote."
            ),
        )
    else:
        entry.update(status="aligned", reason=None)


def _related_process_rules(session, edges, node_id, edge_id) -> list[dict]:
    """Offer navigation along typed process links, never promote rule citations.

    The only two-hop path is ProcessRule -> ApprovalGroup -> Role. Arbitrary
    neighbors, schema terms, and links through another shared role are excluded.
    The caller holds the graph lock for a consistent selection snapshot.
    """
    if node_id is not None:
        selected = _read_node(session, node_id)
        if not selected or selected["type"] not in _RULE_COMPONENT_TYPES.values():
            return []
    incoming: dict[str, list[dict]] = {}
    for edge in edges:
        incoming.setdefault(edge["target"], []).append(edge)
    candidates = (
        incoming.get(node_id, [])
        if node_id is not None
        else [edge for edge in edges if edge["id"] == edge_id]
    )
    rules = {}
    for edge in candidates:
        source = _read_node(session, edge["source"])
        target = _read_node(session, edge["target"])
        if source is None or target is None:
            continue
        if (
            edge["type"] == "hasRole"
            and source["type"] == "ApprovalGroup"
            and target["type"] == "Role"
        ):
            owners = [
                _read_node(session, parent["source"])
                for parent in incoming.get(edge["source"], [])
                if parent["type"] == "hasApprovalGroup"
            ]
        elif target["type"] == _RULE_COMPONENT_TYPES.get(edge["type"]):
            owners = [source]
        else:
            continue
        for rule in owners:
            if rule is None or rule["type"] != "ProcessRule":
                continue
            properties = _properties(rule)
            rules[rule["id"]] = {
                "id": rule["id"],
                "label": _string(rule.get("content")) or rule["id"],
                "source_clause_id": _string(properties.get("source_clause_id")),
                "fact_status": _string(properties.get("fact_status")),
                "review_status": _string(properties.get("review_status")),
            }
    return sorted(
        rules.values(),
        key=lambda rule: (rule["source_clause_id"] or "", rule["label"], rule["id"]),
    )


def _source_view(
    session: GraphSession,
    resources: SourceResourceRegistry,
    node_id: Optional[str],
    edge_id: Optional[str],
) -> dict:
    # Hold only the graph lock: mutation callbacks can acquire the session lock.
    # A single graph snapshot prevents mixing evidence from different revisions.
    with session.graph._lock:
        edges = session.graph.find_edges()
        rule = {}
        references = []
        sources = {}
        assertions = []
        related_relationships = []
        if node_id is not None:
            node = _read_node(session, node_id)
            if node is None:
                raise HTTPException(status_code=404, detail="Graph node not found.")
            selection = {"kind": "node", "id": node_id, "label": node["content"]}
            properties = _properties(node)
            if node["type"] == "Evidence":
                references.append(node_id)
            elif node["type"] == "SourceDocument":
                identity = (
                    _string(properties.get("source_id")),
                    _string(properties.get("source_sha256")),
                )
                sources[identity] = resources.read(*identity)
            else:
                rule = properties
                references.extend(
                    edge["target"]
                    for edge in edges
                    if edge["source"] == node_id and is_evidence_link(edge["type"], session.graph)
                )
            for edge in edges:
                records = edge.get("metadata", {}).get("candidate_assertions")
                if (
                    node_id not in (edge["source"], edge["target"])
                    or not isinstance(records, list)
                    or not records
                ):
                    continue
                source_node = _read_node(session, edge["source"])
                target_node = _read_node(session, edge["target"])
                related_relationships.append({
                    "edge_id": edge["id"],
                    "predicate": edge["type"],
                    "source_label": (source_node or {}).get("content") or edge["source"],
                    "target_label": (target_node or {}).get("content") or edge["target"],
                    "assertion_count": len(records),
                })
        else:
            edge = next((edge for edge in edges if edge["id"] == edge_id), None)
            if edge is None:
                raise HTTPException(
                    status_code=404, detail="Graph relationship not found."
                )
            selection = {"kind": "edge", "id": edge_id, "label": edge["type"]}
            if is_evidence_link(edge["type"], session.graph):
                references.append(edge["target"])
                rule = _properties(_read_node(session, edge["source"]))
            elif is_source_link(edge["type"], session.graph):
                references.append(edge["source"])
            properties = edge.get("metadata", {})
            if "evidence_id" in properties:
                references.append(properties["evidence_id"])
            if "evidence_ids" in properties:
                ids = properties["evidence_ids"]
                references.extend(ids if isinstance(ids, list) else [ids])
            records = properties.get("candidate_assertions")
            for record in records if isinstance(records, list) else []:
                if not isinstance(record, dict):
                    continue
                ids = record.get("evidence_ids", [])
                ids = [value for value in ids if isinstance(value, str)] if isinstance(ids, list) else []
                references.extend(ids)
                assertions.append({
                    "assertion_id": _string(record.get("assertion_id")),
                    "qualifiers": {
                        key: value for key, value in record.items()
                        if key not in {"assertion_id", "evidence_ids"}
                    },
                    "evidence_ids": ids,
                    "fact_status": _string(properties.get("fact_status")),
                    "review_status": _string(properties.get("review_status")),
                })
        evidence = []
        seen = set()
        reference_ids = {value for value in references if isinstance(value, str)}
        for index, reference in enumerate(references):
            if isinstance(reference, str) and reference:
                if reference in seen:
                    continue
                seen.add(reference)
                node = _read_node(session, reference)
            else:
                node = None
                reference = f"(invalid evidence reference {index + 1})"
                while reference in reference_ids:
                    reference += "*"
            entry = _evidence_entry(reference, node, rule)
            identity = (entry["source_id"], entry["source_sha256"])
            source = None
            if node and node.get("type") == "Evidence" and all(identity):
                source = sources.setdefault(identity, resources.read(*identity))
            _validate_evidence(entry, node, edges, session, source)
            evidence.append(entry)
        evidence.sort(
            key=lambda item: {"primary": 0, "supporting": 1, "unknown": 2}[item["role"]]
        )
        related_rules = _related_process_rules(session, edges, node_id, edge_id)
        result = {
            "selection": selection,
            "evidence": evidence,
            "sources": list(sources.values()),
            "related_rules": related_rules,
            "status": "ok" if evidence or sources or related_rules else "no_evidence",
        }
        if assertions:
            result["assertions"] = assertions
        if related_relationships:
            result["related_relationships"] = related_relationships
        return result


@router.get("/view")
def view_source_material(
    request: Request,
    node_id: Optional[str] = None,
    edge_id: Optional[str] = None,
    session: GraphSession = Depends(get_session),
) -> dict:
    if (node_id is None) == (edge_id is None):
        raise HTTPException(
            status_code=422, detail="Provide exactly one node_id or edge_id."
        )
    resources = request.app.state.source_resources
    return _source_view(session, resources, node_id, edge_id)
