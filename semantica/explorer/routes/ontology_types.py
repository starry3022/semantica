"""Read explicit instance types without inventing business classifications."""

import re
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..dependencies import get_session
from ..session import GraphSession
from .ontology_evidence import _related_rules
from .ontology_references import _concept_references

router = APIRouter(prefix="/api/ontology", tags=["ontology"])
_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
_RDFS = "http://www.w3.org/2000/01/rdf-schema#"
_OWL = "http://www.w3.org/2002/07/owl#"
_SKOS = "http://www.w3.org/2004/02/skos/core#"
_PREFIXES = {"rdf": _RDF, "rdfs": _RDFS, "owl": _OWL, "skos": _SKOS}
_TYPE_KEYS = ("rdf:type", _RDF + "type", "@type")
_TYPE_EDGES = {"rdf:type", _RDF + "type"}
_CLASS_TYPES = {_OWL + "Class", _RDFS + "Class"}
_SCHEMA_TYPES = {
    _OWL + name
    for name in (
        "Ontology",
        "Class",
        "ObjectProperty",
        "DatatypeProperty",
        "AnnotationProperty",
        "FunctionalProperty",
        "InverseFunctionalProperty",
        "TransitiveProperty",
        "SymmetricProperty",
        "AsymmetricProperty",
        "ReflexiveProperty",
        "IrreflexiveProperty",
        "Restriction",
        "DataRange",
        "Axiom",
        "AllDisjointClasses",
        "AllDisjointProperties",
    )
} | {_RDFS + "Class", _RDFS + "Datatype", _RDFS + "Property", _RDF + "Property"}
_METATYPES = _SCHEMA_TYPES | {_OWL + "NamedIndividual"}
_GENERIC_TYPES = {"entity", "unknown", "node"}
NOTICE = (
    "Types reflect explicit graph declarations, including local types qualified "
    "by the graph's declared base URI. Related business concepts share verified "
    "candidate citations; they are not instance types or business approval."
)


def _properties(node):
    return {
        **(node.properties if isinstance(node.properties, dict) else {}),
        **(node.metadata if isinstance(node.metadata, dict) else {}),
    }


def _references(value):
    values = value if isinstance(value, list) else [value]
    for item in values:
        if isinstance(item, dict):
            item = item.get("@id") or item.get("uri") or item.get("id")
        if isinstance(item, str) and item:
            yield item


def _iri(value):
    if not isinstance(value, str) or re.search(r'[\s\x00-\x20\x7f<>"{}|\\^`]', value):
        return None
    if re.search(r"%(?![0-9a-fA-F]{2})", value):
        return None
    prefix, separator, local = value.partition(":")
    if separator and prefix in _PREFIXES and local:
        return _PREFIXES[prefix] + local
    try:
        parsed = urlsplit(value)
        if parsed.scheme in {"http", "https"} and parsed.hostname:
            return value
        if parsed.scheme == "urn" and parsed.path:
            return value
    except ValueError:
        pass
    return None


def _namespace(graph):
    raw = graph.metadata.get("base_uri") if isinstance(graph.metadata, dict) else None
    base = _iri(raw)
    if base is None or base != raw or urlsplit(base).query:
        return None
    # Match process_graph._base_uri for supported absolute namespaces. Do not
    # expand a compact prefix here: that would disagree with the RDF exporter.
    return base if base.endswith(("/", "#", ":")) else base + "/"


def _declarations(graph, node):
    for edge in graph._adjacency.get(node.node_id, []):
        if (
            isinstance(edge.edge_type, str)
            and edge.edge_type in _TYPE_EDGES
            and isinstance(edge.target_id, str)
        ):
            basis = {"kind": "rdf_type_edge", "value": edge.target_id}
            if isinstance(edge.edge_id, str):
                basis["edge_id"] = edge.edge_id
            yield edge.target_id, basis
    properties = _properties(node)
    for key in _TYPE_KEYS:
        for value in _references(properties.get(key)):
            yield value, {"kind": "rdf_type_property", "value": value}
    if isinstance(node.node_type, str):
        yield node.node_type, {"kind": "node_type", "value": node.node_type}


def _label(node, fallback):
    if node is not None and isinstance(node.content, str) and node.content:
        return node.content
    return fallback


