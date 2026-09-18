"""The example exports the native technical report and replays without a model."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from rdflib import Graph, OWL, RDF, URIRef


SCRIPT = Path(__file__).resolve().parents[2] / "examples/validate_candidate_facts.py"
NS = "https://semantica.dev/ns#"
FACTS = {
    "entities": [{"id": "requirement", "type": "RequiredDocument"}],
    "relationships": [],
}
PROPOSAL = {
    "name": "材料要求",
    "classes": [
        {
            "name": "RequiredDocument",
            "uri": NS + "RequiredDocument",
            "label": "材料要求",
            "comment": "待提供材料的要求，不是一份实际合同。",
            "subClassOf": None,
        }
    ],
    "properties": [
        {
            "name": "text",
            "uri": NS + "text",
            "type": "data",
            "label": "名称",
            "comment": "候选项名称。",
            "domain": [NS + "RequiredDocument"],
            "range": ["http://www.w3.org/2001/XMLSchema#string"],
        },
        {
            "name": "confidence",
            "uri": NS + "confidence",
            "type": "data",
            "label": "候选评分",
            "comment": "导出器提供的候选评分，不代表业务审核。",
            "domain": [NS + "RequiredDocument"],
            "range": ["http://www.w3.org/2001/XMLSchema#decimal"],
        },
    ],
}


def cli():
    spec = importlib.util.spec_from_file_location("candidate_cli", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_native_artifacts_and_offline_replay(tmp_path, capsys):
    facts_file = tmp_path / "facts.json"
    facts_file.write_text(json.dumps(FACTS))
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"provider": "openai", "model": "test", "api_key": "test-secret"})
    )
    entry = cli()
    out = tmp_path / "out"
    with patch("semantica.ontology.llm_generator.create_provider") as factory:
        factory.return_value.generate_structured.return_value = deepcopy(PROPOSAL)
        assert (
            entry.main(
                [
                    "--facts",
                    str(facts_file),
                    "--config",
                    str(config),
                    "--output",
                    str(out),
                ]
            )
            == 0
        )
        factory.return_value.generate_structured.assert_called_once()
    assert json.loads((out / "facts.json").read_text()) == FACTS
    base = Graph().parse(out / "base.ttl")
    draft = Graph().parse(out / "ontology.ttl")
    assert (
        URIRef(NS + "requirement"),
        RDF.type,
        URIRef(NS + "RequiredDocument"),
    ) in base
    assert (URIRef(NS + "RequiredDocument"), RDF.type, OWL.Class) in draft
    report = json.loads((out / "issues.json").read_text())
    assert report["conforms"] is True
    assert "coverage" in report and "technical_issues" in report
    replay = tmp_path / "replay"
    with patch(
        "semantica.ontology.llm_generator.create_provider",
        side_effect=AssertionError("offline"),
    ):
        assert (
            entry.main(
                [
                    "--facts",
                    str(facts_file),
                    "--replay",
                    str(out / "ontology.json"),
                    "--output",
                    str(replay),
                ]
            )
            == 0
        )
    assert json.loads((replay / "ontology.json").read_text()) == json.loads(
        (out / "ontology.json").read_text()
    )
    assert "test-secret" not in capsys.readouterr().out
    assert all("test-secret" not in path.read_text() for path in out.iterdir())


def test_output_guard_and_provider_error_do_not_publish_or_expose_secret(
    tmp_path, capsys
):
    facts = tmp_path / "facts.json"
    facts.write_text(json.dumps(FACTS))
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"provider": "openai", "model": "test", "api_key": "test-secret"})
    )
    out = tmp_path / "out"
    entry = cli()
    with patch("semantica.ontology.llm_generator.create_provider") as factory:
        factory.return_value.generate_structured.side_effect = RuntimeError(
            "test-secret"
        )
        assert (
            entry.main(
                ["--facts", str(facts), "--config", str(config), "--output", str(out)]
            )
            == 2
        )
    assert not out.exists()
    out.mkdir()
    (out / "keep").write_text("user data")
    with patch("semantica.ontology.llm_generator.create_provider") as factory:
        assert (
            entry.main(
                ["--facts", str(facts), "--config", str(config), "--output", str(out)]
            )
            == 2
        )
        factory.assert_not_called()
    assert (out / "keep").read_text() == "user data"
    captured = capsys.readouterr()
    assert "test-secret" not in captured.out + captured.err


@pytest.mark.parametrize(
    "key,value",
    [
        ("provider", ["bad"]),
        ("model", 123),
        ("prompt_version", "wrong-version"),
        ("prompt_sha256", "wrong-prompt"),
        ("input_rdf_sha256", "wrong-rdf"),
    ],
)
def test_replay_rejects_invalid_generation_provenance(tmp_path, key, value):
    facts = tmp_path / "facts.json"
    facts.write_text(json.dumps(FACTS))
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"provider": "openai", "model": "test"}))
    out = tmp_path / "out"
    entry = cli()
    with patch(
        "semantica.ontology.llm_generator.create_provider", autospec=True
    ) as factory:
        factory.return_value.generate_structured.return_value = deepcopy(PROPOSAL)
        assert (
            entry.main(
                ["--facts", str(facts), "--config", str(config), "--output", str(out)]
            )
            == 0
        )
    saved = json.loads((out / "ontology.json").read_text())
    saved["metadata"][key] = value
    (out / "ontology.json").write_text(json.dumps(saved))
    with patch(
        "semantica.ontology.llm_generator.create_provider",
        side_effect=AssertionError("offline"),
    ):
        assert (
            entry.main(
                [
                    "--facts",
                    str(facts),
                    "--replay",
                    str(out / "ontology.json"),
                    "--output",
                    str(tmp_path / "replay"),
                ]
            )
            == 2
        )
    assert not (tmp_path / "replay").exists()


@pytest.mark.parametrize("key", ["review_feedback", "version", "name", "base_uri"])
def test_private_config_cannot_hide_prompt_or_schema_options(tmp_path, key):
    facts = tmp_path / "facts.json"
    facts.write_text(json.dumps(FACTS))
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"provider": "openai", "model": "test", key: "hidden"})
    )
    with patch(
        "semantica.ontology.llm_generator.create_provider", autospec=True
    ) as factory:
        assert (
            cli().main(
                [
                    "--facts",
                    str(facts),
                    "--config",
                    str(config),
                    "--output",
                    str(tmp_path / "out"),
                ]
            )
            == 2
        )
        factory.assert_not_called()
    assert not (tmp_path / "out").exists()
