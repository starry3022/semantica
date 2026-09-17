"""Business/source links preserve exact occurrence and immutable schema identity."""

import copy
import hashlib

import pytest


TEXT = "前😀\r\n采购申请\n合同\n采购申请\n"
BASE = "https://example.test/business/"
TTL = """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<https://example.test/business/PurchaseRequest> a owl:Class ;
    rdfs:label "采购申请" ; rdfs:comment "申请类型；候选。" .
"""


@pytest.fixture
def proposal():
    return {
        "uri": BASE,
        "classes": [
            {
                "uri": BASE + "PurchaseRequest",
                "name": "PurchaseRequest",
                "label": "采购申请",
                "evidence_lines": [4, 4],
                "evidence_quote": "采购申请\n",
            }
        ],
        "properties": [],
        "metadata": {"source_sha256": hashlib.sha256(TEXT.encode()).hexdigest()},
    }


def build(proposal, source=TEXT, ttl=TTL):
    from semantica.ontology.evidence_context import build_evidence_context

    return build_evidence_context(
        proposal, ttl, source, "policy-A", ["https://example.test/support/"]
    )


def test_context_uses_exact_unicode_occurrence_and_exported_definition(proposal):
    result = build(proposal)
    assert result["support_ontologies"] == ["https://example.test/support/"]
    term = result["business_ontologies"][0]["terms"][0]
    assert (term["start_char"], term["end_char"], term["quote"]) == (12, 17, "采购申请\n")
    assert term["source_id"] == "policy-A"
    assert term["source_sha256"] == hashlib.sha256(TEXT.encode()).hexdigest()
    assert term["comment"] == "申请类型；候选。"
    assert term["type"] == "owl:Class"
    assert term["parents"] == term["domain"] == term["range"] == []


def test_legacy_quote_requires_one_occurrence(proposal):
    proposal["classes"][0].pop("evidence_lines")
    with pytest.raises(ValueError, match="ambiguous|unique"):
        build(proposal)
    proposal["classes"][0]["evidence_quote"] = "合同"
    term = build(proposal)["business_ontologies"][0]["terms"][0]
    assert (term["start_char"], term["end_char"]) == (9, 11)


@pytest.mark.parametrize("lines", [[0, 1], [4, 5], [True, 1], [3, 2]])
def test_context_rejects_invalid_line_selection(proposal, lines):
    proposal["classes"][0]["evidence_lines"] = lines
    with pytest.raises(ValueError):
        build(proposal)


def test_context_rejects_changed_source_or_quote(proposal):
    with pytest.raises(ValueError, match="hash"):
        build(proposal, source=TEXT + "changed")
    proposal["classes"][0]["evidence_quote"] = "不存在"
    with pytest.raises(ValueError, match="quote"):
        build(proposal)


def test_context_rejects_missing_or_changed_exported_term(proposal):
    with pytest.raises(ValueError):
        build(proposal, ttl=TTL.replace("PurchaseRequest>", "Different>"))
    with pytest.raises(ValueError):
        build(proposal, ttl=TTL.replace('rdfs:label "采购申请"', 'rdfs:label "另一概念"'))


def test_context_does_not_mutate_input_candidate(proposal):
    original = copy.deepcopy(proposal)
    build(proposal)
    assert proposal == original