def _memberships(graph, node):
    declarations = list(_declarations(graph, node))
    if any(_iri(value) in _SCHEMA_TYPES for value, _ in declarations):
        return []
    found = {}
    for value, basis in declarations:
        uri = _iri(value)
        if uri is None and basis["kind"] == "node_type":
            base = _namespace(graph)
            if (
                base
                and value not in _GENERIC_TYPES
                and re.fullmatch(r"[\w.-]+", value, flags=re.UNICODE)
            ):
                uri = _iri(base + value)
                basis = {"kind": "graph_namespace", "value": value}
        if uri is None or uri in _METATYPES:
            continue
        if uri not in found:
            target = graph.nodes.get(uri)
            loaded = target is not None and any(
                _iri(declared) in _CLASS_TYPES
                for declared, _ in _declarations(graph, target)
            )
            owner = _properties(target).get("scheme_uri") if loaded else None
            found[uri] = {
                "class_uri": uri,
                "label": _label(target, uri),
                "loaded": loaded,
                "ontology_uri": owner if isinstance(owner, str) else None,
                "basis": [],
            }
        if basis not in found[uri]["basis"]:
            found[uri]["basis"].append(basis)
    for item in found.values():
        item["basis"].sort(
            key=lambda value: (value["kind"], value["value"], value.get("edge_id", ""))
        )
    return [found[key] for key in sorted(found)]


def _related_concepts(request, session, node_id):
    context = getattr(request.app.state, "ontology_evidence_context", None)
    if context is None or not context.business_ontologies:
        return [], "unconfigured"
    resources = getattr(request.app.state, "source_resources", None)
    if resources is None:
        return [], "unavailable"
    concepts = []
    available = False
    for ontology in context.business_ontologies:
        for term in ontology.terms:
            if term.type != "owl:Class":
                continue
            try:
                result = _related_rules(
                    session, resources, context, ontology.uri, term.uri
                )
            except HTTPException as exc:
                if exc.status_code == 404:
                    continue
                raise
            available = available or result["status"] == "ready"
            evidence_ids = {
                evidence["id"]
                for rule in result["associations"]
                for evidence in rule["evidence"]
                if rule["node_id"] == node_id or evidence["id"] == node_id
            }
            if evidence_ids:
                concepts.append(
                    {
                        "class_uri": term.uri,
                        "label": result["term"]["label"],
                        "ontology_uri": ontology.uri,
                        "evidence_ids": sorted(evidence_ids),
                    }
                )
    concepts.sort(key=lambda item: (item["ontology_uri"], item["class_uri"]))
    return concepts, "ready" if available else "unavailable"


@router.get("/instance-types")
def instance_types(
    request: Request,
    node_id: str = Query(..., min_length=1),
    session: GraphSession = Depends(get_session),
) -> dict:
    with session.graph._lock:
        node = session.graph.nodes.get(node_id)
        if node is None:
            raise HTTPException(404, "Instance node not found.")
        types = _memberships(session.graph, node)
        concepts, related_status = _related_concepts(request, session, node_id)
        references = _concept_references(request, session, node_id=node_id)
        return {
            "node_id": node_id,
            "status": "declared" if types else "unmapped",
            "types": types,
            "related_concepts": concepts,
            "related_status": related_status,
            "concept_references": references["references"],
            "concept_reference_issues": references["issues"],
            "notice": NOTICE,
        }


@router.get("/concept-references")
def concept_references(
    request: Request,
    class_uri: str = Query(..., min_length=1),
    session: GraphSession = Depends(get_session),
) -> dict:
    if _iri(class_uri) != class_uri:
        raise HTTPException(400, "class_uri must be an absolute class IRI.")
    with session.graph._lock:
        return {
            "class_uri": class_uri,
            **_concept_references(request, session, class_uri=class_uri),
        }


@router.get("/class-instances")
def class_instances(
    class_uri: str = Query(..., min_length=1),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    session: GraphSession = Depends(get_session),
) -> dict:
    if _iri(class_uri) != class_uri:
        raise HTTPException(400, "class_uri must be an absolute class IRI.")
    with session.graph._lock:
        instances = []
        # Query parameters address string identities; malformed legacy keys
        # cannot be navigated and must not break valid instance results.
        for node_id in sorted(
            key for key in session.graph.nodes if isinstance(key, str)
        ):
            node = session.graph.nodes[node_id]
            for membership in _memberships(session.graph, node):
                if membership["class_uri"] == class_uri:
                    instances.append(
                        {
                            "node_id": node_id,
                            "label": _label(node, node_id),
                            "basis": membership["basis"],
                        }
                    )
                    break
        return {
            "class_uri": class_uri,
            "instances": instances[skip : skip + limit],
            "total": len(instances),
            "skip": skip,
            "limit": limit,
        }
