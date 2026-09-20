"""RDF ontology generation describes one observed vocabulary by default."""

from copy import deepcopy
import hashlib
from unittest.mock import MagicMock

import pytest
from rdflib import Graph, RDF, XSD

from semantica.ontology.candidate_ontology import (
    build_rdf_vocabulary_prompt,
    normalize_rdf_vocabulary_ontology,
)
from semantica.ontology.engine import OntologyEngine
from semantica.ontology.llm_generator import LLMOntologyGenerator
from semantica.ontology.rdf_input import prepare_rdf_input
from semantica.utils.exceptions import ProcessingError, ValidationError


EX = "https://example.test/process/"
BUSINESS = "https://example.test/business/"
SOURCE = "财务负责人审批；供应商付款应提供合法有效的合同。"
RDF_TEXT = f"""@prefix ex: <{EX}> .
ex:finance a ex:Role ; ex:name "财务负责人"@zh ;
    ex:fact_status "candidate" ; ex:review_status "unreviewed" .
"""


def proposal():
    return {
        "classes": [
            {
                "name": "Role",
                "uri": EX + "Role",
                "label": "组织角色",
                "comment": "规则所引用的组织岗位，不标识具体任职人员。",
            }
        ],
        "properties": [
            {
                "name": key,
                "uri": EX + key,
                "label": label,
                "comment": label + "的定义。",
                "type": "data",
                "domain": [EX + "Role"],
                "range": [datatype],
            }
            for key, label, datatype in (
                ("name", "名称", str(RDF.langString)),
                ("fact_status", "知识状态", str(XSD.string)),
                ("review_status", "业务审核状态", str(XSD.string)),
            )
        ],
    }


def engine(result=None):
    value = object.__new__(OntologyEngine)
    value.config = {}
    value.llm = LLMOntologyGenerator(provider=None, model="test-model", max_tokens=2000)
    value.llm.provider_name = "test-provider"
    value.llm.provider = MagicMock()
    value.llm.provider.generate_structured.return_value = deepcopy(result or proposal())
    value.generator = MagicMock()
    return value


def test_default_rdf_generation_preserves_observed_role_and_property_identity():
    value = engine()
    graph = Graph().parse(data=RDF_TEXT, format="turtle")
    before = set(graph)
    result = value.from_rdf(graph, source_text=SOURCE, base_uri=BUSINESS)

    assert {row["uri"] for row in result["classes"]} == {EX + "Role"}
    assert {row["uri"] for row in result["properties"]} == {
        EX + "name",
        EX + "fact_status",
        EX + "review_status",
    }
    assert "concept_references" not in result
    assert result["metadata"]["input_kind"] == "rdf"
    assert result["metadata"]["generation_mode"] == "observed_vocabulary"
    assert result["metadata"]["fact_status"] == "candidate"
    assert result["metadata"]["review_status"] == "unreviewed"
    assert result["metadata"]["input_rdf_sha256"] == prepare_rdf_input(graph).sha256
    assert (
        result["metadata"]["source_sha256"]
        == hashlib.sha256(SOURCE.encode()).hexdigest()
    )
    prompt = value.llm.provider.generate_structured.call_args.args[0]
    assert SOURCE in prompt
    assert "Do not add terms" in prompt
    assert (
        result["metadata"]["prompt_sha256"]
        == hashlib.sha256(prompt.encode()).hexdigest()
    )
    assert value.llm.provider.generate_structured.call_args.kwargs == {
        "model": "test-model",
        "max_tokens": 2000,
    }
    assert set(graph) == before
    value.generator.generate_ontology.assert_not_called()


@pytest.mark.parametrize(
    "corruption", ["new_class", "replace_role", "concept_reference"]
)
def test_source_context_cannot_create_a_parallel_class_vocabulary(corruption):
    result = proposal()
    finance = {
        **result["classes"][0],
        "name": "FinanceOfficer",
        "uri": BUSINESS + "FinanceOfficer",
    }
    if corruption == "new_class":
        result["classes"].append(finance)
    elif corruption == "replace_role":
        result["classes"] = [finance]
    else:
        result["concept_references"] = [
            {"node_id": EX + "finance", "class_uri": EX + "Role"}
        ]
    with pytest.raises(ValidationError):
        engine(result).from_rdf(RDF_TEXT, source_text=SOURCE, base_uri=BUSINESS)


@pytest.mark.parametrize(
    "statement",
    [
        "ex:Role a owl:Class .",
        "ex:approves a owl:FunctionalProperty .",
        "ex:Role a owl:AllDisjointClasses .",
        "ex:finance a owl:NamedIndividual .",
        "ex:Role a rdfs:Class .",
        "ex:name a rdf:Property .",
        "ex:Role rdfs:subClassOf ex:Person .",
        "ex:name rdfs:domain ex:Role .",
        "ex:Role owl:equivalentClass ex:Person .",
        "ex:finance a [ owl:unionOf (ex:Role ex:Person) ] .",
        'ex:finance a "Role" .',
    ],
)
def test_schema_and_anonymous_class_input_is_rejected_before_generation(statement):
    data = (
        RDF_TEXT
        + f"""
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdf: <{RDF}> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
{statement}
"""
    )
    value = engine()
    with pytest.raises(ValidationError, match="(?i)(schema|named)"):
        value.from_rdf(data)
    value.llm.provider.generate_structured.assert_not_called()


