"""LLM review supplies semantics; validation preserves or rejects its decisions."""

from copy import deepcopy
import hashlib
import json
from unittest.mock import MagicMock, patch

import pytest

from semantica.semantic_extract.candidate_coverage import (
    COMPETENCY_PROMPT_VERSION, CoverageResponseV2, CoverageReviewError,
    LEGACY_PROMPT_VERSION, PROMPT_VERSION,
    apply_coverage_review, build_coverage_prompt, review_candidate_facts,
)
from semantica.semantic_extract.candidate_profile import (
    extract_candidate_facts, replay_candidate_facts,
)
from semantica.utils.exceptions import ProcessingError, ValidationError


TEXT = "材料😀\r\n\r\n员工因业务需要采购设备或服务时，应提前提交申请。\r\n附注：蓝色是标记。"


def evidence(line=3):
    return [{"start_line": line, "end_line": line}]


@pytest.fixture
def initial():
    entities = {"entities": [
        {"id": f"e{i}", "text": name, "type": kind, "confidence": 0.9,
         "evidence": evidence(4 if i == 5 else 3)}
        for i, (name, kind) in enumerate([
            ("员工", "Role"), ("申请", "Request"), ("设备", "Category"),
            ("服务", "Category"), ("蓝色", "Description"),
        ], start=1)
    ]}
    relations = {"relationships": [{
        "source_id": "e1", "target_id": "e2", "type": "submitsInAdvance",
        "confidence": 0.9, "condition": "因业务需要采购设备或服务时",
        "modality": "应", "negation": False, "evidence": evidence(),
    }]}
    provider = MagicMock()
    provider.generate_typed.side_effect = [entities, relations]
    with patch("semantica.semantic_extract.candidate_profile.create_provider", return_value=provider):
        return extract_candidate_facts(TEXT, source_id="policy", provider="openai", model="test")


@pytest.fixture
def response(initial):
    retained = deepcopy(initial["extraction"]["responses"]["relationships"]["relationships"][0])
    final = [{"id": "f1", **retained}] + [{
        "id": f"f{i}", "source_id": "e2", "target_id": endpoint,
        "type": "appliesToCategory", "confidence": 0.9,
        "condition": "因业务需要采购设备或服务时；设备与服务为可选类别",
        "negation": False, "modality": None, "evidence": evidence(),
    } for i, endpoint in [(2, "e3"), (3, "e4")]]
    return {
        "relationships": final,
        "relationship_reviews": [{
            "relationship_id": "r1", "decision": "retained", "output_ids": ["f1"],
            "reason": "保留原文提前提交义务及完整适用条件。", "evidence": evidence(),
        }],
        "entity_reviews": [{
            "entity_id": f"e{i}", "status": "descriptive" if i == 5 else "linked",
            "relationship_ids": [r["id"] for r in final if f"e{i}" in (r["source_id"], r["target_id"])],
            "reason": "描述性标记，没有独立连接依据。" if i == 5 else "已表达原文角色或适用类别。",
            "evidence": evidence(4 if i == 5 else 3),
        } for i in range(1, 6)],
        "clause_reviews": [
            {"lines": [1, 4], "status": "context_only", "relationship_ids": [], "reason": "标题与描述性附注。"},
            {"lines": [3], "status": "covered", "relationship_ids": ["f1", "f2", "f3"], "reason": "义务、条件与并列可选类别。"},
        ],
        "competency_reviews": [{
            "question": "谁应提前提交申请，适用哪些可选采购类别？",
            "answer": "员工因业务需要采购设备或服务时应提前提交申请。",
            "status": "answered", "entity_ids": ["e1", "e2", "e3", "e4"],
            "relationship_ids": ["f1", "f2", "f3"], "evidence": evidence(),
        }],
    }


def review(initial, response):
    provider = MagicMock()
    provider.generate_typed.return_value = response
    with patch("semantica.semantic_extract.candidate_profile.create_provider", return_value=provider):
        result = review_candidate_facts(TEXT, initial, provider="openai", model="reviewer", api_key="private-never-export")
    return result, provider


