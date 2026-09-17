"""Source material stays explicit, verifiable, and separate from graph trust."""

import hashlib
import json

import pytest

pytest.importorskip("fastapi")

from starlette.testclient import TestClient  # noqa: E402

from semantica.context.context_graph import ContextGraph  # noqa: E402
from semantica.explorer.app import create_app  # noqa: E402
from semantica.explorer.session import GraphSession  # noqa: E402

TEXT = "前言😀\n审批。\n再次审批。\n<script>alert(1)</script>"
SHA = hashlib.sha256(TEXT.encode("utf-8")).hexdigest()
RULE = "https://example.test/rule/1"
EVIDENCE = "https://example.test/evidence/1"
SOURCE = "https://example.test/source/1"


def make_graph():
    graph = ContextGraph(advanced_analytics=False)
    graph.add_node(
        RULE,
        "ProcessRule",
        "采购审批",
        source_clause_id="C2",
        supporting_clause_ids=["C1"],
        fact_status="candidate",
        review_status="unreviewed",
    )
    graph.add_node(
        EVIDENCE,
        "Evidence",
        "再次审批。",
        clause_id="C2",
        quote="审批。",
        start_char=10,
        end_char=13,
        source_id="policy",
        source_sha256=SHA,
        fact_status="candidate",
        review_status="unreviewed",
    )
    graph.add_node(
        "support",
        "Evidence",
        "前文审批",
        clause_id="C1",
        quote="😀\n审批。",
        start_char=2,
        end_char=7,
        source_id="policy",
        source_sha256=SHA,
        fact_status="candidate",
        review_status="unreviewed",
    )
    graph.add_node(
        SOURCE,
        "SourceDocument",
        "policy",
        source_id="policy",
        source_sha256=SHA,
        fact_status="candidate",
        review_status="unreviewed",
    )
    graph.add_node("legacy", "Note", "Legacy content")
    graph.add_edge(RULE, EVIDENCE, "hasEvidence", id="has-evidence")
    graph.add_edge(RULE, "support", "hasEvidence", id="has-support")
    graph.add_edge(EVIDENCE, SOURCE, "fromSource", id="from-source")
    graph.add_edge("support", SOURCE, "fromSource", id="support-source")
    graph.add_edge(RULE, "legacy", "hasActor", id="unrelated")
    return graph


def test_unregistered_material_reports_missing_instead_of_absent_route():
    with TestClient(create_app(session=GraphSession(make_graph()))) as client:
        response = client.get("/api/sources/view", params={"node_id": RULE})

    assert response.status_code == 200
    view = response.json()
    assert view["status"] == "ok"
    assert view["sources"][0]["status"] == "source_missing"
    assert view["sources"][0]["text"] is None
    assert all(item["status"] == "source_missing" for item in view["evidence"])


@pytest.fixture
def sources_client():
    from semantica.explorer.source_resources import SourceResourceRegistry

    graph = make_graph()
    resources = SourceResourceRegistry()
    resources.register_text("policy", TEXT, title="采购制度", version="v1")
    app = create_app(session=GraphSession(graph), source_resources=resources)
    with TestClient(app) as client:
        yield client, graph, resources


def test_rule_exposes_primary_and_supporting_unicode_evidence(sources_client):
    client, graph, _ = sources_client
    before = graph.find_node(EVIDENCE)
    response = client.get("/api/sources/view", params={"node_id": RULE})
    assert response.status_code == 200
    view = response.json()
    assert view["selection"] == {"kind": "node", "id": RULE, "label": "采购审批"}
    assert [(e["id"], e["role"], e["status"]) for e in view["evidence"]] == [
        (EVIDENCE, "primary", "aligned"),
        ("support", "supporting", "aligned"),
    ]
    assert view["evidence"][0]["start_char"] == 10
    assert view["evidence"][1]["quote"] == "😀\n审批。"
    assert view["sources"][0]["text"] == TEXT
    assert view["sources"][0]["character_count"] == len(TEXT)
    assert view["sources"][0]["source_sha256"] == SHA
    assert view["sources"][0]["actual_sha256"] == SHA
    assert view["sources"][0]["title"] == "采购制度"
    assert view["sources"][0]["version"] == "v1"
    assert view["sources"][0]["source_uri"] is None
    assert all(e["fact_status"] == "candidate" for e in view["evidence"])
    assert all(e["review_status"] == "unreviewed" for e in view["evidence"])
    assert graph.find_node(EVIDENCE) == before
    assert response.headers["content-type"].startswith("application/json")


