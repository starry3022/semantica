"""Qualified candidate RDF preserves assertions without asserting their contents."""

import json
from copy import deepcopy

import pytest
from rdflib import RDF, XSD, Graph, Literal, Namespace, URIRef

from semantica.utils.exceptions import ValidationError

EX = Namespace("https://example.test/domain/")
SEM = Namespace("https://semantica.dev/ns#")


@pytest.mark.parametrize(
    "reserved", [RDF.Statement, RDF.subject, RDF.predicate, RDF.object]
)
@pytest.mark.parametrize("field", ["type", "id", "assertion_id", "class"])
def test_reification_vocabulary_cannot_enter_business_schema(reserved, field):
    from semantica.ontology.candidate_ontology import build_candidate_prompt

    data = facts()
    if field == "type":
        data["relationships"][0][field] = str(reserved)
    elif field == "id":
        data["entities"][0][field] = str(reserved)
        data["relationships"][0]["source_id"] = str(reserved)
    elif field == "class":
        data["entities"][0]["type"] = str(reserved)
    else:
        data["relationships"][0]["id"] = str(reserved)
    with pytest.raises(ValidationError, match="transport|collide"):
        build_candidate_prompt(data, qualified_statements=True)


def facts():
    return {
        "@context": {"ex": str(EX)},
        "entities": [
            {"id": "ex:role", "type": "ex:Role", "text": "审核角色", "confidence": 0.8},
            {"id": "ex:request", "type": "ex:Request", "text": "申请", "confidence": 0.7},
        ],
        "relationships": [
            {
                "id": "urn:test:review-1",
                "source_id": "ex:role",
                "target_id": "ex:request",
                "type": "ex:reviews",
                "confidence": 0.9,
                "metadata": {"condition": "材料完整时", "modality": "可以", "negation": False},
            }
        ],
        "metadata": {"fact_status": "candidate", "review_status": "unreviewed"},
    }


def test_qualified_relations_are_named_statements_not_asserted_business_triples():
    from semantica.ontology.candidate_statements import prepare_candidate_statements

    data = facts()
    original = deepcopy(data)
    result = prepare_candidate_statements(data)
    graph = Graph().parse(data=result.rdf, format="turtle")
    assertion = URIRef("urn:test:review-1")

    assert (assertion, RDF.type, RDF.Statement) in graph
    assert (assertion, RDF.subject, EX.role) in graph
    assert (assertion, RDF.predicate, EX.reviews) in graph
    assert (assertion, RDF.object, EX.request) in graph
    assert (EX.role, EX.reviews, EX.request) not in graph
    assert (EX.role, EX.reviews, EX.request) in result.projection.graph
    assert (EX.role, RDF.type, EX.Role) in graph
    assert (EX.role, SEM.text, Literal("审核角色")) in graph
    assert (EX.role, SEM.confidence, Literal("0.8", datatype=XSD.decimal)) in graph
    assert result.assertion_ids == [str(assertion)]
    assert set(graph) == set(result.prepared.graph)
    assert data == original


def test_qualifiers_evidence_and_unknown_metadata_are_losslessly_transported():
    from semantica.ontology.candidate_statements import (
        CANDIDATE_NS,
        REPRESENTATION,
        prepare_candidate_statements,
    )

    data = facts()
    evidence = {
        "quote": "😀条件\r\n正文",
        "source_id": "policy",
        "source_sha256": "a" * 64,
        "start_char": 5,
        "end_char": 13,
        "start_line": 2,
        "end_line": 3,
        "status": "citation_aligned",
        "span_origin": "program_from_selected_lines",
        "custom": {"nested": [None, False, "值"]},
    }
    relation = data["relationships"][0]
    relation["metadata"].update(evidence=[evidence], unknown={"review": None})
    data["entities"][0]["metadata"] = {"evidence": [evidence], "custom": [1, 2]}
    data["metadata"]["unknown"] = {"key": None}
    data["extra"] = {"original": True}
    result = prepare_candidate_statements(data)
    graph = result.prepared.graph
    candidate = Namespace(CANDIDATE_NS)
    assertion = URIRef(result.assertion_ids[0])

    assert (assertion, candidate.condition, Literal("材料完整时")) in graph
    assert (assertion, candidate.modality, Literal("可以")) in graph
    assert (assertion, candidate.negation, Literal(False)) in graph
    assert (
        assertion,
        candidate.confidence,
        Literal("0.9", datatype=XSD.decimal),
    ) in graph
    assert json.loads(str(graph.value(assertion, candidate.recordJson))) == relation
    assert (
        json.loads(str(graph.value(EX.role, candidate.recordJson)))
        == data["entities"][0]
    )
    document = next(graph.subjects(RDF.type, candidate.CandidateDataset))
    assert json.loads(str(graph.value(document, candidate.recordJson))) == {
        "@context": data["@context"],
        "metadata": data["metadata"],
        "extra": data["extra"],
    }
    assert (document, candidate.representation, Literal(REPRESENTATION)) in graph
    evidence_node = graph.value(assertion, candidate.hasEvidence)
    assert isinstance(evidence_node, URIRef)
    assert (EX.role, candidate.hasEvidence, evidence_node) in graph
    assert (evidence_node, candidate.quote, Literal(evidence["quote"])) in graph
    assert (evidence_node, candidate.startChar, Literal(5)) in graph
    assert (evidence_node, candidate.sourceId, Literal("policy")) in graph
    assert (evidence_node, candidate.sourceSha256, Literal("a" * 64)) in graph
    assert json.loads(str(graph.value(evidence_node, candidate.recordJson))) == evidence


