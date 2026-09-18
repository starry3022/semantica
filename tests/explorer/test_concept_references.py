"""Explicit candidate references are not fabricated type memberships."""

from copy import deepcopy
import hashlib
from datetime import datetime

import pytest
from starlette.testclient import TestClient

from semantica.context.context_graph import ContextGraph
from semantica.explorer.app import create_app
from semantica.explorer.session import GraphSession
from semantica.explorer.source_resources import SourceResourceRegistry
from semantica.ontology.graph_snapshot import build_graph_snapshot

BASE = "https://example.org/business/"
TEXT = "供应商付款申请应提供合法有效的合同、发票以及验收材料。\n"
SHA = hashlib.sha256(TEXT.encode()).hexdigest()


@pytest.fixture
def scene():
    graph = ContextGraph(advanced_analytics=False)
    graph.metadata = {"base_uri": "https://example.org/process/"}
    graph.add_node(
        "urn:rule",
        "ProcessRule",
        "提供材料",
        fact_status="candidate",
        review_status="unreviewed",
    )
    graph.add_node(
        "urn:evidence",
        "Evidence",
        TEXT,
        quote=TEXT,
        start_char=0,
        end_char=len(TEXT),
        source_id="policy",
        source_sha256=SHA,
    )
    graph.add_edge("urn:rule", "urn:evidence", "hasEvidence")
    terms, references = [], []
    for name, label in (
        ("Contract", "合同"),
        ("Invoice", "发票"),
        ("AcceptanceMaterial", "验收材料"),
    ):
        uri, node_id = BASE + name, "urn:document:" + name
        props = {
            "name": "合法有效的" + label,
            "fact_status": "candidate",
            "review_status": "unreviewed",
        }
        graph.add_node(node_id, "RequiredDocument", props["name"], **props)
        graph.add_edge("urn:rule", node_id, "requiresDocument")
        graph.add_node(
            uri, "owl:Class", label, scheme_uri=BASE, **{"rdfs:comment": label + "类型"}
        )
        terms.append(
            dict(
                uri=uri,
                label=label,
                type="owl:Class",
                comment=label + "类型",
                domain=[],
                range=[],
                parents=[],
                source_id="policy",
                source_sha256=SHA,
                start_char=0,
                end_char=len(TEXT),
                quote=TEXT,
            )
        )
        references.append(
            dict(
                node_id=node_id,
                class_uri=uri,
                relation="references_concept",
                rationale="该材料要求引用对应的业务材料概念。",
                node_type="RequiredDocument",
                node_label=props["name"],
                node_properties=props,
                input_rdf_sha256="a" * 64,
            )
        )
    manifest = {
        "schema_version": 1,
        "business_ontologies": [
            {"uri": BASE, "terms": terms, "concept_references": references}
        ],
        "support_ontologies": [],
    }
    resources = SourceResourceRegistry()
    manifest["business_ontologies"][0]["input_graph"] = build_graph_snapshot(
        graph.to_dict(), "a" * 64
    )
    resources.register_text("policy", TEXT)
    with TestClient(
        create_app(session=GraphSession(graph), source_resources=resources)
    ) as client:
        yield client, graph, manifest, resources


def register(scene):
    response = scene[0].post("/api/ontology/evidence-context", json=scene[2])
    assert response.status_code == 200, response.text


def test_explicit_three_way_references_remain_distinct_from_membership(scene):
    register(scene)
    client, graph, _, _ = scene
    before = deepcopy(graph.to_dict())
    for name in ("Contract", "Invoice", "AcceptanceMaterial"):
        node_id, uri = "urn:document:" + name, BASE + name
        data = client.get(
            "/api/ontology/instance-types", params={"node_id": node_id}
        ).json()
        assert [item["class_uri"] for item in data["concept_references"]] == [uri]
        assert data["concept_references"][0]["evidence_ids"] == ["urn:evidence"]
        assert data["concept_references"][0]["review_status"] == "unreviewed"
        assert data["concept_reference_issues"] == []
        assert all(item["class_uri"] != uri for item in data["types"])
        reverse = client.get(
            "/api/ontology/concept-references", params={"class_uri": uri}
        ).json()
        assert [item["node_id"] for item in reverse["references"]] == [node_id]
        assert (
            client.get(
                "/api/ontology/class-instances", params={"class_uri": uri}
            ).json()["total"]
            == 0
        )
    assert graph.to_dict() == before


