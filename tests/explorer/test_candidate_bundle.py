"""Portable candidate bundles retain exact RDF identity and explicit citations."""

import copy
import hashlib
import json
import shutil

import pytest
from rdflib import XSD
from starlette.testclient import TestClient

from semantica.export.rdf_exporter import RDFExporter, SEMANTICA_NS


NS = "https://example.test/vocabulary/"
ALICE = "https://example.test/facts/finance"
PAYMENT = "https://example.test/facts/payment"
TEXT = "前言😀\n财务负责人审核付款。\n财务负责人审核付款。"
SHA = hashlib.sha256(TEXT.encode()).hexdigest()


def _inputs():
    quote = "财务负责人审核付款。"
    start = TEXT.rindex(quote)
    evidence = {
        "quote": quote,
        "start_char": start,
        "end_char": start + len(quote),
        "source_id": "policy",
        "source_sha256": SHA,
    }
    facts = {
        "entities": [
            {
                "id": ALICE,
                "type": NS + "FinanceOfficer",
                "text": "财务负责人",
                "metadata": {"evidence": [evidence]},
            },
            {"id": PAYMENT, "type": NS + "Payment", "text": "付款"},
        ],
        "relationships": [
            {
                "source_id": ALICE,
                "target_id": PAYMENT,
                "type": NS + "reviews",
                "metadata": {"evidence": [evidence], "modality": "obligation"},
            },
        ],
    }
    ontology = {
        "uri": NS,
        "name": "采购本体草案",
        "version": None,
        "metadata": {
            "source": "llm",
            "fact_status": "candidate",
            "review_status": "unreviewed",
        },
        "classes": [
            {
                "uri": NS + name,
                "name": name,
                "label": label,
                "comment": label,
                "subClassOf": None,
            }
            for name, label in [("FinanceOfficer", "财务负责人"), ("Payment", "付款")]
        ],
        "properties": [
            {
                "uri": SEMANTICA_NS + "text",
                "name": "text",
                "label": "名称",
                "type": "data",
                "domain": [],
                "range": [str(XSD.string)],
            },
            {
                "uri": SEMANTICA_NS + "confidence",
                "name": "confidence",
                "label": "置信度",
                "type": "data",
                "domain": [],
                "range": [str(XSD.decimal)],
            },
            {
                "uri": NS + "reviews",
                "name": "reviews",
                "label": "审核",
                "type": "object",
                "domain": [NS + "FinanceOfficer"],
                "range": [NS + "Payment"],
            },
        ],
    }
    manifest = {
        "sources": [
            {
                "source_id": "policy",
                "path": "source.txt",
                "source_sha256": SHA,
                "title": "采购制度",
            }
        ]
    }
    return RDFExporter().export_to_rdf(facts), ontology, facts, manifest


def _write_bundle(path, *, inputs=None):
    from semantica.explorer.candidate_bundle import build_candidate_graph

    path.mkdir()
    rdf, ontology, facts, manifest = inputs or _inputs()
    graph = build_candidate_graph(rdf, ontology, facts, manifest)
    data = {
        "source.txt": TEXT.encode(),
        "base.ttl": rdf.encode(),
        "ontology.json": json.dumps(ontology, ensure_ascii=False).encode(),
        "facts.json": json.dumps(facts, ensure_ascii=False).encode(),
        "source-manifest.json": json.dumps(manifest).encode(),
        "candidate-graph.json": json.dumps(graph, ensure_ascii=False).encode(),
    }
    for name, content in data.items():
        (path / name).write_bytes(content)
    _rehash(path)
    return graph


def _rehash(path):
    summary = {
        "format_version": "candidate-facts-bundle-v1",
        "files": {
            child.name: hashlib.sha256(child.read_bytes()).hexdigest()
            for child in path.iterdir()
            if child.is_file() and child.name != "SUMMARY.json"
        },
    }
    (path / "SUMMARY.json").write_text(json.dumps(summary))


