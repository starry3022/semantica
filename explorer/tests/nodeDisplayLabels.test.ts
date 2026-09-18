import assert from "node:assert/strict";
import test from "node:test";
import Graph from "graphology";
import type { EdgeAttributes, NodeAttributes } from "../src/store/graphStore.ts";
import { getNodeDisplayLabel, projectApprovalGroupLabels } from "../src/workspaces/GraphWorkspace/nodeDisplayLabels.ts";
import { resolveDisplayGraph } from "../src/workspaces/GraphWorkspace/graphSceneState.ts";

function fixture() {
  const graph = new Graph<NodeAttributes, EdgeAttributes>({ type: "directed", multi: true });
  const add = (id: string, nodeType: string, label: string, properties: Record<string, unknown> = {}) => {
    graph.addNode(id, { label, content: label, nodeType, properties, x: 0, y: 0, size: 8, color: "#123456" });
  };
  const link = (id: string, source: string, target: string, edgeType = "hasApprovalGroup") => {
    graph.addDirectedEdgeWithKey(id, source, target, { edgeType, weight: 1, properties: {} });
  };
  add("rule", "ProcessRule", "采购审批 · 审批 [C007]", { source_clause_id: "C007" });
  add("group", "ApprovalGroup", "审批组 (all)", { mode: "all", fact_status: "candidate", review_status: "unreviewed" });
  link("approval", "rule", "group");
  return { graph, add, link };
}

test("old approval groups gain the associated rule's main clause without rewriting source content", () => {
  const { graph } = fixture();
  const before = graph.export();
  const projected = projectApprovalGroupLabels(graph);
  assert.equal(projected.getNodeAttribute("group", "label"), "审批组 (all) [C007]");
  assert.equal(getNodeDisplayLabel(graph, "group", "审批组 (all)"), "审批组 (all) [C007]", "search results resolve an existing graph ID even when their API content is old");
  assert.equal(projected.getNodeAttribute("group", "content"), "审批组 (all)");
  assert.deepEqual(projected.getNodeAttribute("group", "properties"), before.nodes.find(node => node.key === "group")?.attributes?.properties);
  assert.deepEqual(graph.export(), before);
});

test("shared groups show every distinct main clause in a stable order and acknowledge unknown clauses", () => {
  const { graph, add, link } = fixture();
  add("earlier", "ProcessRule", "Earlier", { source_clause_id: "C005", supporting_clause_ids: ["C003"] });
  add("same-clause", "ProcessRule", "Same main clause", { source_clause_id: "C007" });
  add("unknown", "ProcessRule", "Rule [C099]", {});
  link("duplicate-edge", "rule", "group");
  link("earlier-edge", "earlier", "group");
  link("same-edge", "same-clause", "group");
  link("unknown-edge", "unknown", "group");
  assert.equal(getNodeDisplayLabel(graph, "group"), "审批组 (all) [C005, C007, 未知条款]");
  graph.dropEdge("earlier-edge");
  link("earlier-edge-reordered", "earlier", "group");
  assert.equal(getNodeDisplayLabel(graph, "group"), "审批组 (all) [C005, C007, 未知条款]");
});

test("only a correctly directed approval relation from a process rule can supply a clause", () => {
  const { graph, add, link } = fixture();
  graph.dropEdge("approval");
  link("wrong-direction", "group", "rule");
  link("wrong-relation", "rule", "group", "hasActor");
  add("role", "Role", "Role", { source_clause_id: "C009" });
  link("wrong-source-type", "role", "group");
  add("other", "ApprovalGroupLike", "Custom node", {});
  link("wrong-target-type", "rule", "other");
  assert.equal(getNodeDisplayLabel(graph, "group"), "审批组 (all)");
  assert.equal(getNodeDisplayLabel(graph, "other"), "Custom node");
  assert.equal(projectApprovalGroupLabels(graph), graph, "unrelated graphs do not need a clone");
});

test("missing or invalid main-clause fields stay unknown rather than being inferred from the rule name", () => {
  const { graph } = fixture();
  for (const source_clause_id of [undefined, null, "", "  ", ["C007"], 7, { id: "C007" }]) {
    graph.setNodeAttribute("rule", "properties", { source_clause_id, supporting_clause_ids: ["C005"] });
    assert.equal(getNodeDisplayLabel(graph, "group"), "审批组 (all) [未知条款]");
  }
  graph.dropEdge("approval");
  assert.equal(getNodeDisplayLabel(graph, "group"), "审批组 (all)");
});

test("existing clause suffixes are not repeated and remain stable through repeated projection", () => {
  const { graph, add, link } = fixture();
  graph.setNodeAttribute("group", "label", "审批组 (all) [C007]");
  assert.equal(getNodeDisplayLabel(graph, "group"), "审批组 (all) [C007]");
  add("earlier", "ProcessRule", "Earlier", { source_clause_id: "C005" });
  link("earlier-edge", "earlier", "group");
  assert.equal(getNodeDisplayLabel(graph, "group"), "审批组 (all) [C005, C007]");
  const projected = projectApprovalGroupLabels(graph);
  assert.equal(getNodeDisplayLabel(projected, "group"), "审批组 (all) [C005, C007]");
  assert.equal(projectApprovalGroupLabels(projected), projected);
});

test("ordinary bracketed text is preserved instead of being mistaken for a generated clause suffix", () => {
  const { graph } = fixture();
  graph.setNodeAttribute("group", "label", "审批组 [办公采购] (all)");
  assert.equal(getNodeDisplayLabel(graph, "group"), "审批组 [办公采购] (all) [C007]");
});

test("explicit compact and full process vocabulary terms support the same display labels", () => {
  const { graph } = fixture();
  graph.setNodeAttribute("rule", "nodeType", "https://example.test/process/ProcessRule");
  graph.setNodeAttribute("group", "nodeType", "proc:ApprovalGroup");
  graph.setEdgeAttribute("approval", "edgeType", "https://example.test/process#hasApprovalGroup");
  assert.equal(getNodeDisplayLabel(graph, "group"), "审批组 (all) [C007]");
});

test("full and focused views keep the same group title even when an associated rule is outside focus", () => {
  const { graph, add, link } = fixture();
  add("earlier", "ProcessRule", "Earlier", { source_clause_id: "C005" });
  add("role", "Role", "直属主管");
  link("earlier-edge", "earlier", "group");
  link("membership", "group", "role", "hasRole");
  const sourceGraph = projectApprovalGroupLabels(graph);
  const full = resolveDisplayGraph("", [], [], "full", { sourceGraph }).graph;
  const focused = resolveDisplayGraph("role", [], [], "focused", { sourceGraph }).graph;
  assert.equal(focused.hasNode("earlier"), false);
  assert.equal(full.getNodeAttribute("group", "label"), "审批组 (all) [C005, C007]");
  assert.equal(focused.getNodeAttribute("group", "label"), "审批组 (all) [C005, C007]");
});

test("changes to the underlying relationship replace the display suffix without leaving stale labels", () => {
  const { graph } = fixture();
  assert.equal(projectApprovalGroupLabels(graph).getNodeAttribute("group", "label"), "审批组 (all) [C007]");
  graph.setNodeAttribute("rule", "properties", { source_clause_id: "C008" });
  assert.equal(projectApprovalGroupLabels(graph).getNodeAttribute("group", "label"), "审批组 (all) [C008]");
  graph.dropEdge("approval");
  assert.equal(projectApprovalGroupLabels(graph).getNodeAttribute("group", "label"), "审批组 (all)");
  assert.equal(getNodeDisplayLabel(graph, "absent", "API result label"), "API result label");
});