def test_business_concept_generation_remains_an_explicit_compatibility_mode():
    value = engine()
    value.llm.generate_ontology_from_rdf = MagicMock(return_value={"legacy": True})
    assert value.from_rdf(
        RDF_TEXT,
        generation_mode="business_concepts",
        source_text=SOURCE,
        base_uri=BUSINESS,
    ) == {"legacy": True}
    value.llm.generate_ontology_from_rdf.assert_called_once_with(
        RDF_TEXT,
        source_text=SOURCE,
        rdf_format="turtle",
        base_uri=BUSINESS,
    )
    value.llm.provider.generate_structured.assert_not_called()


def test_unknown_generation_mode_is_rejected_before_provider_call():
    value = engine()
    with pytest.raises(ValidationError, match="generation_mode"):
        value.from_rdf(RDF_TEXT, generation_mode="replace_instances")
    value.llm.provider.generate_structured.assert_not_called()


def test_provider_failure_does_not_fall_back_to_business_or_heuristic_generation():
    value = engine()
    value.llm.provider.generate_structured.side_effect = RuntimeError("provider failed")
    with pytest.raises(ProcessingError):
        value.from_rdf(RDF_TEXT)
    value.generator.generate_ontology.assert_not_called()


def test_from_data_routes_rdf_to_the_same_default_vocabulary_contract():
    value = engine()
    result = value.from_data(RDF_TEXT, source_text=SOURCE, base_uri=BUSINESS)
    assert result["classes"][0]["uri"] == EX + "Role"
    assert result["metadata"]["generation_mode"] == "observed_vocabulary"


def test_same_local_name_in_another_namespace_is_a_distinct_class():
    data = RDF_TEXT + f" <urn:other:role> a <{BUSINESS}Role> ."
    raw = proposal()
    raw["classes"].append(
        {
            "name": "OtherRole",
            "uri": BUSINESS + "Role",
            "label": "其他角色",
            "comment": "另一个命名空间中的角色类型。",
        }
    )
    result = engine(raw).from_rdf(data)
    assert {row["uri"] for row in result["classes"]} == {EX + "Role", BUSINESS + "Role"}
    assert result["properties"][0]["domain"] == [EX + "Role"]


def test_required_material_is_not_retagged_as_a_real_contract():
    data = RDF_TEXT.replace("ex:Role", "ex:RequiredDocument").replace(
        "财务负责人", "合法有效的合同"
    )
    raw = proposal()
    raw["classes"][0].update(
        name="RequiredDocument",
        uri=EX + "RequiredDocument",
        label="材料要求",
        comment="规则所要求提供的材料，不代表实物或文件已存在。",
    )
    for prop in raw["properties"]:
        prop["domain"] = [EX + "RequiredDocument"]
    result = engine(raw).from_rdf(data, source_text=SOURCE)
    assert result["classes"][0]["uri"] == EX + "RequiredDocument"
    assert "concept_references" not in result


def test_replay_binds_rdf_source_and_prompt_and_retains_generation_provenance():
    result = engine().from_rdf(RDF_TEXT, source_text=SOURCE, base_uri=BUSINESS)
    before = deepcopy(result)
    restored = normalize_rdf_vocabulary_ontology(
        result,
        RDF_TEXT,
        source_text=SOURCE,
        base_uri=BUSINESS,
    )
    assert restored == before
    assert result == before
    assert build_rdf_vocabulary_prompt(RDF_TEXT, source_text=SOURCE, base_uri=BUSINESS)
    for rdf, source, options in (
        (RDF_TEXT.replace("财务负责人", "部门负责人"), SOURCE, {"base_uri": BUSINESS}),
        (RDF_TEXT, "另一份原文。", {"base_uri": BUSINESS}),
        (RDF_TEXT, SOURCE, {"base_uri": EX}),
    ):
        with pytest.raises(ValidationError, match="replay"):
            normalize_rdf_vocabulary_ontology(
                result, rdf, source_text=source, **options
            )


@pytest.mark.parametrize(
    "data", ["https://example.org/remote.ttl", "/tmp/ontology.ttl", "invalid turtle"]
)
def test_remote_paths_and_malformed_rdf_never_reach_provider(data):
    value = engine()
    with pytest.raises(ValidationError):
        value.from_rdf(data)
    value.llm.provider.generate_structured.assert_not_called()


def test_mixed_predicates_fail_before_calling_provider():
    value = engine()
    with pytest.raises(ValidationError, match="mix literals"):
        value.from_rdf(RDF_TEXT + " ex:finance ex:name ex:other .")
    value.llm.provider.generate_structured.assert_not_called()
