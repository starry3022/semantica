#!/usr/bin/env python3
"""Export the native candidate-fact ontology/RDF technical validation path.

The same entities/relationships feed OntologyGenerator and RDFExporter. SHACL
checks self-consistency against the resulting draft, not factual truth or review.
Use a private --config for one generation, or --replay for offline validation.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ontology_from_text import ExportError, _check_output, _json_bytes
from semantica.export.rdf_exporter import RDFExporter
from semantica.ontology.candidate_ontology import (
    CANDIDATE_PROMPT_VERSION,
    build_candidate_prompt,
    normalize_candidate_ontology,
)
from semantica.ontology.engine import OntologyEngine
from semantica.ontology.llm_generator import GENERATION_OPTIONS
from semantica.ontology.ontology_generator import OntologyGenerator
from semantica.ontology.owl_generator import OWLGenerator
from semantica.ontology.rdf_input import prepare_rdf_input


def run(args):
    output = args.output.absolute()
    _check_output(output)
    facts_bytes = args.facts.read_bytes()
    facts = json.loads(facts_bytes)
    options = {"name": args.name, "base_uri": args.base_uri}
    base_rdf = RDFExporter().export_to_rdf(facts, format="turtle")
    rdf_hash = prepare_rdf_input(base_rdf).sha256
    prompt = build_candidate_prompt(facts, **options)
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
    if args.replay:
        saved = json.loads(args.replay.read_text(encoding="utf-8"))
        metadata = saved.get("metadata", {})
        if (
            metadata.get("source") != "llm"
            or metadata.get("input_rdf_sha256") != rdf_hash
            or metadata.get("prompt_sha256") != prompt_hash
            or metadata.get("prompt_version") != CANDIDATE_PROMPT_VERSION
            or any(
                not isinstance(metadata.get(key), str) or not metadata[key].strip()
                for key in ("provider", "model")
            )
        ):
            raise ExportError(
                "Replay requires matching candidate RDF, prompt and model provenance."
            )
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
        mode = "offline_replay"
    else:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        if not isinstance(config, dict) or any(
            not isinstance(config.get(key), str) or not config[key]
            for key in ("provider", "model")
        ):
            raise ExportError("Private configuration must specify provider and model.")
        if set(config) - {
            *GENERATION_OPTIONS,
            "method",
            "provider",
            "api_key",
            "base_url",
            "max_retries",
            "timeout",
            "timeout_seconds",
        }:
            raise ExportError(
                "Configuration must contain only provider and generation settings."
            )
        ontology = OntologyGenerator(**config).generate_ontology(
            facts, method="llm", **options
        )
        mode = "llm"

    engine = OntologyEngine(provider=None)
    report = engine.validate_graph(base_rdf, ontology=ontology)
    files = {
        "facts.json": facts_bytes,
        "base.ttl": base_rdf.encode("utf-8"),
        "prompt.txt": prompt.encode("utf-8"),
        "ontology.json": _json_bytes(ontology),
        "ontology.ttl": OWLGenerator()
        .generate_owl(ontology, format="turtle")
        .encode("utf-8"),
        "shapes.ttl": engine.to_shacl(ontology).encode("utf-8"),
        "issues.json": _json_bytes(report.to_dict()),
    }
    summary = {
        "mode": mode,
        "fact_status": "candidate",
        "review_status": "unreviewed",
        "meaning": "Technical consistency with a draft derived from the same facts; not independent semantic validation or business approval.",
        "entities": len(facts["entities"]),
        "relationships": len(facts["relationships"]),
        "classes": len(ontology["classes"]),
        "properties": len(ontology["properties"]),
        "input_rdf_sha256": rdf_hash,
        "conforms": report.conforms,
        "coverage": report.coverage,
        "technical_issues": report.technical_issues,
        "files": {
            name: hashlib.sha256(value).hexdigest() for name, value in files.items()
        },
    }
    files["SUMMARY.json"] = _json_bytes(summary)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".candidate-validation-", dir=output.parent
    ) as temp:
        staged = Path(temp) / "artifacts"
        staged.mkdir()
        for name, value in files.items():
            (staged / name).write_bytes(value)
        _check_output(output)
        if output.exists():
            output.rmdir()
        staged.rename(output)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--facts", required=True, type=Path, help="entities/relationships JSON"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--config", type=Path, help="Private provider/model JSON; never exported"
    )
    mode.add_argument("--replay", type=Path, help="Previously generated ontology.json")
    parser.add_argument(
        "--output", type=Path, required=True, help="New or empty artifact directory"
    )
    parser.add_argument("--name", default="CandidateOntology")
    parser.add_argument("--base-uri", default="https://semantica.dev/ontology/")
    args = parser.parse_args(argv)
    try:
        summary = run(args)
    except ExportError as error:
        print(str(error), file=sys.stderr)
        return 2
    except Exception:
        # Provider exceptions can contain credentials; do not echo their text.
        print(
            "Candidate validation failed; no artifacts were published.", file=sys.stderr
        )
        return 2
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
