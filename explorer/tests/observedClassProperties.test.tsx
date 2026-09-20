import assert from "node:assert/strict";
import test from "node:test";
import { JSDOM } from "jsdom";
import React from "react";
import { loadClassInstances } from "../src/workspaces/GraphWorkspace/instanceTypes.ts";
import type { OntologyGraphNode, OntologyGraphEdge } from "../src/workspaces/OntologyWorkspace/api.ts";

(globalThis as typeof globalThis & { React: typeof React }).React = React;
const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost" });
Object.assign(globalThis, { window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement, Node: dom.window.Node });
Object.defineProperty(globalThis, "navigator", { configurable: true, value: dom.window.navigator });
const { act, cleanup, fireEvent, render } = await import("@testing-library/react");
const { ClassPropertiesPanel } = await import("../src/workspaces/OntologyWorkspace/ClassPropertiesPanel.tsx");
const ns = "https://example.test/schema/";
const classUri = ns + "FinanceHead";
const owner = "https://example.test/ontology/";
const classNode: OntologyGraphNode = { id: classUri, type: "owl:Class", content: "财务负责人" };
const fields = [
  { property_uri: ns + "text", label: "文本", loaded: true, ontology_uri: owner, kinds: ["literal"], instance_count: 2 },
  { property_uri: ns + "confidence", label: "置信度", loaded: true, ontology_uri: owner, kinds: ["literal"], instance_count: 1 },
  { property_uri: ns + "approves", label: "审批", loaded: true, ontology_uri: owner, kinds: ["object"], instance_count: 1 },
];
const propertyNodes: OntologyGraphNode[] = fields.map((field) => ({ id: field.property_uri, type: field.kinds[0] === "literal" ? "owl:DatatypeProperty" : "owl:ObjectProperty", content: field.label, properties: { scheme_uri: owner } }));
const legacySnapshot = { class_uri: classUri, total: 2, skip: 0, limit: 1, instances: [{ node_id: "finance", label: "财务负责人", basis: [] }] };
const snapshot = { ...legacySnapshot, observed_properties: fields };
const response = (payload: unknown, status = 200) => new Response(JSON.stringify(payload), { status });
const originalFetch = globalThis.fetch;
test.afterEach(() => { cleanup(); globalThis.fetch = originalFetch; });

test("domainless predicates show exact identities and all-instance usage without inventing declarations", async () => {
  const requests: string[] = [];
  const opened: [string, string | null | undefined][] = [];
  globalThis.fetch = async (input) => { requests.push(String(input)); return response(snapshot); };
  const nodes = [classNode, ...propertyNodes];
  const before = JSON.stringify(nodes);
  const view = render(<ClassPropertiesPanel classUri={classUri} nodes={nodes} edges={[]} onSelectTerm={(uri, ontology) => opened.push([uri, ontology])} />);
  const button = await view.findByRole("button", { name: "View property 文本（text）" });
  assert.equal(button.title, ns + "text");
  fireEvent.click(button);
  assert.deepEqual(opened, [[ns + "text", owner]]);
  assert.equal(view.container.querySelectorAll("article").length, 3);
  assert.match(view.container.textContent ?? "", /Properties · 3/);
  assert.match(view.container.textContent ?? "", /Used by 2 of 2 instances/);
  assert.match(view.container.textContent ?? "", /Domain not declared/);
  assert.doesNotMatch(view.container.textContent ?? "", /Declared on this class/);
  assert.equal(new URL(requests[0], "http://localhost").searchParams.get("limit"), "1");
  assert.equal(JSON.stringify(nodes), before);
});

test("declared, inherited, range and observed properties merge once by exact IRI", async () => {
  globalThis.fetch = async () => response({ ...snapshot, observed_properties: fields.slice(0, 1) });
  const parent = ns + "Role";
  const edges: OntologyGraphEdge[] = [
    { source: classUri, target: parent, type: "rdfs:subClassOf" },
    { source: ns + "text", target: parent, type: "rdfs:domain" },
    { source: ns + "text", target: classUri, type: "rdfs:range" },
  ];
  const view = render(<ClassPropertiesPanel classUri={classUri} nodes={[classNode, ...propertyNodes, { id: parent, type: "owl:Class", content: "角色" }]} edges={edges} onSelectTerm={() => {}} />);
  await view.findByText(/Used by 2 of 2 instances/);
  assert.equal(view.getAllByRole("button", { name: "View property 文本（text）" }).length, 1);
  assert.equal(view.container.querySelectorAll("article").length, 1);
  assert.match(view.container.textContent ?? "", /Declared on parent: 角色/);
  assert.match(view.container.textContent ?? "", /Class appears in range/);
  assert.doesNotMatch(view.container.textContent ?? "", /Domain not declared/);
  assert.equal(view.queryByText(/Referenced as range/), null);
});

