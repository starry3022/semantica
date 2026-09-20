"""Lossless candidate assertions whose relationship contents stay unasserted."""

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass

from rdflib import RDF, XSD, Graph, Literal, Namespace, URIRef

from ..export.rdf_exporter import RDFExporter, normalize_confidence
from ..utils.exceptions import ValidationError
from .rdf_input import PreparedRDF, prepare_rdf_input

CANDIDATE_NS = "https://semantica.dev/candidate#"
REPRESENTATION = "qualified_candidate_statements_v1"
_CANDIDATE = Namespace(CANDIDATE_NS)
_REIFICATION_IRIS = frozenset({RDF.Statement, RDF.subject, RDF.predicate, RDF.object})
_EVIDENCE_FIELDS = {
    "quote": "quote",
    "source_id": "sourceId",
    "source_sha256": "sourceSha256",
    "start_char": "startChar",
    "end_char": "endChar",
    "start_line": "startLine",
    "end_line": "endLine",
    "status": "status",
    "span_origin": "spanOrigin",
}


@dataclass(frozen=True)
class CandidateStatements:
    """Authoritative assertions and a separate, unasserted business projection."""

    rdf: str
    prepared: PreparedRDF
    projection: PreparedRDF
    facts_sha256: str
    assertion_ids: list[str]


def _json(value) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        if json.loads(encoded) == value:
            return encoded
    except (TypeError, ValueError, RecursionError):
        pass
    raise ValidationError("Candidate records must contain lossless JSON values.")


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _validate_facts(data):
    if not isinstance(data, dict):
        raise ValidationError("Candidate facts must be an object.")
    entities = data.get("entities")
    relations = data.get("relationships", [])
    if (
        not isinstance(entities, list)
        or not entities
        or not isinstance(relations, list)
    ):
        raise ValidationError(
            "Candidate facts require nonempty entities and a relationships list."
        )
    if data.get("metadata") is not None and not isinstance(data["metadata"], dict):
        raise ValidationError("Candidate metadata must be an object or null.")
    for records, required in (
        (entities, ("id", "type")),
        (relations, ("type",)),
    ):
        for record in records:
            if not isinstance(record, dict):
                raise ValidationError("Candidate records must be objects.")
            fields = (*required, "id") if "id" in record else required
            for field in fields:
                if not isinstance(record.get(field), str) or not record[field].strip():
                    raise ValidationError(
                        "Candidate IDs and types must be nonempty strings."
                    )
            metadata = record.get("metadata")
            if metadata is not None and not isinstance(metadata, dict):
                raise ValidationError("Candidate metadata must be an object or null.")
            metadata = metadata or {}
            if not isinstance(metadata.get("evidence", []), list):
                raise ValidationError("Candidate evidence must be a list.")
            for field in ("condition", "modality"):
                if metadata.get(field) is not None and not isinstance(
                    metadata[field], str
                ):
                    raise ValidationError(
                        "Candidate condition and modality must be strings or null."
                    )
            if (
                metadata.get("negation") is not None
                and type(metadata["negation"]) is not bool
            ):
                raise ValidationError("Candidate negation must be a boolean or null.")
    for record in relations:
        for keys in (("source_id", "source"), ("target_id", "target")):
            value = record.get(keys[0]) or record.get(keys[1])
            if not isinstance(value, str) or not value.strip():
                raise ValidationError(
                    "Candidate relationship endpoints must be nonempty strings."
                )


def _record(graph, subject, record, reserved):
    graph.add((subject, _CANDIDATE.recordJson, Literal(_json(record))))
    for evidence in (record.get("metadata") or {}).get("evidence", []):
        node = URIRef("urn:semantica:candidate:evidence:" + _hash(_json(evidence)))
        if node in reserved:
            raise ValidationError(
                "Candidate evidence resource identity collides with another resource."
            )
        graph.add((subject, _CANDIDATE.hasEvidence, node))
        graph.add((node, RDF.type, _CANDIDATE.Evidence))
        graph.add((node, _CANDIDATE.recordJson, Literal(_json(evidence))))
        if isinstance(evidence, dict):
            for key, field in _EVIDENCE_FIELDS.items():
                value = evidence.get(key)
                if value is not None:
                    graph.add((node, _CANDIDATE[field], Literal(value)))


