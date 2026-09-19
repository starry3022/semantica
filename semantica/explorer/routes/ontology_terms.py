"""Explicit, revision-checked ontology term edits in the current graph session."""

import copy
import hashlib
import json
import uuid
from threading import RLock
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field, field_validator
from rdflib.namespace import XSD

from ...context.context_graph import ContextEdge
from ..dependencies import get_session
from ..session import GraphSession

router = APIRouter(prefix="/api/ontology", tags=["ontology"])
# Serialize this endpoint's commits and notifications across sessions in this
# process. Using session._lock here would invert legacy graph->session callback
# locking. This independent lock is never acquired by those existing writers.
_EDIT_LOCK = RLock()
_OWL = "http://www.w3.org/2002/07/owl#"
_RDFS = "http://www.w3.org/2000/01/rdf-schema#"
_TYPES = {
    "rdfs:Class": "owl:Class",
    _RDFS + "Class": "owl:Class",
    **{
        value: "owl:" + name
        for name in ("Class", "ObjectProperty", "DatatypeProperty")
        for value in ("owl:" + name, _OWL + name)
    },
}
_CLASS_TYPES = {"owl:Class", _OWL + "Class", "rdfs:Class", _RDFS + "Class"}
_PREDICATES = {
    "parents": "rdfs:subClassOf",
    "domain": "rdfs:domain",
    "range": "rdfs:range",
}
_FIELDS = {
    predicate: field
    for field, compact in _PREDICATES.items()
    for predicate in (compact, _RDFS + compact.split(":", 1)[1])
}
_XSD_DATATYPES = {str(XSD) + name for name in XSD.__annotations__}


class TermEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: str = Field(min_length=1)
    label: str = Field(min_length=1)
    comment: str
    parents: list[str]
    domain: list[str]
    range: list[str]

    @field_validator("label")
    @classmethod
    def nonblank_label(cls, value):
        if not value.strip():
            raise ValueError("A term label must contain visible text.")
        return value

    @field_validator("parents", "domain", "range")
    @classmethod
    def distinct_references(cls, values):
        if len(values) != len(set(values)):
            raise ValueError("Schema references must not contain duplicates.")
        return values


def _field(predicate):
    return _FIELDS.get(predicate) if isinstance(predicate, str) else None


def _properties(node):
    return {**node.properties, **node.metadata}


def _owned_term(graph, ontology_uri, term_uri):
    node = graph.nodes.get(term_uri)
    if node is None or _properties(node).get("scheme_uri") != ontology_uri:
        raise HTTPException(404, "The term is not explicitly owned by this ontology.")
    if not isinstance(node.node_type, str) or node.node_type not in _TYPES:
        raise HTTPException(
            400, "Only named OWL classes and object/datatype properties are editable."
        )
    if term_uri.startswith("_:"):
        raise HTTPException(
            400, "Anonymous ontology expressions are not editable terms."
        )
    return node


def _schema_edges(graph, term_uri):
    return [
        edge
        for edge in graph.edges
        if edge.source_id == term_uri and _field(edge.edge_type) is not None
    ]


def _canonical_json(value):
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            default=jsonable_encoder,
        )
    except (TypeError, ValueError, RecursionError) as exc:
        raise HTTPException(
            400, "The term contains unsupported metadata values."
        ) from exc


def _document(ontology_uri, node, edges):
    properties = _properties(node)
    comment = properties.get("rdfs:comment", properties.get(_RDFS + "comment", ""))
    if not isinstance(node.content, str) or not isinstance(comment, str):
        raise HTTPException(400, "The term label and comment must be text.")
    term = {
        "id": node.node_id,
        "type": _TYPES[node.node_type],
        "label": node.content,
        "comment": comment,
        **{
            field: sorted(
                {edge.target_id for edge in edges if _field(edge.edge_type) == field}
            )
            for field in _PREDICATES
        },
    }
    for key in ("domain_expressions", "range_expressions"):
        if properties.get(key):
            term[key] = copy.deepcopy(properties[key])
    # Include both raw metadata containers and exact edge identity/metadata so
    # concurrent edits outside this form cannot be silently overwritten.
    snapshot = {
        "ontology_uri": ontology_uri,
        "node": {
            "id": node.node_id,
            "type": node.node_type,
            "content": node.content,
            "properties": node.properties,
            "metadata": node.metadata,
            "valid_from": node.valid_from,
            "valid_until": node.valid_until,
        },
        "edges": sorted((_canonical_json(edge.to_dict()) for edge in edges)),
    }
    revision = (
        "sha256:"
        + hashlib.sha256(_canonical_json(snapshot).encode("utf-8")).hexdigest()
    )
    return {
        "ontology_uri": ontology_uri,
        "term_uri": node.node_id,
        "revision": revision,
        "term": term,
        "scope": "session",
    }


