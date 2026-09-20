import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { JSDOM } from "jsdom";
import { graph } from "../src/store/graphStore.ts";
import { GraphInspectorPanel } from "../src/workspaces/GraphWorkspace/GraphInspectorPanel.tsx";
import { GRAPH_THEME } from "../src/workspaces/GraphWorkspace/graphTheme.ts";
import type { InstanceTypesSnapshot } from "../src/workspaces/GraphWorkspace/instanceTypes.ts";

Object.assign(globalThis, { React });
const ns = "https://example.test/vocabulary/";
const snapshot: InstanceTypesSnapshot = {
  node_id: "finance", status: "declared", types: [{ class_uri: ns + "FinanceHead", label: "财务负责人", loaded: true, ontology_uri: ns, basis: [] }],
  related_concepts: [], related_status: "unconfigured", notice: "",
  property_definitions: [
    { key: ns + "text", property_uri: ns + "text", label: "文本", loaded: true, ontology_uri: ns },
    { key: ns + "confidence", property_uri: ns + "confidence", label: "置信度", loaded: true, ontology_uri: ns },
  ],
};
const props = {
  nodeId: "finance", predictions: [], predictionType: "", pathTargetId: "", pathResult: null,
  onPredictionTypeChange() {}, onRunPredictions() {}, onPathTargetChange() {}, onTracePath() {}, onDownloadProvenance() {},
  onOpenOntologyEntity() {},
};
function render(current: InstanceTypesSnapshot | null = snapshot) {
  return new JSDOM(renderToStaticMarkup(<GraphInspectorPanel {...props} instanceTypes={current} />)).window.document;
}
function section(document: Document, label: string) {
  return [...document.querySelectorAll("details")].find((details) => details.querySelector("summary")?.textContent === label);
}
test.beforeEach(() => {
  graph.clear();
  graph.addNode(ns + "FinanceHead", { label: "财务负责人", content: "财务负责人", nodeType: "owl:Class", properties: {} });
  graph.addNode("finance", { label: "财务负责人", nodeType: ns + "FinanceHead", color: "#ff0000", properties: {
    [ns + "text"]: "财务负责人", [ns + "confidence"]: "0.95", "rdf:type": [ns + "FinanceHead"], fact_status: "candidate", review_status: "unreviewed",
  } });
});
test.afterEach(() => graph.clear());

test("candidate status stays beside identity without a separate record panel or graph mutation", () => {
  const before = JSON.stringify(graph.export());
  const document = render();
  const properties = section(document, "Properties");
  assert.ok(properties);
  assert.equal(properties.querySelectorAll("button[title]").length, 2);
  assert.ok(properties.querySelector(`button[title="${ns}text"]`));
  assert.ok(properties.querySelector(`button[title="${ns}confidence"]`));
  for (const value of ["fact_status", "review_status", "rdf:type", "candidate", "unreviewed"]) {
    assert.equal(properties.textContent?.includes(value), false);
  }
  assert.equal(section(document, "Record details"), undefined);
  const status = document.querySelector('[aria-label="Review status"]');
  assert.ok(status?.textContent?.includes("candidate"));
  assert.ok(status?.textContent?.includes("unreviewed"));
  assert.ok(section(document, "Node identifier")?.textContent?.includes(ns + "FinanceHead"));
  assert.equal(JSON.stringify(graph.export()), before);
});

test("old graphs with explicitly identified governance predicates keep them alongside class properties", () => {
  const document = render({ ...snapshot, property_definitions: [...snapshot.property_definitions!, ...["fact_status", "review_status"].map(key => ({ key, property_uri: ns + key, label: key === "fact_status" ? "知识状态" : "业务审核状态", loaded: true, ontology_uri: ns }))] });
  const properties = section(document, "Properties")!;
  assert.ok(properties.querySelector(`button[title="${ns}fact_status"]`));
  assert.ok(properties.querySelector(`button[title="${ns}review_status"]`));
  assert.equal(section(document, "Record details"), undefined);
  assert.equal(document.querySelector('[aria-label="Review status"]'), null);
});

test("all supported type declaration keys stay out of the business property list", () => {
  for (const key of ["rdf:type", "http://www.w3.org/1999/02/22-rdf-syntax-ns#type", "@type"]) {
    graph.setNodeAttribute("finance", "properties", { [key]: ns + "FinanceHead" });
    const document = render();
    assert.equal(section(document, "Properties")?.textContent?.includes(ns + "FinanceHead"), false);
    assert.ok(section(document, "Node identifier")?.textContent?.includes(ns + "FinanceHead"));
  }
});

test("missing or stale definitions do not hide values or reuse another node's links", () => {
  for (const current of [null, { ...snapshot, node_id: "other" }]) {
    const document = render(current);
    assert.equal(section(document, "Properties")?.querySelectorAll("button[title]").length, 0);
    assert.ok(document.body.textContent?.includes("财务负责人"));
    assert.ok(document.querySelector('[aria-label="Review status"]')?.textContent?.includes("unreviewed"));
  }
});

test("namespace-qualified but unloaded status definitions remain record metadata", () => {
  const document = render({ ...snapshot, property_definitions: [...snapshot.property_definitions!, ...["fact_status", "review_status"].map(key => ({ key, property_uri: ns + key, label: key, loaded: false, ontology_uri: null }))] });
  const properties = section(document, "Properties")!;
  assert.equal(properties.textContent?.includes("candidate"), false);
  assert.equal(properties.textContent?.includes("unreviewed"), false);
  const status = document.querySelector('[aria-label="Review status"]');
  assert.ok(status?.textContent?.includes("candidate"));
  assert.ok(status?.textContent?.includes("unreviewed"));
});

test("explicit schema properties are not hidden just because their short keys resemble metadata", () => {
  graph.setNodeAttribute("finance", "properties", { confidence: 0.95, source: "policy", constructor: "business value" });
  const current = { ...snapshot, property_definitions: ["confidence", "source"].map(key => ({ key, property_uri: ns + key, label: key, loaded: true, ontology_uri: ns })) };
  const document = render(current);
  const properties = section(document, "Properties")!;
  assert.ok(properties.querySelector(`button[title="${ns}confidence"]`));
  assert.ok(properties.querySelector(`button[title="${ns}source"]`));
  assert.ok(properties.textContent?.includes("business value"));
  assert.equal(section(document, "Record details"), undefined);
});

test("inspector uses a neutral readable class badge while retaining the exact type IRI", () => {
  const document = render();
  const badge = document.querySelector(`span[title="${ns}FinanceHead"]`);
  assert.equal(badge?.textContent, "财务负责人");
  assert.ok(badge?.getAttribute("style")?.includes(GRAPH_THEME.ui.text.muted));
  graph.setNodeAttribute("finance", "nodeType", '<img src=x onerror="alert(1)">');
  const malicious = render(null);
  assert.equal(malicious.querySelector("img,script"), null);
  assert.ok(malicious.body.textContent?.includes('<img src=x onerror="alert(1)">'));
});
