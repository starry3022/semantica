"""Recall, ranking, cache and work bounds for the Explorer search index."""

import pytest

from semantica.explorer.search_index import GraphSearchIndex


def _node(node_id, label, node_type="RequiredDocument", **properties):
    return {
        "id": node_id,
        "type": node_type,
        "content": label,
        "properties": {"label": label, **properties},
    }


class CountingDocuments(dict):
    """Count real document reads without replacing candidate or scoring behavior."""

    def __init__(self, documents):
        super().__init__(documents)
        self.lookups = 0

    def get(self, key, default=None):
        self.lookups += 1
        return super().get(key, default)


@pytest.mark.parametrize(
    ("query", "longer_label"),
    [
        ("合同", "合法有效的合同"),
        ("Contract", "Precontractual agreement"),
        ("V2合同", "HV2合同附件"),
    ],
)
def test_exact_label_does_not_suppress_longer_containing_labels(query, longer_label):
    index = GraphSearchIndex()
    index.rebuild(
        [
            _node("a-class", query, "owl:Class"),
            _node("z-document", longer_label),
            _node("unrelated", "发票"),
        ]
    )

    matches, diagnostics = index.search(query)

    assert [node_id for node_id, _ in matches] == ["a-class", "z-document"]
    assert matches[0][1] > matches[1][1] > 0
    assert diagnostics["candidates"] == 2


@pytest.mark.parametrize(
    ("limit", "expected"),
    [
        (0, []),
        (1, ["a-class"]),
        (2, ["a-class", "m-document"]),
        (3, ["a-class", "m-document", "z-description"]),
    ],
)
def test_exact_then_label_contains_then_secondary_text_respect_result_limit(
    limit, expected
):
    index = GraphSearchIndex()
    index.rebuild(
        [
            _node("z-description", "附件", description="必须提供合同"),
            _node("m-document", "合法有效的合同"),
            _node("a-class", "合同", "owl:Class"),
        ]
    )

    matches, _ = index.search("合同", limit=limit)

    assert [node_id for node_id, _ in matches] == expected


def test_type_and_metadata_filters_still_recall_documents_beside_an_exact_class():
    index = GraphSearchIndex()
    index.rebuild(
        [
            _node("class", "合同", "owl:Class", confidence=1.0, tags=["legal"]),
            _node("document", "合法有效的合同", confidence=0.9, tags=["legal"]),
            _node("uncertain", "其他合同", confidence=0.4, tags=["legal"]),
            _node("untagged", "归档合同", confidence=0.9),
        ]
    )
    filters = {
        "type": "RequiredDocument",
        "min_confidence": 0.8,
        "tags": ["legal"],
    }

    matches, _ = index.search("合同", filters=filters)
    cached, diagnostics = index.search("合同", filters=filters)

    assert [node_id for node_id, _ in matches] == ["document"]
    assert cached == matches
    assert diagnostics["cache_hit"] is True
    unfiltered, _ = index.search("合同", limit=1)
    assert [node_id for node_id, _ in unfiltered] == ["class"]


def test_combined_results_refresh_after_upsert_remove_and_rebuild():
    index = GraphSearchIndex()
    index.rebuild([_node("class", "合同", "owl:Class")])
    first, _ = index.search("合同")
    cached, diagnostics = index.search("合同")
    assert cached == first
    assert diagnostics["cache_hit"] is True

    index.upsert(_node("document", "合法有效的合同"))
    added, diagnostics = index.search("合同")
    assert [node_id for node_id, _ in added] == ["class", "document"]
    assert diagnostics["cache_hit"] is False
    added.clear()
    cached, _ = index.search("合同")
    assert [node_id for node_id, _ in cached] == ["class", "document"]

    index.upsert(_node("document", "发票"))
    updated, diagnostics = index.search("合同")
    assert [node_id for node_id, _ in updated] == ["class"]
    assert diagnostics["cache_hit"] is False

    index.upsert(_node("document", "合法有效的合同"))
    index.search("合同")
    index.remove("class")
    removed, diagnostics = index.search("合同")
    assert [node_id for node_id, _ in removed] == ["document"]
    assert diagnostics["cache_hit"] is False

    index.rebuild([_node("replacement", "采购合同")])
    rebuilt, diagnostics = index.search("合同")
    assert [node_id for node_id, _ in rebuilt] == ["replacement"]
    assert diagnostics["cache_hit"] is False


def test_large_graph_contains_scan_keeps_its_document_budget_and_cached_fast_path():
    nodes = [_node(f"n{number:05}", "普通材料") for number in range(20000)]
    nodes[4] = _node("n00004", "合法有效的合同")
    nodes[25] = _node("n00025", "超过扫描边界的合同")
    nodes[-1] = _node("n19999", "远端合同")
    nodes.append(_node("z-exact", "合同", "owl:Class"))
    index = GraphSearchIndex(secondary_scan_limit=25)
    index.rebuild(nodes)
    documents = CountingDocuments(index._documents)
    index._documents = documents

    matches, diagnostics = index.search("合同")

    assert [node_id for node_id, _ in matches] == ["z-exact", "n00004"]
    assert diagnostics["candidates"] == 2
    assert documents.lookups <= 27  # 25 scanned documents plus two ranked candidates.
    documents.lookups = 0
    cached, diagnostics = index.search("合同")
    assert cached == matches
    assert diagnostics["cache_hit"] is True
    assert documents.lookups == 0


@pytest.mark.parametrize(
    ("limit", "candidate_count", "highest_scanned_id", "max_reads"),
    [(3, 201, "n00199", 401), (12, 241, "n00239", 481)],
)
def test_contains_hit_budget_does_not_displace_indexed_exact_matches(
    limit, candidate_count, highest_scanned_id, max_reads
):
    index = GraphSearchIndex()
    index.rebuild(
        [_node(f"n{number:05}", "有效合同") for number in range(3000)]
        + [_node("z-exact", "合同", "owl:Class")]
    )
    documents = CountingDocuments(index._documents)
    index._documents = documents

    matches, diagnostics = index.search("合同", limit=limit)

    assert len(matches) == limit
    assert [node_id for node_id, _ in matches[:2]] == ["z-exact", highest_scanned_id]
    assert diagnostics["candidates"] == candidate_count
    assert documents.lookups <= max_reads


def test_token_prefix_and_secondary_only_queries_keep_existing_behavior():
    index = GraphSearchIndex()
    index.rebuild(
        [
            _node("medicine", "Metformin", "drug", aliases=["Glucophage"]),
            _node("fallback", "附件", description="rareterm"),
        ]
    )

    prefix, _ = index.search("METF")
    alias, _ = index.search("  glucophage  ")
    secondary, diagnostics = index.search("rareterm")
    missing, _ = index.search("absent")
    empty, _ = index.search("  ")

    assert [node_id for node_id, _ in prefix] == ["medicine"]
    assert [node_id for node_id, _ in alias] == ["medicine"]
    assert [node_id for node_id, _ in secondary] == ["fallback"]
    assert diagnostics["path"] == "secondary_scan"
    assert missing == empty == []