@pytest.mark.parametrize(
    "change",
    [
        "node_label",
        "node_type",
        "node_properties",
        "term_label",
        "missing_source",
        "quote",
        "edge",
    ],
)
def test_stale_mappings_are_reported_and_never_reused(scene, change):
    register(scene)
    client, graph, _, resources = scene
    node = graph.nodes["urn:document:Contract"]
    if change == "node_label":
        node.content = "不同材料"
    elif change == "node_type":
        node.node_type = "Role"
    elif change == "node_properties":
        node.properties["name"] = "另一份合同"
    elif change == "term_label":
        graph.nodes[BASE + "Contract"].content = "其他概念"
    elif change == "missing_source":
        client.app.state.source_resources = SourceResourceRegistry()
    elif change == "quote":
        graph.nodes["urn:evidence"].properties["quote"] = "不匹配"
    else:
        next(
            edge for edge in graph.edges if edge.target_id == node.node_id
        ).edge_type = "relatedTo"
    response = client.get(
        "/api/ontology/concept-references", params={"class_uri": BASE + "Contract"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["references"] == []
    assert response.json()["issues"][0]["reason"]


def test_shared_quote_without_explicit_mapping_does_not_match_documents(scene):
    scene[2]["business_ontologies"][0]["concept_references"] = []
    register(scene)
    result = (
        scene[0]
        .get(
            "/api/ontology/instance-types", params={"node_id": "urn:document:Contract"}
        )
        .json()
    )
    assert result["concept_references"] == []


def test_legacy_context_has_no_mapping_requirement(scene):
    del scene[2]["business_ontologies"][0]["concept_references"]
    register(scene)
    result = (
        scene[0]
        .get(
            "/api/ontology/concept-references", params={"class_uri": BASE + "Contract"}
        )
        .json()
    )
    assert result["references"] == []
    assert result["issues"] == []


@pytest.mark.parametrize(
    "change", ["unknown_class", "duplicate", "type_assertion", "technical_node"]
)
def test_invalid_registration_is_atomic(scene, change):
    register(scene)
    modified = deepcopy(scene[2])
    refs = modified["business_ontologies"][0]["concept_references"]
    if change == "unknown_class":
        refs[0]["class_uri"] = BASE + "Absent"
    elif change == "duplicate":
        refs.append(deepcopy(refs[0]))
    elif change == "type_assertion":
        refs[0]["relation"] = "rdf:type"
    else:
        refs[0]["node_type"] = "Evidence"
    assert (
        scene[0].post("/api/ontology/evidence-context", json=modified).status_code
        == 422
    )
    result = (
        scene[0]
        .get(
            "/api/ontology/concept-references", params={"class_uri": BASE + "Contract"}
        )
        .json()
    )
    assert len(result["references"]) == 1


@pytest.mark.parametrize(
    "change", ["rule_content", "rule_properties", "owner", "namespace"]
)
def test_input_semantic_changes_invalidate_the_original_proposal(scene, change):
    register(scene)
    client, graph, _, _ = scene
    if change == "rule_content":
        graph.nodes["urn:rule"].content = "新规则"
    elif change == "rule_properties":
        graph.nodes["urn:rule"].properties["modality"] = "prohibition"
    elif change == "namespace":
        graph.metadata["base_uri"] = "https://example.org/another/"
    else:
        graph.add_node("urn:other-rule", "ProcessRule", "另一规则")
        graph.add_edge("urn:other-rule", "urn:evidence", "hasEvidence")
        next(
            edge for edge in graph.edges if edge.target_id == "urn:document:Contract"
        ).source_id = "urn:other-rule"
    data = client.get(
        "/api/ontology/concept-references", params={"class_uri": BASE + "Contract"}
    ).json()
    assert data["references"] == []
    assert "input graph" in data["issues"][0]["reason"]


def test_new_unrelated_ontology_and_layout_do_not_invalidate_input(scene):
    register(scene)
    client, graph, _, _ = scene
    graph.add_node("urn:unrelated", "owl:Class", "无关类")
    graph.metadata["layout"] = {"x": 10}
    result = client.get(
        "/api/ontology/concept-references", params={"class_uri": BASE + "Contract"}
    ).json()
    assert len(result["references"]) == 1
    assert result["issues"] == []


def test_references_cannot_be_registered_without_input_identity(scene):
    del scene[2]["business_ontologies"][0]["input_graph"]
    assert (
        scene[0].post("/api/ontology/evidence-context", json=scene[2]).status_code
        == 422
    )


@pytest.mark.parametrize(
    "value", [datetime(2026, 9, 18), {1: "one", "name": "name"}, float("nan")]
)
def test_invalid_live_properties_make_proposal_unavailable_without_server_error(
    scene, value
):
    register(scene)
    client, graph, _, _ = scene
    graph.nodes["urn:rule"].properties["malformed"] = value
    response = client.get(
        "/api/ontology/concept-references", params={"class_uri": BASE + "Contract"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "unavailable"
    assert response.json()["references"] == []
    assert response.json()["issues"][0]["reason"]