def test_projection_uses_one_draft_and_exact_rdf_types_and_property_iris():
    from semantica.explorer.candidate_bundle import build_candidate_graph

    rdf, ontology, facts, manifest = _inputs()
    before = copy.deepcopy((ontology, facts, manifest))
    graph = build_candidate_graph(rdf, ontology, facts, manifest)
    assert (ontology, facts, manifest) == before
    assert build_candidate_graph(rdf, ontology, facts, manifest) == graph
    nodes = {node["id"]: node for node in graph["nodes"]}
    assert [
        node["id"] for node in graph["nodes"] if node["type"] == "owl:Ontology"
    ] == [NS]
    assert nodes[ALICE]["type"] == NS + "FinanceOfficer"
    assert nodes[ALICE]["properties"][SEMANTICA_NS + "text"] == "财务负责人"
    assert nodes[ALICE]["properties"]["rdf:type"] == [NS + "FinanceOfficer"]
    assert nodes[NS + "FinanceOfficer"]["properties"]["scheme_uri"] == NS
    assert nodes[SEMANTICA_NS + "text"]["content"] == "名称"
    assert any(
        edge["source"] == ALICE
        and edge["target"] == NS + "FinanceOfficer"
        and edge["type"] == "rdf:type"
        for edge in graph["edges"]
    )
    assert graph["metadata"]["provenance_overlay"]["included_in_base_rdf"] is False
    assert graph["metadata"]["rdf_literals"][ALICE][SEMANTICA_NS + "confidence"] == [
        {"value": "1", "datatype": str(XSD.decimal), "language": None}
    ]


def test_relocated_bundle_serves_sources_draft_and_exact_property_identity(tmp_path):
    from semantica.explorer.candidate_bundle import (
        create_bundle_app,
        read_candidate_bundle,
    )

    original = tmp_path / "original"
    _write_bundle(original)
    moved = tmp_path / "elsewhere" / "bundle"
    shutil.copytree(original, moved)
    shutil.rmtree(original)
    files = read_candidate_bundle(moved)
    assert files["source.txt"] == TEXT.encode()
    assert (
        json.loads(files["SUMMARY.json"])["format_version"]
        == "candidate-facts-bundle-v1"
    )
    app = create_bundle_app(moved)
    with TestClient(app) as client:
        source = client.get("/api/sources/view", params={"node_id": ALICE}).json()
        assert source["evidence"][0]["status"] == "aligned"
        assert source["evidence"][0]["start_char"] == TEXT.rindex("财务负责人审核付款。")
        assert source["evidence"][0]["review_status"] == "unreviewed"
        assert source["sources"][0]["text"] == TEXT
        assert source["sources"][0]["version"] is None
        types = client.get(
            "/api/ontology/instance-types", params={"node_id": ALICE}
        ).json()
        assert types["types"][0]["class_uri"] == NS + "FinanceOfficer"
        assert any(
            prop["property_uri"] == SEMANTICA_NS + "text"
            and prop["label"] == "名称"
            and prop["loaded"]
            for prop in types["property_definitions"]
        )
        assert list(app.state.ontology_registry) == [NS]
        assert app.state.ontology_registry[NS].status == "draft"
        for node in app.state.session.graph.find_nodes():
            if node["type"] in {"Evidence", "SourceDocument"}:
                opened = client.get(
                    "/api/sources/view", params={"node_id": node["id"]}
                ).json()
                assert opened["sources"][0]["text"] == TEXT


def test_relationship_only_receives_explicit_evidence_and_merges_same_spo(tmp_path):
    from semantica.explorer.candidate_bundle import create_bundle_app

    rdf, ontology, facts, manifest = _inputs()
    second = copy.deepcopy(facts["relationships"][0])
    first_citation = second["metadata"]["evidence"][0]
    first_citation["start_char"] = TEXT.index(first_citation["quote"])
    first_citation["end_char"] = first_citation["start_char"] + len(
        first_citation["quote"]
    )
    facts["relationships"].append(second)
    facts["entities"][0]["metadata"]["evidence"] = []
    graph = _write_bundle(tmp_path / "bundle", inputs=(rdf, ontology, facts, manifest))
    edge = next(edge for edge in graph["edges"] if edge["type"] == NS + "reviews")
    with TestClient(create_bundle_app(tmp_path / "bundle")) as client:
        view = client.get("/api/sources/view", params={"edge_id": edge["id"]}).json()
        assert len(view["evidence"]) == 2
        assert {item["status"] for item in view["evidence"]} == {"aligned"}
        assert (
            client.get("/api/sources/view", params={"node_id": ALICE}).json()["status"]
            == "no_evidence"
        )
        assert (
            client.get("/api/sources/view", params={"node_id": PAYMENT}).json()[
                "status"
            ]
            == "no_evidence"
        )


@pytest.mark.parametrize(
    ("change", "status"),
    [
        ({"start_char": -1}, "invalid_offsets"),
        ({"quote": "不相符"}, "quote_mismatch"),
        ({"source_sha256": "0" * 64}, "hash_mismatch"),
        ({"source_id": "missing"}, "source_missing"),
    ],
)
def test_invalid_evidence_is_kept_and_honestly_reported(tmp_path, change, status):
    from semantica.explorer.candidate_bundle import create_bundle_app

    rdf, ontology, facts, manifest = _inputs()
    facts["entities"][0]["metadata"]["evidence"][0].update(change)
    _write_bundle(tmp_path / "bundle", inputs=(rdf, ontology, facts, manifest))
    with TestClient(create_bundle_app(tmp_path / "bundle")) as client:
        result = client.get("/api/sources/view", params={"node_id": ALICE}).json()
        assert result["evidence"][0]["status"] == status
        assert result["evidence"][0]["reason"]


