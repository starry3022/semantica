"""Explicit business vocabulary/source anchors, separate from instance RDF."""

import hashlib
from typing import Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    field_validator,
    model_validator,
)
from rdflib import Graph, OWL, RDF, RDFS, URIRef


def _iri(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or any(character.isspace() for character in value)
    ):
        raise ValueError("An absolute HTTP(S) ontology IRI is required.")
    return value


class TermEvidenceAnchor(BaseModel):
    """Source occurrence plus the exact schema definition it supported."""

    model_config = ConfigDict(extra="forbid", strict=True)
    uri: str
    label: str = Field(min_length=1)
    type: Literal["owl:Class", "owl:ObjectProperty", "owl:DatatypeProperty"]
    comment: str
    domain: list[str]
    range: list[str]
    parents: list[str]
    source_id: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    start_char: StrictInt = Field(ge=0)
    end_char: StrictInt = Field(gt=0)
    quote: str = Field(min_length=1)

    @field_validator("uri")
    @classmethod
    def valid_uri(cls, value):
        return _iri(value)

    @field_validator("domain", "range", "parents")
    @classmethod
    def valid_references(cls, values):
        return [_iri(value) for value in values]

    @model_validator(mode="after")
    def valid_span(self):
        if self.end_char <= self.start_char or not self.quote.strip():
            raise ValueError("An evidence span must contain nonblank source text.")
        if not self.source_id.strip():
            raise ValueError("A source identity is required.")
        return self


class ConceptReference(BaseModel):
    """An LLM proposal bound to an input node snapshot, never an rdf:type."""

    model_config = ConfigDict(extra="forbid", strict=True)
    node_id: str = Field(min_length=1)
    class_uri: str
    relation: Literal["references_concept"]
    rationale: str = Field(min_length=1)
    node_type: Literal[
        "ProcessRule",
        "Role",
        "Activity",
        "ApprovalGroup",
        "Condition",
        "RequiredDocument",
        "RelativeDeadline",
    ]
    node_label: str
    node_properties: dict
    input_rdf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class InputGraphSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    node_ids: list[str] = Field(min_length=1, max_length=10000)
    base_uri: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rdf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class BusinessOntologyContext(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    uri: str
    terms: list[TermEvidenceAnchor] = Field(max_length=2000)
    concept_references: list[ConceptReference] = Field(
        default_factory=list, max_length=10000
    )
    input_graph: InputGraphSnapshot | None = None

    @field_validator("uri")
    @classmethod
    def valid_uri(cls, value):
        return _iri(value)

    @model_validator(mode="after")
    def valid_concept_references(self):
        if self.concept_references and self.input_graph is None:
            raise ValueError("RDF concept references require an input graph snapshot.")
        if self.input_graph and len(set(self.input_graph.node_ids)) != len(
            self.input_graph.node_ids
        ):
            raise ValueError("Input graph node identities must be unique.")
        classes = {term.uri for term in self.terms if term.type == "owl:Class"}
        seen = set()
        for reference in self.concept_references:
            key = (reference.node_id, reference.class_uri)
            if reference.class_uri not in classes or key in seen:
                raise ValueError(
                    "Concept references need unique nodes/classes owned by this ontology."
                )
            if not reference.rationale.strip():
                raise ValueError("A candidate concept reference needs a rationale.")
            if (
                reference.node_id not in self.input_graph.node_ids
                or reference.input_rdf_sha256 != self.input_graph.rdf_sha256
            ):
                raise ValueError(
                    "Concept reference differs from its input graph identity."
                )
            seen.add(key)
        return self


class OntologyEvidenceContext(BaseModel):
    """A caller-registered citation index, never an equivalence or type assertion."""

    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1]
    business_ontologies: list[BusinessOntologyContext] = Field(max_length=100)
    support_ontologies: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("schema_version", mode="before")
    @classmethod
    def integer_version(cls, value):
        if type(value) is not int:
            raise ValueError("schema_version must be an integer.")
        return value

    @model_validator(mode="after")
    def unique_roles_and_terms(self):
        business = [item.uri for item in self.business_ontologies]
        roles = business + [_iri(uri) for uri in self.support_ontologies]
        terms = [term.uri for item in self.business_ontologies for term in item.terms]
        if len(set(roles)) != len(roles):
            raise ValueError("Ontology roles must be unique and disjoint.")
        if len(set(terms)) != len(terms):
            raise ValueError("Every business term must have one explicit owner.")
        return self


def _source_span(term: dict, text: str) -> tuple[int, int, str]:
    quote = term.get("evidence_quote")
    if not isinstance(quote, str) or not quote.strip():
        raise ValueError("An exact evidence quote is required.")
    if "evidence_lines" in term:
        lines = text.splitlines(keepends=True)
        selection = term["evidence_lines"]
        if (
            not isinstance(selection, list)
            or len(selection) != 2
            or any(type(value) is not int for value in selection)
            or not 1 <= selection[0] <= selection[1] <= len(lines)
        ):
            raise ValueError("Invalid evidence line range.")
        start = sum(map(len, lines[: selection[0] - 1]))
        end = sum(map(len, lines[: selection[1]]))
        if text[start:end] != quote:
            raise ValueError("The quote differs from the selected source lines.")
    else:
        start = text.find(quote)
        if start < 0:
            raise ValueError("The quote is absent from the source.")
        if text.find(quote, start + 1) >= 0:
            raise ValueError("An ambiguous quote needs a unique source line range.")
        end = start + len(quote)
    return start, end, quote


def build_evidence_context(
    ontology: dict,
    turtle: str,
    text: str,
    source_id: str,
    support_ontologies: list[str],
) -> dict:
    """Bind a validated export to exact source occurrences without changing it."""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if ontology.get("metadata", {}).get("source_sha256") != digest:
        raise ValueError("Source hash differs from the ontology proposal.")
    graph = Graph().parse(data=turtle, format="turtle")
    terms = []
    for item in ontology["classes"] + ontology["properties"]:
        subject = URIRef(item["uri"])
        types = [
            kind
            for kind in (OWL.Class, OWL.ObjectProperty, OWL.DatatypeProperty)
            if (subject, RDF.type, kind) in graph
        ]
        if len(types) != 1 or str(graph.value(subject, RDFS.label)) != item["label"]:
            raise ValueError("Exported term identity does not match the proposal.")
        start, end, quote = _source_span(item, text)
        terms.append(
            TermEvidenceAnchor(
                uri=item["uri"],
                label=item["label"],
                type="owl:" + str(types[0]).rsplit("#", 1)[-1],
                comment=str(graph.value(subject, RDFS.comment) or ""),
                domain=sorted(map(str, graph.objects(subject, RDFS.domain))),
                range=sorted(map(str, graph.objects(subject, RDFS.range))),
                parents=sorted(map(str, graph.objects(subject, RDFS.subClassOf))),
                source_id=source_id,
                source_sha256=digest,
                start_char=start,
                end_char=end,
                quote=quote,
            )
        )
    return OntologyEvidenceContext(
        schema_version=1,
        business_ontologies=[BusinessOntologyContext(uri=ontology["uri"], terms=terms)],
        support_ontologies=support_ontologies,
    ).model_dump()
