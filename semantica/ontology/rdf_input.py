"""Bounded, offline RDF snapshots for ontology proposals and replay validation."""

from dataclasses import dataclass
import hashlib
import re
from urllib.parse import urlsplit

from rdflib import BNode, Graph, Literal, OWL, RDF, RDFS, URIRef
from rdflib.compare import to_canonical_graph

from ..utils.exceptions import ValidationError


MAX_RDF_BYTES = 2_000_000
MAX_RDF_TRIPLES = 10_000
MAX_RDF_BLANK_NODES = 128
SUPPORT_TYPES = frozenset({"Evidence", "SourceDocument"})
_FORMATS = {
    "turtle": "turtle",
    "ttl": "turtle",
    "nt": "nt",
    "ntriples": "nt",
    "n-triples": "nt",
}
_SCHEMA_TYPES = {
    OWL.Class,
    OWL.Ontology,
    OWL.ObjectProperty,
    OWL.DatatypeProperty,
    OWL.AnnotationProperty,
    OWL.Restriction,
    OWL.Axiom,
    RDFS.Class,
    RDFS.Datatype,
    RDF.Property,
}


@dataclass(frozen=True)
class PreparedRDF:
    """An independent canonical graph plus JSON-safe, stable subject records.

    URI subjects keep their complete input IRIs. Blank subjects use canonical
    ``_:`` identifiers. ``semantic_node_ids`` excludes schema and source/evidence
    support subjects; every remaining subject needs a proposal coverage decision.
    """

    graph: Graph
    canonical_ntriples: str
    sha256: str
    node_ids: frozenset[str]
    semantic_node_ids: frozenset[str]
    support_node_ids: frozenset[str]
    required_document_ids: frozenset[str]
    snapshot: list[dict]


def _identifier(term) -> str:
    return term.n3() if isinstance(term, BNode) else str(term)


def _local_name(iri: str) -> str:
    return iri.rsplit("#", 1)[-1].rsplit("/", 1)[-1].rsplit(":", 1)[-1]


def _object_record(term) -> dict:
    if isinstance(term, Literal):
        return {
            "kind": "literal",
            "value": str(term),
            "datatype": str(term.datatype) if term.datatype else None,
            "language": term.language,
        }
    return {
        "kind": "bnode" if isinstance(term, BNode) else "iri",
        "value": _identifier(term),
    }


def _validate_iri(term):
    value = str(term)
    try:
        valid = urlsplit(value).scheme and not re.search(
            r'[\s<>"{}|\\^\x60\x00-\x1f]', value
        )
    except ValueError:
        valid = False
    if not valid or re.search(r"%(?![0-9a-fA-F]{2})", value):
        raise ValidationError("RDF input identifiers must be absolute, safe IRIs")


def prepare_rdf_input(rdf_data, rdf_format="turtle") -> PreparedRDF:
    """Parse inline Turtle/N-Triples or copy a Graph; never load a path or URL.

    No input is truncated. Triple order and blank-node labels do not affect the
    SHA-256, which hashes sorted canonical N-Triples encoded as UTF-8.
    """
    if isinstance(rdf_data, PreparedRDF):
        return rdf_data
    if not isinstance(rdf_format, str) or rdf_format.lower() not in _FORMATS:
        raise ValidationError("RDF input format must be inline Turtle or N-Triples")
    if isinstance(rdf_data, Graph):
        original = rdf_data
    else:
        if isinstance(rdf_data, bytes):
            if len(rdf_data) > MAX_RDF_BYTES:
                raise ValidationError("RDF input exceeds the byte limit")
            try:
                rdf_data = rdf_data.decode("utf-8")
            except UnicodeDecodeError as error:
                raise ValidationError("RDF input must be UTF-8") from error
        if not isinstance(rdf_data, str) or not rdf_data.strip():
            raise ValidationError(
                "RDF input must be a nonempty inline RDF string or Graph"
            )
        if len(rdf_data.encode("utf-8")) > MAX_RDF_BYTES:
            raise ValidationError("RDF input exceeds the byte limit")
        try:
            original = Graph().parse(
                data=rdf_data,
                format=_FORMATS[rdf_format.lower()],
                publicID="urn:semantica:rdf-input:",
            )
        except Exception as error:
            raise ValidationError("Malformed inline RDF input") from error
    if not original:
        raise ValidationError("RDF input contains no triples")
    if len(original) > MAX_RDF_TRIPLES:
        raise ValidationError("RDF input exceeds the triple limit")

    copied = Graph()
    blank_nodes = set()
    for subject, predicate, obj in original:
        if (
            not isinstance(subject, (URIRef, BNode))
            or not isinstance(predicate, URIRef)
            or not isinstance(obj, (URIRef, BNode, Literal))
        ):
            raise ValidationError("RDF input contains an invalid RDF term")
        for term in (subject, predicate, obj):
            if isinstance(term, URIRef):
                _validate_iri(term)
            elif isinstance(term, Literal) and term.datatype:
                _validate_iri(term.datatype)
            if isinstance(term, BNode):
                blank_nodes.add(term)
        copied.add((subject, predicate, obj))
    if len(blank_nodes) > MAX_RDF_BLANK_NODES:
        raise ValidationError("RDF input exceeds the blank-node limit")
    if len(copied.serialize(format="nt").encode("utf-8")) > MAX_RDF_BYTES:
        raise ValidationError("Normalized RDF input exceeds the byte limit")

    canonical = to_canonical_graph(copied)
    serialized = "\n".join(sorted(canonical.serialize(format="nt").splitlines())) + "\n"
    snapshot: list[dict] = []
    support, schema, required = set(), set(), set()
    for subject in sorted(set(canonical.subjects()), key=_identifier):
        node_id = _identifier(subject)
        types = sorted(
            str(value)
            for value in canonical.objects(subject, RDF.type)
            if isinstance(value, URIRef)
        )
        local_types = {_local_name(value) for value in types}
        if local_types & SUPPORT_TYPES:
            support.add(node_id)
        if any(URIRef(value) in _SCHEMA_TYPES for value in types):
            schema.add(node_id)
        if "RequiredDocument" in local_types:
            required.add(node_id)
        snapshot.append(
            {
                "id": node_id,
                "types": types,
                "statements": [
                    {"predicate": str(predicate), "object": _object_record(obj)}
                    for predicate, obj in sorted(
                        canonical.predicate_objects(subject),
                        key=lambda pair: (str(pair[0]), pair[1].n3()),
                    )
                ],
            }
        )
    node_ids = frozenset(node["id"] for node in snapshot)
    return PreparedRDF(
        graph=canonical,
        canonical_ntriples=serialized,
        sha256=hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
        node_ids=node_ids,
        semantic_node_ids=node_ids - support - schema,
        support_node_ids=frozenset(support),
        required_document_ids=frozenset(required),
        snapshot=snapshot,
    )
