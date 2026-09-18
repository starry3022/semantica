"""RDF-grounded proposals preserve input identity without asserting instances."""

from copy import deepcopy
import hashlib
from unittest.mock import MagicMock, patch

import pytest
from rdflib import Graph, Literal, RDF, URIRef, XSD

from semantica.ontology.engine import OntologyEngine
from semantica.ontology.llm_generator import LLMOntologyGenerator
from semantica.utils.exceptions import ProcessingError, ValidationError


BASE = "https://example.test/business/"
PROCESS = "https://example.test/process/"
DOC = "https://example.test/nodes/contract"
RULE = "https://example.test/nodes/rule"
EVIDENCE = "https://example.test/nodes/evidence"
SOURCE = "https://example.test/nodes/source"
TEXT = "申请应提供合法有效的合同。\n"
RDF_TEXT = f"""@prefix p: <{PROCESS}> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
<{RULE}> a p:ProcessRule ; p:requiresDocument <{DOC}> ; p:hasEvidence <{EVIDENCE}> .
<{DOC}> a p:RequiredDocument ; p:name "合法有效的合同"@zh ; p:amount "12.50"^^xsd:decimal .
<{EVIDENCE}> a p:Evidence ; p:quote "申请应提供合法有效的合同。" ; p:fromSource <{SOURCE}> .
<{SOURCE}> a p:SourceDocument ; p:source_id "policy" .
"""


@pytest.fixture
def proposal():
    return {
        "name": "付款材料业务本体",
        "classes": [
            {
                "name": "Contract",
                "uri": BASE + "Contract",
                "label": "合同",
                "comment": "付款申请要求提供的合同类型。",
                "subClassOf": None,
                "evidence_lines": [1, 1],
                "evidence_nodes": [DOC],
            }
        ],
        "properties": [],
        "concept_references": [
            {
                "node_id": DOC,
                "class_uri": BASE + "Contract",
                "relation": "references_concept",
                "rationale": "该材料要求引用合同概念。",
            }
        ],
        "unmapped_nodes": [{"node_id": RULE, "reason": "规则陈述不是一份具体合同。"}],
    }


@pytest.fixture
def generator(proposal):
    with patch("semantica.ontology.llm_generator.create_provider") as factory:
        factory.return_value.generate_structured.return_value = proposal
        yield LLMOntologyGenerator(
            provider="openai", model="test-model", max_tokens=2000
        )


def prepare(data=RDF_TEXT, **options):
    from semantica.ontology.rdf_input import prepare_rdf_input

    return prepare_rdf_input(data, **options)


def test_rdf_input_identity_is_stable_across_order_and_blank_node_names():
    first = prepare(
        '<https://example.test/a> <https://example.test/p> _:first .\n_:first <https://example.test/name> "值"@zh .',
        rdf_format="nt",
    )
    second = prepare(
        '_:other <https://example.test/name> "值"@zh .\n<https://example.test/a> <https://example.test/p> _:other .',
        rdf_format="nt",
    )
    assert first.sha256 == second.sha256
    assert first.canonical_ntriples == second.canonical_ntriples
    assert first.sha256 == hashlib.sha256(first.canonical_ntriples.encode()).hexdigest()


def test_input_snapshot_preserves_nodes_datatypes_languages_and_graph():
    graph = Graph().parse(data=RDF_TEXT, format="turtle")
    before = set(graph)
    prepared = prepare(graph)
    assert prepared.node_ids == {DOC, RULE, EVIDENCE, SOURCE}
    assert prepared.semantic_node_ids == {DOC, RULE}
    assert prepared.support_node_ids == {EVIDENCE, SOURCE}
    assert prepared.required_document_ids == {DOC}
    assert set(prepared.graph) == before == set(graph)
    node = next(node for node in prepared.snapshot if node["id"] == DOC)
    assert node["types"] == [PROCESS + "RequiredDocument"]
    assert {
        "predicate": PROCESS + "name",
        "object": {
            "kind": "literal",
            "value": "合法有效的合同",
            "datatype": None,
            "language": "zh",
        },
    } in node["statements"]
    assert {
        "predicate": PROCESS + "amount",
        "object": {
            "kind": "literal",
            "value": "12.50",
            "datatype": str(XSD.decimal),
            "language": None,
        },
    } in node["statements"]