@pytest.mark.parametrize("corruption", ["removed", "qualifier", "bare", "malformed"])
def test_preservation_validation_rejects_missing_changed_or_extra_graph_content(
    corruption,
):
    from semantica.ontology.candidate_statements import (
        CANDIDATE_NS,
        prepare_candidate_statements,
        validate_candidate_statements,
    )

    data = facts()
    result = prepare_candidate_statements(data)
    valid = validate_candidate_statements(result.rdf, data)
    assert valid == {
        "conforms": True,
        "scope": "source_derived_preservation",
        "errors": [],
    }
    graph = Graph().parse(data=result.rdf, format="turtle")
    assertion = URIRef(result.assertion_ids[0])
    candidate = Namespace(CANDIDATE_NS)
    if corruption == "removed":
        graph.remove((assertion, None, None))
    elif corruption == "qualifier":
        graph.set((assertion, candidate.condition, Literal("无条件")))
    elif corruption == "bare":
        graph.add((EX.role, EX.reviews, EX.request))
    rdf = (
        "invalid RDF" if corruption == "malformed" else graph.serialize(format="turtle")
    )
    report = validate_candidate_statements(rdf, data)
    assert report["conforms"] is False
    assert report["scope"] == "source_derived_preservation"
    assert report["errors"]


@pytest.mark.parametrize(
    "corruption",
    [
        "root",
        "entities_empty",
        "entities_wrong_type",
        "relationships_wrong_type",
        "entity_wrong_type",
        "entity_id",
        "entity_type",
        "duplicate_entity",
        "relation_wrong_type",
        "relation_id",
        "duplicate_relation",
        "duplicate_idless",
        "predicate",
        "unknown_endpoint",
        "entity_collision",
        "type_collision",
        "evidence_collision",
        "protocol_collision",
        "entity_type_collision",
        "statement_type_collision",
        "entity_statement_collision",
        "metadata",
        "condition",
        "negation",
        "evidence_list",
    ],
)
def test_invalid_records_and_resource_identity_collisions_are_rejected(corruption):
    from semantica.ontology.candidate_statements import (
        CANDIDATE_NS,
        prepare_candidate_statements,
    )

    data = facts()
    if corruption == "root":
        data = []
    elif corruption == "entities_empty":
        data["entities"] = []
    elif corruption == "entities_wrong_type":
        data["entities"] = {}
    elif corruption == "relationships_wrong_type":
        data["relationships"] = {}
    elif corruption == "entity_wrong_type":
        data["entities"][0] = "entity"
    elif corruption == "entity_id":
        data["entities"][0]["id"] = None
    elif corruption == "entity_type":
        data["entities"][0]["type"] = " "
    elif corruption == "duplicate_entity":
        data["entities"][1]["id"] = str(EX.role)
    elif corruption == "relation_wrong_type":
        data["relationships"][0] = "relation"
    elif corruption == "relation_id":
        data["relationships"][0]["id"] = None
    elif corruption == "duplicate_relation":
        data["relationships"].append(deepcopy(data["relationships"][0]))
    elif corruption == "duplicate_idless":
        data["relationships"][0].pop("id")
        data["relationships"].append(deepcopy(data["relationships"][0]))
    elif corruption == "predicate":
        data["relationships"][0]["type"] = ""
    elif corruption == "unknown_endpoint":
        data["relationships"][0]["target_id"] = "ex:missing"
    elif corruption == "entity_collision":
        data["relationships"][0]["id"] = "ex:role"
    elif corruption == "type_collision":
        data["relationships"][0]["id"] = "ex:Role"
    elif corruption == "evidence_collision":
        data["relationships"][0]["metadata"]["evidence"] = [{"quote": "source"}]
        prepared = prepare_candidate_statements(data)
        evidence = next(
            prepared.prepared.graph.objects(None, Namespace(CANDIDATE_NS).hasEvidence)
        )
        data["relationships"][0]["id"] = str(evidence)
    elif corruption == "protocol_collision":
        data["relationships"][0]["type"] = CANDIDATE_NS + "recordJson"
    elif corruption == "entity_type_collision":
        data["entities"][0]["type"] = str(EX.request)
    elif corruption == "statement_type_collision":
        data["entities"][0]["type"] = str(RDF.Statement)
    elif corruption == "entity_statement_collision":
        data["entities"][0]["metadata"] = {"uri": str(EX.request)}
        data["relationships"][0]["type"] = str(SEM.sourceUri)
    elif corruption == "metadata":
        data["relationships"][0]["metadata"] = []
    elif corruption == "condition":
        data["relationships"][0]["metadata"]["condition"] = ["not a string"]
    elif corruption == "negation":
        data["relationships"][0]["metadata"]["negation"] = "false"
    elif corruption == "evidence_list":
        data["relationships"][0]["metadata"]["evidence"] = {"quote": "source"}
    with pytest.raises(ValidationError):
        prepare_candidate_statements(data)


