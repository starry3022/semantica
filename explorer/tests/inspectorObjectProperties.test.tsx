import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { JSDOM } from "jsdom";
import { graph } from "../src/store/graphStore.ts";
import { GraphInspectorPanel } from "../src/workspaces/GraphWorkspace/GraphInspectorPanel.tsx";
import { loadInstanceTypes, type InstanceTypesSnapshot } from "../src/workspaces/GraphWorkspace/instanceTypes.ts";

const dom = new JSDOM("<html><body></body></html>", { url: "http://localhost" });
Object.assign(globalThis, { React, window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement, Node: dom.window.Node });
Object.defineProperty(globalThis, "navigator", { configurable: true, value: dom.window.navigator });
const { cleanup, fireEvent, render } = await import("@testing-library/react");
const ns = "https://example.test/ontology/";
const approves = ns + "approves";
const objectProperty = {
  property_uri: approves, label: "审批", loaded: true, ontology_uri: ns,
  targets: [
    { node_id: "purchase", label: "采购申请", edge_ids: ["approval-purchase"] },
    { node_id: "payment", label: "供应商付款申请", edge_ids: ["approval-payment"] },
  ],
};
const snapshot = {
  node_id: "finance", status: "declared" as const, types: [{ class_uri: ns + "FinanceHead", label: "财务负责人", loaded: true, ontology_uri: ns, basis: [] }],
  related_concepts: [], related_status: "unconfigured" as const, notice: "",
  property_definitions: [{ key: ns + "text", property_uri: ns + "text", label: "文本", loaded: true, ontology_uri: ns }],
  object_properties: [objectProperty],
};
const props = {
  nodeId: "finance", predictions: [], predictionType: "", pathTargetId: "", pathResult: null,
  onPredictionTypeChange() {}, onRunPredictions() {}, onPathTargetChange() {}, onTracePath() {}, onDownloadProvenance() {},
};
test.beforeEach(() => {
  graph.clear();
  graph.addNode("finance", { label: "财务负责人", nodeType: ns + "FinanceHead", properties: { [ns + "text"]: "财务负责人", fact_status: "candidate", review_status: "unreviewed" } });
  for (const target of objectProperty.targets) {
    graph.addNode(target.node_id, { label: target.label, properties: {} });
    graph.addDirectedEdgeWithKey(target.edge_ids[0], "finance", target.node_id, { edgeType: approves, properties: {} });
  }
  globalThis.fetch = async () => new Response("{}", { status: 404 });
});
test.afterEach(() => { cleanup(); graph.clear(); });

test("instance Properties includes outgoing object values and exact definition/relationship navigation", () => {
  const opened: string[] = [], inspected: string[] = [];
  const before = JSON.stringify(graph.export());
  const view = render(<GraphInspectorPanel {...props} instanceTypes={snapshot}
    onOpenOntologyEntity={(uri) => opened.push(uri)} onInspectRelationship={(id: string) => inspected.push(id)} />);
  const panel = view.getByText("Properties", { selector: "summary" }).parentElement!;
  fireEvent.click(view.getByText("Properties", { selector: "summary" }));
  assert.ok(view.queryByText("Record details") === null);
  assert.ok(panel.textContent?.includes("文本（text）"));
  fireEvent.click(view.getByRole("button", { name: "View property 审批（approves）", exact: true }));
  assert.deepEqual(opened, [approves]);
  for (const target of objectProperty.targets) {
    const button = view.getByRole("button", { name: `View relationship 审批（approves） → ${target.label}`, exact: true });
    assert.ok(panel.contains(button));
    fireEvent.click(button);
  }
  assert.deepEqual(inspected, ["approval-purchase", "approval-payment"]);
  assert.equal(JSON.stringify(graph.export()), before);
});

test("parallel relations remain individually inspectable without duplicating the property definition", () => {
  const current = { ...snapshot, object_properties: [{ ...objectProperty, targets: [{ ...objectProperty.targets[0], edge_ids: ["approval-purchase", "approval-other"] }] }] };
  graph.addDirectedEdgeWithKey("approval-other", "finance", "purchase", { edgeType: approves, properties: {} });
  const inspected: string[] = [];
  const view = render(<GraphInspectorPanel {...props} instanceTypes={current}
    onOpenOntologyEntity={() => {}} onInspectRelationship={(id: string) => inspected.push(id)} />);
  fireEvent.click(view.getByText("Properties", { selector: "summary" }));
  assert.equal(view.getAllByRole("button", { name: "View property 审批（approves）", exact: true }).length, 1);
  for (const button of view.getAllByRole("button", { name: /^View relationship / })) fireEvent.click(button);
  assert.deepEqual(inspected, ["approval-purchase", "approval-other"]);
});

