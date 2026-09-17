import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<html><body></body></html>");
Object.assign(globalThis, { React, window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement, Node: dom.window.Node });
Object.defineProperty(globalThis, "navigator", { configurable: true, value: dom.window.navigator });
const { act, cleanup, render } = await import("@testing-library/react");
const { useOntologySelectionFocus } = await import("../src/workspaces/OntologyWorkspace/useOntologySelectionFocus.ts");
import type { OntologyFocusRequest, OntologyFocusFlow } from "../src/workspaces/OntologyWorkspace/useOntologySelectionFocus.ts";

let nextFrame = 0;
const frames = new Map<number, FrameRequestCallback>();
const observers = new Set<() => void>();
dom.window.requestAnimationFrame = (callback) => { const id = ++nextFrame; frames.set(id, callback); return id; };
dom.window.cancelAnimationFrame = (id) => { frames.delete(id); };
class ResizeObserverStub {
  constructor(private callback: () => void) {}
  observe() { observers.add(this.callback); }
  disconnect() { observers.delete(this.callback); }
}
Object.assign(globalThis, { ResizeObserver: ResizeObserverStub });
async function frame() {
  await act(async () => {
    const pending = [...frames.values()]; frames.clear(); pending.forEach((callback) => callback(0));
  });
}
function fixture() {
  let size = { width: 960, height: 600 };
  const container = document.createElement("div");
  container.getBoundingClientRect = () => ({ ...size, x: 0, y: 0, top: 0, left: 0, right: size.width, bottom: size.height, toJSON() {} });
  const viewportCalls: { x: number; y: number; zoom: number }[] = [];
  const fits: unknown[] = [];
  const measured = new Map<string, ReturnType<OntologyFocusFlow["getInternalNode"]>>();
  const flow: OntologyFocusFlow = {
    viewportInitialized: true,
    getInternalNode: (id) => measured.get(id),
    setViewport: async (viewport) => { viewportCalls.push(viewport); return true; },
    fitView: async (options) => { fits.push(options); return true; },
  };
  const ref = { current: container };
  const resize = (width: number, height: number) => { size = { width, height }; observers.forEach((callback) => callback()); };
  const measure = (id: string, x = 600, y = 400) => measured.set(id, { measured: { width: 200, height: 80 }, internals: { positionAbsolute: { x, y } } });
  function Harness({ request, nodeIds = ["a"] }: { request: OntologyFocusRequest | null; nodeIds?: string[] }) {
    useOntologySelectionFocus(flow, nodeIds.map((id) => ({ id })), request, ref);
    return null;
  }
  return { Harness, flow, measure, resize, viewportCalls, fits };
}
test.afterEach(() => { cleanup(); frames.clear(); observers.clear(); });

test("a requested class waits for measured dimensions and centers within the canvas remaining beside the detail panel", async () => {
  const f = fixture(); const request = { nodeId: "a" };
  const view = render(<f.Harness request={request} />);
  await frame();
  assert.deepEqual(f.viewportCalls, [], "an unmeasured class must not be focused with guessed dimensions");
  f.measure("a");
  view.rerender(<f.Harness request={request} />);
  f.resize(640, 480);
  await frame();
  assert.equal(f.viewportCalls.length, 1);
  const viewport = f.viewportCalls[0];
  assert.ok(viewport.zoom >= 1 && viewport.zoom <= 1.25, "class text stays readable");
  assert.ok(Math.abs(viewport.x + 700 * viewport.zoom - 320) < 0.001);
  assert.ok(Math.abs(viewport.y + 440 * viewport.zoom - 240) < 0.001);
  assert.equal(f.fits.length, 0, "target focus must not subsequently fit the entire ontology");
});

test("a hidden canvas waits for a real resize and uninitialized viewports cannot consume the focus request", async () => {
  const f = fixture(); const request = { nodeId: "a" };
  f.measure("a"); f.resize(0, 0); f.flow.viewportInitialized = false;
  const view = render(<f.Harness request={request} />);
  await frame();
  assert.equal(f.viewportCalls.length, 0);
  f.flow.viewportInitialized = true;
  view.rerender(<f.Harness request={request} />);
  await frame();
  assert.equal(f.viewportCalls.length, 0);
  f.resize(640, 480);
  await frame();
  assert.equal(f.viewportCalls.length, 1);
});

test("a newer target replaces a queued focus and ordinary measurement or save refreshes cannot move the camera again", async () => {
  const f = fixture(); f.measure("a"); f.measure("b", 100, 200);
  const request = { nodeId: "b" };
  const view = render(<f.Harness request={{ nodeId: "a" }} nodeIds={["a", "b"]} />);
  view.rerender(<f.Harness request={request} nodeIds={["a", "b"]} />);
  await frame();
  assert.equal(f.viewportCalls.length, 1);
  assert.ok(Math.abs(f.viewportCalls[0].x + 200 * f.viewportCalls[0].zoom - 480) < 0.001);
  f.measure("b", 50, 80);
  view.rerender(<f.Harness request={request} nodeIds={["a", "b"]} />);
  f.resize(700, 480);
  await frame();
  assert.equal(f.viewportCalls.length, 1);
  view.rerender(<f.Harness request={{ nodeId: "a" }} nodeIds={["a", "b"]} />);
  await frame();
  assert.equal(f.viewportCalls.length, 2, "only an intentional target change requests another focus");
});

test("clearing the selection or unmounting cancels queued camera movement", async () => {
  const f = fixture(); f.measure("a");
  const view = render(<f.Harness request={{ nodeId: "a" }} />);
  view.rerender(<f.Harness request={null} />);
  await frame();
  assert.equal(f.viewportCalls.length, 0);
  view.rerender(<f.Harness request={{ nodeId: "a" }} />);
  view.unmount();
  await frame();
  assert.equal(f.viewportCalls.length, 0);
});

test("an overview request fits once after its nodes are measured, with no repeated fit on refreshed objects", async () => {
  const f = fixture(); const request = { nodeId: null };
  const view = render(<f.Harness request={request} />);
  await frame();
  assert.equal(f.fits.length, 0);
  f.measure("a");
  view.rerender(<f.Harness request={request} />);
  await frame();
  assert.equal(f.fits.length, 1);
  assert.equal(f.viewportCalls.length, 0);
  view.rerender(<f.Harness request={request} />);
  await frame();
  assert.equal(f.fits.length, 1);
});
