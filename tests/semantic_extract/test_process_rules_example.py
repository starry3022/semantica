"""Exercise the offline CLI against real source/evidence and real RDF exports."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from semantica.semantic_extract.process_extractor import finalize_process_rules


class ProcessRulesExampleTests(unittest.TestCase):
    def setUp(self):
        self.repo = Path(__file__).resolve().parents[2]
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.text = "检修完成后2个工作日内，检修员必须提交验收单。"
        self.source = self.root / "source.txt"
        self.source.write_text(self.text, encoding="utf-8")
        response = {
            "rules": [
                {
                    "id": "R1",
                    "source_clause_id": "C001",
                    "activity": "设备检修",
                    "action": "提交验收单",
                    "modality": "obligation",
                    "actors": ["检修员"],
                    "conditions": [],
                    "condition_logic": "all",
                    "approvals": None,
                    "required_documents": ["验收单"],
                    "supporting_clause_ids": [],
                    "deadline": {
                        "value": 2,
                        "unit": "working_day",
                        "anchor": "检修完成",
                        "relation": "after",
                        "text": "检修完成后2个工作日内",
                    },
                    "evidence": [{"clause_id": "C001", "quote": self.text}],
                    "confidence": 0.8,
                }
            ],
            "clause_assessments": [
                {"clause_id": "C001", "disposition": "rule", "reason": "提交要求"}
            ],
        }
        self.extraction = finalize_process_rules(
            self.text, "maintenance-demo", response
        )
        self.replay = self.root / "extraction.json"
        self.replay.write_text(self.extraction.model_dump_json(), encoding="utf-8")

    def invoke(self, output):
        return subprocess.run(
            [
                sys.executable,
                str(self.repo / "examples/process_rules_from_text.py"),
                "--source-file",
                str(self.source),
                "--output-dir",
                str(output),
                "--replay",
                str(self.replay),
            ],
            cwd=self.repo,
            capture_output=True,
            text=True,
        )

    def test_offline_replay_exports_rules_rdf_ontology_and_real_validation(self):
        output = self.root / "artifacts"
        run = self.invoke(output)
        self.assertEqual(run.returncode, 0, run.stderr + run.stdout)
        summary = json.loads((output / "SUMMARY.json").read_text())
        self.assertEqual(summary["rule_count"], 1)
        self.assertEqual(summary["mode"], "offline_replay")
        self.assertEqual(summary["review_status"], "unreviewed")
        validation = json.loads((output / "validation.json").read_text())
        self.assertTrue(validation["conforms"])
        self.assertGreater(validation["property_shapes"], 0)
        self.assertGreater(validation["matching_focus_nodes"], 0)
        self.assertIn("working_day", (output / "instances.ttl").read_text())
        self.assertEqual((output / "source.txt").read_bytes(), self.source.read_bytes())

    def test_replay_rejects_source_changed_since_extraction(self):
        self.source.write_text(self.text.replace("2", "7"), encoding="utf-8")
        run = self.invoke(self.root / "changed")
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("Source hash differs", run.stderr)

    def test_replay_recomputes_evidence_offsets_instead_of_trusting_json(self):
        data = self.extraction.model_dump(mode="json")
        data["evidence_spans"][0]["start_char"] = 9
        self.replay.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        output = self.root / "realigned"
        run = self.invoke(output)
        self.assertEqual(run.returncode, 0, run.stderr + run.stdout)
        saved = json.loads((output / "process-rules.json").read_text())
        self.assertEqual(saved["evidence_spans"][0]["start_char"], 0)

    def test_incomplete_coverage_is_exported_for_review_but_not_success(self):
        data = self.extraction.model_dump(mode="json")
        data["coverage"]["assessments"] = []
        self.replay.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        output = self.root / "incomplete"
        run = self.invoke(output)
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("coverage is incomplete", run.stderr)
        summary = json.loads((output / "SUMMARY.json").read_text())
        self.assertEqual(summary["status"], "incomplete")
        self.assertFalse(summary["coverage"]["complete"])

    def test_zero_rules_cannot_be_reported_as_successful_knowledge_extraction(self):
        data = self.extraction.model_dump(mode="json")
        data["rules"] = []
        data["evidence_spans"] = []
        data["coverage"]["assessments"][0]["disposition"] = "non_normative"
        self.replay.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        run = self.invoke(self.root / "empty")
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("No candidate process rules", run.stderr)


if __name__ == "__main__":
    unittest.main()
