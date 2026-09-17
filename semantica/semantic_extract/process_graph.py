"""Lossless graph projection for candidate process rules, not executed events.

Inputs are validated against ProcessExtractionResult, including dictionaries.
Numeric interval consistency is enforced by NumericConstraint in process_schemas;
SHACL checks graph structure, required fields, datatypes and evidence linkage.
Neither structural conformance nor model confidence constitutes policy approval.
Clause/span consistency cannot independently authenticate the original document;
source hashing and exact alignment belong to the extraction boundary.
"""

import hashlib
import json
import re
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

from rdflib import BNode, Graph, Literal, Namespace, OWL, RDF, RDFS, URIRef, XSD
from rdflib.collection import Collection

from .process_schemas import ProcessExtractionResult


DEFAULT_BASE = "https://example.org/process-rules/"
SH = Namespace("http://www.w3.org/ns/shacl#")
CLASSES = (
    "ProcessRule",
    "Activity",
    "Role",
    "ApprovalGroup",
    "Condition",
    "RequiredDocument",
    "RelativeDeadline",
    "Evidence",
    "SourceDocument",
)
OBJECT_PROPERTIES = {
    "hasActivity": ("ProcessRule", "Activity"),
    "hasActor": ("ProcessRule", "Role"),
    "hasRecipient": ("ProcessRule", "Role"),
    "hasCondition": ("ProcessRule", "Condition"),
    "hasApprovalGroup": ("ProcessRule", "ApprovalGroup"),
    "hasRole": ("ApprovalGroup", "Role"),
    "requiresDocument": ("ProcessRule", "RequiredDocument"),
    "hasDeadline": ("ProcessRule", "RelativeDeadline"),
    "hasEvidence": ("ProcessRule", "Evidence"),
    "fromSource": ("Evidence", "SourceDocument"),
    "definedIn": ("ProcessRule", "SourceDocument"),
}
NUMERIC_FIELDS = {"lower", "upper"}
DATATYPE_PROPERTIES = {
    "rule_id": (("ProcessRule", "Evidence"), XSD.string),
    "source_clause_id": (("ProcessRule",), XSD.string),
    "action": (("ProcessRule",), XSD.string),
    "modality": (("ProcessRule",), XSD.string),
    "condition_logic": (("ProcessRule",), XSD.string),
    "confidence": (("ProcessRule",), XSD.double),
    "rule_data": (("ProcessRule",), RDF.JSON),
    "supporting_clause_ids": (("ProcessRule",), RDF.JSON),
    "name": (("Activity", "Role", "RequiredDocument"), XSD.string),
    "text": (("Condition", "RelativeDeadline"), XSD.string),
    "field": (("Condition",), XSD.string),
    "lower": (("Condition",), XSD.decimal),
    "upper": (("Condition",), XSD.decimal),
    "lower_inclusive": (("Condition",), XSD.boolean),
    "upper_inclusive": (("Condition",), XSD.boolean),
    "unit": (("Condition", "RelativeDeadline"), XSD.string),
    "mode": (("ApprovalGroup",), XSD.string),
    "value": (("RelativeDeadline",), XSD.integer),
    "anchor": (("RelativeDeadline",), XSD.string),
    "relation": (("RelativeDeadline",), XSD.string),
    "clause_id": (("Evidence",), XSD.string),
    "quote": (("Evidence",), XSD.string),
    "start_char": (("Evidence",), XSD.integer),
    "end_char": (("Evidence",), XSD.integer),
    "source_id": (("SourceDocument", "Evidence"), XSD.string),
    "source_sha256": (("SourceDocument", "Evidence"), XSD.string),
    "text_length": (("SourceDocument",), XSD.integer),
    "fact_status": (CLASSES, XSD.string),
    "review_status": (CLASSES, XSD.string),
}


