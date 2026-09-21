#!/usr/bin/env python3
"""Complete an existing bundle's provenance definitions through an LLM.

Without --config, validate and replay a bundle's saved provenance model offline.
Original business facts, RDF, ontology and projection are copied unchanged.
"""

import argparse
import json
import logging
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from examples.extract_candidate_facts import _check_output, _digest, _json_bytes, _read_config
from semantica.explorer.candidate_bundle import build_candidate_graph, create_bundle_app, read_candidate_bundle
from semantica.ontology.candidate_provenance import generate_provenance_model, serialize_relationship_shapes, validate_provenance_model
from semantica.ontology.llm_generator import LLMOntologyGenerator
from semantica.ontology.owl_generator import OWLGenerator
from semantica.utils.exceptions import ValidationError


def run(args):
    output = args.output.absolute()
    _check_output(output)
    files = read_candidate_bundle(args.bundle)
    summary = json.loads(files.pop("SUMMARY.json"))
    if summary.get("format_version") != "candidate-facts-bundle-v2":
        raise ValueError("Provenance completion requires qualified candidate bundle v2.")
    projection = build_candidate_graph(
        files["base.ttl"].decode("utf-8"), json.loads(files["ontology.json"]),
        json.loads(files["facts.json"]), json.loads(files["source-manifest.json"]),
    )
    if projection != json.loads(files["candidate-graph.json"]):
        raise ValueError("Saved projection differs from the bundle inputs.")
    if args.config:
        llm = LLMOntologyGenerator(**_read_config(args.config))
        model, prompt, response = generate_provenance_model(projection, files["base.ttl"], llm)
        files["provenance-model.json"] = _json_bytes(model)
        files["provenance-prompt.txt"] = prompt.encode("utf-8")
        files["provenance-response.json"] = _json_bytes(response)
        files["provenance-ontology.ttl"] = OWLGenerator().generate_owl(model["ontology"], format="turtle").encode("utf-8")
        files["provenance-shapes.ttl"] = serialize_relationship_shapes(model["relationship_shapes"]).encode("utf-8")
        summary["provenance_mode"] = "llm"
    else:
        model = json.loads(files["provenance-model.json"])
        summary["provenance_mode"] = "offline_replay"
    validate_provenance_model(model, projection, files["base.ttl"])
    summary["provenance_generation"] = model["ontology"]["metadata"]
    summary["files"] = {name: _digest(value) for name, value in files.items()}
    files["SUMMARY.json"] = _json_bytes(summary)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".candidate-provenance-", dir=output.parent) as temp:
        staged = Path(temp) / "bundle"
        staged.mkdir()
        for name, value in files.items():
            target = staged / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(value)
        create_bundle_app(staged)
        _check_output(output)
        if output.exists():
            output.rmdir()
        staged.rename(output)
    return {"output": str(output), "mode": summary["provenance_mode"], "model": model["ontology"]["metadata"]["model"], "classes": len(model["ontology"]["classes"]), "properties": len(model["ontology"]["properties"]), "relationship_shapes": len(model.get("relationship_shapes", []))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--config", type=Path, help="Private provider configuration; omit to replay")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        result = run(args)
    except ValidationError as error:
        print(f"LLM output validation failed: {error}", file=sys.stderr)
        return 2
    except Exception:
        print("LLM provenance generation or validation failed; no bundle published.", file=sys.stderr)
        return 2
    finally:
        logging.disable(previous)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
