"""Portable Explorer projection of native candidate facts and one ontology draft.

The base RDF is authoritative. Version 2 displays its qualified assertions through
a separate business projection; version 1 retains its original metadata overlay.
Neither representation implies business approval. Bundle paths are not HTTP routes.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from rdflib import BNode, Literal, RDF, URIRef

from ..export.rdf_exporter import RDFExporter, SEMANTICA_NS
from ..ontology.candidate_statements import REPRESENTATION, prepare_candidate_statements
from ..ontology.rdf_input import prepare_rdf_input
from ..utils.exceptions import ValidationError


_REQUIRED_FILES = {
    "base.ttl",
    "ontology.json",
    "facts.json",
    "source-manifest.json",
    "candidate-graph.json",
}
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MAX_FILE_BYTES = 20 * 1024 * 1024
_MAX_BUNDLE_BYTES = 50 * 1024 * 1024
_STATUS = {"fact_status": "candidate", "review_status": "unreviewed"}


def _json_bytes(value) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _viewer_id(kind: str, value) -> str:
    return (
        "urn:semantica:viewer:"
        + kind
        + ":"
        + hashlib.sha256(_json_bytes(value)).hexdigest()
    )


def _safe_file(root: Path, name: str) -> Path:
    if (
        not isinstance(name, str)
        or not name
        or any(character in name for character in ("\\", ":", "\x00"))
        or Path(name).is_absolute()
        or any(part in {"..", "."} for part in name.split("/"))
        or "//" in name
    ):
        raise ValueError("Bundle paths must be relative contained file paths.")
    path = root / name
    if any(
        part.is_symlink()
        for part in [path, *path.parents]
        if part != root and part.is_relative_to(root)
    ):
        raise ValueError("Bundle paths must not contain symlinks.")
    if not path.resolve().is_relative_to(root):
        raise ValueError("Bundle file path escapes its directory.")
    return path


def _read_file(path: Path) -> bytes:
    try:
        if not path.is_file() or path.stat().st_size > _MAX_FILE_BYTES:
            raise ValueError("Bundle file is missing or exceeds the size limit.")
        return path.read_bytes()
    except OSError as error:
        raise ValueError("Cannot read a required bundle file.") from error


def _json_document(content: bytes, name: str) -> dict:
    try:
        value = json.loads(content.decode("utf-8"))
    except (ValueError, UnicodeError) as error:
        raise ValueError(f"Bundle {name} must contain valid UTF-8 JSON.") from error
    if not isinstance(value, dict):
        raise ValueError(f"Bundle {name} must contain a JSON object.")
    return value


def _validate_qualified_ontology_inputs(ontology, statements):
    bindings = {
        "input_rdf_sha256": statements.prepared.sha256,
        "input_facts_sha256": statements.facts_sha256,
        "projection_rdf_sha256": statements.projection.sha256,
    }
    metadata = ontology.get("metadata") or {}
    if any(metadata.get(key) != value for key, value in bindings.items()):
        raise ValueError(
            "Candidate ontology input bindings do not match its facts and RDF."
        )


def read_candidate_bundle(bundle_path: str | Path) -> dict[str, bytes]:
    """Read only contained, hash-verified files, returning immutable file bytes.

    ``SUMMARY.json`` contains ``files: {relative_path: sha256}``; every consumed
    artifact and registered source must be listed. The summary has no self-hash.
    Checksums establish artifact consistency, not authenticity or business truth.
    """
    from .source_resources import SourceResourceRegistry

    root = Path(bundle_path).resolve()
    if not root.is_dir():
        raise ValueError("Candidate bundle directory is missing.")
    summary_bytes = _read_file(_safe_file(root, "SUMMARY.json"))
    summary = _json_document(summary_bytes, "SUMMARY.json")
    hashes = summary.get("files")
    if not isinstance(hashes, dict) or not _REQUIRED_FILES.issubset(hashes):
        raise ValueError("Bundle manifest must list all required artifacts.")
    if "SUMMARY.json" in hashes:
        raise ValueError("Bundle manifest must not contain a summary self-hash.")
    files = {"SUMMARY.json": summary_bytes}
    total = len(summary_bytes)
    for name, digest in hashes.items():
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise ValueError("Bundle file hash must be a SHA-256 hex digest.")
        content = _read_file(_safe_file(root, name))
        total += len(content)
        if total > _MAX_BUNDLE_BYTES:
            raise ValueError("Candidate bundle exceeds the total size limit.")
        if hashlib.sha256(content).hexdigest() != digest:
            raise ValueError(f"Bundle file hash mismatch: {name}")
        files[name] = content
    manifest = _json_document(files["source-manifest.json"], "source-manifest.json")
    sources = manifest.get("sources")
    if not isinstance(sources, list):
        raise ValueError("Bundle source manifest must contain a sources list.")
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("Bundle source manifest entries must be objects.")
        name = source.get("path")
        _safe_file(root, name)
        if name not in files:
            raise ValueError("Every source path must be listed in the bundle manifest.")
        SourceResourceRegistry._validate_metadata(
            source.get("source_id"),
            **{key: source.get(key) for key in ("title", "version", "source_uri")},
        )
        try:
            files[name].decode("utf-8")
        except UnicodeError as error:
            raise ValueError("Bundle source material must be UTF-8.") from error
        declared = source.get("source_sha256") or source.get("sha256")
        if declared is not None and declared != hashlib.sha256(files[name]).hexdigest():
            raise ValueError("The source manifest hash does not match its material.")
    ontology = _json_document(files["ontology.json"], "ontology.json")
    facts = _json_document(files["facts.json"], "facts.json")
    metadata = ontology.get("metadata", {})
    generation = summary.get("generation", {})
    if not isinstance(metadata, dict) or not isinstance(generation, dict):
        raise ValueError("Bundle representation and generation must be objects.")
    version = summary.get("format_version")
    qualified = generation.get("qualified_statements")
    representation = metadata.get("representation")
    if version == "candidate-facts-bundle-v2":
        if representation != REPRESENTATION or qualified is not True:
            raise ValueError("Bundle v2 requires matching qualified representation.")
    elif version in (None, "candidate-facts-bundle-v1"):
        if representation is not None or (
            qualified is not None and qualified is not False
        ):
            raise ValueError(
                "Legacy bundle version cannot declare qualified representation."
            )
    else:
        raise ValueError("Unsupported candidate bundle version.")
    try:
        prepared = prepare_rdf_input(files["base.ttl"])
        statements = (
            prepare_candidate_statements(facts)
            if version == "candidate-facts-bundle-v2"
            else None
        )
        expected = (
            statements.prepared
            if statements is not None
            else prepare_rdf_input(RDFExporter().export_to_rdf(deepcopy(facts)))
        )
    except (ValidationError, KeyError, TypeError) as error:
        raise ValueError(
            "Bundle facts or base RDF do not match its representation."
        ) from error
    if prepared.sha256 != expected.sha256:
        raise ValueError("Bundle representation does not match facts and base RDF.")
    if statements is not None:
        _validate_qualified_ontology_inputs(ontology, statements)
    return files


def _ontology_projection(ontology: dict, graph):
    from .routes.ontology import _as_uri_list, _convert_ontology_to_graph

    if not isinstance(ontology.get("uri"), str) or not ontology["uri"]:
        raise ValueError("Candidate ontology requires an explicit IRI.")
    classes = ontology.get("classes")
    properties = ontology.get("properties")
    if not isinstance(classes, list) or not isinstance(properties, list):
        raise ValueError("Candidate ontology requires classes and properties lists.")
    for terms, observed in (
        (classes, {str(value) for value in graph.objects(None, RDF.type)}),
        (properties, {str(value) for value in graph.predicates() if value != RDF.type}),
    ):
        uris = [term.get("uri") for term in terms if isinstance(term, dict)]
        if (
            len(uris) != len(terms)
            or any(not isinstance(uri, str) for uri in uris)
            or len(set(uris)) != len(uris)
            or set(uris) != observed
        ):
            raise ValueError(
                "Candidate ontology must describe exactly the base RDF vocabulary."
            )
    translated = {
        **ontology,
        "classes": [
            {
                **term,
                "description": term.get("comment") or term.get("description", ""),
                "parents": _as_uri_list(term.get("subClassOf") or term.get("parents")),
            }
            for term in classes
        ],
        "properties": [
            {**term, "description": term.get("comment") or term.get("description", "")}
            for term in properties
        ],
    }
    return _convert_ontology_to_graph(translated)


def build_candidate_graph(
    base_rdf: str, ontology: dict, facts: dict, source_manifest: dict
) -> dict:
    """Project the exported RDF, its one draft schema and explicit citations.

    No domain types, relations or evidence are inferred from labels. Literal
    properties keep complete predicate IRIs; datatype/language lexical records
    are retained in graph metadata alongside the original RDF hash.
    """
    prepared = prepare_rdf_input(base_rdf)
    qualified = (ontology.get("metadata") or {}).get("representation") == REPRESENTATION
    statements = prepare_candidate_statements(facts) if qualified else None
    exported = (
        statements.prepared
        if statements is not None
        else prepare_rdf_input(RDFExporter().export_to_rdf(deepcopy(facts)))
    )
    if prepared.sha256 != exported.sha256:
        raise ValueError("Candidate facts do not match the supplied base RDF.")
    if statements is not None:
        _validate_qualified_ontology_inputs(ontology, statements)
    graph = statements.projection.graph if statements is not None else prepared.graph
    if any(isinstance(term, BNode) for triple in graph for term in triple):
        raise ValueError("Candidate bundle projection requires named RDF resources.")
    schema_nodes, schema_edges = _ontology_projection(ontology, graph)
    nodes = {node["id"]: deepcopy(node) for node in schema_nodes}
    if len(nodes) != len(schema_nodes):
        raise ValueError("Candidate ontology contains overlapping term identities.")
    edges: dict[str, dict] = {}
    literal_records: dict[str, dict] = {}

    def add_edge(source, predicate, target, properties=None):
        identity = _viewer_id("edge", [source, predicate, target])
        edge = edges.setdefault(
            identity,
            {
                "id": identity,
                "source": source,
                "target": target,
                "type": predicate,
                "weight": 1.0,
                "properties": dict(_STATUS),
            },
        )
        if properties:
            edge["properties"].update(properties)
        return edge

    for edge in schema_edges:
        add_edge(edge["source"], edge["type"], edge["target"], edge.get("properties"))
    for node in nodes.values():
        node.setdefault("properties", {}).update(_STATUS)
    for subject in sorted(set(graph.subjects()), key=str):
        identifier = str(subject)
        if identifier in nodes:
            raise ValueError("Candidate instance and ontology term identities overlap.")
        types = sorted(str(value) for value in graph.objects(subject, RDF.type))
        properties = {"rdf:type": types, **_STATUS}
        for predicate in sorted(set(graph.predicates(subject)), key=str):
            values = sorted(
                (
                    value
                    for value in graph.objects(subject, predicate)
                    if isinstance(value, Literal)
                ),
                key=lambda value: value.n3(),
            )
            if values:
                properties[str(predicate)] = (
                    str(values[0])
                    if len(values) == 1
                    else [str(value) for value in values]
                )
                literal_records.setdefault(identifier, {})[str(predicate)] = [
                    {
                        "value": str(value),
                        "datatype": str(value.datatype) if value.datatype else None,
                        "language": value.language,
                    }
                    for value in values
                ]
        label = properties.get(SEMANTICA_NS + "text")
        nodes[identifier] = {
            "id": identifier,
            "type": types[0] if len(types) == 1 else "entity",
            "content": label if isinstance(label, str) else identifier,
            "properties": properties,
        }
    for subject, predicate, obj in sorted(
        graph, key=lambda triple: tuple(term.n3() for term in triple)
    ):
        if isinstance(obj, Literal):
            continue
        identifier = str(obj)
        if identifier not in nodes:
            nodes[identifier] = {
                "id": identifier,
                "type": "entity",
                "content": identifier,
                "properties": dict(_STATUS),
            }
        add_edge(
            str(subject),
            "rdf:type" if predicate == RDF.type else str(predicate),
            identifier,
        )

    sources = source_manifest.get("sources", [])
    if not isinstance(sources, list) or any(
        not isinstance(source, dict) for source in sources
    ):
        raise ValueError("Source manifest requires source entries.")

    def add_source(source_id, digest):
        identifier = _viewer_id("source", [source_id, digest])
        source = next(
            (
                entry
                for entry in sources
                if entry.get("source_id") == source_id
                and (entry.get("source_sha256") or entry.get("sha256")) == digest
            ),
            {},
        )
        node = {
            "id": identifier,
            "type": "SourceDocument",
            "content": source.get("title") or source_id or "Unknown source",
            "properties": {"source_id": source_id, "source_sha256": digest, **_STATUS},
        }
        if identifier in nodes and nodes[identifier] != node:
            raise ValueError("Candidate RDF collides with a viewer source identity.")
        nodes[identifier] = node
        return identifier

    for source in sources:
        digest = source.get("source_sha256") or source.get("sha256")
        if source.get("source_id") and digest:
            add_source(source["source_id"], digest)

    def citations(record):
        metadata = record.get("metadata") or {}
        evidence = metadata.get("evidence", [])
        if not isinstance(evidence, list):
            raise ValueError("Candidate evidence must be an explicit list.")
        references = []
        for entry in evidence:
            entry = (
                deepcopy(entry)
                if isinstance(entry, dict)
                else {"invalid_evidence": entry}
            )
            identifier = _viewer_id("evidence", entry)
            node = {
                "id": identifier,
                "type": "Evidence",
                "content": entry.get("quote")
                if isinstance(entry.get("quote"), str)
                else "Invalid evidence",
                "properties": {**entry, **_STATUS},
            }
            if identifier in nodes and nodes[identifier] != node:
                raise ValueError(
                    "Candidate RDF collides with a viewer evidence identity."
                )
            nodes[identifier] = node
            if isinstance(entry.get("source_id"), str) and isinstance(
                entry.get("source_sha256"), str
            ):
                source_id = add_source(entry["source_id"], entry["source_sha256"])
                add_edge(identifier, "fromSource", source_id)
            if identifier not in references:
                references.append(identifier)
        return references

    exporter = RDFExporter()
    namespaces = exporter.serializer.namespace_manager.extract_namespaces(facts)
    iri = exporter.serializer._as_turtle_iri
    for entity in facts.get("entities", []):
        identifier = iri(entity["id"], namespaces)
        for evidence_id in citations(entity):
            add_edge(identifier, "hasEvidence", evidence_id)
    for index, relationship in enumerate(facts.get("relationships", [])):
        source = iri(
            relationship.get("source_id") or relationship.get("source"), namespaces
        )
        target = iri(
            relationship.get("target_id") or relationship.get("target"), namespaces
        )
        predicate = iri(relationship["type"], namespaces)
        if (URIRef(source), URIRef(predicate), URIRef(target)) not in graph:
            raise ValueError(
                "Candidate relationship has no matching base RDF statement."
            )
        edge = add_edge(source, predicate, target)
        references = citations(relationship)
        if references:
            edge["properties"]["evidence_ids"] = sorted(
                set(edge["properties"].get("evidence_ids", []) + references)
            )
        qualifiers = {
            key: value
            for key, value in (relationship.get("metadata") or {}).items()
            if key not in {"evidence", "fact_status", "review_status"}
        }
        # The graph edge represents a set-valued RDF statement. Keep each
        # extraction's qualifiers bound to its own citations when that same
        # statement occurs in multiple independently qualified assertions.
        assertion = {**deepcopy(qualifiers), "evidence_ids": sorted(references)}
        if statements is not None:
            assertion["assertion_id"] = statements.assertion_ids[index]
        assertions = edge["properties"].setdefault("candidate_assertions", [])
        if assertion not in assertions:
            assertions.append(assertion)
    return {
        "nodes": [nodes[key] for key in sorted(nodes)],
        "edges": [edges[key] for key in sorted(edges)],
        "metadata": {
            "input_kind": "candidate_facts",
            "input_rdf_sha256": prepared.sha256,
            "ontology_uri": ontology["uri"],
            **_STATUS,
            "rdf_literals": literal_records,
            "provenance_overlay": {
                "included_in_base_rdf": qualified,
                "description": (
                    "Business relationship edges display qualified candidate assertions from base.ttl; they are not unconditional facts. Evidence and qualifiers are included in that authoritative RDF."
                    if qualified
                    else "Evidence, source documents, candidate status and relationship qualifiers are viewer metadata; base.ttl is the exported RDF."
                ),
            },
        },
    }


def create_bundle_app(bundle_path: str | Path, *, provenance_storage_path=None):
    """Create the standard Explorer app from a verified, relocatable bundle."""
    from ..context.context_graph import ContextGraph
    from .app import create_app
    from .candidate_provenance import with_provenance_schema
    from ..ontology.candidate_provenance import validate_provenance_model
    from .routes.ontology import OntologyEntry
    from .session import GraphSession
    from .source_resources import SourceResourceRegistry

    files = read_candidate_bundle(bundle_path)
    ontology = _json_document(files["ontology.json"], "ontology.json")
    facts = _json_document(files["facts.json"], "facts.json")
    manifest = _json_document(files["source-manifest.json"], "source-manifest.json")
    projection = build_candidate_graph(
        files["base.ttl"].decode("utf-8"), ontology, facts, manifest
    )
    if (
        _json_document(files["candidate-graph.json"], "candidate-graph.json")
        != projection
    ):
        raise ValueError(
            "The candidate-graph projection does not match its bundle inputs."
        )
    provenance = None
    if "provenance-model.json" in files:
        model = _json_document(files["provenance-model.json"], "provenance-model.json")
        validate_provenance_model(model, projection, files["base.ttl"])
        projection = with_provenance_schema(projection, model)
        provenance = model["ontology"]
    resources = SourceResourceRegistry()
    for source in manifest["sources"]:
        text = files[source["path"]].decode("utf-8")
        resources.register_text(
            source.get("source_id"),
            text,
            **{key: source.get(key) for key in ("title", "version", "source_uri")},
        )
    graph = ContextGraph(advanced_analytics=False)
    graph.metadata = deepcopy(projection["metadata"])
    graph.add_nodes(projection["nodes"])
    graph.add_edges(projection["edges"])
    session = GraphSession(graph)
    app = create_app(
        session=session,
        source_resources=resources,
        provenance_storage_path=provenance_storage_path,
    )
    # Make the loaded graph available to CLI diagnostics before ASGI startup;
    # the standard app lifespan installs this same session when serving begins.
    app.state.session = session
    app.state.ontology_registry = {
        ontology["uri"]: OntologyEntry(
            uri=ontology["uri"],
            name=ontology.get("name") or "Candidate ontology",
            format="turtle",
            status="draft",
            version=ontology.get("version"),
            class_count=len(ontology["classes"]),
            property_count=len(ontology["properties"]),
        )
    }
    if provenance is not None:
        app.state.ontology_registry[provenance["uri"]] = OntologyEntry(
            uri=provenance["uri"],
            name=provenance["name"],
            format="turtle",
            status="draft",
            class_count=len(provenance["classes"]),
            property_count=len(provenance["properties"]),
            tags=["provenance"],
        )
    app.state.candidate_bundle_summary = _json_document(
        files["SUMMARY.json"], "SUMMARY.json"
    )
    return app
