"""Real session edits for explicitly owned ontology terms."""

from copy import deepcopy

import pytest

pytest.importorskip("fastapi")

from starlette.testclient import TestClient  # noqa: E402

from semantica.context.context_graph import ContextGraph  # noqa: E402
from semantica.explorer.app import create_app  # noqa: E402
from semantica.explorer.session import GraphSession  # noqa: E402

BUSINESS = "https://example.org/term-editing/"
OTHER = "https://example.org/external/"
CLASS = BUSINESS + "PurchaseRequest"
PARENT = BUSINESS + "Request"
APPROVER = BUSINESS + "Approver"
OBJECT = BUSINESS + "requiresApprovalBy"
DATA = BUSINESS + "requestCode"
EXTERNAL = OTHER + "ExternalRole"
XSD = "http://www.w3.org/2001/XMLSchema#"
URL = "/api/ontology/term"


@pytest.fixture
def scene():
    graph = ContextGraph(advanced_analytics=False)
    events = []
    graph.add_node(BUSINESS, "owl:Ontology", "业务本体")
    graph.add_node(OTHER, "owl:Ontology", "外部本体")
    for uri, label in ((CLASS, "采购申请"), (PARENT, "申请"), (APPROVER, "审批岗位")):
        graph.add_node(
            uri,
            "owl:Class",
            label,
            scheme_uri=BUSINESS,
            **{
                "rdfs:label": label,
                "rdfs:comment": "现有定义",
                "fact_status": "candidate",
                "review_status": "unreviewed",
                "unknown_metadata": {"preserve": [1, "原文😀"]},
            },
        )
    graph.add_node(EXTERNAL, "owl:Class", "外部岗位", scheme_uri=OTHER)
    for uri, kind, label in (
        (OBJECT, "owl:ObjectProperty", "需要审批"),
        (DATA, "owl:DatatypeProperty", "申请编号"),
    ):
        graph.add_node(
            uri,
            kind,
            label,
            scheme_uri=BUSINESS,
            **{
                "rdfs:label": label,
                "rdfs:comment": "属性定义",
                "fact_status": "candidate",
                "review_status": "unreviewed",
                "unknown_metadata": {"preserve": [1, "原文😀"]},
            },
        )
    graph.add_edge(OBJECT, CLASS, "rdfs:domain", id="object-domain", note="保留")
    graph.add_edge(OBJECT, APPROVER, "rdfs:range", id="object-range", note="保留")
    graph.add_edge(DATA, CLASS, "rdfs:domain", id="data-domain", note="保留")
    graph.add_edge(DATA, XSD + "string", "rdfs:range", id="data-range", note="保留")
    graph.add_node("urn:rule:original", "ProcessRule", "原候选规则", fact_status="candidate")
    graph.mutation_callback = lambda *event: events.append(event)
    session = GraphSession(graph)
    with TestClient(create_app(session=session)) as client:
        yield client, graph, session, events


def read_term(scene, term=CLASS, ontology=BUSINESS):
    response = scene[0].get(URL, params={"ontology_uri": ontology, "term_uri": term})
    assert response.status_code == 200, response.text
    return response.json()


def edit_payload(document, **changes):
    return {
        "expected_revision": document["revision"],
        **{
            key: document["term"][key]
            for key in ("label", "comment", "parents", "domain", "range")
        },
        **changes,
    }


def patch_term(scene, payload, term=CLASS, ontology=BUSINESS):
    return scene[0].patch(
        URL, params={"ontology_uri": ontology, "term_uri": term}, json=payload
    )