def test_same_spo_keeps_each_assertion_and_missing_ids_have_stable_content_identity():
    from semantica.ontology.candidate_statements import (
        CANDIDATE_NS,
        prepare_candidate_statements,
    )

    data = facts()
    prohibited = deepcopy(data["relationships"][0])
    prohibited.pop("id")
    prohibited["metadata"] = {"condition": "材料缺失时", "negation": True, "modality": "禁止"}
    unknown = deepcopy(prohibited)
    unknown["metadata"] = {"condition": None, "negation": None, "modality": None}
    data["relationships"].extend([prohibited, unknown])
    result = prepare_candidate_statements(data)
    assert result.rdf == prepare_candidate_statements(deepcopy(data)).rdf
    assert len(set(result.assertion_ids)) == 3
    graph = result.prepared.graph
    candidate = Namespace(CANDIDATE_NS)
    assert set(graph.subjects(RDF.type, RDF.Statement)) == {
        URIRef(identifier) for identifier in result.assertion_ids
    }
    assert (EX.role, EX.reviews, EX.request) not in graph
    assert (URIRef(result.assertion_ids[1]), candidate.negation, Literal(True)) in graph
    assert graph.value(URIRef(result.assertion_ids[2]), candidate.negation) is None
    assert [
        json.loads(str(graph.value(URIRef(identifier), candidate.recordJson)))
        for identifier in result.assertion_ids
    ] == data["relationships"]
    data["relationships"].reverse()
    assert (
        prepare_candidate_statements(data).assertion_ids == result.assertion_ids[::-1]
    )


@pytest.mark.parametrize(
    "key,value",
    [
        ("condition", "另一个条件"),
        ("negation", None),
        ("negation", True),
        ("modality", None),
        ("unknown", {"nested": None}),
    ],
)
def test_every_qualifier_change_alters_authoritative_identity_without_changing_projection(
    key, value
):
    from semantica.ontology.candidate_statements import prepare_candidate_statements

    data = facts()
    original = prepare_candidate_statements(data)
    data["relationships"][0]["metadata"][key] = value
    changed = prepare_candidate_statements(data)
    assert changed.facts_sha256 != original.facts_sha256
    assert changed.prepared.sha256 != original.prepared.sha256
    assert changed.projection.sha256 == original.projection.sha256


@pytest.mark.parametrize(
    "value", [float("nan"), {1: "non-string key"}, ("tuple",), {"set"}]
)
def test_non_json_metadata_cannot_be_coerced_or_silently_lost(value):
    from semantica.ontology.candidate_statements import prepare_candidate_statements

    data = facts()
    data["metadata"]["unknown"] = value
    with pytest.raises(ValidationError):
        prepare_candidate_statements(data)