def test_facade_runs_independent_review_and_preserves_qualifiers(initial, response):
    before = deepcopy(initial)
    provider = MagicMock()
    provider.generate_typed.side_effect = [
        initial["extraction"]["responses"]["entities"],
        initial["extraction"]["responses"]["relationships"], response,
    ]
    with (
        patch("semantica.semantic_extract.candidate_profile.create_provider", return_value=provider),
        patch("semantica.semantic_extract.candidate_coverage_stages.review_candidate_facts", review_candidate_facts),
    ):
        result = extract_candidate_facts(TEXT, source_id="policy", provider="openai", model="test", review_coverage=True)
    assert provider.generate_typed.call_count == 3
    assert initial == before
    assert result["facts"]["entities"] == initial["facts"]["entities"]
    final = result["facts"]["relationships"]
    assert len(final) == 3
    for key in ("condition", "modality", "negation", "evidence"):
        assert final[0]["metadata"][key] == initial["facts"]["relationships"][0]["metadata"][key]
    for relation in final:
        assert relation["metadata"]["prompt_version"] == PROMPT_VERSION
        assert relation["metadata"]["review_status"] == "unreviewed"
        for citation in relation["metadata"]["evidence"]:
            assert TEXT[citation["start_char"]:citation["end_char"]] == citation["quote"]
    descriptive = result["facts"]["entities"][4]["id"]
    assert all(descriptive not in (r["source_id"], r["target_id"]) for r in final)
    assert result["issues"] == []


def test_replay_is_identical_without_a_provider_and_keeps_original_response(initial, response):
    result, _ = review(initial, response)
    assert result["extraction"]["responses"] == initial["extraction"]["responses"]
    assert "private-never-export" not in json.dumps(result)
    with patch("semantica.semantic_extract.candidate_profile.create_provider", side_effect=AssertionError("offline")):
        assert replay_candidate_facts(TEXT, result["extraction"], source_id="policy") == result


@pytest.mark.parametrize("fault", [
    "missing_entity", "missing_initial_relation", "duplicate_final_id", "unknown_endpoint",
    "unknown_reference", "missing_line", "duplicate_line", "outside_line", "missing_link_reference",
    "false_linked_status", "changed_retained_condition", "changed_retained_evidence",
    "bad_evidence", "unknown_business_field", "removed_has_output", "revised_has_no_output",
    "missing_competency", "unlinked_answer_entity", "answer_without_relationships",
])
def test_rejects_inconsistent_output_without_repair_or_input_mutation(initial, response, fault):
    before = deepcopy(initial)
    if fault == "missing_entity":
        response["entity_reviews"].pop()
    elif fault == "missing_initial_relation":
        response["relationship_reviews"].clear()
    elif fault == "duplicate_final_id":
        response["relationships"][2]["id"] = "f2"
    elif fault == "unknown_endpoint":
        response["relationships"][1]["target_id"] = "absent"
    elif fault == "unknown_reference":
        response["clause_reviews"][1]["relationship_ids"].append("absent")
    elif fault == "missing_line":
        response["clause_reviews"][0]["lines"] = [1]
    elif fault == "duplicate_line":
        response["clause_reviews"][0]["lines"].append(3)
    elif fault == "outside_line":
        response["clause_reviews"][0]["lines"].append(99)
    elif fault == "missing_link_reference":
        response["entity_reviews"][1]["relationship_ids"].pop()
    elif fault == "false_linked_status":
        response["entity_reviews"][4]["status"] = "linked"
    elif fault == "changed_retained_condition":
        response["relationships"][0]["condition"] = None
    elif fault == "changed_retained_evidence":
        response["relationships"][0]["evidence"] = evidence(1)
    elif fault == "bad_evidence":
        response["relationships"][1]["evidence"] = evidence(99)
    elif fault == "unknown_business_field":
        response["relationships"][1]["business_rule"] = "invented"
    elif fault == "removed_has_output":
        response["relationship_reviews"][0]["decision"] = "removed"
    elif fault == "revised_has_no_output":
        response["relationship_reviews"][0].update(decision="revised", output_ids=[])
    elif fault == "missing_competency":
        response.pop("competency_reviews")
    elif fault == "unlinked_answer_entity":
        response["competency_reviews"][0]["entity_ids"].append("e5")
    elif fault == "answer_without_relationships":
        response["competency_reviews"][0]["relationship_ids"] = []
    with pytest.raises(ValidationError) as error:
        review(initial, response)
    assert initial == before
    if isinstance(error.value, CoverageReviewError):
        assert error.value.record["response"] == CoverageResponseV2.model_validate(response).model_dump(mode="json")