def test_saved_class_fields_change_the_loaded_graph_and_search(scene):
    client, graph, session, events = scene
    old_metadata = deepcopy(graph.nodes[CLASS].metadata)
    document = read_term(scene)
    assert document["scope"] == "session"
    assert document["term"] == {
        "id": CLASS,
        "type": "owl:Class",
        "label": "采购申请",
        "comment": "现有定义",
        "parents": [],
        "domain": [],
        "range": [],
    }
    response = patch_term(
        scene,
        edit_payload(document, label="采购请购单", comment="修改后的候选定义", parents=[PARENT]),
    )
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["changed"] is True
    assert saved["scope"] == "session"
    assert saved["revision"] != document["revision"]
    assert read_term(scene) == {
        key: value for key, value in saved.items() if key != "changed"
    }
    loaded = client.get("/api/ontology/graph", params={"uri": BUSINESS}).json()
    node = next(item for item in loaded["nodes"] if item["id"] == CLASS)
    assert node["content"] == "采购请购单"
    assert node["properties"]["rdfs:label"] == "采购请购单"
    assert node["properties"]["rdfs:comment"] == "修改后的候选定义"
    assert any(
        edge["source"] == CLASS
        and edge["target"] == PARENT
        and edge["type"] == "rdfs:subClassOf"
        for edge in loaded["edges"]
    )
    assert (
        graph.nodes[CLASS].metadata["unknown_metadata"]
        == old_metadata["unknown_metadata"]
    )
    assert graph.nodes[CLASS].metadata["fact_status"] == "candidate"
    assert graph.nodes[CLASS].metadata["review_status"] == "unreviewed"
    assert CLASS in {item["node"]["id"] for item in session.search("采购请购单")}
    assert "UPDATE_NODE" in {event[0] for event in events}


def test_object_property_changes_keep_unmodified_edge_identity_and_metadata(scene):
    _, graph, _, events = scene
    before_domain = deepcopy(
        next(edge.to_dict() for edge in graph.edges if edge.edge_id == "object-domain")
    )
    before_other = deepcopy(graph.nodes["urn:rule:original"])
    response = patch_term(
        scene,
        edit_payload(read_term(scene, OBJECT), label="需要责任岗位", range=[EXTERNAL]),
        OBJECT,
    )
    assert response.status_code == 200, response.text
    assert response.json()["term"]["domain"] == [CLASS]
    assert response.json()["term"]["range"] == [EXTERNAL]
    assert (
        next(edge.to_dict() for edge in graph.edges if edge.edge_id == "object-domain")
        == before_domain
    )
    assert graph.nodes["urn:rule:original"] == before_other
    assert not any(edge.edge_id == "object-range" for edge in graph.edges)
    assert "object-range" not in graph._edge_index
    assert all(
        edge.target_id != APPROVER
        for edge in graph.edge_type_index["rdfs:range"]
        if edge.source_id == OBJECT
    )
    added = next(
        edge
        for edge in graph.edges
        if edge.source_id == OBJECT and edge.target_id == EXTERNAL
    )
    assert graph._edge_index[added.edge_id] is added
    assert added in graph._adjacency[OBJECT]
    assert {event[0] for event in events} == {"UPDATE_NODE", "REMOVE_EDGE", "ADD_EDGE"}


def test_datatype_property_accepts_known_xsd_datatype_without_creating_a_node(scene):
    graph = scene[1]
    graph.add_node(XSD + "integer", "rdfs:Datatype", "整数")
    before_nodes = set(graph.nodes)
    response = patch_term(
        scene, edit_payload(read_term(scene, DATA), range=[XSD + "integer"]), DATA
    )
    assert response.status_code == 200, response.text
    assert response.json()["term"]["range"] == [XSD + "integer"]
    assert set(graph.nodes) == before_nodes
    loaded = scene[0].get("/api/ontology/graph", params={"uri": BUSINESS}).json()
    assert any(node["id"] == XSD + "integer" for node in loaded["nodes"])
    assert any(
        edge["source"] == DATA
        and edge["target"] == XSD + "integer"
        and edge["type"] == "rdfs:range"
        for edge in loaded["edges"]
    )


def test_unloaded_datatype_range_is_rejected_instead_of_creating_a_dangling_edge(scene):
    document = read_term(scene, DATA)
    before = deepcopy(scene[1].to_dict())
    response = patch_term(
        scene,
        edit_payload(document, label="不能保存", range=[XSD + "nonNegativeInteger"]),
        DATA,
    )
    assert response.status_code == 400, response.text
    assert "loaded" in response.json()["detail"]
    assert scene[1].to_dict() == before
    assert scene[3] == []


def test_noop_preserves_revision_graph_and_events(scene):
    document = read_term(scene, OBJECT)
    before = deepcopy(scene[1].to_dict())
    response = patch_term(scene, edit_payload(document), OBJECT)
    assert response.status_code == 200
    assert response.json()["changed"] is False
    assert response.json()["revision"] == document["revision"]
    assert scene[1].to_dict() == before
    assert scene[3] == []


