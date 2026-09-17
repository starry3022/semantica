"""Graph namespace declarations survive JSON without aliasing or stale state."""

import json
from copy import deepcopy

import pytest

from semantica.context.context_graph import ContextGraph


def payload(base="https://example.org/process/"):
    return {
        "nodes": [{"id": "urn:rule:one", "type": "ProcessRule", "content": "规则"}],
        "edges": [],
        "metadata": {"base_uri": base, "nested": {"labels": ["中文😀"]}},
    }


def test_json_and_dictionary_round_trips_preserve_independent_metadata(tmp_path):
    original = payload()
    graph = ContextGraph(advanced_analytics=False)
    graph.from_dict(original)
    assert graph.metadata == original["metadata"]
    original["metadata"]["nested"]["labels"].append("input mutation")
    assert graph.metadata["nested"]["labels"] == ["中文😀"]
    exported = graph.to_dict()
    exported["metadata"]["nested"]["labels"].append("output mutation")
    assert graph.metadata["nested"]["labels"] == ["中文😀"]
    destination = tmp_path / "graph.json"
    graph.save_to_file(destination)
    assert json.loads(destination.read_text())["metadata"] == graph.metadata
    loaded = ContextGraph(advanced_analytics=False)
    loaded.load_from_file(destination)
    assert loaded.metadata == graph.metadata
    loaded.metadata["nested"]["labels"].append("other graph")
    assert graph.metadata["nested"]["labels"] == ["中文😀"]


@pytest.mark.parametrize(
    "replacement", [{"nodes": [], "edges": []}, [], {"metadata": None}]
)
def test_file_replacement_without_metadata_clears_the_previous_namespace(
    tmp_path, replacement
):
    graph = ContextGraph(advanced_analytics=False)
    graph.from_dict(payload())
    destination = tmp_path / "legacy.json"
    destination.write_text(json.dumps(replacement))
    graph.load_from_file(destination)
    assert graph.metadata == {}
    assert graph.to_dict().get("metadata", {}) == {}


def test_dictionary_replacement_and_clear_do_not_retain_old_namespace():
    graph = ContextGraph(advanced_analytics=False)
    graph.from_dict(payload())
    graph.from_dict(payload("https://example.org/second/"))
    assert graph.metadata["base_uri"] == "https://example.org/second/"
    graph.from_dict({"nodes": [], "edges": []})
    assert graph.metadata == {}
    graph.from_dict(payload())
    graph.clear()
    assert graph.metadata == {}


@pytest.mark.parametrize("invalid", [[], "https://example.org/", 7, True])
@pytest.mark.parametrize("loader", ["dictionary", "file"])
def test_invalid_metadata_is_rejected_before_replacing_the_graph(
    tmp_path, invalid, loader
):
    graph = ContextGraph(advanced_analytics=False)
    graph.from_dict(payload())
    before = deepcopy(graph.to_dict())
    replacement = {"nodes": [], "edges": [], "metadata": invalid}
    with pytest.raises(ValueError, match="metadata"):
        if loader == "dictionary":
            graph.from_dict(replacement)
        else:
            destination = tmp_path / "bad.json"
            destination.write_text(json.dumps(replacement))
            graph.load_from_file(destination)
    assert graph.to_dict() == before


def test_markdown_replacement_clears_json_metadata_without_extending_its_format(
    tmp_path,
):
    legacy = ContextGraph(advanced_analytics=False)
    legacy.add_node("urn:legacy", "entity", "旧图")
    destination = tmp_path / "markdown"
    legacy.save_to_file(destination, format="markdown")
    graph = ContextGraph(advanced_analytics=False)
    graph.from_dict(payload())
    graph.load_from_file(destination, format="markdown")
    assert graph.metadata == {}
    assert set(graph.nodes) == {"urn:legacy"}


def test_failed_or_missing_file_load_retains_existing_metadata(tmp_path):
    graph = ContextGraph(advanced_analytics=False)
    graph.from_dict(payload())
    before = deepcopy(graph.to_dict())
    graph.load_from_file(tmp_path / "missing.json")
    assert graph.to_dict() == before
    bad = tmp_path / "bad.json"
    bad.write_text("{")
    with pytest.raises(json.JSONDecodeError):
        graph.load_from_file(bad)
    assert graph.to_dict() == before


def test_failed_markdown_load_keeps_the_existing_graph_namespace(tmp_path):
    graph = ContextGraph(advanced_analytics=False)
    graph.from_dict(payload())
    before = deepcopy(graph.to_dict())
    folder = tmp_path / "invalid-markdown"
    folder.mkdir()
    with pytest.raises(FileNotFoundError):
        graph.load_from_file(folder, format="markdown")
    assert graph.to_dict() == before


def test_legacy_graph_output_does_not_add_empty_metadata():
    graph = ContextGraph(advanced_analytics=False)
    assert "metadata" not in graph.to_dict()