@pytest.mark.parametrize("field", ["prompt_sha256", "input_sha256", "prompt_version"])
def test_replay_rejects_changed_review_binding(initial, response, field):
    result, _ = review(initial, response)
    result["extraction"]["coverage_review"][field] = "tampered"
    with pytest.raises(CoverageReviewError, match="binding"):
        replay_candidate_facts(TEXT, result["extraction"], source_id="policy")


def test_clause_groups_may_include_valid_blank_lines_without_rewriting_the_audit(initial, response):
    response["clause_reviews"][0]["lines"].append(2)
    result, _ = review(initial, response)
    assert result["extraction"]["coverage_review"]["response"]["clause_reviews"][0]["lines"] == [1, 4, 2]


def test_revised_and_removed_decisions_are_explicit_and_uncertainty_is_visible(initial, response):
    response["relationship_reviews"][0]["decision"] = "revised"
    response["relationships"][0]["condition"] += "；提前提交"
    revised, _ = review(initial, response)
    assert revised["facts"]["relationships"][0]["metadata"]["condition"].endswith("提前提交")

    response["relationships"].pop(0)
    response["relationship_reviews"][0].update(decision="removed", output_ids=[])
    for entity in response["entity_reviews"]:
        entity["relationship_ids"] = [r for r in entity["relationship_ids"] if r != "f1"]
    response["entity_reviews"][0].update(status="unresolved", reason="独立复核仍有待确认的参与方式。")
    response["clause_reviews"][1].update(status="unresolved", relationship_ids=["f2", "f3"])
    response["competency_reviews"][0].update(status="unresolved", relationship_ids=["f2", "f3"])
    removed, _ = review(initial, response)
    assert len(removed["facts"]["relationships"]) == 2
    assert sum(i["code"] == "coverage_unresolved" for i in removed["issues"]) == 3


def test_v1_review_keeps_exact_prompt_identity_and_replays_without_added_evaluation(initial, response):
    from semantica.semantic_extract.candidate_coverage import _input, _json, _hash

    prompt = build_coverage_prompt(TEXT, initial, prompt_version=LEGACY_PROMPT_VERSION)
    assert hashlib.sha256(prompt.encode()).hexdigest() == "1e1be08863940edde7fe0b43bd01e2729df3f16cd4155d8a69b26444fd796826"
    response.pop("competency_reviews")
    record = {
        "prompt_version": LEGACY_PROMPT_VERSION, "provider": "openai", "model": "test",
        "input_sha256": _hash(_json(_input(TEXT, initial))), "prompt_sha256": _hash(prompt),
        "response": response,
    }
    result = apply_coverage_review(TEXT, initial, record)
    assert result["facts"]["relationships"][0]["metadata"]["prompt_version"] == LEGACY_PROMPT_VERSION
    assert "competency_reviews" not in result["extraction"]["coverage_review"]["response"]
    with patch("semantica.semantic_extract.candidate_profile.create_provider", side_effect=AssertionError("offline")):
        assert replay_candidate_facts(TEXT, result["extraction"], source_id="policy") == result


def test_v2_review_keeps_its_original_prompt_and_model_metadata(initial, response):
    from semantica.semantic_extract.candidate_coverage import _input, _json, _hash

    prompt = build_coverage_prompt(TEXT, initial, prompt_version=COMPETENCY_PROMPT_VERSION)
    assert hashlib.sha256(prompt.encode()).hexdigest() == "5d1bcfd609ff9dbf5e0b205da94a6437566543b5deb75b181f5f01dd7540cb8d"
    record = {
        "prompt_version": COMPETENCY_PROMPT_VERSION, "provider": "openai", "model": "test",
        "input_sha256": _hash(_json(_input(TEXT, initial))), "prompt_sha256": _hash(prompt),
        "response": response,
    }
    result = apply_coverage_review(TEXT, initial, record)
    assert result["facts"]["relationships"][0]["metadata"]["prompt_version"] == COMPETENCY_PROMPT_VERSION
    with patch("semantica.semantic_extract.candidate_profile.create_provider", side_effect=AssertionError("offline")):
        assert replay_candidate_facts(TEXT, result["extraction"], source_id="policy") == result


