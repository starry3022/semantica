"""Process-rule projection preserves constraints and validates real RDF data."""

import copy
import hashlib
import json
import unittest
from decimal import Decimal

from pyshacl import validate
from rdflib import Graph, Literal, Namespace, RDF, URIRef, XSD
from rdflib.compare import isomorphic

from semantica.semantic_extract.process_graph import (
    export_process_rdf,
    process_rule_ontology,
    process_rule_shapes,
    process_rules_to_graph,
)


BASE = "https://example.org/test-process/"
NS = Namespace(BASE)
TEXT = "金额达到100且低于500元时，经主管和财务批准。申请人须于批准后2个工作日内补交申请单。"


def result_fixture():
    quote = "申请人须于批准后2个工作日内补交申请单。"
    return {
        "source_id": "policy.txt",
        "source_sha256": hashlib.sha256(TEXT.encode()).hexdigest(),
        "text_length": len(TEXT),
        "clauses": [
            {"id": "clause-1", "text": TEXT, "start_char": 0, "end_char": len(TEXT)}
        ],
        "rules": [
            {
                "id": "rule-1",
                "source_clause_id": "clause-1",
                "activity": "采购",
                "action": "补交",
                "modality": "obligation",
                "actors": ["申请人"],
                "recipient_roles": [],
                "conditions": [
                    {
                        "text": "金额达到100且低于500元",
                        "numeric": {
                            "field": "金额",
                            "lower": "100",
                            "upper": "500",
                            "lower_inclusive": True,
                            "upper_inclusive": False,
                            "unit": "元",
                        },
                    }
                ],
                "condition_logic": "all",
                "approvals": {"roles": ["主管", "财务"], "mode": "all"},
                "required_documents": ["申请单"],
                "deadline": {
                    "value": 2,
                    "unit": "working_day",
                    "anchor": "批准",
                    "relation": "after",
                    "text": "批准后2个工作日内",
                },
                "supporting_clause_ids": [],
                "evidence": [{"clause_id": "clause-1", "quote": quote}],
                "confidence": 0.91,
            }
        ],
        "evidence_spans": [
            {
                "rule_id": "rule-1",
                "clause_id": "clause-1",
                "quote": quote,
                "start_char": TEXT.index(quote),
                "end_char": len(TEXT),
            }
        ],
        "coverage": {"clause_count": 1, "covered_clause_count": 1},
        "fact_status": "candidate",
        "review_status": "unreviewed",
    }


