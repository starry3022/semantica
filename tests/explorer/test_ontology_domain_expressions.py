"""Real load, graph, and term APIs preserve complex ontology declarations."""

from copy import deepcopy

import pytest
from rdflib import Graph, Namespace

pytest.importorskip("fastapi")

from starlette.testclient import TestClient  # noqa: E402

from semantica.context.context_graph import ContextGraph  # noqa: E402
from semantica.explorer.app import create_app  # noqa: E402
from semantica.explorer.routes.ontology import (  # noqa: E402
    _ontology_dict_from_nodes,
    _parse_rdf_sync,
)
from semantica.explorer.session import GraphSession  # noqa: E402
from semantica.ingest.ontology_ingestor import OntologyIngestor  # noqa: E402
from semantica.semantic_extract.process_graph import process_rule_ontology  # noqa: E402

EX = Namespace("https://example.org/expressions/")
TERM_URL = "/api/ontology/term"
PREFIXES = """
@prefix : <https://example.org/expressions/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
:Ontology a owl:Ontology .
:A a owl:Class . :B a owl:Class . :C a owl:Class .
"""


@pytest.fixture
def scene():
    graph = ContextGraph(advanced_analytics=False)
    session = GraphSession(graph)
    with TestClient(create_app(session=session)) as client:
        yield client, graph


def load(scene, content):
    response = scene[0].post(
        "/api/ontology/load", json={"content": content, "format": "turtle"}
    )
    assert response.status_code == 200, response.text
    return response.json()


def read_term(scene, uri):
    response = scene[0].get(
        TERM_URL, params={"ontology_uri": str(EX.Ontology), "term_uri": str(uri)}
    )
    assert response.status_code == 200, response.text
    return response.json()


def patch_term(scene, uri, document, **changes):
    payload = {
        "expected_revision": document["revision"],
        **{
            key: document["term"][key]
            for key in ("label", "comment", "parents", "domain", "range")
        },
        **changes,
    }
    return scene[0].patch(
        TERM_URL,
        params={"ontology_uri": str(EX.Ontology), "term_uri": str(uri)},
        json=payload,
    )


@pytest.mark.parametrize("fallback", [False, True])
def test_real_process_union_survives_load_graph_and_term(scene, monkeypatch, fallback):
    if fallback:

        def unavailable(*args, **kwargs):
            raise RuntimeError("force basic parser")

        monkeypatch.setattr(OntologyIngestor, "ingest_ontology", unavailable)
    raw = process_rule_ontology(base_uri=str(EX), label_language="zh").serialize(
        format="turtle"
    )
    load(scene, raw)
    response = scene[0].get("/api/ontology/graph", params={"uri": str(EX.Ontology)})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert sum(node["type"] == "owl:Class" for node in payload["nodes"]) == 9
    role_properties = {
        node["id"]
        for node in payload["nodes"]
        for expression in node["properties"].get("domain_expressions", [])
        if str(EX.Role) in expression.get("members", [])
    }
    assert role_properties == {str(EX.name), str(EX.fact_status), str(EX.review_status)}
    assert not any(
        edge["source"] in role_properties and edge["type"] == "rdfs:domain"
        for edge in payload["edges"]
    )
    term = read_term(scene, EX.name)["term"]
    assert term["domain"] == []
    assert term["domain_expressions"] == [
        {
            "kind": "unionOf",
            "members": [str(EX.Activity), str(EX.Role), str(EX.RequiredDocument)],
        }
    ]
    assert "range_expressions" not in term
    converted = _ontology_dict_from_nodes(
        str(EX.Ontology), "Process", payload["nodes"], payload["edges"]
    )
    converted_name = next(
        prop for prop in converted["properties"] if prop["uri"] == str(EX.name)
    )
    assert converted_name["domain_expressions"] == term["domain_expressions"]


