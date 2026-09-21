"""Candidate facts and their ontology draft share the exported vocabulary."""

from copy import deepcopy
import hashlib
import json
from unittest.mock import MagicMock

import pytest
from rdflib import RDF, RDFS, XSD

from semantica.export.rdf_exporter import RDFExporter
from semantica.ontology.candidate_ontology import (
    build_candidate_prompt,
    generate_candidate_ontology,
    normalize_candidate_ontology,
)
from semantica.ontology.llm_generator import LLMOntologyGenerator
from semantica.ontology.rdf_input import prepare_rdf_input
from semantica.utils.exceptions import ProcessingError, ValidationError


EX = "https://example.test/vocab#"
SEM = "https://semantica.dev/ns#"
ORG = "urn:example:Organization"


def qualified_facts():
    data = facts()
    data["relationships"][0]["id"] = "urn:example:assertion"
    data["relationships"][0]["metadata"] = {
        "condition": "完成后的三个工作日内",
        "modality": "必须补齐",
        "negation": False,
        "evidence": [{"quote": "必须补齐", "start_char": 0, "end_char": 4}],
    }
    return data


def test_qualified_prompt_contains_complete_facts_without_transport_vocabulary():
    from semantica.ontology.candidate_statements import prepare_candidate_statements

    data = qualified_facts()
    prompt = build_candidate_prompt(data, qualified_statements=True)
    payload = json.loads(prompt.split("INPUT:\n", 1)[1])
    statements = prepare_candidate_statements(data)
    assert payload["candidate_facts"] == data
    assert payload["input_rdf_sha256"] == statements.prepared.sha256
    assert payload["input_facts_sha256"] == statements.facts_sha256
    assert set(payload["observed_vocabulary"]["classes"]) == {EX + "PERSON", ORG}
    assert str(RDF.Statement) not in payload["observed_vocabulary"]["classes"]
    assert str(RDF.subject) not in payload["observed_vocabulary"]["properties"]
    assert "unconditional" in prompt
    assert "candidate-facts-ontology-v3" in prompt


@pytest.mark.parametrize(
    "field,value",
    [("condition", "五个工作日内"), ("modality", "可以"), ("negation", True), ("evidence", [])],
)
def test_qualified_replay_rejects_changed_context_even_when_vocabulary_is_equal(
    field, value
):
    data = qualified_facts()
    result = generate_candidate_ontology(
        data, llm(proposal()), qualified_statements=True
    )
    changed = deepcopy(data)
    changed["relationships"][0]["metadata"][field] = value
    assert build_candidate_prompt(
        data, qualified_statements=True
    ) != build_candidate_prompt(changed, qualified_statements=True)
    with pytest.raises(ValidationError, match="matching|context"):
        normalize_candidate_ontology(result, changed, qualified_statements=True)


def test_qualified_generation_binds_authoritative_graph_and_replays_exactly():
    from semantica.ontology.candidate_statements import (
        REPRESENTATION,
        prepare_candidate_statements,
    )

    data = qualified_facts()
    generator = llm(proposal())
    result = generate_candidate_ontology(data, generator, qualified_statements=True)
    prepared = prepare_candidate_statements(data)
    assert result["metadata"]["representation"] == REPRESENTATION
    assert result["metadata"]["input_rdf_sha256"] == prepared.prepared.sha256
    assert result["metadata"]["input_facts_sha256"] == prepared.facts_sha256
    assert result["metadata"]["projection_rdf_sha256"] == prepared.projection.sha256
    assert result == normalize_candidate_ontology(
        result, data, qualified_statements=True
    )
    assert (
        "qualified_statements"
        not in generator.provider.generate_structured.call_args.kwargs
    )


def facts():
    return {
        "@context": {"ex": EX},
        "entities": [
            {"id": "ex:alice", "type": "ex:PERSON", "name": "Alice"},
            {"id": "ex:acme", "type": ORG, "name": "Acme"},
        ],
        "relationships": [
            {"source": "ex:alice", "target": "ex:acme", "type": "ex:WORKS_FOR"},
            {"source": "ex:alice", "target": "ex:acme", "type": "managesAccount"},
        ],
        "metadata": {"fact_status": "candidate", "review_status": "unreviewed"},
    }