@pytest.mark.parametrize(
    "data,format",
    [
        ("", "turtle"),
        ("  ", "turtle"),
        ("broken turtle", "turtle"),
        ("https://example.test/data.ttl", "turtle"),
        (b"\xff", "nt"),
        ({}, "turtle"),
        (RDF_TEXT, "json-ld"),
        (RDF_TEXT, "xml"),
    ],
)
def test_invalid_or_remote_rdf_is_rejected_before_provider(generator, data, format):
    with pytest.raises(ValidationError):
        generator.generate_ontology_from_rdf(data, rdf_format=format, base_uri=BASE)
    generator.provider.generate_structured.assert_not_called()


def test_input_limits_reject_the_whole_graph_instead_of_truncating(monkeypatch):
    import semantica.ontology.rdf_input as rdf_input

    monkeypatch.setattr(rdf_input, "MAX_RDF_BYTES", 20)
    with pytest.raises(ValidationError, match="limit"):
        prepare()
    monkeypatch.setattr(rdf_input, "MAX_RDF_BYTES", 100000)
    monkeypatch.setattr(rdf_input, "MAX_RDF_TRIPLES", 2)
    with pytest.raises(ValidationError, match="limit"):
        prepare(Graph().parse(data=RDF_TEXT, format="turtle"))


def test_llm_receives_complete_rdf_and_returns_candidate_concept_references(generator):
    graph = Graph().parse(data=RDF_TEXT, format="turtle")
    before = set(graph)
    result = generator.generate_ontology_from_rdf(
        graph, source_text=TEXT, base_uri=BASE, max_tokens=6000
    )
    assert result["classes"][0]["evidence_nodes"] == [DOC]
    assert result["classes"][0]["evidence_quote"] == TEXT
    assert result["concept_references"][0]["node_id"] == DOC
    assert result["concept_references"][0]["relation"] == "references_concept"
    assert result["unmapped_nodes"] == [{"node_id": RULE, "reason": "规则陈述不是一份具体合同。"}]
    assert result["metadata"]["input_kind"] == "rdf"
    assert result["metadata"]["input_rdf_sha256"] == prepare(graph).sha256
    assert (
        result["metadata"]["source_sha256"] == hashlib.sha256(TEXT.encode()).hexdigest()
    )
    assert result["metadata"]["fact_status"] == "candidate"
    assert result["metadata"]["review_status"] == "unreviewed"
    prompt = generator.provider.generate_structured.call_args.args[0]
    assert DOC in prompt and EVIDENCE in prompt and "12.50" in prompt
    assert (
        result["metadata"]["prompt_sha256"]
        == hashlib.sha256(prompt.encode()).hexdigest()
    )
    assert generator.provider.generate_structured.call_args.kwargs == {
        "model": "test-model",
        "max_tokens": 6000,
    }
    assert set(graph) == before
    assert (URIRef(DOC), RDF.type, URIRef(BASE + "Contract")) not in graph


def test_rdf_without_original_text_uses_rdf_grounding_only(generator, proposal):
    del proposal["classes"][0]["evidence_lines"]
    result = generator.generate_ontology_from_rdf(RDF_TEXT, base_uri=BASE)
    assert result["classes"][0]["evidence_quote"] is None
    assert result["classes"][0]["evidence_nodes"] == [DOC]
    assert result["metadata"]["rdf_grounding_required"] is True


