#!/usr/bin/env python3
"""Extract candidate entities/relationships and publish a portable Explorer bundle.

Live mode uses native LLM extraction, independent semantic coverage review,
qualified RDF, LLM OntologyGenerator and validate_graph. Replay verifies the
saved bundle without contacting a model.
Provider credentials are supplied privately and never included in the bundle.
"""

import argparse
import hashlib
import json
import logging
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from semantica.explorer.candidate_bundle import (
    build_candidate_graph,
    read_candidate_bundle,
)
from semantica.export.rdf_exporter import RDFExporter
from semantica.ontology.candidate_ontology import (
    CANDIDATE_PROMPT_VERSION,
    QUALIFIED_CANDIDATE_PROMPT_VERSION,
    build_candidate_prompt,
    normalize_candidate_ontology,
)
from semantica.ontology.candidate_statements import (
    prepare_candidate_statements,
    validate_candidate_statements,
)
from semantica.ontology.engine import OntologyEngine
from semantica.ontology.llm_generator import GENERATION_OPTIONS
from semantica.ontology.ontology_generator import OntologyGenerator
from semantica.ontology.owl_generator import OWLGenerator
from semantica.ontology.rdf_input import prepare_rdf_input
from semantica.semantic_extract.candidate_profile import (
    extract_candidate_facts,
    replay_candidate_facts,
)
from semantica.semantic_extract.candidate_coverage import (
    CoverageReviewError,
)
from semantica.semantic_extract.candidate_coverage_stages import review_candidate_facts


BUNDLE_VERSION = "candidate-facts-bundle-v2"
LEGACY_BUNDLE_VERSION = "candidate-facts-bundle-v1"


class ExportError(ValueError):
    """A fixed error safe to print without provider credentials."""


def _check_output(output):
    if output.is_symlink() or (
        output.exists() and (not output.is_dir() or any(output.iterdir()))
    ):
        raise ExportError("Output must be a nonexistent or empty directory.")


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def _read_config(path):
    config = json.loads(path.read_bytes())
    allowed = {
        *GENERATION_OPTIONS,
        "method",
        "provider",
        "api_key",
        "base_url",
        "max_retries",
        "timeout",
        "timeout_seconds",
    }
    if (
        not isinstance(config, dict)
        or set(config) - allowed
        or any(
            not isinstance(config.get(key), str) or not config[key].strip()
            for key in ("provider", "model")
        )
        or config.get("method", "llm") != "llm"
    ):
        raise ExportError(
            "Private configuration must specify provider/model and only LLM generation settings."
        )
    if config.get("thinking") is not None and config["thinking"] not in (
        {"type": "enabled"}, {"type": "disabled"},
    ):
        raise ExportError("thinking must specify only an enabled or disabled type.")
    return {key: value for key, value in config.items() if key != "method"}


def _replay_ontology(saved, facts, options, rdf_hash, prompt_hash):
    metadata = saved.get("metadata", {})
    prompt_version = (
        QUALIFIED_CANDIDATE_PROMPT_VERSION
        if options.get("qualified_statements")
        else CANDIDATE_PROMPT_VERSION
    )
    if (
        metadata.get("source") != "llm"
        or metadata.get("input_rdf_sha256") != rdf_hash
        or metadata.get("prompt_sha256") != prompt_hash
        or metadata.get("prompt_version") != prompt_version
        or any(
            not isinstance(metadata.get(key), str) or not metadata[key].strip()
            for key in ("provider", "model")
        )
    ):
        raise ExportError("Replay ontology must match the candidate RDF and prompt.")
    ontology = normalize_candidate_ontology(saved, facts, **options)
    ontology["metadata"].update(
        {
            key: metadata[key]
            for key in (
                "source",
                "provider",
                "model",
                "prompt_version",
                "prompt_sha256",
            )
        }
    )
    return ontology


