import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test from "node:test";
import { JSDOM } from "jsdom";
import React from "react";
import { RetainedWorkspace } from "../src/RetainedWorkspace";

(globalThis as typeof globalThis & { React: typeof React }).React = React;
const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost" });
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  HTMLElement: dom.window.HTMLElement,
  Node: dom.window.Node,
});
Object.defineProperty(globalThis, "navigator", { configurable: true, value: dom.window.navigator });
const { act, cleanup, fireEvent, render, waitFor, within } = await import("@testing-library/react");
const { GraphInspectorPanel } = await import("../src/workspaces/GraphWorkspace/GraphInspectorPanel.tsx");
const { RelationshipSourceEvidence } = await import("../src/workspaces/GraphWorkspace/SourceEvidencePanel.tsx");
const { graph } = await import("../src/store/graphStore.ts");

const text = "前言😀\n需审批。\n需审批。\n支持😀条款。\n<script>window.bad=1</script>";
const sha256 = createHash("sha256").update(text).digest("hex");
const source = {
  source_id: "policy/采购",
  source_sha256: sha256,
  actual_sha256: sha256,
  title: "采购办法",
  version: null,
  source_uri: null,
  status: "available",
  reason: null,
  text,
  character_count: Array.from(text).length,
};
const primary = {
  id: "e-main",
  clause_id: "C002",
  role: "primary",
  quote: "需审批。",
  start_char: 9,
  end_char: 13,
  source_id: source.source_id,
  source_sha256: sha256,
  status: "aligned",
  reason: null,
  fact_status: "candidate",
  review_status: "unreviewed",
};
const supporting = {
  ...primary,
  id: "e-support",
  clause_id: "C001",
  role: "supporting",
  quote: "支持😀条款。",
  start_char: 14,
  end_char: 20,
};
const bundle = {
  selection: { kind: "node", id: "rule-1", label: "采购审批规则" },
  evidence: [primary, supporting],
  sources: [source],
  status: "ok",
};
const defaults = {
  predictions: [],
  predictionType: "",
  onPredictionTypeChange: () => undefined,
  onRunPredictions: () => undefined,
  pathTargetId: "",
  onPathTargetChange: () => undefined,
  onTracePath: () => undefined,
  pathResult: null,
  onDownloadProvenance: () => undefined,
};

function response(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
}

function addNode(id: string, nodeType = "ProcessRule") {
  graph.addNode(id, { label: id, content: "Node Markdown body", nodeType, properties: {} });
}

test.beforeEach(() => {
  graph.clear();
  addNode("rule-1");
  addNode("rule-2");
  globalThis.fetch = async () => response(bundle);
});
test.afterEach(cleanup);

test("a retained inactive workspace hides its body portal and restores the chosen supporting evidence on return", async () => {
  const content = <GraphInspectorPanel {...defaults} nodeId="rule-1" />;
  const view = render(<RetainedWorkspace active>{content}</RetainedWorkspace>);
  fireEvent.click(await view.findByRole("button", { name: "Open source material" }));
  const dialog = view.getByRole("dialog");
  fireEvent.click(within(dialog).getByRole("button", { name: /Supporting.*C001/ }));
  assert.equal(dialog.querySelector("mark")?.textContent, "支持😀条款。");
  view.rerender(<RetainedWorkspace active={false}>{content}</RetainedWorkspace>);
  assert.ok(view.queryByRole("dialog") === null, "the body portal must not cover another workspace");
  view.rerender(<RetainedWorkspace active>{content}</RetainedWorkspace>);
  const restored = view.getByRole("dialog");
  assert.equal(restored.querySelector("mark")?.textContent, "支持😀条款。");
  assert.equal(document.activeElement, within(restored).getByRole("button", { name: "Close source material" }));
});