@pytest.mark.parametrize(
    "case",
    [
        "missing_nodes",
        "unknown_node",
        "duplicate_node",
        "unknown_class",
        "wrong_class_evidence",
        "duplicate_mapping",
        "wrong_relation",
        "support_mapping",
        "missing_coverage",
        "mapped_and_unmapped",
        "unknown_unmapped",
        "empty_reason",
        "bad_lines",
    ],
)
def test_invalid_mapping_or_grounding_fails_closed(generator, proposal, case):
    if case == "missing_nodes":
        del proposal["classes"][0]["evidence_nodes"]
    elif case == "unknown_node":
        proposal["classes"][0]["evidence_nodes"] = ["https://example.test/missing"]
    elif case == "duplicate_node":
        proposal["classes"][0]["evidence_nodes"] = [DOC, DOC]
    elif case == "unknown_class":
        proposal["concept_references"][0]["class_uri"] = BASE + "Missing"
    elif case == "wrong_class_evidence":
        proposal["classes"][0]["evidence_nodes"] = [RULE]
    elif case == "duplicate_mapping":
        proposal["concept_references"] *= 2
    elif case == "wrong_relation":
        proposal["concept_references"][0]["relation"] = "rdf:type"
    elif case == "support_mapping":
        proposal["classes"][0]["evidence_nodes"] = [DOC, EVIDENCE]
        proposal["concept_references"][0]["node_id"] = EVIDENCE
    elif case == "missing_coverage":
        proposal["concept_references"] = []
    elif case == "mapped_and_unmapped":
        proposal["unmapped_nodes"].append({"node_id": DOC, "reason": "uncertain"})
    elif case == "unknown_unmapped":
        proposal["unmapped_nodes"].append({"node_id": "missing", "reason": "uncertain"})
    elif case == "empty_reason":
        proposal["unmapped_nodes"][0]["reason"] = " "
    else:
        proposal["classes"][0]["evidence_lines"] = [2, 2]
    with pytest.raises(ValidationError):
        generator.generate_ontology_from_rdf(RDF_TEXT, source_text=TEXT, base_uri=BASE)


def test_every_required_document_must_be_mapped_or_explicitly_unmapped(
    generator, proposal
):
    proposal["concept_references"] = []
    proposal["unmapped_nodes"].append(
        {
            "node_id": DOC,
            "reason": "Cannot safely distinguish a contract type from its requirements.",
        }
    )
    result = generator.generate_ontology_from_rdf(
        RDF_TEXT, source_text=TEXT, base_uri=BASE
    )
    assert result["concept_references"] == []
    assert {item["node_id"] for item in result["unmapped_nodes"]} == {DOC, RULE}


def test_replay_revalidates_mapping_without_a_provider(proposal):
    generator = LLMOntologyGenerator(provider=None)
    result = generator.normalize_ontology_from_rdf(
        proposal, prepare(), source_text=TEXT, base_uri=BASE
    )
    assert result["metadata"]["input_kind"] == "rdf"
    invalid = deepcopy(result)
    invalid["concept_references"][0]["node_id"] = "missing"
    with pytest.raises(ValidationError):
        generator.normalize_ontology_from_rdf(
            invalid, prepare(), source_text=TEXT, base_uri=BASE
        )


def test_provider_failure_is_not_silently_replaced_with_heuristics(generator):
    generator.provider.generate_structured.side_effect = RuntimeError(
        "private gateway data"
    )
    with pytest.raises(
        ProcessingError, match="LLM ontology generation failed"
    ) as error:
        generator.generate_ontology_from_rdf(RDF_TEXT, source_text=TEXT, base_uri=BASE)
    assert "private gateway data" not in str(error.value)


