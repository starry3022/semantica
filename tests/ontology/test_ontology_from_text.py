"""The ontology CLI exports grounded candidates and replays without an LLM."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest
from rdflib import Graph, OWL, RDF, RDFS, URIRef, XSD
from rdflib.compare import isomorphic


REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "examples" / "ontology_from_text.py"
BASE = "https://example.org/purchasing/"
TEXT = "版本：V1.3\n采购申请属于申请。\n采购申请需要合同。\n采购申请记录申请金额。\n"
SECRET = "test-only-private-api-key"


@pytest.fixture
def cli():
    assert SCRIPT.exists(), "the reusable ontology CLI has not been implemented"
    spec = importlib.util.spec_from_file_location("ontology_example_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def inputs(tmp_path):
    source = tmp_path / "input.txt"
    source.write_bytes(TEXT.encode("utf-8"))
    config = tmp_path / "private.json"
    config.write_text(
        json.dumps(
            {
                "provider": "openai",
                "model": "fixture-model",
                "api_key": SECRET,
                "base_url": "https://gateway.invalid/v1",
                "max_tokens": 4096,
            }
        ),
        encoding="utf-8",
    )
    return source, config


@pytest.fixture
def response():
    return {
        "name": "采购业务本体",
        "classes": [
            {
                "name": "Application",
                "label": "申请",
                "comment": "用于请求业务办理的申请类型。",
                "evidence_quote": "申请",
            },
            {
                "name": "PurchaseRequest",
                "label": "采购申请",
                "comment": "请求办理采购的申请类型。",
                "parent": "Application",
                "evidence_quote": "采购申请属于申请。",
            },
            {
                "name": "Contract",
                "label": "合同",
                "comment": "采购申请需要提供的合同类型。",
                "evidence_quote": "合同",
            },
        ],
        "properties": [
            {
                "name": "requiresContract",
                "label": "需要合同",
                "comment": "采购申请需要提供合同。",
                "type": "object",
                "domain": ["PurchaseRequest"],
                "range": ["Contract"],
                "evidence_quote": "采购申请需要合同。",
            },
            {
                "name": "applicationAmount",
                "label": "申请金额",
                "comment": "采购申请记录的申请金额。",
                "type": "data",
                "domain": ["PurchaseRequest"],
                "range": ["xsd:decimal"],
                "evidence_quote": "采购申请记录申请金额。",
            },
        ],
    }


def arguments(inputs, output, replay=None):
    source, config = inputs
    return [
        "--source",
        str(source),
        "--output",
        str(output),
        "--base-uri",
        BASE,
        "--name",
        "采购业务本体",
        *(["--replay", str(replay)] if replay else ["--config", str(config)]),
    ]


def generate(cli, inputs, output, response):
    provider = MagicMock()
    provider.generate_structured.return_value = copy.deepcopy(response)
    with patch(
        "semantica.ontology.llm_generator.create_provider", return_value=provider
    ):
        assert cli.main(arguments(inputs, output)) == 0
    assert provider.generate_structured.call_count == 1
    return provider


def test_generation_exports_grounded_rdf_and_separate_support_vocabulary(
    cli, inputs, tmp_path, response, capsys
):
    output = tmp_path / "artifacts"
    provider = generate(cli, inputs, output, response)
    ontology = json.loads((output / "ontology.json").read_text())
    assert "version" in ontology and ontology["version"] is None
    metadata = ontology["metadata"]
    assert metadata["source"] == "llm"
    assert metadata["model"] == "fixture-model"
    assert metadata["source_sha256"] == hashlib.sha256(TEXT.encode()).hexdigest()
    assert (
        metadata["prompt_sha256"]
        == hashlib.sha256((output / "prompt.txt").read_bytes()).hexdigest()
    )
    assert metadata["fact_status"] == "candidate"
    assert metadata["review_status"] == "unreviewed"
    assert (output / "source.txt").read_bytes() == TEXT.encode()
    assert (
        output / "prompt.txt"
    ).read_text() == provider.generate_structured.call_args.args[0]
    ttl = Graph().parse(output / "ontology.ttl", format="turtle")
    xml = Graph().parse(output / "ontology.owl", format="xml")
    assert isomorphic(ttl, xml)
    assert len(set(ttl.subjects(RDF.type, OWL.Class))) == 3
    assert (
        URIRef(BASE + "PurchaseRequest"),
        RDFS.subClassOf,
        URIRef(BASE + "Application"),
    ) in ttl
    assert (URIRef(BASE + "applicationAmount"), RDFS.range, XSD.decimal) in ttl
    assert str(ttl.value(URIRef(BASE + "PurchaseRequest"), RDFS.label)) == "采购申请"
    assert "采购申请属于申请。" in str(ttl.value(URIRef(BASE + "PurchaseRequest"), RDFS.comment))
    assert "unreviewed" in str(ttl.value(URIRef(BASE), RDFS.comment))
    assert not list(ttl.objects(None, OWL.versionInfo))
    assert not list(xml.objects(None, OWL.versionInfo))
    support = Graph().parse(output / "process-vocabulary.ttl", format="turtle")
    assert any(str(label) == "证据起始位置" for label in support.objects(None, RDFS.label))
    assert not (output / "instances.ttl").exists()
    validation = json.loads((output / "validation.json").read_text())
    assert validation["valid"] and validation["rdf_roundtrip_isomorphic"]
    summary = json.loads((output / "SUMMARY.json").read_text())
    assert summary["status"] == "candidate"
    assert summary["mode"] == "llm"
    captured = capsys.readouterr()
    assert SECRET not in captured.out + captured.err
    assert all(SECRET not in path.read_text() for path in output.iterdir())


def test_source_id_exports_replayable_evidence_context_without_changing_rdf(
    cli, inputs, tmp_path, response
):
    response["classes"][0]["evidence_quote"] = "采购申请属于申请。"
    original = tmp_path / "original"
    generate(cli, inputs, original, response)
    output = tmp_path / "linked"
    with patch("semantica.ontology.llm_generator.create_provider") as provider:
        assert (
            cli.main(
                arguments(inputs, output, replay=original / "ontology.json")
                + ["--source-id", "registered-policy"]
            )
            == 0
        )
    provider.assert_not_called()
    context_path = output / "ontology-evidence-context.json"
    context = json.loads(context_path.read_text())
    assert context["business_ontologies"][0]["uri"] == BASE
    terms = context["business_ontologies"][0]["terms"]
    assert len(terms) == 5
    assert {item["source_id"] for item in terms} == {"registered-policy"}
    request = next(item for item in terms if item["uri"] == BASE + "PurchaseRequest")
    assert request["parents"] == [BASE + "Application"]
    prop = next(item for item in terms if item["uri"] == BASE + "requiresContract")
    assert prop["domain"] == [BASE + "PurchaseRequest"]
    assert prop["range"] == [BASE + "Contract"]
    assert isomorphic(
        Graph().parse(original / "ontology.ttl"), Graph().parse(output / "ontology.ttl")
    )
    summary = json.loads((output / "SUMMARY.json").read_text())
    assert (
        summary["artifacts"][context_path.name]
        == hashlib.sha256(context_path.read_bytes()).hexdigest()
    )


def test_replay_calls_no_provider_and_rechecks_rdf(cli, inputs, tmp_path, response):
    generated = tmp_path / "generated"
    generate(cli, inputs, generated, response)
    output = tmp_path / "replayed"
    with patch(
        "semantica.ontology.llm_generator.create_provider",
        side_effect=AssertionError("replay must not create a provider"),
    ) as create:
        assert cli.main(arguments(inputs, output, generated / "ontology.json")) == 0
    create.assert_not_called()
    assert json.loads((output / "SUMMARY.json").read_text())["mode"] == "offline_replay"
    assert isomorphic(
        Graph().parse(output / "ontology.ttl"),
        Graph().parse(generated / "ontology.ttl"),
    )


def test_real_cli_replays_an_export(cli, inputs, tmp_path, response):
    generated = tmp_path / "generated"
    generate(cli, inputs, generated, response)
    output = tmp_path / "cli-replay"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            *arguments(inputs, output, generated / "ontology.json"),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert (output / "SUMMARY.json").exists()


def test_replay_rejects_changed_source_without_export(
    cli, inputs, tmp_path, response, capsys
):
    generated = tmp_path / "generated"
    generate(cli, inputs, generated, response)
    inputs[0].write_text(TEXT + "新条款。", encoding="utf-8")
    output = tmp_path / "rejected"
    assert cli.main(arguments(inputs, output, generated / "ontology.json")) == 2
    assert "Source hash" in capsys.readouterr().err
    assert not output.exists()


@pytest.mark.parametrize(
    "fault", ["empty", "ungrounded", "unknown_range", "fixed_term"]
)
def test_invalid_model_output_is_not_published(cli, inputs, tmp_path, response, fault):
    if fault == "empty":
        response = {}
    elif fault == "ungrounded":
        response["classes"][0]["evidence_quote"] = "不存在的引文"
    elif fault == "unknown_range":
        response["properties"][0]["range"] = ["InventedType"]
    else:
        response["classes"][0]["name"] = "Evidence"
    provider = MagicMock()
    provider.generate_structured.return_value = response
    output = tmp_path / "rejected"
    with patch(
        "semantica.ontology.llm_generator.create_provider", return_value=provider
    ):
        assert cli.main(arguments(inputs, output)) == 2
    assert not output.exists()


def test_existing_output_is_preserved_before_generation(cli, inputs, tmp_path):
    output = tmp_path / "existing"
    output.mkdir()
    (output / "user-file.txt").write_text("preserve me")
    with patch("semantica.ontology.llm_generator.create_provider") as create:
        assert cli.main(arguments(inputs, output)) == 2
    create.assert_not_called()
    assert (output / "user-file.txt").read_text() == "preserve me"
    assert len(list(output.iterdir())) == 1


def test_failure_redacts_provider_error_and_preserves_empty_output(
    cli, inputs, tmp_path, capsys
):
    output = tmp_path / "empty"
    output.mkdir()
    provider = MagicMock()
    provider.generate_structured.side_effect = RuntimeError("Authorization: " + SECRET)
    with patch(
        "semantica.ontology.llm_generator.create_provider", return_value=provider
    ):
        assert cli.main(arguments(inputs, output)) == 2
    captured = capsys.readouterr()
    assert SECRET not in captured.out + captured.err
    assert list(output.iterdir()) == []


def test_replay_does_not_preserve_unsupported_review_or_secret_metadata(
    cli, inputs, tmp_path, response
):
    generated = tmp_path / "generated"
    generate(cli, inputs, generated, response)
    path = generated / "ontology.json"
    ontology = json.loads(path.read_text())
    ontology["metadata"].update(review_status="approved", api_key=SECRET)
    path.write_text(json.dumps(ontology, ensure_ascii=False), encoding="utf-8")
    output = tmp_path / "replayed"
    assert cli.main(arguments(inputs, output, path)) == 0
    saved = json.loads((output / "ontology.json").read_text())
    assert saved["metadata"]["review_status"] == "unreviewed"
    assert all(SECRET not in path.read_text() for path in output.iterdir())


def test_replay_rejects_tampered_prompt(cli, inputs, tmp_path, response, capsys):
    generated = tmp_path / "generated"
    generate(cli, inputs, generated, response)
    (generated / "prompt.txt").write_text("a different prompt", encoding="utf-8")
    output = tmp_path / "rejected"
    assert cli.main(arguments(inputs, output, generated / "ontology.json")) == 2
    assert "Prompt hash" in capsys.readouterr().err
    assert not output.exists()


def test_standalone_replay_reconstructs_only_the_matching_prompt(
    cli, inputs, tmp_path, response
):
    generated = tmp_path / "generated"
    generate(cli, inputs, generated, response)
    replay = tmp_path / "standalone-ontology.json"
    replay.write_bytes((generated / "ontology.json").read_bytes())
    output = tmp_path / "replayed"
    assert cli.main(arguments(inputs, output, replay)) == 0
    assert (output / "prompt.txt").read_bytes() == (
        generated / "prompt.txt"
    ).read_bytes()


def test_replay_revalidates_edited_terms(cli, inputs, tmp_path, response):
    generated = tmp_path / "generated"
    generate(cli, inputs, generated, response)
    replay = generated / "ontology.json"
    ontology = json.loads(replay.read_text())
    ontology["classes"][0]["evidence_quote"] = "not present in the source"
    replay.write_text(json.dumps(ontology), encoding="utf-8")
    output = tmp_path / "rejected"
    assert cli.main(arguments(inputs, output, replay)) == 2
    assert not output.exists()


def test_existing_empty_output_is_populated_on_success(cli, inputs, tmp_path, response):
    output = tmp_path / "empty"
    output.mkdir()
    generate(cli, inputs, output, response)
    assert (output / "SUMMARY.json").exists()


def test_output_symlink_is_not_followed(cli, inputs, tmp_path):
    actual = tmp_path / "user-directory"
    actual.mkdir()
    output = tmp_path / "output-link"
    output.symlink_to(actual, target_is_directory=True)
    with patch("semantica.ontology.llm_generator.create_provider") as create:
        assert cli.main(arguments(inputs, output)) == 2
    create.assert_not_called()
    assert output.is_symlink() and list(actual.iterdir()) == []


def test_config_and_replay_are_mutually_exclusive(cli, inputs, tmp_path):
    with patch("semantica.ontology.llm_generator.create_provider") as create:
        with pytest.raises(SystemExit) as error:
            cli.main(
                arguments(inputs, tmp_path / "output") + ["--replay", "saved.json"]
            )
    assert error.value.code == 2
    create.assert_not_called()


def test_source_line_endings_are_preserved_in_artifacts_and_hash(
    cli, inputs, tmp_path, response
):
    raw = TEXT.replace("\n", "\r\n").encode("utf-8")
    inputs[0].write_bytes(raw)
    output = tmp_path / "crlf-output"
    generate(cli, inputs, output, response)
    assert (output / "source.txt").read_bytes() == raw
    assert (
        json.loads((output / "ontology.json").read_text())["metadata"]["source_sha256"]
        == hashlib.sha256(raw).hexdigest()
    )


def test_max_tokens_overrides_only_this_generation(cli, inputs, tmp_path, response):
    original_config = inputs[1].read_bytes()
    provider = MagicMock()
    provider.generate_structured.return_value = response
    with patch(
        "semantica.ontology.llm_generator.create_provider", return_value=provider
    ):
        assert (
            cli.main(
                arguments(inputs, tmp_path / "larger-output")
                + ["--max-tokens", "16384"]
            )
            == 0
        )
    assert provider.generate_structured.call_args.kwargs["max_tokens"] == 16384
    assert inputs[1].read_bytes() == original_config
