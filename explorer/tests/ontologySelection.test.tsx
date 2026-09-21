import assert from "node:assert/strict";
import { registerHooks } from "node:module";
import test from "node:test";
import React from "react";
import { JSDOM } from "jsdom";

// Styles are applied in the browser; the real ReactFlow component still renders here.
registerHooks({ load(url, context, nextLoad) {
  return url.endsWith(".css") ? { format: "module", source: "", shortCircuit: true } : nextLoad(url, context);
} });
const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost", pretendToBeVisual: true });
Object.assign(globalThis, { React, window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement, Element: dom.window.Element, Node: dom.window.Node, getComputedStyle: dom.window.getComputedStyle });
Object.defineProperty(globalThis, "navigator", { configurable: true, value: dom.window.navigator });
class ResizeObserverStub { observe() {} unobserve() {} disconnect() {} }
Object.assign(globalThis, { ResizeObserver: ResizeObserverStub, requestAnimationFrame: dom.window.requestAnimationFrame.bind(dom.window), cancelAnimationFrame: dom.window.cancelAnimationFrame.bind(dom.window) });
const { act, cleanup, fireEvent, render, waitFor } = await import("@testing-library/react");
const { OntologyEditor } = await import("../src/workspaces/OntologyWorkspace/OntologyEditor.tsx");
const { OntologyWorkspace } = await import("../src/workspaces/OntologyWorkspace/index.tsx");
const { ReactFlowProvider, useStoreApi } = await import("@xyflow/react");
const { declaredRelationshipEdges, relationshipEdgeLabel } = await import("../src/workspaces/OntologyWorkspace/relationshipShapes.ts");

const ontology = "https://example.test/policy/";
const requestClass = `${ontology}Request`;
const approvalClass = `${ontology}Approval`;
const amountProperty = `${ontology}amount`;
const nodes = [
  { id: requestClass, type: "owl:Class", content: "采购申请" },
  { id: approvalClass, type: "owl:Class", content: "采购审批" },
  { id: amountProperty, type: "owl:DatatypeProperty", content: "申请金额" },
];
const edges = [{ id: "amount-domain", source: amountProperty, target: requestClass, type: "rdfs:domain" }];

test.beforeEach(() => {
  dom.window.history.replaceState(null, "", `/?ontologyTab=editor&ontologyEntity=${encodeURIComponent(requestClass)}`);
  globalThis.fetch = async (input) => {
    const url = new URL(String(input), "http://localhost");
    const value = url.pathname === "/api/ontology/registry" ? [{ uri: ontology, name: "采购制度" }]
      : url.pathname.startsWith("/api/ontology/entity/") ? { owning_ontology: ontology }
        : url.pathname === "/api/ontology/graph" ? { uri: ontology, nodes, edges }
          : {};
    return new Response(JSON.stringify(value));
  };
});
test.afterEach(cleanup);

function selectedIds(container: HTMLElement) {
  return [...container.querySelectorAll(".react-flow__node.selected")].map((node) => node.getAttribute("data-id"));
}

test("a class with saved relationship declarations opens a readable neighborhood and can restore the full ontology", async () => {
  const relation = `${ontology}hasEvidence`;
  const unrelated = `${ontology}Unrelated`;
  const graphNodes = [...nodes.filter((node) => node.id !== amountProperty),
    { id: relation, type: "owl:ObjectProperty", content: "有证据" },
    { id: unrelated, type: "owl:Class", content: "其他类型" }];
  const graphEdges = [{ id: `${ontology}shape`, source: requestClass, target: approvalClass, type: relation,
    properties: { schema_kind: "relationship_shape", shape_uri: `${ontology}shape`, property_uri: relation, ontology_uri: ontology, label: "模型声明的关系", comment: "候选关系定义", definition_source: "llm" } }];
  const original = globalThis.fetch;
  globalThis.fetch = async (input, init) => new URL(String(input), "http://localhost").pathname === "/api/ontology/graph"
    ? new Response(JSON.stringify({ uri: ontology, nodes: graphNodes, edges: graphEdges })) : original(input, init);
  const view = render(<OntologyEditor />);
  await view.findByRole("heading", { name: "Class Details" });
  await waitFor(() => assert.equal(view.container.querySelectorAll(".react-flow__node").length, 2));
  assert.equal(view.container.querySelector(`[data-id='${unrelated}']`), null);
  const toggle = view.getByRole<HTMLInputElement>("checkbox", { name: "Show entire ontology" });
  assert.equal(toggle.checked, false);
  fireEvent.click(toggle);
  await waitFor(() => assert.ok(view.container.querySelector(`[data-id='${unrelated}']`)));
  assert.deepEqual(selectedIds(view.container), [requestClass]);
});

