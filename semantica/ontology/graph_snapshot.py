"""Compare the semantic fields represented by a process RDF projection."""

import hashlib
import json


def graph_snapshot_digest(nodes, edges, base_uri):
    """Ignore layout and edge IDs/weights, which are absent from instance RDF."""
    records = []
    for node in nodes:
        label = node.get("content", node.get("label", ""))
        records.append(
            {
                "id": node["id"],
                "type": node["type"],
                "label": label,
                "properties": {"content": label, **node.get("properties", {})},
            }
        )
    relations = sorted(
        {
            (
                edge.get("source_id", edge.get("source")),
                edge["type"],
                edge.get("target_id", edge.get("target")),
            )
            for edge in edges
        }
    )
    payload = {
        "base_uri": base_uri,
        "nodes": sorted(records, key=lambda node: node["id"]),
        "edges": relations,
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def build_graph_snapshot(graph, rdf_sha256):
    return {
        "node_ids": sorted(node["id"] for node in graph["nodes"]),
        "base_uri": graph["metadata"]["base_uri"],
        "sha256": graph_snapshot_digest(
            graph["nodes"], graph["edges"], graph["metadata"]["base_uri"]
        ),
        "rdf_sha256": rdf_sha256,
    }
