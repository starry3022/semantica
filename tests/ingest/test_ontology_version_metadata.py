"""An import must not invent an ontology release version from missing metadata."""

import pytest
from rdflib import Graph, Literal, OWL, RDF, URIRef

from semantica.ingest.ontology_ingestor import OntologyIngestor


@pytest.mark.parametrize("version", [None, "2.1-candidate"])
def test_import_preserves_only_an_explicit_ontology_version(version):
    graph = Graph()
    subject = URIRef("https://example.org/business/")
    graph.add((subject, RDF.type, OWL.Ontology))
    if version is not None:
        graph.add((subject, OWL.versionInfo, Literal(version)))
    ontology = OntologyIngestor()._convert_to_dict(graph, "business.ttl", "turtle")
    assert ontology["version"] == version
