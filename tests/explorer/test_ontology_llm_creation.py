"""Hub creation consumes the native LLM ontology DTO without reminting terms."""

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

pytest.importorskip("fastapi")

from starlette.testclient import TestClient  # noqa: E402

from semantica.context.context_graph import ContextGraph  # noqa: E402
from semantica.explorer.app import create_app  # noqa: E402
from semantica.explorer.routes.ontology import OntologyEntry  # noqa: E402
from semantica.explorer.session import GraphSession  # noqa: E402
from semantica.utils.exceptions import ValidationError  # noqa: E402

BASE = "https://example.org/business/"
XSD_STRING = "http://www.w3.org/2001/XMLSchema#string"
RDF = '@prefix ex: <https://example.org/process/> . ex:doc ex:name "合法有效的合同" .'
SOURCE = "付款申请应提供合法有效的合同。"


@pytest.fixture
def scene():
    graph = ContextGraph(advanced_analytics=False)
    graph.add_node("existing", "entity", "Existing material")
    session = GraphSession(graph)
    app = create_app(session=session)
    app.state.ontology_registry = {}
    with TestClient(app) as client:
        yield client, session, app


@pytest.fixture
def proposal():
    return {
        "uri": BASE,
        "name": "供应商材料本体",
        "version": "invented-model-version",
        "classes": [
            {
                "name": "Document",
                "uri": BASE + "Document",
                "label": "材料",
                "comment": "付款申请所需材料的类型。",
                "subClassOf": None,
            },
            {
                "name": "Contract",
                "uri": BASE + "Contract",
                "label": "合同",
                "comment": "付款申请要求的合同类型。",
                "subClassOf": BASE + "Document",
            },
        ],
        "properties": [
            {
                "name": "requiresDocument",
                "uri": BASE + "requiresDocument",
                "label": "需要材料",
                "comment": "关联所要求的材料类型。",
                "type": "object",
                "domain": [BASE + "Contract", BASE + "Document"],
                "range": [BASE + "Document"],
            },
            {
                "name": "documentName",
                "uri": BASE + "documentName",
                "label": "材料名称",
                "comment": "材料的文字名称。",
                "type": "data",
                "domain": [BASE + "Document"],
                "range": [XSD_STRING],
            },
        ],
        "metadata": {"fact_status": "candidate", "review_status": "unreviewed"},
    }


def stub_engine(monkeypatch, result):
    calls = []

    class GenerationBoundary:
        def __init__(self, **config):
            pass

        def from_rdf(self, data, **options):
            calls.append(("rdf", data, options))
            if isinstance(result, Exception):
                raise result
            return deepcopy(result)

        def from_text(self, text, **options):
            calls.append(("text", text, options))
            if isinstance(result, Exception):
                raise result
            return deepcopy(result)

    monkeypatch.setattr("semantica.ontology.OntologyEngine", GenerationBoundary)
    return calls


