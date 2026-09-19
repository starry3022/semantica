"""Preserve anonymous property domains/ranges without inventing named edges.

Only a plain union of named terms is projected as an interpretable expression.
Other expressions retain their reachable RDF, including the original property
declaration. Limits reject the projection rather than return a partial payload.
"""

import json
from typing import Any

from rdflib import BNode, Graph, OWL, RDF, RDFS, URIRef
from rdflib.term import Node

MAX_EXPRESSION_NODES = 256
MAX_EXPRESSION_TRIPLES = 2048
MAX_EXPRESSION_BYTES = 256 * 1024
MAX_EXPRESSIONS_PER_SIDE = 64
_LIST_LINKS = {OWL.unionOf, OWL.intersectionOf, OWL.oneOf, RDF.rest}


def _expression_graph(
    graph: Graph, subject: Node, predicate: URIRef, root: BNode
) -> tuple[Graph, str]:
    """Copy the anonymous closure, following named RDF list cells as well."""
    result = Graph()
    result.add((subject, predicate, root))
    pending: list[Node] = [root]
    visited: set[Node] = set()
    while pending:
        node = pending.pop()
        if node in visited:
            continue
        visited.add(node)
        if len(visited) > MAX_EXPRESSION_NODES:
            raise ValueError("Anonymous ontology expression exceeds the node limit.")
        for triple in graph.triples((node, None, None)):
            result.add(triple)
            if len(result) > MAX_EXPRESSION_TRIPLES:
                raise ValueError(
                    "Anonymous ontology expression exceeds the triple limit."
                )
            _, relation, target = triple
            if isinstance(target, BNode) or (
                relation in _LIST_LINKS
                and isinstance(target, URIRef)
                and target != RDF.nil
            ):
                pending.append(target)
    # Split only NT record delimiters; Unicode line separators may be literal data.
    rdf = (
        "\n".join(sorted(result.serialize(format="nt").rstrip("\n").split("\n"))) + "\n"
    )
    if len(rdf.encode("utf-8")) > MAX_EXPRESSION_BYTES:
        raise ValueError("Anonymous ontology expression exceeds the RDF payload limit.")
    return result, rdf


def _named_union(graph: Graph, root: BNode) -> dict[str, Any]:
    heads = list(graph.objects(root, OWL.unionOf))
    if len(heads) != 1:
        raise ValueError("Only one plain owl:unionOf expression is supported.")
    for predicate, obj in graph.predicate_objects(root):
        if predicate == OWL.unionOf or (
            predicate == RDF.type
            and obj in {OWL.Class, RDFS.Class, RDFS.Datatype, OWL.DataRange}
        ):
            continue
        raise ValueError(
            "The anonymous expression has additional unsupported statements."
        )

    members = []
    current = heads[0]
    visited = set()
    while current != RDF.nil:
        if not isinstance(current, (BNode, URIRef)) or current in visited:
            raise ValueError("The owl:unionOf RDF list is malformed or cyclic.")
        visited.add(current)
        first = list(graph.objects(current, RDF.first))
        rest = list(graph.objects(current, RDF.rest))
        if len(first) != 1 or len(rest) != 1 or not isinstance(first[0], URIRef):
            raise ValueError("The owl:unionOf RDF list must contain named members.")
        for predicate, obj in graph.predicate_objects(current):
            if predicate in {RDF.first, RDF.rest} or (
                predicate == RDF.type and obj == RDF.List
            ):
                continue
            raise ValueError("The RDF list has additional unsupported statements.")
        members.append(str(first[0]))
        current = rest[0]
    if not members:
        raise ValueError("An empty owl:unionOf is preserved as an opaque expression.")
    return {"kind": "unionOf", "members": members}


def property_domain_range_expressions(graph: Graph, subject: Node) -> dict[str, Any]:
    """Return additive expression fields; leave named domain/range handling alone."""
    result = {}
    for side, predicate in (("domain", RDFS.domain), ("range", RDFS.range)):
        expressions: list[dict[str, Any]] = []
        for root in graph.objects(subject, predicate):
            if not isinstance(root, BNode):
                continue
            if len(expressions) >= MAX_EXPRESSIONS_PER_SIDE:
                raise ValueError(
                    "Anonymous ontology expression count exceeds the limit."
                )
            expression_graph, rdf = _expression_graph(graph, subject, predicate, root)
            try:
                expression = _named_union(expression_graph, root)
            except ValueError as exc:
                expression = {
                    "kind": "unsupported",
                    "reason": str(exc),
                    "rdf_format": "nt",
                    "rdf": rdf,
                    "root": root.n3(),
                }
            expressions.append(expression)
        if expressions:
            result[f"{side}_expressions"] = sorted(
                expressions, key=lambda item: json.dumps(item, sort_keys=True)
            )
    return result