def _base_uri(base_uri):
    if not isinstance(base_uri, str) or re.search(r'[\s<>"{}|\\^`]', base_uri):
        raise ValueError(
            "base_uri must be an absolute IRI without forbidden characters"
        )
    if re.search(r"%(?![0-9a-fA-F]{2})", base_uri):
        raise ValueError("base_uri contains an invalid percent escape")
    parsed = urlsplit(base_uri)
    if not parsed.scheme or not base_uri.split(":", 1)[1]:
        raise ValueError("base_uri must be an absolute IRI")
    if parsed.scheme in {"http", "https"} and not parsed.netloc:
        raise ValueError("HTTP(S) base_uri requires a host")
    if parsed.query:
        raise ValueError("base_uri must not contain a query")
    return base_uri if base_uri.endswith(("/", "#", ":")) else base_uri + "/"


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def process_rules_to_graph(result, base_uri=DEFAULT_BASE):
    """Project validated normative candidates into the Explorer graph format.

    Decimal amounts remain exact strings in JSON, becoming xsd:decimal in RDF.
    Evidence offsets come exclusively from extractor-aligned evidence_spans.
    """
    base_uri = _base_uri(base_uri)
    raw = result.model_dump() if hasattr(result, "model_dump") else result
    # Revalidate a dictionary even for model inputs: existing model instances
    # may have been mutated since their initial validation.
    data = ProcessExtractionResult.model_validate(raw).model_dump(mode="json")
    source_hash = data["source_sha256"]
    if not re.fullmatch(r"[0-9a-fA-F]{64}", source_hash):
        raise ValueError("source_sha256 must be a SHA-256 hex digest")
    source_id = data["source_id"]
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}
    clauses = {clause["id"]: clause for clause in data["clauses"]}
    if len(clauses) != len(data["clauses"]):
        raise ValueError("duplicate source clause id")
    for clause in clauses.values():
        if not 0 <= clause["start_char"] < clause["end_char"] <= data[
            "text_length"
        ] or clause["end_char"] - clause["start_char"] != len(clause["text"]):
            raise ValueError("source clause has inconsistent text offsets")

    def identifier(kind, key):
        suffix = hashlib.sha256(_json([source_id, key]).encode()).hexdigest()[:24]
        return f"{base_uri}id/{source_hash}/{kind}/{suffix}"

    def node(kind, key, label, properties):
        ident = identifier(kind, key)
        nodes.setdefault(
            ident,
            {
                "id": ident,
                "type": kind,
                "label": label,
                "content": label,
                "properties": {
                    **properties,
                    "fact_status": "candidate",
                    "review_status": "unreviewed",
                },
            },
        )
        return ident

    def edge(source, predicate, target):
        ident = identifier("edge", [source, predicate, target])
        edges[ident] = {
            "id": ident,
            "source_id": source,
            "target_id": target,
            "type": predicate,
            "properties": {},
        }

    source = node(
        "SourceDocument",
        source_id,
        source_id,
        {
            "source_id": source_id,
            "source_sha256": source_hash,
            "text_length": data["text_length"],
        },
    )
    seen_rules = set()
    for rule in data["rules"]:
        rule_key = rule["id"]
        if rule_key in seen_rules:
            raise ValueError(f"duplicate process rule id: {rule_key}")
        seen_rules.add(rule_key)
        references = [rule["source_clause_id"], *rule["supporting_clause_ids"]]
        if len(references) != len(set(references)):
            raise ValueError(f"duplicate clause reference in rule {rule_key}")
        if any(clause_id not in clauses for clause_id in references):
            raise ValueError(f"rule {rule_key} references an absent source clause")
        evidence_keys = [
            (item["clause_id"], item["quote"]) for item in rule["evidence"]
        ]
        if len(evidence_keys) != len(set(evidence_keys)):
            raise ValueError(f"duplicate evidence in rule {rule_key}")
        cited_ids = {clause_id for clause_id, _ in evidence_keys}
        if cited_ids != set(references):
            raise ValueError(
                f"rule {rule_key} evidence must cover exactly its referenced clauses"
            )
        current = node(
            "ProcessRule",
            rule_key,
            f'{rule["activity"]} · {rule["action"]} [{rule["source_clause_id"]}]',
            {
                "rule_id": rule_key,
                "source_clause_id": rule["source_clause_id"],
                "action": rule["action"],
                "modality": rule["modality"],
                "condition_logic": rule["condition_logic"],
                "confidence": rule["confidence"],
                "supporting_clause_ids": rule["supporting_clause_ids"],
                "rule_data": rule,
            },
        )
        edge(current, "definedIn", source)
        activity = node(
            "Activity", rule["activity"], rule["activity"], {"name": rule["activity"]}
        )
        edge(current, "hasActivity", activity)
        for actor in rule["actors"]:
            edge(current, "hasActor", node("Role", actor, actor, {"name": actor}))
        for role in rule.get("recipient_roles", []):
            edge(current, "hasRecipient", node("Role", role, role, {"name": role}))
        for index, condition in enumerate(rule["conditions"]):
            properties = {"text": condition["text"], **(condition.get("numeric") or {})}
            target = node("Condition", [rule_key, index], condition["text"], properties)
            edge(current, "hasCondition", target)
        approval = rule.get("approvals")
        if approval:
            group = node(
                "ApprovalGroup",
                rule_key,
                "审批组 (" + approval["mode"] + ")",
                {"mode": approval["mode"]},
            )
            edge(current, "hasApprovalGroup", group)
            for role in approval["roles"]:
                edge(group, "hasRole", node("Role", role, role, {"name": role}))
        for document in rule["required_documents"]:
            target = node("RequiredDocument", document, document, {"name": document})
            edge(current, "requiresDocument", target)
        if rule.get("deadline"):
            deadline = rule["deadline"]
            target = node("RelativeDeadline", rule_key, deadline["text"], deadline)
            edge(current, "hasDeadline", target)
        if not rule["evidence"]:
            raise ValueError(f"rule {rule_key} has no evidence")
        for evidence in rule["evidence"]:
            spans = [
                span
                for span in data["evidence_spans"]
                if span["rule_id"] == rule_key
                and span["clause_id"] == evidence["clause_id"]
                and span["quote"] == evidence["quote"]
            ]
            if not spans:
                raise ValueError(f"rule {rule_key} evidence has no aligned source span")
            for span in spans:
                start, end = span["start_char"], span["end_char"]
                if (
                    type(start) is not int
                    or type(end) is not int
                    or not 0 <= start < end <= data["text_length"]
                    or end - start != len(span["quote"])
                ):
                    raise ValueError("invalid aligned evidence offsets")
                clause = clauses.get(span["clause_id"])
                if clause is None:
                    raise ValueError("evidence references an absent source clause")
                local_start = start - clause["start_char"]
                local_end = end - clause["start_char"]
                if (
                    not 0 <= local_start < local_end <= len(clause["text"])
                    or clause["text"][local_start:local_end] != span["quote"]
                ):
                    raise ValueError(
                        "evidence quote does not match source clause offsets"
                    )
                target = node(
                    "Evidence",
                    [rule_key, span["clause_id"], start, end],
                    span["quote"],
                    {**span, "source_id": source_id, "source_sha256": source_hash},
                )
                edge(current, "hasEvidence", target)
                edge(target, "fromSource", source)
    return {
        "nodes": list(nodes.values()),
        "edges": list(edges.values()),
        "metadata": {
            "base_uri": base_uri,
            "source_id": source_id,
            "source_sha256": source_hash,
            "coverage": data["coverage"],
            "fact_status": "candidate",
            "review_status": "unreviewed",
            "semantics": "normative process candidates; not observed execution events",
        },
    }