test("named OWL business endpoints remain visible alongside LLM provenance declarations", async () => {
  const businessProperty = `${ontology}requestsAuthorization`;
  const evidenceProperty = `${ontology}hasEvidence`;
  const evidenceClass = `${ontology}Evidence`;
  const graphNodes = [...nodes,
    { id: businessProperty, type: "owl:ObjectProperty", content: "请求授权" },
    { id: evidenceProperty, type: "owl:ObjectProperty", content: "有证据", properties: { schema_role: "provenance" } },
    { id: evidenceClass, type: "owl:Class", content: "证据" }];
  const graphEdges = [
    { source: businessProperty, target: approvalClass, type: "rdfs:domain" },
    { source: businessProperty, target: requestClass, type: "rdfs:range" },
    { id: "saved-shape", source: requestClass, target: evidenceClass, type: evidenceProperty,
      properties: { schema_kind: "relationship_shape", shape_uri: `${ontology}shape`, property_uri: evidenceProperty, ontology_uri: ontology, label: "采购申请有证据", comment: "候选关系定义", definition_source: "llm", schema_role: "provenance" } },
  ];
  const projected = declaredRelationshipEdges(graphNodes, graphEdges);
  assert.equal(projected.length, 4);
  assert.deepEqual([projected[3].source, projected[3].target, projected[3].type], [approvalClass, requestClass, businessProperty]);
  assert.equal(relationshipEdgeLabel(graphEdges[2], graphNodes), "有证据（hasEvidence）");
  assert.equal(relationshipEdgeLabel(projected[3], graphNodes), "请求授权（requestsAuthorization）");
  assert.equal(declaredRelationshipEdges(graphNodes, projected).length, 4, "saved and OWL declarations must not duplicate the same displayed link");
  const original = globalThis.fetch;
  globalThis.fetch = async (input, init) => new URL(String(input), "http://localhost").pathname === "/api/ontology/graph"
    ? new Response(JSON.stringify({ uri: ontology, nodes: graphNodes, edges: graphEdges })) : original(input, init);
  const view = render(<OntologyEditor />);
  await view.findByRole("heading", { name: "Class Details" });
  await waitFor(() => assert.equal(view.container.querySelectorAll(".react-flow__node").length, 3));
  assert.ok(view.container.querySelector(`[data-id='${approvalClass}']`));
  assert.ok(view.container.querySelector(`[data-id='${evidenceClass}']`));
});

test("usage and conjunctive or anonymous OWL endpoints never become simple relationship declarations", () => {
  const property = { id: `${ontology}reviews`, type: "owl:ObjectProperty", content: "审核" };
  const graphNodes = [...nodes, property];
  const instance = { source: requestClass, target: approvalClass, type: property.id };
  assert.deepEqual(declaredRelationshipEdges(graphNodes, [instance]), [instance]);
  const declared = [{ source: property.id, target: requestClass, type: "rdfs:domain" }, { source: property.id, target: approvalClass, type: "rdfs:range" }];
  const conjunctive = [...declared, { source: property.id, target: approvalClass, type: "rdfs:domain" }];
  assert.deepEqual(declaredRelationshipEdges(graphNodes, conjunctive), conjunctive);
  const complex = [...nodes, { ...property, properties: { domain_expressions: [{ kind: "unionOf", members: [requestClass, approvalClass] }] } }];
  assert.deepEqual(declaredRelationshipEdges(complex, declared), declared);
});

test("opening a class deep link selects and visibly marks the same node as the detail panel", async () => {
  const view = render(<OntologyEditor />);
  await view.findByRole("heading", { name: "Class Details" });
  await waitFor(() => assert.deepEqual(selectedIds(view.container), [requestClass]));
  const selected = view.container.querySelector<HTMLElement>(".react-flow__node.selected [data-ontology-selected='true']");
  assert.ok(selected, "the selected custom node must have a visible selected treatment");
  assert.ok(selected.style.boxShadow || selected.style.outline || selected.style.borderColor);
});

