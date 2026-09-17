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

# Labels describe the fixed representation vocabulary, not inferred business types.
_VOCABULARY_ANNOTATIONS = {
    "en": {
        "Ontology": (
            "Process evidence vocabulary",
            "A fixed support vocabulary for candidate process rules and their evidence; "
            "not a business ontology inferred from source text or policy approval.",
        ),
        "ProcessRule": (
            "Process rule",
            "A candidate normative rule, not an observed business event or approved policy.",
        ),
        "Activity": (
            "Activity",
            "A named process activity referenced by a rule, not a record of its execution.",
        ),
        "Role": (
            "Organizational role",
            "A named actor, recipient or approval role; it does not identify a specific person.",
        ),
        "ApprovalGroup": (
            "Approval group",
            "The approval roles and all-or-any requirement attached to a candidate rule.",
        ),
        "Condition": (
            "Applicability condition",
            "A prerequisite for a rule, optionally expressed with numeric bounds.",
        ),
        "RequiredDocument": (
            "Required material",
            "A document or material required by a rule, distinct from the rule's source document.",
        ),
        "RelativeDeadline": (
            "Relative deadline",
            "A time requirement measured relative to a stated event or reference point.",
        ),
        "Evidence": (
            "Source evidence",
            "An exact source quotation and its location supporting a candidate rule; "
            "alignment does not imply business approval.",
        ),
        "SourceDocument": (
            "Source document",
            "The identity, content hash and character count of the material from which rules were extracted.",
        ),
        "hasActivity": (
            "Has activity",
            "Links a candidate rule to the activity it describes.",
        ),
        "hasActor": (
            "Has actor role",
            "Links a candidate rule to a role responsible for its action.",
        ),
        "hasRecipient": (
            "Has recipient role",
            "Links a candidate rule to a role receiving its request or action.",
        ),
        "hasCondition": (
            "Has condition",
            "Links a candidate rule to an applicability condition.",
        ),
        "hasApprovalGroup": (
            "Has approval group",
            "Links a candidate rule to its set of approval requirements.",
        ),
        "hasRole": (
            "Has approval role",
            "Links an approval group to one of its required roles.",
        ),
        "requiresDocument": (
            "Requires material",
            "Links a candidate rule to a document or material it requires.",
        ),
        "hasDeadline": (
            "Has deadline",
            "Links a candidate rule to its relative time requirement.",
        ),
        "hasEvidence": (
            "Has source evidence",
            "Links a candidate rule to an exact quotation supporting it.",
        ),
        "fromSource": (
            "Quoted from source",
            "Links evidence to the source document containing its quotation.",
        ),
        "definedIn": (
            "Defined in source",
            "Links a candidate rule to the source document from which it was extracted.",
        ),
        "rule_id": (
            "Rule identifier",
            "The extraction identifier of a candidate rule or the rule supported by evidence.",
        ),
        "source_clause_id": (
            "Primary clause identifier",
            "The identifier of the primary source clause defining a candidate rule.",
        ),
        "action": (
            "Required or permitted action",
            "The action expressed by the rule, interpreted together with its modality.",
        ),
        "modality": (
            "Requirement modality",
            "Whether the candidate rule expresses an obligation, permission or prohibition.",
        ),
        "condition_logic": (
            "Condition combination",
            "Whether all or any of the rule's conditions must hold.",
        ),
        "confidence": (
            "Extraction confidence",
            "The extractor's confidence score; it is not evidence of business review or approval.",
        ),
        "rule_data": (
            "Complete rule data",
            "The complete candidate rule as JSON, retained for lossless reconstruction.",
        ),
        "supporting_clause_ids": (
            "Supporting clause identifiers",
            "A JSON list of additional clauses supporting the rule or its inherited requirements.",
        ),
        "name": (
            "Name",
            "The source-derived name of an activity, organizational role or required material.",
        ),
        "text": (
            "Requirement text",
            "The text expressing an applicability condition or relative deadline.",
        ),
        "field": (
            "Measured field",
            "The quantity constrained by a numeric condition, such as a purchase amount.",
        ),
        "lower": (
            "Lower bound",
            "The exact numeric lower bound; inclusion is specified separately.",
        ),
        "upper": (
            "Upper bound",
            "The exact numeric upper bound; inclusion is specified separately.",
        ),
        "lower_inclusive": (
            "Includes lower bound",
            "Whether the numeric interval includes its lower bound.",
        ),
        "upper_inclusive": (
            "Includes upper bound",
            "Whether the numeric interval includes its upper bound.",
        ),
        "unit": (
            "Measurement unit",
            "The unit of a numeric condition or relative deadline.",
        ),
        "mode": (
            "Approval combination",
            "Whether all or any roles in the approval group are required; this does not define their order.",
        ),
        "value": (
            "Deadline amount",
            "The integer number of time units in a relative deadline.",
        ),
        "anchor": (
            "Deadline reference point",
            "The stated event or reference point from which a relative deadline is measured.",
        ),
        "relation": (
            "Deadline direction",
            "Whether the relative deadline is before or after its reference point.",
        ),
        "clause_id": (
            "Evidence clause identifier",
            "The identifier of the source clause containing the evidence quotation.",
        ),
        "quote": (
            "Exact quotation",
            "The verbatim source text supporting a candidate rule, without normalization.",
        ),
        "start_char": (
            "Evidence start offset",
            "The 0-based, inclusive Unicode code point offset of the quotation in "
            "the full source; [start_char, end_char) uses code points, not UTF-16 "
            "code units or bytes. This is technical metadata, not a business category.",
        ),
        "end_char": (
            "Evidence end offset",
            "The 0-based, exclusive Unicode code point offset of the quotation in "
            "the full source; [start_char, end_char) uses code points, not UTF-16 "
            "code units or bytes. This is technical metadata, not a business category.",
        ),
        "source_id": (
            "Source identifier",
            "The registered identity of the material, also recorded on its evidence.",
        ),
        "source_sha256": (
            "Source SHA-256",
            "The SHA-256 digest of the source's UTF-8 bytes, binding evidence to the exact material content.",
        ),
        "text_length": (
            "Source character count",
            "The full source length in Unicode code points, not UTF-16 code units or bytes.",
        ),
        "fact_status": (
            "Knowledge status",
            "The candidate status of extracted knowledge; structural validity does not make it verified policy.",
        ),
        "review_status": (
            "Business review status",
            "The business review status, initially unreviewed; successful evidence alignment does not change it.",
        ),
    },
    "zh": {
        "Ontology": (
            "流程与证据支持词汇",
            "用于表示候选流程规则及其证据的固定支持词汇；不是从材料推导的业务本体，也不表示制度已经审核。",
        ),
        "ProcessRule": ("流程规则", "从材料抽取的候选规范性规则，不是已发生的业务事件或已经审核的制度。"),
        "Activity": ("流程活动", "规则所描述的具名流程活动，不代表该活动已经实际执行。"),
        "Role": ("组织角色", "规则中的执行、接收或审批角色名称，不代表某个具体人员。"),
        "ApprovalGroup": ("审批组", "候选规则要求的审批角色集合及其全部或任一满足方式。"),
        "Condition": ("适用条件", "规则适用的前提条件，可包含数值范围及其边界。"),
        "RequiredDocument": ("所需材料", "规则要求提供的文档或材料，与承载规则原文的来源文档不同。"),
        "RelativeDeadline": ("相对期限", "以指定事件或时间参照点为基准表达的期限要求。"),
        "Evidence": ("原文证据", "支持候选规则的逐字原文及其定位信息；引用对齐不代表业务审核通过。"),
        "SourceDocument": ("来源文档", "规则抽取所依据材料的身份、内容哈希与字符长度。"),
        "hasActivity": ("关联活动", "将候选规则关联到其所描述的流程活动。"),
        "hasActor": ("执行角色", "将候选规则关联到负责执行其动作的组织角色。"),
        "hasRecipient": ("接收角色", "将候选规则关联到接收其申请或动作的组织角色。"),
        "hasCondition": ("适用条件", "将候选规则关联到决定其是否适用的前提条件。"),
        "hasApprovalGroup": ("所需审批组", "将候选规则关联到其要求的审批角色集合。"),
        "hasRole": ("审批角色", "将审批组关联到该组包含的一个审批角色。"),
        "requiresDocument": ("要求材料", "将候选规则关联到其要求提供的文档或材料。"),
        "hasDeadline": ("期限要求", "将候选规则关联到其要求满足的相对期限。"),
        "hasEvidence": ("支持证据", "将候选规则关联到支持该规则的逐字原文引用。"),
        "fromSource": ("引用来源", "将原文证据关联到包含该引用的来源文档。"),
        "definedIn": ("规则来源", "将候选规则关联到抽取该规则时依据的来源文档。"),
        "rule_id": ("规则标识", "候选规则的抽取标识，也用于记录证据所支持的规则。"),
        "source_clause_id": ("主条款标识", "定义候选规则的主要原文条款所使用的标识。"),
        "action": ("要求或允许的动作", "规则所描述的动作，其要求方式由规范语气共同确定。"),
        "modality": ("规范语气", "标明候选规则表达的是义务、许可还是禁止要求。"),
        "condition_logic": ("条件组合方式", "标明规则的适用条件需要全部满足还是满足任一项。"),
        "confidence": ("抽取置信度", "抽取器给出的置信度分数，不代表业务审核或制度批准。"),
        "rule_data": ("完整规则数据", "以 JSON 保存的完整候选规则，用于无损恢复抽取结果。"),
        "supporting_clause_ids": ("支持条款标识", "以 JSON 列表保存的额外条款标识，用于支持规则或其继承的要求。"),
        "name": ("名称", "来源于材料的流程活动、组织角色或所需材料名称。"),
        "text": ("要求原文", "表达规则适用条件或相对期限要求的文本。"),
        "field": ("约束字段", "数值条件所约束的量，例如采购金额或单笔付款金额。"),
        "lower": ("数值下界", "精确的数值范围下界，是否包含该边界由独立字段指定。"),
        "upper": ("数值上界", "精确的数值范围上界，是否包含该边界由独立字段指定。"),
        "lower_inclusive": ("包含下界", "标明数值范围是否包含其下界对应的数值。"),
        "upper_inclusive": ("包含上界", "标明数值范围是否包含其上界对应的数值。"),
        "unit": ("计量单位", "数值适用条件或相对期限所采用的计量单位。"),
        "mode": ("审批组合方式", "标明审批组要求全部角色还是任一角色审批，不表示审批先后顺序。"),
        "value": ("期限数值", "相对期限中的整数时间单位数量，需结合计量单位读取。"),
        "anchor": ("期限参照点", "计算相对期限时所依据的事件或时间参照点。"),
        "relation": ("期限方向", "标明相对期限位于其参照点之前还是之后。"),
        "clause_id": ("证据条款标识", "包含该原文证据引用的来源条款所使用的标识。"),
        "quote": ("逐字引用", "用于支持候选规则的原文片段，保留原始文字且不做归一化。"),
        "start_char": (
            "证据起始位置",
            "引用在完整原文中从 0 开始计数、包含起点的 Unicode 码点偏移。"
            "区间 [start_char, end_char) 按码点计数，不按 UTF-16 代码单元或字节计数。"
            "这是定位引用的技术元数据，不是业务类别。",
        ),
        "end_char": (
            "证据结束位置",
            "引用在完整原文中从 0 开始计数、不包含终点的 Unicode 码点偏移。"
            "区间 [start_char, end_char) 按码点计数，不按 UTF-16 代码单元或字节计数。"
            "这是定位引用的技术元数据，不是业务类别。",
        ),
        "source_id": ("来源标识", "已注册材料的身份标识，同样记录在该材料的证据上。"),
        "source_sha256": ("来源 SHA-256", "原文 UTF-8 字节的 SHA-256 摘要，将证据绑定到精确的材料内容。"),
        "text_length": ("原文字符长度", "完整原文的 Unicode 码点数量，不是 UTF-16 代码单元数量或字节数。"),
        "fact_status": ("知识状态", "抽取知识的候选状态；结构校验通过不代表其成为已核实制度。"),
        "review_status": ("业务审核状态", "业务审核状态，初始为未审核；引用定位对齐成功不会改变该状态。"),
    },
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


def process_rule_ontology(base_uri=DEFAULT_BASE, *, label_language="en"):
    """Return the fixed support vocabulary with English or Chinese annotations.

    Labels and comments describe the representation shared by projection and
    validation; selecting a language never changes its IRIs or RDF constraints.
    """
    if label_language not in _VOCABULARY_ANNOTATIONS:
        raise ValueError("label_language must be 'en' or 'zh'")
    ns = Namespace(_base_uri(base_uri))
    graph = Graph()
    graph.bind("process", ns)
    graph.add((ns.Ontology, RDF.type, OWL.Ontology))
    for kind in CLASSES:
        graph.add((ns[kind], RDF.type, OWL.Class))
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
    for name, (label, comment) in _VOCABULARY_ANNOTATIONS[label_language].items():
        graph.add((ns[name], RDFS.label, Literal(label, lang=label_language)))
        graph.add((ns[name], RDFS.comment, Literal(comment, lang=label_language)))
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
