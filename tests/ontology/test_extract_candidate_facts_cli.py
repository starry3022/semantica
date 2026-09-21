"""Portable source-to-facts-to-schema artifacts use one native vocabulary."""

from argparse import Namespace
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

import pytest
from rdflib import Graph, OWL, RDF


@pytest.fixture
def cli():
    path = Path(__file__).parents[2] / "examples" / "extract_candidate_facts.py"
    spec = importlib.util.spec_from_file_location("extract_candidate_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def extraction():
    text = "财务负责人😀\r\n审核付款申请。"
    source_hash = hashlib.sha256(text.encode()).hexdigest()
    evidence = {
        "quote": text,
        "start_char": 0,
        "end_char": len(text),
        "source_id": "policy",
        "source_sha256": source_hash,
    }
    metadata = {
        "fact_status": "candidate",
        "review_status": "unreviewed",
        "evidence": [evidence],
    }
    return text, {
        "facts": {
            "entities": [
                {
                    "id": "urn:example:officer",
                    "text": "财务负责人",
                    "type": "FinanceOfficer",
                    "metadata": metadata,
                },
                {
                    "id": "urn:example:request",
                    "text": "付款申请",
                    "type": "PaymentRequest",
                    "metadata": metadata,
                },
            ],
            "relationships": [
                {
                    "id": "urn:example:review",
                    "source_id": "urn:example:officer",
                    "target_id": "urn:example:request",
                    "type": "reviews",
                    "metadata": {
                        **metadata,
                        "modality": "obligation",
                        "condition": "source condition",
                    },
                }
            ],
        },
        "extraction": {
            "provider": "openai",
            "model": "test",
            "source_sha256": source_hash,
        },
        "prompts": {"entities": "entity prompt", "relationships": "relation prompt"},
        "issues": [],
    }


@pytest.fixture
def generation(cli, extraction, monkeypatch):
    text, extracted = extraction
    calls = []

    def extract(value, *, source_id, **config):
        assert value == text and source_id == "policy"
        assert config["api_key"] == "private-never-export"
        assert config["review_coverage"] is True
        calls.append("extraction")
        return deepcopy(extracted)

    def replay(value, records, *, source_id):
        assert value == text and source_id == "policy"
        assert records == extracted["extraction"]
        calls.append("replay")
        return deepcopy(extracted)

    def proposal(prompt, **options):
        # Only replace the provider boundary: normalization, export and SHACL run.
        payload = json.loads(prompt.split("INPUT:\n", 1)[1])
        vocabulary = payload["observed_vocabulary"]
        calls.append("ontology")
        return {
            "classes": [
                {
                    "name": iri.rsplit("#", 1)[-1],
                    "uri": iri,
                    "label": "候选类型",
                    "comment": "候选领域类别",
                    "subClassOf": None,
                }
                for iri in vocabulary["classes"]
            ],
            "properties": [
                {
                    "name": iri.rsplit("#", 1)[-1],
                    "uri": iri,
                    "label": "候选属性",
                    "comment": "候选领域属性",
                    "type": prop["type"],
                    "domain": prop["supported_domains"][:1],
                    "range": prop["supported_ranges"][:1],
                }
                for iri, prop in vocabulary["properties"].items()
            ],
        }

    from unittest.mock import Mock

    provider = Mock()
    provider.is_available.return_value = True
    provider.generate_structured.side_effect = proposal
    monkeypatch.setattr(cli, "extract_candidate_facts", extract)
    monkeypatch.setattr(cli, "replay_candidate_facts", replay)
    monkeypatch.setattr(
        "semantica.ontology.llm_generator.create_provider", lambda *a, **kw: provider
    )
    return calls


def args_for(tmp_path, text):
    source = tmp_path / "input.txt"
    source.write_bytes(text.encode())
    config = tmp_path / "private.json"
    config.write_text(
        json.dumps(
            {"provider": "openai", "model": "test", "api_key": "private-never-export"}
        )
    )
    return Namespace(
        source=source,
        source_id="policy",
        title="采购制度",
        version=None,
        config=config,
        replay=None,
        output=tmp_path / "output",
        name="CandidateOntology",
        base_uri="https://example.test/draft/",
    )


def test_complete_bundle_and_relocation_replay(cli, extraction, generation, tmp_path):
    text, expected = extraction
    args = args_for(tmp_path, text)
    summary = cli.run(args)
    assert generation == ["extraction", "ontology"]
    assert summary["fact_status"] == "candidate"
    assert summary["review_status"] == "unreviewed"
    assert (args.output / "source.txt").read_bytes() == text.encode()
    assert json.loads((args.output / "facts.json").read_text()) == expected["facts"]
    rdf = Graph().parse(args.output / "base.ttl", format="turtle")
    owl = Graph().parse(args.output / "ontology.ttl", format="turtle")
    assert summary["format_version"] == "candidate-facts-bundle-v2"
    assert summary["validation_scope"] == "business_projection_schema"
    assert summary["preservation_conforms"] is True
    from semantica.ontology.candidate_statements import prepare_candidate_statements

    projection = prepare_candidate_statements(expected["facts"]).projection.graph
    assert set(projection.objects(None, RDF.type)) == set(
        owl.subjects(RDF.type, OWL.Class)
    )
    assert len(list(rdf.subjects(RDF.type, RDF.Statement))) == 1
    preserved = json.loads((args.output / "preservation.json").read_text())
    assert preserved["conforms"] is True
    assert preserved["scope"] == "source_derived_preservation"
    manifest = json.loads((args.output / "source-manifest.json").read_text())
    assert manifest["sources"][0]["path"] == "source.txt"
    assert manifest["sources"][0]["version"] is None
    for name, digest in summary["files"].items():
        content = (args.output / name).read_bytes()
        assert hashlib.sha256(content).hexdigest() == digest
        assert b"private-never-export" not in content
        assert str(tmp_path).encode() not in content
    moved = tmp_path / "another-computer" / "bundle"
    shutil.copytree(args.output, moved)
    shutil.rmtree(args.output)
    args.source.unlink()
    args.config.unlink()
    replay_args = Namespace(
        replay=moved,
        output=tmp_path / "replayed",
        source=None,
        source_id=None,
        title=None,
        version=None,
        name=None,
        base_uri=None,
        config=None,
    )
    replayed = cli.run(replay_args)
    assert generation == ["extraction", "ontology", "replay"]
    assert replayed["mode"] == "offline_replay"
    for name in ("facts.json", "base.ttl", "candidate-graph.json", "source.txt"):
        assert (replay_args.output / name).read_bytes() == (moved / name).read_bytes()


def test_real_v1_fixture_replays_without_a_provider(cli, tmp_path, monkeypatch):
    fixture = Path(__file__).parents[1] / "fixtures" / "candidate_bundle_v1"

    def no_provider(*args, **kwargs):
        raise AssertionError("Offline replay attempted a provider call")

    monkeypatch.setattr(cli, "extract_candidate_facts", no_provider)
    monkeypatch.setattr(cli, "OntologyGenerator", no_provider)
    args = Namespace(replay=fixture, output=tmp_path / "v1-replay")
    summary = cli.run(args)
    assert summary["format_version"] == "candidate-facts-bundle-v1"
    assert summary["mode"] == "offline_replay"
    for name in (
        "facts.json",
        "extraction.json",
        "base.ttl",
        "candidate-graph.json",
        "entity-prompt.txt",
        "relationship-prompt.txt",
        "ontology-prompt.txt",
        "ontology.json",
    ):
        assert (args.output / name).read_bytes() == (fixture / name).read_bytes()


def test_replay_rejects_changed_qualifiers_with_updated_manifest(
    cli, extraction, generation, tmp_path
):
    args = args_for(tmp_path, extraction[0])
    cli.run(args)
    path = args.output / "facts.json"
    facts = json.loads(path.read_text())
    facts["relationships"][0]["metadata"]["condition"] = "different condition"
    path.write_text(json.dumps(facts))
    summary_path = args.output / "SUMMARY.json"
    summary = json.loads(summary_path.read_text())
    summary["files"]["facts.json"] = hashlib.sha256(path.read_bytes()).hexdigest()
    summary_path.write_text(json.dumps(summary))
    with pytest.raises(ValueError, match="facts"):
        cli.run(Namespace(replay=args.output, output=tmp_path / "replay"))


def test_nonempty_output_rejected_before_model_call(
    cli, extraction, generation, tmp_path
):
    args = args_for(tmp_path, extraction[0])
    args.output.mkdir()
    (args.output / "keep.txt").write_text("user data")
    with pytest.raises(ValueError, match="empty"):
        cli.run(args)
    assert generation == []
    assert (args.output / "keep.txt").read_text() == "user data"


def test_ontology_failure_does_not_publish_partial_output(
    cli, extraction, generation, monkeypatch, tmp_path
):
    args = args_for(tmp_path, extraction[0])

    def fail(*a, **kw):
        raise RuntimeError("private-never-export")

    monkeypatch.setattr(cli.OntologyGenerator, "generate_ontology", fail)
    assert (
        cli.main(
            [
                "--source",
                str(args.source),
                "--source-id",
                "policy",
                "--config",
                str(args.config),
                "--output",
                str(args.output),
            ]
        )
        == 2
    )
    assert not args.output.exists()


def test_invalid_config_rejected_before_extraction(
    cli, extraction, generation, tmp_path
):
    args = args_for(tmp_path, extraction[0])
    args.config.write_text(
        json.dumps({"provider": "openai", "model": "test", "review_feedback": "secret"})
    )
    with pytest.raises(ValueError, match="configuration"):
        cli.run(args)
    assert generation == []


def test_replay_rejects_changed_source_without_model_call(
    cli, extraction, generation, tmp_path
):
    args = args_for(tmp_path, extraction[0])
    cli.run(args)
    (args.output / "source.txt").write_text("changed")
    args.replay = args.output
    args.output = tmp_path / "replayed"
    args.source = (
        args.source_id
    ) = args.title = args.version = args.name = args.base_uri = args.config = None
    with pytest.raises(ValueError):
        cli.run(args)
    assert generation == ["extraction", "ontology"]
    assert not args.output.exists()


@pytest.mark.parametrize(
    "field,value", [("sha256", "0" * 64), ("source_id", "another-policy")]
)
def test_replay_rejects_inconsistent_summary_identity(
    cli, extraction, generation, tmp_path, field, value
):
    args = args_for(tmp_path, extraction[0])
    cli.run(args)
    summary_path = args.output / "SUMMARY.json"
    summary = json.loads(summary_path.read_text())
    summary["source"][field] = value
    summary_path.write_text(json.dumps(summary))
    args.replay = args.output
    args.output = tmp_path / "replayed"
    args.source = (
        args.source_id
    ) = args.title = args.version = args.name = args.base_uri = args.config = None
    with pytest.raises(ValueError, match="source identity"):
        cli.run(args)
    assert generation == ["extraction", "ontology"]
    assert not args.output.exists()


@pytest.mark.parametrize("staged", [False, True])
def test_existing_bundle_review_exports_audit_and_replays_offline(
    cli, extraction, generation, monkeypatch, tmp_path, staged
):
    args = args_for(tmp_path, extraction[0])
    cli.run(args)
    reviewed = deepcopy(extraction[1])
    reviewed["extraction"]["coverage_review"] = {
        "prompt_version": "candidate-semantic-coverage-v1", "provider": "openai", "model": "test",
        "input_sha256": "recorded-input", "prompt_sha256": "recorded-prompt",
        "response": {"entity_reviews": [{"status": "linked"}] * 2,
                     "clause_reviews": [{"status": "covered"}], "relationships": [], "relationship_reviews": []},
    }
    reviewed["prompts"]["coverage_review"] = "recorded review prompt"
    if staged:
        record = reviewed["extraction"]["coverage_review"]
        record["prompt_version"] = "candidate-semantic-coverage-staged-v1"
        audit = record.pop("response")
        record["stages"] = [
            {"name": name, "prompt_sha256": "recorded", "generation_options": {}, "response": deepcopy(audit)}
            for name in ("diagnosis", "revision_1", "acceptance_1")
        ]
        for stage in record["stages"]:
            reviewed["prompts"]["coverage_" + stage["name"]] = "recorded " + stage["name"]

    def review(text, initial, **config):
        assert text == extraction[0] and initial == extraction[1]
        assert config["api_key"] == "private-never-export"
        generation.append("coverage_review")
        return deepcopy(reviewed)

    monkeypatch.setattr(cli, "review_candidate_facts", review)
    review_args = Namespace(
        replay=None, review_bundle=args.output, config=args.config, output=tmp_path / "reviewed",
    )
    summary = cli.run(review_args)
    assert generation == ["extraction", "ontology", "replay", "coverage_review", "ontology"]
    assert summary["semantic_coverage_review"]["entity_reviews"] == 2
    assert summary["review_status"] == "unreviewed"
    assert summary["mode"] == "llm_coverage_review"
    assert summary["semantic_coverage_review"]["stages"] == (3 if staged else 0)
    if staged:
        for stage in reviewed["extraction"]["coverage_review"]["stages"]:
            assert (review_args.output / f"coverage-{stage['name']}.json").exists()
            assert (review_args.output / f"coverage-{stage['name']}-prompt.txt").exists()
    assert (review_args.output / "source.txt").read_bytes() == (args.output / "source.txt").read_bytes()
    for name in ("coverage-review.json", "coverage-review-prompt.txt"):
        assert name in summary["files"]
        assert b"private-never-export" not in (review_args.output / name).read_bytes()

    def replay(text, record, *, source_id):
        assert text == extraction[0] and source_id == "policy"
        assert record == reviewed["extraction"]
        return deepcopy(reviewed)

    monkeypatch.setattr(cli, "replay_candidate_facts", replay)
    replay_args = Namespace(replay=review_args.output, output=tmp_path / "replayed")
    cli.run(replay_args)
    for name in ("facts.json", "coverage-review.json", "coverage-review-prompt.txt"):
        assert (replay_args.output / name).read_bytes() == (review_args.output / name).read_bytes()
    assert generation.count("ontology") == 2

    # Even a rewritten bundle hash cannot make a different audit prompt replay.
    path = review_args.output / "coverage-review-prompt.txt"
    path.write_text("changed audit prompt", encoding="utf-8")
    summary["files"][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    (review_args.output / "SUMMARY.json").write_text(json.dumps(summary), encoding="utf-8")
    replay_args.output = tmp_path / "tampered"
    with pytest.raises(ValueError, match="prompt artifacts"):
        cli.run(replay_args)
    assert not replay_args.output.exists()


@pytest.mark.parametrize("field", ["source_id", "title", "sha256"])
def test_review_bundle_checks_source_identity_before_model(
    cli, extraction, generation, tmp_path, field
):
    args = args_for(tmp_path, extraction[0])
    cli.run(args)
    path = args.output / "SUMMARY.json"
    summary = json.loads(path.read_text(encoding="utf-8"))
    summary["source"][field] = "different"
    path.write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(ValueError, match="source identity"):
        cli.run(Namespace(replay=None, review_bundle=args.output, config=args.config, output=tmp_path / "reviewed"))
    assert generation == ["extraction", "ontology"]


def test_rejected_review_saves_diagnostic_and_never_publishes_or_overwrites(
    cli, extraction, generation, monkeypatch, tmp_path
):
    args = args_for(tmp_path, extraction[0])
    cli.run(args)
    record = {"response": {"relationships": []}, "model": "test"}

    def reject(*a, **kw):
        raise cli.CoverageReviewError("missing line coverage", record)

    monkeypatch.setattr(cli, "review_candidate_facts", reject)
    target = tmp_path / "rejected"
    argv = ["--config", str(args.config), "--review-bundle", str(args.output), "--output", str(target)]
    assert cli.main(argv) == 2
    assert not target.exists()
    diagnostic = tmp_path / "rejected.coverage-rejected.json"
    assert json.loads(diagnostic.read_text(encoding="utf-8"))["review"] == record
    diagnostic.write_text("previous rejected response", encoding="utf-8")
    assert cli.main(argv) == 2
    assert diagnostic.read_text(encoding="utf-8") == "previous rejected response"
    assert generation.count("ontology") == 1
