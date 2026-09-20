import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { JSDOM } from "jsdom";
import { graph } from "../src/store/graphStore.ts";
import { GraphInspectorPanel } from "../src/workspaces/GraphWorkspace/GraphInspectorPanel.tsx";
import { ClassPropertiesPanel } from "../src/workspaces/OntologyWorkspace/ClassPropertiesPanel.tsx";
import { loadInstanceTypes, type InstanceTypesSnapshot } from "../src/workspaces/GraphWorkspace/instanceTypes.ts";

Object.assign(globalThis, { React });
const ns = "https://example.test/process/";
const definition = { key: "name", property_uri: ns + "name", label: "名称", loaded: true, ontology_uri: ns };
const snapshot = {
  node_id: "finance", status: "declared" as const,
  types: [{ class_uri: ns + "Role", label: "组织角色", loaded: true, ontology_uri: ns, basis: [] }],
  related_concepts: [], related_status: "unconfigured" as const, notice: "Candidate facts",
  property_definitions: [definition],
};
const props = {
  nodeId: "finance", predictions: [], predictionType: "", pathTargetId: "", pathResult: null,
  onPredictionTypeChange() {}, onRunPredictions() {}, onPathTargetChange() {}, onTracePath() {}, onDownloadProvenance() {},
  onOpenOntologyEntity() {},
};
function inspector(current: InstanceTypesSnapshot | null, extra = {}) {
  return new JSDOM(renderToStaticMarkup(<GraphInspectorPanel {...props} instanceTypes={current} {...extra} />)).window.document;
}
test.beforeEach(() => {
  graph.clear();
  graph.addNode("finance", { label: "财务负责人", nodeType: "Role", properties: { name: "财务负责人", review_status: "unreviewed" } });
});
test.afterEach(() => graph.clear());

test("Explorer and Hub show the same label and local key tied to the exact property IRI", () => {
  const explorer = inspector(snapshot);
  const button = explorer.querySelector('button[aria-label="View property 名称（name）"]');
  assert.equal(button?.textContent, "名称（name）");
  assert.equal(button?.getAttribute("title"), ns + "name");
  const hub = new JSDOM(renderToStaticMarkup(<ClassPropertiesPanel classUri={ns + "Role"}
    nodes={[{ id: ns + "Role", type: "owl:Class", content: "组织角色" }, { id: ns + "name", type: "owl:DatatypeProperty", content: "名称" }]}
    edges={[{ source: ns + "name", target: ns + "Role", type: "rdfs:domain" }]} onSelectTerm={() => {}} />)).window.document;
  const hubButton = hub.querySelector('button[aria-label="View property 名称（name）"]');
  assert.equal(hubButton?.textContent, button?.textContent);
  assert.equal(hubButton?.getAttribute("title"), ns + "name");
});

test("missing, stale, loading and failed definitions retain raw fields without wrong links", () => {
  for (const [current, extra] of [
    [null, {}], [snapshot, { instanceTypesLoading: true }],
    [snapshot, { instanceTypesError: "Unavailable" }], [{ ...snapshot, node_id: "other" }, {}],
    [{ ...snapshot, property_definitions: [{ ...definition, loaded: false }] }, {}],
  ] as const) {
    const document = inspector(current, extra);
    assert.equal(document.querySelector('button[aria-label="View property 名称（name）"]'), null);
    assert.ok(document.body.textContent?.includes("unreviewed"));
    assert.ok(document.body.textContent?.includes("name"));
  }
});

test("absolute property keys are not matched to another namespace's equal local name", () => {
  const other = "https://example.test/business/name";
  graph.setNodeAttribute("finance", "properties", { [other]: "另一个名称", name: "财务负责人" });
  const document = inspector({ ...snapshot, property_definitions: [definition, { ...definition, key: other, property_uri: other, label: "业务名称" }] });
  assert.equal(document.querySelector('button[aria-label="View property 业务名称（name）"]')?.getAttribute("title"), other);
  assert.equal(document.querySelector('button[aria-label="View property 名称（name）"]')?.getAttribute("title"), ns + "name");
});

test("untrusted property labels stay text and identical names are not repeated", () => {
  const label = '<img src=x onerror="alert(1)">';
  const document = inspector({ ...snapshot, property_definitions: [{ ...definition, label }] });
  assert.equal(document.querySelector("img,script"), null);
  assert.ok(document.body.textContent?.includes(label + "（name）"));
  assert.ok(inspector({ ...snapshot, property_definitions: [{ ...definition, label: "name" }] }).querySelector('button[aria-label="View property name"]'));
});

test("property definitions are optional for old servers and invalid definitions are rejected", async () => {
  const original = globalThis.fetch;
  try {
    const { property_definitions: definitions, ...legacy } = snapshot;
    for (const payload of [legacy, snapshot]) {
      globalThis.fetch = async () => new Response(JSON.stringify(payload));
      await loadInstanceTypes("finance");
    }
    for (const invalid of [null, {}, [{ ...definitions[0], property_uri: 42 }], [{ ...definition, loaded: "yes" }], [{ ...definition, key: null }]]) {
      globalThis.fetch = async () => new Response(JSON.stringify({ ...snapshot, property_definitions: invalid }));
      await assert.rejects(loadInstanceTypes("finance"));
    }
  } finally { globalThis.fetch = original; }
});
