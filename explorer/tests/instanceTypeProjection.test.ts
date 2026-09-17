import assert from "node:assert/strict";
import test from "node:test";
import { graph } from "../src/store/graphStore.ts";
import { resolveDisplayGraph, resolveEdgeElementStyle } from "../src/workspaces/GraphWorkspace/graphSceneState.ts";
import { GRAPH_THEME } from "../src/workspaces/GraphWorkspace/graphTheme.ts";
import type { EdgeAttributes } from "../src/store/graphStore.ts";
import { createKnowledgeGraphScope } from "../src/workspaces/GraphWorkspace/graphSchemaScope.ts";
import { projectInstanceTypes } from "../src/workspaces/GraphWorkspace/instanceTypeProjection.ts";
import type { InstanceTypesSnapshot } from "../src/workspaces/GraphWorkspace/instanceTypes.ts";

const snapshot: InstanceTypesSnapshot = {
  node_id: "rule", status: "declared", types: [
    { class_uri: "https://example.test/ProcessRule", label: "流程规则", loaded: true, ontology_uri: "https://example.test/", basis: [{ kind: "graph_namespace", value: "https://example.test/" }] },
    { class_uri: "https://external.test/Rule", label: "Rule", loaded: false, ontology_uri: null, basis: [{ kind: "rdf_type_property", value: "https://external.test/Rule" }] },
  ], related_concepts: [{ class_uri: "https://example.test/Request", label: "采购申请", ontology_uri: "https://example.test/", evidence_ids: ["evidence"] }], related_status: "ready", notice: "Candidate association only",
};
function node(id: string, nodeType = "entity") {
  graph.addNode(id, { nodeType, label: id, content: id, x: 0, y: 0, size: 8, color: "#123456", properties: {} });
}
function setup(mode: "full" | "focused" | "grouped" = "full") {
  node("rule", "ProcessRule"); node("evidence");
  node(snapshot.types[0].class_uri, "owl:Class"); node(snapshot.related_concepts[0].class_uri, "owl:Class");
  graph.addDirectedEdgeWithKey("support", "rule", "evidence", { edgeType: "hasEvidence", weight: 1, properties: {} });
  const scope = createKnowledgeGraphScope(graph);
  return resolveDisplayGraph("rule", [], [], mode, { sourceGraph: scope.graph });
}
test.beforeEach(() => graph.clear());
test.after(() => graph.clear());

test("type links add only declared classes to a copy without writing RDF or connecting business evidence as type", () => {
  const base = setup(); const original = graph.export(); const originalDisplay = base.graph.export();
  const result = projectInstanceTypes(base, snapshot, graph);
  assert.equal(result.graph.order, 4); assert.equal(result.graph.size, 3);
  assert.equal(result.graph.hasNode(snapshot.related_concepts[0].class_uri), false);
  assert.equal(result.links.size, 2); assert.equal(result.classReferences.size, 2);
  assert.deepEqual(graph.export(), original); assert.deepEqual(base.graph.export(), originalDisplay);
  for (const [id, type] of result.links) {
    assert.deepEqual(result.graph.extremities(id), ["rule", type.class_uri]);
    assert.equal(result.graph.getEdgeAttribute(id, "edgeType"), "rdf:type");
    assert.equal(graph.hasEdge(id), false);
  }
});
test("missing class definitions become explicit display references and do not enter the store", () => {
  const result = projectInstanceTypes(setup(), snapshot, graph);
  const ref = result.graph.getNodeAttributes(snapshot.types[1].class_uri);
  assert.match(ref.label, /not loaded/i);
  assert.equal(graph.hasNode(snapshot.types[1].class_uri), false);
  assert.ok(Number.isFinite(ref.x)); assert.ok(Number.isFinite(ref.y));
});
test("type links have a visible curved rendering path when inspecting their endpoints", () => {
  const result = projectInstanceTypes(setup("focused"), snapshot, graph);
  const edgeId = [...result.links.keys()][0];
  const attrs = result.graph.getEdgeAttributes(edgeId) as EdgeAttributes;
  const style = resolveEdgeElementStyle(GRAPH_THEME, "inspection", "neighbor", attrs, "rule", snapshot.types[0].class_uri, "focused", edgeId);
  assert.equal(style.hidden, false);
  assert.ok(Math.abs(style.curvature) > 0);
});
test("switching instances or disabling links leaves no prior class references", () => {
  const base = setup(); projectInstanceTypes(base, snapshot, graph);
  assert.equal(projectInstanceTypes(base, null, graph).graph, base.graph);
  const next = projectInstanceTypes(base, { ...snapshot, node_id: "evidence", types: [] }, graph);
  assert.deepEqual(next.graph.export(), base.graph.export());
  const missing = projectInstanceTypes(base, { ...snapshot, node_id: "not-visible" }, graph);
  assert.equal(missing.links.size, 0);
});
test("requested classes survive the focused neighbor cap and do not get bundled with business relationships", () => {
  setup("focused");
  for (let i = 0; i < 30; i++) { node(`n${i}`); graph.addDirectedEdgeWithKey(`e${i}`, "rule", `n${i}`, { edgeType: "mentions", weight: 1, properties: {} }); }
  const base = resolveDisplayGraph("rule", [], [], "focused", { sourceGraph: createKnowledgeGraphScope(graph).graph });
  assert.equal(base.graph.order, 17);
  const result = projectInstanceTypes(base, snapshot, graph);
  assert.equal(result.graph.order, 19);
  assert.equal(result.links.size, 2);
  assert.deepEqual(result.graph.getEdgeAttribute([...result.links.keys()][0], "rawEdgeIds"), []);
  assert.ok(result.state.selectedVisibleNeighborIds.includes(snapshot.types[0].class_uri));
});
test("a visible class and a business relation sharing its endpoints are preserved", () => {
  setup(); graph.addDirectedEdgeWithKey("business", "rule", snapshot.types[0].class_uri, { edgeType: "mentions", weight: 1, properties: {} });
  const base = resolveDisplayGraph("rule", [], [], "full");
  const result = projectInstanceTypes(base, snapshot, graph);
  assert.equal(result.graph.size, base.graph.size + 2);
  assert.equal(result.links.size, 2);
  assert.equal(result.classReferences.size, 1);
});

test("large displayed graphs can show class links without overflowing the call stack", () => {
  const base = setup();
  for (let i = 0; i < 150000; i++) {
    base.graph.addNode(`large-${i}`, { nodeType: "entity", content: "", label: "", properties: {}, x: i, y: -i, size: 1, color: "#123456" });
  }
  const result = projectInstanceTypes(base, snapshot, graph);
  assert.equal(result.links.size, 2);
  assert.ok(Number.isFinite(result.graph.getNodeAttribute(snapshot.types[0].class_uri, "x")));
});
