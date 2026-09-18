"""Native candidate facts, ontology, RDF and SHACL must share term identity."""

from copy import deepcopy
from unittest.mock import patch

import pytest
from rdflib import Graph, OWL, RDF, RDFS, URIRef, XSD
from rdflib.namespace import SH

from semantica.export.rdf_exporter import RDFExporter
from semantica.ontology.engine import OntologyEngine
from semantica.ontology.ontology_generator import OntologyGenerator
from semantica.ontology.owl_generator import OWLGenerator
from semantica.utils.exceptions import ValidationError


VOCAB = "https://semantica.dev/ns#"
PERSON = URIRef("urn:candidate:person")
ORGANIZATION = URIRef("urn:candidate:organization")

TERM_CASES = [
    pytest.param(
        ("PERSON", "ORGANIZATION", "WORKS_FOR"),
        tuple(VOCAB + term for term in ("PERSON", "ORGANIZATION", "WORKS_FOR")),
        None,
        id="bare-uppercase",
    ),
    pytest.param(
        ("BusinessPerson", "BusinessOrganization", "worksFor"),
        tuple(
            VOCAB + term
            for term in ("BusinessPerson", "BusinessOrganization", "worksFor")
        ),
        None,
        id="bare-camel-case",
    ),
    pytest.param(
        (
            "https://people.example.test/types/PERSON",
            "https://companies.example.test/types/Organization",
            "https://relations.example.test/worksFor",
        ),
        (
            "https://people.example.test/types/PERSON",
            "https://companies.example.test/types/Organization",
            "https://relations.example.test/worksFor",
        ),
        None,
        id="full-iris",
    ),
    pytest.param(
        tuple(
            "https://example.test/schema#" + term
            for term in ("Person", "Organization", "worksFor")
        ),
        tuple(
            "https://example.test/schema#" + term
            for term in ("Person", "Organization", "worksFor")
        ),
        None,
        id="hash-namespace",
    ),
    pytest.param(
        tuple(
            "https://example.test/schema/" + term
            for term in ("Person", "Organization", "worksFor")
        ),
        tuple(
            "https://example.test/schema/" + term
            for term in ("Person", "Organization", "worksFor")
        ),
        None,
        id="slash-namespace",
    ),
    pytest.param(
        ("business:PERSON", "business:ORGANIZATION", "business:WORKS_FOR"),
        tuple(
            "https://example.test/business#" + term
            for term in ("PERSON", "ORGANIZATION", "WORKS_FOR")
        ),
        {"business": "https://example.test/business#"},
        id="context-curies",
    ),
]


@pytest.fixture
def provider():
    with patch(
        "semantica.ontology.llm_generator.create_provider", autospec=True
    ) as factory:
        yield factory.return_value


def _facts(terms, context=None):
    data = {
        "entities": [
            {"id": str(PERSON), "type": terms[0], "text": "Alice"},
            {"id": str(ORGANIZATION), "type": terms[1], "text": "Acme"},
        ],
        "relationships": [
            {"source_id": str(PERSON), "target_id": str(ORGANIZATION), "type": terms[2]}
        ],
    }
    if context is not None:
        data["@context"] = context
    return data


def _proposal(iris, names=("Person", "Organization", "worksFor")):
    return {
        "name": "Candidate ontology",
        "classes": [
            {
                "name": name,
                "uri": iri,
                "label": name,
                "comment": "Observed candidate type.",
                "subClassOf": None,
            }
            for name, iri in zip(names[:2], iris[:2])
        ],
        "properties": [
            {
                "name": names[2],
                "uri": iris[2],
                "label": names[2],
                "comment": "Observed candidate relationship.",
                "type": "object",
                "domain": [iris[0]],
                "range": [iris[1]],
            },
            {
                "name": "text",
                "uri": VOCAB + "text",
                "label": "Text",
                "comment": "Candidate display text.",
                "type": "data",
                "domain": [],
                "range": [str(XSD.string)],
            },
            {
                "name": "confidence",
                "uri": VOCAB + "confidence",
                "label": "Confidence",
                "comment": "Extraction confidence, not business approval.",
                "type": "data",
                "domain": [],
                "range": [str(XSD.decimal)],
            },
        ],
    }


def _generate(data, proposal, provider, entrypoint="generator"):
    provider.generate_structured.return_value = proposal
    if entrypoint == "engine":
        return OntologyEngine(provider="openai", model="test").from_data(
            data, method="llm", min_occurrences=99
        )
    return OntologyGenerator(provider="openai", model="test").generate_ontology(
        data, method="llm", min_occurrences=99
    )


