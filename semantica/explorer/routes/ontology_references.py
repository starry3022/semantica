"""Check explicit RDF-generated concept references against live evidence."""

from fastapi import HTTPException

from ...ontology.graph_snapshot import graph_snapshot_digest
from .ontology_evidence import _related_rules
from .sources import _read_node, _related_process_rules

NOTICE = (
    "LLM-proposed concept references are candidate / unreviewed. They describe "
    "what a requirement or rule refers to, not an rdf:type assertion or business approval."
)


def _concept_references(request, session, *, node_id=None, class_uri=None):
    context = getattr(request.app.state, "ontology_evidence_context", None)
    resources = getattr(request.app.state, "source_resources", None)
    result = {
        "references": [],
        "issues": [],
        "status": "unconfigured",
        "notice": NOTICE,
    }
    if context is None:
        return result
    result["status"] = "ready"
    edges = session.graph.find_edges()
    checked = {}
    for ontology in context.business_ontologies:
        input_changed = False
        if ontology.input_graph is not None:
            try:
                snapshot = ontology.input_graph
                ids = set(snapshot.node_ids)
                nodes = [_read_node(session, key) for key in snapshot.node_ids]
                incident_edges = [
                    edge
                    for edge in edges
                    if edge["source"] in ids or edge["target"] in ids
                ]
                current_base = session.graph.metadata.get("base_uri")
                input_changed = (
                    any(node is None for node in nodes)
                    or graph_snapshot_digest(nodes, incident_edges, current_base)
                    != snapshot.sha256
                )
            except (TypeError, ValueError, KeyError):
                # Reject invalid live state without breaking read-only navigation.
                input_changed = True
        for reference in ontology.concept_references:
            if node_id is not None and reference.node_id != node_id:
                continue
            if class_uri is not None and reference.class_uri != class_uri:
                continue
            reason = None
            node = None if input_changed else _read_node(session, reference.node_id)
            if input_changed:
                reason = "The input graph changed; regenerate its candidate concept references."
            elif node is None or (
                node["type"] != reference.node_type
                or node["content"] != reference.node_label
                or node["properties"]
                != {"content": reference.node_label, **reference.node_properties}
            ):
                reason = "The RDF node changed or is missing; regenerate its candidate concept reference."
            elif resources is None:
                reason = "Source resources are unavailable."
            evidence_ids = set()
            if reason is None:
                key = (ontology.uri, reference.class_uri)
                if key not in checked:
                    try:
                        checked[key] = _related_rules(session, resources, context, *key)
                    except HTTPException as exc:
                        if exc.status_code != 404:
                            raise
                        checked[key] = None
                related = checked[key]
                if related is None or not any(
                    anchor["term_uri"] == reference.class_uri
                    and anchor["status"] == "aligned"
                    for anchor in related["anchors"]
                ):
                    reason = "The class definition or its source citation is unavailable or changed."
                else:
                    rule_ids = (
                        {reference.node_id}
                        if node["type"] == "ProcessRule"
                        else {
                            rule["id"]
                            for rule in _related_process_rules(
                                session, edges, reference.node_id, None
                            )
                        }
                    )
                    evidence_ids = {
                        evidence["id"]
                        for rule in related["associations"]
                        if rule["node_id"] in rule_ids
                        for evidence in rule["evidence"]
                    }
                    if not evidence_ids:
                        reason = "No aligned source evidence connects this node's rules to the proposed class."
            if reason:
                result["issues"].append(
                    {
                        "node_id": reference.node_id,
                        "class_uri": reference.class_uri,
                        "reason": reason,
                    }
                )
                continue
            result["references"].append(
                {
                    "node_id": reference.node_id,
                    "label": reference.node_label,
                    "class_uri": reference.class_uri,
                    "class_label": checked[(ontology.uri, reference.class_uri)]["term"][
                        "label"
                    ],
                    "ontology_uri": ontology.uri,
                    "rationale": reference.rationale,
                    "status": "candidate",
                    "review_status": "unreviewed",
                    "evidence_ids": sorted(evidence_ids),
                }
            )
    if result["issues"] and not result["references"]:
        result["status"] = "unavailable"
    return result
