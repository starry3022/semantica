"""Read-only business-concept navigation through validated source citations."""

from fastapi import APIRouter, Depends, HTTPException, Request

from ...ontology.evidence_context import OntologyEvidenceContext, TermEvidenceAnchor
from ..dependencies import get_session
from ..session import GraphSession
from .sources import _properties, _read_node, _source_view, _string


router = APIRouter(prefix="/api/ontology", tags=["ontology"])
NOTICE = (
    "These candidate links identify shared source citations, including explicitly "
    "declared property context. They do not assign instance types, establish "
    "business approval, or guarantee complete rule coverage."
)


def _configuration(context: OntologyEvidenceContext | None) -> dict:
    return {
        "configured": bool(context and context.business_ontologies),
        "business_ontologies": [item.uri for item in context.business_ontologies]
        if context
        else [],
        "support_ontologies": context.support_ontologies if context else [],
    }


@router.get("/evidence-context")
def get_evidence_context(request: Request) -> dict:
    return _configuration(getattr(request.app.state, "ontology_evidence_context", None))


@router.post("/evidence-context")
def register_evidence_context(
    context: OntologyEvidenceContext, request: Request
) -> dict:
    # Pydantic validates the complete payload before this atomic replacement.
    # No files, URLs, graph nodes or RDF assertions are read/written here.
    request.app.state.ontology_evidence_context = context
    return _configuration(context)


def _snapshot_matches(
    anchor: TermEvidenceAnchor, node: dict | None, edges: list, owner: str
) -> bool:
    if node is None:
        return False
    properties = _properties(node)
    if (
        node["type"] != anchor.type
        or node["content"] != anchor.label
        or properties.get("rdfs:comment", "") != anchor.comment
        or properties.get("scheme_uri") != owner
    ):
        return False
    for field, predicate in (
        ("domain", "rdfs:domain"),
        ("range", "rdfs:range"),
        ("parents", "rdfs:subClassOf"),
    ):
        actual = {
            edge["target"]
            for edge in edges
            if edge["source"] == anchor.uri and edge["type"] == predicate
        }
        if actual != set(getattr(anchor, field)):
            return False
    return True


def _check_anchor(anchor, session, edges, resources, owner):
    result = {
        "term_uri": anchor.uri,
        "label": anchor.label,
        "status": "aligned",
        "reason": None,
    }
    if not _snapshot_matches(anchor, _read_node(session, anchor.uri), edges, owner):
        result.update(
            status="term_changed",
            reason="The term definition or schema changed; register its updated source context.",
        )
        return result, None
    source = resources.read(anchor.source_id, anchor.source_sha256)
    if source["status"] != "available":
        result.update(status=source["status"], reason=source["reason"])
        return result, None
    text = source["text"]
    if not 0 <= anchor.start_char < anchor.end_char <= len(text):
        result.update(
            status="invalid_offsets",
            reason="The term citation is outside the source character range.",
        )
    elif text[anchor.start_char : anchor.end_char] != anchor.quote:
        result.update(
            status="quote_mismatch",
            reason="The term citation does not match the registered source at these offsets.",
        )
    return result, text if result["status"] == "aligned" else None