def export_process_rdf(graph):
    """Export every node property, including lossless rule JSON, as Turtle."""
    ns = Namespace(_base_uri(graph["metadata"]["base_uri"]))
    rdf = Graph()
    rdf.bind("process", ns)
    node_ids = {node["id"] for node in graph["nodes"]}
    for node in graph["nodes"]:
        subject = URIRef(node["id"])
        rdf.add((subject, RDF.type, ns[node["type"]]))
        rdf.add((subject, RDFS.label, Literal(node["label"], datatype=XSD.string)))
        for key, value in node["properties"].items():
            if value is None:
                continue
            if isinstance(value, (dict, list)):
                literal = Literal(_json(value), datatype=RDF.JSON)
            elif key in NUMERIC_FIELDS:
                literal = Literal(Decimal(str(value)), datatype=XSD.decimal)
            elif isinstance(value, str):
                literal = Literal(value, datatype=XSD.string)
            else:
                literal = Literal(value)
            rdf.add((subject, ns[key], literal))
    for edge in graph["edges"]:
        if edge["source_id"] not in node_ids or edge["target_id"] not in node_ids:
            raise ValueError("graph edge references an absent node")
        rdf.add(
            (URIRef(edge["source_id"]), ns[edge["type"]], URIRef(edge["target_id"]))
        )
    return rdf.serialize(format="turtle")


def process_rule_ontology(base_uri=DEFAULT_BASE):
    """Return the explicit vocabulary shared by projection and validation."""
    ns = Namespace(_base_uri(base_uri))
    graph = Graph()
    graph.bind("process", ns)
    graph.add((ns.Ontology, RDF.type, OWL.Ontology))
    graph.add((ns.Ontology, RDFS.label, Literal("Process Rule Ontology")))
    graph.add(
        (
            ns.Ontology,
            RDFS.comment,
            Literal(
                "Candidate normative process rules; not verified policy or business events."
            ),
        )
    )
    for kind in CLASSES:
        graph.add((ns[kind], RDF.type, OWL.Class))
        graph.add((ns[kind], RDFS.label, Literal(kind)))
    for name, (domain, range_) in OBJECT_PROPERTIES.items():
        graph.add((ns[name], RDF.type, OWL.ObjectProperty))
        graph.add((ns[name], RDFS.domain, ns[domain]))
        graph.add((ns[name], RDFS.range, ns[range_]))
    for name, (domains, datatype) in DATATYPE_PROPERTIES.items():
        graph.add((ns[name], RDF.type, OWL.DatatypeProperty))
        graph.add((ns[name], RDFS.range, datatype))
        domain = ns[domains[0]]
        if len(domains) > 1:
            domain, members = BNode(), BNode()
            graph.add((domain, RDF.type, OWL.Class))
            graph.add((domain, OWL.unionOf, members))
            Collection(graph, members, [ns[kind] for kind in domains])
        graph.add((ns[name], RDFS.domain, domain))
    return graph


