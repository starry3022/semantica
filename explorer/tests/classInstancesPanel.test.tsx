import assert from "node:assert/strict";
import test from "node:test";
import { JSDOM } from "jsdom";
import React from "react";
import { loadClassInstances } from "../src/workspaces/GraphWorkspace/instanceTypes.ts";

(globalThis as typeof globalThis & { React: typeof React }).React = React;
const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost" });
Object.assign(globalThis, { window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement, Node: dom.window.Node });
Object.defineProperty(globalThis, "navigator", { configurable: true, value: dom.window.navigator });
const { act, cleanup, fireEvent, render } = await import("@testing-library/react");
const { ClassInstancesPanel } = await import("../src/workspaces/OntologyWorkspace/ClassInstancesPanel.tsx");
const classUri = "https://example.test/technical/ProcessRule";
const first = { class_uri: classUri, instances: [{ node_id: "rule-1", label: "采购审批规则", basis: [{ kind: "graph_namespace", value: "https://example.test/technical/" }] }], total: 1, skip: 0, limit: 20 };
const response = (payload: unknown, status = 200) => new Response(JSON.stringify(payload), { status });
test.afterEach(cleanup);

test("class instances load on demand and navigate exact node IDs without claiming evidence links are types", async () => {
  const requests: string[] = [];
  const opened: string[] = [];
  globalThis.fetch = async (input) => {
    if (String(input).startsWith("/api/ontology/concept-references?")) return response({ class_uri: classUri, references: [], issues: [], status: "unconfigured", notice: "No concept mapping registered." });
    requests.push(String(input));
    return response(first);
  };
  const view = render(<ClassInstancesPanel classUri={classUri} onJumpToGraphNode={(id) => opened.push(id)} />);
  assert.equal(requests.length, 0);
  fireEvent.click(view.getByRole("button", { name: "Declared instances" }));
  fireEvent.click(await view.findByRole("button", { name: "Open instance 采购审批规则" }));
  assert.deepEqual(opened, ["rule-1"]);
  assert.match(view.container.textContent ?? "", /1 declared instance/);
  assert.match(view.container.textContent ?? "", /evidence associations are not instance declarations/i);
  assert.equal(new URL(requests[0], "http://localhost").searchParams.get("class_uri"), classUri);
});

test("class instance pages preserve totals and request the next bounded page", async () => {
  globalThis.fetch = async (input) => {
    const skip = Number(new URL(String(input), "http://localhost").searchParams.get("skip"));
    return response({ ...first, total: 21, skip, instances: skip ? [{ ...first.instances[0], node_id: "rule-21", label: "Last rule" }] : Array.from({ length: 20 }, (_, i) => ({ ...first.instances[0], node_id: `rule-${i}`, label: `Rule ${i}` })) });
  };
  const view = render(<ClassInstancesPanel classUri={classUri} onJumpToGraphNode={() => {}} />);
  fireEvent.click(view.getByRole("button", { name: "Declared instances" }));
  await view.findByRole("button", { name: "Open instance Rule 0" });
  assert.equal((view.getByRole("button", { name: "Previous instances" }) as HTMLButtonElement).disabled, true);
  fireEvent.click(view.getByRole("button", { name: "Next instances" }));
  assert.equal(view.queryByRole("button", { name: "Open instance Rule 0" }), null);
  await view.findByRole("button", { name: "Open instance Last rule" });
  assert.equal((view.getByRole("button", { name: "Next instances" }) as HTMLButtonElement).disabled, true);
  assert.match(view.container.textContent ?? "", /21.*21/);
});

test("switching classes cancels old requests, clears results and resets disclosure and page", async () => {
  let finish: ((r: Response) => void) | undefined;
  let signal: AbortSignal | null | undefined;
  const pending = new Promise<Response>((resolve) => { finish = resolve; });
  const otherUri = "urn:example:Other";
  globalThis.fetch = async (input, init) => {
    if (new URL(String(input), "http://localhost").searchParams.get("class_uri") === classUri) { signal = init?.signal; return pending; }
    return response({ ...first, class_uri: otherUri, instances: [], total: 0 });
  };
  const view = render(<ClassInstancesPanel classUri={classUri} onJumpToGraphNode={() => {}} />);
  fireEvent.click(view.getByRole("button", { name: "Declared instances" }));
  view.rerender(<ClassInstancesPanel classUri={otherUri} onJumpToGraphNode={() => {}} />);
  assert.equal(signal?.aborted, true);
  assert.equal(view.getByRole("button", { name: "Declared instances" }).getAttribute("aria-expanded"), "false");
  fireEvent.click(view.getByRole("button", { name: "Declared instances" }));
  await view.findByText(/No declared instances/);
  await act(async () => { finish?.(response(first)); await pending; });
  assert.equal(view.queryByText("采购审批规则"), null);
});

