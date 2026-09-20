import assert from "node:assert/strict";
import test from "node:test";
import Graph from "graphology";

import { clearGraph, graph as sourceGraph, type NodeAttributes } from "../src/store/graphStore.ts";
import { buildGraphColorLegend } from "../src/workspaces/GraphWorkspace/graphColorLegend.ts";
import { resolveDisplayGraph, resolveNodeElementStyle } from "../src/workspaces/GraphWorkspace/graphSceneState.ts";
import { GRAPH_THEME, withAlpha } from "../src/workspaces/GraphWorkspace/graphTheme.ts";

function attributes(overrides: Partial<NodeAttributes> = {}): NodeAttributes {
  return {
    label: "Example", content: "Example", x: 0, y: 0, size: 8,
    nodeType: "Person", semanticGroup: "Person", color: "#123456",
    properties: {}, ...overrides,
  };
}

test("default canvas color is neutral across types, modules, and stored color metadata", () => {
  const samples = [
    attributes({ nodeType: "https://example.org/policy#FinanceHead", baseColor: "#abcdef" }),
    attributes({ nodeType: "https://example.org/policy#Contract", semanticGroup: "Procurement", color: "#ff0000", baseColor: "#ff00ff", mutedColor: "#ff0000", borderColor: "#ffff00", glowColor: "#ff0000" }),
    attributes({ nodeType: "https://example.org/policy#Invoice", semanticGroup: "Finance", color: "#0000ff", baseColor: "#00ffff", strokeColor: "#00ff00", haloColor: "#00ff00" }),
  ];
  const before = structuredClone(samples);
  for (const tier of ["overview", "structure", "inspection"] as const) {
    for (const state of ["default", "neighbor", "muted", "inactive"] as const) {
      const styles = samples.map((attrs) => resolveNodeElementStyle(GRAPH_THEME, tier, state, attrs, attrs.label));
      for (const style of styles.slice(1)) {
        assert.equal(style.color, styles[0].color, `${tier}/${state} fill`);
        assert.equal(style.shellColor, styles[0].shellColor, `${tier}/${state} shell`);
        assert.equal(style.borderColor, styles[0].borderColor, `${tier}/${state} border`);
        assert.equal(style.haloColor, styles[0].haloColor, `${tier}/${state} halo`);
      }
    }
  }
  const style = resolveNodeElementStyle(GRAPH_THEME, "inspection", "default", samples[0], samples[0].label);
  assert.equal(style.color, withAlpha(GRAPH_THEME.palette.overview.nodeCore, GRAPH_THEME.nodes.entityShapes.entity.fillAlpha));
  assert.deepEqual(samples, before, "Display policy must preserve original graph metadata");
});

test("selection, hover, and path colors override stored ring and glow metadata", () => {
  for (const state of ["selected", "hovered", "path"] as const) {
    const clean = attributes();
    const colored = attributes({ baseColor: "#ff0000", ringColor: "#ff0000", haloColor: "#00ff00", glowColor: "#ffff00" });
    for (const tier of ["overview", "structure", "inspection"] as const) {
      const expected = resolveNodeElementStyle(GRAPH_THEME, tier, state, clean, clean.label);
      const actual = resolveNodeElementStyle(GRAPH_THEME, tier, state, colored, colored.label);
      assert.equal(actual.color, GRAPH_THEME.palette.accent[state]);
      assert.equal(actual.borderColor, expected.borderColor);
      assert.equal(actual.ringColor, expected.ringColor);
      assert.equal(actual.haloColor, expected.haloColor);
      assert.equal(actual.showHalo, true);
      assert.equal(actual.forceLabel, true);
    }
  }
});

test("grouped display nodes share the neutral fill without losing their group shape", () => {
  const first = attributes({ isCommunityGroup: true, entityShape: "community", baseColor: "#ff0000", borderColor: "#ff0000" });
  const second = attributes({ isCommunityGroup: true, entityShape: "community", baseColor: "#0000ff", borderColor: "#0000ff" });
  for (const tier of ["overview", "structure", "inspection"] as const) {
    const left = resolveNodeElementStyle(GRAPH_THEME, tier, "default", first, first.label);
    const right = resolveNodeElementStyle(GRAPH_THEME, tier, "default", second, second.label);
    assert.equal(left.color, right.color);
    assert.equal(left.borderColor, right.borderColor);
    assert.equal(left.entityShape, "community");
  }
});

