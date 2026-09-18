"""Native generated-shape contracts, exercised by real RDF parsing and pySHACL."""

import pytest

pytest.importorskip("pyshacl")
rdflib = pytest.importorskip("rdflib")

from rdflib import Graph, Literal, Namespace, RDF, XSD  # noqa: E402

from semantica.ontology.ontology_generator import SHACLGenerator  # noqa: E402
from semantica.ontology.ontology_validator import run_shacl_validation  # noqa: E402

EX = Namespace("https://example.org/business#")
SH = Namespace("http://www.w3.org/ns/shacl#")


def _ontology():
    return {
        "namespace": {"base_uri": str(EX)},
        "classes": [{"name": "Person", "uri": str(EX.Person)}],
        "properties": [
            {
                "name": "name",
                "uri": str(EX.name),
                "type": "data",
                "domain": [str(EX.Person)],
                "range": ["string"],
                "required": True,
            }
        ],
    }


def _serialize(ontology, format="turtle"):
    generator = SHACLGenerator()
    return generator.serialize(generator.generate(ontology), format)


@pytest.mark.parametrize("format", ["turtle", "json-ld", "nt"])
@pytest.mark.parametrize("domain", [str(EX.Person), [str(EX.Person)]])
def test_full_iri_domain_keeps_required_property_constraint(format, domain):
    ontology = _ontology()
    ontology["properties"][0]["domain"] = domain
    report = run_shacl_validation(
        f"<{EX.alice}> a <{EX.Person}> .",
        _serialize(ontology, format),
        shacl_format=format,
    )
    assert not report.conforms
    assert [(v.focus_node, v.result_path, v.constraint) for v in report.violations] == [
        (str(EX.alice), str(EX.name), "MinCountConstraintComponent")
    ]


@pytest.mark.parametrize("parent_key", ["parent", "parent_class", "subClassOf"])
@pytest.mark.parametrize("parent", [str(EX.Person), [str(EX.Person)]])
def test_full_iri_parent_attaches_inherited_constraint(parent_key, parent):
    ontology = _ontology()
    ontology["properties"][0]["domain"] = "Person"
    ontology["classes"].append(
        {
            "name": "Employee",
            "uri": str(EX.Employee),
            parent_key: parent,
        }
    )
    report = run_shacl_validation(
        f"<{EX.alice}> a <{EX.Employee}> .", _serialize(ontology)
    )
    assert not report.conforms
    assert any(v.result_path == str(EX.name) for v in report.violations)


@pytest.mark.parametrize("format", ["turtle", "json-ld", "nt"])
@pytest.mark.parametrize("datatype", ["string", "xsd:string", str(XSD.string)])
def test_datatype_alias_prefixed_and_absolute_iri_have_same_semantics(format, datatype):
    ontology = _ontology()
    ontology["properties"][0].update(domain="Person", range=[datatype])
    shapes = _serialize(ontology, format)
    parsed = Graph().parse(data=shapes, format=format)
    assert set(parsed.objects(None, SH.datatype)) == {XSD.string}
    valid = f'<{EX.alice}> a <{EX.Person}> ; <{EX.name}> "Alice" .'
    assert run_shacl_validation(valid, shapes, shacl_format=format).conforms
    invalid = f"<{EX.alice}> a <{EX.Person}> ; <{EX.name}> 12 ."
    report = run_shacl_validation(invalid, shapes, shacl_format=format)
    assert not report.conforms
    assert any(v.constraint == "DatatypeConstraintComponent" for v in report.violations)


@pytest.mark.parametrize("format", ["turtle", "json-ld", "nt"])
def test_generated_shape_labels_preserve_quotes_unicode_and_newlines(format):
    ontology = _ontology()
    label = '人员 "申请人"\n第二行\\来源'
    ontology["classes"][0].update(label=label, comment=label)
    shapes = Graph().parse(data=_serialize(ontology, format), format=format)
    shape = next(shapes.subjects(RDF.type, SH.NodeShape))
    assert shapes.value(shape, SH.name) == Literal(label)
    if format != "nt":  # N-Triples currently has no description export contract.
        assert shapes.value(shape, SH.description) == Literal(label)


def _shapes(body):
    return f"""
@prefix ex: <{EX}> .
@prefix sh: <{SH}> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
{body}
"""


def _issue_codes(report):
    return {issue["code"] for issue in report.technical_issues}


