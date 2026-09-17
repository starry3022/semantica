"""Offline contract tests for evidence-backed, candidate process rules."""

import copy
import hashlib
import importlib.util
import json
import unittest
from decimal import Decimal
from unittest.mock import Mock, patch


class ProcessExtractorContractTests(unittest.TestCase):
    def setUp(self):
        module = "semantica.semantic_extract.process_extractor"
        self.assertIsNotNone(
            importlib.util.find_spec(module),
            "The opt-in process rule extractor has not been implemented",
        )
        from semantica.semantic_extract import process_extractor, process_schemas

        self.extractor = process_extractor
        self.schemas = process_schemas
        self.text = (
            "设备检修办法\n版本：示例\n\n"
            "检修时长不少于2小时且少于8小时，由值班工程师和安全员共同批准。\n\n"
            "夜间检修还需要厂长批准，并在检修完成后2个工作日内提交验收单。"
        )
        self.response = {
            "rules": [
                {
                    "id": "R001",
                    "source_clause_id": "C002",
                    "activity": "设备检修",
                    "action": "审批",
                    "modality": "obligation",
                    "actors": [],
                    "conditions": [
                        {
                            "text": "检修时长不少于2小时且少于8小时",
                            "numeric": {
                                "field": "检修时长",
                                "lower": "2",
                                "upper": "8",
                                "lower_inclusive": True,
                                "upper_inclusive": False,
                                "unit": "小时",
                            },
                        }
                    ],
                    "condition_logic": "all",
                    "approvals": {"roles": ["值班工程师", "安全员"], "mode": "all"},
                    "required_documents": [],
                    "deadline": None,
                    "supporting_clause_ids": [],
                    "evidence": [
                        {"clause_id": "C002", "quote": self.text.split("\n\n")[1]}
                    ],
                    "confidence": 0.8,
                },
                {
                    "id": "R002",
                    "source_clause_id": "C003",
                    "activity": "夜间检修",
                    "action": "审批并提交验收单",
                    "modality": "obligation",
                    "actors": [],
                    "conditions": [{"text": "夜间检修", "numeric": None}],
                    "condition_logic": "all",
                    "approvals": {"roles": ["值班工程师", "安全员", "厂长"], "mode": "all"},
                    "required_documents": ["验收单"],
                    "deadline": {
                        "value": 2,
                        "unit": "working_day",
                        "anchor": "检修完成",
                        "relation": "after",
                        "text": "检修完成后2个工作日内",
                    },
                    "supporting_clause_ids": ["C002"],
                    "evidence": [
                        {"clause_id": "C003", "quote": self.text.split("\n\n")[2]},
                        {"clause_id": "C002", "quote": "由值班工程师和安全员共同批准"},
                    ],
                    "confidence": 0.7,
                },
            ],
            "clause_assessments": [
                {
                    "clause_id": "C001",
                    "disposition": "non_normative",
                    "reason": "仅标题与示例版本",
                },
                {"clause_id": "C002", "disposition": "rule", "reason": "检修审批条件"},
                {"clause_id": "C003", "disposition": "rule", "reason": "附加审批与提交时限"},
            ],
        }

    def finalize(self, response=None, text=None):
        return self.extractor.finalize_process_rules(
            self.text if text is None else text,
            "example:maintenance",
            self.response if response is None else response,
        )

    def test_preserves_process_semantics_and_exact_evidence_offsets(self):
        result = self.finalize()
        self.assertEqual(result.rules[0].conditions[0].numeric.lower, Decimal("2"))
        self.assertFalse(result.rules[0].conditions[0].numeric.upper_inclusive)
        self.assertEqual(result.rules[1].approvals.roles, ["值班工程师", "安全员", "厂长"])
        self.assertEqual(result.rules[1].required_documents, ["验收单"])
        self.assertEqual(result.rules[1].deadline.anchor, "检修完成")
        self.assertEqual(result.rules[1].deadline.unit, "working_day")
        for span in result.evidence_spans:
            self.assertEqual(self.text[span.start_char : span.end_char], span.quote)
        self.assertEqual(
            result.source_sha256, hashlib.sha256(self.text.encode()).hexdigest()
        )
        self.assertEqual(result.text_length, len(self.text))
        self.assertEqual(result.fact_status, "candidate")
        self.assertEqual(result.review_status, "unreviewed")
        self.assertTrue(result.coverage["complete"])
        self.assertEqual(result.coverage["status"], "needs_review")
        self.assertEqual(result.coverage["issues"], [])
        json.dumps(result.model_dump(mode="json"), ensure_ascii=False)

    def test_segmentation_preserves_content_and_original_offsets(self):
        text = " \r\n设备办法\r\n版本一\r\n  \r\n\t申请人应提交检修单。\r\n\r\n"
        clauses = self.extractor.segment_source_clauses(text)
        self.assertEqual([clause.id for clause in clauses], ["C001", "C002"])
        self.assertEqual(
            [clause.text for clause in clauses], ["设备办法\r\n版本一", "申请人应提交检修单。"]
        )
        for clause in clauses:
            self.assertEqual(text[clause.start_char : clause.end_char], clause.text)
        self.assertEqual(
            "".join(text.split()), "".join("".join(c.text.split()) for c in clauses)
        )

    def test_strict_schema_rejects_unknown_fields_at_every_depth(self):
        for location in (
            "response",
            "rule",
            "condition",
            "numeric",
            "evidence",
            "approval",
            "deadline",
            "assessment",
        ):
            response = copy.deepcopy(self.response)
            targets = {
                "response": response,
                "rule": response["rules"][0],
                "condition": response["rules"][0]["conditions"][0],
                "numeric": response["rules"][0]["conditions"][0]["numeric"],
                "evidence": response["rules"][0]["evidence"][0],
                "approval": response["rules"][0]["approvals"],
                "deadline": response["rules"][1]["deadline"],
                "assessment": response["clause_assessments"][0],
            }
            targets[location]["invented"] = True
            with self.subTest(location=location), self.assertRaises(ValueError):
                self.finalize(response)

    def test_numeric_bounds_are_finite_and_nonempty(self):
        original = self.response["rules"][0]["conditions"][0]["numeric"]
        for changes in (
            {"lower": float("nan")},
            {"upper": float("inf")},
            {"lower": "9", "upper": "8"},
            {"lower": "8", "upper": "8", "upper_inclusive": False},
            {"lower": None, "upper": None},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.schemas.NumericConstraint.model_validate({**original, **changes})
        exact = self.schemas.NumericConstraint.model_validate(
            {**original, "lower": "8", "upper": "8", "upper_inclusive": True}
        )
        self.assertEqual(exact.lower, exact.upper)
        lower_only = self.schemas.NumericConstraint.model_validate(
            {**original, "upper": None}
        )
        self.assertIsNone(lower_only.upper)

    def test_approval_disjunction_and_process_terms_are_not_hardcoded(self):
        text = "数据销毁须由数据保护官或审计负责人批准。"
        candidate = copy.deepcopy(self.response["rules"][0])
        candidate.update(
            activity="数据销毁",
            source_clause_id="C001",
            conditions=[],
            approvals={"roles": ["数据保护官", "审计负责人"], "mode": "any"},
            evidence=[{"clause_id": "C001", "quote": text}],
        )
        response = {
            "rules": [candidate],
            "clause_assessments": [
                {
                    "clause_id": "C001",
                    "disposition": "rule",
                    "reason": "替代审批角色",
                }
            ],
        }
        rule = self.finalize(response, text).rules[0]
        self.assertEqual(rule.activity, "数据销毁")
        self.assertEqual(rule.approvals.mode, "any")
        self.assertEqual(rule.approvals.roles, ["数据保护官", "审计负责人"])

    def test_fabricated_or_ambiguous_evidence_is_rejected(self):
        for quote in ("不存在的证据", " "):
            response = copy.deepcopy(self.response)
            response["rules"][0]["evidence"][0]["quote"] = quote
            with self.subTest(quote=quote), self.assertRaises(ValueError):
                self.finalize(response)
        response = {
            "rules": [copy.deepcopy(self.response["rules"][0])],
            "clause_assessments": [],
        }
        response["rules"][0]["source_clause_id"] = "C001"
        response["rules"][0]["evidence"] = [{"clause_id": "C001", "quote": "批准"}]
        with self.assertRaisesRegex(ValueError, "ambiguous|unique"):
            self.finalize(response, "批准后再次批准。")

    def test_primary_and_supporting_clauses_require_evidence(self):
        for index in (0, 1):
            response = copy.deepcopy(self.response)
            response["rules"][1]["evidence"].pop(index)
            with self.subTest(index=index), self.assertRaisesRegex(
                ValueError, "evidence"
            ):
                self.finalize(response)

    def test_unknown_clause_and_duplicate_ids_are_rejected(self):
        for change in (
            "source",
            "support",
            "evidence",
            "assessment",
            "duplicate_rule",
            "duplicate_assessment",
        ):
            response = copy.deepcopy(self.response)
            if change == "source":
                response["rules"][0]["source_clause_id"] = "C099"
            elif change == "support":
                response["rules"][1]["supporting_clause_ids"] = ["C099"]
            elif change == "evidence":
                response["rules"][0]["evidence"][0]["clause_id"] = "C099"
            elif change == "assessment":
                response["clause_assessments"][0]["clause_id"] = "C099"
            elif change == "duplicate_rule":
                response["rules"].append(copy.deepcopy(response["rules"][0]))
            else:
                response["clause_assessments"].append(
                    copy.deepcopy(response["clause_assessments"][0])
                )
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.finalize(response)

    def test_missing_assessment_rule_or_unresolved_clause_never_reports_complete(self):
        for change in ("unassessed", "unlinked", "unresolved", "contradiction"):
            response = copy.deepcopy(self.response)
            if change == "unassessed":
                response["clause_assessments"].pop()
            elif change == "unlinked":
                response["rules"].pop()
            elif change == "unresolved":
                response["clause_assessments"][2]["disposition"] = "unresolved"
            else:
                response["clause_assessments"][2]["disposition"] = "non_normative"
            with self.subTest(change=change):
                result = self.finalize(response)
                self.assertFalse(result.coverage["complete"])
                self.assertTrue(result.coverage["issues"])
                self.assertEqual(result.coverage["status"], "needs_review")

    def test_reason_deadline_and_confidence_are_validated(self):
        for change in ("reason", "deadline", "confidence"):
            response = copy.deepcopy(self.response)
            if change == "reason":
                response["clause_assessments"][0]["reason"] = "  "
            elif change == "deadline":
                response["rules"][1]["deadline"]["value"] = 0
            else:
                response["rules"][0]["confidence"] = float("nan")
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.finalize(response)

    def test_source_identity_and_nonempty_text_are_required(self):
        for text, source_id in ((" \n", "test"), (self.text, " ")):
            with self.subTest(text=text, source_id=source_id), self.assertRaises(
                ValueError
            ):
                self.extractor.finalize_process_rules(text, source_id, self.response)

    def test_provider_called_once_with_generic_clause_aware_prompt(self):
        llm = Mock()
        llm.generate_typed.return_value = (
            self.schemas.ProcessRulesResponse.model_validate(self.response)
        )
        with patch.object(
            self.extractor, "create_provider", return_value=llm
        ) as factory:
            result = self.extractor.extract_process_rules(
                self.text,
                source_id="example:maintenance",
                provider="openai",
                model="test-model",
                temperature=0,
                max_tokens=8192,
            )
        factory.assert_called_once_with(
            "openai", model="test-model", temperature=0, max_tokens=8192
        )
        llm.generate_typed.assert_called_once()
        args, kwargs = llm.generate_typed.call_args
        self.assertIs(args[1], self.schemas.ProcessRulesResponse)
        self.assertEqual(kwargs["max_retries"], 1)
        self.assertEqual(kwargs["model"], "test-model")
        prompt = args[0]
        self.assertIn("C001", prompt)
        self.assertIn("C003", prompt)
        self.assertIn(self.text.split("\n\n")[2], prompt)
        self.assertIn("supporting_clause_ids", prompt)
        self.assertNotIn("财务负责人", prompt)
        self.assertNotIn("5000", prompt)
        self.assertEqual(result.source_id, "example:maintenance")

    def test_provider_failure_propagates_without_fallback(self):
        llm = Mock()
        llm.generate_typed.side_effect = RuntimeError("provider unavailable")
        with patch.object(self.extractor, "create_provider", return_value=llm):
            with self.assertRaisesRegex(RuntimeError, "provider unavailable"):
                self.extractor.extract_process_rules(self.text, source_id="test")
        llm.generate_typed.assert_called_once()
        llm.generate.assert_not_called()

    def test_provider_source_json_roundtrips_multiline_clauses(self):
        llm = Mock()
        llm.generate_typed.return_value = self.response
        with patch.object(self.extractor, "create_provider", return_value=llm):
            self.extractor.extract_process_rules(self.text, source_id="test")
        prompt = llm.generate_typed.call_args.args[0]
        source_json = prompt.split("BEGIN SOURCE CLAUSES\n", 1)[1].rsplit(
            "\nEND SOURCE CLAUSES", 1
        )[0]
        self.assertTrue(
            source_json.startswith("[{"),
            "Clauses must be serialized as a JSON array, preserving line escapes",
        )
        source = json.loads(source_json)
        self.assertEqual(source[0], {"id": "C001", "text": "设备检修办法\n版本：示例"})
        self.assertIn("\\n", source_json)
        self.assertEqual(
            [item["text"] for item in source],
            [
                clause.text
                for clause in self.extractor.segment_source_clauses(self.text)
            ],
        )

    def test_recipients_remain_separate_from_actors_and_approvals(self):
        text = "设备员应向运维主管报送检修记录及验收单。"
        candidate = copy.deepcopy(self.response["rules"][0])
        candidate.update(
            source_clause_id="C001",
            action="报送",
            actors=["设备员"],
            recipient_roles=["运维主管"],
            approvals=None,
            conditions=[],
            required_documents=["检修记录", "验收单"],
            evidence=[{"clause_id": "C001", "quote": text}],
        )
        self.assertIn("recipient_roles", self.schemas.ProcessRule.model_fields)
        result = self.finalize(
            {
                "rules": [candidate],
                "clause_assessments": [
                    {
                        "clause_id": "C001",
                        "disposition": "rule",
                        "reason": "材料报送义务",
                    }
                ],
            },
            text,
        )
        self.assertEqual(result.rules[0].actors, ["设备员"])
        self.assertEqual(result.rules[0].recipient_roles, ["运维主管"])
        self.assertIsNone(result.rules[0].approvals)
        self.assertEqual(result.rules[0].required_documents, ["检修记录", "验收单"])
        self.assertEqual(self.finalize().rules[0].recipient_roles, [])

    def test_linebreak_normalization_in_evidence_is_still_rejected(self):
        text = "设备员应提交\n检修记录。"
        candidate = copy.deepcopy(self.response["rules"][0])
        candidate.update(
            source_clause_id="C001",
            evidence=[{"clause_id": "C001", "quote": text}],
        )
        response = {"rules": [candidate], "clause_assessments": []}
        self.assertEqual(self.finalize(response, text).evidence_spans[0].quote, text)
        for replacement in ("", " "):
            candidate["evidence"][0]["quote"] = text.replace("\n", replacement)
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                self.finalize(response, text)

    def test_mutated_pydantic_response_is_revalidated(self):
        response = self.schemas.ProcessRulesResponse.model_validate(self.response)
        response.rules[1].deadline.value = True
        with self.assertRaises(ValueError):
            self.finalize(response)

    def test_flags_confidence_and_offsets_reject_non_numeric_types(self):
        numeric = self.response["rules"][0]["conditions"][0]["numeric"]
        for field in ("lower_inclusive", "upper_inclusive"):
            for value in (1, 0, "true", "false"):
                with self.subTest(field=field, value=value), self.assertRaises(
                    ValueError
                ):
                    self.schemas.NumericConstraint.model_validate(
                        {**numeric, field: value}
                    )
        for value in (True, False, "0.9"):
            rule = {**self.response["rules"][0], "confidence": value}
            with self.subTest(confidence=value), self.assertRaises(ValueError):
                self.schemas.ProcessRule.model_validate(rule)
        for value in (0, 1, 0.9):
            rule = {**self.response["rules"][0], "confidence": value}
            self.assertEqual(
                self.schemas.ProcessRule.model_validate(rule).confidence, value
            )
        result = self.finalize().model_dump(mode="json")
        for schema, original, field, value in (
            (self.schemas.SourceClause, result["clauses"][0], "start_char", False),
            (self.schemas.SourceClause, result["clauses"][0], "end_char", True),
            (
                self.schemas.EvidenceSpan,
                result["evidence_spans"][0],
                "start_char",
                False,
            ),
            (self.schemas.EvidenceSpan, result["evidence_spans"][0], "end_char", True),
            (self.schemas.ProcessExtractionResult, result, "text_length", True),
        ):
            with self.subTest(schema=schema.__name__, field=field), self.assertRaises(
                ValueError
            ):
                schema.model_validate({**original, field: value})

    def test_empty_model_output_is_an_error_but_descriptive_documents_are_candidates(
        self,
    ):
        with self.assertRaisesRegex(ValueError, "empty|no rules|no assessments"):
            self.finalize({"rules": [], "clause_assessments": []})
        result = self.finalize(
            {
                "rules": [],
                "clause_assessments": [
                    {
                        "clause_id": "C001",
                        "disposition": "non_normative",
                        "reason": "仅说明文档用途，没有规范性要求",
                    }
                ],
            },
            "本文件介绍设备检修业务。",
        )
        self.assertEqual(result.rules, [])
        self.assertEqual(result.fact_status, "candidate")
        self.assertEqual(result.review_status, "unreviewed")
        self.assertEqual(result.coverage["status"], "needs_review")

    def test_nonquantitative_order_and_document_qualifiers_remain_in_rules(self):
        text = "作业前，检修员应提交有效的检修许可。"
        candidate = copy.deepcopy(self.response["rules"][0])
        candidate.update(
            source_clause_id="C001",
            action="作业前提交有效的检修许可",
            actors=["检修员"],
            approvals=None,
            conditions=[{"text": "作业前，且检修许可有效", "numeric": None}],
            required_documents=["检修许可"],
            evidence=[{"clause_id": "C001", "quote": text}],
        )
        response = {
            "rules": [candidate],
            "clause_assessments": [
                {
                    "clause_id": "C001",
                    "disposition": "rule",
                    "reason": "事前材料要求",
                }
            ],
        }
        result = self.finalize(response, text)
        self.assertIsNone(result.rules[0].deadline)
        self.assertEqual(result.rules[0].action, "作业前提交有效的检修许可")
        self.assertEqual(result.rules[0].conditions[0].text, "作业前，且检修许可有效")

    def test_provider_prompt_explicitly_requires_approval_groups(self):
        """Check the prompt contract, not the quality of a real model response."""
        llm = Mock()
        llm.generate_typed.return_value = self.response
        with patch.object(self.extractor, "create_provider", return_value=llm):
            self.extractor.extract_process_rules(self.text, source_id="test")
        prompt = llm.generate_typed.call_args.args[0]
        self.assertIn("Approval-group contract:", prompt)
        self.assertIn("actors never encodes approval AND/OR", prompt)
        self.assertIn("condition_logic never replaces approvals.mode", prompt)
        self.assertIn("approvals=null is invalid", prompt)
        examples_json = prompt.split("BEGIN APPROVAL EXAMPLES\n", 1)[1].split(
            "\nEND APPROVAL EXAMPLES", 1
        )[0]
        examples = json.loads(examples_json)
        self.assertEqual(len(examples), 2)
        self.assertEqual(examples[0]["approvals"]["mode"], "all")
        self.assertEqual(examples[1]["approvals"]["mode"], "any")
        for example in examples:
            self.assertEqual(
                example["approvals"]["roles"], ["Reviewer A", "Reviewer B"]
            )
            self.assertEqual(example["actors"], example["approvals"]["roles"])
        self.assertNotIn("财务负责人", examples_json)
        self.assertNotIn("5000", examples_json)

    def test_provider_prompt_requires_boolean_flags_for_unbounded_intervals(self):
        """Unbounded numeric endpoints do not make the flags nullable."""
        llm = Mock()
        llm.generate_typed.return_value = self.response
        with patch.object(self.extractor, "create_provider", return_value=llm):
            self.extractor.extract_process_rules(self.text, source_id="test")
        prompt = llm.generate_typed.call_args.args[0]
        self.assertIn(
            "lower_inclusive and upper_inclusive are ALWAYS JSON booleans", prompt
        )
        self.assertIn(
            "For an absent lower bound, use lower=null and lower_inclusive=false",
            prompt,
        )
        self.assertIn(
            "For an absent upper bound, use upper=null and upper_inclusive=false",
            prompt,
        )
        self.assertIn("never use null for either inclusive flag", prompt)

    def test_provider_prompt_preserves_shared_document_qualification_scope(self):
        """A prompt contract check, not an asserted model accuracy result."""
        llm = Mock()
        llm.generate_typed.return_value = self.response
        with patch.object(self.extractor, "create_provider", return_value=llm):
            self.extractor.extract_process_rules(self.text, source_id="test")
        prompt = llm.generate_typed.call_args.args[0]
        self.assertIn("Document qualification contract:", prompt)
        contract = prompt.split("Document qualification contract:\n", 1)[1].split(
            "\nJSON schema:", 1
        )[0]
        self.assertIn("shared qualifications", contract)
        self.assertIn("original complete document requirement", contract)
        self.assertIn("only the first item", contract)
        self.assertIn("required_documents", contract)
        self.assertIn("unresolved", contract)
        self.assertIn("Before returning output", contract)
        self.assertNotIn("合法有效的合同", contract)


if __name__ == "__main__":
    unittest.main()
