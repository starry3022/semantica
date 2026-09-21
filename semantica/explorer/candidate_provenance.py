"""Load a validated LLM provenance model without synthesizing schema terms."""

from copy import deepcopy


def _matches(predicate, legacy, graph):
    bindings = graph.metadata.get("provenance_bindings", {}).get("edge_types", {})
    return predicate == legacy or predicate == bindings.get(legacy)


def is_evidence_link(predicate, graph):
    return _matches(predicate, "hasEvidence", graph)


def is_source_link(predicate, graph):
    return _matches(predicate, "fromSource", graph)


def with_provenance_schema(projection, model):
    """Apply model-supplied identities to existing nodes and edges only."""
    from .candidate_bundle import _viewer_id
    from .routes.ontology import _convert_ontology_to_graph

    result = deepcopy(projection)
    ontology = model["ontology"]
    translated = {
        **ontology,
        "classes": [
            {**term, "description": term["comment"]}
            for term in ontology["classes"]
        ],
        "properties": [
            {**term, "description": term["comment"]}
            for term in ontology["properties"]
        ],
    }
    schema_nodes, schema_edges = _convert_ontology_to_graph(translated)
    bindings = model["bindings"]
    for node in schema_nodes:
        node["properties"]["schema_role"] = "provenance"
        node["properties"]["definition_source"] = "llm"
    for node in result["nodes"]:
        uri = bindings["node_types"].get(node["type"])
        if uri:
            node["properties"]["rdf:type"] = [uri]
            schema_edges.append(
                {"source": node["id"], "type": "rdf:type", "target": uri}
            )
    for edge in result["edges"]:
        edge["type"] = bindings["edge_types"].get(edge["type"], edge["type"])
    for edge in schema_edges:
        edge["id"] = _viewer_id("edge", [edge["source"], edge["type"], edge["target"]])
    result["nodes"].extend(schema_nodes)
    result["edges"].extend(schema_edges)
    result["metadata"].update(
        provenance_schema_uri=ontology["uri"], provenance_bindings=deepcopy(bindings)
    )
    if "relationship_shapes" in model:
        owners = {node["id"]: node.get("properties", {}).get("scheme_uri") for node in result["nodes"]}
        result["metadata"]["relationship_shapes"] = [
            {**deepcopy(shape), "ontology_uri": owners.get(shape["path"]) or ontology["uri"], "schema_role": shape.get("schema_role", "provenance"), "definition_source": "llm"}
            for shape in model["relationship_shapes"]
        ]
    return result


def project_relationship_shapes(session, ontology_uri, core_node_ids):
    """Display explicit saved shapes, never infer them from instance usage.

    These edges belong to the schema response only. They are not stored as RDF
    instance statements between classes and do not mutate the source graph.
    """
    from .candidate_bundle import _viewer_id

    nodes, edges = {}, []
    for shape in session.graph.metadata.get("relationship_shapes", []):
        targets = shape.get("value_classes", [shape.get("value_class")])
        if not (shape["ontology_uri"] == ontology_uri or shape["target_class"] in core_node_ids or any(target in core_node_ids for target in targets)):
            continue
        for uri in (shape["target_class"], shape["path"], *targets):
            node = session.get_node(uri)
            if node is None:
                # This is a reference to an explicit RDF input type (for example
                # rdf:Statement), not an owned/redeclared business class.
                node = {"id": uri, "type": "external", "content": uri.rsplit("#", 1)[-1].rsplit("/", 1)[-1], "properties": {"external_reference": True}}
            nodes[uri] = node
        for target in targets:
            edges.append({
                "id": shape["uri"] if len(targets) == 1 else _viewer_id("shape", [shape["uri"], target]),
                "source": shape["target_class"], "target": target, "type": shape["path"],
                "properties": {
                    "schema_kind": "relationship_shape", "shape_uri": shape["uri"],
                    "property_uri": shape["path"], "ontology_uri": shape["ontology_uri"],
                    "label": shape["label"], "comment": shape["comment"],
                    "value_classes": targets,
                    "schema_role": shape["schema_role"], "definition_source": shape["definition_source"],
                },
            })
    properties = {edge["type"] for edge in edges}
    for predicate in ("rdfs:domain", "rdfs:range"):
        for edge in session.iter_edges(edge_type=predicate):
            if edge["source"] in properties:
                edges.append(edge)
                target = session.get_node(edge["target"])
                if target is not None:
                    nodes[target["id"]] = target
    return list(nodes.values()), edges
