"""Explicit instance typing stays separate from business evidence associations."""

from copy import deepcopy
import hashlib
import json

import pytest

pytest.importorskip("fastapi")

from starlette.testclient import TestClient  # noqa: E402
from semantica.explorer.app import create_app  # noqa: E402
from semantica.explorer.session import GraphSession  # noqa: E402
from semantica.explorer.source_resources import SourceResourceRegistry  # noqa: E402

BASE = "https://example.org/process/"
BUSINESS = "https://example.org/business/"
RULE_CLASS = BASE + "ProcessRule"
BUSINESS_CLASS = BUSINESS + "PurchaseRequest"
RULE = "urn:rule:one"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
TYPES = "/api/ontology/instance-types"
INSTANCES = "/api/ontology/class-instances"


@pytest.fixture
def scene(tmp_path):
    path = tmp_path / "candidate-graph.json"
    path.write_text(
        json.dumps(
            {
                "metadata": {"base_uri": BASE},
                "nodes": [
                    {
                        "id": RULE,
                        "type": "ProcessRule",
                        "label": "采购审批规则",
                        "properties": {
                            "fact_status": "candidate",
                            "review_status": "unreviewed",
                        },
                    }
                ],
                "edges": [],
            }
        )
    )
    session = GraphSession.from_file(str(path))
    graph = session.graph
    graph.add_node(BASE, "owl:Ontology", "流程与证据支持词汇")
    graph.add_node(RULE_CLASS, "owl:Class", "流程规则", scheme_uri=BASE)
    graph.add_node(BUSINESS_CLASS, "owl:Class", "采购申请", scheme_uri=BUSINESS)
    with TestClient(create_app(session=session)) as client:
        yield client, graph, session


def read_types(scene, node_id=RULE):
    response = scene[0].get(TYPES, params={"node_id": node_id})
    assert response.status_code == 200, response.text
    return response.json()


def test_property_definitions_use_exact_predicate_identity_and_do_not_mutate_facts(
    scene,
):
    graph = scene[1]
    graph.nodes[RULE].properties["name"] = "财务负责人"
    graph.add_node(BASE + "name", "owl:DatatypeProperty", "名称", scheme_uri=BASE)
    graph.add_node(
        BUSINESS + "name", "owl:DatatypeProperty", "业务名称", scheme_uri=BUSINESS
    )
    graph.add_node(
        BASE + "fact_status", "owl:DatatypeProperty", "知识状态", scheme_uri=BASE
    )
    before = deepcopy(graph.to_dict())
    definitions = {row["key"]: row for row in read_types(scene)["property_definitions"]}
    assert definitions["name"] == {
        "key": "name",
        "property_uri": BASE + "name",
        "label": "名称",
        "loaded": True,
        "ontology_uri": BASE,
    }
    assert definitions["fact_status"]["label"] == "知识状态"
    assert definitions["review_status"]["loaded"] is False
    assert graph.to_dict() == before
    graph.nodes[BASE + "name"].content = "角色名称"
    assert (
        next(
            row
            for row in read_types(scene)["property_definitions"]
            if row["key"] == "name"
        )["label"]
        == "角色名称"
    )


def test_property_iris_resolve_without_namespace_but_local_fields_never_guess(scene):
    graph = scene[1]
    graph.metadata = {}
    graph.nodes[RULE].properties[BUSINESS + "name"] = "财务负责人"
    graph.nodes[RULE].properties["name"] = "财务负责人"
    graph.add_node(
        BUSINESS + "name", "owl:DatatypeProperty", "业务名称", scheme_uri=BUSINESS
    )
    definitions = {row["key"]: row for row in read_types(scene)["property_definitions"]}
    assert definitions[BUSINESS + "name"]["property_uri"] == BUSINESS + "name"
    assert definitions[BUSINESS + "name"]["label"] == "业务名称"
    assert "name" not in definitions