test("property-list and canvas selections replace the previous selected node", async () => {
  const view = render(<OntologyEditor />);
  await view.findByRole("heading", { name: "Class Details" });
  fireEvent.click(view.getByRole("button", { name: /申请金额/ }));
  await waitFor(() => assert.deepEqual(selectedIds(view.container), [amountProperty]));
  assert.ok(view.getByRole("heading", { name: "Property Details" }));
  fireEvent.click(view.container.querySelector(`[data-id='${approvalClass}']`)!);
  await waitFor(() => assert.deepEqual(selectedIds(view.container), [approvalClass]));
  assert.ok(view.getByRole("heading", { name: "Class Details" }));
});

test("keyboard selection and Escape keep the canvas and detail selection synchronized", async () => {
  const view = render(<OntologyEditor />);
  await view.findByRole("heading", { name: "Class Details" });
  fireEvent.keyDown(view.container.querySelector(`[data-id='${approvalClass}']`)!, { key: "Enter" });
  await waitFor(() => assert.deepEqual(selectedIds(view.container), [approvalClass]));
  fireEvent.keyDown(view.container.querySelector(`[data-id='${approvalClass}']`)!, { key: "Escape" });
  await waitFor(() => assert.deepEqual(selectedIds(view.container), []));
  assert.equal(view.queryByRole("heading", { name: "Class Details" }), null);
});

test("clearing the canvas selection closes details and removes the prior node highlight", async () => {
  const view = render(<OntologyEditor />);
  await view.findByRole("heading", { name: "Class Details" });
  fireEvent.click(view.container.querySelector(".react-flow__pane")!);
  await waitFor(() => assert.deepEqual(selectedIds(view.container), []));
  assert.equal(view.queryByRole("heading", { name: "Class Details" }), null);
});

test("native drag selection preserves the camera, while explicitly reselecting the current class recenters it", async () => {
  let store: ReturnType<typeof useStoreApi> | undefined;
  function CaptureFlowStore() { store = useStoreApi(); return null; }
  const view = render(<ReactFlowProvider><CaptureFlowStore /><OntologyEditor /></ReactFlowProvider>);
  await view.findByRole("heading", { name: "Class Details" });
  const canvas = view.container.querySelector<HTMLElement>(".ontology-editor-flow")!.parentElement!;
  canvas.getBoundingClientRect = () => new dom.window.DOMRect(0, 0, 900, 600);
  const viewportCalls: unknown[] = [];
  const panZoom = store!.getState().panZoom!;
  panZoom.setViewport = async (viewport) => { viewportCalls.push(viewport); return viewport; };
  await act(async () => {
    store!.getState().triggerNodeChanges(nodes.map((node) => ({ id: node.id, type: "dimensions", dimensions: { width: 180, height: 60 } })));
  });
  await waitFor(() => assert.equal(viewportCalls.length, 1));
  await act(async () => {
    // ReactFlow emits selection changes when dragging starts, before position updates.
    store!.getState().triggerNodeChanges([
      { id: requestClass, type: "select", selected: false },
      { id: approvalClass, type: "select", selected: true },
      { id: approvalClass, type: "position", position: { x: 720, y: 500 }, dragging: true },
    ]);
  });
  await waitFor(() => assert.deepEqual(selectedIds(view.container), [approvalClass]));
  await act(async () => { await new Promise<void>((resolve) => dom.window.requestAnimationFrame(() => resolve())); });
  assert.equal(viewportCalls.length, 1, "native selection and dragging must preserve the user's viewport");
  fireEvent.click(view.container.querySelector(`[data-id='${approvalClass}']`)!);
  await waitFor(() => assert.equal(viewportCalls.length, 2, "an explicit click may recenter an already selected class"));
  await act(async () => {
    store!.getState().triggerNodeChanges([{ id: approvalClass, type: "position", position: { x: 780, y: 520 }, dragging: false }]);
  });
  await act(async () => { await new Promise<void>((resolve) => dom.window.requestAnimationFrame(() => resolve())); });
  assert.equal(viewportCalls.length, 2, "later position updates must not repeat the completed focus");
});