test("old servers keep incoming-only range references collapsed outside the property count", async () => {
  globalThis.fetch = async () => response(legacySnapshot);
  const inbound = ["requestedBy", "assignedTo", "reviewedBy"].map((name) => ({ id: ns + name, type: "owl:ObjectProperty", content: name }));
  const edges = [
    ...propertyNodes.map((node) => ({ source: node.id, target: classUri, type: "rdfs:domain" })),
    ...inbound.map((node) => ({ source: node.id, target: classUri, type: "rdfs:range" })),
  ];
  const opened: string[] = [];
  const view = render(<ClassPropertiesPanel classUri={classUri} nodes={[classNode, ...propertyNodes, ...inbound]} edges={edges} onSelectTerm={(uri) => opened.push(uri)} />);
  await view.findByText(/Instance property usage unavailable on this server/);
  assert.ok(view.getByRole("heading", { name: "Properties · 3" }));
  const summary = view.getByText("Referenced as range · 3", { selector: "summary" });
  assert.equal(summary.closest("details")?.open, false);
  assert.equal(view.getByRole("region", { name: "Class properties" }).querySelectorAll(":scope > article").length, 3);
  fireEvent.click(summary);
  fireEvent.click(view.getByRole("button", { name: "View property requestedBy" }));
  assert.deepEqual(opened, [ns + "requestedBy"]);
});

test("observed and declared predicates also used as ranges stay only in the main list", async () => {
  globalThis.fetch = async () => response({ ...snapshot, observed_properties: fields.slice(0, 1) });
  const edges = [
    { source: ns + "confidence", target: classUri, type: "rdfs:domain" },
    ...propertyNodes.map((node) => ({ source: node.id, target: classUri, type: "rdfs:range" })),
  ];
  const view = render(<ClassPropertiesPanel classUri={classUri} nodes={[classNode, ...propertyNodes]} edges={edges} onSelectTerm={() => {}} />);
  await view.findByText(/Used by 2 of 2 instances/);
  assert.ok(view.getByRole("heading", { name: "Properties · 2" }));
  assert.equal(view.getByRole("region", { name: "Class properties" }).querySelectorAll(":scope > article").length, 2);
  const summary = view.getByText("Referenced as range · 1", { selector: "summary" });
  fireEvent.click(summary);
  assert.equal(view.getAllByRole("button", { name: "View property 文本（text）" }).length, 1);
  assert.equal(view.getAllByRole("button", { name: "View property 置信度（confidence）" }).length, 1);
  assert.match(view.getByRole("button", { name: "View property 文本（text）" }).closest("article")?.textContent ?? "", /Class appears in range/);
  assert.match(view.getByRole("button", { name: "View property 置信度（confidence）" }).closest("article")?.textContent ?? "", /Class appears in range/);
  assert.equal(summary.closest("details")?.querySelectorAll("article").length, 1);
});