def prepare_candidate_statements(facts: dict) -> CandidateStatements:
    """Keep native entity identity while representing relationships as records."""
    _validate_facts(facts)
    data = deepcopy(facts)
    facts_hash = _hash(_json(data))
    exporter = RDFExporter()
    projection = prepare_rdf_input(exporter.export_to_rdf(data))
    entities = prepare_rdf_input(exporter.export_to_rdf({**data, "relationships": []}))
    graph = Graph()
    for triple in entities.graph:
        graph.add(triple)
    namespaces = exporter.serializer.namespace_manager.extract_namespaces(data)
    iri = exporter.serializer._as_turtle_iri
    entity_ids = [URIRef(iri(entity["id"], namespaces)) for entity in data["entities"]]
    if len(set(entity_ids)) != len(entity_ids):
        raise ValidationError(
            "Candidate entity IDs must be unique after IRI resolution."
        )
    resources = {
        term
        for triple in projection.graph
        for term in triple
        if isinstance(term, URIRef)
    }
    vocabulary = set(projection.graph.predicates()) | set(
        projection.graph.objects(None, RDF.type)
    )
    if set(entity_ids) & vocabulary:
        raise ValidationError(
            "Candidate entity IDs cannot collide with vocabulary resources."
        )
    if _REIFICATION_IRIS & resources or any(
        str(term).startswith(CANDIDATE_NS) for term in resources
    ):
        raise ValidationError(
            "Candidate business resources collide with the transport namespace."
        )
    assertion_ids = []
    for relation in data.get("relationships", []):
        endpoints = []
        for primary, alternate in (("source_id", "source"), ("target_id", "target")):
            endpoint = URIRef(
                iri(relation.get(primary) or relation.get(alternate), namespaces)
            )
            if endpoint not in entity_ids:
                raise ValidationError(
                    "Candidate relationship has an unknown entity endpoint."
                )
            endpoints.append(endpoint)
        if (
            endpoints[0],
            URIRef(iri(relation["type"], namespaces)),
            endpoints[1],
        ) in entities.graph:
            raise ValidationError(
                "Candidate relationship collides with an asserted entity description."
            )
        identifier = (
            iri(relation["id"], namespaces)
            if "id" in relation
            else "urn:semantica:candidate:assertion:" + _hash(_json(relation))
        )
        if (
            identifier in assertion_ids
            or URIRef(identifier) in resources
            or URIRef(identifier) in _REIFICATION_IRIS
            or identifier.startswith(CANDIDATE_NS)
        ):
            raise ValidationError(
                "Candidate assertion IDs must be unique and cannot collide with other resources."
            )
        assertion_ids.append(identifier)
    document = URIRef("urn:semantica:candidate:dataset:" + facts_hash)
    reserved = resources | {URIRef(identifier) for identifier in assertion_ids}
    if document in reserved:
        raise ValidationError(
            "Candidate dataset resource identity collides with another resource."
        )
    reserved.add(document)
    graph.add((document, RDF.type, _CANDIDATE.CandidateDataset))
    graph.add((document, _CANDIDATE.representation, Literal(REPRESENTATION)))
    graph.add((document, _CANDIDATE.factsSha256, Literal(facts_hash)))
    graph.add(
        (
            document,
            _CANDIDATE.recordJson,
            Literal(
                _json(
                    {
                        k: v
                        for k, v in data.items()
                        if k not in {"entities", "relationships"}
                    }
                )
            ),
        )
    )
    for entity in data["entities"]:
        subject = URIRef(iri(entity["id"], namespaces))
        graph.add((document, _CANDIDATE.entity, subject))
        _record(graph, subject, entity, reserved)
    for relation, identifier in zip(data.get("relationships", []), assertion_ids):
        assertion = URIRef(identifier)
        graph.add((document, _CANDIDATE.assertion, assertion))
        graph.add((assertion, RDF.type, RDF.Statement))
        for predicate, value in (
            (RDF.subject, relation.get("source_id") or relation.get("source")),
            (RDF.predicate, relation["type"]),
            (RDF.object, relation.get("target_id") or relation.get("target")),
        ):
            graph.add((assertion, predicate, URIRef(iri(value, namespaces))))
        _record(graph, assertion, relation, reserved)
        for key in ("condition", "modality", "negation"):
            value = (relation.get("metadata") or {}).get(key)
            if value is not None:
                graph.add((assertion, _CANDIDATE[key], Literal(value)))
        if "confidence" in relation:
            confidence = normalize_confidence(relation["confidence"])
            if confidence is not None:
                graph.add(
                    (
                        assertion,
                        _CANDIDATE.confidence,
                        Literal(confidence, datatype=XSD.decimal),
                    )
                )
    prepared = prepare_rdf_input(graph)
    return CandidateStatements(
        rdf=prepared.canonical_ntriples,
        prepared=prepared,
        projection=projection,
        facts_sha256=facts_hash,
        assertion_ids=assertion_ids,
    )


def validate_candidate_statements(rdf, facts: dict) -> dict:
    """Check exact source-derived preservation, not independent business accuracy.

    An empty error list proves correspondence to the supplied candidate records;
    it cannot prove their completeness, source interpretation or business truth.
    """
    errors = []
    try:
        expected = prepare_candidate_statements(facts).prepared
        actual = prepare_rdf_input(rdf)
        missing = set(expected.graph) - set(actual.graph)
        extra = set(actual.graph) - set(expected.graph)
        if missing or extra:
            errors.append(
                "Qualified RDF does not match the candidate facts: "
                f"{len(missing)} missing and {len(extra)} unexpected triples."
            )
    except (ValidationError, TypeError, ValueError) as error:
        errors.append(str(error))
    return {
        "conforms": not errors,
        "scope": "source_derived_preservation",
        "errors": errors,
    }