def term(name, uri, **extra):
    return {
        "name": name,
        "uri": uri,
        "label": name,
        "comment": f"Definition of {name}.",
        **extra,
    }


def proposal():
    return {
        "classes": [term("PERSON", EX + "PERSON"), term("Organization", ORG)],
        "properties": [
            term(
                "WORKS_FOR",
                EX + "WORKS_FOR",
                type="object",
                domain=[EX + "PERSON"],
                range=[ORG],
            ),
            term(
                "managesAccount",
                SEM + "managesAccount",
                type="object",
                domain=[EX + "PERSON"],
                range=[ORG],
            ),
            term("text", SEM + "text", type="data", domain=[], range=[str(XSD.string)]),
            term(
                "confidence",
                SEM + "confidence",
                type="data",
                domain=[],
                range=[str(XSD.decimal)],
            ),
        ],
    }


def llm(result):
    generator = LLMOntologyGenerator(provider=None, model="test-model", max_tokens=2000)
    generator.provider_name = "test-provider"
    generator.provider = MagicMock()
    generator.provider.generate_structured.return_value = result
    return generator


def test_generation_uses_exact_exported_vocabulary_and_preserves_input():
    data = facts()
    before = deepcopy(data)
    generator = llm(proposal())
    result = generate_candidate_ontology(data, generator, max_tokens=4000)
    prepared = prepare_rdf_input(RDFExporter().export_to_rdf(data))
    assert {item["uri"] for item in result["classes"]} == {
        str(obj) for obj in prepared.graph.objects(None, RDF.type)
    }
    assert {item["uri"] for item in result["properties"]} == {
        str(predicate) for _, predicate, _ in prepared.graph if predicate != RDF.type
    }
    prompt = generator.provider.generate_structured.call_args.args[0]
    assert prompt == build_candidate_prompt(data)
    assert EX + "PERSON" in prompt and EX + "WORKS_FOR" in prompt
    assert SEM + "managesAccount" in prompt and ORG in prompt
    assert generator.provider.generate_structured.call_args.kwargs == {
        "model": "test-model",
        "max_tokens": 4000,
    }
    assert result["metadata"]["input_rdf_sha256"] == prepared.sha256
    assert (
        result["metadata"]["prompt_sha256"]
        == hashlib.sha256(prompt.encode()).hexdigest()
    )
    assert result["metadata"]["source"] == "llm"
    assert result["metadata"]["input_kind"] == "candidate_facts"
    assert result["metadata"]["model"] == "test-model"
    assert result["metadata"]["fact_status"] == "candidate"
    assert result["metadata"]["review_status"] == "unreviewed"
    assert "concept_references" not in result
    assert data == before


@pytest.mark.parametrize(
    "corruption",
    [
        "reminted_class",
        "missing_class",
        "unknown_class",
        "duplicate_class",
        "missing_property",
        "reminted_property",
        "unknown_property",
        "duplicate_property",
    ],
)
def test_replay_rejects_vocabulary_replacement_or_incomplete_coverage(corruption):
    raw = proposal()
    if corruption == "reminted_class":
        raw["classes"][0]["uri"] = EX + "Person"
    elif corruption == "missing_class":
        raw["classes"].pop()
    elif corruption == "unknown_class":
        raw["classes"].append(term("Contract", EX + "Contract"))
    elif corruption == "duplicate_class":
        raw["classes"].append(deepcopy(raw["classes"][0]))
    elif corruption == "missing_property":
        raw["properties"].pop()
    elif corruption == "reminted_property":
        raw["properties"][0]["uri"] = EX + "worksFor"
    elif corruption == "unknown_property":
        raw["properties"].append(term("invented", EX + "invented"))
    elif corruption == "duplicate_property":
        raw["properties"].append(deepcopy(raw["properties"][0]))
    with pytest.raises(ValidationError, match="vocabulary|observed|duplicate"):
        normalize_candidate_ontology(raw, facts())