def test_engine_dispatches_rdf_to_llm_and_keeps_dict_heuristics(proposal):
    with patch("semantica.ontology.llm_generator.create_provider") as factory:
        factory.return_value.generate_structured.return_value = proposal
        engine = OntologyEngine(model="test-model")
        for rdf_input in (RDF_TEXT, Graph().parse(data=RDF_TEXT, format="turtle")):
            result = engine.from_data(rdf_input, source_text=TEXT, base_uri=BASE)
            assert result["metadata"]["input_kind"] == "rdf"
        dictionary = {
            "entities": [{"id": "one", "type": "Person"}],
            "relationships": [],
        }
        for options in ({}, {"method": "heuristic"}):
            result = engine.from_data(
                dictionary, min_occurrences=1, validate=False, **options
            )
            assert result["classes"][0]["name"] == "Person"


def test_engine_rejects_mismatched_methods_instead_of_returning_empty_ontology():
    engine = object.__new__(OntologyEngine)
    engine.llm = MagicMock()
    with pytest.raises(ValidationError):
        engine.from_data(RDF_TEXT, method="heuristic")
    with pytest.raises(ValidationError):
        engine.from_data({"entities": [], "relationships": []}, method="llm")


@pytest.mark.parametrize(
    "bad_iri", ["relative", "https://example.test/bad name", "https://[bad"]
)
def test_graph_input_rejects_invalid_identifiers_with_validation_error(bad_iri):
    graph = Graph()
    graph.add((URIRef(bad_iri), RDF.type, URIRef(PROCESS + "Role")))
    with pytest.raises(ValidationError):
        prepare(graph)


def test_graph_input_rejects_relative_literal_datatypes():
    graph = Graph()
    graph.add(
        (
            URIRef(DOC),
            URIRef(PROCESS + "value"),
            Literal("x", datatype=URIRef("relative")),
        )
    )
    with pytest.raises(ValidationError):
        prepare(graph)


def test_only_type_iris_exempt_support_subjects_from_semantic_coverage():
    graph = Graph()
    graph.add((URIRef(DOC), RDF.type, Literal(PROCESS + "Evidence")))
    prepared = prepare(graph)
    assert prepared.semantic_node_ids == {DOC}
    assert prepared.support_node_ids == set()


def test_prompt_preserves_every_rdf_statement_and_support_metadata(generator):
    prepared = prepare()
    prompt = generator.build_rdf_prompt(prepared, source_text=TEXT, base_uri=BASE)
    import json

    data = json.loads(
        prompt.split("Complete normalized RDF and subject snapshot (JSON data):\n", 1)[
            1
        ]
    )
    assert "canonical_ntriples" not in data
    assert data["input_rdf_sha256"] == prepared.sha256
    assert data["subjects"] == prepared.snapshot
    assert sum(len(node["statements"]) for node in data["subjects"]) == len(
        prepared.graph
    )
    assert data["semantic_node_ids"] == sorted([DOC, RULE])
    assert (
        "Do not invent equivalence or instance mappings to that vocabulary"
        not in prompt
    )
    assert "exactly two inclusive integer line numbers" in prompt
    assert "[26, 26]" in prompt
    assert "never [26]" in prompt


def test_singleton_source_lines_are_rejected_instead_of_silently_repaired(
    generator, proposal
):
    proposal["classes"][0]["evidence_lines"] = [1]
    with pytest.raises(ValidationError, match="line range"):
        generator.generate_ontology_from_rdf(RDF_TEXT, source_text=TEXT, base_uri=BASE)


def test_rdf_prompt_separates_reusable_names_from_policy_qualifiers(generator):
    prompt = generator.build_rdf_prompt(prepare(), source_text=TEXT, base_uri=BASE)
    assert "Class labels must name reusable concepts" in prompt
    assert "Keep policy qualifiers on the requirement or relation" in prompt
    assert "follow-up activity is not the completion event" in prompt


@pytest.mark.parametrize("field", ["label", "comment"])
def test_rdf_only_terms_still_require_business_definitions(generator, proposal, field):
    del proposal["classes"][0]["evidence_lines"]
    proposal["classes"][0][field] = " "
    with pytest.raises(ValidationError):
        generator.generate_ontology_from_rdf(RDF_TEXT, base_uri=BASE)


