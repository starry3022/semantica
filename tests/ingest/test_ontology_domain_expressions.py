"""Anonymous domain/range expressions survive the native ontology projection."""

import pytest
from rdflib import BNode, Graph, Literal, Namespace, RDF, RDFS, OWL, XSD
from rdflib.compare import isomorphic

from semantica.ingest.ontology_ingestor import OntologyIngestor
from semantica.semantic_extract.process_graph import process_rule_ontology

EX = Namespace("https://example.org/expressions/")
PREFIXES = """
@prefix : <https://example.org/expressions/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
:Ontology a owl:Ontology .
:A a owl:Class . :B a owl:Class . :C a owl:Class .
"""


def ingest(content, tmp_path):
    path = tmp_path / "expressions.ttl"
    path.write_text(content, encoding="utf-8")
    return OntologyIngestor().ingest_ontology(path).data


def by_uri(data, uri):
    return next(prop for prop in data["properties"] if prop["uri"] == str(uri))


def test_process_vocabulary_retains_the_three_role_attributes(tmp_path):
    graph = process_rule_ontology(base_uri=str(EX), label_language="zh")
    before = set(graph)
    data = ingest(graph.serialize(format="turtle"), tmp_path)
    assert len(data["classes"]) == 9
    role_properties = {
        prop["uri"]
        for prop in data["properties"]
        for expression in prop.get("domain_expressions", [])
        if str(EX.Role) in expression.get("members", [])
    }
    assert role_properties == {str(EX.name), str(EX.fact_status), str(EX.review_status)}
    assert by_uri(data, EX.name)["domain_expressions"] == [
        {
            "kind": "unionOf",
            "members": [str(EX.Activity), str(EX.Role), str(EX.RequiredDocument)],
        }
    ]
    assert "domain" not in by_uri(data, EX.name)
    assert set(graph) == before


def test_direct_declarations_and_union_expressions_remain_separate(tmp_path):
    data = ingest(
        PREFIXES
        + """
        :object a owl:ObjectProperty ;
            rdfs:domain :A, :B, [a owl:Class; owl:unionOf (:B :C)] ;
            rdfs:range [owl:unionOf (:A :C)] .
        :data a owl:DatatypeProperty ;
            rdfs:domain :A ;
            rdfs:range [a rdfs:Datatype; owl:unionOf (xsd:string xsd:integer)] .
        :simple a owl:DatatypeProperty ; rdfs:domain :A ; rdfs:range xsd:string .
        """,
        tmp_path,
    )
    object_property = by_uri(data, EX.object)
    assert object_property["domain"] == [str(EX.A), str(EX.B)]
    assert object_property["domain_expressions"] == [
        {"kind": "unionOf", "members": [str(EX.B), str(EX.C)]}
    ]
    assert object_property["range_expressions"] == [
        {"kind": "unionOf", "members": [str(EX.A), str(EX.C)]}
    ]
    assert "range" not in object_property
    assert by_uri(data, EX.data)["range_expressions"] == [
        {"kind": "unionOf", "members": [str(XSD.string), str(XSD.integer)]}
    ]
    assert "domain_expressions" not in by_uri(data, EX.simple)
    assert "range_expressions" not in by_uri(data, EX.simple)


@pytest.mark.parametrize(
    "expression",
    [
        "_:root owl:unionOf _:list . _:list rdf:first :A ; rdf:rest _:list .",
        "_:root owl:unionOf _:list . _:list rdf:first :A .",
        "_:root owl:unionOf _:list . _:list rdf:first :A, :B ; rdf:rest rdf:nil .",
        "_:root owl:unionOf ([:nested '保留'@zh] :B) .",
        "_:root a owl:Restriction ; owl:onProperty :object ; owl:someValuesFrom :A .",
        "_:root owl:unionOf (:A :B) ; owl:intersectionOf (:B :C) .",
    ],
)
def test_unsupported_or_malformed_expressions_keep_opaque_rdf(expression, tmp_path):
    content = (
        PREFIXES + ":object a owl:ObjectProperty ; rdfs:domain _:root . " + expression
    )
    original = Graph().parse(data=content, format="turtle")
    data = ingest(content, tmp_path)
    prop = by_uri(data, EX.object)
    assert "domain" not in prop
    opaque = prop["domain_expressions"][0]
    assert opaque["kind"] == "unsupported"
    assert opaque["reason"]
    assert "members" not in opaque
    assert opaque["rdf_format"] == "nt"
    restored = Graph().parse(data=opaque["rdf"], format=opaque["rdf_format"])
    expected = Graph()
    for triple in original:
        if isinstance(triple[0], BNode) or triple[:2] == (EX.object, RDFS.domain):
            expected.add(triple)
    assert isomorphic(restored, expected)
    assert opaque["root"].startswith("_:")


def test_opaque_rdf_keeps_unicode_line_separators_inside_literals(tmp_path):
    graph = Graph()
    root = BNode()
    note = Literal("第一行\u2028第二行\u0085第三行\u2029结尾😀", lang="zh")
    graph.add((EX.object, RDF.type, OWL.ObjectProperty))
    graph.add((EX.object, RDFS.domain, root))
    graph.add((root, RDF.type, OWL.Restriction))
    graph.add((root, RDFS.comment, note))
    data = ingest(graph.serialize(format="turtle"), tmp_path)
    opaque = by_uri(data, EX.object)["domain_expressions"][0]
    restored = Graph().parse(data=opaque["rdf"], format="nt")
    assert list(restored.objects(None, RDFS.comment)) == [note]


def test_oversized_expression_is_rejected_without_partial_payload(tmp_path):
    graph = Graph()
    root = BNode()
    graph.add((EX.object, RDF.type, OWL.ObjectProperty))
    graph.add((EX.object, RDFS.domain, root))
    graph.add((root, EX.note, Literal("x" * (1024 * 1024))))
    with pytest.raises(Exception, match="expression.*limit"):
        ingest(graph.serialize(format="turtle"), tmp_path)


def test_opaque_rdf_preserves_multiline_literals_and_literal_metadata(tmp_path):
    graph = Graph()
    root = BNode()
    graph.add((EX.object, RDF.type, OWL.ObjectProperty))
    graph.add((EX.object, RDFS.domain, root))
    graph.add((root, RDF.type, OWL.Restriction))
    graph.add((root, OWL.onProperty, EX.object))
    graph.add((root, EX.note, Literal('第一行\n"引号"和\\反斜线😀', lang="zh")))
    graph.add((root, EX.code, Literal('line1\n"line2"\\😀', datatype=XSD.string)))
    data = ingest(graph.serialize(format="turtle"), tmp_path)
    opaque = by_uri(data, EX.object)["domain_expressions"][0]
    restored = Graph().parse(data=opaque["rdf"], format=opaque["rdf_format"])
    expected = Graph()
    for triple in graph:
        if isinstance(triple[0], BNode) or triple[:2] == (EX.object, RDFS.domain):
            expected.add(triple)
    assert isomorphic(restored, expected)
