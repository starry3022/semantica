"""OWL vocabulary references preserve the same identity as candidate RDF."""

from copy import deepcopy

import pytest
from rdflib import Graph, OWL, RDF, RDFS, URIRef, XSD

from semantica.ontology.owl_generator import OWLGenerator


BASE = "https://example.test/ontology/"


def ontology(namespace):
    return {
        "uri": BASE,
        "name": "SharedVocabulary",
        "version": "1.0",
        "classes": [
            {
                "name": "Person",
                "uri": namespace + "Person",
                "subClassOf": namespace + "Agent",
            },
            {"name": "Agent", "uri": namespace + "Agent"},
            {"name": "Organization", "uri": namespace + "Organization"},
        ],
        "properties": [
            {
                "name": "worksFor",
                "uri": namespace + "worksFor",
                "type": "object",
                "domain": [namespace + "Person"],
                "range": [namespace + "Organization"],
            },
            {
                "name": "employeeCode",
                "uri": namespace + "employeeCode",
                "type": "data",
                "domain": [namespace + "Person"],
                "range": [namespace + "EmployeeCode"],
            },
        ],
    }


@pytest.mark.parametrize("format,parser", [("turtle", "turtle"), ("rdfxml", "xml")])
def test_urn_declarations_and_all_references_keep_their_absolute_iris(format, parser):
    namespace = "urn:example:"
    draft = ontology(namespace)
    before = deepcopy(draft)
    graph = Graph().parse(
        data=OWLGenerator().generate_owl(draft, format=format), format=parser
    )
    person = URIRef(namespace + "Person")
    agent = URIRef(namespace + "Agent")
    organization = URIRef(namespace + "Organization")
    works_for = URIRef(namespace + "worksFor")
    employee_code = URIRef(namespace + "employeeCode")
    assert (person, RDF.type, OWL.Class) in graph
    assert (works_for, RDF.type, OWL.ObjectProperty) in graph
    assert (employee_code, RDF.type, OWL.DatatypeProperty) in graph
    assert (person, RDFS.subClassOf, agent) in graph
    assert (works_for, RDFS.domain, person) in graph
    assert (works_for, RDFS.range, organization) in graph
    assert (employee_code, RDFS.domain, person) in graph
    assert (employee_code, RDFS.range, URIRef(namespace + "EmployeeCode")) in graph
    assert not any(str(node).startswith(BASE + "Urn") for node in graph.all_nodes())
    assert draft == before


@pytest.mark.parametrize(
    "namespace", ["https://example.test/vocab#", "http://example.test/vocab/"]
)
@pytest.mark.parametrize("format,parser", [("turtle", "turtle"), ("rdfxml", "xml")])
def test_http_hash_and_slash_vocabulary_identity_is_preserved(
    namespace, format, parser
):
    graph = Graph().parse(
        data=OWLGenerator().generate_owl(ontology(namespace), format=format),
        format=parser,
    )
    assert (
        URIRef(namespace + "Person"),
        RDFS.subClassOf,
        URIRef(namespace + "Agent"),
    ) in graph
    assert (
        URIRef(namespace + "worksFor"),
        RDFS.domain,
        URIRef(namespace + "Person"),
    ) in graph
    assert (
        URIRef(namespace + "worksFor"),
        RDFS.range,
        URIRef(namespace + "Organization"),
    ) in graph


@pytest.mark.parametrize("format,parser", [("turtle", "turtle"), ("rdfxml", "xml")])
def test_known_curie_references_expand_before_absolute_scheme_detection(format, parser):
    draft = ontology("urn:example:")
    draft["classes"][0]["subClassOf"] = "owl:Thing"
    draft["properties"][0]["domain"] = ["rdfs:Resource"]
    draft["properties"][0]["range"] = ["owl:Thing"]
    draft["properties"][1]["range"] = ["xsd:string"]
    graph = Graph().parse(
        data=OWLGenerator().generate_owl(draft, format=format), format=parser
    )
    assert (URIRef("urn:example:Person"), RDFS.subClassOf, OWL.Thing) in graph
    assert (URIRef("urn:example:worksFor"), RDFS.domain, RDFS.Resource) in graph
    assert (URIRef("urn:example:worksFor"), RDFS.range, OWL.Thing) in graph
    assert (URIRef("urn:example:employeeCode"), RDFS.range, XSD.string) in graph


def test_basic_turtle_fallback_keeps_urn_references(monkeypatch):
    import semantica.ontology.owl_generator as owl_module

    monkeypatch.setattr(owl_module, "HAS_RDFLIB", False)
    graph = Graph().parse(
        data=OWLGenerator().generate_owl(ontology("urn:example:")), format="turtle"
    )
    assert (
        URIRef("urn:example:Person"),
        RDFS.subClassOf,
        URIRef("urn:example:Agent"),
    ) in graph
    assert (
        URIRef("urn:example:worksFor"),
        RDFS.range,
        URIRef("urn:example:Organization"),
    ) in graph
    assert (
        URIRef("urn:example:employeeCode"),
        RDFS.range,
        URIRef("urn:example:EmployeeCode"),
    ) in graph
