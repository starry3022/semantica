#!/usr/bin/env python3
"""Generate an RDF-grounded candidate ontology and replay its validated bundle.

The native OntologyEngine uses an LLM for RDF input. An optional candidate graph
must represent exactly the same RDF before Explorer node snapshots can be bound.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from rdflib import OWL, RDF

from ontology_from_text import (
    ExportError,
    _check_output,
    _json_bytes,
    _metadata,
    _rdf_artifacts,
)
from semantica.ontology.engine import OntologyEngine
from semantica.ontology.evidence_context import (
    BusinessOntologyContext,
    ConceptReference,
    build_evidence_context,
)
from semantica.ontology.llm_generator import LLMOntologyGenerator
from semantica.ontology.rdf_input import prepare_rdf_input
from semantica.ontology.graph_snapshot import build_graph_snapshot
from semantica.semantic_extract.process_graph import (
    _base_uri,
    CLASSES,
    DATATYPE_PROPERTIES,
    DEFAULT_BASE,
    OBJECT_PROPERTIES,
    export_process_rdf,
    process_rule_ontology,
)


def bind_concept_references(context, ontology, candidate_graph):
    """Bind explicit model references after the caller verified RDF equivalence."""
    nodes = {node["id"]: node for node in candidate_graph["nodes"]}
    references = []
    for item in ontology["concept_references"]:
        node = nodes[item["node_id"]]
        references.append(
            ConceptReference(
                **item,
                node_type=node["type"],
                node_label=node["label"],
                node_properties=node["properties"],
                input_rdf_sha256=ontology["metadata"]["input_rdf_sha256"],
            ).model_dump()
        )
    business = context["business_ontologies"][0]
    business["concept_references"] = references
    business["input_graph"] = build_graph_snapshot(
        candidate_graph, ontology["metadata"]["input_rdf_sha256"]
    )
    context["business_ontologies"][0] = BusinessOntologyContext.model_validate(
        business
    ).model_dump()
    return context


def run(args):
    output = args.output.absolute()
    _check_output(output)
    source_bytes = args.source.read_bytes()
    text = source_bytes.decode("utf-8")
    rdf_bytes = args.rdf.read_bytes()
    prepared = prepare_rdf_input(rdf_bytes, rdf_format=args.rdf_format)
    candidate_graph = None
    if args.graph:
        candidate_graph = json.loads(args.graph.read_text(encoding="utf-8"))
        projected = prepare_rdf_input(export_process_rdf(candidate_graph))
        if projected.sha256 != prepared.sha256:
            raise ExportError(
                "Candidate graph and input RDF do not describe the same statements."
            )
    graph_base = candidate_graph["metadata"]["base_uri"] if candidate_graph else None
    process_base = args.process_base_uri or graph_base or DEFAULT_BASE
    if graph_base and _base_uri(process_base) != _base_uri(graph_base):
        raise ExportError(
            "Process vocabulary namespace differs from the candidate graph."
        )
    if _base_uri(args.base_uri) == _base_uri(process_base):
        raise ExportError("Business and process namespaces must differ.")
    options = {
        "base_uri": args.base_uri,
        "name": args.name or "BusinessOntology",
        "excluded_terms": sorted({*CLASSES, *OBJECT_PROPERTIES, *DATATYPE_PROPERTIES}),
    }
    if args.max_tokens is not None:
        options["max_tokens"] = args.max_tokens
    if args.replay:
        saved = json.loads(args.replay.read_text(encoding="utf-8"))
        original_metadata = saved.get("metadata", {})
        if (
            original_metadata.get("input_kind") != "rdf"
            or original_metadata.get("input_rdf_sha256") != prepared.sha256
        ):
            raise ExportError("Input RDF differs from the saved RDF-grounded ontology.")
        prompt = (args.replay.parent / "prompt.txt").read_bytes().decode("utf-8")
        metadata = _metadata(original_metadata, source_bytes, prompt)
        options["name"] = args.name or saved.get("name") or "BusinessOntology"
        generator = LLMOntologyGenerator(provider=None)
        ontology = generator.normalize_ontology_from_rdf(
            saved, prepared, source_text=text, **options
        )
        mode = "offline_replay"
    else:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        if not isinstance(config, dict) or any(
            not isinstance(config.get(key), str) or not config[key]
            for key in ("provider", "model")
        ):
            raise ExportError("Private configuration must specify provider and model.")
        engine = OntologyEngine(**config)
        prompt = engine.llm.build_rdf_prompt(prepared, source_text=text, **options)
        ontology = engine.from_rdf(
            prepared, source_text=text, generation_mode="business_concepts", **options
        )
        metadata = _metadata(ontology["metadata"], source_bytes, prompt)
        mode = "llm"
    ontology["metadata"] = {
        **ontology["metadata"],
        **metadata,
        "input_kind": "rdf",
        "input_rdf_sha256": prepared.sha256,
    }
    ontology["version"] = None
    turtle, xml, validation = _rdf_artifacts(ontology)
    validation.update(
        concept_references=len(ontology["concept_references"]),
        unmapped_nodes=len(ontology["unmapped_nodes"]),
        input_rdf_sha256=prepared.sha256,
    )
    vocabulary = process_rule_ontology(process_base, label_language="zh")
    files = {
        "source.txt": source_bytes,
        "input.ttl": prepared.canonical_ntriples.encode(),
        "prompt.txt": prompt.encode(),
        "ontology.json": _json_bytes(ontology),
        "ontology.ttl": turtle,
        "ontology.owl": xml,
        "process-vocabulary.ttl": vocabulary.serialize(format="turtle").encode(),
        "concept-references.json": _json_bytes(
            {
                "status": "candidate",
                "review_status": "unreviewed",
                "input_rdf_sha256": prepared.sha256,
                "references": ontology["concept_references"],
                "unmapped_nodes": ontology["unmapped_nodes"],
            }
        ),
        "validation.json": _json_bytes(validation),
    }
    if args.source_id:
        context = build_evidence_context(
            ontology,
            turtle.decode(),
            text,
            args.source_id,
            [str(vocabulary.value(predicate=RDF.type, object=OWL.Ontology))],
        )
        if candidate_graph is not None:
            context = bind_concept_references(context, ontology, candidate_graph)
        files["ontology-evidence-context.json"] = _json_bytes(context)
    summary = {
        "mode": mode,
        **ontology["metadata"],
        "validation": validation,
        "artifacts": {
            name: hashlib.sha256(value).hexdigest() for name, value in files.items()
        },
    }
    files["SUMMARY.json"] = _json_bytes(summary)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".rdf-ontology-", dir=output.parent
    ) as directory:
        staging = Path(directory) / "artifacts"
        staging.mkdir()
        for name, content in files.items():
            (staging / name).write_bytes(content)
        _check_output(output)
        staging.rename(output)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rdf", required=True, type=Path, help="Inline RDF file; no URL fetching"
    )
    parser.add_argument("--rdf-format", choices=("turtle", "nt"), default="turtle")
    parser.add_argument(
        "--graph",
        type=Path,
        help="Matching candidate process graph for Explorer concept references",
    )
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--source-id")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--base-uri", required=True)
    parser.add_argument(
        "--process-base-uri",
        help="Defaults to the candidate graph namespace when supplied",
    )
    parser.add_argument("--name")
    parser.add_argument("--max-tokens", type=int)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--config", type=Path)
    mode.add_argument("--replay", type=Path)
    args = parser.parse_args(argv)
    if args.max_tokens is not None and (args.max_tokens <= 0 or args.replay):
        parser.error("--max-tokens must be positive and requires --config")
    if args.graph and not args.source_id:
        parser.error("--graph requires --source-id for Explorer bindings")
    try:
        summary = run(args)
    except ExportError as error:
        print(str(error), file=sys.stderr)
        return 2
    except Exception:
        print(
            "RDF ontology generation or validation failed; no artifacts were published.",
            file=sys.stderr,
        )
        return 2
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