@pytest.mark.parametrize("node_id", [EVIDENCE, SOURCE])
def test_evidence_and_source_document_open_same_full_text(sources_client, node_id):
    client, _, _ = sources_client
    view = client.get("/api/sources/view", params={"node_id": node_id}).json()
    assert view["sources"][0]["text"] == TEXT
    assert view["sources"][0]["status"] == "available"
    assert len(view["evidence"]) == (1 if node_id == EVIDENCE else 0)


@pytest.mark.parametrize(
    ("changes", "status"),
    [
        ({"source_sha256": "0" * 64}, "hash_mismatch"),
        ({"start_char": -1}, "invalid_offsets"),
        ({"end_char": 999}, "invalid_offsets"),
        ({"end_char": 10}, "invalid_offsets"),
        ({"start_char": True}, "invalid_offsets"),
        ({"start_char": "10"}, "invalid_offsets"),
        ({"end_char": 13.0}, "invalid_offsets"),
        ({"quote": "different"}, "quote_mismatch"),
        ({"quote": ["审批。"]}, "invalid_evidence"),
        ({"source_id": ["policy"]}, "invalid_evidence"),
        ({"source_sha256": {"bad": "hash"}}, "invalid_evidence"),
        ({"source_sha256": ""}, "invalid_evidence"),
    ],
)
def test_invalid_evidence_never_claims_alignment(sources_client, changes, status):
    client, graph, _ = sources_client
    # Remove the link so each case independently tests the evidence contract.
    graph.edges[:] = [e for e in graph.edges if e.edge_id != "from-source"]
    graph.nodes[EVIDENCE].metadata.update(changes)
    view = client.get("/api/sources/view", params={"node_id": EVIDENCE}).json()
    assert view["evidence"][0]["status"] == status
    assert view["evidence"][0]["reason"]
    if status == "hash_mismatch":
        assert view["sources"][0]["text"] is None


def test_from_source_identity_conflict_is_not_aligned(sources_client):
    client, graph, _ = sources_client
    graph.nodes[SOURCE].metadata["source_id"] = "another-policy"
    view = client.get("/api/sources/view", params={"node_id": EVIDENCE}).json()
    assert view["evidence"][0]["status"] == "source_mismatch"
    assert view["evidence"][0]["reason"]


def test_conflicting_additional_source_link_fails_closed(sources_client):
    client, graph, _ = sources_client
    graph.add_node(
        "conflicting-source",
        "SourceDocument",
        source_id="other",
        source_sha256=SHA,
    )
    graph.add_edge(EVIDENCE, "conflicting-source", "fromSource")
    view = client.get("/api/sources/view", params={"node_id": EVIDENCE}).json()
    assert view["evidence"][0]["status"] == "source_mismatch"


@pytest.mark.parametrize("invalid_hash", [None, [], {}, True, "bad hash"])
def test_source_document_invalid_hash_never_selects_a_revision(
    sources_client, invalid_hash
):
    client, graph, _ = sources_client
    graph.nodes[SOURCE].metadata["source_sha256"] = invalid_hash
    response = client.get("/api/sources/view", params={"node_id": SOURCE})
    assert response.status_code == 200
    source = response.json()["sources"][0]
    assert source["status"] in {"source_missing", "hash_mismatch"}
    assert source["text"] is None
    assert source["version"] is None
    assert source["reason"]


@pytest.mark.parametrize("edge_id", ["has-evidence", "from-source"])
def test_evidence_relationships_have_explicit_source_access(sources_client, edge_id):
    client, _, _ = sources_client
    view = client.get("/api/sources/view", params={"edge_id": edge_id}).json()
    assert view["selection"]["kind"] == "edge"
    assert [e["id"] for e in view["evidence"]] == [EVIDENCE]
    assert view["sources"][0]["text"] == TEXT


def test_unrelated_relationship_does_not_infer_evidence_from_rule(sources_client):
    client, _, _ = sources_client
    view = client.get("/api/sources/view", params={"edge_id": "unrelated"}).json()
    assert view["status"] == "no_evidence"
    assert view["evidence"] == []
    assert view["sources"] == []


def test_relationship_can_explicitly_reference_evidence(sources_client):
    client, graph, _ = sources_client
    graph.add_edge(
        RULE, "legacy", "supports", id="explicit", evidence_ids=[EVIDENCE, "support"]
    )
    view = client.get("/api/sources/view", params={"edge_id": "explicit"}).json()
    assert [e["id"] for e in view["evidence"]] == [EVIDENCE, "support"]
    assert len(view["sources"]) == 1


