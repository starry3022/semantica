#!/usr/bin/env python3
"""Generate a grounded candidate business ontology, or replay a saved result.

Use --config with a private JSON provider configuration for generation. Use
--replay with an exported ontology.json for offline validation and export.
Business schema and the fixed process/evidence vocabulary are separate files;
this command never rewrites process rules, instance RDF or SHACL constraints.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rdflib import Graph, Literal, OWL, RDF, RDFS, URIRef
from rdflib.compare import isomorphic

from semantica.ontology.llm_generator import LLMOntologyGenerator
from semantica.ontology.owl_generator import OWLGenerator
from semantica.semantic_extract.process_graph import (
    CLASSES,
    DATATYPE_PROPERTIES,
    DEFAULT_BASE,
    OBJECT_PROPERTIES,
    process_rule_ontology,
)


class ExportError(ValueError):
    """A safe, fixed explanation that may be printed without private config."""


def _check_output(output):
    if output.is_symlink() or (
        output.exists() and (not output.is_dir() or any(output.iterdir()))
    ):
        raise ExportError("Output must be a nonexistent or empty directory.")


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _metadata(metadata, source_bytes, prompt):
    if not isinstance(metadata, dict) or metadata.get("source") != "llm":
        raise ExportError("Saved ontology must identify its LLM provenance.")
    if metadata.get("source_sha256") != hashlib.sha256(source_bytes).hexdigest():
        raise ExportError("Source hash differs from the saved ontology.")
    if metadata.get("prompt_sha256") != hashlib.sha256(prompt.encode()).hexdigest():
        raise ExportError("Prompt hash differs from the saved ontology.")
    required = ("provider", "model", "prompt_version")
    if any(
        not isinstance(metadata.get(key), str) or not metadata[key] for key in required
    ):
        raise ExportError("Saved ontology is missing generation provenance.")
    return {
        key: metadata[key]
        for key in (
            "source",
            "provider",
            "model",
            "source_sha256",
            "prompt_version",
            "prompt_sha256",
        )
    } | {"fact_status": "candidate", "review_status": "unreviewed"}


def _rdf_artifacts(ontology):
    """Use the existing serializer, then verify annotations and RDF references."""
    serialized = OWLGenerator().generate_owl(ontology, format="turtle")
    graph = Graph().parse(data=serialized, format="turtle")
    expected_classes = {URIRef(term["uri"]) for term in ontology["classes"]}
    if set(graph.subjects(RDF.type, OWL.Class)) != expected_classes:
        raise ExportError("RDF export did not preserve the declared classes.")
    for term in ontology["classes"] + ontology["properties"]:
        subject = URIRef(term["uri"])
        if str(graph.value(subject, RDFS.label)) != term["label"]:
            raise ExportError("RDF export did not preserve a term label.")
        if "type" in term:
            rdf_type = (
                OWL.ObjectProperty if term["type"] == "object" else OWL.DatatypeProperty
            )
            if (subject, RDF.type, rdf_type) not in graph:
                raise ExportError("RDF export did not preserve a property type.")
            for key, predicate in (("domain", RDFS.domain), ("range", RDFS.range)):
                if set(graph.objects(subject, predicate)) != {
                    URIRef(value) for value in term[key]
                }:
                    raise ExportError(
                        "RDF export did not preserve property references."
                    )
        elif term.get("subClassOf"):
            if (subject, RDFS.subClassOf, URIRef(term["subClassOf"])) not in graph:
                raise ExportError("RDF export did not preserve class inheritance.")
        graph.set(
            (
                subject,
                RDFS.comment,
                Literal(
                    f"{term.get('comment') or ''}\nCandidate / unreviewed. "
                    f"Evidence quote: {term['evidence_quote']}"
                ),
            )
        )
    metadata = ontology["metadata"]
    graph.set(
        (
            URIRef(ontology["uri"]),
            RDFS.comment,
            Literal(
                "LLM-generated candidate business ontology; unreviewed. "
                "Structural and quotation checks do not constitute business approval.\n"
                f"Provider: {metadata['provider']}\nModel: {metadata['model']}\n"
                f"Source SHA-256: {metadata['source_sha256']}\n"
                f"Prompt version: {metadata['prompt_version']}\n"
                f"Prompt SHA-256: {metadata['prompt_sha256']}"
            ),
        )
    )
    turtle = graph.serialize(format="turtle")
    xml = graph.serialize(format="xml")
    roundtrip = Graph().parse(data=xml, format="xml")
    if not isomorphic(graph, roundtrip):
        raise ExportError("Turtle and RDF/XML exports are not equivalent.")
    validation = {
        "valid": True,
        "classes": len(ontology["classes"]),
        "properties": len(ontology["properties"]),
        "grounded_terms": len(ontology["classes"]) + len(ontology["properties"]),
        "rdf_triples": len(graph),
        "rdf_roundtrip_isomorphic": True,
        "fact_status": "candidate",
        "review_status": "unreviewed",
        "meaning": "Structure, RDF references and exact quotations only; not semantic or business approval.",
    }
    return turtle.encode(), xml.encode(), validation


def run(args):
    """Validate the whole bundle before atomically publishing any artifacts."""
    output = args.output.absolute()
    _check_output(output)
    if args.base_uri.rstrip("/#") == args.process_base_uri.rstrip("/#"):
        raise ExportError("Business and process vocabulary namespaces must differ.")
    source_bytes = args.source.read_bytes()
    text = source_bytes.decode("utf-8")
    excluded = sorted({*CLASSES, *OBJECT_PROPERTIES, *DATATYPE_PROPERTIES})
    options = {
        "base_uri": args.base_uri,
        "name": args.name or "BusinessOntology",
        "require_grounding": True,
        "excluded_terms": excluded,
    }
    if args.max_tokens is not None:
        options["max_tokens"] = args.max_tokens
    if args.replay:
        saved = json.loads(args.replay.read_text(encoding="utf-8"))
        if not isinstance(saved, dict):
            raise ExportError("Replay ontology must be a JSON object.")
        original_metadata = saved.get("metadata", {})
        if (
            not isinstance(original_metadata, dict)
            or original_metadata.get("source_sha256")
            != hashlib.sha256(source_bytes).hexdigest()
        ):
            raise ExportError("Source hash differs from the saved ontology.")
        options["name"] = args.name or saved.get("name") or "BusinessOntology"
        generator = LLMOntologyGenerator(provider=None)
        prompt_path = args.replay.parent / "prompt.txt"
        prompt = (
            prompt_path.read_bytes().decode("utf-8")
            if prompt_path.is_file()
            else generator._build_prompt(text=text, **options)
        )
        metadata = _metadata(original_metadata, source_bytes, prompt)
        ontology = generator._normalize_output(saved, text=text, **options)
        mode = "offline_replay"
    else:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        if not isinstance(config, dict) or any(
            not isinstance(config.get(key), str) or not config[key]
            for key in ("provider", "model")
        ):
            raise ExportError("Private configuration must specify provider and model.")
        generator = LLMOntologyGenerator(**config)
        prompt = generator._build_prompt(text=text, **options)
        ontology = generator.generate_ontology_from_text(text, **options)
        metadata = _metadata(ontology.get("metadata"), source_bytes, prompt)
        mode = "llm"
    ontology["metadata"] = metadata
    # The source material's version is not an ontology release version.
    ontology["version"] = None
    turtle, xml, validation = _rdf_artifacts(ontology)
    vocabulary = process_rule_ontology(args.process_base_uri, label_language="zh")
    files = {
        "source.txt": source_bytes,
        "prompt.txt": prompt.encode("utf-8"),
        "ontology.json": _json_bytes(ontology),
        "ontology.ttl": turtle,
        "ontology.owl": xml,
        "process-vocabulary.ttl": vocabulary.serialize(format="turtle").encode(),
        "validation.json": _json_bytes(validation),
    }
    summary = {
        "status": "candidate",
        "mode": mode,
        "classes": validation["classes"],
        "properties": validation["properties"],
        **metadata,
        "validation": validation,
        "artifacts": {
            name: hashlib.sha256(value).hexdigest() for name, value in files.items()
        },
    }
    files["SUMMARY.json"] = _json_bytes(summary)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".ontology-", dir=output.parent
    ) as temporary:
        staging = Path(temporary) / "artifacts"
        staging.mkdir()
        for name, value in files.items():
            (staging / name).write_bytes(value)
        _check_output(output)
        staging.rename(output)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="UTF-8 source text")
    parser.add_argument(
        "--output", type=Path, required=True, help="New or empty artifact directory"
    )
    parser.add_argument("--base-uri", required=True, help="Business ontology namespace")
    parser.add_argument("--name", help="Business ontology name")
    parser.add_argument("--process-base-uri", default=DEFAULT_BASE)
    parser.add_argument(
        "--max-tokens",
        type=int,
        help="Override the output token limit for this generation",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--config", type=Path, help="Private JSON provider configuration")
    mode.add_argument("--replay", type=Path, help="Previously exported ontology.json")
    args = parser.parse_args(argv)
    if args.max_tokens is not None and (args.max_tokens <= 0 or args.replay):
        parser.error("--max-tokens must be positive and requires --config")
    try:
        summary = run(args)
    except ExportError as error:
        print(str(error), file=sys.stderr)
        return 2
    except Exception:
        # Provider exceptions may contain API keys or request headers.
        print(
            "Ontology generation or validation failed; no artifacts were published.",
            file=sys.stderr,
        )
        return 2
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