@pytest.mark.parametrize(
    "key", ["../name", "unknown:name", "javascript:alert(1)", "bad key", "<img>"]
)
def test_invalid_or_unresolved_property_keys_cannot_borrow_a_schema_identity(
    scene, key
):
    scene[1].nodes[RULE].properties[key] = "candidate"
    assert key not in {row["key"] for row in read_types(scene)["property_definitions"]}


def test_a_class_with_the_same_iri_is_not_a_property_definition(scene):
    scene[1].add_node(BASE + "fact_status", "owl:Class", "误导标签")
    row = next(
        row
        for row in read_types(scene)["property_definitions"]
        if row["key"] == "fact_status"
    )
    assert row["loaded"] is False
    assert row["label"] == "fact_status"


def test_loaded_candidate_namespace_connects_an_instance_to_its_exact_support_class(
    scene,
):
    before = deepcopy(scene[1].to_dict())
    result = read_types(scene)
    assert result["node_id"] == RULE
    assert result["status"] == "declared"
    assert result["types"] == [
        {
            "class_uri": RULE_CLASS,
            "label": "流程规则",
            "loaded": True,
            "ontology_uri": BASE,
            "basis": [{"kind": "graph_namespace", "value": "ProcessRule"}],
        }
    ]
    assert result["related_concepts"] == []
    assert result["related_status"] == "unconfigured"
    assert result["notice"]
    assert scene[1].to_dict() == before


def test_observed_properties_use_all_explicit_instances_without_declaring_domains(
    scene,
):
    client, graph, _ = scene
    graph.metadata = {}
    graph.nodes[RULE].node_type = RULE_CLASS
    graph.nodes[RULE].properties.update(
        {BASE + "text": "财务负责人", BASE + "confidence": "0.95", "rdf:type": RULE_CLASS}
    )
    graph.add_node(
        "urn:item:second", RULE_CLASS, "另一负责人", **{BASE + "text": ["甲", "乙"]}
    )
    graph.add_node(
        "urn:item:other", BUSINESS_CLASS, "其他类型", **{BUSINESS + "exclusive": "other"}
    )
    graph.add_node(BASE + "text", "owl:DatatypeProperty", "文本", scheme_uri=BASE)
    graph.add_node(BASE + "confidence", "owl:DatatypeProperty", "置信度", scheme_uri=BASE)
    graph.add_node(BASE + "approves", "owl:ObjectProperty", "审批", scheme_uri=BASE)
    graph.add_edge(RULE, "urn:item:other", BASE + "approves", id="one")
    graph.add_edge(RULE, "urn:item:second", BASE + "approves", id="two")
    graph.add_edge("urn:item:second", "urn:item:other", BASE + "approves", id="three")
    graph.add_edge(RULE, RULE_CLASS, "rdf:type", id="type")
    graph.add_edge(RULE, "urn:item:other", "hasEvidence", id="overlay")
    before = deepcopy(graph.to_dict())
    pages = [
        client.get(
            INSTANCES, params={"class_uri": RULE_CLASS, "skip": skip, "limit": 1}
        ).json()
        for skip in (0, 1)
    ]
    expected = [
        {
            "property_uri": BASE + "approves",
            "label": "审批",
            "loaded": True,
            "ontology_uri": BASE,
            "kinds": ["object"],
            "instance_count": 2,
        },
        {
            "property_uri": BASE + "confidence",
            "label": "置信度",
            "loaded": True,
            "ontology_uri": BASE,
            "kinds": ["literal"],
            "instance_count": 1,
        },
        {
            "property_uri": BASE + "text",
            "label": "文本",
            "loaded": True,
            "ontology_uri": BASE,
            "kinds": ["literal"],
            "instance_count": 2,
        },
    ]
    assert pages[0]["observed_properties"] == expected
    assert pages[1]["observed_properties"] == expected
    assert pages[0]["total"] == 2
    assert graph.to_dict() == before


