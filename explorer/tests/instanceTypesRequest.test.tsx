import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { JSDOM } from "jsdom";
(globalThis as typeof globalThis & { React: typeof React }).React = React;
const dom = new JSDOM("<html><body></body></html>", { url: "http://localhost" });
Object.assign(globalThis, { window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement, Node: dom.window.Node });
Object.defineProperty(globalThis, "navigator", { configurable: true, value: dom.window.navigator });
const { act, cleanup, render, waitFor } = await import("@testing-library/react");
const { useInstanceTypes } = await import("../src/workspaces/GraphWorkspace/useInstanceTypes.ts");
function Harness({ nodeId, version }: { nodeId: string; version: number }) {
  const state = useInstanceTypes(nodeId, version);
  return <div>{state.loading ? "loading" : state.error ?? state.snapshot?.node_id ?? "empty"}</div>;
}
const payload = (node_id: string) => ({ node_id, status: "unmapped", types: [], related_concepts: [], related_status: "unconfigured", notice: "No declaration" });
test.afterEach(cleanup);
test("a node change clears prior content and ignores an older late response", async () => {
  const pending = new Map<string, (response: Response) => void>();
  globalThis.fetch = (input) => new Promise(resolve => pending.set(new URL(String(input), "http://localhost").searchParams.get("node_id")!, resolve));
  const view = render(<Harness nodeId="a" version={1} />);
  view.rerender(<Harness nodeId="b" version={1} />);
  await act(async () => pending.get("b")!(new Response(JSON.stringify(payload("b")))));
  assert.equal(view.container.textContent, "b");
  await act(async () => pending.get("a")!(new Response(JSON.stringify(payload("a")))));
  assert.equal(view.container.textContent, "b");
  view.rerender(<Harness nodeId="" version={1} />);
  assert.equal(view.container.textContent, "empty");
});
test("graph revisions invalidate class data and failures cannot show the last successful mapping", async () => {
  globalThis.fetch = async () => new Response(JSON.stringify(payload("a")));
  const view = render(<Harness nodeId="a" version={1} />);
  await waitFor(() => assert.equal(view.container.textContent, "a"));
  let reject!: (reason: Error) => void;
  globalThis.fetch = () => new Promise((_resolve, fail) => { reject = fail; });
  view.rerender(<Harness nodeId="a" version={2} />);
  assert.equal(view.container.textContent, "loading");
  await act(async () => reject(new Error("Mapping unavailable")));
  assert.match(view.container.textContent ?? "", /Mapping unavailable/);
});