@pytest.mark.parametrize(
    "corruption",
    [
        "wrong_kind",
        "wrong_domain",
        "wrong_range",
        "unknown_range",
        "multiple_domains",
        "wrong_datatype",
        "invented_parent",
        "required",
        "cardinality",
        "pattern",
        "equivalent_class",
        "instance_mappings",
        "false_evidence",
    ],
)
def test_replay_rejects_unsupported_semantic_assertions(corruption):
    raw = proposal()
    prop = raw["properties"][0]
    if corruption == "wrong_kind":
        prop["type"] = "data"
    elif corruption == "wrong_domain":
        prop["domain"] = [ORG]
    elif corruption == "wrong_range":
        prop["range"] = [EX + "PERSON"]
    elif corruption == "unknown_range":
        prop["range"] = [EX + "Unknown"]
    elif corruption == "multiple_domains":
        prop["domain"] = [EX + "PERSON", ORG]
    elif corruption == "wrong_datatype":
        raw["properties"][2]["range"] = [str(XSD.integer)]
    elif corruption == "invented_parent":
        raw["classes"][0]["subClassOf"] = ORG
    elif corruption == "required":
        prop["required"] = True
    elif corruption == "cardinality":
        prop["cardinality"] = {"min": 1, "max": 1}
    elif corruption == "pattern":
        prop["pattern"] = "A.*"
    elif corruption == "equivalent_class":
        raw["classes"][0]["equivalentClass"] = EX + "Contract"
    elif corruption == "instance_mappings":
        raw["concept_references"] = [{"node_id": EX + "alice", "class_uri": ORG}]
    elif corruption == "false_evidence":
        raw["classes"][0]["evidence_nodes"] = [EX + "acme"]
    with pytest.raises(ValidationError):
        normalize_candidate_ontology(raw, facts())


@pytest.mark.parametrize(
    "corruption",
    [
        "missing_type",
        "blank_type",
        "empty_entities",
        "missing_predicate",
        "missing_endpoint",
    ],
)
def test_invalid_facts_are_rejected_before_provider_call(corruption):
    data = facts()
    if corruption == "missing_type":
        data["entities"][0].pop("type")
    elif corruption == "blank_type":
        data["entities"][0]["type"] = " "
    elif corruption == "empty_entities":
        data["entities"] = []
    elif corruption == "missing_predicate":
        data["relationships"][0].pop("type")
    elif corruption == "missing_endpoint":
        data["relationships"][0].pop("target")
    generator = llm(proposal())
    with pytest.raises(ValidationError):
        generate_candidate_ontology(data, generator)
    generator.provider.generate_structured.assert_not_called()


def test_unavailable_provider_and_provider_failure_have_no_heuristic_fallback():
    with pytest.raises(ProcessingError, match="not initialized"):
        generate_candidate_ontology(facts(), LLMOntologyGenerator(provider=None))
    generator = llm(proposal())
    error = RuntimeError("provider unavailable")
    generator.provider.generate_structured.side_effect = error
    with pytest.raises(ProcessingError, match="generation failed") as caught:
        generate_candidate_ontology(facts(), generator)
    assert caught.value.__cause__ is error
    assert generator.provider.generate_structured.call_count == 1


def test_generation_and_replay_share_validation_and_preserve_provenance_inputs():
    data = facts()
    raw = proposal()
    raw["metadata"] = {"fact_status": "approved", "review_status": "approved"}
    generator = llm(raw)
    result = generate_candidate_ontology(
        data, generator, name="FactsSchema", base_uri=EX
    )
    before = deepcopy(result)
    replay = normalize_candidate_ontology(
        result,
        data,
        name="FactsSchema",
        base_uri=EX,
        provider="test-provider",
        model="test-model",
    )
    assert replay == result == before
    assert result["metadata"]["fact_status"] == "candidate"
    assert result["metadata"]["review_status"] == "unreviewed"
    assert result["classes"][0]["evidence_nodes"] == [EX + "alice"]