test("a rule opens full source text at the second repeated quote using Unicode character offsets", async () => {
  let requested = "";
  globalThis.fetch = async (input) => { requested = String(input); return response(bundle); };
  const view = render(<GraphInspectorPanel {...defaults} nodeId="rule-1" />);
  fireEvent.click(await view.findByRole("button", { name: "Open source material" }));
  const dialog = view.getByRole("dialog", { name: "Source material & evidence" });
  const mark = dialog.querySelector("mark");
  assert.equal(mark?.textContent, "需审批。");
  assert.equal(mark?.previousSibling?.textContent, "前言😀\n需审批。\n");
  assert.equal(within(dialog).getByLabelText("Full source text").textContent, text);
  assert.equal(new URL(requested, "http://localhost").searchParams.get("node_id"), "rule-1");
  assert.match(dialog.textContent ?? "", /Version: Unknown/);
  assert.match(dialog.textContent ?? "", /candidate/);
  assert.match(dialog.textContent ?? "", /unreviewed/);
  assert.match(dialog.textContent ?? "", /Citation aligned/);
  assert.match(dialog.textContent ?? "", /does not mean business approval/);
  assert.ok(view.getByRole("tab", { name: "Markdown source" }));
});

test("primary and supporting evidence switch the exact highlighted range including emoji", async () => {
  const view = render(<GraphInspectorPanel {...defaults} nodeId="rule-1" />);
  fireEvent.click(await view.findByRole("button", { name: "Open source material" }));
  const dialog = view.getByRole("dialog");
  fireEvent.click(within(dialog).getByRole("button", { name: /Supporting.*C001/ }));
  assert.equal(dialog.querySelectorAll("mark").length, 1);
  assert.equal(dialog.querySelector("mark")?.textContent, "支持😀条款。");
  assert.equal(dialog.querySelector("mark")?.previousSibling?.textContent, "前言😀\n需审批。\n需审批。\n");
  fireEvent.click(within(dialog).getByRole("button", { name: /Primary.*C002/ }));
  assert.equal(dialog.querySelector("mark")?.textContent, "需审批。");
});

test("switching materials clears evidence and never highlights another source with the same quote", async () => {
  const otherText = "另一份😀材料\n需审批。";
  const otherHash = createHash("sha256").update(otherText).digest("hex");
  const otherSource = { ...source, source_id: "other", title: "第二份材料", version: "v2", source_sha256: otherHash, actual_sha256: otherHash, text: otherText };
  const otherEvidence = { ...primary, id: "other-evidence", clause_id: "O001", source_id: "other", source_sha256: otherHash, start_char: 7, end_char: 11 };
  globalThis.fetch = async () => response({ ...bundle, sources: [source, otherSource], evidence: [primary, otherEvidence] });
  const view = render(<GraphInspectorPanel {...defaults} nodeId="rule-1" />);
  fireEvent.click(await view.findByRole("button", { name: "Open source material" }));
  const dialog = view.getByRole("dialog");
  fireEvent.change(within(dialog).getByRole("combobox", { name: "Source material" }), { target: { value: "1" } });
  assert.equal(within(dialog).getByLabelText("Full source text").textContent, otherText);
  assert.equal(dialog.querySelector("mark"), null);
  fireEvent.click(within(dialog).getByRole("button", { name: /Primary.*C002/ }));
  assert.equal(within(dialog).getByLabelText("Full source text").textContent, text);
  assert.equal(dialog.querySelector("mark")?.textContent, "需审批。");
  fireEvent.click(within(dialog).getByRole("button", { name: /Primary.*O001/ }));
  assert.equal(within(dialog).getByLabelText("Full source text").textContent, otherText);
  assert.equal(dialog.querySelector("mark")?.textContent, "需审批。");
});

test("source HTML is literal text and creates no executable elements", async () => {
  const view = render(<GraphInspectorPanel {...defaults} nodeId="rule-1" />);
  fireEvent.click(await view.findByRole("button", { name: "Open source material" }));
  const dialog = view.getByRole("dialog");
  assert.equal(dialog.querySelector("script"), null);
  assert.equal(dialog.querySelector("img"), null);
  assert.match(within(dialog).getByLabelText("Full source text").textContent ?? "", /<script>window.bad=1<\/script>/);
});