def _class_reference(graph, reference):
    try:
        parsed = urlsplit(reference)
        named = (
            parsed.scheme in {"http", "https", "urn"}
            and (bool(parsed.path) if parsed.scheme == "urn" else bool(parsed.hostname))
            and not any(character.isspace() for character in reference)
        )
    except ValueError as exc:
        raise HTTPException(400, "Class references must be valid named IRIs.") from exc
    node = graph.nodes.get(reference)
    if (
        not named
        or node is None
        or not isinstance(node.node_type, str)
        or node.node_type not in _CLASS_TYPES
    ):
        raise HTTPException(
            400, "Class references must name classes already loaded in the graph."
        )


def _validate_changes(graph, current, body):
    kind = current["type"]
    fields = ("parents",) if kind == "owl:Class" else ("domain", "range")
    for field in _PREDICATES:
        wanted = set(getattr(body, field))
        if wanted == set(current[field]):
            continue
        if current.get(f"{field}_expressions"):
            raise HTTPException(
                400,
                f"{field} contains a complex expression and cannot be changed by this form.",
            )
        if field not in fields:
            raise HTTPException(400, f"{field} cannot be edited for this term type.")
        for reference in wanted:
            if field == "range" and kind == "owl:DatatypeProperty":
                if reference not in _XSD_DATATYPES:
                    raise HTTPException(
                        400, "Datatype ranges must be recognized XSD datatype IRIs."
                    )
                if reference not in graph.nodes:
                    raise HTTPException(
                        400,
                        "Datatype ranges must already be loaded in the graph. Import the datatype before selecting it.",
                    )
            else:
                _class_reference(graph, reference)
        if field == "parents":
            pending = list(wanted)
            visited = set()
            while pending:
                ancestor = pending.pop()
                if ancestor == current["id"]:
                    raise HTTPException(
                        400, "The parent change would create an inheritance cycle."
                    )
                if ancestor in visited:
                    continue
                visited.add(ancestor)
                pending.extend(
                    edge.target_id
                    for edge in graph._adjacency.get(ancestor, [])
                    if _field(edge.edge_type) == "parents"
                )


def _prepare_edges(graph, term_uri, edges, body):
    removed = [
        edge
        for edge in edges
        if edge.target_id not in getattr(body, _field(edge.edge_type))
    ]
    added = []
    for field, predicate in _PREDICATES.items():
        existing_targets = {
            edge.target_id for edge in edges if _field(edge.edge_type) == field
        }
        for target in sorted(set(getattr(body, field)) - existing_targets):
            edge_id = "ontology-term:" + uuid.uuid4().hex
            added.append(
                ContextEdge(
                    source_id=term_uri,
                    target_id=target,
                    edge_type=predicate,
                    edge_id=edge_id,
                    family_id=edge_id,
                )
            )
    return removed, added