@pytest.mark.parametrize("entrypoint", ["generator", "engine"])
@pytest.mark.parametrize("terms,iris,context", TERM_CASES)
def test_candidate_ontology_rdf_and_validation_share_observed_identity(
    provider, entrypoint, terms, iris, context
):
    data = _facts(terms, context)
    before = deepcopy(data)
    ontology = _generate(data, _proposal(iris), provider, entrypoint)
    provider.generate_structured.assert_called_once()

    graph = Graph().parse(data=RDFExporter().export_to_rdf(data), format="turtle")
    schema = Graph().parse(data=OWLGenerator().generate_owl(ontology), format="turtle")
    expected_classes = {URIRef(iri) for iri in iris[:2]}
    predicate = URIRef(iris[2])
    assert set(graph.objects(None, RDF.type)) == expected_classes
    assert set(schema.subjects(RDF.type, OWL.Class)) == expected_classes
    assert (PERSON, predicate, ORGANIZATION) in graph
    assert (predicate, RDF.type, OWL.ObjectProperty) in schema
    assert set(schema.objects(predicate, RDFS.domain)) == {URIRef(iris[0])}
    assert set(schema.objects(predicate, RDFS.range)) == {URIRef(iris[1])}
    declared_predicates = set(schema.subjects(RDF.type, OWL.ObjectProperty)) | set(
        schema.subjects(RDF.type, OWL.DatatypeProperty)
    )
    assert set(graph.predicates()) - {RDF.type} == declared_predicates

    engine = OntologyEngine(provider="openai", model="test")
    shapes = Graph().parse(data=engine.to_shacl(ontology), format="turtle")
    assert set(shapes.objects(None, SH.targetClass)) == expected_classes
    source_shape = next(shapes.subjects(SH.targetClass, URIRef(iris[0])))
    relation_shapes = [
        shape
        for shape in shapes.objects(source_shape, SH.property)
        if (shape, SH.path, predicate) in shapes
    ]
    assert len(relation_shapes) == 1
    assert (relation_shapes[0], SH["class"], URIRef(iris[1])) in shapes
    focus_nodes = {
        subject
        for target in shapes.objects(None, SH.targetClass)
        for subject in graph.subjects(RDF.type, target)
    }
    assert focus_nodes == {PERSON, ORGANIZATION}
    report = engine.validate_graph(graph, ontology=ontology)
    assert report.conforms
    assert not report.violations
    assert report.coverage["focus_node_count"] == 2
    assert report.coverage["constrained_focus_node_count"] > 0
    assert report.coverage["constraint_count"] > 0

    # One corrupted relationship must reach an actual SHACL constraint.
    graph.remove((PERSON, predicate, ORGANIZATION))
    graph.add((PERSON, predicate, PERSON))
    invalid = engine.validate_graph(graph, ontology=ontology)
    assert not invalid.conforms
    assert invalid.coverage["constrained_focus_node_count"] > 0
    assert any(
        violation.constraint.endswith("ClassConstraintComponent")
        and violation.focus_node == str(PERSON)
        and violation.result_path == str(predicate)
        and violation.class_ == iris[1]
        for violation in invalid.violations
    )
    assert data == before
    assert ontology["metadata"]["fact_status"] == "candidate"
    assert ontology["metadata"]["review_status"] == "unreviewed"


def test_material_requirement_is_preserved_without_asserting_a_contract(provider):
    terms = ("ProcessRule", "RequiredDocument", "requiresDocument")
    iris = tuple(VOCAB + term for term in terms)
    data = _facts(terms)
    data["entities"][1]["text"] = "合法有效的合同"
    for entity in data["entities"]:
        entity.update(fact_status="candidate", review_status="unreviewed")
    before = deepcopy(data)
    original_rdf = Graph().parse(
        data=RDFExporter().export_to_rdf(data), format="turtle"
    )

    ontology = _generate(data, _proposal(iris, terms), provider)
    exported = Graph().parse(data=RDFExporter().export_to_rdf(data), format="turtle")
    assert set(exported) == set(original_rdf)
    assert set(exported.objects(ORGANIZATION, RDF.type)) == {URIRef(iris[1])}
    assert {item["uri"] for item in ontology["classes"]} == set(iris[:2])
    assert ontology["metadata"]["fact_status"] == "candidate"
    assert ontology["metadata"]["review_status"] == "unreviewed"
    assert data == before


def test_model_cannot_replace_a_requirement_type_with_an_unobserved_contract(provider):
    terms = ("ProcessRule", "RequiredDocument", "requiresDocument")
    iris = tuple(VOCAB + term for term in terms)
    data = _facts(terms)
    data["entities"][1]["text"] = "合法有效的合同"
    before = deepcopy(data)
    proposal = _proposal(iris, terms)
    proposal["classes"][1].update(name="Contract", uri=VOCAB + "Contract")

    with pytest.raises(ValidationError):
        _generate(data, proposal, provider)
    assert data == before
