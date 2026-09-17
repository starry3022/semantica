"""Business ontology terms may cross-reference only verified process evidence."""

import hashlib
from copy import deepcopy

import pytest

pytest.importorskip("fastapi")

from starlette.testclient import TestClient  # noqa: E402

from semantica.context.context_graph import ContextGraph  # noqa: E402
from semantica.explorer.app import create_app  # noqa: E402
from semantica.explorer.session import GraphSession  # noqa: E402
from semantica.explorer.source_resources import SourceResourceRegistry  # noqa: E402

BUSINESS = "https://example.org/business/"
SUPPORT = "https://example.org/process/"
PURCHASE = BUSINESS + "PurchaseRequest"
RULE = "urn:rule:purchase"
EVIDENCE = "urn:evidence:purchase"
SOURCE = "urn:source:policy"
TEXT = "序😀\r\n采购申请须审批。\r\n附件齐全。\r\n采购申请须审批。\r\n"
SHA = hashlib.sha256(TEXT.encode("utf-8")).hexdigest()
CONTEXT_URL = "/api/ontology/evidence-context"
RELATED_URL = "/api/ontology/related-rules"


@pytest.fixture
def manifest():
    return {
        "schema_version": 1,
        "business_ontologies": [
            {
                "uri": BUSINESS,
                "terms": [
                    {
                        "uri": PURCHASE,
                        "label": "采购申请",
                        "type": "owl:Class",
                        "comment": "采购申请业务类别",
                        "domain": [],
                        "range": [],
                        "parents": [],
                        "source_id": "policy",
                        "source_sha256": SHA,
                        "start_char": 4,
                        "end_char": 12,
                        "quote": "采购申请须审批。",
                    }
                ],
            }
        ],
        "support_ontologies": [SUPPORT],
    }


@pytest.fixture
def scene():
    graph = ContextGraph(advanced_analytics=False)
    graph.add_node(BUSINESS, "owl:Ontology", "采购业务候选本体")
    graph.add_node(SUPPORT, "owl:Ontology", "流程与证据支持词汇")
    graph.add_node(
        PURCHASE,
        "owl:Class",
        "采购申请",
        scheme_uri=BUSINESS,
        **{"rdfs:comment": "采购申请业务类别"},
    )
    graph.add_node(
        RULE,
        "ProcessRule",
        "采购审批规则",
        modality="obligation",
        source_clause_id="C1",
        supporting_clause_ids=["C2"],
        fact_status="candidate",
        review_status="unreviewed",
    )
    graph.add_node(
        EVIDENCE,
        "Evidence",
        "采购申请须审批。",
        clause_id="C1",
        quote="采购申请须审批。",
        start_char=4,
        end_char=12,
        source_id="policy",
        source_sha256=SHA,
    )
    graph.add_node(
        SOURCE,
        "SourceDocument",
        "policy",
        source_id="policy",
        source_sha256=SHA,
    )
    graph.add_edge(RULE, EVIDENCE, "hasEvidence", id="rule-evidence")
    graph.add_edge(EVIDENCE, SOURCE, "fromSource", id="evidence-source")
    resources = SourceResourceRegistry()
    resources.register_text("policy", TEXT, title="采购制度", version="V1.3")
    app = create_app(session=GraphSession(graph), source_resources=resources)
    with TestClient(app) as client:
        yield client, graph, resources