def _commit(graph, node, candidate, removed, added):
    """Commit prevalidated local replacements while the caller holds graph._lock."""
    removed_objects = {id(edge) for edge in removed}
    edges_after = [
        edge for edge in graph.edges if id(edge) not in removed_objects
    ] + added
    adjacency_after = [
        edge
        for edge in graph._adjacency.get(node.node_id, [])
        if id(edge) not in removed_objects
    ] + added
    kinds = {edge.edge_type for edge in removed + added}
    buckets_after = {
        kind: [
            edge
            for edge in graph.edge_type_index.get(kind, [])
            if id(edge) not in removed_objects
        ]
        + [edge for edge in added if edge.edge_type == kind]
        for kind in kinds
    }
    edge_ids = {edge.edge_id for edge in removed + added}
    identities_after = {
        edge_id: next((edge for edge in edges_after if edge.edge_id == edge_id), None)
        for edge_id in edge_ids
    }
    absent = object()
    before = {
        "edges": list(graph.edges),
        "adjacency": graph._adjacency.get(node.node_id, absent),
        "buckets": {kind: graph.edge_type_index.get(kind, absent) for kind in kinds},
        "identities": {
            edge_id: graph._edge_index.get(edge_id, absent) for edge_id in edge_ids
        },
        "cache": graph._analytics_cache,
    }

    def restore(mapping, key, value):
        if value is absent:
            mapping.pop(key, None)
        else:
            mapping[key] = value

    try:
        graph.nodes[node.node_id] = candidate
        graph.edges[:] = edges_after
        if adjacency_after:
            graph._adjacency[node.node_id] = adjacency_after
        else:
            graph._adjacency.pop(node.node_id, None)
        for kind, bucket in buckets_after.items():
            if bucket:
                graph.edge_type_index[kind] = bucket
            else:
                graph.edge_type_index.pop(kind, None)
        for edge_id, edge in identities_after.items():
            if edge is None:
                graph._edge_index.pop(edge_id, None)
            else:
                graph._edge_index[edge_id] = edge
        graph._analytics_cache = {}
    except Exception:
        graph.nodes[node.node_id] = node
        graph.edges[:] = before["edges"]
        restore(graph._adjacency, node.node_id, before["adjacency"])
        for kind, bucket in before["buckets"].items():
            restore(graph.edge_type_index, kind, bucket)
        for edge_id, edge in before["identities"].items():
            restore(graph._edge_index, edge_id, edge)
        graph._analytics_cache = before["cache"]
        raise


@router.get("/term")
def get_term(
    ontology_uri: str = Query(..., min_length=1),
    term_uri: str = Query(..., min_length=1),
    session: GraphSession = Depends(get_session),
) -> dict:
    with session.graph._lock:
        node = _owned_term(session.graph, ontology_uri, term_uri)
        return _document(ontology_uri, node, _schema_edges(session.graph, term_uri))


@router.patch("/term")
def patch_term(
    body: TermEditRequest,
    ontology_uri: str = Query(..., min_length=1),
    term_uri: str = Query(..., min_length=1),
    session: GraphSession = Depends(get_session),
) -> dict:
    graph = session.graph
    with _EDIT_LOCK:
        with graph._lock:
            node = _owned_term(graph, ontology_uri, term_uri)
            edges = _schema_edges(graph, term_uri)
            current = _document(ontology_uri, node, edges)
            if body.expected_revision != current["revision"]:
                raise HTTPException(
                    409,
                    {
                        "code": "ontology_term_revision_conflict",
                        "message": "This term changed. Reload it before saving again.",
                        "current_revision": current["revision"],
                    },
                )
            _validate_changes(graph, current["term"], body)
            candidate = copy.deepcopy(node)
            if body.label != current["term"]["label"]:
                candidate.content = body.label
                for container in (candidate.properties, candidate.metadata):
                    container["rdfs:label"] = body.label
                    if _RDFS + "label" in container:
                        container[_RDFS + "label"] = body.label
            if body.comment != current["term"]["comment"]:
                for container in (candidate.properties, candidate.metadata):
                    container["rdfs:comment"] = body.comment
                    if _RDFS + "comment" in container:
                        container[_RDFS + "comment"] = body.comment
            removed, added = _prepare_edges(graph, term_uri, edges, body)
            node_changed = candidate != node
            if not node_changed and not removed and not added:
                return {**current, "changed": False}
            removed_objects = {id(edge) for edge in removed}
            updated_edges = [
                edge for edge in edges if id(edge) not in removed_objects
            ] + added
            # Serialize response and event payloads before changing graph state.
            result = {
                **_document(ontology_uri, candidate, updated_edges),
                "changed": True,
            }
            events = [("REMOVE_EDGE", edge.edge_id, edge.to_dict()) for edge in removed]
            events.extend(("ADD_EDGE", edge.edge_id, edge.to_dict()) for edge in added)
            if node_changed:
                events.append(("UPDATE_NODE", term_uri, candidate.to_dict()))
            _commit(graph, node, candidate, removed, added)
        # Mutation callbacks acquire session locks and broadcast. Never call
        # them while holding the graph lock, or expose partial schema indexes.
        for operation, entity_id, payload in events:
            graph._emit_mutation(operation, entity_id, payload)
        return result