test("opening an observed property in another ontology selects and centers it after the previous focus completed", async () => {
  const foreignOntology = "https://other.test/schema/";
  const foreignProperty = `${foreignOntology}text`;
  const foreignNodes = [{ id: foreignProperty, type: "owl:DatatypeProperty", content: "文本", properties: { scheme_uri: foreignOntology } }];
  const context = { configured: true, business_ontologies: [ontology, foreignOntology], support_ontologies: [] };
  globalThis.fetch = async (input) => {
    const url = new URL(String(input), "http://localhost");
    const value = url.pathname === "/api/ontology/registry" ? [{ uri: ontology, name: "采购制度" }, { uri: foreignOntology, name: "共享属性" }]
      : url.pathname.startsWith("/api/ontology/entity/") ? { owning_ontology: ontology }
        : url.pathname === "/api/ontology/graph" ? url.searchParams.get("uri") === foreignOntology
          ? { uri: foreignOntology, nodes: foreignNodes, edges: [] } : { uri: ontology, nodes, edges }
          : url.pathname === "/api/ontology/class-instances" ? { class_uri: requestClass, skip: 0, limit: 1, total: 1, instances: [{ node_id: "request-1", label: "申请", basis: [] }], observed_properties: [{ property_uri: foreignProperty, label: "文本", loaded: true, ontology_uri: foreignOntology, kinds: ["literal"], instance_count: 1 }] }
            : {};
    return new Response(JSON.stringify(value));
  };
  let store: ReturnType<typeof useStoreApi> | undefined;
  function CaptureFlowStore() { store = useStoreApi(); return null; }
  const view = render(<ReactFlowProvider><CaptureFlowStore /><OntologyEditor evidenceContext={context} /></ReactFlowProvider>);
  const property = await view.findByRole("button", { name: "View property 文本（text）" });
  const canvas = view.container.querySelector<HTMLElement>(".ontology-editor-flow")!.parentElement!;
  canvas.getBoundingClientRect = () => new dom.window.DOMRect(0, 0, 900, 600);
  const viewportCalls: { x: number; y: number; zoom: number }[] = [];
  store!.getState().panZoom!.setViewport = async (viewport) => { viewportCalls.push(viewport); return viewport; };
  await act(async () => { store!.getState().triggerNodeChanges(nodes.map((node) => ({ id: node.id, type: "dimensions", dimensions: { width: 180, height: 60 } }))); });
  await waitFor(() => assert.equal(viewportCalls.length, 1));
  fireEvent.click(view.getByText("Tools", { selector: "summary" }));
  fireEvent.click(view.getByRole("checkbox", { name: "Enable advanced editing" }));
  fireEvent.click(view.getByText("Tools", { selector: "summary" }));
  assert.ok(view.getByRole("button", { name: "Save draft" }));
  fireEvent.click(property);
  await view.findByRole("heading", { name: "Property Details" });
  await waitFor(() => assert.deepEqual(selectedIds(view.container), [foreignProperty]));
  await act(async () => { store!.getState().triggerNodeChanges([{ id: foreignProperty, type: "dimensions", dimensions: { width: 180, height: 60 } }]); });
  await waitFor(() => assert.equal(viewportCalls.length, 2, "the new exact property needs a new focus request"));
  const viewport = viewportCalls[1];
  const target = store!.getState().nodeLookup.get(foreignProperty)!;
  assert.equal((target.internals.positionAbsolute.x + 90) * viewport.zoom + viewport.x, 450);
  assert.equal((target.internals.positionAbsolute.y + 30) * viewport.zoom + viewport.y, 300);
  assert.equal(view.getByRole<HTMLSelectElement>("combobox", { name: "Active ontology" }).value, foreignOntology);
  assert.equal(new URL(dom.window.location.href).searchParams.get("ontologyEntity"), foreignProperty);
  assert.equal(view.queryByRole("button", { name: "Save draft" }), null, "structural editing is reset for the newly opened ontology");
});

const supportOntology = "https://example.test/process/Ontology";
const supportClass = "https://example.test/process/ProcessRule";
const configuredContext = { configured: true, business_ontologies: [ontology], support_ontologies: [supportOntology] };

function configureHub() {
  dom.window.history.replaceState(null, "", `/?ontologyTab=editor&ontologyEntity=${encodeURIComponent(supportClass)}`);
  globalThis.fetch = async (input) => {
    const url = new URL(String(input), "http://localhost");
    const entries = [{ uri: ontology, name: "采购制度" }, { uri: supportOntology, name: "流程与证据支持词汇" }].map((entry) => ({
      ...entry, format: "turtle", status: "draft", class_count: 1, concept_count: 0, property_count: 0,
      loaded_at: "2026-09-17T00:00:00Z", enabled: true, tags: [],
    }));
    const value = url.pathname === "/api/ontology/evidence-context" ? configuredContext
      : url.pathname === "/api/ontology/registry" ? entries
        : url.pathname.startsWith("/api/ontology/entity/") ? { owning_ontology: supportOntology }
          : url.pathname === "/api/ontology/graph" ? {
            uri: url.searchParams.get("uri"),
            nodes: url.searchParams.get("uri") === supportOntology ? [{ id: supportClass, type: "owl:Class", content: "流程规则" }] : nodes,
            edges: [],
          }
            : {};
    return new Response(JSON.stringify(value));
  };
}

