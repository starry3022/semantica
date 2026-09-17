import assert from "node:assert/strict";
import test from "node:test";
import Graph from "graphology";
import { graph, type EdgeAttributes, type NodeAttributes } from "../src/store/graphStore.ts";
import {
  checkGroupedViewAvailability,
  resolveDisplayGraph,
  resolveDisplayStateSnapshot,
} from "../src/workspaces/GraphWorkspace/graphSceneState.ts";
import { createKnowledgeGraphScope } from "../src/workspaces/GraphWorkspace/graphSchemaScope.ts";

function addNode(target: typeof graph, id: string, nodeType = "entity", properties: Record<string, unknown> = {}) {
  target.addNode(id, { label: id, content: id, nodeType, properties, x: 0, y: 0, color: "#123456", size: 8 });
}

function addEdge(target: typeof graph, id: string, source: string, destination: string, edgeType = "related_to") {
  target.addDirectedEdgeWithKey(id, source, destination, { edgeType, weight: 1, properties: {} });
}

test.beforeEach(() => graph.clear());
test.after(() => graph.clear());

function scopedFixture() {
  addNode(graph, "rule", "ProcessRule");
  addNode(graph, "evidence", "Evidence");
  addNode(graph, "schema", "owl:Class");
  addEdge(graph, "support", "rule", "evidence", "hasEvidence");
  addEdge(graph, "type", "rule", "schema", "rdf:type");
  const sourceGraph = graph.copy() as Graph<NodeAttributes, EdgeAttributes>;
  sourceGraph.dropNode("schema");
  return sourceGraph;
}

test("full display uses the supplied scope without mutating the canonical graph", () => {
  const sourceGraph = scopedFixture();
  const before = graph.export();
  const result = resolveDisplayGraph("", [], [], "full", { sourceGraph });
  assert.deepEqual(result.graph.nodes().sort(), ["evidence", "rule"]);
  assert.deepEqual(result.graph.edges(), ["support"]);
  assert.deepEqual(graph.export(), before);
});

test("focused neighbors and collapse state use the supplied scope", () => {
  const sourceGraph = scopedFixture();
  const result = resolveDisplayGraph("rule", [], [], "focused", { sourceGraph });
  const state = resolveDisplayStateSnapshot("rule", [], "full", { sourceGraph });
  assert.deepEqual(result.graph.nodes().sort(), ["evidence", "rule"]);
  assert.deepEqual(state.selectedVisibleNeighborIds, ["evidence"]);
  const collapsed = resolveDisplayGraph("rule", [], [], "full", { sourceGraph, collapsedNeighborhoodNodeIds: ["rule"] });
  assert.equal(collapsed.graph.hasNode("schema"), false);
});

test("grouped display and availability operate on the scope including an empty scope", () => {
  const sourceGraph = scopedFixture();
  const result = resolveDisplayGraph("", [], [], "grouped", { sourceGraph });
  const members = result.graph.mapNodes((id, attrs) => attrs.properties?.__communityGroup?.memberNodeIds ?? [id]).flat();
  assert.deepEqual(members.sort(), ["evidence", "rule"]);
  sourceGraph.clear();
  assert.equal(checkGroupedViewAvailability(sourceGraph).available, false);
  assert.equal(resolveDisplayGraph("", [], [], "grouped", { sourceGraph }).graph.order, 0);
});

test("existing resolver calls keep the complete graph when no scope is provided", () => {
  scopedFixture();
  assert.equal(resolveDisplayGraph("", [], [], "full").graph.order, 3);
});

test("default scope hides exact compact and full schema definitions while preserving knowledge instances", () => {
  const schemaTypes = ["owl:Ontology", "owl:Class", "rdfs:Class", "rdf:Property", "rdfs:Property", "owl:ObjectProperty", "owl:DatatypeProperty", "owl:AnnotationProperty", "owl:Restriction", "rdfs:Datatype", "http://www.w3.org/2002/07/owl#Class", "http://www.w3.org/2000/01/rdf-schema#Datatype"];
  schemaTypes.forEach((nodeType, index) => addNode(graph, `schema-${index}`, nodeType));
  const instanceTypes = ["ProcessRule", "Evidence", "SourceDocument", "PurchaseRequest", "owl:NamedIndividual", "skos:Concept", "http://www.w3.org/2004/02/skos/core#Concept", "CustomProperty"];
  instanceTypes.forEach((nodeType, index) => addNode(graph, `instance-${index}`, nodeType, { scheme_uri: "business" }));
  addEdge(graph, "evidence-link", "instance-0", "instance-1", "hasEvidence");
  const before = graph.export();
  const result = createKnowledgeGraphScope(graph);
  assert.deepEqual(result.graph.nodes().sort(), instanceTypes.map((_, index) => `instance-${index}`).sort());
  assert.equal(result.hiddenNodeCount, schemaTypes.length);
  assert.deepEqual(result.graph.edges(), ["evidence-link"]);
  assert.deepEqual(graph.export(), before);
  const full = createKnowledgeGraphScope(graph, true);
  assert.equal(full.graph, graph);
  assert.equal(full.hiddenNodeCount, 0);
  assert.deepEqual(full.graph.export(), before);
});