def test_observed_properties_keep_exact_namespaces_and_unloaded_definitions(scene):
    client, graph, _ = scene
    graph.nodes[RULE].properties.update(
        {"name": "本地", BUSINESS + "name": "另一个命名空间", BUSINESS + "unloaded": 3}
    )
    graph.add_node(BASE + "name", "owl:DatatypeProperty", "名称", scheme_uri=BASE)
    graph.add_node(
        BUSINESS + "name", "owl:DatatypeProperty", "业务名称", scheme_uri=BUSINESS
    )
    graph.add_node("urn:target", BUSINESS_CLASS, "对象")
    graph.add_edge(RULE, "urn:target", BUSINESS + "unloadedRelation")
    rows = client.get(INSTANCES, params={"class_uri": RULE_CLASS}).json()[
        "observed_properties"
    ]
    by_uri = {row["property_uri"]: row for row in rows}
    assert set(by_uri) == {
        BASE + "name",
        BUSINESS + "name",
        BUSINESS + "unloaded",
        BUSINESS + "unloadedRelation",
    }
    assert by_uri[BASE + "name"]["label"] == "名称"
    assert by_uri[BUSINESS + "name"]["label"] == "业务名称"
    assert by_uri[BUSINESS + "unloaded"]["loaded"] is False
    assert by_uri[BUSINESS + "unloadedRelation"]["kinds"] == ["object"]
    assert by_uri[BUSINESS + "unloadedRelation"]["instance_count"] == 1


def test_observed_properties_ignore_display_metadata_and_reflect_current_graph(scene):
    client, graph, _ = scene
    graph.nodes[RULE].properties.update(
        {
            "content": "显示内容",
            "x": 1,
            "name": "财务负责人",
            "source": "材料",
            "confidence": 0.95,
            "valid_from": "2026-01-01",
        }
    )
    graph.add_node(BASE + "name", "owl:DatatypeProperty", "名称", scheme_uri=BASE)
    before = client.get(INSTANCES, params={"class_uri": RULE_CLASS}).json()
    assert [row["property_uri"] for row in before["observed_properties"]] == [
        BASE + "name"
    ]
    graph.nodes[RULE].properties.pop("name")
    after = client.get(INSTANCES, params={"class_uri": RULE_CLASS}).json()
    assert after["observed_properties"] == []
    assert (
        client.get(INSTANCES, params={"class_uri": BUSINESS_CLASS}).json()[
            "observed_properties"
        ]
        == []
    )


def test_observed_properties_keep_loaded_short_predicates_and_separate_namespaces(
    scene,
):
    client, graph, _ = scene
    graph.nodes[RULE].properties.update(
        {"confidence": 0.95, "source": "材料", BUSINESS + "fact_status": "引用状态"}
    )
    for key in ("fact_status", "review_status", "confidence", "source"):
        graph.add_node(BASE + key, "owl:DatatypeProperty", key, scheme_uri=BASE)
    graph.add_node(
        BUSINESS + "fact_status", "owl:DatatypeProperty", "外部状态", scheme_uri=BUSINESS
    )
    rows = client.get(INSTANCES, params={"class_uri": RULE_CLASS}).json()[
        "observed_properties"
    ]
    assert {row["property_uri"] for row in rows} == {
        BASE + key for key in ("fact_status", "review_status", "confidence", "source")
    } | {BUSINESS + "fact_status"}
    assert all(row["instance_count"] == 1 for row in rows)
    # A similarly named definition in another namespace does not identify a bare key.
    graph.nodes.pop(BASE + "fact_status")
    graph.nodes.pop(BASE + "review_status")
    rows = client.get(INSTANCES, params={"class_uri": RULE_CLASS}).json()[
        "observed_properties"
    ]
    assert {row["property_uri"] for row in rows} == {
        BASE + "confidence",
        BASE + "source",
        BUSINESS + "fact_status",
    }