def test_verified_business_term_links_exact_rule_evidence(scene, manifest):
    client, graph, _ = scene
    before = deepcopy(graph.find_node(RULE))
    assert TEXT[4:12] == "采购申请须审批。"
    assert len(TEXT[:4].encode("utf-16-le")) // 2 == 5

    registered = client.post(CONTEXT_URL, json=manifest)
    assert registered.status_code == 200, registered.text
    assert client.get(CONTEXT_URL).json() == {
        "configured": True,
        "business_ontologies": [BUSINESS],
        "support_ontologies": [SUPPORT],
    }
    response = client.get(
        RELATED_URL, params={"ontology_uri": BUSINESS, "term_uri": PURCHASE}
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "ready"
    assert data["ontology_uri"] == BUSINESS
    assert data["term_uri"] == PURCHASE
    assert data["association_status"] == "candidate"
    assert data["term"] == {
        "id": PURCHASE,
        "label": "采购申请",
        "type": "owl:Class",
        "description": "采购申请业务类别",
    }
    assert len(data["associations"]) == 1
    rule = data["associations"][0]
    assert rule["node_id"] == RULE
    assert rule["label"] == "采购审批规则"
    assert rule["modality"] == "obligation"
    assert rule["fact_status"] == "candidate"
    assert rule["review_status"] == "unreviewed"
    assert rule["evidence"] == [
        {
            "id": EVIDENCE,
            "clause_id": "C1",
            "role": "primary",
            "quote": "采购申请须审批。",
            "start_char": 4,
            "end_char": 12,
            "source_id": "policy",
            "source_sha256": SHA,
            "links": [
                {
                    "term_uri": PURCHASE,
                    "label": "采购申请",
                    "kind": "direct",
                    "relation": None,
                }
            ],
        }
    ]
    assert data["anchors"][0]["status"] == "aligned"
    assert data["notice"]
    assert graph.find_node(RULE) == before


def _register(scene, manifest):
    response = scene[0].post(CONTEXT_URL, json=manifest)
    assert response.status_code == 200, response.text


def _related(scene, term_uri=PURCHASE, ontology_uri=BUSINESS):
    response = scene[0].get(
        RELATED_URL, params={"ontology_uri": ontology_uri, "term_uri": term_uri}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _add_supporting_property(scene, manifest, relation="rdfs:domain"):
    """Add independently specified property and supporting-clause fixtures."""
    _, graph, _ = scene
    property_uri = BUSINESS + "requiresMaterials"
    graph.add_node(
        property_uri,
        "owl:ObjectProperty",
        "需附材料",
        scheme_uri=BUSINESS,
        **{"rdfs:comment": "申请要求附带材料"},
    )
    graph.add_edge(property_uri, PURCHASE, relation, id="property-class")
    graph.add_node(
        "urn:evidence:materials",
        "Evidence",
        "附件齐全。",
        clause_id="C2",
        quote="附件齐全。",
        start_char=14,
        end_char=19,
        source_id="policy",
        source_sha256=SHA,
    )
    graph.add_edge(RULE, "urn:evidence:materials", "hasEvidence", id="rule-materials")
    graph.add_edge(
        "urn:evidence:materials", SOURCE, "fromSource", id="materials-source"
    )
    manifest["business_ontologies"][0]["terms"].append(
        {
            "uri": property_uri,
            "label": "需附材料",
            "type": "owl:ObjectProperty",
            "comment": "申请要求附带材料",
            "domain": [PURCHASE] if relation == "rdfs:domain" else [],
            "range": [PURCHASE] if relation == "rdfs:range" else [],
            "parents": [],
            "source_id": "policy",
            "source_sha256": SHA,
            "start_char": 4,
            "end_char": 19,
            "quote": "采购申请须审批。\r\n附件齐全。",
        }
    )
    return property_uri


def test_unconfigured_context_and_legacy_graph_have_explicit_empty_state():
    graph = ContextGraph(advanced_analytics=False)
    graph.add_node("legacy", "Entity", "旧图节点")
    with TestClient(create_app(session=GraphSession(graph))) as client:
        assert client.get(CONTEXT_URL).json() == {
            "configured": False,
            "business_ontologies": [],
            "support_ontologies": [],
        }
        response = client.get(
            RELATED_URL,
            params={"ontology_uri": BUSINESS, "term_uri": "legacy"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "unconfigured"
        assert response.json()["associations"] == []
        assert response.json()["notice"]
        assert graph.find_node("legacy")["content"] == "旧图节点"


def test_context_is_scoped_to_one_explorer_session(scene, manifest):
    _register(scene, manifest)
    other = create_app(session=GraphSession(ContextGraph(advanced_analytics=False)))
    with TestClient(other) as client:
        assert client.get(CONTEXT_URL).json()["configured"] is False
    assert scene[0].get(CONTEXT_URL).json()["configured"] is True


def test_successful_context_registration_replaces_previous_context(scene, manifest):
    _register(scene, manifest)
    replacement = deepcopy(manifest)
    replacement["support_ontologies"] = []
    replacement["business_ontologies"][0]["terms"][0]["source_id"] = "unregistered"
    _register(scene, replacement)
    assert scene[0].get(CONTEXT_URL).json()["support_ontologies"] == []
    data = _related(scene)
    assert data["associations"] == []
    assert data["anchors"][0]["status"] == "source_missing"


def test_unknown_term_is_not_resolved_by_similar_label(scene, manifest):
    _register(scene, manifest)
    response = scene[0].get(
        RELATED_URL,
        params={"ontology_uri": BUSINESS, "term_uri": BUSINESS + "采购申请"},
    )
    assert response.status_code == 404


@pytest.mark.parametrize("relation", ["rdfs:domain", "rdfs:range"])
def test_explicit_property_link_preserves_roles_and_deduplicates_basis(
    scene, manifest, relation
):
    _, graph, _ = scene
    property_uri = _add_supporting_property(scene, manifest, relation)
    graph.add_edge(RULE, EVIDENCE, "hasEvidence", id="duplicate-rule-evidence")
    graph.add_edge(property_uri, PURCHASE, relation, id="duplicate-property-class")
    _register(scene, manifest)

    data = _related(scene)
    assert len(data["associations"]) == 1
    evidence = {item["id"]: item for item in data["associations"][0]["evidence"]}
    assert set(evidence) == {EVIDENCE, "urn:evidence:materials"}
    assert evidence[EVIDENCE]["role"] == "primary"
    assert evidence["urn:evidence:materials"]["role"] == "supporting"
    assert evidence["urn:evidence:materials"]["quote"] == "附件齐全。"
    primary_links = evidence[EVIDENCE]["links"]
    assert len(primary_links) == 2
    assert {
        (link["term_uri"], link["kind"], link["relation"]) for link in primary_links
    } == {
        (PURCHASE, "direct", None),
        (property_uri, "property", relation),
    }
    assert evidence["urn:evidence:materials"]["links"] == [
        {
            "term_uri": property_uri,
            "label": "需附材料",
            "kind": "property",
            "relation": relation,
        }
    ]


def test_selecting_property_uses_only_its_own_direct_anchor(scene, manifest):
    property_uri = _add_supporting_property(scene, manifest)
    _register(scene, manifest)
    data = _related(scene, property_uri)
    assert len(data["associations"]) == 1
    assert len(data["associations"][0]["evidence"]) == 2
    for evidence in data["associations"][0]["evidence"]:
        assert evidence["links"] == [
            {
                "term_uri": property_uri,
                "label": "需附材料",
                "kind": "direct",
                "relation": None,
            }
        ]


def test_unknown_clause_role_is_not_promoted_to_primary(scene, manifest):
    scene[1].nodes[EVIDENCE].metadata["clause_id"] = "unlisted-clause"
    _register(scene, manifest)
    evidence = _related(scene)["associations"][0]["evidence"][0]
    assert evidence["role"] == "unknown"


def test_original_rule_review_state_is_preserved_without_approving_association(
    scene, manifest
):
    scene[1].nodes[RULE].metadata.update(
        fact_status="accepted", review_status="reviewed"
    )
    _register(scene, manifest)
    data = _related(scene)
    assert data["association_status"] == "candidate"
    assert data["associations"][0]["fact_status"] == "accepted"
    assert data["associations"][0]["review_status"] == "reviewed"


def test_chinese_emoji_and_crlf_offsets_are_unicode_codepoints(scene, manifest):
    quote = "😀\r\n采购申请须审批。\r\n"
    assert TEXT[1:14] == quote
    manifest["business_ontologies"][0]["terms"][0].update(
        start_char=1, end_char=14, quote=quote
    )
    scene[1].nodes[EVIDENCE].metadata.update(start_char=1, end_char=14, quote=quote)
    _register(scene, manifest)
    data = _related(scene)
    evidence = data["associations"][0]["evidence"][0]
    assert (evidence["start_char"], evidence["end_char"], evidence["quote"]) == (
        1,
        14,
        quote,
    )
    assert data["anchors"][0]["status"] == "aligned"


def test_repeated_quote_matches_only_the_declared_source_interval(scene, manifest):
    _, graph, _ = scene
    assert TEXT[21:29] == "采购申请须审批。"
    graph.add_node("urn:rule:repeated", "ProcessRule", "后文同句", source_clause_id="C3")
    graph.add_node(
        "urn:evidence:repeated",
        "Evidence",
        "采购申请须审批。",
        clause_id="C3",
        quote="采购申请须审批。",
        start_char=21,
        end_char=29,
        source_id="policy",
        source_sha256=SHA,
    )
    graph.add_edge("urn:rule:repeated", "urn:evidence:repeated", "hasEvidence")
    graph.add_edge("urn:evidence:repeated", SOURCE, "fromSource")
    _register(scene, manifest)
    assert [item["node_id"] for item in _related(scene)["associations"]] == [RULE]


@pytest.mark.parametrize(
    "start,end,quote", [(12, 14, "\r\n"), (12, 21, "\r\n附件齐全。\r\n")]
)
def test_touching_or_whitespace_only_intersection_does_not_link(
    scene, manifest, start, end, quote
):
    # The second case overlaps the anchor only in its final CRLF.
    manifest["business_ontologies"][0]["terms"][0].update(
        start_char=4,
        end_char=14 if end == 21 else 12,
        quote="采购申请须审批。\r\n" if end == 21 else "采购申请须审批。",
    )
    assert TEXT[start:end] == quote
    scene[1].nodes[EVIDENCE].metadata.update(
        start_char=start, end_char=end, quote=quote
    )
    _register(scene, manifest)
    assert _related(scene)["associations"] == []


def test_identical_text_in_another_source_never_cross_links(scene, manifest):
    _, graph, resources = scene
    assert resources.register_text("another-policy", TEXT) == SHA
    graph.add_node("urn:rule:other", "ProcessRule", "同文其他材料", source_clause_id="C1")
    graph.add_node(
        "urn:evidence:other",
        "Evidence",
        "采购申请须审批。",
        clause_id="C1",
        quote="采购申请须审批。",
        start_char=4,
        end_char=12,
        source_id="another-policy",
        source_sha256=SHA,
    )
    graph.add_node(
        "urn:source:other",
        "SourceDocument",
        "another-policy",
        source_id="another-policy",
        source_sha256=SHA,
    )
    graph.add_edge("urn:rule:other", "urn:evidence:other", "hasEvidence")
    graph.add_edge("urn:evidence:other", "urn:source:other", "fromSource")
    _register(scene, manifest)
    assert [item["node_id"] for item in _related(scene)["associations"]] == [RULE]


def test_same_source_id_with_another_valid_revision_does_not_link(scene, manifest):
    _, graph, resources = scene
    other_hash = resources.register_text("policy", TEXT + "修订后记")
    assert other_hash != SHA
    graph.nodes[EVIDENCE].metadata["source_sha256"] = other_hash
    graph.nodes[SOURCE].metadata["source_sha256"] = other_hash
    _register(scene, manifest)
    assert _related(scene)["associations"] == []


@pytest.mark.parametrize("relation", ["relatedTo", "fromSource", "rdf:type"])
def test_arbitrary_neighbor_relationship_is_not_evidence(scene, manifest, relation):
    graph = scene[1]
    graph.edges[:] = [edge for edge in graph.edges if edge.edge_id != "rule-evidence"]
    graph.add_edge(RULE, EVIDENCE, relation)
    graph.nodes[RULE].content = "采购申请"
    _register(scene, manifest)
    assert _related(scene)["associations"] == []


def test_only_process_rule_nodes_can_supply_rule_associations(scene, manifest):
    scene[1].nodes[RULE].node_type = "Entity"
    _register(scene, manifest)
    assert _related(scene)["associations"] == []


def test_property_neighbor_without_domain_or_range_is_not_a_basis(scene, manifest):
    property_uri = _add_supporting_property(scene, manifest, "relatedTo")
    manifest["business_ontologies"][0]["terms"][0].update(
        start_char=21, end_char=29, quote="采购申请须审批。"
    )
    _register(scene, manifest)
    data = _related(scene)
    assert data["associations"] == []
    assert property_uri not in {item["term_uri"] for item in data["anchors"]}


def test_property_anchor_in_another_ontology_is_not_followed(scene, manifest):
    property_uri = _add_supporting_property(scene, manifest)
    other_ontology = "https://example.org/other-business/"
    graph = scene[1]
    graph.add_node(other_ontology, "owl:Ontology", "另一业务本体")
    graph.nodes[property_uri].metadata["scheme_uri"] = other_ontology
    foreign_term = manifest["business_ontologies"][0]["terms"].pop()
    manifest["business_ontologies"].append(
        {"uri": other_ontology, "terms": [foreign_term]}
    )
    manifest["business_ontologies"][0]["terms"][0].update(
        start_char=21, end_char=29, quote="采购申请须审批。"
    )
    _register(scene, manifest)
    data = _related(scene)
    assert data["associations"] == []
    assert property_uri not in {item["term_uri"] for item in data["anchors"]}


def test_subclass_link_does_not_inherit_the_parent_evidence_anchor(scene, manifest):
    graph = scene[1]
    parent_uri = BUSINESS + "Application"
    graph.add_node(
        parent_uri,
        "owl:Class",
        "申请",
        scheme_uri=BUSINESS,
        **{"rdfs:comment": "一般申请"},
    )
    graph.add_edge(PURCHASE, parent_uri, "rdfs:subClassOf")
    child_term = manifest["business_ontologies"][0]["terms"][0]
    parent_term = dict(child_term, uri=parent_uri, label="申请", comment="一般申请")
    child_term.update(start_char=21, end_char=29, parents=[parent_uri])
    manifest["business_ontologies"][0]["terms"].append(parent_term)
    _register(scene, manifest)
    data = _related(scene)
    assert data["associations"] == []
    assert {item["term_uri"] for item in data["anchors"]} == {PURCHASE}


@pytest.mark.parametrize(
    "changes,status",
    [
        ({"source_id": "missing"}, "source_missing"),
        ({"source_sha256": "0" * 64}, "hash_mismatch"),
        ({"end_char": 32}, "invalid_offsets"),
        ({"quote": "采购申请无需审批。"}, "quote_mismatch"),
    ],
)
def test_invalid_anchor_reports_reason_without_an_association(
    scene, manifest, changes, status
):
    manifest["business_ontologies"][0]["terms"][0].update(changes)
    _register(scene, manifest)
    data = _related(scene)
    assert data["status"] == "unavailable"
    assert data["associations"] == []
    assert data["anchors"][0]["status"] == status
    assert data["anchors"][0]["reason"]


def test_missing_registered_material_does_not_look_aligned(scene, manifest):
    scene[0].app.state.source_resources = SourceResourceRegistry()
    _register(scene, manifest)
    data = _related(scene)
    assert data["status"] == "unavailable"
    assert data["associations"] == []
    assert data["anchors"][0]["status"] == "source_missing"


@pytest.mark.parametrize(
    "changes,status",
    [
        ({"quote": "错误引文"}, "quote_mismatch"),
        ({"start_char": -1}, "invalid_offsets"),
        ({"end_char": 32}, "invalid_offsets"),
        ({"start_char": True}, "invalid_offsets"),
    ],
)
def test_invalid_graph_evidence_is_reported_without_becoming_a_link(
    scene, manifest, changes, status
):
    scene[1].nodes[EVIDENCE].metadata.update(changes)
    _register(scene, manifest)
    data = _related(scene)
    assert data["associations"] == []
    issue = next(item for item in data["evidence_issues"] if item["id"] == EVIDENCE)
    assert issue["clause_id"] == "C1"
    assert issue["status"] == status
    assert issue["reason"]


def test_evidence_from_source_conflict_is_rejected(scene, manifest):
    scene[1].nodes[SOURCE].metadata["source_id"] = "different-policy"
    _register(scene, manifest)
    data = _related(scene)
    assert data["associations"] == []
    assert data["evidence_issues"][0]["status"] == "source_mismatch"


@pytest.mark.parametrize("field", ["label", "comment", "type"])
def test_changed_term_definition_invalidates_direct_and_property_anchors(
    scene, manifest, field
):
    _add_supporting_property(scene, manifest)
    _register(scene, manifest)
    node = scene[1].nodes[PURCHASE]
    if field == "label":
        node.content = "付款申请"
    elif field == "comment":
        node.metadata["rdfs:comment"] = "另一份定义"
    else:
        node.node_type = "owl:ObjectProperty"
    data = _related(scene)
    assert data["status"] == "unavailable"
    assert data["associations"] == []
    root = next(item for item in data["anchors"] if item["term_uri"] == PURCHASE)
    assert root["status"] == "term_changed"
    assert root["reason"]


@pytest.mark.parametrize("relation", ["rdfs:domain", "rdfs:range", "rdfs:subClassOf"])
def test_changed_schema_edge_set_invalidates_the_term(scene, manifest, relation):
    _register(scene, manifest)
    scene[1].add_node(BUSINESS + "Other", "owl:Class", "其他", scheme_uri=BUSINESS)
    scene[1].add_edge(PURCHASE, BUSINESS + "Other", relation)
    data = _related(scene)
    assert data["associations"] == []
    assert data["anchors"][0]["status"] == "term_changed"


def test_changed_property_snapshot_drops_only_its_evidence_basis(scene, manifest):
    property_uri = _add_supporting_property(scene, manifest)
    _register(scene, manifest)
    scene[1].nodes[property_uri].metadata["rdfs:comment"] = "改写后的属性定义"
    data = _related(scene)
    assert len(data["associations"]) == 1
    evidence = data["associations"][0]["evidence"]
    assert [item["id"] for item in evidence] == [EVIDENCE]
    assert [link["kind"] for link in evidence[0]["links"]] == ["direct"]
    anchor = next(item for item in data["anchors"] if item["term_uri"] == property_uri)
    assert anchor["status"] == "term_changed"


def test_valid_property_basis_survives_missing_selected_term_material(scene, manifest):
    property_uri = _add_supporting_property(scene, manifest)
    manifest["business_ontologies"][0]["terms"][0]["source_id"] = "missing"
    _register(scene, manifest)
    data = _related(scene)
    assert data["status"] == "ready"
    assert len(data["associations"]) == 1
    assert len(data["associations"][0]["evidence"]) == 2
    for evidence in data["associations"][0]["evidence"]:
        assert {link["term_uri"] for link in evidence["links"]} == {property_uri}
    root = next(item for item in data["anchors"] if item["term_uri"] == PURCHASE)
    assert root["status"] == "source_missing"


@pytest.mark.parametrize("location", ["root", "ontology", "term"])
@pytest.mark.parametrize("field", ["path", "url", "source_path"])
def test_file_or_url_parameters_are_rejected_atomically(
    scene, manifest, location, field
):
    _register(scene, manifest)
    invalid = deepcopy(manifest)
    target = {
        "root": invalid,
        "ontology": invalid["business_ontologies"][0],
        "term": invalid["business_ontologies"][0]["terms"][0],
    }[location]
    target[field] = (
        "../../private/secret.txt" if field != "url" else "https://invalid.test/"
    )
    response = scene[0].post(CONTEXT_URL, json=invalid)
    assert response.status_code in {400, 422}, response.text
    assert [item["node_id"] for item in _related(scene)["associations"]] == [RULE]


@pytest.mark.parametrize(
    "case", ["term", "ontology", "support", "overlap", "cross-term"]
)
def test_duplicate_and_overlapping_declarations_are_rejected_atomically(
    scene, manifest, case
):
    _register(scene, manifest)
    invalid = deepcopy(manifest)
    ontology = invalid["business_ontologies"][0]
    if case == "term":
        ontology["terms"].append(deepcopy(ontology["terms"][0]))
    elif case == "ontology":
        invalid["business_ontologies"].append(deepcopy(ontology))
    elif case == "support":
        invalid["support_ontologies"].append(SUPPORT)
    elif case == "overlap":
        invalid["support_ontologies"].append(BUSINESS)
    else:
        invalid["business_ontologies"].append(
            {"uri": "https://example.org/other/", "terms": deepcopy(ontology["terms"])}
        )
    response = scene[0].post(CONTEXT_URL, json=invalid)
    assert response.status_code in {400, 422}, response.text
    assert scene[0].get(CONTEXT_URL).json()["business_ontologies"] == [BUSINESS]
    assert [item["node_id"] for item in _related(scene)["associations"]] == [RULE]


@pytest.mark.parametrize(
    "field,value",
    [
        ("type", "ProcessRule"),
        ("start_char", True),
        ("end_char", 12.0),
        ("source_sha256", "not-a-sha256"),
        ("quote", ["采购申请须审批。"]),
        ("domain", PURCHASE),
    ],
)
def test_manifest_field_types_are_strict(scene, manifest, field, value):
    _register(scene, manifest)
    invalid = deepcopy(manifest)
    invalid["business_ontologies"][0]["terms"][0][field] = value
    response = scene[0].post(CONTEXT_URL, json=invalid)
    assert response.status_code in {400, 422}, response.text
    assert [item["node_id"] for item in _related(scene)["associations"]] == [RULE]


@pytest.mark.parametrize("version", [True, "1", 2])
def test_manifest_schema_version_is_explicit_and_strict(scene, manifest, version):
    manifest["schema_version"] = version
    response = scene[0].post(CONTEXT_URL, json=manifest)
    assert response.status_code in {400, 422}, response.text
    assert scene[0].get(CONTEXT_URL).json()["configured"] is False


@pytest.mark.parametrize("field", ["comment", "domain", "range", "parents"])
def test_definition_snapshot_fields_are_required(scene, manifest, field):
    del manifest["business_ontologies"][0]["terms"][0][field]
    response = scene[0].post(CONTEXT_URL, json=manifest)
    assert response.status_code in {400, 422}, response.text


@pytest.mark.parametrize("key", [None, "wrong-key"])
def test_context_write_requires_authentication_and_preserves_old_context(
    scene, manifest, monkeypatch, key
):
    _register(scene, manifest)
    monkeypatch.delenv("SEMANTICA_ALLOW_ANONYMOUS", raising=False)
    monkeypatch.setenv("SEMANTICA_API_KEY", "test-private-key")
    replacement = deepcopy(manifest)
    replacement["support_ontologies"] = []
    headers = {} if key is None else {"X-API-Key": key}
    assert (
        scene[0].post(CONTEXT_URL, json=replacement, headers=headers).status_code == 401
    )
    accepted = {"X-API-Key": "test-private-key"}
    assert scene[0].get(CONTEXT_URL, headers=accepted).json()["support_ontologies"] == [
        SUPPORT
    ]
    assert (
        scene[0].post(CONTEXT_URL, json=replacement, headers=accepted).status_code
        == 200
    )
    assert (
        scene[0].get(CONTEXT_URL, headers=accepted).json()["support_ontologies"] == []
    )


@pytest.mark.parametrize(
    "source_id",
    ["../../private/secret.txt", "file:///etc/passwd", "https://invalid.test/material"],
)
def test_source_identity_is_opaque_and_never_loaded_as_a_path_or_url(
    scene, manifest, monkeypatch, source_id
):
    def unexpected_read(*args, **kwargs):
        pytest.fail("HTTP context must not load a source path or URL")

    monkeypatch.setattr(SourceResourceRegistry, "register_file", unexpected_read)
    monkeypatch.setattr("pathlib.Path.read_bytes", unexpected_read)
    monkeypatch.setattr("pathlib.Path.read_text", unexpected_read)
    monkeypatch.setattr("urllib.request.urlopen", unexpected_read)
    manifest["business_ontologies"][0]["terms"][0]["source_id"] = source_id
    _register(scene, manifest)
    data = _related(scene)
    assert data["associations"] == []
    assert data["anchors"][0]["status"] == "source_missing"


def test_registration_and_queries_do_not_mutate_graph_or_assert_instance_types(
    scene, manifest
):
    _add_supporting_property(scene, manifest)
    graph = scene[1]
    before = deepcopy(graph.to_dict())
    _register(scene, manifest)
    _related(scene)
    _related(scene, BUSINESS + "requiresMaterials")
    scene[0].get(CONTEXT_URL)
    assert graph.to_dict() == before
    assert not any(
        edge.edge_type == "rdf:type" and edge.target_id == PURCHASE
        for edge in graph.edges
    )


@pytest.mark.parametrize(
    "changes", [{"start_char": -1}, {"start_char": 12, "end_char": 12}]
)
def test_intrinsically_invalid_span_is_rejected_before_context_replacement(
    scene, manifest, changes
):
    _register(scene, manifest)
    invalid = deepcopy(manifest)
    invalid["business_ontologies"][0]["terms"][0].update(changes)
    response = scene[0].post(CONTEXT_URL, json=invalid)
    assert response.status_code == 422, response.text
    assert [item["node_id"] for item in _related(scene)["associations"]] == [RULE]


@pytest.mark.parametrize("node_type", ["Entity", "SourceDocument"])
def test_has_evidence_target_must_really_be_an_evidence_node(
    scene, manifest, node_type
):
    scene[1].nodes[EVIDENCE].node_type = node_type
    _register(scene, manifest)
    assert _related(scene)["associations"] == []


def test_dangling_has_evidence_reference_does_not_create_an_association(
    scene, manifest
):
    del scene[1].nodes[EVIDENCE]
    _register(scene, manifest)
    assert _related(scene)["associations"] == []


@pytest.mark.parametrize(
    "changes",
    [
        {"source_id": None},
        {"source_sha256": None},
        {"quote": ["采购申请须审批。"]},
        {"start_char": "4"},
        {"end_char": 12.0},
    ],
)
def test_malformed_legacy_evidence_fields_fail_closed_without_server_error(
    scene, manifest, changes
):
    scene[1].nodes[EVIDENCE].metadata.update(changes)
    _register(scene, manifest)
    assert _related(scene)["associations"] == []


def test_source_markup_is_returned_as_json_text(scene, manifest):
    client, graph, resources = scene
    quote = "<script>alert('x')</script>"
    source = "😀\r\n<script>alert('x')</script>"
    assert source[3:30] == quote
    digest = resources.register_text("policy", source)
    manifest["business_ontologies"][0]["terms"][0].update(
        source_sha256=digest, start_char=3, end_char=30, quote=quote
    )
    graph.nodes[EVIDENCE].metadata.update(
        source_sha256=digest, start_char=3, end_char=30, quote=quote
    )
    graph.nodes[SOURCE].metadata["source_sha256"] = digest
    _register(scene, manifest)
    response = client.get(
        RELATED_URL, params={"ontology_uri": BUSINESS, "term_uri": PURCHASE}
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["associations"][0]["evidence"][0]["quote"] == quote


@pytest.mark.parametrize("invalid_source_id", [["policy"], {"id": "policy"}, 7, True])
def test_unrelated_malformed_source_identity_does_not_break_valid_rule_links(
    scene, manifest, invalid_source_id
):
    graph = scene[1]
    graph.add_node(
        "urn:rule:malformed-source",
        "ProcessRule",
        "来源身份损坏的无关规则",
        source_clause_id="C-invalid",
    )
    graph.add_node(
        "urn:evidence:malformed-source",
        "Evidence",
        "采购申请须审批。",
        clause_id="C-invalid",
        quote="采购申请须审批。",
        start_char=4,
        end_char=12,
        source_id=invalid_source_id,
        source_sha256=SHA,
    )
    graph.add_edge(
        "urn:rule:malformed-source", "urn:evidence:malformed-source", "hasEvidence"
    )
    _register(scene, manifest)

    data = _related(scene)

    assert data["status"] == "ready"
    assert [item["node_id"] for item in data["associations"]] == [RULE]
    assert [item["id"] for item in data["associations"][0]["evidence"]] == [EVIDENCE]


@pytest.mark.parametrize("field", ["fact_status", "review_status", "modality"])
@pytest.mark.parametrize(
    "invalid_value", [{"value": "candidate"}, ["candidate"], True, 7]
)
def test_malformed_rule_display_fields_are_returned_as_unknown(
    scene, manifest, field, invalid_value
):
    scene[1].nodes[RULE].metadata[field] = invalid_value
    _register(scene, manifest)

    data = _related(scene)

    assert data["status"] == "ready"
    assert len(data["associations"]) == 1
    assert data["associations"][0]["node_id"] == RULE
    assert data["associations"][0][field] is None