test("schema type metadata and explicit rdf:type assertions are honored without label guessing", () => {
  addNode(graph, "typed-in-properties", "entity", { "rdf:type": ["owl:Class"] });
  addNode(graph, "full-type", "entity", { "http://www.w3.org/1999/02/22-rdf-syntax-ns#type": "http://www.w3.org/2002/07/owl#ObjectProperty" });
  addNode(graph, "declared-in-edge");
  addNode(graph, "owl:Class");
  addEdge(graph, "declaration", "declared-in-edge", "owl:Class", "http://www.w3.org/1999/02/22-rdf-syntax-ns#type");
  addNode(graph, "real-instance", "Request", { "rdf:type": "typed-in-properties" });
  addNode(graph, "http://example.test/ontology/looks-like-a-class", "entity", { scheme_uri: "business", label: "owl:Class" });
  addEdge(graph, "instance-type", "real-instance", "typed-in-properties", "rdf:type");
  const result = createKnowledgeGraphScope(graph);
  assert.deepEqual(result.graph.nodes().sort(), ["http://example.test/ontology/looks-like-a-class", "real-instance"]);
  assert.equal(result.hiddenEdgeCount, 2);
});

test("only solely structural generic endpoints are hidden, with no arbitrary neighbor traversal", () => {
  addNode(graph, "property", "owl:DatatypeProperty");
  addNode(graph, "datatype");
  addNode(graph, "external-class");
  addNode(graph, "mixed-use");
  addNode(graph, "business", "Customer");
  addNode(graph, "knowledge", "skos:Concept");
  addNode(graph, "individual", "owl:NamedIndividual");
  addNode(graph, "ordinary-neighbor");
  addEdge(graph, "range", "property", "datatype", "rdfs:range");
  addEdge(graph, "domain", "property", "external-class", "http://www.w3.org/2000/01/rdf-schema#domain");
  addEdge(graph, "mixed-domain", "property", "mixed-use", "rdfs:domain");
  addEdge(graph, "ordinary", "mixed-use", "business", "owns");
  addEdge(graph, "concept", "property", "knowledge", "rdfs:range");
  addEdge(graph, "named", "property", "individual", "rdfs:range");
  addEdge(graph, "unrelated", "property", "ordinary-neighbor", "mentions");
  const result = createKnowledgeGraphScope(graph);
  assert.deepEqual(result.graph.nodes().sort(), ["business", "individual", "knowledge", "mixed-use", "ordinary-neighbor"]);
  assert.deepEqual(result.graph.edges(), ["ordinary"]);
});

test("legacy graphs retain identity; schema-only graphs are empty until included", () => {
  addNode(graph, "legacy");
  assert.equal(createKnowledgeGraphScope(graph).graph, graph);
  graph.clear();
  addNode(graph, "ontology", "owl:Ontology");
  assert.equal(createKnowledgeGraphScope(graph).graph.order, 0);
  assert.equal(createKnowledgeGraphScope(graph, true).graph.order, 1);
});

test("scope recalculates for live additions and changed schema types without altering source data", () => {
  addNode(graph, "live", "entity");
  assert.equal(createKnowledgeGraphScope(graph).graph.order, 1);
  graph.mergeNodeAttributes("live", { nodeType: "owl:Class" });
  addNode(graph, "new-rule", "ProcessRule");
  assert.deepEqual(createKnowledgeGraphScope(graph).graph.nodes(), ["new-rule"]);
  graph.mergeNodeAttributes("live", { nodeType: "Customer" });
  assert.equal(createKnowledgeGraphScope(graph).graph, graph);
});