test("node changes, loading, failure and old responses cannot retain earlier relationship values", () => {
  const view = render(<GraphInspectorPanel {...props} instanceTypes={snapshot} onInspectRelationship={() => {}} />);
  for (const extra of [
    { instanceTypes: { ...snapshot, node_id: "another" } },
    { instanceTypes: snapshot, instanceTypesLoading: true },
    { instanceTypes: snapshot, instanceTypesError: "Unavailable" },
    { instanceTypes: { ...snapshot, object_properties: undefined } },
    { instanceTypes: null },
  ]) {
    view.rerender(<GraphInspectorPanel {...props} {...extra} onInspectRelationship={() => {}} />);
    assert.equal(view.queryAllByRole("button", { name: /^View relationship /, hidden: true }).length, 0);
  }
});

test("same local names in different namespaces stay separate and unloaded definitions stay unlinked", () => {
  const foreign = { ...objectProperty, property_uri: "https://other.test/approves", label: "其他审批", loaded: false, ontology_uri: null, targets: [{ ...objectProperty.targets[1], edge_ids: ["foreign-edge"] }] };
  const view = render(<GraphInspectorPanel {...props} instanceTypes={{ ...snapshot, object_properties: [objectProperty, foreign] }} onOpenOntologyEntity={() => {}} />);
  fireEvent.click(view.getByText("Properties", { selector: "summary" }));
  assert.equal(view.getByRole("button", { name: "View property 审批（approves）", exact: true }).getAttribute("title"), approves);
  assert.equal(view.queryByRole("button", { name: "View property 其他审批（approves）", exact: true }), null);
  assert.ok(view.container.querySelector('[title="https://other.test/approves"]'));
});

test("a predicate with literal and object values has one exact-IRI property row", () => {
  graph.setNodeAttribute("finance", "properties", { [approves]: "literal legacy value" });
  const current = { ...snapshot, property_definitions: [{ key: approves, property_uri: approves, label: "审批", loaded: true, ontology_uri: ns }] };
  const view = render(<GraphInspectorPanel {...props} instanceTypes={current} onOpenOntologyEntity={() => {}} onInspectRelationship={() => {}} />);
  fireEvent.click(view.getByText("Properties", { selector: "summary" }));
  assert.equal(view.getAllByRole("button", { name: "View property 审批（approves）", exact: true }).length, 1);
  assert.ok(view.getByText("literal legacy value"));
  assert.equal(view.getAllByRole("button", { name: /^View relationship / }).length, 2);
});

test("untrusted object labels remain text and absent local edges cannot open the wrong relationship", () => {
  const label = '<img src=x onerror="alert(1)">';
  const current = { ...snapshot, object_properties: [{ ...objectProperty, label, targets: [{ node_id: "missing", label, edge_ids: ["missing-edge"] }] }] };
  const inspected: string[] = [];
  const view = render(<GraphInspectorPanel {...props} instanceTypes={current} onOpenOntologyEntity={() => {}} onInspectRelationship={(id: string) => inspected.push(id)} />);
  fireEvent.click(view.getByText("Properties", { selector: "summary" }));
  assert.equal(view.container.querySelector("img,script"), null);
  assert.ok(view.container.textContent?.includes(label));
  assert.equal(view.queryAllByRole("button", { name: /^View relationship / }).length, 0);
  assert.deepEqual(inspected, []);
});

test("object property DTOs accept old responses and reject ambiguous or malformed targets", async () => {
  const payload = (object_properties: unknown) => ({ ...snapshot, object_properties });
  for (const value of [payload(undefined), payload([]), snapshot]) {
    globalThis.fetch = async () => new Response(JSON.stringify(value));
    const result: InstanceTypesSnapshot = await loadInstanceTypes("finance");
    assert.equal(result.node_id, "finance");
  }
  for (const invalid of [null, {}, [null], [{ ...objectProperty, property_uri: "" }], [objectProperty, objectProperty],
    [{ ...objectProperty, loaded: "yes" }], [{ ...objectProperty, targets: [] }],
    [{ ...objectProperty, targets: [objectProperty.targets[0], objectProperty.targets[0]] }],
    ...[null, {}, [], [""], ["one", "one"], [42]].map(edge_ids => [{ ...objectProperty, targets: [{ ...objectProperty.targets[0], edge_ids }] }]),
  ]) {
    globalThis.fetch = async () => new Response(JSON.stringify(payload(invalid)));
    await assert.rejects(loadInstanceTypes("finance"));
  }
});