def test_support_subjects_alone_cannot_ground_business_concepts(generator, proposal):
    proposal["classes"][0]["evidence_nodes"] = [EVIDENCE, SOURCE]
    proposal["concept_references"] = []
    proposal["unmapped_nodes"].append({"node_id": DOC, "reason": "uncertain"})
    with pytest.raises(ValidationError):
        generator.generate_ontology_from_rdf(RDF_TEXT, source_text=TEXT, base_uri=BASE)


def test_source_text_requires_line_grounding_even_if_a_quote_matches(
    generator, proposal
):
    del proposal["classes"][0]["evidence_lines"]
    proposal["classes"][0]["evidence_quote"] = TEXT
    with pytest.raises(ValidationError):
        generator.generate_ontology_from_rdf(RDF_TEXT, source_text=TEXT, base_uri=BASE)


def test_replay_preserves_generation_provenance_and_revalidates_input_identity(
    generator,
):
    generated = generator.generate_ontology_from_rdf(
        RDF_TEXT, source_text=TEXT, base_uri=BASE
    )
    replay = LLMOntologyGenerator(provider=None)
    result = replay.normalize_ontology_from_rdf(generated, RDF_TEXT, source_text=TEXT)
    assert result == generated
    changed_rdf = RDF_TEXT.replace("12.50", "99.00")
    with pytest.raises(ValidationError, match="identity"):
        replay.normalize_ontology_from_rdf(generated, changed_rdf, source_text=TEXT)
    with pytest.raises(ValidationError):
        replay.normalize_ontology_from_rdf(generated, RDF_TEXT, source_text="无关文本。\n")


def test_schema_subjects_can_ground_terms_without_becoming_candidate_instances(
    generator, proposal
):
    schema_node = "https://example.test/schema/Contract"
    rdf = f"<{schema_node}> a <http://www.w3.org/2002/07/owl#Class> ."
    proposal["classes"][0]["evidence_nodes"] = [schema_node]
    del proposal["classes"][0]["evidence_lines"]
    proposal["concept_references"] = []
    proposal["unmapped_nodes"] = []
    result = generator.generate_ontology_from_rdf(rdf, base_uri=BASE)
    assert result["classes"][0]["evidence_nodes"] == [schema_node]
    assert result["concept_references"] == []


def test_property_grounding_and_single_domain_range_are_required(generator, proposal):
    del proposal["classes"][0]["evidence_lines"]
    proposal["properties"] = [
        {
            "name": "documentLabel",
            "uri": BASE + "documentLabel",
            "type": "data",
            "domain": [BASE + "Contract"],
            "range": [str(XSD.string)],
            "label": "材料名称",
            "comment": "要求提供的材料名称。",
            "evidence_nodes": [DOC],
        }
    ]
    result = generator.generate_ontology_from_rdf(RDF_TEXT, base_uri=BASE)
    assert result["properties"][0]["evidence_nodes"] == [DOC]
    proposal["properties"][0]["range"].append(str(XSD.anyURI))
    with pytest.raises(ValidationError):
        generator.generate_ontology_from_rdf(RDF_TEXT, base_uri=BASE)


def test_engine_from_rdf_forwards_provider_and_options_without_using_heuristics():
    engine = object.__new__(OntologyEngine)
    engine.llm = MagicMock()
    engine.generator = MagicMock()
    engine.from_rdf(
        RDF_TEXT,
        provider="custom",
        model="new-model",
        source_text=TEXT,
        rdf_format="nt",
        name="Ontology",
        base_uri=BASE,
    )
    engine.llm.set_provider.assert_called_once_with("custom", model="new-model")
    engine.llm.generate_ontology_from_rdf.assert_called_once_with(
        RDF_TEXT, source_text=TEXT, rdf_format="nt", name="Ontology", base_uri=BASE
    )
    engine.generator.generate_ontology.assert_not_called()