def process_rule_shapes(base_uri=DEFAULT_BASE):
    """Structural SHACL with property constraints and nonempty focus classes."""
    ns = Namespace(_base_uri(base_uri))
    graph = Graph()
    graph.bind("process", ns)
    graph.bind("sh", SH)
    for kind in CLASSES:
        graph.add((ns[kind + "Shape"], RDF.type, SH.NodeShape))
        graph.add((ns[kind + "Shape"], SH.targetClass, ns[kind]))

    def prop(
        kind,
        name,
        *,
        minimum=0,
        maximum=1,
        datatype=None,
        target=None,
        choices=None,
        positive=False,
        nonnegative=False,
        less_than=None,
    ):
        shape = ns[kind + "_" + name + "Shape"]
        graph.add((ns[kind + "Shape"], SH.property, shape))
        graph.add((shape, RDF.type, SH.PropertyShape))
        graph.add((shape, SH.path, ns[name]))
        graph.add((shape, SH.minCount, Literal(minimum)))
        if maximum is not None:
            graph.add((shape, SH.maxCount, Literal(maximum)))
        if datatype:
            graph.add((shape, SH.datatype, datatype))
            if datatype == XSD.string:
                graph.add((shape, SH.minLength, Literal(1)))
        if target:
            graph.add((shape, SH.nodeKind, SH.IRI))
            graph.add((shape, SH["class"], ns[target]))
        if choices:
            values = BNode()
            Collection(
                graph, values, [Literal(value, datatype=datatype) for value in choices]
            )
            graph.add((shape, SH["in"], values))
        if positive:
            graph.add((shape, SH.minExclusive, Literal(0)))
        if nonnegative:
            graph.add((shape, SH.minInclusive, Literal(0)))
        if less_than:
            graph.add((shape, SH.lessThan, ns[less_than]))

    for kind in CLASSES:
        prop(kind, "fact_status", minimum=1, datatype=XSD.string, choices=["candidate"])
        prop(
            kind,
            "review_status",
            minimum=1,
            datatype=XSD.string,
            choices=["unreviewed"],
        )
    for kind in ("Activity", "Role", "RequiredDocument"):
        prop(kind, "name", minimum=1, datatype=XSD.string)
    prop("ProcessRule", "hasActivity", minimum=1, target="Activity")
    prop("ProcessRule", "definedIn", minimum=1, target="SourceDocument")
    prop("ProcessRule", "hasEvidence", minimum=1, maximum=None, target="Evidence")
    prop("ProcessRule", "hasActor", maximum=None, target="Role")
    prop("ProcessRule", "hasRecipient", maximum=None, target="Role")
    prop("ProcessRule", "hasCondition", maximum=None, target="Condition")
    prop("ProcessRule", "hasApprovalGroup", target="ApprovalGroup")
    prop("ProcessRule", "hasDeadline", target="RelativeDeadline")
    prop("ProcessRule", "requiresDocument", maximum=None, target="RequiredDocument")
    prop(
        "ProcessRule",
        "modality",
        minimum=1,
        datatype=XSD.string,
        choices=["obligation", "permission", "prohibition"],
    )
    prop(
        "ProcessRule",
        "condition_logic",
        minimum=1,
        datatype=XSD.string,
        choices=["all", "any"],
    )
    prop("ProcessRule", "action", minimum=1, datatype=XSD.string)
    prop("ProcessRule", "rule_data", minimum=1, datatype=RDF.JSON)
    prop(
        "ApprovalGroup", "mode", minimum=1, datatype=XSD.string, choices=["all", "any"]
    )
    prop("ApprovalGroup", "hasRole", minimum=1, maximum=None, target="Role")
    prop("Condition", "text", minimum=1, datatype=XSD.string)
    prop("Condition", "field", datatype=XSD.string)
    prop("Condition", "unit", datatype=XSD.string)
    for field in ("lower", "upper"):
        prop("Condition", field, datatype=XSD.decimal)
    for field in ("lower_inclusive", "upper_inclusive"):
        prop("Condition", field, datatype=XSD.boolean)
    # A condition is either textual only or a complete numeric constraint.
    # Counts in these branches supplement the datatype checks above.
    textual, numeric = BNode(), BNode()
    alternatives = BNode()
    Collection(graph, alternatives, [textual, numeric])
    graph.add((ns.ConditionShape, SH["or"], alternatives))

    def counts(parent, fields, minimum, maximum):
        graph.add((parent, RDF.type, SH.NodeShape))
        for field in fields:
            shape = BNode()
            graph.add((parent, SH.property, shape))
            graph.add((shape, RDF.type, SH.PropertyShape))
            graph.add((shape, SH.path, ns[field]))
            graph.add((shape, SH.minCount, Literal(minimum)))
            graph.add((shape, SH.maxCount, Literal(maximum)))

    required_numeric = ("field", "unit", "lower_inclusive", "upper_inclusive")
    counts(textual, (*required_numeric, "lower", "upper"), 0, 0)
    counts(numeric, required_numeric, 1, 1)
    bounded_below, bounded_above, bounds = BNode(), BNode(), BNode()
    counts(bounded_below, ("lower",), 1, 1)
    counts(bounded_above, ("upper",), 1, 1)
    Collection(graph, bounds, [bounded_below, bounded_above])
    graph.add((numeric, SH["or"], bounds))

    prop("RelativeDeadline", "value", minimum=1, datatype=XSD.integer, positive=True)
    prop(
        "RelativeDeadline",
        "unit",
        minimum=1,
        datatype=XSD.string,
        choices=["working_day", "calendar_day", "hour", "minute", "month", "year"],
    )
    prop("RelativeDeadline", "anchor", minimum=1, datatype=XSD.string)
    prop(
        "RelativeDeadline",
        "relation",
        minimum=1,
        datatype=XSD.string,
        choices=["after", "before"],
    )
    prop("Evidence", "quote", minimum=1, datatype=XSD.string)
    prop("Evidence", "clause_id", minimum=1, datatype=XSD.string)
    prop(
        "Evidence",
        "start_char",
        minimum=1,
        datatype=XSD.integer,
        nonnegative=True,
        less_than="end_char",
    )
    prop("Evidence", "end_char", minimum=1, datatype=XSD.integer, positive=True)
    prop("Evidence", "fromSource", minimum=1, target="SourceDocument")
    for kind in ("Evidence", "SourceDocument"):
        prop(kind, "source_id", minimum=1, datatype=XSD.string)
        prop(kind, "source_sha256", minimum=1, datatype=XSD.string)
    prop(
        "SourceDocument", "text_length", minimum=1, datatype=XSD.integer, positive=True
    )

    for kind, message, query in (
        (
            "Evidence",
            "Evidence source identity must match its linked source document.",
            f"""
            SELECT $this WHERE {{
                $this <{ns.source_id}> ?evidenceId ;
                      <{ns.source_sha256}> ?evidenceHash ; <{ns.fromSource}> ?source .
                ?source <{ns.source_id}> ?sourceId ; <{ns.source_sha256}> ?sourceHash .
                FILTER (?evidenceId != ?sourceId || ?evidenceHash != ?sourceHash)
            }}
        """,
        ),
        (
            "Condition",
            "Numeric interval must be ordered and nonempty.",
            f"""
            SELECT $this WHERE {{
                $this <{ns['lower']}> ?lower ; <{ns['upper']}> ?upper ;
                      <{ns.lower_inclusive}> ?lowerInclusive ;
                      <{ns.upper_inclusive}> ?upperInclusive .
                FILTER (?lower > ?upper ||
                    (?lower = ?upper && (!?lowerInclusive || !?upperInclusive)))
            }}
        """,
        ),
        (
            "Evidence",
            "Evidence span must fit its source and match the quote length.",
            f"""
            SELECT $this WHERE {{
                $this <{ns.start_char}> ?start ; <{ns.end_char}> ?end ;
                      <{ns.quote}> ?quote ; <{ns.fromSource}> ?source .
                ?source <{ns.text_length}> ?sourceLength .
                FILTER (?end > ?sourceLength || (?end - ?start) != STRLEN(?quote))
            }}
        """,
        ),
    ):
        constraint = BNode()
        graph.add((ns[kind + "Shape"], SH.sparql, constraint))
        graph.add((constraint, RDF.type, SH.SPARQLConstraint))
        graph.add((constraint, SH.message, Literal(message)))
        graph.add((constraint, SH.select, Literal(query)))
    return graph