def test_unmatched_shapes_keep_conformance_but_expose_missing_coverage():
    report = run_shacl_validation(
        f'<{EX.alice}> a <{EX.Person}> ; <{EX.name}> "Alice" .',
        _shapes(
            """
ex:Shape a sh:NodeShape ; sh:targetClass ex:DifferentPerson ;
    sh:property [ sh:path ex:required ; sh:minCount 1 ] .
"""
        ),
    )
    assert report.conforms
    assert report.violations == report.warnings == report.infos == []
    assert report.coverage["focus_node_count"] == 0
    assert report.coverage["constrained_focus_node_count"] == 0
    assert report.coverage["unmatched_target_classes"] == [str(EX.DifferentPerson)]
    assert report.coverage["untargeted_data_classes"] == [str(EX.Person)]
    assert report.coverage["undeclared_predicates"] == [str(EX.name)]
    assert "no_focus_nodes" in _issue_codes(report)
    assert "coverage" in report.summary().lower()
    assert report.to_dict()["coverage"] == report.coverage
    assert report.to_dict()["technical_issues"] == report.technical_issues


@pytest.mark.parametrize(
    "constraints",
    [
        "",
        "sh:property [ sh:path ex:name ] ;",
        "sh:closed false ; sh:property [ sh:path ex:name ; sh:minCount 0 ] ;",
        "sh:property [ sh:path ex:name ; sh:minCount 1 ; sh:deactivated true ] ;",
    ],
)
def test_target_only_or_inert_shapes_expose_no_effective_constraints(constraints):
    report = run_shacl_validation(
        f"<{EX.alice}> a <{EX.Person}> .",
        _shapes(f"ex:Shape a sh:NodeShape ; {constraints} sh:targetClass ex:Person ."),
    )
    assert report.conforms
    assert report.coverage["focus_node_count"] == 1
    assert report.coverage["constraint_count"] == 0
    assert report.coverage["constrained_focus_node_count"] == 0
    assert "no_effective_constraints" in _issue_codes(report)
    assert "coverage" in report.summary().lower()


def test_generated_required_shapes_have_real_nonzero_coverage():
    report = run_shacl_validation(
        f'<{EX.alice}> a <{EX.Person}> ; <{EX.name}> "Alice" .',
        _serialize(_ontology()),
    )
    assert report.conforms
    assert report.coverage["target_shape_count"] == 1
    assert report.coverage["constraint_count"] == 2
    assert report.coverage["focus_node_count"] == 1
    assert report.coverage["constrained_focus_node_count"] == 1
    assert report.coverage["target_resolution_complete"]
    assert report.coverage["evaluation_complete"]
    assert report.technical_issues == []


def test_empty_data_keeps_standard_conformance_and_explicit_empty_coverage():
    report = run_shacl_validation("", _serialize(_ontology()))
    assert report.conforms
    assert report.violations == []
    assert report.coverage["data_triple_count"] == 0
    assert report.coverage["focus_node_count"] == 0
    assert "empty_data_graph" in _issue_codes(report)


def test_target_class_coverage_includes_transitive_data_subclasses():
    data = f"""
@prefix ex: <{EX}> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
ex:Employee rdfs:subClassOf ex:Worker .
ex:Worker rdfs:subClassOf ex:Person .
ex:alice a ex:Employee .
"""
    report = run_shacl_validation(data, _serialize(_ontology()))
    assert not report.conforms
    assert report.coverage["focus_node_count"] == 1
    assert report.coverage["constrained_focus_node_count"] == 1
    assert report.coverage["unmatched_target_classes"] == []
    assert report.coverage["untargeted_data_classes"] == []


def test_explicit_target_node_is_counted_even_when_absent_from_data():
    report = run_shacl_validation(
        "",
        _shapes(
            """
ex:Shape a sh:NodeShape ; sh:targetNode ex:alice ;
    sh:property [ sh:path ex:name ; sh:minCount 1 ] .
"""
        ),
    )
    assert not report.conforms
    assert report.coverage["focus_node_count"] == 1
    assert report.coverage["constrained_focus_node_count"] == 1
    assert report.violations[0].focus_node == str(EX.alice)


def test_subjects_and_objects_targets_count_distinct_focus_nodes():
    report = run_shacl_validation(
        f"<{EX.alice}> <{EX.knows}> <{EX.bob}> .",
        _shapes(
            """
ex:Subjects a sh:NodeShape ; sh:targetSubjectsOf ex:knows ; sh:nodeKind sh:IRI .
ex:Objects a sh:NodeShape ; sh:targetObjectsOf ex:knows ; sh:nodeKind sh:IRI .
"""
        ),
    )
    assert report.conforms
    assert report.coverage["target_shape_count"] == 2
    assert report.coverage["focus_node_count"] == 2
    assert report.coverage["constrained_focus_node_count"] == 2
    assert report.coverage["target_resolution_complete"]