def test_dangling_or_wrong_type_evidence_is_reported(sources_client):
    client, graph, _ = sources_client
    graph.add_edge(
        RULE,
        "legacy",
        "supports",
        id="bad-reference",
        evidence_ids=["missing", "legacy"],
    )
    view = client.get("/api/sources/view", params={"edge_id": "bad-reference"}).json()
    assert [e["status"] for e in view["evidence"]] == [
        "invalid_evidence",
        "invalid_evidence",
    ]
    assert all(e["reason"] for e in view["evidence"])
    assert view["sources"] == []


def test_malformed_evidence_references_have_distinct_selection_ids(sources_client):
    client, graph, _ = sources_client
    graph.add_edge(
        RULE,
        "legacy",
        "supports",
        id="malformed-references",
        evidence_ids=[None, [], {}, True],
    )
    view = client.get(
        "/api/sources/view", params={"edge_id": "malformed-references"}
    ).json()
    ids = [e["id"] for e in view["evidence"]]
    assert len(ids) == len(set(ids))
    assert all(e["status"] == "invalid_evidence" for e in view["evidence"])
    assert view["sources"] == []


def test_legacy_and_sequential_selections_do_not_retain_previous_text(sources_client):
    client, _, _ = sources_client
    assert client.get("/api/sources/view", params={"node_id": RULE}).json()["sources"]
    legacy = client.get("/api/sources/view", params={"node_id": "legacy"}).json()
    assert legacy["status"] == "no_evidence"
    assert legacy["sources"] == []
    assert legacy["evidence"] == []


def test_two_sources_and_versions_remain_isolated(sources_client):
    client, graph, resources = sources_client
    second = "其他材料"
    second_sha = hashlib.sha256(second.encode()).hexdigest()
    resources.register_text("second", second)
    resources.register_text("policy", "新版本")
    graph.add_node(
        "second-evidence",
        "Evidence",
        quote="材料",
        start_char=2,
        end_char=4,
        source_id="second",
        source_sha256=second_sha,
    )
    graph.add_edge(RULE, "second-evidence", "hasEvidence")
    view = client.get("/api/sources/view", params={"node_id": RULE}).json()
    assert {s["source_id"]: s["text"] for s in view["sources"]} == {
        "policy": TEXT,
        "second": second,
    }
    assert all(e["status"] == "aligned" for e in view["evidence"])
    assert view["sources"][1]["version"] is None


def test_source_api_cannot_read_paths_or_fetch_urls(sources_client, tmp_path):
    client, graph, _ = sources_client
    secret = tmp_path / "secret.txt"
    secret.write_text("private-unregistered-material")
    for source_id in [
        str(secret),
        "../../secret.txt",
        "file://" + str(secret),
        "https://example.test/private",
    ]:
        graph.nodes[SOURCE].metadata["source_id"] = source_id
        view = client.get(
            "/api/sources/view",
            params={"node_id": SOURCE, "path": str(secret), "url": source_id},
        ).json()
        assert view["sources"][0]["status"] == "source_missing"
        assert view["sources"][0]["text"] is None
        assert "private-unregistered-material" not in json.dumps(view)
    assert (
        client.get("/api/sources/view", params={"path": str(secret)}).status_code == 422
    )


def test_source_view_requires_authentication(sources_client, monkeypatch):
    client, _, _ = sources_client
    monkeypatch.setenv("SEMANTICA_ALLOW_ANONYMOUS", "false")
    monkeypatch.setenv("SEMANTICA_API_KEY", "source-test-key")
    assert (
        client.get("/api/sources/view", params={"node_id": SOURCE}).status_code == 401
    )
    response = client.get(
        "/api/sources/view",
        params={"node_id": SOURCE},
        headers={"X-API-Key": "source-test-key"},
    )
    assert response.status_code == 200
    assert response.json()["sources"][0]["text"] == TEXT


@pytest.mark.parametrize("params", [{}, {"node_id": RULE, "edge_id": "unrelated"}])
def test_selection_must_be_unambiguous(sources_client, params):
    client, _, _ = sources_client
    assert client.get("/api/sources/view", params=params).status_code == 422


@pytest.mark.parametrize("params", [{"node_id": "missing"}, {"edge_id": "missing"}])
def test_missing_selection_returns_404(sources_client, params):
    client, _, _ = sources_client
    assert client.get("/api/sources/view", params=params).status_code == 404