test("semantic groups, not shape categories, determine labels and distinct entries", () => {
  const graph = new Graph();
  graph.addNode("one", attributes({ semanticGroup: "Research", entityShape: "compound" }));
  graph.addNode("two", attributes({ semanticGroup: "Research", entityShape: "entity" }));
  graph.addNode("synthetic", attributes({ semanticGroup: "Research", baseColor: "#654321", isCommunityGroup: true }));
  graph.addNode("hidden", { ...attributes(), hidden: true });
  assert.deepEqual(buildGraphColorLegend(graph).map(({ group, color, count }) => ({ group, color, count })), [
    { group: "Research", color: "#123456", count: 2 },
    { group: "Research", color: "#654321", count: 1 },
  ]);
  assert.equal(new Set(buildGraphColorLegend(graph).map((item) => item.id)).size, 2);
});

test("legend rebuilds after in-place changes and uses only the supplied display graph", () => {
  const graph = new Graph();
  graph.addNode("one", attributes());
  graph.addNode("two", attributes({ semanticGroup: "Location" }));
  const first = buildGraphColorLegend(graph);
  graph.mergeNodeAttributes("one", { semanticGroup: "Project", baseColor: "#fedcba" });
  graph.dropNode("two");
  assert.equal(first.length, 2);
  assert.deepEqual(buildGraphColorLegend(graph).map(({ group, color }) => ({ group, color })), [
    { group: "Project", color: "#fedcba" },
  ]);
  graph.clear();
  assert.deepEqual(buildGraphColorLegend(graph), []);
});

test("fallback labels and ordering are stable and no groups are silently dropped", () => {
  const graph = new Graph();
  graph.addNode("fallback", attributes({ semanticGroup: undefined, nodeType: "" }));
  for (let i = 11; i >= 0; i -= 1) graph.addNode(String(i), attributes({ semanticGroup: undefined, nodeType: `Type ${i}` }));
  const items = buildGraphColorLegend(graph);
  assert.equal(items.length, 13);
  assert.ok(items.some((item) => item.group === "entity"));
  const reverse = new Graph();
  graph.nodes().reverse().forEach((id) => reverse.addNode(id, graph.getNodeAttributes(id)));
  assert.deepEqual(items, buildGraphColorLegend(reverse));
});


test("focused legend keeps semantic colors for selected, path, and neighbor clones", (t) => {
  clearGraph();
  t.after(clearGraph);
  for (const id of ["selected", "path", "neighbor", "outside"]) {
    sourceGraph.addNode(id, attributes({ label: id, baseColor: "#abcdef" }));
  }
  sourceGraph.addDirectedEdgeWithKey("path-edge", "selected", "path", { weight: 1 });
  sourceGraph.addDirectedEdgeWithKey("neighbor-edge", "selected", "neighbor", { weight: 1 });
  const focused = resolveDisplayGraph("selected", ["selected", "path"], ["path-edge"], "focused").graph;

  // Verify the fixture exercises baked interaction colors, not ordinary clones.
  assert.equal(focused.getNodeAttribute("selected", "baseColor"), GRAPH_THEME.palette.accent.selected);
  assert.equal(focused.getNodeAttribute("path", "baseColor"), GRAPH_THEME.palette.accent.path);
  assert.notEqual(focused.getNodeAttribute("neighbor", "baseColor"), "#abcdef");
  assert.ok(!focused.hasNode("outside"));
  assert.deepEqual(buildGraphColorLegend(focused).map(({ group, color, count }) => ({ group, color, count })), [
    { group: "Person", color: "#abcdef", count: 3 },
  ]);
  assert.equal(sourceGraph.getNodeAttribute("selected", "baseColor"), "#abcdef");

  // Changing focus retains the semantic swatch while following the displayed subset.
  const nextFocus = resolveDisplayGraph("neighbor", [], [], "focused").graph;
  assert.deepEqual(buildGraphColorLegend(nextFocus).map(({ color, count }) => ({ color, count })), [
    { color: "#abcdef", count: 2 },
  ]);
});