@pytest.mark.parametrize("mode", ["data", "text"])
def test_native_proposal_keeps_term_identity_and_candidate_semantics(
    scene, proposal, monkeypatch, mode
):
    client, session, _ = scene
    calls = stub_engine(monkeypatch, proposal)
    response = client.post(
        "/api/ontology/create",
        json={
            "mode": mode,
            "namespace": BASE,
            "name": "供应商材料本体",
            "description": "从材料要求生成的候选本体。",
            "sample_data": RDF,
            "schema_text": SOURCE,
            "source_text": SOURCE,
            "provider": "openai",
            "model": "test-model",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "status": "success",
        "uri": BASE,
        "name": "供应商材料本体",
        "nodes_added": 5,
        "edges_added": 6,
        "format": "turtle",
    }
    for suffix, label, comment, node_type in (
        ("Document", "材料", "付款申请所需材料的类型。", "owl:Class"),
        ("Contract", "合同", "付款申请要求的合同类型。", "owl:Class"),
        (
            "requiresDocument",
            "需要材料",
            "关联所要求的材料类型。",
            "owl:ObjectProperty",
        ),
        ("documentName", "材料名称", "材料的文字名称。", "owl:DatatypeProperty"),
    ):
        node = session.get_node(BASE + suffix)
        assert node["type"] == node_type
        assert node["content"] == label
        assert node["properties"]["rdfs:comment"] == comment
        assert node["properties"]["scheme_uri"] == BASE
        assert node["properties"]["fact_status"] == "candidate"
        assert node["properties"]["review_status"] == "unreviewed"
    root = session.get_node(BASE)
    assert root["properties"]["fact_status"] == "candidate"
    assert root["properties"]["review_status"] == "unreviewed"

    edges, _ = session.get_edges()
    assert {(e["source"], e["type"], e["target"]) for e in edges} == {
        (BASE + "Contract", "rdfs:subClassOf", BASE + "Document"),
        (BASE + "requiresDocument", "rdfs:domain", BASE + "Contract"),
        (BASE + "requiresDocument", "rdfs:domain", BASE + "Document"),
        (BASE + "requiresDocument", "rdfs:range", BASE + "Document"),
        (BASE + "documentName", "rdfs:domain", BASE + "Document"),
        (BASE + "documentName", "rdfs:range", XSD_STRING),
    }
    assert all(e["properties"]["fact_status"] == "candidate" for e in edges)
    assert all(e["properties"]["review_status"] == "unreviewed" for e in edges)
    entry = client.get("/api/ontology/registry").json()[0]
    assert entry["uri"] == BASE
    assert entry["version"] is None
    assert entry["status"] == "draft"
    assert entry["class_count"] == 2
    assert entry["property_count"] == 2

    method, content, options = calls.pop()
    assert not calls
    assert method == ("rdf" if mode == "data" else "text")
    assert content == (RDF if mode == "data" else SOURCE)
    assert options["name"] == "供应商材料本体"
    assert options["base_uri"] == BASE
    assert options["provider"] == "openai"
    assert options["model"] == "test-model"
    if mode == "data":
        assert options["source_text"] == SOURCE
        assert options["rdf_format"] == "turtle"


@pytest.mark.parametrize(
    "mode,field", [("data", "sample_data"), ("text", "schema_text")]
)
@pytest.mark.parametrize("content", [None, "", " \n\t"])
def test_empty_generation_input_is_rejected_before_generation(
    scene, proposal, monkeypatch, mode, field, content
):
    client, session, app = scene
    before = (session.get_nodes(), session.get_edges())
    calls = stub_engine(monkeypatch, proposal)

    response = client.post(
        "/api/ontology/create",
        json={"mode": mode, "namespace": BASE, "name": "材料本体", field: content},
    )

    assert response.status_code == 422
    assert not calls
    assert (session.get_nodes(), session.get_edges()) == before
    assert app.state.ontology_registry == {}


@pytest.mark.parametrize("mode", ["data", "text"])
@pytest.mark.parametrize(
    "error,status,detail",
    [
        (RuntimeError, 500, "Ontology generation failed."),
        (ValidationError, 422, "Ontology generation input or output is invalid."),
    ],
)
def test_generation_failure_is_controlled_and_does_not_mutate_graph(
    scene, monkeypatch, caplog, mode, error, status, detail
):
    client, session, app = scene
    before = (session.get_nodes(), session.get_edges())
    secret = "provider-secret-token-DO-NOT-LEAK"
    stub_engine(monkeypatch, error(f"Remote provider error: {secret}"))

    response = client.post(
        "/api/ontology/create",
        json={
            "mode": mode,
            "namespace": BASE,
            "name": "材料本体",
            "sample_data": RDF,
            "schema_text": SOURCE,
        },
    )

    assert response.status_code == status
    assert response.json() == {"detail": detail}
    assert secret not in caplog.text
    assert (session.get_nodes(), session.get_edges()) == before
    assert app.state.ontology_registry == {}


@pytest.mark.parametrize(
    "result",
    [
        None,
        {},
        {"uri": BASE, "classes": [], "properties": []},
        {"uri": BASE, "classes": [{"name": "Contract"}], "properties": []},
        {
            "uri": BASE,
            "classes": [{"uri": BASE + "Contract"}],
            "properties": "malformed",
        },
    ],
)
def test_invalid_generation_result_cannot_create_an_empty_or_partial_ontology(
    scene, monkeypatch, result
):
    client, session, app = scene
    before = (session.get_nodes(), session.get_edges())
    stub_engine(monkeypatch, result)

    response = client.post(
        "/api/ontology/create",
        json={"mode": "data", "namespace": BASE, "name": "材料本体", "sample_data": RDF},
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": "Ontology generation input or output is invalid."
    }
    assert (session.get_nodes(), session.get_edges()) == before
    assert app.state.ontology_registry == {}


def test_scratch_creation_keeps_its_existing_empty_draft_contract(scene, monkeypatch):
    client, session, _ = scene
    calls = stub_engine(monkeypatch, RuntimeError("Must not generate scratch ontology"))

    response = client.post(
        "/api/ontology/create",
        json={"mode": "scratch", "namespace": BASE, "name": "Empty draft"},
    )

    assert response.status_code == 200
    assert response.json()["uri"] == BASE.rstrip("/") + "#ontology"
    assert response.json()["nodes_added"] == 1
    assert response.json()["edges_added"] == 0
    assert not calls
    assert session.get_node(response.json()["uri"])["content"] == "Empty draft"
    entry = client.get("/api/ontology/registry").json()[0]
    assert entry["status"] == "draft"
    assert entry["version"] == "0.1.0"


@pytest.mark.parametrize("source_text", ["", SOURCE])
def test_real_native_rdf_engine_connects_to_hub_with_optional_source(
    scene, monkeypatch, source_text
):
    client, session, _ = scene
    doc = "https://example.org/process/doc"
    class_uri = "https://example.org/process/RequiredDocument"
    property_uri = "https://example.org/process/name"
    proposal = {
        "classes": [
            {
                "name": "RequiredDocument",
                "uri": class_uri,
                "label": "材料要求",
                "comment": "规则所要求的材料，不代表具体合同已存在。",
                "subClassOf": None,
                "evidence_nodes": [doc],
            }
        ],
        "properties": [
            {
                "name": "name",
                "uri": property_uri,
                "label": "名称",
                "comment": "材料要求的原文名称。",
                "type": "data",
                "domain": [class_uri],
                "range": [XSD_STRING],
            }
        ],
    }
    generations = []

    class Provider:
        def generate_structured(self, prompt, **options):
            generations.append((prompt, options))
            return deepcopy(proposal)

    monkeypatch.setattr(
        "semantica.ontology.llm_generator.create_provider", lambda *_a, **_k: Provider()
    )
    response = client.post(
        "/api/ontology/create",
        json={
            "mode": "data",
            "namespace": BASE,
            "name": "材料候选本体",
            "sample_data": RDF + f" <{doc}> a <{class_uri}> .",
            "source_text": source_text,
            "model": "test-model",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["uri"] == BASE
    node = session.get_node(class_uri)
    assert node["content"] == "材料要求"
    assert node["properties"]["fact_status"] == "candidate"
    assert node["properties"]["review_status"] == "unreviewed"
    assert len(generations) == 1
    assert generations[0][1]["model"] == "test-model"
    assert "材料候选本体" in generations[0][0]
    assert doc in generations[0][0]
    assert session.get_node(property_uri)["content"] == "名称"
    assert session.get_node(BASE + "Contract") is None
    # Creating a schema does not fabricate a live input node or rdf:type claim.
    assert session.get_node(doc) is None
    assert all(
        edge["source"] != doc and edge["target"] != doc
        for edge in session.get_edges()[0]
    )


def test_malformed_turtle_is_rejected_by_native_engine_without_provider_call(
    scene, monkeypatch
):
    client, session, app = scene
    before = (session.get_nodes(), session.get_edges())

    class Provider:
        def generate_structured(self, *_args, **_options):
            pytest.fail("Malformed Turtle must not reach the provider")

    monkeypatch.setattr(
        "semantica.ontology.llm_generator.create_provider", lambda *_a, **_k: Provider()
    )
    response = client.post(
        "/api/ontology/create",
        json={
            "mode": "data",
            "namespace": BASE,
            "name": "材料候选本体",
            "sample_data": '{"name": "not Turtle RDF"}',
        },
    )

    assert response.status_code == 422
    assert (session.get_nodes(), session.get_edges()) == before
    assert app.state.ontology_registry == {}


@pytest.mark.parametrize("collision", ["class", "property", "ontology", "registry"])
def test_rdf_generation_rejects_existing_identities_without_partial_mutation(
    scene, proposal, monkeypatch, collision
):
    client, session, app = scene
    uri, kind = {
        "class": (BASE + "Document", "owl:Class"),
        "property": (BASE + "documentName", "owl:DatatypeProperty"),
        "ontology": (BASE, "owl:Ontology"),
        "registry": (BASE, "owl:Ontology"),
    }[collision]
    if collision == "registry":
        app.state.ontology_registry[uri] = OntologyEntry(
            uri=uri,
            name="Existing reviewed schema",
            status="external",
            version="saved-version",
        )
    else:
        session.add_node(
            uri,
            kind,
            "用户编辑的名称",
            **{
                "rdfs:label": "用户编辑的名称",
                "domain_expressions": [
                    {
                        "kind": "unionOf",
                        "members": [BASE + "Document", "urn:other:Role"],
                    }
                ],
            },
        )
    before = deepcopy(
        (session.get_nodes(), session.get_edges(), app.state.ontology_registry)
    )
    revision = session._graph_revision
    stub_engine(monkeypatch, proposal)

    response = client.post(
        "/api/ontology/create",
        json={
            "mode": "data",
            "namespace": BASE,
            "name": "New draft",
            "sample_data": RDF,
        },
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "ontology_identity_conflict"
    assert response.json()["detail"]["conflicts"] == [uri]
    assert (
        session.get_nodes(),
        session.get_edges(),
        app.state.ontology_registry,
    ) == before
    assert session._graph_revision == revision


def test_second_rdf_generation_keeps_the_first_complete_draft(
    scene, proposal, monkeypatch
):
    client, session, app = scene
    stub_engine(monkeypatch, proposal)
    body = {
        "mode": "data",
        "namespace": BASE,
        "name": "First draft",
        "sample_data": RDF,
    }
    first = client.post("/api/ontology/create", json=body)
    assert first.status_code == 200, first.text
    before = deepcopy(
        (session.get_nodes(), session.get_edges(), app.state.ontology_registry)
    )
    second = client.post(
        "/api/ontology/create", json={**body, "name": "Replacement draft"}
    )
    assert second.status_code == 409, second.text
    assert (
        session.get_nodes(),
        session.get_edges(),
        app.state.ontology_registry,
    ) == before


def test_concurrent_rdf_creates_cannot_claim_the_same_vocabulary(
    scene, proposal, monkeypatch
):
    client, session, app = scene
    ready = Barrier(2)

    class GenerationBoundary:
        def __init__(self, **_config):
            pass

        def from_rdf(self, _data, **_options):
            ready.wait(timeout=10)
            return deepcopy(proposal)

    monkeypatch.setattr("semantica.ontology.OntologyEngine", GenerationBoundary)
    body = {"mode": "data", "namespace": BASE, "name": "Draft", "sample_data": RDF}
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(lambda _: client.post("/api/ontology/create", json=body), range(2))
        )
    assert sorted(response.status_code for response in responses) == [200, 409]
    assert list(app.state.ontology_registry) == [BASE]
    assert session.get_node(BASE + "documentName")["content"] == "材料名称"