@pytest.mark.parametrize("mutation", ["node", "edge", "immutable_metadata"])
def test_revision_covers_term_node_and_exact_schema_edges(scene, mutation):
    document = read_term(scene, OBJECT)
    graph = scene[1]
    if mutation == "node":
        graph.nodes[OBJECT].content = "并发修改"
    elif mutation == "immutable_metadata":
        graph.nodes[OBJECT].metadata["unknown_metadata"] = {"changed": True}
    else:
        next(edge for edge in graph.edges if edge.edge_id == "object-domain").metadata[
            "note"
        ] = "新元数据"
    before = deepcopy(graph.to_dict())
    response = patch_term(scene, edit_payload(document, label="过期覆盖"), OBJECT)
    assert response.status_code == 409, response.text
    assert graph.to_dict() == before


def test_unrelated_mutation_does_not_invalidate_a_term_revision(scene):
    document = read_term(scene)
    scene[1].add_node("urn:unrelated", "Entity", "不相关")
    response = patch_term(scene, edit_payload(document, comment="本次修改"))
    assert response.status_code == 200, response.text


@pytest.mark.parametrize(
    "term,changes",
    [
        (CLASS, {"parents": ["https://unknown.invalid/Unloaded"]}),
        (CLASS, {"parents": [CLASS]}),
        (CLASS, {"parents": [OBJECT]}),
        (CLASS, {"domain": [PARENT]}),
        (OBJECT, {"parents": [PARENT]}),
        (OBJECT, {"domain": [XSD + "string"]}),
        (OBJECT, {"range": [XSD + "string"]}),
        (DATA, {"range": [CLASS]}),
        (DATA, {"range": [XSD + "inventedDatatype"]}),
    ],
)
def test_invalid_semantics_never_partially_apply_other_valid_changes(
    scene, term, changes
):
    document = read_term(scene, term)
    before = deepcopy(scene[1].to_dict())
    response = patch_term(
        scene, edit_payload(document, label="不应写入", comment="也不应写入", **changes), term
    )
    assert response.status_code == 400, response.text
    assert scene[1].to_dict() == before
    assert scene[3] == []


def test_parent_change_rejects_a_cycle_through_existing_ancestors(scene):
    scene[1].add_edge(PARENT, APPROVER, "rdfs:subClassOf")
    scene[1].add_edge(
        APPROVER, CLASS, "http://www.w3.org/2000/01/rdf-schema#subClassOf"
    )
    scene[3].clear()
    before = deepcopy(scene[1].to_dict())
    response = patch_term(
        scene, edit_payload(read_term(scene), label="循环", parents=[PARENT])
    )
    assert response.status_code == 400
    assert scene[1].to_dict() == before
    assert scene[3] == []


def test_full_iri_types_and_schema_predicates_keep_their_original_form(scene):
    graph = scene[1]
    graph.nodes[OBJECT].node_type = "http://www.w3.org/2002/07/owl#ObjectProperty"
    edge = next(edge for edge in graph.edges if edge.edge_id == "object-domain")
    graph.edge_type_index[edge.edge_type].remove(edge)
    edge.edge_type = "http://www.w3.org/2000/01/rdf-schema#domain"
    graph.edge_type_index[edge.edge_type].append(edge)
    old_edge = deepcopy(edge.to_dict())
    document = read_term(scene, OBJECT)
    assert document["term"]["type"] == "owl:ObjectProperty"
    assert document["term"]["domain"] == [CLASS]
    response = patch_term(scene, edit_payload(document, label="新属性名"), OBJECT)
    assert response.status_code == 200
    assert (
        graph.nodes[OBJECT].node_type == "http://www.w3.org/2002/07/owl#ObjectProperty"
    )
    assert edge.to_dict() == old_edge


