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

function provenanceFixture() {
  const citationType = "https://provenance.test/QuotedSpan";
  const sourceType = "https://provenance.test/Material";
  const citationLink = "https://provenance.test/cites";
  for (const id of ["manager", "purchase", "payment", "applicant"]) addNode(graph, id, "BusinessObject");
  for (const [id, source, target] of [["purchase-approval", "manager", "purchase"], ["payment-approval", "manager", "payment"], ["authorization", "applicant", "manager"]]) {
    addEdge(graph, id, source, target, "https://business.test/relationship");
  }
  addNode(graph, citationType, "owl:Class", { schema_role: "provenance" });
  addNode(graph, sourceType, "owl:Class", { schema_role: "provenance" });
  addNode(graph, citationLink, "owl:ObjectProperty", { schema_role: "provenance" });
  addNode(graph, "material", sourceType);
  for (let index = 0; index < 4; index++) {
    const id = `citation-${index}`;
    // Cover exact declarations through node type, scalar/array metadata, and edges.
    addNode(graph, id, index === 0 ? citationType : "entity", index === 1 ? { "rdf:type": [citationType] }
      : index === 2 ? { "http://www.w3.org/1999/02/22-rdf-syntax-ns#type": citationType } : {});
    if (index === 3) addEdge(graph, "citation-type", id, citationType, "rdf:type");
    addEdge(graph, `cites-${index}`, "manager", id, citationLink);
    addEdge(graph, `material-${index}`, id, "material", "https://provenance.test/source");
  }
  return { citationType, sourceType, citationLink };
}

test("business graph keeps three relationships while four citations and their material are optional", () => {
  provenanceFixture();
  const before = graph.export();
  const scope = createKnowledgeGraphScope(graph);
  assert.deepEqual(scope.graph.nodes().sort(), ["applicant", "manager", "payment", "purchase"]);
  assert.deepEqual(scope.graph.edges().sort(), ["authorization", "payment-approval", "purchase-approval"]);
  assert.equal(scope.hiddenSchemaNodeCount, 3);
  assert.equal(scope.hiddenProvenanceNodeCount, 5);
  for (const mode of ["full", "focused", "grouped"] as const) {
    const result = resolveDisplayGraph("manager", [], [], mode, { sourceGraph: scope.graph });
    const members = result.graph.mapNodes((id, attrs) => attrs.properties?.__communityGroup?.memberNodeIds ?? [id]).flat();
    assert.ok(members.every(id => !scope.provenanceNodeIds.has(id)));
  }
  assert.equal(resolveDisplayStateSnapshot("manager", [], "focused", { sourceGraph: scope.graph }).selectedVisibleNeighborIds.length, 3);
  const expanded = createKnowledgeGraphScope(graph, false, true);
  assert.equal(expanded.graph.order, 9);
  assert.equal(expanded.graph.size, 11);
  assert.equal(expanded.hiddenProvenanceNodeCount, 0);
  assert.equal(resolveDisplayStateSnapshot("manager", [], "focused", { sourceGraph: expanded.graph }).selectedVisibleNeighborIds.length, 7);
  assert.deepEqual(graph.export(), before);
});

test("provenance and schema switches are independent and source data survives every combination", () => {
  const { citationType, citationLink } = provenanceFixture();
  // A declared provenance predicate can connect two business objects without hiding either object.
  addEdge(graph, "business-provenance", "purchase", "payment", citationLink);
  const before = graph.export();
  for (const includeSchema of [false, true]) {
    for (const includeProvenance of [false, true]) {
      const scope = createKnowledgeGraphScope(graph, includeSchema, includeProvenance);
      assert.equal(scope.graph.hasNode(citationType), includeSchema);
      assert.equal(scope.graph.hasNode("citation-0"), includeProvenance);
      assert.equal(scope.graph.hasEdge("business-provenance"), includeProvenance);
      assert.ok(scope.graph.hasNode("purchase") && scope.graph.hasNode("payment"));
      assert.deepEqual(graph.export(), before);
    }
  }
  assert.equal(createKnowledgeGraphScope(graph, true, true).graph, graph);
});

test("provenance display honors exact loaded roles and updates without guessing from evidence names", () => {
  const { citationType } = provenanceFixture();
  addNode(graph, "legacy-evidence", "Evidence");
  addNode(graph, "other-vocabulary", "https://other.test/QuotedSpan");
  addNode(graph, "same-label", "BusinessObject", { label: "Evidence", quote: "An ordinary business value" });
  let scope = createKnowledgeGraphScope(graph);
  for (const id of ["legacy-evidence", "other-vocabulary", "same-label"]) assert.ok(scope.graph.hasNode(id));
  graph.setNodeAttribute(citationType, "properties", {});
  scope = createKnowledgeGraphScope(graph);
  assert.ok(scope.graph.hasNode("citation-0"));
  graph.setNodeAttribute(citationType, "properties", { schema_role: "provenance" });
  scope = createKnowledgeGraphScope(graph);
  assert.equal(scope.graph.hasNode("citation-0"), false);
  assert.ok(graph.hasNode("citation-0"));
});
