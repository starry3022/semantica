#!/usr/bin/env python3
"""Extract candidate process rules, or replay an extraction without an LLM call.

Use --config with a private JSON file containing provider/model and optional
api_key/base_url/temperature/max_tokens. Use --replay to verify and export a
saved ProcessExtractionResult against the unchanged original source.
"""
import argparse
import hashlib
import json
import logging
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rdflib import Graph, RDF
from rdflib.namespace import SH
from pyshacl import validate

from semantica.semantic_extract.process_extractor import (
    extract_process_rules,
    finalize_process_rules,
)
from semantica.semantic_extract.process_graph import (
    DEFAULT_BASE,
    export_process_rdf,
    process_rule_ontology,
    process_rule_shapes,
    process_rules_to_graph,
)
from semantica.semantic_extract.process_schemas import ProcessExtractionResult


def write_artifacts(
    result, source_bytes, output, base_uri=DEFAULT_BASE, mode="offline_replay"
):
    """Export candidates and independently run structural SHACL validation."""
    if hashlib.sha256(source_bytes).hexdigest() != result.source_sha256:
        raise ValueError("Source hash differs from extraction result")

    def save(name, value):
        (output / name).write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    graph = process_rules_to_graph(result, base_uri=base_uri)
    turtle = export_process_rdf(graph)
    ontology = process_rule_ontology(base_uri)
    shapes = process_rule_shapes(base_uri)
    data = Graph().parse(data=turtle, format="turtle")
    conforms, report, report_text = validate(data, shacl_graph=shapes, inference="none")
    targets = set(shapes.objects(None, SH.targetClass))
    focus = {node for target in targets for node in data.subjects(RDF.type, target)}
    validation = {
        "conforms": bool(conforms),
        "matching_focus_nodes": len(focus),
        "node_shapes": len(set(shapes.subjects(RDF.type, SH.NodeShape))),
        "property_shapes": len(set(shapes.objects(None, SH.property))),
        "validation_results": len(set(report.subjects(RDF.type, SH.ValidationResult))),
        "report": report_text,
        "meaning": "Structural conformance only; not semantic completeness or governance approval",
    }
    (output / "source.txt").write_bytes(source_bytes)
    save("process-rules.json", result.model_dump(mode="json"))
    save("candidate-graph.json", graph)
    (output / "instances.ttl").write_text(turtle, encoding="utf-8")
    ontology.serialize(output / "ontology.ttl", format="turtle")
    ontology.serialize(output / "ontology.owl", format="xml")
    shapes.serialize(output / "shapes.ttl", format="turtle")
    save("validation.json", validation)
    summary = {
        "status": (
            "needs_review"
            if conforms and result.coverage["complete"] and result.rules
            else "incomplete"
        ),
        "mode": mode,
        "source_id": result.source_id,
        "source_sha256": result.source_sha256,
        "rule_count": len(result.rules),
        "nodes": len(graph["nodes"]),
        "edges": len(graph["edges"]),
        "rdf_triples": len(data),
        "ontology_triples": len(ontology),
        "coverage": result.coverage,
        "fact_status": result.fact_status,
        "review_status": result.review_status,
        "validation": validation,
        "artifacts": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(output.iterdir())
            if p.is_file() and p.name != "SUMMARY.json"
        },
    }
    save("SUMMARY.json", summary)
    if not conforms:
        raise ValueError(
            "Generated graph failed structural SHACL validation; inspect validation.json"
        )
    if not result.rules:
        raise ValueError(
            "No candidate process rules; inspect source and clause assessments"
        )
    if not result.coverage["complete"]:
        raise ValueError(
            "Clause coverage is incomplete; inspect process-rules.json before use"
        )
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-file", type=Path, required=True)
    parser.add_argument("--source-id", help="Default: source filename")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--base-uri", default=DEFAULT_BASE)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--config", type=Path, help="Private LLM configuration; never written to output"
    )
    mode.add_argument(
        "--replay", type=Path, help="Saved process-rules.json; makes no network request"
    )
    args = parser.parse_args(argv)
    secret = None
    # Provider exception logs can contain raw payloads. The CLI reports a
    # redacted error below; applications control their own SDK logging policy.
    logging.disable(logging.CRITICAL)
    try:
        source_bytes = args.source_file.read_bytes()
        source = source_bytes.decode("utf-8")
        args.output_dir.mkdir(parents=True, exist_ok=True)
        if any(args.output_dir.iterdir()):
            raise ValueError("Output directory must be empty")
        if args.replay:
            previous = ProcessExtractionResult.model_validate_json(
                args.replay.read_text(encoding="utf-8")
            )
            if previous.source_sha256 != hashlib.sha256(source_bytes).hexdigest():
                raise ValueError("Source hash differs from saved extraction")
            if args.source_id and args.source_id != previous.source_id:
                raise ValueError("Source id differs from saved extraction")
            # Recompute source clauses and evidence offsets, never trust a
            # saved candidate file to attest its own evidence alignment.
            result = finalize_process_rules(
                source,
                previous.source_id,
                {
                    "rules": [r.model_dump(mode="json") for r in previous.rules],
                    "clause_assessments": previous.coverage["assessments"],
                },
            )
        else:
            config = json.loads(args.config.read_text(encoding="utf-8"))
            if not isinstance(config, dict):
                raise ValueError("LLM config must be a JSON object")
            secret = config.get("api_key")
            if secret is not None and (not isinstance(secret, str) or not secret):
                secret = None
                raise ValueError("api_key must be a nonempty string")
            options = {
                key: config[key]
                for key in (
                    "api_key",
                    "base_url",
                    "temperature",
                    "max_tokens",
                    "max_retries",
                )
                if key in config
            }
            result = extract_process_rules(
                source,
                source_id=args.source_id or args.source_file.name,
                provider=config.get("provider", "openai"),
                model=config.get("model"),
                **options,
            )
        summary = write_artifacts(
            result,
            source_bytes,
            args.output_dir,
            args.base_uri,
            "offline_replay" if args.replay else "llm",
        )
        print(
            json.dumps(
                {
                    key: summary[key]
                    for key in ("mode", "rule_count", "nodes", "edges", "review_status")
                },
                ensure_ascii=False,
            )
        )
        return 0
    except Exception as exc:
        message = str(exc)
        if secret:
            message = message.replace(secret, "[REDACTED]").replace(
                json.dumps(secret, ensure_ascii=False)[1:-1], "[REDACTED]"
            )
        print(
            json.dumps(
                {"error_type": type(exc).__name__, "error": message}, ensure_ascii=False
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