@pytest.mark.parametrize("side", ["domain", "range"])
def test_complex_side_is_read_only_but_labels_and_other_side_remain_editable(
    scene, side
):
    other = "range" if side == "domain" else "domain"
    load(
        scene,
        PREFIXES
        + f":property a owl:ObjectProperty ; rdfs:{side} :A, [owl:unionOf (:A :B)] ; rdfs:{other} :B .",
    )
    document = read_term(scene, EX.property)
    before_expression = deepcopy(document["term"][side + "_expressions"])
    result = patch_term(
        scene,
        EX.property,
        document,
        label="保留复杂定义",
        comment="仅更新说明",
        **{other: [str(EX.C)]},
    )
    assert result.status_code == 200, result.text
    saved = result.json()
    assert saved["term"][side + "_expressions"] == before_expression
    assert saved["term"][side] == [str(EX.A)]
    assert saved["term"][other] == [str(EX.C)]
    assert saved["revision"] != document["revision"]
    before = deepcopy(scene[1].to_dict())
    rejected = patch_term(
        scene, EX.property, saved, label="不能写入", **{side: [str(EX.B)]}
    )
    assert rejected.status_code == 400, rejected.text
    assert "complex" in rejected.json()["detail"].lower()
    assert scene[1].to_dict() == before


def test_direct_multiple_domains_are_not_recast_as_a_union(scene):
    load(
        scene,
        PREFIXES
        + ":property a owl:ObjectProperty ; rdfs:domain :A, :B ; rdfs:range :C .",
    )
    document = read_term(scene, EX.property)
    assert document["term"]["domain"] == [str(EX.A), str(EX.B)]
    assert "domain_expressions" not in document["term"]
    assert (
        patch_term(scene, EX.property, document, domain=[str(EX.C)]).status_code == 200
    )


def test_opaque_cyclic_expression_is_visible_and_cannot_be_replaced_by_flat_edit(scene):
    load(
        scene,
        PREFIXES
        + ":property a owl:ObjectProperty ; rdfs:domain _:root . _:root owl:unionOf _:list . _:list rdf:first :A ; rdf:rest _:list .",
    )
    document = read_term(scene, EX.property)
    opaque = document["term"]["domain_expressions"][0]
    assert opaque["kind"] == "unsupported"
    assert Graph().parse(data=opaque["rdf"], format=opaque["rdf_format"])
    saved = patch_term(scene, EX.property, document, comment="未解释表达式仍保留")
    assert saved.status_code == 200, saved.text
    assert saved.json()["term"]["domain_expressions"] == [opaque]
    rejected = patch_term(scene, EX.property, saved.json(), domain=[str(EX.A)])
    assert rejected.status_code == 400, rejected.text


def test_fallback_preserves_union_range_and_opaque_payload():
    content = (
        PREFIXES
        + ":property a owl:ObjectProperty ; rdfs:range [owl:unionOf (:A :B)] ; rdfs:domain [a owl:Restriction; owl:onProperty :p; owl:someValuesFrom :C] ."
    )
    nodes, _, _ = _parse_rdf_sync(content.encode(), "turtle")
    properties = next(
        node["properties"] for node in nodes if node["id"] == str(EX.property)
    )
    assert properties["range_expressions"] == [
        {"kind": "unionOf", "members": [str(EX.A), str(EX.B)]}
    ]
    assert properties["domain_expressions"][0]["kind"] == "unsupported"


@pytest.mark.parametrize(
    "path,method",
    [("/api/ontology/shacl/generate", "post"), ("/api/ontology/shacl/shapes", "get")],
)
def test_shacl_generation_rejects_lossy_expression_conversion(scene, path, method):
    load(
        scene,
        PREFIXES
        + ":property a owl:ObjectProperty ; rdfs:domain [owl:unionOf (:A :B)] ; rdfs:range :C .",
    )
    response = getattr(scene[0], method)(
        path,
        **(
            {"json": {"uri": str(EX.Ontology)}}
            if method == "post"
            else {"params": {"uri": str(EX.Ontology)}}
        ),
    )
    assert response.status_code == 422, response.text
    assert "expression" in response.json()["detail"].lower()
    assert "shacl_turtle" not in response.json()
