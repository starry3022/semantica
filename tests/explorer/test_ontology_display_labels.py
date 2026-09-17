"""The graph's visible content must preserve human-readable ontology labels."""

import pytest

pytest.importorskip("fastapi")

from semantica.explorer.routes.ontology import _convert_ontology_to_graph  # noqa: E402


@pytest.mark.parametrize(
    "label,expected", [("证据起始字符", "证据起始字符"), (None, "start_char"), ("", "start_char")]
)
def test_property_content_prefers_label_and_preserves_iri(label, expected):
    uri = "https://example.org/process/start_char"
    nodes, _ = _convert_ontology_to_graph(
        {
            "uri": "https://example.org/process/",
            "properties": [
                {"name": "start_char", "uri": uri, "type": "data", "label": label}
            ],
        }
    )
    node = next(item for item in nodes if item["id"] == uri)
    assert node["content"] == expected
    assert node["properties"]["rdfs:label"] == expected
    assert node["type"] == "owl:DatatypeProperty"


def test_class_content_prefers_label_without_changing_its_identifier():
    uri = "https://example.org/business/PurchaseRequest"
    nodes, _ = _convert_ontology_to_graph(
        {
            "uri": "https://example.org/business/",
            "classes": [{"name": "PurchaseRequest", "uri": uri, "label": "采购申请"}],
        }
    )
    node = next(item for item in nodes if item["id"] == uri)
    assert node["content"] == "采购申请"
    assert node["properties"]["rdfs:label"] == "采购申请"