test("invalid evidence states explain why a quote cannot be located without leaving a highlight", async () => {
  const failures = [
    { status: "source_missing", reason: "Source material is not registered." },
    { status: "hash_mismatch", reason: "SHA-256 does not match the evidence." },
    { status: "invalid_offsets", reason: "Offsets are outside the source text." },
    { status: "quote_mismatch", reason: "The quoted text differs from the selected range." },
    { status: "source_mismatch", reason: "Evidence names a different source." },
  ];
  globalThis.fetch = async () => response({ ...bundle, evidence: [primary, ...failures.map((failure, index) => ({ ...supporting, ...failure, id: `error-${index}`, clause_id: `E${index}` }))] });
  const view = render(<GraphInspectorPanel {...defaults} nodeId="rule-1" />);
  fireEvent.click(await view.findByRole("button", { name: "Open source material" }));
  const dialog = view.getByRole("dialog");
  assert.ok(dialog.querySelector("mark"));
  for (const [index, failure] of failures.entries()) {
    fireEvent.click(within(dialog).getByRole("button", { name: new RegExp(`Supporting.*E${index}`) }));
    assert.equal(dialog.querySelector("mark"), null);
    assert.match(within(dialog).getByRole("status").textContent ?? "", new RegExp(failure.reason.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
    assert.doesNotMatch(within(dialog).getByRole("status").textContent ?? "", /Citation aligned/);
  }
});

test("missing source shows its identity and reason without a full text or located state", async () => {
  globalThis.fetch = async () => response({ ...bundle, sources: [{ ...source, text: null, actual_sha256: null, status: "source_missing", reason: "Source material is not registered." }], evidence: [{ ...primary, status: "source_missing", reason: "Source material is not registered." }] });
  const view = render(<GraphInspectorPanel {...defaults} nodeId="rule-1" />);
  fireEvent.click(await view.findByRole("button", { name: "Open source material" }));
  const dialog = view.getByRole("dialog");
  assert.match(dialog.textContent ?? "", /policy\/采购/);
  assert.match(dialog.textContent ?? "", /not registered/);
  assert.equal(within(dialog).queryByLabelText("Full source text"), null);
  assert.equal(dialog.querySelector("mark"), null);
});

test("Evidence and SourceDocument use the same material viewer, with no invented evidence for the document", async () => {
  addNode("evidence-node", "Evidence");
  addNode("document-node", "SourceDocument");
  globalThis.fetch = async (input) => response(String(input).includes("document-node") ? { ...bundle, evidence: [] } : { ...bundle, evidence: [primary] });
  const view = render(<GraphInspectorPanel {...defaults} nodeId="evidence-node" />);
  fireEvent.click(await view.findByRole("button", { name: "Open source material" }));
  assert.equal(view.getByLabelText("Full source text").textContent, text);
  assert.ok(view.getByRole("dialog").querySelector("mark"));
  view.rerender(<GraphInspectorPanel {...defaults} nodeId="document-node" />);
  assert.equal(view.queryByRole("dialog"), null);
  fireEvent.click(await view.findByRole("button", { name: "Open source material" }));
  assert.equal(view.getByLabelText("Full source text").textContent, text);
  assert.equal(view.getByRole("dialog").querySelector("mark"), null);
});

test("node changes close the previous material and ignore late responses from an old selection", async () => {
  let resolveOld: ((value: Response) => void) | undefined;
  const oldResponse = new Promise<Response>((resolve) => { resolveOld = resolve; });
  globalThis.fetch = async (input) => String(input).includes("rule-1") ? oldResponse : response({ selection: { kind: "node", id: "rule-2", label: "Legacy node" }, evidence: [], sources: [], status: "no_evidence" });
  const view = render(<GraphInspectorPanel {...defaults} nodeId="rule-1" />);
  view.rerender(<GraphInspectorPanel {...defaults} nodeId="rule-2" />);
  await view.findByText(/No explicit evidence or source material/);
  await act(async () => { resolveOld?.(response(bundle)); await oldResponse; });
  assert.equal(view.queryByRole("button", { name: "Open source material" }), null);
  assert.equal(view.queryByRole("dialog"), null);
  assert.equal(view.queryByText("采购办法"), null);
});

test("legacy graphs retain Markdown content and show an explicit empty evidence state", async () => {
  globalThis.fetch = async () => response({ selection: { kind: "node", id: "rule-1", label: "Old node" }, evidence: [], sources: [], status: "no_evidence" });
  const view = render(<GraphInspectorPanel {...defaults} nodeId="rule-1" />);
  await view.findByText(/No explicit evidence or source material/);
  assert.ok(view.getByText("Node Markdown body"));
  assert.equal(view.queryByRole("button", { name: "Open source material" }), null);
});

test("source request failures show a readable error instead of stale content", async () => {
  globalThis.fetch = async () => response({ detail: "Service unavailable" }, 503);
  const view = render(<GraphInspectorPanel {...defaults} nodeId="rule-1" />);
  await waitFor(() => assert.match(view.getByRole("alert").textContent ?? "", /could not be loaded/));
  assert.equal(view.queryByRole("button", { name: "Open source material" }), null);
});

test("a quote containing emoji and multiple line breaks preserves its exact range", async () => {
  const multilineText = "甲😀\n乙\n尾";
  globalThis.fetch = async () => response({
    ...bundle,
    sources: [{ ...source, text: multilineText }],
    evidence: [{ ...primary, start_char: 1, end_char: 5, quote: "😀\n乙\n" }],
  });
  const view = render(<GraphInspectorPanel {...defaults} nodeId="rule-1" />);
  fireEvent.click(await view.findByRole("button", { name: "Open source material" }));
  const mark = view.getByRole("dialog").querySelector("mark");
  assert.equal(mark?.textContent, "😀\n乙\n");
  assert.equal(mark?.previousSibling?.textContent, "甲");
  assert.equal(mark?.nextSibling?.textContent, "尾");
});

test("an inconsistent aligned response cannot bypass source identity, hash, range or quote checks", async () => {
  const invalid = [
    { ...primary, id: "bad-range", clause_id: "E0", start_char: -1 },
    { ...primary, id: "bad-end", clause_id: "E1", end_char: 999 },
    { ...primary, id: "bad-quote", clause_id: "E2", quote: "Different quote" },
    { ...primary, id: "bad-source", clause_id: "E3", source_id: "another-source" },
    { ...primary, id: "bad-hash", clause_id: "E4", source_sha256: "0".repeat(64) },
  ];
  globalThis.fetch = async () => response({ ...bundle, evidence: [primary, ...invalid] });
  const view = render(<GraphInspectorPanel {...defaults} nodeId="rule-1" />);
  fireEvent.click(await view.findByRole("button", { name: "Open source material" }));
  const dialog = view.getByRole("dialog");
  for (let index = 0; index < invalid.length; index += 1) {
    fireEvent.click(within(dialog).getByRole("button", { name: new RegExp(`Primary.*E${index}`) }));
    assert.equal(dialog.querySelector("mark"), null);
    assert.match(within(dialog).getByRole("status").textContent ?? "", /Not located/);
  }
});

test("relationship bundles require an explicit edge and encode only that edge identity", async () => {
  const requests: string[] = [];
  const edge = "https://example.org/edge?a=1&b=采购";
  globalThis.fetch = async (input) => { requests.push(String(input)); return response({ ...bundle, selection: { kind: "edge", id: edge, label: "hasEvidence" } }); };
  const view = render(<RelationshipSourceEvidence edgeIds={["unrelated", edge]} />);
  assert.equal(requests.length, 0);
  assert.equal(view.queryByRole("button", { name: "Open source material" }), null);
  fireEvent.change(view.getByRole("combobox", { name: "Relationship for evidence" }), { target: { value: edge } });
  fireEvent.click(await view.findByRole("button", { name: "Open source material" }));
  assert.equal(requests.length, 1);
  const query = new URL(requests[0], "http://localhost").searchParams;
  assert.equal(query.get("edge_id"), edge);
  assert.equal(query.has("node_id"), false);
  assert.equal(view.getByRole("dialog").querySelector("mark")?.textContent, "需审批。");
  view.rerender(<RelationshipSourceEvidence edgeIds={["other-a", "other-b"]} />);
  assert.equal(view.queryByRole("dialog"), null);
  assert.equal((view.getByRole("combobox", { name: "Relationship for evidence" }) as HTMLSelectElement).value, "");
  assert.equal(requests.length, 1);
});

test("the source dialog closes with Escape and restores focus to its entry", async () => {
  const view = render(<GraphInspectorPanel {...defaults} nodeId="rule-1" />);
  const entry = await view.findByRole("button", { name: "Open source material" });
  entry.focus();
  fireEvent.click(entry);
  assert.equal(document.activeElement, view.getByRole("button", { name: "Close source material" }));
  fireEvent.keyDown(view.getByRole("dialog"), { key: "Escape" });
  assert.equal(view.queryByRole("dialog"), null);
  assert.equal(document.activeElement, entry);
});
