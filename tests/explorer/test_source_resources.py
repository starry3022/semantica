"""Only explicitly registered UTF-8 material may be returned by identity."""

import hashlib
import json

import pytest


@pytest.fixture
def registry_type():
    from semantica.explorer.source_resources import SourceResourceRegistry

    return SourceResourceRegistry


def test_registry_preserves_text_bytes_unicode_and_versions(registry_type, tmp_path):
    raw = "制度😀\r\n重复\n重复\r\n".encode("utf-8")
    source = tmp_path / "source.txt"
    source.write_bytes(raw)
    resources = registry_type()
    resources.register_file("policy", source, title="制度", version="2026-09")
    resources.register_text("policy", "another revision")
    expected = hashlib.sha256(raw).hexdigest()

    result = resources.read("policy", expected)
    assert result["status"] == "available"
    assert result["text"] == raw.decode("utf-8")
    assert result["actual_sha256"] == expected
    assert result["character_count"] == 12
    assert result["version"] == "2026-09"


def test_unknown_source_or_revision_never_falls_back(registry_type):
    resources = registry_type()
    resources.register_text("policy", "right material")
    missing = resources.read("unregistered", "a" * 64)
    mismatch = resources.read("policy", "0" * 64)
    assert missing["status"] == "source_missing"
    assert mismatch["status"] == "hash_mismatch"
    assert missing["text"] is None
    assert mismatch["text"] is None
    assert missing["reason"] and mismatch["reason"]


def test_registry_is_an_immutable_material_snapshot(registry_type, tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("original")
    resources = registry_type()
    resources.register_file("policy", source)
    source.write_text("changed after startup")
    result = resources.read("policy", hashlib.sha256(b"original").hexdigest())
    assert result["text"] == "original"
    assert result["status"] == "available"
    result["text"] = "caller mutation"
    assert (
        resources.read("policy", hashlib.sha256(b"original").hexdigest())["text"]
        == "original"
    )


def test_invalid_utf8_is_missing_instead_of_changed_material(registry_type, tmp_path):
    (tmp_path / "source.txt").write_bytes(b"original\xff")
    manifest = tmp_path / "sources.json"
    manifest.write_text(
        json.dumps({"sources": [{"source_id": "policy", "path": "source.txt"}]})
    )
    result = registry_type.from_manifest(manifest).read("policy", "0" * 64)
    assert result["status"] == "source_missing"
    assert result["text"] is None


def test_manifest_resolves_relative_paths_without_exposing_paths(
    registry_type, tmp_path
):
    (tmp_path / "source.txt").write_bytes("原文\r\n😀".encode())
    manifest = tmp_path / "sources.json"
    manifest.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "source_id": "policy",
                        "path": "source.txt",
                        "title": "制度",
                        "source_uri": "https://example.test/policy",
                    }
                ]
            }
        )
    )
    resources = registry_type.from_manifest(manifest)
    result = resources.read("policy", hashlib.sha256("原文\r\n😀".encode()).hexdigest())
    assert result["text"] == "原文\r\n😀"
    assert result["version"] is None
    assert result["source_uri"] == "https://example.test/policy"
    assert str(tmp_path) not in json.dumps(result)


@pytest.mark.parametrize(
    "source_path",
    [
        "/etc/passwd",
        "../secret.txt",
        "a/../../secret.txt",
        "https://example.test/material",
        "file:///etc/passwd",
        "C:\\secret.txt",
        "..\\secret.txt",
    ],
)
def test_manifest_rejects_absolute_traversal_and_url_paths(
    registry_type, tmp_path, source_path
):
    manifest = tmp_path / "sources.json"
    manifest.write_text(
        json.dumps({"sources": [{"source_id": "policy", "path": source_path}]})
    )
    with pytest.raises(ValueError):
        registry_type.from_manifest(manifest)


def test_manifest_rejects_symlink_escape(registry_type, tmp_path):
    private = tmp_path / "secret.txt"
    private.write_text("private")
    public = tmp_path / "public"
    public.mkdir()
    (public / "escape.txt").symlink_to(private)
    manifest = public / "sources.json"
    manifest.write_text(
        json.dumps({"sources": [{"source_id": "policy", "path": "escape.txt"}]})
    )
    with pytest.raises(ValueError):
        registry_type.from_manifest(manifest)


def test_missing_manifest_resource_remains_an_explicit_empty_state(
    registry_type, tmp_path
):
    manifest = tmp_path / "sources.json"
    manifest.write_text(
        json.dumps(
            {"sources": [{"source_id": "policy", "path": "missing.txt", "title": "制度"}]}
        )
    )
    result = registry_type.from_manifest(manifest).read("policy", "0" * 64)
    assert result["status"] == "source_missing"
    assert result["title"] is None
    assert result["text"] is None
    assert str(tmp_path) not in result["reason"]


def test_missing_revisions_do_not_borrow_metadata_from_another_version(
    registry_type, tmp_path
):
    manifest = tmp_path / "sources.json"
    manifest.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "source_id": "policy",
                        "path": "missing-v1.txt",
                        "version": "v1",
                        "title": "First policy",
                        "source_uri": "https://example.test/v1",
                    },
                    {
                        "source_id": "policy",
                        "path": "missing-v2.txt",
                        "version": "v2",
                        "title": "Second policy",
                        "source_uri": "https://example.test/v2",
                    },
                ]
            }
        )
    )
    resources = registry_type.from_manifest(manifest)
    for digest in [
        hashlib.sha256(b"first").hexdigest(),
        hashlib.sha256(b"second").hexdigest(),
        "0" * 64,
    ]:
        result = resources.read("policy", digest)
        assert result["status"] == "source_missing"
        assert result["version"] is None
        assert result["title"] is None
        assert result["source_uri"] is None
        assert result["actual_sha256"] is None
        assert result["text"] is None


@pytest.mark.parametrize(
    "document",
    [
        [],
        {},
        {"sources": {}},
        {"sources": [None]},
        {"sources": [{"source_id": [], "path": "source.txt"}]},
    ],
)
def test_manifest_rejects_invalid_structure(registry_type, tmp_path, document):
    manifest = tmp_path / "sources.json"
    manifest.write_text(json.dumps(document))
    with pytest.raises(ValueError):
        registry_type.from_manifest(manifest)


def test_cli_registers_manifest_before_serving(registry_type, tmp_path, monkeypatch):
    import uvicorn
    from starlette.testclient import TestClient

    from semantica.explorer import main

    source = tmp_path / "source.txt"
    source.write_text("原文")
    digest = hashlib.sha256("原文".encode()).hexdigest()
    graph = tmp_path / "graph.json"
    graph.write_text(
        json.dumps(
            {
                "nodes": [
                    {
                        "id": "source",
                        "type": "SourceDocument",
                        "properties": {"source_id": "policy", "source_sha256": digest},
                    }
                ],
                "edges": [],
            }
        )
    )
    manifest = tmp_path / "sources.json"
    manifest.write_text(
        json.dumps({"sources": [{"source_id": "policy", "path": "source.txt"}]})
    )
    responses = []

    def serve(app, **_kwargs):
        with TestClient(app) as client:
            responses.append(
                client.get("/api/sources/view", params={"node_id": "source"}).json()
            )

    monkeypatch.setattr(uvicorn, "run", serve)
    main(["--graph", str(graph), "--source-manifest", str(manifest), "--no-browser"])
    assert responses[0]["sources"][0]["text"] == "原文"