test("missing API and invalid class responses show errors instead of an empty or stale list", async () => {
  for (const [payload, status] of [[{ detail: "Not found" }, 404], [{ ...first, class_uri: "other" }, 200]] as const) {
    globalThis.fetch = async () => response(payload, status);
    const view = render(<ClassInstancesPanel classUri={classUri} onJumpToGraphNode={() => {}} />);
    fireEvent.click(view.getByRole("button", { name: "Declared instances" }));
    await view.findByRole("alert");
    assert.equal(view.queryByText(/No declared instances/), null);
    assert.equal(view.queryByText("采购审批规则"), null);
    cleanup();
  }
});

test("instance labels remain literal and navigation is disabled without a graph callback", async () => {
  const html = '<img src=x onerror="window.bad=1">';
  globalThis.fetch = async () => response({ ...first, instances: [{ ...first.instances[0], label: html }] });
  const view = render(<ClassInstancesPanel classUri={classUri} />);
  fireEvent.click(view.getByRole("button", { name: "Declared instances" }));
  const button = await view.findByRole("button", { name: `Open instance ${html}` });
  assert.equal((button as HTMLButtonElement).disabled, true);
  assert.equal(view.container.querySelector("img,script,a[href]"), null);
});

test("class list client validates response identity, page and item shape", async () => {
  for (const payload of [{ ...first, class_uri: "wrong" }, { ...first, skip: 20 }, { ...first, total: -1 }, { ...first, instances: [{ ...first.instances[0], node_id: {} }] }, { ...first, instances: [{ ...first.instances[0], basis: "name guess" }] }]) {
    globalThis.fetch = async () => response(payload);
    await assert.rejects(loadClassInstances(classUri, 0, 20));
  }
});

const businessUri = "https://example.test/business/Contract";
const conceptReference = {
  node_id: "requirement-1", label: "合法有效的合同", class_uri: businessUri, class_label: "合同",
  ontology_uri: "https://example.test/business/", rationale: "The candidate requirement refers to a contract document.",
  status: "candidate", review_status: "unreviewed", evidence_ids: ["e-contract"],
};
const conceptSnapshot = { class_uri: businessUri, references: [conceptReference], issues: [], status: "ready", notice: "Candidate references are not type declarations." };

test("business concept references show a collapsed count and navigate as references, separately from declared instances", async () => {
  const opened: string[] = [];
  const requests: string[] = [];
  globalThis.fetch = async (input) => {
    requests.push(String(input));
    return response(String(input).startsWith("/api/ontology/concept-references?") ? conceptSnapshot : { ...first, class_uri: businessUri, instances: [], total: 0 });
  };
  const view = render(<ClassInstancesPanel classUri={businessUri} onJumpToGraphNode={(id) => opened.push(id)} />);
  const disclosure = await view.findByRole("button", { name: "Concept references (1)" });
  assert.equal(disclosure.getAttribute("aria-expanded"), "false");
  assert.equal(view.queryByText("合法有效的合同"), null);
  assert.equal(requests.length, 1, "reference count does not load declared-instance pages");
  fireEvent.click(disclosure);
  fireEvent.click(view.getByRole("button", { name: "Open referenced node 合法有效的合同" }));
  assert.deepEqual(opened, ["requirement-1"]);
  assert.match(view.container.textContent ?? "", /candidate\s*\/\s*unreviewed/i);
  assert.match(view.container.textContent ?? "", /not.*instance declaration/i);
  assert.equal(view.queryByRole("button", { name: /Open instance/ }), null);
  fireEvent.click(view.getByRole("button", { name: "Declared instances" }));
  await view.findByText("No declared instances in the current graph.");
  assert.ok(view.getByRole("button", { name: "Open referenced node 合法有效的合同" }));
});