def test_failed_provider_has_no_fallback(initial):
    before = deepcopy(initial)
    provider = MagicMock()
    provider.generate_typed.side_effect = RuntimeError("private-never-export")
    with patch("semantica.semantic_extract.candidate_profile.create_provider", return_value=provider):
        with pytest.raises(ProcessingError) as error:
            review_candidate_facts(TEXT, initial, provider="openai", model="test")
    assert "private-never-export" not in str(error.value)
    assert initial == before


def test_empty_entities_skip_review():
    provider = MagicMock()
    provider.generate_typed.return_value = {"entities": []}
    with patch("semantica.semantic_extract.candidate_profile.create_provider", return_value=provider):
        result = extract_candidate_facts(TEXT, source_id="policy", provider="openai", model="test", review_coverage=True)
    assert provider.generate_typed.call_count == 1
    assert "coverage_review" not in result["extraction"]


@pytest.fixture
def stage_responses(response):
    question = response["competency_reviews"][0]
    diagnosis = {"questions": [{
        "id": "q1", "question": question["question"], "entity_ids": question["entity_ids"],
        "gap": "类别范围应可通过端点导航。", "evidence": evidence(),
    }], "non_question_entities": [{
        "entity_id": "e5", "reason": "附注仅描述标记颜色，无关系依据。", "evidence": evidence(4),
    }]}
    patch_result = {
        "retained_ids": ["r1"], "revisions": [], "removals": [],
        "additions": deepcopy(response["relationships"][1:]),
    }
    audit = {key: deepcopy(response[key]) for key in ["entity_reviews", "clause_reviews", "competency_reviews"]}
    audit.update(verdict="pass", findings=[])
    audit["competency_reviews"][0]["question_id"] = "q1"
    for group in ["entity_reviews", "clause_reviews", "competency_reviews"]:
        for item in audit[group]:
            item["relationship_ids"] = ["r1" if key == "f1" else key for key in item["relationship_ids"]]
    return [diagnosis, patch_result, audit]


def staged_review(initial, responses):
    from semantica.semantic_extract.candidate_coverage_stages import review_candidate_facts as staged

    provider = MagicMock()
    provider.generate_typed.side_effect = responses
    with patch("semantica.semantic_extract.candidate_profile.create_provider", return_value=provider):
        result = staged(TEXT, initial, provider="openai", model="test", max_tokens=32000,
                        reasoning_effort="low", api_key="private-never-export")
    return result, provider


def test_staged_review_caps_calls_and_replays_explicit_delta_without_a_provider(initial, stage_responses):
    before = deepcopy(initial)
    result, provider = staged_review(initial, stage_responses)
    assert initial == before
    assert len(result["facts"]["relationships"]) == 3
    assert result["facts"]["entities"] == initial["facts"]["entities"]
    assert [call.kwargs["max_tokens"] for call in provider.generate_typed.call_args_list] == [6000, 10000, 12000]
    record = result["extraction"]["coverage_review"]
    assert [stage["name"] for stage in record["stages"]] == ["diagnosis", "revision_1", "acceptance_1"]
    assert record["stages"][1]["response"]["retained_ids"] == ["r1"]
    assert "relationships" not in record["stages"][1]["response"]
    assert "private-never-export" not in json.dumps(result)
    assert result["facts"]["relationships"][0]["metadata"]["condition"] == initial["facts"]["relationships"][0]["metadata"]["condition"]
    with patch("semantica.semantic_extract.candidate_profile.create_provider", side_effect=AssertionError("offline")):
        assert replay_candidate_facts(TEXT, result["extraction"], source_id="policy") == result


def test_native_facade_uses_two_extraction_calls_then_three_review_stages(initial, stage_responses):
    provider = MagicMock()
    provider.generate_typed.side_effect = [
        initial["extraction"]["responses"]["entities"],
        initial["extraction"]["responses"]["relationships"], *stage_responses,
    ]
    with patch("semantica.semantic_extract.candidate_profile.create_provider", return_value=provider):
        result = extract_candidate_facts(TEXT, source_id="policy", provider="openai", model="test", review_coverage=True)
    assert provider.generate_typed.call_count == 5
    assert len(result["extraction"]["coverage_review"]["stages"]) == 3


