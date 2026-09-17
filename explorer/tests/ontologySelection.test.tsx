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
const { ReactFlowProvider, useStoreApi } = await import("@xyflow/react");

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