test("unloaded definitions and foreign same-name predicates never create false local links", async () => {
  const foreign = "https://other.test/text";
  const foreignOwner = "https://other.test/ontology/";
  const html = '<img src=x onerror="window.bad=1">';
  globalThis.fetch = async () => response({ ...snapshot, observed_properties: [
    fields[0], { ...fields[0], property_uri: foreign, label: html, ontology_uri: foreignOwner },
    { ...fields[0], property_uri: ns + "unknown", label: "未加载", loaded: false, ontology_uri: null },
    { ...fields[0], property_uri: ns + "unowned", label: "无所属本体", ontology_uri: null },
  ] });
  const opened: [string, string | null | undefined][] = [];
  const view = render(<ClassPropertiesPanel classUri={classUri} nodes={[classNode, ...propertyNodes]} edges={[]} onSelectTerm={(uri, ontology) => opened.push([uri, ontology])} />);
  fireEvent.click(await view.findByRole("button", { name: `View property ${html}（text）` }));
  assert.deepEqual(opened, [[foreign, foreignOwner]]);
  const unknown = view.getByRole("button", { name: "View property 未加载（unknown）" });
  assert.equal((unknown as HTMLButtonElement).disabled, true);
  assert.equal(view.container.querySelector("img,script"), null);
  assert.match(view.container.textContent ?? "", /Definition not loaded/);
  const unavailable = view.container.querySelector(`article[data-property-uri="${foreign}"]`);
  assert.doesNotMatch(unavailable?.textContent ?? "", /Domain not declared/);
  assert.match(unavailable?.textContent ?? "", /Definition in another ontology/);
  assert.equal((view.getByRole("button", { name: "View property 无所属本体（unowned）" }) as HTMLButtonElement).disabled, true);
  assert.match(view.container.querySelector(`article[data-property-uri="${ns}unowned"]`)?.textContent ?? "", /Definition not available in this view/);
});

test("old servers and failed usage requests preserve schema declarations without claiming no usage", async () => {
  const edges = [{ source: ns + "text", target: classUri, type: "rdfs:domain" }];
  for (const [payload, status] of [[legacySnapshot, 200], [{ detail: "Not found" }, 404], [{ ...snapshot, class_uri: "wrong" }, 200]] as const) {
    globalThis.fetch = async () => response(payload, status);
    const view = render(<ClassPropertiesPanel classUri={classUri} nodes={[classNode, ...propertyNodes]} edges={edges} onSelectTerm={() => {}} />);
    assert.ok(view.getByRole("button", { name: "View property 文本（text）" }));
    await view.findByText(/Instance property usage unavailable/);
    assert.match(view.container.textContent ?? "", /Declared on this class/);
    assert.doesNotMatch(view.container.textContent ?? "", /No properties|Used by 0/);
    if (payload !== legacySnapshot) assert.ok(view.getByRole("alert"));
    cleanup();
  }
});

test("class changes and graph revisions clear usage and abort stale requests before reloading", async () => {
  const pending: { resolve: (value: Response) => void; signal: AbortSignal | null | undefined }[] = [];
  globalThis.fetch = (_input, init) => new Promise<Response>((resolve) => { pending.push({ resolve, signal: init?.signal }); });
  const props = { classUri, nodes: [classNode, ...propertyNodes], edges: [], onSelectTerm() {} };
  const view = render(<ClassPropertiesPanel {...props} graphRevision={1} />);
  await act(async () => pending[0].resolve(response(snapshot)));
  await view.findByText(/Used by 2 of 2 instances/);
  view.rerender(<ClassPropertiesPanel {...props} graphRevision={2} />);
  assert.equal(pending[0].signal?.aborted, true);
  assert.equal(view.queryByRole("button", { name: "View property 文本（text）" }), null);
  const next = ns + "Other";
  view.rerender(<ClassPropertiesPanel {...props} classUri={next} graphRevision={2} />);
  assert.equal(pending[1].signal?.aborted, true);
  await act(async () => pending[1].resolve(response(snapshot)));
  assert.equal(view.queryByText(/Used by 2 of 2 instances/), null);
  await act(async () => pending[2].resolve(response({ ...snapshot, class_uri: next, total: 0, instances: [], observed_properties: [] })));
  await view.findByText(/No declared or observed properties/);
  assert.equal(view.queryByRole("button", { name: "View property 文本（text）" }), null);
});

test("the class-instance client accepts optional usage and rejects malformed or contradictory statistics", async () => {
  for (const payload of [legacySnapshot, snapshot]) {
    globalThis.fetch = async () => response(payload);
    await loadClassInstances(classUri, 0, 1);
  }
  for (const invalid of [null, {}, [{ ...fields[0], property_uri: 5 }], [{ ...fields[0], kinds: [] }], [{ ...fields[0], kinds: ["inferred"] }], [{ ...fields[0], kinds: ["literal", "literal"] }], [{ ...fields[0], instance_count: 0 }], [{ ...fields[0], instance_count: 3 }], [{ ...fields[0], instance_count: 1.5 }], [fields[0], fields[0]]]) {
    globalThis.fetch = async () => response({ ...snapshot, observed_properties: invalid });
    await assert.rejects(loadClassInstances(classUri, 0, 1));
  }
});