@pytest.mark.parametrize("fault", ["plan_endpoint", "missing_disposition", "patch_endpoint", "question_endpoint", "missing_question"])
def test_staged_validation_stops_at_the_failed_stage_and_preserves_outputs(initial, stage_responses, fault):
    if fault == "plan_endpoint":
        stage_responses[0]["questions"][0]["entity_ids"].append("missing")
        count = 1
    elif fault == "missing_disposition":
        stage_responses[1]["retained_ids"].clear()
        count = 2
    elif fault == "patch_endpoint":
        stage_responses[1]["additions"][0]["target_id"] = "missing"
        count = 2
    elif fault == "question_endpoint":
        stage_responses[2]["competency_reviews"][0]["entity_ids"].pop()
        count = 3
    else:
        stage_responses[2]["competency_reviews"][0]["question_id"] = "missing"
        count = 3
    with pytest.raises(CoverageReviewError) as error:
        staged_review(initial, stage_responses)
    assert len(error.value.record["stages"]) == count


def test_model_rejection_routes_findings_to_one_bounded_revision_round(initial, stage_responses):
    diagnosis, patch_result, audit = stage_responses
    rejected = deepcopy(audit)
    rejected.update(verdict="needs_revision", findings=["明确补充可选类别的范围说明。"])
    second_patch = deepcopy(patch_result)
    second_patch["additions"][0]["condition"] += "；类别为可选范围"
    result, provider = staged_review(initial, [diagnosis, patch_result, rejected, second_patch, audit])
    assert provider.generate_typed.call_count == 5
    assert "PREVIOUS_ACCEPTANCE" in provider.generate_typed.call_args_list[3].args[0]
    assert result["facts"]["relationships"][1]["metadata"]["condition"].endswith("类别为可选范围")
    assert replay_candidate_facts(TEXT, result["extraction"], source_id="policy") == result
    with pytest.raises(CoverageReviewError, match="further revision") as error:
        staged_review(initial, [diagnosis, patch_result, rejected, second_patch, rejected])
    assert len(error.value.record["stages"]) == 5


@pytest.mark.parametrize("fault", ["prompt", "order", "extra_stage", "private_setting"])
def test_staged_replay_rejects_tampering(initial, stage_responses, fault):
    result, _ = staged_review(initial, stage_responses)
    stages = result["extraction"]["coverage_review"]["stages"]
    if fault == "prompt":
        stages[1]["prompt_sha256"] = "different"
    elif fault == "order":
        stages[1], stages[2] = stages[2], stages[1]
    elif fault == "private_setting":
        stages[1]["generation_options"]["api_key"] = "private-never-export"
    else:
        stages.append(deepcopy(stages[-1]))
    with pytest.raises(CoverageReviewError):
        replay_candidate_facts(TEXT, result["extraction"], source_id="policy")


def test_technical_retry_preserves_rejection_and_replays_model_correction(initial, stage_responses):
    from semantica.semantic_extract.candidate_coverage_stages import RelationshipPatch

    diagnosis, patch_result, audit = stage_responses
    invalid = deepcopy(patch_result)
    invalid["retained_ids"].append("r1")
    result, provider = staged_review(initial, [diagnosis, invalid, patch_result, audit])
    stages = result["extraction"]["coverage_review"]["stages"]
    assert [stage["name"] for stage in stages] == [
        "diagnosis", "revision_1", "revision_1_retry1", "acceptance_1",
    ]
    recorded_invalid = RelationshipPatch.model_validate(invalid).model_dump(mode="json")
    assert stages[1]["response"] == recorded_invalid
    assert "Duplicates: ['r1']" in stages[1]["validation_error"]
    retry_prompt = provider.generate_typed.call_args_list[2].args[0]
    retry_input = json.loads(retry_prompt.split("\nINPUT:\n", 1)[1])
    assert retry_input["TECHNICAL_RETRY"] == {
        "previous_response": recorded_invalid, "validation_error": stages[1]["validation_error"],
    }
    assert provider.generate_typed.call_count == 4
    with patch("semantica.semantic_extract.candidate_profile.create_provider", side_effect=AssertionError("offline")):
        assert replay_candidate_facts(TEXT, result["extraction"], source_id="policy") == result
    stages[1]["validation_error"] = "altered feedback"
    with pytest.raises(CoverageReviewError, match="feedback"):
        replay_candidate_facts(TEXT, result["extraction"], source_id="policy")