test("one ontology selector shows the deep-linked owner and permits switching all loaded ontologies", async () => {
  configureHub();
  const view = render(<OntologyEditor evidenceContext={configuredContext} />);
  const select = await view.findByRole<HTMLSelectElement>("combobox", { name: "Active ontology" });
  await waitFor(() => assert.equal(select.value, supportOntology));
  assert.equal(view.getAllByRole("combobox").length, 1);
  assert.deepEqual([...select.options].filter((option) => option.value).map((option) => option.value), [ontology, supportOntology]);
  assert.equal(view.queryByText("Technical and other ontologies"), null);
  assert.equal(view.queryByText("Select business ontology..."), null);
  await waitFor(() => assert.deepEqual(selectedIds(view.container), [supportClass]));
  fireEvent.change(select, { target: { value: ontology } });
  await waitFor(() => assert.equal(select.value, ontology));
  assert.equal(view.queryByRole("heading", { name: "Class Details" }), null);
  assert.equal(new URL(dom.window.location.href).searchParams.has("ontologyEntity"), false);
});

test("structural editing remains opt-in and its tool popup closes without hiding class details", async () => {
  configureHub();
  const view = render(<OntologyEditor evidenceContext={configuredContext} />);
  await view.findByRole("heading", { name: "Class Details" });
  const trigger = view.getByText("Tools", { selector: "summary" });
  const menu = trigger.closest("details")!;
  assert.equal(menu.open, false);
  assert.equal(view.queryByRole("button", { name: "Save draft" }), null);
  assert.equal(view.container.querySelector(".react-flow__node.draggable"), null);
  fireEvent.click(trigger);
  assert.equal(menu.open, true);
  fireEvent.click(view.getByRole("checkbox", { name: "Enable advanced editing" }));
  assert.ok(view.getByRole("button", { name: "Add Class" }));
  assert.ok(view.getByRole("button", { name: "Save draft" }));
  assert.ok(view.container.querySelector(".react-flow__node.draggable"));
  fireEvent.keyDown(document, { key: "Escape" });
  assert.equal(menu.open, false);
  assert.equal(document.activeElement, trigger);
  assert.ok(view.getByRole("heading", { name: "Class Details" }));
  fireEvent.click(trigger);
  fireEvent.pointerDown(view.getByRole("button", { name: "Auto Layout" }));
  assert.equal(menu.open, false);
  fireEvent.click(trigger);
  fireEvent.focusIn(view.getByRole("combobox", { name: "Active ontology" }));
  assert.equal(menu.open, false);
});

test("graph and management views share one compact navigation control", async () => {
  configureHub();
  const view = render(<OntologyWorkspace />);
  await view.findByRole("heading", { name: "Class Details" });
  const select = view.getByRole<HTMLSelectElement>("combobox", { name: "Ontology view" });
  assert.equal(select.value, "editor");
  assert.deepEqual([...select.options].map((option) => option.value), ["editor", "registry", "versions", "alignments", "health", "shacl"]);
  const toolbar = view.getByRole("toolbar", { name: "Ontology graph tools" });
  assert.ok(toolbar.contains(select));
  assert.ok(toolbar.contains(view.getByRole("combobox", { name: "Active ontology" })));
  assert.equal(view.queryByText("Advanced ontology tools"), null);
  fireEvent.change(select, { target: { value: "registry" } });
  await waitFor(() => assert.equal(new URL(dom.window.location.href).searchParams.get("ontologyTab"), "registry"));
  assert.equal(view.queryByRole("toolbar", { name: "Ontology graph tools" }), null);
  const registrySelect = view.getByRole<HTMLSelectElement>("combobox", { name: "Ontology view" });
  assert.equal(registrySelect.value, "registry");
  fireEvent.change(registrySelect, { target: { value: "editor" } });
  await view.findByRole("toolbar", { name: "Ontology graph tools" });
});