def run(args):
    """Generate/replay once, then atomically publish only a complete bundle."""
    output = args.output.absolute()
    _check_output(output)
    saved_files = None
    bundle_version = BUNDLE_VERSION
    if args.replay:
        if any(
            getattr(args, key, None) is not None
            for key in (
                "source",
                "source_id",
                "title",
                "version",
                "name",
                "base_uri",
                "config",
                "review_bundle",
            )
        ):
            raise ExportError(
                "Replay uses the source and generation identity saved in its bundle."
            )
        saved_files = read_candidate_bundle(args.replay)
        previous = json.loads(saved_files["SUMMARY.json"])
        bundle_version = previous.get("format_version")
        if bundle_version not in {BUNDLE_VERSION, LEGACY_BUNDLE_VERSION}:
            raise ExportError(
                "Replay requires a candidate-facts bundle of this version."
            )
        source = previous["source"]
        options = previous["generation"]
        source_bytes = saved_files["source.txt"]
        manifest = json.loads(saved_files["source-manifest.json"])
        expected_source = {
            "source_id": source.get("source_id"),
            "source_sha256": _digest(source_bytes),
            "path": "source.txt",
            "title": source.get("title"),
            "version": source.get("version"),
        }
        if source.get("sha256") != expected_source["source_sha256"] or manifest.get(
            "sources"
        ) != [expected_source]:
            raise ExportError(
                "Replay source identity differs from its saved material manifest."
            )
        extracted = replay_candidate_facts(
            source_bytes.decode("utf-8"),
            json.loads(saved_files["extraction.json"]),
            source_id=source["source_id"],
        )
        if extracted["facts"] != json.loads(saved_files["facts.json"]):
            raise ExportError(
                "Replay extraction does not reproduce the saved candidate facts."
            )
        mode = "offline_replay"
    elif getattr(args, "review_bundle", None):
        if args.config is None or any(
            getattr(args, key, None) is not None
            for key in ("source", "source_id", "title", "version", "name", "base_uri")
        ):
            raise ExportError(
                "Review uses a private config and the source identity saved in its input bundle."
            )
        config = _read_config(args.config)
        inputs = read_candidate_bundle(args.review_bundle)
        previous = json.loads(inputs["SUMMARY.json"])
        if previous.get("format_version") != BUNDLE_VERSION:
            raise ExportError("Coverage review requires a qualified candidate bundle.")
        source = previous["source"]
        options = previous["generation"]
        source_bytes = inputs["source.txt"]
        manifest = json.loads(inputs["source-manifest.json"])
        expected_source = {
            "source_id": source.get("source_id"),
            "source_sha256": _digest(source_bytes),
            "path": "source.txt",
            "title": source.get("title"),
            "version": source.get("version"),
        }
        if source.get("sha256") != expected_source["source_sha256"] or manifest.get(
            "sources"
        ) != [expected_source]:
            raise ExportError("Review source identity differs from its saved material.")
        extracted = replay_candidate_facts(
            source_bytes.decode("utf-8"), json.loads(inputs["extraction.json"]),
            source_id=source["source_id"],
        )
        if extracted["facts"] != json.loads(inputs["facts.json"]):
            raise ExportError("Review input facts do not match the original model responses.")
        extracted = review_candidate_facts(source_bytes.decode("utf-8"), extracted, **config)
        mode = "llm_coverage_review"
    else:
        if args.source is None or not args.source_id or args.config is None:
            raise ExportError("Generation requires --source, --source-id and --config.")
        config = _read_config(args.config)
        source_bytes = args.source.read_bytes()
        source = {
            "source_id": args.source_id,
            "sha256": _digest(source_bytes),
            "title": args.title,
            "version": args.version,
        }
        options = {
            "name": args.name or "CandidateOntology",
            "base_uri": args.base_uri or "https://semantica.dev/ontology/",
            "qualified_statements": True,
        }
        extracted = extract_candidate_facts(
            source_bytes.decode("utf-8"), source_id=args.source_id, review_coverage=True, **config
        )
        mode = "llm"

    facts = extracted["facts"]
    if not facts.get("entities"):
        raise ExportError(
            "No candidate entities were extracted; no ontology bundle was published."
        )
    qualified = options.get("qualified_statements") is True
    statements = prepare_candidate_statements(facts) if qualified else None
    base_rdf = (
        statements.rdf
        if statements is not None
        else RDFExporter().export_to_rdf(facts, format="turtle")
    )
    rdf_hash = prepare_rdf_input(base_rdf).sha256
    prompt = build_candidate_prompt(facts, **options)
    if saved_files is not None:
        ontology = _replay_ontology(
            json.loads(saved_files["ontology.json"]),
            facts,
            options,
            rdf_hash,
            _digest(prompt.encode()),
        )
    else:
        ontology = OntologyGenerator(**config).generate_ontology(
            facts, method="llm", **options
        )
    engine = OntologyEngine(provider=None)
    # SHACL describes business types, so it runs on a temporary vocabulary
    # projection. Reification transport triples are not business observations.
    report = engine.validate_graph(
        statements.projection.canonical_ntriples if statements else base_rdf,
        ontology=ontology,
    )
    issues = report.to_dict()
    preservation = None
    if qualified:
        preservation = validate_candidate_statements(base_rdf, facts)
        if not preservation["conforms"]:
            raise ExportError("Qualified RDF did not preserve its candidate facts.")
        issues["scope"] = "business_projection_schema"
        issues["authoritative_rdf_sha256"] = rdf_hash
    source_manifest = {
        "sources": [
            {
                "source_id": source["source_id"],
                "source_sha256": source["sha256"],
                "path": "source.txt",
                "title": source.get("title"),
                "version": source.get("version"),
            }
        ]
    }
    graph = build_candidate_graph(base_rdf, ontology, facts, source_manifest)
    files = {
        "source.txt": source_bytes,
        "source-manifest.json": _json_bytes(source_manifest),
        "facts.json": _json_bytes(facts),
        "extraction.json": _json_bytes(extracted["extraction"]),
        "extraction-issues.json": _json_bytes(extracted["issues"]),
        "entity-prompt.txt": extracted["prompts"]["entities"].encode("utf-8"),
        "relationship-prompt.txt": extracted["prompts"]["relationships"].encode(
            "utf-8"
        ),
        "base.ttl": base_rdf.encode("utf-8"),
        "ontology-prompt.txt": prompt.encode("utf-8"),
        "ontology.json": _json_bytes(ontology),
        "ontology.ttl": OWLGenerator()
        .generate_owl(ontology, format="turtle")
        .encode("utf-8"),
        "shapes.ttl": engine.to_shacl(ontology).encode("utf-8"),
        "issues.json": _json_bytes(issues),
        "candidate-graph.json": _json_bytes(graph),
    }
    if preservation is not None:
        files["preservation.json"] = _json_bytes(preservation)
    if "coverage_review" in extracted["extraction"]:
        files["coverage-review.json"] = _json_bytes(extracted["extraction"]["coverage_review"])
        files["coverage-review-prompt.txt"] = extracted["prompts"]["coverage_review"].encode(
            "utf-8"
        )
        for stage in extracted["extraction"]["coverage_review"].get("stages", []):
            name = stage["name"]
            files[f"coverage-{name}.json"] = _json_bytes(stage)
            files[f"coverage-{name}-prompt.txt"] = extracted["prompts"]["coverage_" + name].encode("utf-8")
    if saved_files is not None:
        for name in (
            "entity-prompt.txt",
            "relationship-prompt.txt",
            "ontology-prompt.txt",
            *(
                ["coverage-review.json", "coverage-review-prompt.txt"]
                if "coverage_review" in extracted["extraction"] else []
            ),
            *(name for name in files if name.startswith("coverage-") and name not in {"coverage-review.json", "coverage-review-prompt.txt"}),
        ):
            if saved_files.get(name) != files[name]:
                raise ExportError(
                    "Replay prompt artifacts differ from their recorded inputs."
                )
    summary = {
        "format_version": bundle_version,
        "mode": mode,
        "source": source,
        "generation": options,
        "fact_status": "candidate",
        "review_status": "unreviewed",
        "entities": len(facts["entities"]),
        "relationships": len(facts["relationships"]),
        "classes": len(ontology["classes"]),
        "properties": len(ontology["properties"]),
        "input_rdf_sha256": rdf_hash,
        "conforms": report.conforms,
        "coverage": report.coverage,
        "technical_issues": report.technical_issues,
        "extraction_issue_count": len(extracted["issues"]),
        "limitations": [
            "Model-proposed entities, types, relationships and definitions remain unreviewed; technical consistency does not prove business accuracy or completeness.",
            "RDFExporter exports base entity/relation triples. Evidence and relation qualifiers remain in facts.json and the Explorer overlay, not qualified RDF assertions.",
            "Input is one UTF-8 document of at most 32000 Unicode characters; no automatic chunking or cross-document entity merging.",
        ],
        "files": {name: _digest(value) for name, value in files.items()},
    }
    if qualified:
        summary.update(
            validation_scope="business_projection_schema",
            preservation_conforms=preservation["conforms"],
            input_facts_sha256=statements.facts_sha256,
        )
        summary["limitations"][1] = (
            "base.ttl preserves qualified candidate statements, source evidence and metadata; "
            "display edges and SHACL use an internal business projection. Preservation compares "
            "against the same extracted facts and cannot detect facts the model omitted. "
            "Schema conformance does not prove independent business completeness."
        )
    if "coverage_review" in extracted["extraction"]:
        review = extracted["extraction"]["coverage_review"]
        audit = review["stages"][-1]["response"] if "stages" in review else review["response"]
        summary["semantic_coverage_review"] = {
            "prompt_version": review["prompt_version"],
            "provider": review["provider"],
            "model": review["model"],
            "stages": len(review.get("stages", [])),
            "entity_reviews": len(audit["entity_reviews"]),
            "clause_reviews": len(audit["clause_reviews"]),
            "competency_reviews": len(audit.get("competency_reviews", [])),
            "unresolved": sum(
                item["status"] == "unresolved"
                for group in ("entity_reviews", "clause_reviews", "competency_reviews")
                for item in audit.get(group, [])
            ),
            "status": "llm_candidate_review",
        }
    files["SUMMARY.json"] = _json_bytes(summary)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".candidate-bundle-", dir=output.parent
    ) as temp:
        staged = Path(temp) / "bundle"
        staged.mkdir()
        for name, value in files.items():
            (staged / name).write_bytes(value)
        read_candidate_bundle(staged)
        _check_output(output)
        if output.exists():
            output.rmdir()
        staged.rename(output)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--config", type=Path, help="Private provider/model JSON")
    mode.add_argument(
        "--replay", type=Path, help="Previously generated bundle directory"
    )
    parser.add_argument("--source", type=Path, help="Original UTF-8 document")
    parser.add_argument(
        "--review-bundle", type=Path,
        help="With --config, independently review an existing bundle's original LLM extraction",
    )
    parser.add_argument(
        "--source-id", help="Stable source identity; never interpreted as a path"
    )
    parser.add_argument("--title", help="Known material title")
    parser.add_argument(
        "--version", help="Known material version; omitted means unknown"
    )
    parser.add_argument("--name", help="Ontology draft title")
    parser.add_argument(
        "--base-uri", help="Ontology container IRI; exported term IRIs remain unchanged"
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="New or empty bundle directory"
    )
    args = parser.parse_args(argv)
    # Third-party provider errors may include private request settings.
    previous_logging = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        summary = run(args)
    except CoverageReviewError as error:
        diagnostic = args.output.with_name(args.output.name + ".coverage-rejected.json")
        diagnostic.parent.mkdir(parents=True, exist_ok=True)
        try:
            with diagnostic.open("x", encoding="utf-8") as stream:
                json.dump(
                    {"error": str(error), "review": error.record}, stream,
                    ensure_ascii=False, indent=2,
                )
        except FileExistsError:
            print(
                "A previous rejected coverage review is already saved; it was not overwritten.",
                file=sys.stderr,
            )
        print(
            f"Coverage review rejected: {error}; no bundle published. Diagnostic: {diagnostic}",
            file=sys.stderr,
        )
        return 2
    except ExportError as error:
        print(str(error), file=sys.stderr)
        return 2
    except Exception:
        print(
            "Candidate extraction/validation failed; no bundle was published.",
            file=sys.stderr,
        )
        return 2
    finally:
        logging.disable(previous_logging)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