def test_technical_retry_is_bounded_without_fabricating_a_patch(initial, stage_responses):
    from semantica.semantic_extract.candidate_coverage_stages import RelationshipPatch

    diagnosis, invalid, audit = stage_responses
    invalid["retained_ids"].clear()
    provider = MagicMock()
    provider.generate_typed.side_effect = [diagnosis, invalid, invalid, audit]
    from semantica.semantic_extract.candidate_coverage_stages import review_candidate_facts as staged

    with patch("semantica.semantic_extract.candidate_profile.create_provider", return_value=provider):
        with pytest.raises(CoverageReviewError, match="missing:.*r1") as error:
            staged(TEXT, initial, provider="openai", model="test")
    assert provider.generate_typed.call_count == 3
    assert len(error.value.record["stages"]) == 3
    for item in error.value.record["stages"][1:]:
        assert item["response"] == RelationshipPatch.model_validate(invalid).model_dump(mode="json")
        assert "validation_error" in item


def test_resume_uses_validated_completed_stages_without_repeating_calls(initial, stage_responses):
    from semantica.semantic_extract.candidate_coverage_stages import review_candidate_facts as staged

    diagnosis, patch_result, audit = stage_responses
    with pytest.raises(CoverageReviewError) as error:
        staged_review(initial, [diagnosis, RuntimeError("provider interrupted")])
    checkpoint = error.value.record
    before = deepcopy(checkpoint)
    provider = MagicMock()
    provider.generate_typed.side_effect = [patch_result, audit]
    with patch("semantica.semantic_extract.candidate_profile.create_provider", return_value=provider):
        result = staged(TEXT, initial, provider="openai", model="test", resume_record=checkpoint)
    assert checkpoint == before
    assert provider.generate_typed.call_count == 2
    assert "Stage: revision_1\n" in provider.generate_typed.call_args_list[0].args[0]
    assert result["extraction"]["coverage_review"]["stages"][0] == before["stages"][0]
    with patch("semantica.semantic_extract.candidate_profile.create_provider", side_effect=AssertionError("offline")):
        assert replay_candidate_facts(TEXT, result["extraction"], source_id="policy") == result
        with pytest.raises(ValidationError, match="provider and model"):
            staged(TEXT, initial, provider="openai", model="changed", resume_record=checkpoint)
        checkpoint["input_sha256"] = "different source"
        with pytest.raises(CoverageReviewError, match="binding"):
            staged(TEXT, initial, provider="openai", model="test", resume_record=checkpoint)


def test_acceptance_feedback_identifies_missing_question_endpoint(initial, stage_responses):
    from semantica.semantic_extract.candidate_coverage_stages import CoverageAcceptance

    diagnosis, patch_result, audit = stage_responses
    invalid = deepcopy(audit)
    invalid["competency_reviews"][0]["relationship_ids"].remove("f2")
    result, provider = staged_review(initial, [diagnosis, patch_result, invalid, audit])
    failed = result["extraction"]["coverage_review"]["stages"][2]
    assert "question q1" in failed["validation_error"]
    assert "['e3']" in failed["validation_error"]
    assert failed["response"] == CoverageAcceptance.model_validate(invalid).model_dump(mode="json")
    assert provider.generate_typed.call_count == 4
    assert replay_candidate_facts(TEXT, result["extraction"], source_id="policy") == result


@pytest.mark.parametrize("fault", ["missing_question_entity", "missing_exclusion", "overlap", "unknown_exclusion"])
def test_diagnosis_accounts_for_every_entity_without_requiring_a_link(initial, stage_responses, fault):
    diagnosis = stage_responses[0]
    if fault == "missing_question_entity":
        diagnosis["questions"][0]["entity_ids"].remove("e3")
    elif fault == "missing_exclusion":
        diagnosis["non_question_entities"].clear()
    elif fault == "overlap":
        diagnosis["non_question_entities"][0]["entity_id"] = "e1"
    else:
        diagnosis["non_question_entities"][0]["entity_id"] = "unknown"
    with pytest.raises(CoverageReviewError, match="account for every entity") as error:
        staged_review(initial, [diagnosis, diagnosis])
    assert [item["name"] for item in error.value.record["stages"]] == ["diagnosis", "diagnosis_retry1"]
    assert all("validation_error" in item for item in error.value.record["stages"])