@pytest.mark.parametrize(
    "filename",
    ["source.txt", "facts.json", "base.ttl", "ontology.json", "candidate-graph.json"],
)
def test_corrupt_or_missing_artifacts_are_rejected(tmp_path, filename):
    from semantica.explorer.candidate_bundle import read_candidate_bundle

    bundle = tmp_path / "bundle"
    _write_bundle(bundle)
    (bundle / filename).write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="hash"):
        read_candidate_bundle(bundle)
    (bundle / filename).unlink()
    with pytest.raises(ValueError, match="missing|read"):
        read_candidate_bundle(bundle)


@pytest.mark.parametrize(
    "unsafe",
    [
        "../outside.txt",
        "/etc/passwd",
        "https://example.test/source",
        "dir/../../outside.txt",
        "dir\\outside.txt",
    ],
)
def test_bundle_manifest_rejects_escaping_and_url_paths(tmp_path, unsafe):
    from semantica.explorer.candidate_bundle import read_candidate_bundle

    bundle = tmp_path / "bundle"
    _write_bundle(bundle)
    manifest = json.loads((bundle / "source-manifest.json").read_bytes())
    manifest["sources"][0]["path"] = unsafe
    (bundle / "source-manifest.json").write_text(json.dumps(manifest))
    _rehash(bundle)
    with pytest.raises(ValueError, match="path|relative|listed"):
        read_candidate_bundle(bundle)


def test_bundle_rejects_outside_symlink_and_unlisted_source(tmp_path):
    from semantica.explorer.candidate_bundle import read_candidate_bundle

    bundle = tmp_path / "bundle"
    _write_bundle(bundle)
    outside = tmp_path / "outside.txt"
    outside.write_text(TEXT)
    (bundle / "source.txt").unlink()
    (bundle / "source.txt").symlink_to(outside)
    with pytest.raises(ValueError, match="path|escapes|symlink"):
        read_candidate_bundle(bundle)
    (bundle / "source.txt").unlink()
    (bundle / "source.txt").write_text(TEXT)
    summary = json.loads((bundle / "SUMMARY.json").read_bytes())
    del summary["files"]["source.txt"]
    (bundle / "SUMMARY.json").write_text(json.dumps(summary))
    with pytest.raises(ValueError, match="listed|manifest"):
        read_candidate_bundle(bundle)


def test_loader_rejects_projection_drift_even_with_updated_checksum(tmp_path):
    from semantica.explorer.candidate_bundle import create_bundle_app

    bundle = tmp_path / "bundle"
    graph = _write_bundle(bundle)
    graph["nodes"][0]["content"] = "Changed outside the source facts"
    (bundle / "candidate-graph.json").write_text(json.dumps(graph))
    _rehash(bundle)
    with pytest.raises(ValueError, match="projection|candidate-graph"):
        create_bundle_app(bundle)


def test_cli_bundle_starts_standard_app_and_forbids_ambiguous_inputs(
    tmp_path, monkeypatch
):
    import uvicorn
    from semantica.explorer import main

    bundle = tmp_path / "bundle"
    _write_bundle(bundle)
    calls = []

    def serve(app, **kwargs):
        with TestClient(app) as client:
            assert (
                client.get("/api/sources/view", params={"node_id": ALICE}).json()[
                    "evidence"
                ][0]["status"]
                == "aligned"
            )
        calls.append(kwargs)

    monkeypatch.setattr(uvicorn, "run", serve)
    main(["--bundle", str(bundle), "--port", "8021", "--no-browser"])
    assert calls[0]["port"] == 8021
    for options in [
        ["--graph", "anything.json"],
        ["--source-manifest", "anything.json"],
    ]:
        with pytest.raises(SystemExit) as error:
            main(["--bundle", str(bundle), *options, "--no-browser"])
        assert error.value.code == 2


