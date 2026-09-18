"""RDF bundles carry validated node/concept correspondence through replay."""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from semantica.semantic_extract.process_graph import export_process_rdf

BASE = "https://example.org/business/"
PROCESS = "https://example.org/process/"
TEXT = "付款申请应提供合法有效的合同。\n"
SCRIPT = Path(__file__).resolve().parents[2] / "examples/ontology_from_rdf.py"


@pytest.fixture
def bundle(tmp_path):
    graph = {
        "metadata": {"base_uri": PROCESS},
        "nodes": [
            {
                "id": PROCESS + "document",
                "type": "RequiredDocument",
                "label": "合法有效的合同",
                "properties": {
                    "name": "合法有效的合同",
                    "fact_status": "candidate",
                    "review_status": "unreviewed",
                },
            },
        ],
        "edges": [],
    }
    proposal = {
        "name": "材料本体",
        "classes": [
            {
                "name": "Contract",
                "uri": BASE + "Contract",
                "label": "合同",
                "comment": "付款申请要求提供的合同类型。",
                "subClassOf": None,
                "evidence_lines": [1, 1],
                "evidence_nodes": [PROCESS + "document"],
            }
        ],
        "properties": [],
        "concept_references": [
            {
                "node_id": PROCESS + "document",
                "class_uri": BASE + "Contract",
                "relation": "references_concept",
                "rationale": "材料要求引用合同概念。",
            }
        ],
        "unmapped_nodes": [],
    }
    (tmp_path / "source.txt").write_text(TEXT)
    (tmp_path / "input.ttl").write_text(export_process_rdf(graph))
    (tmp_path / "graph.json").write_text(json.dumps(graph))
    (tmp_path / "config.json").write_text(
        json.dumps(
            {
                "provider": "openai",
                "model": "test-model",
                "api_key": "private-test-secret",
            }
        )
    )
    return tmp_path, proposal, graph


def cli():
    assert SCRIPT.exists(), "RDF ontology export entry point is missing"
    spec = importlib.util.spec_from_file_location("rdf_cli", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def arguments(root, output, *, replay=None):
    return [
        "--rdf",
        str(root / "input.ttl"),
        "--graph",
        str(root / "graph.json"),
        "--source",
        str(root / "source.txt"),
        "--source-id",
        "policy",
        "--base-uri",
        BASE,
        "--process-base-uri",
        PROCESS,
        "--output",
        str(output),
        *(
            ["--replay", str(replay)]
            if replay
            else ["--config", str(root / "config.json")]
        ),
    ]


def test_generation_and_offline_replay_preserve_explicit_mappings(bundle, capsys):
    root, proposal, _ = bundle
    entry = cli()
    with patch("semantica.ontology.llm_generator.create_provider") as factory:
        factory.return_value.generate_structured.return_value = deepcopy(proposal)
        assert entry.main(arguments(root, root / "out")) == 0
        assert factory.return_value.generate_structured.call_count == 1
    saved = json.loads((root / "out/ontology.json").read_text())
    context = json.loads((root / "out/ontology-evidence-context.json").read_text())
    reference = context["business_ontologies"][0]["concept_references"][0]
    assert reference["node_id"] == PROCESS + "document"
    assert reference["class_uri"] == BASE + "Contract"
    assert reference["input_rdf_sha256"] == saved["metadata"]["input_rdf_sha256"]
    assert reference["node_label"] == "合法有效的合同"
    assert (
        saved["metadata"]["source_sha256"] == hashlib.sha256(TEXT.encode()).hexdigest()
    )
    assert saved["metadata"]["input_kind"] == "rdf"
    with patch(
        "semantica.ontology.llm_generator.create_provider",
        side_effect=AssertionError("replay must be offline"),
    ):
        assert (
            entry.main(
                arguments(root, root / "replay", replay=root / "out/ontology.json")
            )
            == 0
        )
    assert (
        json.loads((root / "replay/ontology-evidence-context.json").read_text())
        == context
    )
    captured = capsys.readouterr()
    assert "private-test-secret" not in captured.out + captured.err
    assert all(
        "private-test-secret" not in path.read_text()
        for path in (root / "out").iterdir()
    )


@pytest.mark.parametrize("changed", ["rdf", "graph", "source", "prompt", "mapping"])
def test_replay_rejects_changed_inputs_without_publishing(bundle, changed):
    root, proposal, graph = bundle
    entry = cli()
    with patch("semantica.ontology.llm_generator.create_provider") as factory:
        factory.return_value.generate_structured.return_value = deepcopy(proposal)
        assert entry.main(arguments(root, root / "out")) == 0
    if changed == "rdf":
        (root / "input.ttl").write_text(
            (root / "input.ttl").read_text().replace("合法有效", "另一份")
        )
    elif changed == "graph":
        graph["nodes"][0]["label"] = "另一份合同"
        (root / "graph.json").write_text(json.dumps(graph))
    elif changed == "source":
        (root / "source.txt").write_text(TEXT + "修改")
    elif changed == "prompt":
        (root / "out/prompt.txt").write_text("修改")
    else:
        value = json.loads((root / "out/ontology.json").read_text())
        value["concept_references"][0]["node_id"] = PROCESS + "missing"
        (root / "out/ontology.json").write_text(json.dumps(value))
    with patch(
        "semantica.ontology.llm_generator.create_provider",
        side_effect=AssertionError("offline"),
    ):
        assert (
            entry.main(
                arguments(root, root / "replay", replay=root / "out/ontology.json")
            )
            == 2
        )
    assert not (root / "replay").exists()


def test_graph_rdf_mismatch_fails_before_llm(bundle):
    root, _, graph = bundle
    graph["nodes"][0]["properties"]["name"] = "不同要求"
    (root / "graph.json").write_text(json.dumps(graph))
    with patch("semantica.ontology.llm_generator.create_provider") as factory:
        assert cli().main(arguments(root, root / "out")) == 2
        factory.assert_not_called()


def test_support_namespace_defaults_to_the_input_graph(bundle):
    root, proposal, _ = bundle
    args = arguments(root, root / "out")
    position = args.index("--process-base-uri")
    del args[position : position + 2]
    with patch("semantica.ontology.llm_generator.create_provider") as factory:
        factory.return_value.generate_structured.return_value = proposal
        assert cli().main(args) == 0
    assert (
        PROCESS + "Ontology"
        in json.loads((root / "out/ontology-evidence-context.json").read_text())[
            "support_ontologies"
        ]
    )


@pytest.mark.parametrize(
    "namespace", ["https://example.org/wrong/", PROCESS.rstrip("/") + "#"]
)
def test_conflicting_support_namespace_fails_before_llm(bundle, namespace):
    root, _, _ = bundle
    args = arguments(root, root / "out")
    args[args.index("--process-base-uri") + 1] = namespace
    with patch("semantica.ontology.llm_generator.create_provider") as factory:
        assert cli().main(args) == 2
        factory.assert_not_called()