def _related_rules(session, resources, context, ontology_uri, term_uri):
    with session.graph._lock:
        selected = _read_node(session, term_uri)
        if selected is None:
            raise HTTPException(status_code=404, detail="Ontology term not found.")
        result = {
            "ontology_uri": ontology_uri,
            "term_uri": term_uri,
            "term": {
                "id": term_uri,
                "label": selected["content"],
                "type": selected["type"],
                "description": _properties(selected).get("rdfs:comment", ""),
            },
            "status": "unconfigured",
            "association_status": "candidate",
            "associations": [],
            "anchors": [],
            "evidence_issues": [],
            "notice": NOTICE,
        }
        business = (
            next(
                (
                    item
                    for item in context.business_ontologies
                    if item.uri == ontology_uri
                ),
                None,
            )
            if context
            else None
        )
        if business is None:
            return result
        if _properties(selected).get("scheme_uri") != ontology_uri:
            raise HTTPException(
                status_code=404, detail="The term is not owned by this ontology."
            )
        terms = {item.uri: item for item in business.terms}
        if term_uri not in terms:
            return result
        edges = session.graph.find_edges()
        root_anchor = terms[term_uri]
        root_check, _ = _check_anchor(
            root_anchor, session, edges, resources, ontology_uri
        )
        if root_check["status"] == "term_changed":
            result.update(status="unavailable", anchors=[root_check])
            return result

        candidates = [(root_anchor, "direct", None)]
        if selected["type"] == "owl:Class":
            for edge in edges:
                anchor = terms.get(edge["source"])
                if (
                    edge["target"] == term_uri
                    and edge["type"] in {"rdfs:domain", "rdfs:range"}
                    and anchor is not None
                    and anchor.type in {"owl:ObjectProperty", "owl:DatatypeProperty"}
                ):
                    candidate = (anchor, "property", edge["type"])
                    if candidate not in candidates:
                        candidates.append(candidate)
        validated = []
        checked = set()
        for anchor, kind, relation in candidates:
            check, text = _check_anchor(anchor, session, edges, resources, ontology_uri)
            if anchor.uri not in checked:
                result["anchors"].append(check)
                checked.add(anchor.uri)
            if text is not None:
                validated.append((anchor, kind, relation, text))
        result["status"] = "ready" if validated else "unavailable"
        if not validated:
            return result

        source_ids = {anchor.source_id for anchor, *_ in validated}
        candidate_rules = set()
        for edge in edges:
            if edge["type"] != "hasEvidence":
                continue
            evidence = _read_node(session, edge["target"])
            rule = _read_node(session, edge["source"])
            source_id = _properties(evidence).get("source_id")
            if (
                isinstance(source_id, str)
                and source_id in source_ids
                and rule is not None
                and rule["type"] == "ProcessRule"
            ):
                candidate_rules.add(edge["source"])
        issue_ids = set()
        for rule_id in sorted(candidate_rules):
            rule = _read_node(session, rule_id)
            props = _properties(rule)
            matched = []
            view = _source_view(session, resources, rule_id, None)
            for evidence in view["evidence"]:
                if evidence["source_id"] not in source_ids:
                    continue
                if evidence["status"] != "aligned":
                    if evidence["id"] not in issue_ids:
                        result["evidence_issues"].append(
                            {
                                key: evidence[key]
                                for key in ("id", "clause_id", "status", "reason")
                            }
                        )
                        issue_ids.add(evidence["id"])
                    continue
                links = []
                for anchor, kind, relation, text in validated:
                    if (
                        evidence["source_id"] != anchor.source_id
                        or evidence["source_sha256"] != anchor.source_sha256
                    ):
                        continue
                    start = max(evidence["start_char"], anchor.start_char)
                    end = min(evidence["end_char"], anchor.end_char)
                    if start < end and text[start:end].strip():
                        links.append(
                            {
                                "term_uri": anchor.uri,
                                "label": anchor.label,
                                "kind": kind,
                                "relation": relation,
                            }
                        )
                if links:
                    matched.append(
                        {
                            **{
                                key: evidence[key]
                                for key in (
                                    "id",
                                    "clause_id",
                                    "role",
                                    "quote",
                                    "start_char",
                                    "end_char",
                                    "source_id",
                                    "source_sha256",
                                )
                            },
                            "links": links,
                        }
                    )
            if matched:
                result["associations"].append(
                    {
                        "node_id": rule_id,
                        "label": rule["content"],
                        "modality": _string(props.get("modality")),
                        "fact_status": _string(props.get("fact_status")),
                        "review_status": _string(props.get("review_status")),
                        "evidence": matched,
                    }
                )
        return result


@router.get("/related-rules")
def related_rules(
    request: Request,
    ontology_uri: str,
    term_uri: str,
    session: GraphSession = Depends(get_session),
) -> dict:
    return _related_rules(
        session,
        request.app.state.source_resources,
        getattr(request.app.state, "ontology_evidence_context", None),
        ontology_uri,
        term_uri,
    )