def test_multiple_sources_keep_their_own_exact_unicode_and_markup(tmp_path):
    from semantica.explorer.candidate_bundle import create_bundle_app

    rdf, ontology, facts, manifest = _inputs()
    other_text = "合同😀\r\n<script>alert('material')</script>"
    other_digest = hashlib.sha256(other_text.encode()).hexdigest()
    quote = "😀\r\n<script>alert('material')</script>"
    facts["entities"][1]["metadata"] = {
        "evidence": [
            {
                "quote": quote,
                "start_char": 2,
                "end_char": len(other_text),
                "source_id": "other",
                "source_sha256": other_digest,
            }
        ]
    }
    manifest["sources"].append(
        {
            "source_id": "other",
            "path": "other.txt",
            "source_sha256": other_digest,
            "version": "2026-09",
        }
    )
    bundle = tmp_path / "bundle"
    _write_bundle(bundle, inputs=(rdf, ontology, facts, manifest))
    (bundle / "other.txt").write_bytes(other_text.encode())
    _rehash(bundle)
    with TestClient(create_bundle_app(bundle)) as client:
        first = client.get("/api/sources/view", params={"node_id": ALICE}).json()
        response = client.get("/api/sources/view", params={"node_id": PAYMENT})
        second = response.json()
        assert response.headers["content-type"].startswith("application/json")
        assert first["sources"][0]["source_id"] == "policy"
        assert first["sources"][0]["text"] == TEXT
        assert second["sources"][0]["source_id"] == "other"
        assert second["sources"][0]["text"] == other_text
        assert second["sources"][0]["version"] == "2026-09"
        assert second["evidence"][0]["status"] == "aligned"
        assert second["evidence"][0]["quote"] == quote
        assert len(first["sources"]) == len(second["sources"]) == 1


def test_bundle_cli_rejects_missing_input_without_starting_server(
    tmp_path, monkeypatch, capsys
):
    import uvicorn
    from semantica.explorer import main

    calls = []
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(SystemExit) as error:
        main(["--bundle", str(tmp_path / "absent"), "--no-browser"])
    assert error.value.code == 1
    assert not calls
    assert "invalid or unreadable candidate bundle" in capsys.readouterr().err


def test_projection_refuses_facts_and_ontology_identity_drift():
    from semantica.explorer.candidate_bundle import build_candidate_graph

    rdf, ontology, facts, manifest = _inputs()
    drift = copy.deepcopy(facts)
    drift["entities"][0]["type"] = NS + "Other"
    with pytest.raises(ValueError, match="facts.*base RDF"):
        build_candidate_graph(rdf, ontology, drift, manifest)
    ontology["classes"][0]["uri"] = NS + "RenamedFinanceOfficer"
    with pytest.raises(ValueError, match="exactly.*RDF vocabulary"):
        build_candidate_graph(rdf, ontology, facts, manifest)


def test_verified_file_bytes_must_agree_with_source_manifest_identity(tmp_path):
    from semantica.explorer.candidate_bundle import read_candidate_bundle

    bundle = tmp_path / "bundle"
    _write_bundle(bundle)
    manifest = json.loads((bundle / "source-manifest.json").read_bytes())
    manifest["sources"][0]["source_sha256"] = "0" * 64
    (bundle / "source-manifest.json").write_text(json.dumps(manifest))
    _rehash(bundle)
    with pytest.raises(ValueError, match="source manifest hash"):
        read_candidate_bundle(bundle)


def test_merged_spo_preserves_each_assertions_qualifiers_and_own_evidence():
    from semantica.explorer.candidate_bundle import build_candidate_graph

    rdf, ontology, facts, manifest = _inputs()
    quotes = ["财务负责人", "审核付款。"]
    qualifiers = [
        {"conditions": ["金额超过一万元"], "negated": False, "modality": "obligation"},
        {"conditions": ["材料不完整"], "negated": True, "modality": "prohibition"},
    ]
    template = facts["relationships"][0]
    facts["relationships"] = []
    for quote, qualifier in zip(quotes, qualifiers):
        start = TEXT.index(quote)
        facts["relationships"].append(
            {
                **template,
                "metadata": {
                    **qualifier,
                    "evidence": [
                        {
                            "source_id": "policy",
                            "source_sha256": SHA,
                            "quote": quote,
                            "start_char": start,
                            "end_char": start + len(quote),
                        }
                    ],
                },
            }
        )
    graph = build_candidate_graph(rdf, ontology, facts, manifest)
    edge = next(edge for edge in graph["edges"] if edge["type"] == NS + "reviews")
    nodes = {node["id"]: node for node in graph["nodes"]}
    assertions = edge["properties"]["candidate_assertions"]
    assert len(assertions) == 2
    for assertion, quote, qualifier in zip(assertions, quotes, qualifiers):
        assert {key: assertion[key] for key in qualifier} == qualifier
        assert len(assertion["evidence_ids"]) == 1
        assert nodes[assertion["evidence_ids"][0]]["properties"]["quote"] == quote
    assert set(edge["properties"]["evidence_ids"]) == {
        evidence_id
        for assertion in assertions
        for evidence_id in assertion["evidence_ids"]
    }