test("class changes cancel pending references and clear their count, disclosure and stale content", async () => {
  let complete!: (response: Response) => void;
  let signal: AbortSignal | null | undefined;
  const pending = new Promise<Response>((resolve) => { complete = resolve; });
  const otherUri = "https://example.test/business/Invoice";
  globalThis.fetch = async (input, init) => {
    if (new URL(String(input), "http://localhost").searchParams.get("class_uri") === businessUri) { signal = init?.signal; return pending; }
    return response({ ...conceptSnapshot, class_uri: otherUri, references: [] });
  };
  const view = render(<ClassInstancesPanel classUri={businessUri} onJumpToGraphNode={() => {}} />);
  fireEvent.click(view.getByRole("button", { name: /Concept references/ }));
  view.rerender(<ClassInstancesPanel classUri={otherUri} onJumpToGraphNode={() => {}} />);
  assert.equal(signal?.aborted, true);
  const disclosure = await view.findByRole("button", { name: "Concept references (0)" });
  assert.equal(disclosure.getAttribute("aria-expanded"), "false");
  await act(async () => { complete(response(conceptSnapshot)); await pending; });
  assert.equal(view.queryByText("合法有效的合同"), null);
  assert.equal(view.queryByRole("button", { name: "Concept references (1)" }), null);
  fireEvent.click(disclosure);
  assert.ok(view.getByText("No explicit concept references in the current graph."));
});

test("missing or invalid concept responses never claim a zero count or expose stale mappings", async () => {
  for (const [payload, status] of [
    [{ detail: "Missing endpoint" }, 404],
    [{ ...conceptSnapshot, class_uri: "wrong" }, 200],
    [{ ...conceptSnapshot, references: [{ ...conceptReference, class_uri: "wrong" }] }, 200],
    [{ ...conceptSnapshot, references: [{ ...conceptReference, review_status: "reviewed" }] }, 200],
    [{ ...conceptSnapshot, references: [{ ...conceptReference, evidence_ids: [7] }] }, 200],
    [{ ...conceptSnapshot, issues: [{ node_id: "requirement-1", class_uri: "wrong", reason: "Missing class." }] }, 200],
    [{ ...conceptSnapshot, status: "unavailable", references: [conceptReference] }, 200],
  ] as const) {
    globalThis.fetch = async () => response(payload, status);
    const view = render(<ClassInstancesPanel classUri={businessUri} onJumpToGraphNode={() => {}} />);
    const disclosure = await view.findByRole("button", { name: /Concept references.*unavailable/ });
    assert.equal(view.queryByRole("button", { name: "Concept references (0)" }), null);
    fireEvent.click(disclosure);
    await view.findByRole("alert");
    assert.equal(view.queryByText("合法有效的合同"), null);
    cleanup();
  }
});

test("unconfigured and rejected concept mappings show reasons without pretending to be empty validated results", async () => {
  globalThis.fetch = async () => response({ ...conceptSnapshot, references: [], issues: [], status: "unconfigured", notice: "No concept mapping registered." });
  const view = render(<ClassInstancesPanel classUri={businessUri} />);
  fireEvent.click(await view.findByRole("button", { name: /Concept references.*not configured/ }));
  assert.ok(view.getByText("No concept mapping registered."));
  assert.equal(view.queryByText("No explicit concept references in the current graph."), null);
  view.unmount();
  globalThis.fetch = async () => response({ ...conceptSnapshot, references: [], issues: [{ node_id: "requirement-1", class_uri: businessUri, reason: "RDF fingerprint mismatch." }], status: "unavailable", notice: "Mappings require a matching RDF graph." });
  const invalid = render(<ClassInstancesPanel classUri={businessUri} />);
  fireEvent.click(await invalid.findByRole("button", { name: /Concept references.*unavailable/ }));
  assert.ok(invalid.getByText("RDF fingerprint mismatch."));
  assert.equal(invalid.queryByText("No explicit concept references in the current graph."), null);
});

test("reference labels and rationale are literal text and navigation needs the graph callback", async () => {
  const html = '<img src=x onerror="window.bad=1">';
  globalThis.fetch = async () => response({ ...conceptSnapshot, references: [{ ...conceptReference, label: html, rationale: html }] });
  const view = render(<ClassInstancesPanel classUri={businessUri} />);
  fireEvent.click(await view.findByRole("button", { name: "Concept references (1)" }));
  const button = view.getByRole("button", { name: `Open referenced node ${html}` });
  assert.equal((button as HTMLButtonElement).disabled, true);
  assert.equal(view.container.querySelector("img,script,a[href]"), null);
});