def test_implicit_class_target_matches_native_pyshacl():
    report = run_shacl_validation(
        f"<{EX.alice}> a <{EX.Person}> .",
        _shapes(
            """
ex:Person a sh:NodeShape, rdfs:Class ;
    sh:property [ sh:path ex:name ; sh:minCount 1 ] .
"""
        ),
    )
    assert not report.conforms
    assert report.coverage["target_shape_count"] == 1
    assert report.coverage["focus_node_count"] == 1


def test_deactivated_target_shape_does_not_claim_coverage():
    report = run_shacl_validation(
        f"<{EX.alice}> a <{EX.Person}> .",
        _shapes(
            """
ex:Shape a sh:NodeShape ; sh:targetClass ex:Person ; sh:deactivated true ;
    sh:property [ sh:path ex:name ; sh:minCount 1 ] .
"""
        ),
    )
    assert report.conforms
    assert report.coverage["target_shape_count"] == 0
    assert report.coverage["focus_node_count"] == 0
    assert report.coverage["constraint_count"] == 0


def test_advanced_targets_are_marked_unsupported_in_coverage():
    report = run_shacl_validation(
        f"<{EX.alice}> a <{EX.Person}> .",
        _shapes(
            """
ex:Shape a sh:NodeShape ; sh:target [ a sh:SPARQLTarget ;
    sh:select "SELECT ?this WHERE { ?this ?p ?o }" ] ; sh:nodeKind sh:IRI .
"""
        ),
    )
    assert report.conforms
    assert not report.coverage["target_resolution_complete"]
    assert report.coverage["unsupported_targets"]
    assert "unsupported_targets" in _issue_codes(report)


def test_abort_on_first_marks_partial_evaluation_without_inventing_violations():
    from semantica.ontology.ontology_validator import _run_pyshacl

    data = f"<{EX.alice}> a <{EX.Person}> . <{EX.acme}> a <{EX.Organization}> ."
    shapes = _shapes(
        """
ex:PersonShape a sh:NodeShape ; sh:targetClass ex:Person ;
    sh:property [ sh:path ex:name ; sh:minCount 1 ] .
ex:OrgShape a sh:NodeShape ; sh:targetClass ex:Organization ;
    sh:property [ sh:path ex:name ; sh:minCount 1 ] .
"""
    )
    complete = run_shacl_validation(data, shapes)
    partial = _run_pyshacl(data, shapes, abort_on_first=True)
    assert not complete.conforms and not partial.conforms
    assert complete.violation_count == 2
    assert partial.violation_count < complete.violation_count
    assert complete.coverage["evaluation_complete"]
    assert not partial.coverage["evaluation_complete"]
    assert partial.coverage["focus_node_count"] == 2
    assert "validation_incomplete" in _issue_codes(partial)
    assert "partial" in partial.summary().lower()


def test_unmatched_constraints_do_not_cover_an_unconstrained_matching_shape():
    report = run_shacl_validation(
        f"<{EX.alice}> a <{EX.Person}> .",
        _shapes(
            """
ex:Empty a sh:NodeShape ; sh:targetClass ex:Person .
ex:Other a sh:NodeShape ; sh:targetClass ex:Organization ;
    sh:property [ sh:path ex:name ; sh:minCount 1 ] .
"""
        ),
    )
    assert report.conforms
    assert report.coverage["focus_node_count"] == 1
    assert report.coverage["constraint_count"] == 1
    assert report.coverage["constrained_focus_node_count"] == 0
    assert "no_constrained_focus_nodes" in _issue_codes(report)


@pytest.mark.parametrize("nested", ["", "sh:deactivated true ; sh:minCount 1"])
def test_empty_or_deactivated_node_reference_is_not_an_effective_constraint(nested):
    report = run_shacl_validation(
        f"<{EX.alice}> a <{EX.Person}> .",
        _shapes(
            f"ex:Shape a sh:NodeShape ; sh:targetClass ex:Person ; sh:node [ {nested} ] ."
        ),
    )
    assert report.conforms
    assert report.coverage["constraint_count"] == 0
    assert report.coverage["constrained_focus_node_count"] == 0
    assert "no_effective_constraints" in _issue_codes(report)


def test_successful_abort_option_does_not_mark_evaluation_incomplete():
    report = run_shacl_validation(
        f'<{EX.alice}> a <{EX.Person}> ; <{EX.name}> "Alice" .',
        _serialize(_ontology()),
        abort_on_first=True,
    )
    assert report.conforms
    assert report.coverage["evaluation_complete"]
    assert "validation_incomplete" not in _issue_codes(report)