def test_ontology_graph_includes_full_iri_schema_edges_and_external_endpoints(scene):
    graph = scene[1]
    property_uri = BUSINESS + "fullIriProperty"
    graph.add_node(
        property_uri,
        "http://www.w3.org/2002/07/owl#ObjectProperty",
        "完整IRI属性",
        scheme_uri=BUSINESS,
    )
    expected = {
        "full-parent": (
            CLASS,
            PARENT,
            "http://www.w3.org/2000/01/rdf-schema#subClassOf",
        ),
        "full-domain": (
            property_uri,
            CLASS,
            "http://www.w3.org/2000/01/rdf-schema#domain",
        ),
        "full-range": (
            property_uri,
            EXTERNAL,
            "http://www.w3.org/2000/01/rdf-schema#range",
        ),
    }
    for edge_id, (source, target, predicate) in expected.items():
        graph.add_edge(source, target, predicate, id=edge_id, note="原始边元数据")
    before = deepcopy(graph.to_dict())

    response = scene[0].get("/api/ontology/graph", params={"uri": BUSINESS})
    assert response.status_code == 200, response.text
    document = response.json()
    returned_edges = {edge["id"]: edge for edge in document["edges"]}
    for edge_id, (source, target, predicate) in expected.items():
        assert edge_id in returned_edges
        edge = returned_edges[edge_id]
        assert (edge["source"], edge["target"], edge["type"]) == (
            source,
            target,
            predicate,
        )
        assert edge["properties"]["note"] == "原始边元数据"
    assert {CLASS, PARENT, property_uri, EXTERNAL} <= {
        node["id"] for node in document["nodes"]
    }
    assert graph.to_dict() == before


@pytest.mark.parametrize("term", [EXTERNAL, BUSINESS + "Absent"])
def test_external_or_missing_term_is_not_editable_in_selected_ontology(scene, term):
    response = scene[0].get(URL, params={"ontology_uri": BUSINESS, "term_uri": term})
    assert response.status_code == 404


def test_process_rule_cannot_be_edited_as_an_ontology_term(scene):
    scene[1].nodes["urn:rule:original"].metadata["scheme_uri"] = BUSINESS
    response = scene[0].get(
        URL, params={"ontology_uri": BUSINESS, "term_uri": "urn:rule:original"}
    )
    assert response.status_code == 400


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", "https://evil.invalid/Renamed"),
        ("type", "owl:Class"),
        ("scheme_uri", OTHER),
        ("fact_status", "accepted"),
        ("review_status", "approved"),
        ("source_sha256", "0" * 64),
        ("path", "/etc/passwd"),
        ("url", "https://evil.invalid/"),
    ],
)
def test_immutable_and_arbitrary_fields_are_rejected(scene, field, value):
    before = deepcopy(scene[1].to_dict())
    response = patch_term(scene, {**edit_payload(read_term(scene)), field: value})
    assert response.status_code == 422
    assert scene[1].to_dict() == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("label", "  "),
        ("label", {"value": "名称"}),
        ("comment", None),
        ("parents", "not-a-list"),
        ("domain", [True]),
        ("range", [1]),
        ("parents", [PARENT, PARENT]),
    ],
)
def test_editor_payload_requires_strict_text_and_reference_lists(scene, field, value):
    response = patch_term(scene, edit_payload(read_term(scene), **{field: value}))
    assert response.status_code == 422
    assert scene[3] == []


@pytest.mark.parametrize(
    "field", ["expected_revision", "label", "comment", "parents", "domain", "range"]
)
def test_editor_payload_requires_the_complete_current_snapshot(scene, field):
    payload = edit_payload(read_term(scene))
    del payload[field]
    assert patch_term(scene, payload).status_code == 422


def test_term_endpoints_share_api_key_authentication(scene, monkeypatch):
    document = read_term(scene)
    monkeypatch.delenv("SEMANTICA_ALLOW_ANONYMOUS", raising=False)
    monkeypatch.setenv("SEMANTICA_API_KEY", "term-test-key")
    params = {"ontology_uri": BUSINESS, "term_uri": CLASS}
    assert scene[0].get(URL, params=params).status_code == 401
    assert patch_term(scene, edit_payload(document)).status_code == 401
    response = scene[0].patch(
        URL,
        params=params,
        headers={"X-API-Key": "term-test-key"},
        json=edit_payload(document, label="认证后的名称"),
    )
    assert response.status_code == 200


def test_two_writers_with_one_revision_have_exactly_one_success(scene):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    document = read_term(scene)
    barrier = Barrier(2)

    def save(label):
        barrier.wait(timeout=5)
        return patch_term(scene, edit_payload(document, label=label)).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(save, "并发名称甲")
        second = pool.submit(save, "并发名称乙")
        assert sorted([first.result(timeout=10), second.result(timeout=10)]) == [
            200,
            409,
        ]
    assert read_term(scene)["term"]["label"] in {"并发名称甲", "并发名称乙"}
    assert [event[0] for event in scene[3]] == ["UPDATE_NODE"]