class TestProcessGraph(unittest.TestCase):
    def setUp(self):
        self.result = result_fixture()
        self.graph = process_rules_to_graph(self.result, BASE)

    def nodes(self, kind):
        return [node for node in self.graph["nodes"] if node["type"] == kind]

    def rdf(self):
        return Graph().parse(data=export_process_rdf(self.graph), format="turtle")

    def test_rule_is_candidate_norm_and_retains_complete_input(self):
        rule = self.nodes("ProcessRule")[0]
        self.assertEqual(rule["properties"]["rule_data"], self.result["rules"][0])
        self.assertEqual(rule["properties"]["fact_status"], "candidate")
        self.assertEqual(rule["properties"]["review_status"], "unreviewed")
        self.assertNotIn("Event", {node["type"] for node in self.graph["nodes"]})
        self.assertEqual(
            {node["type"] for node in self.graph["nodes"]},
            {
                "ProcessRule",
                "Activity",
                "Role",
                "ApprovalGroup",
                "Condition",
                "RequiredDocument",
                "RelativeDeadline",
                "Evidence",
                "SourceDocument",
            },
        )

    def test_all_endpoints_resolve_and_approval_roles_are_grouped(self):
        ids = {node["id"] for node in self.graph["nodes"]}
        self.assertEqual(len(ids), len(self.graph["nodes"]))
        for edge in self.graph["edges"]:
            self.assertIn(edge["source_id"], ids)
            self.assertIn(edge["target_id"], ids)
        group = self.nodes("ApprovalGroup")[0]
        self.assertEqual(group["properties"]["mode"], "all")
        role_ids = {
            edge["target_id"]
            for edge in self.graph["edges"]
            if edge["source_id"] == group["id"] and edge["type"] == "hasRole"
        }
        self.assertEqual(
            {node["label"] for node in self.nodes("Role") if node["id"] in role_ids},
            {"主管", "财务"},
        )

    def test_shared_roles_do_not_merge_rule_conditions(self):
        second = copy.deepcopy(self.result["rules"][0])
        second["id"] = "rule-2"
        second["approvals"]["mode"] = "any"
        self.result["rules"].append(second)
        span = {**self.result["evidence_spans"][0], "rule_id": "rule-2"}
        self.result["evidence_spans"].append(span)
        self.graph = process_rules_to_graph(self.result, BASE)
        self.assertEqual(len(self.nodes("Role")), 3)
        self.assertEqual(len(self.nodes("Activity")), 1)
        self.assertEqual(len(self.nodes("Condition")), 2)
        self.assertEqual(
            {n["properties"]["mode"] for n in self.nodes("ApprovalGroup")},
            {"all", "any"},
        )

    def test_ids_are_stable_and_separated_by_source_hash(self):
        self.assertEqual(
            self.graph, process_rules_to_graph(copy.deepcopy(self.result), BASE)
        )
        source_hash = self.result["source_sha256"]
        self.assertTrue(all(source_hash in node["id"] for node in self.graph["nodes"]))
        other = {**self.result, "source_sha256": "a" * 64}
        other_graph = process_rules_to_graph(other, BASE)
        self.assertFalse(
            {n["id"] for n in self.graph["nodes"]}
            & {n["id"] for n in other_graph["nodes"]}
        )

    def test_identical_text_from_different_sources_has_distinct_nodes_and_edges(self):
        other = {**self.result, "source_id": "another-policy.txt"}
        other_graph = process_rules_to_graph(other, BASE)
        for collection in ("nodes", "edges"):
            self.assertFalse(
                {item["id"] for item in self.graph[collection]}
                & {item["id"] for item in other_graph[collection]}
            )

    def test_evidence_preserves_actual_offsets_and_source(self):
        evidence = self.nodes("Evidence")[0]["properties"]
        self.assertEqual(evidence["source_id"], "policy.txt")
        self.assertEqual(evidence["source_sha256"], self.result["source_sha256"])
        self.assertEqual(
            TEXT[evidence["start_char"] : evidence["end_char"]], evidence["quote"]
        )
        self.assertEqual(self.nodes("Condition")[0]["properties"]["lower"], "100")
        self.assertFalse(self.nodes("Condition")[0]["properties"]["upper_inclusive"])

    def test_missing_alignment_is_rejected_without_invented_evidence(self):
        self.result["evidence_spans"] = []
        with self.assertRaises(ValueError):
            process_rules_to_graph(self.result, BASE)

    def test_recipient_roles_are_separate_from_actor_roles(self):
        self.result["rules"][0]["recipient_roles"] = ["主管"]
        self.graph = process_rules_to_graph(self.result, BASE)
        rule = self.nodes("ProcessRule")[0]["id"]
        recipient_ids = {
            edge["target_id"]
            for edge in self.graph["edges"]
            if edge["source_id"] == rule and edge["type"] == "hasRecipient"
        }
        actor_ids = {
            edge["target_id"]
            for edge in self.graph["edges"]
            if edge["source_id"] == rule and edge["type"] == "hasActor"
        }
        self.assertEqual(
            {
                node["label"]
                for node in self.nodes("Role")
                if node["id"] in recipient_ids
            },
            {"主管"},
        )
        self.assertEqual(
            {node["label"] for node in self.nodes("Role") if node["id"] in actor_ids},
            {"申请人"},
        )

    def test_dict_input_must_satisfy_process_schema(self):
        self.result["rules"][0]["deadline"]["value"] = 0
        with self.assertRaises(ValueError):
            process_rules_to_graph(self.result, BASE)

    def test_equal_length_quote_forgery_is_rejected_against_clause(self):
        quote = self.result["rules"][0]["evidence"][0]["quote"].replace("申请人", "审核人")
        self.result["rules"][0]["evidence"][0]["quote"] = quote
        self.result["evidence_spans"][0]["quote"] = quote
        with self.assertRaises(ValueError):
            process_rules_to_graph(self.result, BASE)

    def test_rule_references_must_exist_and_be_unique(self):
        for change in ("primary", "support", "duplicate"):
            result = copy.deepcopy(self.result)
            if change == "primary":
                result["rules"][0]["source_clause_id"] = "NONEXISTENT"
            elif change == "support":
                result["rules"][0]["supporting_clause_ids"] = ["NONEXISTENT"]
            else:
                result["rules"][0]["supporting_clause_ids"] = ["clause-1"]
            with self.subTest(change=change), self.assertRaises(ValueError):
                process_rules_to_graph(result, BASE)

    def test_every_referenced_clause_needs_evidence_and_uncited_clauses_are_rejected(
        self,
    ):
        extra = "所有检修必须登记。"
        self.result["source_sha256"] = hashlib.sha256(
            (TEXT + extra).encode()
        ).hexdigest()
        self.result["text_length"] += len(extra)
        self.result["clauses"].append(
            {
                "id": "clause-2",
                "text": extra,
                "start_char": len(TEXT),
                "end_char": len(TEXT) + len(extra),
            }
        )
        for change in (
            "missing_support_evidence",
            "missing_primary_evidence",
            "unreferenced_evidence",
        ):
            result = copy.deepcopy(self.result)
            rule = result["rules"][0]
            if change == "missing_support_evidence":
                rule["supporting_clause_ids"] = ["clause-2"]
            elif change == "missing_primary_evidence":
                rule["source_clause_id"] = "clause-2"
                rule["supporting_clause_ids"] = ["clause-1"]
            else:
                rule["evidence"].append({"clause_id": "clause-2", "quote": extra})
                result["evidence_spans"].append(
                    {
                        "rule_id": "rule-1",
                        "clause_id": "clause-2",
                        "quote": extra,
                        "start_char": len(TEXT),
                        "end_char": len(TEXT) + len(extra),
                    }
                )
            with self.subTest(change=change), self.assertRaises(ValueError):
                process_rules_to_graph(result, BASE)

    def test_invalid_base_iris_are_rejected(self):
        for base in (
            "relative/path",
            "https://",
            "https://example.org/a b/",
            "",
            "https://example.org/%xx/",
        ):
            with self.subTest(base=base), self.assertRaises(ValueError):
                process_rules_to_graph(self.result, base)

    def test_scalar_and_json_fields_survive_json_to_rdf(self):
        self.graph = json.loads(json.dumps(self.graph, ensure_ascii=False))
        rdf = self.rdf()
        rule = URIRef(self.nodes("ProcessRule")[0]["id"])
        condition = URIRef(self.nodes("Condition")[0]["id"])
        deadline = URIRef(self.nodes("RelativeDeadline")[0]["id"])
        evidence = URIRef(self.nodes("Evidence")[0]["id"])
        raw_rule = rdf.value(rule, NS.rule_data)
        self.assertEqual(raw_rule.datatype, RDF.JSON)
        self.assertEqual(json.loads(str(raw_rule)), self.result["rules"][0])
        self.assertEqual(rdf.value(condition, NS["lower"]).datatype, XSD.decimal)
        self.assertEqual(rdf.value(condition, NS["lower"]).toPython(), 100)
        self.assertEqual(rdf.value(condition, NS.upper_inclusive), Literal(False))
        self.assertEqual(rdf.value(deadline, NS.value).datatype, XSD.integer)
        self.assertEqual(rdf.value(deadline, NS.value).toPython(), 2)
        self.assertEqual(str(rdf.value(deadline, NS.anchor)), "批准")
        self.assertEqual(rdf.value(evidence, NS.start_char).datatype, XSD.integer)
        self.assertEqual(
            str(rdf.value(evidence, NS.source_sha256)), self.result["source_sha256"]
        )

    def test_pydantic_decimal_precision_survives_json_and_rdf(self):
        from semantica.semantic_extract.process_schemas import ProcessExtractionResult

        self.result["rules"][0]["conditions"][0]["numeric"][
            "lower"
        ] = "100.1234567890123456789"
        model = ProcessExtractionResult.model_validate(self.result)
        self.graph = json.loads(json.dumps(process_rules_to_graph(model, BASE)))
        self.assertEqual(
            self.nodes("Condition")[0]["properties"]["lower"], "100.1234567890123456789"
        )
        condition = URIRef(self.nodes("Condition")[0]["id"])
        self.assertEqual(
            str(self.rdf().value(condition, NS["lower"])), "100.1234567890123456789"
        )

    def test_python_dict_with_decimal_keeps_exact_numeric_value(self):
        self.result["rules"][0]["conditions"][0]["numeric"]["lower"] = Decimal(
            "100.0000000000000000001"
        )
        self.graph = process_rules_to_graph(self.result, BASE)
        self.assertEqual(
            self.nodes("Condition")[0]["properties"]["lower"], "100.0000000000000000001"
        )
        condition = URIRef(self.nodes("Condition")[0]["id"])
        self.assertEqual(
            self.rdf().value(condition, NS["lower"]).toPython(),
            Decimal("100.0000000000000000001"),
        )

    def test_turtle_round_trip_preserves_triples(self):
        first = self.rdf()
        second = Graph().parse(data=first.serialize(format="turtle"), format="turtle")
        self.assertTrue(isomorphic(first, second))

    def test_native_shapes_validate_candidate_graph(self):
        shapes = process_rule_shapes(BASE)
        sh = Namespace("http://www.w3.org/ns/shacl#")
        self.assertGreater(
            len(list(shapes.triples((None, RDF.type, sh.PropertyShape)))), 0
        )
        conforms, _, report = validate(
            self.rdf(), shacl_graph=shapes, ont_graph=process_rule_ontology(BASE)
        )
        self.assertTrue(conforms, report)

    def test_removing_rule_evidence_fails_real_shacl(self):
        rdf = self.rdf()
        rule = URIRef(self.nodes("ProcessRule")[0]["id"])
        rdf.remove((rule, NS.hasEvidence, None))
        conforms, _, _ = validate(rdf, shacl_graph=process_rule_shapes(BASE))
        self.assertFalse(conforms)

    def test_removing_deadline_anchor_fails_real_shacl(self):
        rdf = self.rdf()
        deadline = URIRef(self.nodes("RelativeDeadline")[0]["id"])
        rdf.remove((deadline, NS.anchor, None))
        conforms, _, _ = validate(rdf, shacl_graph=process_rule_shapes(BASE))
        self.assertFalse(conforms)

    def test_invalid_approval_mode_and_evidence_offsets_fail_shacl(self):
        for kind, predicate, bad in (
            ("ApprovalGroup", NS.mode, Literal("unknown")),
            ("Evidence", NS.start_char, Literal("zero")),
            ("RelativeDeadline", NS.value, Literal(0, datatype=XSD.integer)),
            ("RelativeDeadline", NS.value, Literal("1.5", datatype=XSD.decimal)),
        ):
            with self.subTest(kind=kind):
                rdf = self.rdf()
                node = URIRef(self.nodes(kind)[0]["id"])
                rdf.set((node, predicate, bad))
                conforms, _, _ = validate(rdf, shacl_graph=process_rule_shapes(BASE))
                self.assertFalse(conforms)

    def test_incomplete_numeric_condition_fails_shacl(self):
        for missing in (
            "field",
            "unit",
            "lower_inclusive",
            "upper_inclusive",
            "both_bounds",
        ):
            with self.subTest(missing=missing):
                rdf = self.rdf()
                condition = URIRef(self.nodes("Condition")[0]["id"])
                fields = ("lower", "upper") if missing == "both_bounds" else (missing,)
                for field in fields:
                    rdf.remove((condition, NS[field], None))
                conforms, _, _ = validate(rdf, shacl_graph=process_rule_shapes(BASE))
                self.assertFalse(conforms)

    def test_nonnumeric_and_one_sided_numeric_conditions_pass_shacl(self):
        for numeric in (
            None,
            {**self.result["rules"][0]["conditions"][0]["numeric"], "upper": None},
        ):
            with self.subTest(numeric=numeric):
                result = copy.deepcopy(self.result)
                result["rules"][0]["conditions"][0]["numeric"] = numeric
                self.graph = process_rules_to_graph(result, BASE)
                conforms, _, report = validate(
                    self.rdf(), shacl_graph=process_rule_shapes(BASE)
                )
                self.assertTrue(conforms, report)

    def test_evidence_source_identity_must_match_linked_document(self):
        for field, bad_value in (
            ("source_id", "wrong-policy"),
            ("source_sha256", "a" * 64),
        ):
            with self.subTest(field=field):
                rdf = self.rdf()
                evidence = URIRef(self.nodes("Evidence")[0]["id"])
                rdf.set((evidence, NS[field], Literal(bad_value, datatype=XSD.string)))
                conforms, _, _ = validate(rdf, shacl_graph=process_rule_shapes(BASE))
                self.assertFalse(conforms)

    def test_evidence_span_cannot_extend_beyond_source_document(self):
        rdf = self.rdf()
        evidence = URIRef(self.nodes("Evidence")[0]["id"])
        # Move both offsets by one so quote length still matches the span;
        # this must fail specifically because the source boundary is exceeded.
        for field in ("start_char", "end_char"):
            value = rdf.value(evidence, NS[field]).toPython()
            rdf.set((evidence, NS[field], Literal(value + 1)))
        conforms, _, _ = validate(rdf, shacl_graph=process_rule_shapes(BASE))
        self.assertFalse(conforms)

    def test_evidence_quote_length_must_match_its_character_span(self):
        rdf = self.rdf()
        evidence = URIRef(self.nodes("Evidence")[0]["id"])
        quote = str(rdf.value(evidence, NS.quote))
        rdf.set((evidence, NS.quote, Literal(quote + "伪", datatype=XSD.string)))
        conforms, _, _ = validate(rdf, shacl_graph=process_rule_shapes(BASE))
        self.assertFalse(conforms)

    def test_reversed_or_empty_numeric_interval_fails_shacl(self):
        for value in ("600", "500"):
            with self.subTest(lower=value):
                rdf = self.rdf()
                condition = URIRef(self.nodes("Condition")[0]["id"])
                rdf.set((condition, NS["lower"], Literal(value, datatype=XSD.decimal)))
                conforms, _, _ = validate(rdf, shacl_graph=process_rule_shapes(BASE))
                self.assertFalse(conforms)


if __name__ == "__main__":
    unittest.main()