def test_completion_token_override_uses_existing_provider_options():
    generator = llm(proposal())
    generate_candidate_ontology(
        facts(), generator, max_completion_tokens=5000, temperature=0, reasoning_effort="low"
    )
    assert generator.provider.generate_structured.call_args.kwargs == {
        "model": "test-model",
        "max_completion_tokens": 5000,
        "temperature": 0,
        "reasoning_effort": "low",
    }


@pytest.mark.parametrize("value", [None, [], {}, 1])
def test_malformed_property_kinds_report_validation_error(value):
    raw = proposal()
    raw["properties"][0]["type"] = value
    with pytest.raises(ValidationError):
        normalize_candidate_ontology(raw, facts())


def test_prompt_and_rdf_hash_are_stable_under_fact_order():
    data = facts()
    reordered = deepcopy(data)
    reordered["entities"].reverse()
    reordered["relationships"].reverse()
    assert build_candidate_prompt(reordered) == build_candidate_prompt(data)
    assert normalize_candidate_ontology(
        proposal(), reordered
    ) == normalize_candidate_ontology(proposal(), data)


def test_only_an_explicit_input_subclass_triple_supports_a_parent():
    data = facts()
    data["relationships"] = [
        {"source": EX + "PERSON", "target": ORG, "type": str(RDFS.subClassOf)}
    ]
    raw = proposal()
    raw["classes"][0]["subClassOf"] = ORG
    raw["properties"] = [
        term("subClassOf", str(RDFS.subClassOf), type="object", domain=[], range=[]),
        *raw["properties"][2:],
    ]
    result = normalize_candidate_ontology(raw, data)
    assert result["classes"][0]["subClassOf"] == ORG
    data["relationships"] = []
    raw["properties"].pop(0)
    with pytest.raises(ValidationError, match="explicit input subClassOf"):
        normalize_candidate_ontology(raw, data)


def test_required_document_facts_keep_their_requirement_type():
    data = {
        "entities": [
            {
                "id": "urn:requirement:contract",
                "type": "RequiredDocument",
                "name": "合法有效的合同",
            }
        ],
        "relationships": [],
    }
    raw = {
        "classes": [
            term(
                "RequiredDocument",
                SEM + "RequiredDocument",
                label="材料要求",
                comment="流程中指定须提供的材料要求，并非实际合同。",
            )
        ],
        "properties": proposal()["properties"][2:],
    }
    before = deepcopy(data)
    result = normalize_candidate_ontology(raw, data)
    assert result["classes"][0]["uri"] == SEM + "RequiredDocument"
    assert "concept_references" not in result
    assert data == before
    raw["classes"][0]["uri"] = EX + "Contract"
    with pytest.raises(ValidationError, match="observed vocabulary"):
        normalize_candidate_ontology(raw, data)


def test_bounded_rdf_input_rejects_instead_of_truncating(monkeypatch):
    import semantica.ontology.rdf_input as rdf_input

    monkeypatch.setattr(rdf_input, "MAX_RDF_TRIPLES", 1)
    generator = llm(proposal())
    with pytest.raises(ValidationError, match="limit"):
        generate_candidate_ontology(facts(), generator)
    generator.provider.generate_structured.assert_not_called()


def test_prompt_uses_entity_literal_language_and_keeps_coarse_types_coarse():
    data = {
        "entities": [{"id": "urn:concept:one", "type": "CONCEPT", "name": "申请材料"}],
        "relationships": [],
    }
    prompt = build_candidate_prompt(data)
    assert "candidate-facts-ontology-v2" in prompt
    assert "input entity-name/text literals" in prompt
    assert "Chinese labels, comments and uncertainties" in prompt
    assert (
        "English PascalCase for class names and camelCase for property names" in prompt
    )
    assert "preserve every IRI byte-for-byte" in prompt
    assert "coarse type such as CONCEPT must remain coarse" in prompt
    assert "Record ambiguity in uncertainties" in prompt