def test_changing_registered_definition_invalidates_old_evidence_context(scene):
    import hashlib

    text = "采购申请须审批。😀"
    sha = hashlib.sha256(text.encode()).hexdigest()
    scene[0].app.state.source_resources.register_text("material", text)
    context = {
        "schema_version": 1,
        "business_ontologies": [
            {
                "uri": BUSINESS,
                "terms": [
                    {
                        "uri": CLASS,
                        "label": "采购申请",
                        "type": "owl:Class",
                        "comment": "现有定义",
                        "domain": [],
                        "range": [],
                        "parents": [],
                        "source_id": "material",
                        "source_sha256": sha,
                        "start_char": 0,
                        "end_char": 8,
                        "quote": "采购申请须审批。",
                    }
                ],
            }
        ],
        "support_ontologies": [],
    }
    assert (
        scene[0].post("/api/ontology/evidence-context", json=context).status_code == 200
    )
    params = {"ontology_uri": BUSINESS, "term_uri": CLASS}
    assert (
        scene[0]
        .get("/api/ontology/related-rules", params=params)
        .json()["anchors"][0]["status"]
        == "aligned"
    )
    assert (
        patch_term(scene, edit_payload(read_term(scene), comment="修改后的定义")).status_code
        == 200
    )
    evidence = scene[0].get("/api/ontology/related-rules", params=params).json()
    assert evidence["status"] == "unavailable"
    assert evidence["anchors"][0]["status"] == "term_changed"
    assert evidence["associations"] == []


@pytest.mark.parametrize(
    "kind", ["rdfs:Class", "http://www.w3.org/2000/01/rdf-schema#Class"]
)
def test_rdfs_class_edits_preserve_stored_type_and_return_canonical_class(scene, kind):
    graph = scene[1]
    graph.nodes[CLASS].node_type = kind
    document = read_term(scene)
    assert document["term"]["type"] == "owl:Class"
    response = patch_term(
        scene, edit_payload(document, label="RDFS采购申请", parents=[PARENT])
    )
    assert response.status_code == 200, response.text
    assert response.json()["term"]["parents"] == [PARENT]
    assert graph.nodes[CLASS].node_type == kind


@pytest.mark.parametrize("compact_also_exists", [False, True])
def test_full_iri_annotations_are_read_and_kept_consistent_when_changed(
    scene, compact_also_exists
):
    graph = scene[1]
    namespace = "http://www.w3.org/2000/01/rdf-schema#"
    for container in (graph.nodes[CLASS].properties, graph.nodes[CLASS].metadata):
        container[namespace + "comment"] = "现有定义"
        container[namespace + "label"] = "采购申请"
        if not compact_also_exists:
            container.pop("rdfs:comment", None)
            container.pop("rdfs:label", None)
    document = read_term(scene)
    assert document["term"]["comment"] == "现有定义"
    response = patch_term(scene, edit_payload(document, label="新名称", comment="新定义"))
    assert response.status_code == 200, response.text
    for container in (graph.nodes[CLASS].properties, graph.nodes[CLASS].metadata):
        assert container[namespace + "comment"] == "新定义"
        assert container[namespace + "label"] == "新名称"
        assert container["rdfs:comment"] == "新定义"
        assert container["rdfs:label"] == "新名称"


@pytest.mark.parametrize("reference", ["https://[broken", "https://[not-an-ipv6]/Role"])
def test_malformed_reference_iri_is_a_client_error_with_no_mutation(scene, reference):
    document = read_term(scene)
    before = deepcopy(scene[1].to_dict())
    response = patch_term(
        scene, edit_payload(document, label="不应保存", parents=[reference])
    )
    assert response.status_code == 400, response.text
    assert scene[1].to_dict() == before
    assert scene[3] == []


@pytest.mark.parametrize("kind", [["owl:Class"], {"type": "owl:Class"}, True, 7])
def test_malformed_reference_node_type_is_rejected_without_partial_changes(scene, kind):
    scene[1].nodes[PARENT].node_type = kind
    document = read_term(scene)
    before = deepcopy(scene[1].to_dict())
    response = patch_term(scene, edit_payload(document, label="不应保存", parents=[PARENT]))
    assert response.status_code == 400, response.text
    assert scene[1].to_dict() == before
    assert scene[3] == []


