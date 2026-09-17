"""Readable vocabulary annotations must preserve the existing RDF schema."""

import pytest
from rdflib import Graph, Literal, Namespace, OWL, RDF, RDFS
from rdflib.compare import to_isomorphic

from semantica.semantic_extract.process_graph import process_rule_ontology


BASE = "https://example.org/vocabulary-regression/"
NS = Namespace(BASE)
# Captured from the existing vocabulary before adding readable annotations.
# Graph canonicalization keeps the assertion independent of blank-node IDs.
BASELINE_STRUCTURE_DIGEST = int(
    "624271f382d647608c3923c0b3991466a54637d9c65bcdc84bb118e410b36561f9", 16
)


@pytest.mark.parametrize("language", ["en", "zh"])
def test_every_named_class_and_property_has_readable_annotations(language):
    graph = process_rule_ontology(BASE, label_language=language)
    expected_counts = {OWL.Class: 9, OWL.ObjectProperty: 11, OWL.DatatypeProperty: 29}
    for rdf_type, expected_count in expected_counts.items():
        subjects = {
            subject
            for subject in graph.subjects(RDF.type, rdf_type)
            if str(subject).startswith(BASE)
        }
        assert len(subjects) == expected_count
        for subject in subjects:
            labels = list(graph.objects(subject, RDFS.label))
            comments = list(graph.objects(subject, RDFS.comment))
            assert len(labels) == len(comments) == 1, str(subject)
            assert labels[0].language == comments[0].language == language
            assert str(labels[0]).strip() and "_" not in str(labels[0])
            assert len(str(comments[0]).strip()) >= 12


def test_default_labels_are_english_and_describe_a_support_vocabulary():
    graph = process_rule_ontology(BASE)
    assert graph.value(NS.Ontology, RDFS.label) == Literal(
        "Process evidence vocabulary", lang="en"
    )
    comment = str(graph.value(NS.Ontology, RDFS.comment))
    assert "fixed" in comment.lower()
    assert "candidate" in comment.lower()
    assert "business ontology" in comment.lower()
    assert graph.value(NS.ProcessRule, RDFS.label) == Literal("Process rule", lang="en")
    assert graph.value(NS.source_sha256, RDFS.label) == Literal(
        "Source SHA-256", lang="en"
    )


def test_chinese_labels_explain_the_support_vocabulary():
    graph = process_rule_ontology(BASE, label_language="zh")
    assert graph.value(NS.Ontology, RDFS.label) == Literal("流程与证据支持词汇", lang="zh")
    comment = str(graph.value(NS.Ontology, RDFS.comment))
    assert "固定" in comment and "候选" in comment and "业务本体" in comment
    assert graph.value(NS.ProcessRule, RDFS.label) == Literal("流程规则", lang="zh")
    assert graph.value(NS.start_char, RDFS.label) == Literal("证据起始位置", lang="zh")


@pytest.mark.parametrize(
    ("language", "zero_based", "codepoint", "included", "excluded", "metadata"),
    [
        ("en", "0-based", "code point", "inclusive", "exclusive", "technical metadata"),
        ("zh", "从 0", "码点", "包含", "不包含", "技术元数据"),
    ],
)
def test_offset_comments_define_the_unicode_interval(
    language, zero_based, codepoint, included, excluded, metadata
):
    graph = process_rule_ontology(BASE, label_language=language)
    start = str(graph.value(NS.start_char, RDFS.comment))
    end = str(graph.value(NS.end_char, RDFS.comment))
    for comment in (start, end):
        for required in (
            "Unicode",
            codepoint,
            zero_based,
            "[start_char, end_char)",
            "UTF-16",
            metadata,
        ):
            assert required in comment
    assert included in start
    assert excluded in end
    assert codepoint in str(graph.value(NS.text_length, RDFS.comment))


@pytest.mark.parametrize("language", ["en", "zh"])
def test_annotations_do_not_change_the_existing_schema(language):
    graph = process_rule_ontology(BASE, label_language=language)
    structure = Graph()
    for triple in graph:
        if triple[1] not in (RDFS.label, RDFS.comment):
            structure.add(triple)
    assert len(structure) == 208
    assert to_isomorphic(structure).graph_digest() == BASELINE_STRUCTURE_DIGEST


def test_unknown_label_language_is_not_silently_replaced():
    with pytest.raises(ValueError, match="label_language"):
        process_rule_ontology(BASE, label_language="fr")
