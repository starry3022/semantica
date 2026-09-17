"""Read-only original material and exact evidence alignment for graph selections."""

import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from ..dependencies import get_session
from ..session import GraphSession
from ..source_resources import SourceResourceRegistry

router = APIRouter(prefix="/api/sources", tags=["sources"])
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


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
        if edge["type"] != "fromSource" or edge["source"] != entry["id"]:
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
                    if edge["source"] == node_id and edge["type"] == "hasEvidence"
                )
        else:
            edge = next((edge for edge in edges if edge["id"] == edge_id), None)
            if edge is None:
                raise HTTPException(
                    status_code=404, detail="Graph relationship not found."
                )
            selection = {"kind": "edge", "id": edge_id, "label": edge["type"]}
            if edge["type"] == "hasEvidence":
                references.append(edge["target"])
                rule = _properties(_read_node(session, edge["source"]))
            elif edge["type"] == "fromSource":
                references.append(edge["source"])
            properties = edge.get("metadata", {})
            if "evidence_id" in properties:
                references.append(properties["evidence_id"])
            if "evidence_ids" in properties:
                ids = properties["evidence_ids"]
                references.extend(ids if isinstance(ids, list) else [ids])
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
        return {
            "selection": selection,
            "evidence": evidence,
            "sources": list(sources.values()),
            "status": "ok" if evidence or sources else "no_evidence",
        }


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