@pytest.mark.parametrize("kind", [["owl:Class"], {"type": "owl:Class"}, True, 7])
def test_malformed_selected_node_type_is_rejected(scene, kind):
    scene[1].nodes[CLASS].node_type = kind
    response = scene[0].get(URL, params={"ontology_uri": BUSINESS, "term_uri": CLASS})
    assert response.status_code == 400


def test_internal_commit_failure_rolls_back_every_local_index_without_events(scene):
    graph = scene[1]
    document = read_term(scene, OBJECT)
    before = deepcopy(graph.to_dict())
    before_adjacency = {key: list(value) for key, value in graph._adjacency.items()}
    before_buckets = {key: list(value) for key, value in graph.edge_type_index.items()}
    before_identities = dict(graph._edge_index)
    graph._analytics_cache = {"existing": "cached"}

    class FailOnceOnNewEdge(dict):
        failed = False

        def __setitem__(self, key, value):
            if key.startswith("ontology-term:") and not self.failed:
                self.failed = True
                raise RuntimeError("Simulated edge index write failure")
            return super().__setitem__(key, value)

    graph._edge_index = FailOnceOnNewEdge(graph._edge_index)
    with pytest.raises(RuntimeError, match="Simulated edge index write failure"):
        patch_term(
            scene, edit_payload(document, label="不能部分保存", range=[EXTERNAL]), OBJECT
        )
    assert graph.to_dict() == before
    assert dict(graph._adjacency) == before_adjacency
    assert dict(graph.edge_type_index) == before_buckets
    assert dict(graph._edge_index) == before_identities
    assert graph._analytics_cache == {"existing": "cached"}
    assert read_term(scene, OBJECT)["revision"] == document["revision"]
    assert scene[3] == []


def test_mutation_observers_see_complete_graph_after_its_lock_is_released(scene):
    graph = scene[1]
    previous = graph.mutation_callback
    observations = []

    def observe(*event):
        assert not graph._lock._is_owned()
        assert graph.nodes[OBJECT].content == "新审批关系"
        assert "object-range" not in graph._edge_index
        new_edge = next(
            edge for edge in graph._adjacency[OBJECT] if edge.target_id == EXTERNAL
        )
        assert graph._edge_index[new_edge.edge_id] is new_edge
        assert new_edge in graph.edge_type_index["rdfs:range"]
        observations.append(event[0])
        previous(*event)

    graph.mutation_callback = observe
    response = patch_term(
        scene,
        edit_payload(read_term(scene, OBJECT), label="新审批关系", range=[EXTERNAL]),
        OBJECT,
    )
    assert response.status_code == 200, response.text
    assert set(observations) == {"UPDATE_NODE", "REMOVE_EDGE", "ADD_EDGE"}


def test_successive_revisions_publish_events_in_commit_order(scene, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    graph, session = scene[1:3]
    first_committed = Event()
    release_first_event = Event()
    second_finished = Event()
    original_emit = graph._emit_mutation

    def delayed_emit(operation, entity_id, payload):
        if (
            operation == "UPDATE_NODE"
            and payload["properties"]["content"] == "alphaword"
        ):
            first_committed.set()
            assert release_first_event.wait(timeout=5)
        original_emit(operation, entity_id, payload)

    monkeypatch.setattr(graph, "_emit_mutation", delayed_emit)
    initial = read_term(scene)

    def save_second(document):
        try:
            return patch_term(scene, edit_payload(document, label="omegaword"))
        finally:
            second_finished.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(patch_term, scene, edit_payload(initial, label="alphaword"))
        try:
            assert first_committed.wait(timeout=5)
            second = pool.submit(save_second, read_term(scene))
            # Let an incorrectly unsynchronized writer publish before the first.
            # A serialized writer waits here until the event gate is released.
            second_finished.wait(timeout=1)
        finally:
            release_first_event.set()
        assert first.result(timeout=5).status_code == 200
        assert second.result(timeout=5).status_code == 200

    assert read_term(scene)["term"]["label"] == "omegaword"
    assert session.search("alphaword") == []
    assert CLASS in {item["node"]["id"] for item in session.search("omegaword")}
    assert [event[2]["properties"]["content"] for event in scene[3]] == [
        "alphaword",
        "omegaword",
    ]
