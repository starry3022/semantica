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
_PROPERTY_TYPES = {
    _OWL + "ObjectProperty",
    _OWL + "DatatypeProperty",
    _OWL + "AnnotationProperty",
    _RDF + "Property",
    _RDFS + "Property",
}
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


def _property_definition(graph, key, uri):
    target = graph.nodes.get(uri)
    loaded = target is not None and any(
        _iri(declared) in _PROPERTY_TYPES
        for declared, _ in _declarations(graph, target)
    )
    owner = _properties(target).get("scheme_uri") if loaded else None
    definition = {
        "key": key,
        "property_uri": uri,
        "label": _label(target, key) if loaded else key,
        "loaded": loaded,
        "ontology_uri": owner if isinstance(owner, str) else None,
    }
    if loaded and _properties(target).get("schema_role") == "provenance":
        definition["schema_role"] = "provenance"
    return definition


def _property_definitions(graph, node):
    """Resolve field identities without matching local names across ontologies."""
    base = _namespace(graph)
    definitions = []
    for key in _properties(node):
        uri = _iri(key)
        if (
            uri is None
            and base
            and isinstance(key, str)
            and re.fullmatch(r"[\w.-]+", key)
        ):
            uri = _iri(base + key)
        if uri is None:
            continue
        definitions.append(_property_definition(graph, key, uri))
    return definitions


def _outgoing_property_edges(graph, node_id):
    """Resolve only this node's explicit outgoing predicates, excluding rdf:type."""
    base = _namespace(graph)
    for edge in graph._adjacency.get(node_id, []):
        if edge.source_id != node_id:
            continue
        uri = _iri(edge.edge_type)
        if (
            uri is None
            and base
            and isinstance(edge.edge_type, str)
            and re.fullmatch(r"[\w.-]+", edge.edge_type)
        ):
            candidate = _iri(base + edge.edge_type)
            # A bare relation name is not enough to turn a display edge
            # into an RDF assertion; require its exact loaded definition.
            if (
                candidate
                and _property_definition(graph, edge.edge_type, candidate)["loaded"]
            ):
                uri = candidate
        if uri is not None and uri != _RDF + "type":
            yield edge, _property_definition(graph, uri, uri)


def _object_properties(graph, node_id):
    """Group outgoing RDF values by predicate and target, preserving edge identity."""
    properties = {}
    for edge, definition in _outgoing_property_edges(graph, node_id):
        if not isinstance(edge.target_id, str):
            continue
        row = properties.setdefault(
            definition["property_uri"],
            {
                **{key: value for key, value in definition.items() if key != "key"},
                "targets": {},
            },
        )
        target = row["targets"].setdefault(
            edge.target_id,
            {
                "node_id": edge.target_id,
                "label": _label(graph.nodes.get(edge.target_id), edge.target_id),
                "edge_ids": set(),
            },
        )
        if isinstance(edge.edge_id, str):
            target["edge_ids"].add(edge.edge_id)
    return [
        {
            **properties[uri],
            "targets": [
                {**target, "edge_ids": sorted(target["edge_ids"])}
                for _, target in sorted(properties[uri]["targets"].items())
            ],
        }
        for uri in sorted(properties)
    ]


def _observed_properties(graph, node_ids):
    """Summarize predicate usage without adding domain or required constraints."""
    # Unqualified display/state keys need an exact loaded predicate definition.
    # Full IRIs with the same local name remain independent, usable predicates.
    display_keys = {
        "content",
        "label",
        "fact_status",
        "review_status",
        "x",
        "y",
        "color",
        "size",
        "valid_from",
        "valid_until",
        "source",
        "source_url",
        "pmid",
        "pmids",
        "evidence",
        "provenance",
        "confidence",
    }
    observed = {}

    def record(definition, node_id, kind):
        uri = definition["property_uri"]
        if uri == _RDF + "type":
            return
        row = observed.setdefault(
            uri,
            {
                **{key: value for key, value in definition.items() if key != "key"},
                "kinds": set(),
                "instances": set(),
            },
        )
        row["kinds"].add(kind)
        row["instances"].add(node_id)

    for node_id in node_ids:
        node = graph.nodes[node_id]
        properties = _properties(node)
        for definition in _property_definitions(graph, node):
            key = definition["key"]
            if key in _TYPE_KEYS or (key in display_keys and not definition["loaded"]):
                continue
            value = properties[key]
            values = value if isinstance(value, list) else [value]
            if any(isinstance(item, (str, int, float, bool)) for item in values):
                record(definition, node_id, "literal")
        for _, definition in _outgoing_property_edges(graph, node_id):
            record(definition, node_id, "object")
    return [
        {
            **{
                key: value
                for key, value in observed[uri].items()
                if key not in {"kinds", "instances"}
            },
            "kinds": sorted(observed[uri]["kinds"]),
            "instance_count": len(observed[uri]["instances"]),
        }
        for uri in sorted(observed)
    ]


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
            "property_definitions": _property_definitions(session.graph, node),
            "object_properties": _object_properties(session.graph, node_id),
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
            "observed_properties": _observed_properties(
                session.graph, [instance["node_id"] for instance in instances]
            ),
            "total": len(instances),
            "skip": skip,
            "limit": limit,
        }