def test_explicit_edges_properties_and_node_type_merge_without_duplicate_classes(scene):
    graph = scene[1]
    graph.add_node(
        "urn:item:typed",
        RULE_CLASS,
        "多个声明",
        **{"rdf:type": [RULE_CLASS, {"@id": BUSINESS_CLASS}]},
    )
    graph.add_edge("urn:item:typed", RULE_CLASS, RDF_TYPE, id="declared-type")
    result = read_types(scene, "urn:item:typed")
    memberships = {item["class_uri"]: item for item in result["types"]}
    assert set(memberships) == {RULE_CLASS, BUSINESS_CLASS}
    assert {basis["kind"] for basis in memberships[RULE_CLASS]["basis"]} == {
        "rdf_type_edge",
        "rdf_type_property",
        "node_type",
    }
    assert {
        basis.get("edge_id")
        for basis in memberships[RULE_CLASS]["basis"]
        if basis["kind"] == "rdf_type_edge"
    } == {"declared-type"}


def test_reverse_lookup_uses_the_same_declarations_and_excludes_schema_nodes(scene):
    scene[1].add_node("urn:item:second", "entity", "显式类型")
    scene[1].add_edge("urn:item:second", RULE_CLASS, "rdf:type", id="second-type")
    response = scene[0].get(
        INSTANCES, params={"class_uri": RULE_CLASS, "skip": 0, "limit": 1}
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["total"] == 2
    assert result["skip"] == 0 and result["limit"] == 1
    assert len(result["instances"]) == 1
    second = (
        scene[0]
        .get(INSTANCES, params={"class_uri": RULE_CLASS, "skip": 1, "limit": 1})
        .json()
    )
    assert {item["node_id"] for item in result["instances"] + second["instances"]} == {
        RULE,
        "urn:item:second",
    }
    for item in result["instances"] + second["instances"]:
        matching = next(
            m
            for m in read_types(scene, item["node_id"])["types"]
            if m["class_uri"] == RULE_CLASS
        )
        assert item["basis"] == matching["basis"]


def test_missing_namespace_does_not_guess_from_a_label_or_loaded_ontology(scene):
    scene[1].metadata = {}
    scene[1].nodes[RULE].content = "流程规则"
    assert read_types(scene)["status"] == "unmapped"
    assert read_types(scene)["types"] == []


def test_unknown_instance_is_404(scene):
    assert scene[0].get(TYPES, params={"node_id": "urn:missing"}).status_code == 404


@pytest.mark.parametrize(
    "schema_type",
    [
        "owl:Ontology",
        "owl:Class",
        "rdfs:Class",
        "rdf:Property",
        "rdfs:Property",
        "owl:ObjectProperty",
        "owl:DatatypeProperty",
        "owl:AnnotationProperty",
        "owl:FunctionalProperty",
        "owl:InverseFunctionalProperty",
        "owl:TransitiveProperty",
        "owl:SymmetricProperty",
        "owl:AsymmetricProperty",
        "owl:ReflexiveProperty",
        "owl:IrreflexiveProperty",
        "owl:Restriction",
        "rdfs:Datatype",
        "owl:DataRange",
        "owl:Axiom",
        "owl:AllDisjointClasses",
        "owl:AllDisjointProperties",
    ],
)
@pytest.mark.parametrize("declaration", ["node_type", "property", "edge"])
def test_schema_declarations_are_never_listed_as_business_instances(
    scene, schema_type, declaration
):
    graph = scene[1]
    graph.add_node(
        "urn:schema", schema_type if declaration == "node_type" else "entity", "Schema"
    )
    node = graph.nodes["urn:schema"]
    node.properties["rdf:type"] = BUSINESS_CLASS
    if declaration == "property":
        node.properties["rdf:type"] = [BUSINESS_CLASS, schema_type]
    if declaration == "edge":
        graph.add_edge(node.node_id, schema_type, "rdf:type")
    assert read_types(scene, node.node_id)["types"] == []
    assert (
        scene[0]
        .get(INSTANCES, params={"class_uri": BUSINESS_CLASS})
        .json()["instances"]
        == []
    )


@pytest.mark.parametrize("declaration", ["property", "edge"])
@pytest.mark.parametrize(
    "class_type", ["owl:Class", "http://www.w3.org/2000/01/rdf-schema#Class"]
)
def test_loaded_class_can_be_declared_by_an_explicit_property_or_edge(
    scene, declaration, class_type
):
    graph = scene[1]
    graph.nodes[RULE_CLASS].node_type = "entity"
    if declaration == "property":
        graph.nodes[RULE_CLASS].properties[RDF_TYPE] = {"@id": class_type}
    else:
        graph.add_edge(RULE_CLASS, class_type, RDF_TYPE)
    assert read_types(scene)["types"][0]["loaded"] is True
    assert read_types(scene)["types"][0]["ontology_uri"] == BASE


@pytest.mark.parametrize(
    "metatype",
    [
        "owl:NamedIndividual",
        "http://www.w3.org/2002/07/owl#NamedIndividual",
        "skos:Concept",
        "http://www.w3.org/2004/02/skos/core#Concept",
    ],
)
def test_individual_and_skos_metatypes_do_not_hide_explicit_business_membership(
    scene, metatype
):
    graph = scene[1]
    graph.add_node("urn:individual", metatype, "一个申请", **{"rdf:type": BUSINESS_CLASS})
    result = read_types(scene, "urn:individual")
    expected = [BUSINESS_CLASS]
    if metatype in {"skos:Concept", "http://www.w3.org/2004/02/skos/core#Concept"}:
        expected.insert(0, "http://www.w3.org/2004/02/skos/core#Concept")
    assert [item["class_uri"] for item in result["types"]] == expected
    reverse = scene[0].get(INSTANCES, params={"class_uri": BUSINESS_CLASS}).json()
    assert [item["node_id"] for item in reverse["instances"]] == ["urn:individual"]


@pytest.mark.parametrize(
    ("node_type", "class_uri"),
    [
        ("skos:Concept", "http://www.w3.org/2004/02/skos/core#Concept"),
        (
            "http://www.w3.org/2004/02/skos/core#Concept",
            "http://www.w3.org/2004/02/skos/core#Concept",
        ),
        ("skos:ConceptScheme", "http://www.w3.org/2004/02/skos/core#ConceptScheme"),
        (
            "http://www.w3.org/2004/02/skos/core#ConceptScheme",
            "http://www.w3.org/2004/02/skos/core#ConceptScheme",
        ),
    ],
)
def test_skos_concept_and_scheme_are_declared_types_even_when_definitions_are_not_loaded(
    scene, node_type, class_uri
):
    scene[1].add_node("urn:vocabulary-item", node_type, "词汇节点")
    result = read_types(scene, "urn:vocabulary-item")
    assert result["status"] == "declared"
    assert result["types"] == [
        {
            "class_uri": class_uri,
            "label": class_uri,
            "loaded": False,
            "ontology_uri": None,
            "basis": [{"kind": "node_type", "value": node_type}],
        }
    ]
    reverse = scene[0].get(INSTANCES, params={"class_uri": class_uri}).json()
    assert [item["node_id"] for item in reverse["instances"]] == ["urn:vocabulary-item"]


@pytest.mark.parametrize(
    ("base", "expected"),
    [
        ("https://example.org/process", "https://example.org/process/ProcessRule"),
        ("https://example.org/process/", "https://example.org/process/ProcessRule"),
        ("https://example.org/process#", "https://example.org/process#ProcessRule"),
        (
            "https://example.org/process#fragment",
            "https://example.org/process#fragment/ProcessRule",
        ),
        ("urn:policy:", "urn:policy:ProcessRule"),
        ("urn:policy", "urn:policy/ProcessRule"),
    ],
)
def test_explicit_namespace_uses_the_process_exporters_separator_rules(
    scene, base, expected
):
    scene[1].metadata = {"base_uri": base}
    result = read_types(scene)
    assert [item["class_uri"] for item in result["types"]] == [expected]


@pytest.mark.parametrize(
    "base",
    [
        None,
        [],
        {},
        True,
        7,
        "",
        "rdf:type",
        "https://[bad",
        "//example.org/",
        "https://example.org/\u00a0",
        "https://example.org/\x7f",
        "https://example.org/%no",
        "https://example.org/path?q=1",
        "file:///etc/passwd",
        "javascript:alert(1)",
    ],
)
def test_invalid_or_unsupported_namespace_is_not_used_for_inference(scene, base):
    scene[1].metadata = {"base_uri": base}
    assert read_types(scene)["types"] == []


@pytest.mark.parametrize("bad", [None, [], {}, True, 7])
def test_malformed_target_class_metadata_is_safe_and_never_string_coerced(scene, bad):
    target = scene[1].nodes[RULE_CLASS]
    target.node_type = bad
    target.properties = bad
    target.metadata = bad
    target.content = bad
    result = read_types(scene)
    assert result["types"] == [
        {
            "class_uri": RULE_CLASS,
            "label": RULE_CLASS,
            "loaded": False,
            "ontology_uri": None,
            "basis": [{"kind": "graph_namespace", "value": "ProcessRule"}],
        }
    ]


@pytest.mark.parametrize("bad", [None, [], {}, True, 7])
def test_malformed_declarations_are_ignored_without_hiding_a_valid_property(scene, bad):
    node = scene[1].nodes[RULE]
    node.node_type = bad
    node.properties["rdf:type"] = [bad, {"@id": bad}, BUSINESS_CLASS]
    result = read_types(scene)
    assert [item["class_uri"] for item in result["types"]] == [BUSINESS_CLASS]


def test_invalid_type_edge_values_and_ids_do_not_crash_or_leak_non_string_values(scene):
    graph = scene[1]
    graph.add_edge(RULE, RULE_CLASS, "rdf:type", id="normal")
    graph.add_edge(RULE, RULE_CLASS, "rdf:type", id="malformed")
    graph.edges[-1].edge_id = ["bad"]
    graph.add_edge(RULE, BUSINESS_CLASS, "rdf:type", id="bad-target")
    graph.edges[-1].target_id = {"uri": BUSINESS_CLASS}
    result = read_types(scene)
    assert [item["class_uri"] for item in result["types"]] == [RULE_CLASS]
    assert all(
        "edge_id" not in basis or isinstance(basis["edge_id"], str)
        for basis in result["types"][0]["basis"]
    )


@pytest.fixture
def evidence_scene(scene):
    client, graph, _ = scene
    text = "序😀\r\n采购申请须审批。\r\n附件齐全。\r\n采购申请须审批。\r\n"
    source_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    graph.nodes[BUSINESS_CLASS].properties["rdfs:comment"] = "采购申请业务类别"
    graph.nodes[RULE].properties["source_clause_id"] = "C1"
    graph.add_node(
        "urn:evidence:one",
        "Evidence",
        "采购申请须审批。",
        clause_id="C1",
        quote="采购申请须审批。",
        start_char=4,
        end_char=12,
        source_id="policy",
        source_sha256=source_hash,
    )
    graph.add_node(
        "urn:source:one",
        "SourceDocument",
        "policy",
        source_id="policy",
        source_sha256=source_hash,
    )
    graph.add_edge(RULE, "urn:evidence:one", "hasEvidence", id="rule-evidence")
    graph.add_edge(
        "urn:evidence:one", "urn:source:one", "fromSource", id="evidence-source"
    )
    client.app.state.source_resources.register_text("policy", text)
    manifest = {
        "schema_version": 1,
        "business_ontologies": [
            {
                "uri": BUSINESS,
                "terms": [
                    {
                        "uri": BUSINESS_CLASS,
                        "label": "采购申请",
                        "type": "owl:Class",
                        "comment": "采购申请业务类别",
                        "domain": [],
                        "range": [],
                        "parents": [],
                        "source_id": "policy",
                        "source_sha256": source_hash,
                        "start_char": 4,
                        "end_char": 12,
                        "quote": "采购申请须审批。",
                    }
                ],
            }
        ],
        "support_ontologies": [BASE],
    }
    response = client.post("/api/ontology/evidence-context", json=manifest)
    assert response.status_code == 200, response.text
    return scene


@pytest.mark.parametrize("selected", [RULE, "urn:evidence:one"])
def test_verified_business_concepts_are_separate_from_declared_instance_types(
    evidence_scene, selected
):
    before = deepcopy(evidence_scene[1].to_dict())
    result = read_types(evidence_scene, selected)
    assert result["related_status"] == "ready"
    assert result["related_concepts"] == [
        {
            "class_uri": BUSINESS_CLASS,
            "label": "采购申请",
            "ontology_uri": BUSINESS,
            "evidence_ids": ["urn:evidence:one"],
        }
    ]
    assert all(item["class_uri"] != BUSINESS_CLASS for item in result["types"])
    assert (
        evidence_scene[0]
        .get(INSTANCES, params={"class_uri": BUSINESS_CLASS})
        .json()["total"]
        == 0
    )
    assert evidence_scene[1].to_dict() == before


def test_related_concepts_do_not_follow_arbitrary_neighbor_edges(evidence_scene):
    graph = evidence_scene[1]
    graph.add_node("urn:actor", "Role", "采购申请")
    graph.add_edge("urn:actor", "urn:evidence:one", "supports")
    graph.add_edge("urn:actor", RULE, "performs")
    result = read_types(evidence_scene, "urn:actor")
    assert result["related_concepts"] == []
    assert result["related_status"] == "ready"


@pytest.mark.parametrize(
    "change",
    [
        "term_label",
        "term_definition",
        "missing_source",
        "source_hash",
        "evidence_quote",
        "evidence_offsets",
        "evidence_source",
        "no_has_evidence",
    ],
)
def test_invalid_or_stale_evidence_never_creates_a_business_type_or_related_concept(
    evidence_scene, change
):
    client, graph, _ = evidence_scene
    if change == "term_label":
        graph.nodes[BUSINESS_CLASS].content = "Changed class"
    elif change == "term_definition":
        graph.nodes[BUSINESS_CLASS].properties["rdfs:comment"] = "Changed definition"
    elif change == "missing_source":
        client.app.state.source_resources = SourceResourceRegistry()
    elif change == "source_hash":
        client.app.state.source_resources = SourceResourceRegistry()
        client.app.state.source_resources.register_text("policy", "Different source")
    elif change == "evidence_quote":
        graph.nodes["urn:evidence:one"].properties["quote"] = "另一段文字"
    elif change == "evidence_offsets":
        graph.nodes["urn:evidence:one"].properties["start_char"] = 999
    elif change == "evidence_source":
        graph.nodes["urn:evidence:one"].properties[
            "source_id"
        ] = "same-text-other-source"
    else:
        next(
            edge for edge in graph.edges if edge.edge_id == "rule-evidence"
        ).edge_type = "relatedTo"
    result = read_types(evidence_scene)
    assert result["related_concepts"] == []
    assert [item["class_uri"] for item in result["types"]] == [RULE_CLASS]
    expected_status = (
        "unavailable"
        if change in {"term_label", "term_definition", "missing_source", "source_hash"}
        else "ready"
    )
    assert result["related_status"] == expected_status


@pytest.mark.parametrize("type_key", ["rdf:type", RDF_TYPE, "@type"])
@pytest.mark.parametrize(
    "reference",
    [
        BUSINESS_CLASS,
        {"@id": BUSINESS_CLASS},
        {"uri": BUSINESS_CLASS},
        {"id": BUSINESS_CLASS},
        [BUSINESS_CLASS],
    ],
)
def test_explicit_property_reference_shapes_are_supported_without_a_graph_namespace(
    scene, type_key, reference
):
    graph = scene[1]
    graph.metadata = {}
    graph.nodes[RULE].properties[type_key] = reference
    result = read_types(scene)
    assert [item["class_uri"] for item in result["types"]] == [BUSINESS_CLASS]
    assert result["types"][0]["basis"] == [
        {"kind": "rdf_type_property", "value": BUSINESS_CLASS}
    ]


def test_queries_reflect_namespace_and_class_changes_without_stale_cache(scene):
    graph = scene[1]
    assert read_types(scene)["types"][0]["label"] == "流程规则"
    graph.nodes[RULE_CLASS].content = "候选流程规则"
    assert read_types(scene)["types"][0]["label"] == "候选流程规则"
    graph.metadata = {"base_uri": "urn:another:"}
    assert read_types(scene)["types"] == [
        {
            "class_uri": "urn:another:ProcessRule",
            "label": "urn:another:ProcessRule",
            "loaded": False,
            "ontology_uri": None,
            "basis": [{"kind": "graph_namespace", "value": "ProcessRule"}],
        }
    ]
    assert (
        scene[0].get(INSTANCES, params={"class_uri": RULE_CLASS}).json()["total"] == 0
    )
    graph.metadata = {}
    assert read_types(scene)["status"] == "unmapped"


@pytest.mark.parametrize(
    ("route", "params"),
    [(TYPES, {"node_id": RULE}), (INSTANCES, {"class_uri": RULE_CLASS})],
)
def test_both_read_routes_enforce_the_existing_authentication(
    scene, monkeypatch, route, params
):
    monkeypatch.delenv("SEMANTICA_ALLOW_ANONYMOUS", raising=False)
    monkeypatch.delenv("SEMANTICA_API_KEY", raising=False)
    assert scene[0].get(route, params=params).status_code == 503
    monkeypatch.setenv("SEMANTICA_API_KEY", "test-api-key")
    assert scene[0].get(route, params=params).status_code == 401
    assert (
        scene[0].get(route, params=params, headers={"X-API-Key": "wrong"}).status_code
        == 401
    )
    assert (
        scene[0]
        .get(route, params=params, headers={"X-API-Key": "test-api-key"})
        .status_code
        == 200
    )


@pytest.mark.parametrize(
    ("extra", "status"),
    [
        ({"skip": -1}, 422),
        ({"limit": 0}, 422),
        ({"limit": 501}, 422),
        ({"class_uri": "ProcessRule"}, 400),
        ({"class_uri": "https://[invalid"}, 400),
        ({"class_uri": "file:///etc/passwd"}, 400),
        ({"class_uri": "javascript:alert(1)"}, 400),
    ],
)
def test_reverse_lookup_rejects_invalid_identifiers_and_pagination(
    scene, extra, status
):
    response = scene[0].get(INSTANCES, params={"class_uri": RULE_CLASS, **extra})
    assert response.status_code == status, response.text


def test_reverse_lookup_skips_legacy_nodes_with_non_string_ids_without_losing_valid_instances(
    scene,
):
    scene[1].add_node(7, RULE_CLASS, "Legacy numeric identity")
    response = scene[0].get(INSTANCES, params={"class_uri": RULE_CLASS})
    assert response.status_code == 200, response.text
    assert [item["node_id"] for item in response.json()["instances"]] == [RULE]


def test_repeated_quote_at_a_different_verified_position_is_not_a_related_concept(
    evidence_scene,
):
    evidence = evidence_scene[1].nodes["urn:evidence:one"]
    evidence.properties.update(start_char=21, end_char=29)
    source = (
        evidence_scene[0]
        .get("/api/sources/view", params={"node_id": "urn:evidence:one"})
        .json()
    )
    assert source["evidence"][0]["status"] == "aligned"
    result = read_types(evidence_scene)
    assert result["related_status"] == "ready"
    assert result["related_concepts"] == []
