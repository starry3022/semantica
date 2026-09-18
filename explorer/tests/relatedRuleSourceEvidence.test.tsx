import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test from "node:test";
import { JSDOM } from "jsdom";
import React from "react";
import { RetainedWorkspace } from "../src/RetainedWorkspace";
import type { SourceEvidence, SourceMaterial, SourceView } from "../src/workspaces/GraphWorkspace/sourceEvidence";

(globalThis as typeof globalThis & { React: typeof React }).React = React;
const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost" });
Object.assign(globalThis, { window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement, Node: dom.window.Node });
Object.defineProperty(globalThis, "navigator", { configurable: true, value: dom.window.navigator });
const { act, cleanup, fireEvent, render, within } = await import("@testing-library/react");
const { SourceEvidencePanel, RelationshipSourceEvidence } = await import("../src/workspaces/GraphWorkspace/SourceEvidencePanel.tsx");

function material(id: string, text: string): SourceMaterial {
  const hash = createHash("sha256").update(text).digest("hex");
  return { source_id: id, title: id, source_sha256: hash, actual_sha256: hash, text, character_count: Array.from(text).length, version: "v1", source_uri: null, status: "available", reason: null };
}

const sourceA = material("复核制度", "甲😀\n需复核。\n需复核。\n尾");
const supportSource = material("支持条款", "支持😀条款。");
const sourceB = material("审批制度", "第二规则\n需审批。\n尾");
const directSource = material("直接材料", "直接说明\n直接证据。");
const primaryA: SourceEvidence = { id: "shared-evidence", clause_id: "A002", role: "primary", quote: "需复核。", start_char: 8, end_char: 12, source_id: sourceA.source_id, source_sha256: sourceA.source_sha256, status: "aligned", reason: null, fact_status: "candidate", review_status: "unreviewed" };
const supportA: SourceEvidence = { ...primaryA, id: "support-a", clause_id: "A001", role: "supporting", quote: "支持😀条款。", start_char: 0, end_char: 6, source_id: supportSource.source_id, source_sha256: supportSource.source_sha256 };
const primaryB: SourceEvidence = { ...primaryA, clause_id: "B002", quote: "需审批。", start_char: 5, end_char: 9, source_id: sourceB.source_id, source_sha256: sourceB.source_sha256 };
const supportB: SourceEvidence = { ...primaryB, id: "support-b", clause_id: "B001", role: "supporting", quote: "第二规则", start_char: 0, end_char: 4 };
const directEvidence: SourceEvidence = { ...primaryA, clause_id: "D001", quote: "直接证据。", start_char: 5, end_char: 10, source_id: directSource.source_id, source_sha256: directSource.source_sha256 };
const ruleA = { id: "rule-a", label: "复核规则", source_clause_id: "A002", fact_status: "extracted", review_status: "pending" };
const ruleB = { id: "rule-b", label: "审批规则", source_clause_id: "B002", fact_status: "candidate", review_status: "unreviewed" };
const relatedView = { selection: { kind: "node", id: "role-1", label: "经办人" }, evidence: [], sources: [], related_rules: [ruleA, ruleB], status: "ok" };
const directView = { ...relatedView, evidence: [directEvidence, supportA], sources: [directSource, supportSource] };
const ruleAView: SourceView = { selection: { kind: "node", id: "rule-a", label: "复核规则" }, evidence: [primaryA, supportA], sources: [sourceA, supportSource], status: "ok" };
const ruleBView: SourceView = { selection: { kind: "node", id: "rule-b", label: "审批规则" }, evidence: [primaryB, supportB], sources: [sourceB], status: "ok" };
const response = (payload: unknown, status = 200) => new Response(JSON.stringify(payload), { status });

function requestedId(input: RequestInfo | URL) {
  const query = new URL(String(input), "http://localhost").searchParams;
  return query.get("node_id") ?? query.get("edge_id");
}

function routeSources(selection: unknown = relatedView, secondRule: unknown = ruleBView, secondRuleStatus = 200) {
  globalThis.fetch = async (input) => {
    if (requestedId(input) === "rule-a") return response(ruleAView);
    if (requestedId(input) === "rule-b") return response(secondRule, secondRuleStatus);
    return response(selection);
  };
}

async function openSources(view: ReturnType<typeof render>) {
  fireEvent.click(await view.findByRole("button", { name: "Open source material" }));
  return view.getByRole("dialog");
}

function chooseContext(view: ReturnType<typeof render>, label: string) {
  const select = view.getByRole("combobox", { name: "Evidence context" });
  const option = within(select).getByRole("option", { name: label });
  fireEvent.change(select, { target: { value: option.getAttribute("value") } });
}

function deferredResponse() {
  let resolve!: (value: Response) => void;
  const promise = new Promise<Response>((finish) => { resolve = finish; });
  return { promise, resolve };
}

test.beforeEach(() => routeSources());
test.afterEach(cleanup);

test("related-only selections count rules and load rule references only when the compact entry opens", async () => {
  const requests: string[] = [];
  globalThis.fetch = async (input) => {
    requests.push(String(input));
    return response(requestedId(input) === "rule-a" ? ruleAView : relatedView);
  };
  const view = render(<SourceEvidencePanel kind="node" id="role-1" />);
  await view.findByText(/2 related rules/);
  assert.doesNotMatch(view.container.textContent ?? "", /0 source materials|0 evidence items/);
  assert.equal(requests.length, 1);
  assert.equal(view.queryByRole("dialog"), null);
  const dialog = await openSources(view);
  await within(dialog).findByLabelText("Full source text");
  assert.equal(requests.length, 2);
  assert.equal(requestedId(requests[1]), "rule-a");
  assert.equal(new URL(requests[1], "http://localhost").searchParams.has("edge_id"), false);
  assert.ok(within(dialog).getByText("Related rule evidence"));
  assert.match(dialog.textContent ?? "", /belong to.*rule.*do not establish.*field.*relationship.*support/i);
  assert.match(dialog.textContent ?? "", /Fact status: extracted.*Business review: pending/);
  assert.match(dialog.textContent ?? "", /Source clause: A002/);
  assert.equal(within(dialog).queryByRole("option", { name: "Direct evidence" }), null);
  assert.equal(dialog.querySelector("mark")?.textContent, "需复核。");
  assert.equal(dialog.querySelector("mark")?.previousSibling?.textContent, "甲😀\n需复核。\n");
});

test("related rule primary and supporting citations retain exact source selection and Unicode highlighting", async () => {
  const view = render(<SourceEvidencePanel kind="node" id="role-1" />);
  const dialog = await openSources(view);
  fireEvent.click(await within(dialog).findByRole("button", { name: /Supporting.*A001/ }));
  assert.equal(within(dialog).getByLabelText("Full source text").textContent, "支持😀条款。");
  assert.equal(dialog.querySelector("mark")?.textContent, "支持😀条款。");
  fireEvent.change(within(dialog).getByRole("combobox", { name: "Source material" }), { target: { value: "0" } });
  assert.equal(within(dialog).getByLabelText("Full source text").textContent, "甲😀\n需复核。\n需复核。\n尾");
  assert.equal(dialog.querySelector("mark"), null);
  fireEvent.click(within(dialog).getByRole("button", { name: /Primary.*A002/ }));
  assert.equal(dialog.querySelector("mark")?.previousSibling?.textContent, "甲😀\n需复核。\n");
});

test("citation navigation scrolls only source text without moving dialog controls out of view", async () => {
  const view = render(<SourceEvidencePanel kind="node" id="role-1" />);
  const dialog = await openSources(view);
  const sourceText = await within(dialog).findByLabelText("Full source text");
  const mark = dialog.querySelector("mark");
  assert.ok(mark);
  // JSDOM has no layout. Supply viewport geometry and emulate the browser's
  // ancestor-scrolling behavior so that a scrollIntoView regression is visible.
  Object.defineProperties(sourceText, {
    clientHeight: { configurable: true, value: 200 },
    clientTop: { configurable: true, value: 1 },
  });
  sourceText.getBoundingClientRect = () => new dom.window.DOMRect(0, 200, 600, 200);
  mark.getBoundingClientRect = () => new dom.window.DOMRect(0, 600, 200, 20);
  mark.scrollIntoView = () => { dialog.scrollTop = 250; };
  sourceText.scrollTop = 40;
  fireEvent.click(within(dialog).getByRole("button", { name: /Supporting.*A001/ }));
  assert.equal(dialog.scrollTop, 0, "citation navigation must leave the outer dialog at its current position");
  assert.equal(sourceText.scrollTop, 349, "the citation is centered within the source text viewport");
  fireEvent.change(within(dialog).getByRole("combobox", { name: "Source material" }), { target: { value: "0" } });
  assert.equal(sourceText.scrollTop, 0, "material navigation without a citation resets the source viewport");
  assert.equal(dialog.scrollTop, 0);
});

test("source audit identifiers and hashes are optional details while title, version and material status stay visible", async () => {
  globalThis.fetch = async () => response({ ...ruleAView, sources: [{ ...sourceA, source_uri: "https://example.test/policy" }, supportSource] });
  const view = render(<SourceEvidencePanel kind="node" id="rule-a" />);
  const dialog = await openSources(view);
  const identity = within(dialog).getByRole("region", { name: "Source identity" });
  const details = identity.querySelector("details");
  assert.ok(details, "verbose audit metadata should have an explicit disclosure");
  assert.equal(details.open, false);
  assert.equal(within(identity).getByRole("heading", { name: "复核制度" }).closest("details"), null);
  assert.equal(within(identity).getByText("Version: v1").closest("details"), null);
  assert.equal(within(identity).getByText(/Material status: available/).closest("details"), null);
  fireEvent.click(within(details).getByText("Source details & SHA-256"));
  assert.equal(details.open, true);
  assert.match(details.textContent ?? "", /Source ID: 复核制度/);
  assert.match(details.textContent ?? "", /Source URI: https:\/\/example.test\/policy/);
  assert.match(details.textContent ?? "", /Expected SHA-256: [a-f0-9]{64}/);
  assert.match(details.textContent ?? "", /Actual SHA-256: [a-f0-9]{64}/);
  fireEvent.click(within(details).getByText("Source details & SHA-256"));
  assert.equal(details.open, false);
});

test("the source details disclosure remains keyboard reachable when no source text is available", async () => {
  globalThis.fetch = async () => response({ ...ruleAView, sources: [], evidence: [{ ...primaryA, status: "source_missing", reason: "The source is unavailable." }] });
  const view = render(<SourceEvidencePanel kind="node" id="rule-a" />);
  const dialog = await openSources(view);
  const summary = within(dialog).getByText("Source details & SHA-256");
  const close = within(dialog).getByRole("button", { name: "Close source material" });
  fireEvent.keyDown(close, { key: "Tab", shiftKey: true });
  assert.ok(document.activeElement === summary, "the final source details control receives reverse-tab focus");
  fireEvent.keyDown(summary, { key: "Tab" });
  assert.ok(document.activeElement === close, "Tab wraps from source details back to Close");
});

test("changing evidence context preserves keyboard focus on its selector and restores the entry on close", async () => {
  routeSources(directView);
  const view = render(<React.StrictMode><SourceEvidencePanel kind="node" id="role-1" /></React.StrictMode>);
  const entry = await view.findByRole("button", { name: "Open source material" });
  entry.focus();
  fireEvent.click(entry);
  assert.ok(document.activeElement === view.getByRole("button", { name: "Close source material" }));
  view.getByRole("combobox", { name: "Evidence context" }).focus();
  for (const [label, clause] of [["复核规则", "A002"], ["审批规则", "B002"], ["Direct evidence", "D001"]]) {
    chooseContext(view, label);
    assert.ok(document.activeElement === view.getByRole("combobox", { name: "Evidence context" }), "context changes keep focus on their selector");
    await view.findByRole("button", { name: new RegExp(`Primary.*${clause}`) });
    assert.ok(document.activeElement === view.getByRole("combobox", { name: "Evidence context" }), "loading evidence does not move keyboard focus");
  }
  fireEvent.keyDown(view.getByRole("dialog"), { key: "Escape" });
  assert.ok(document.activeElement === entry, "closing the dialog restores focus to its entry");
});

test("changing related rules resets evidence even when their evidence IDs are identical", async () => {
  const view = render(<SourceEvidencePanel kind="node" id="role-1" />);
  await openSources(view);
  await view.findByRole("button", { name: /Primary.*A002/ });
  chooseContext(view, "审批规则");
  assert.equal(view.queryByLabelText("Full source text"), null);
  assert.equal(view.getByRole("dialog").querySelector("mark"), null);
  await view.findByRole("button", { name: /Primary.*B002/ });
  const dialog = view.getByRole("dialog");
  assert.equal(within(dialog).getByLabelText("Full source text").textContent, "第二规则\n需审批。\n尾");
  assert.equal(dialog.querySelector("mark")?.textContent, "需审批。");
  assert.equal(within(dialog).queryByRole("button", { name: /A002/ }), null);
  assert.match(dialog.textContent ?? "", /Fact status: candidate.*Business review: unreviewed/);
  assert.doesNotMatch(dialog.textContent ?? "", /Fact status: extracted/);
});

test("direct and related evidence remain separate choices and a requested direct supporting citation is preserved", async () => {
  routeSources(directView);
  const view = render(<SourceEvidencePanel kind="node" id="role-1" initialEvidenceId="support-a" />);
  const dialog = await openSources(view);
  assert.equal(dialog.querySelector("mark")?.textContent, "支持😀条款。");
  assert.ok(within(dialog).getByRole("option", { name: "Direct evidence" }));
  assert.equal(within(dialog).queryByText("Related rule evidence"), null);
  chooseContext(view, "复核规则");
  await view.findByRole("button", { name: /Primary.*A002/ });
  assert.equal(view.getByRole("dialog").querySelector("mark")?.textContent, "需复核。");
  assert.equal(view.queryByRole("button", { name: /D001/ }), null);
  chooseContext(view, "Direct evidence");
  assert.equal(view.getByRole("dialog").querySelector("mark")?.textContent, "支持😀条款。");
  fireEvent.click(view.getByRole("button", { name: /Primary.*D001/ }));
  assert.equal(view.getByRole("dialog").querySelector("mark")?.textContent, "直接证据。");
  assert.equal(view.queryByRole("button", { name: /A002/ }), null);
});

test("a single related rule still exposes its context and unknown rule statuses", async () => {
  routeSources({ ...relatedView, related_rules: [{ ...ruleA, fact_status: null, review_status: null, source_clause_id: null }] });
  const view = render(<SourceEvidencePanel kind="node" id="role-1" />);
  await view.findByText(/1 related rule\b/);
  const dialog = await openSources(view);
  assert.ok(within(dialog).getByRole("combobox", { name: "Evidence context" }));
  assert.ok(within(dialog).getByRole("option", { name: "复核规则" }));
  assert.match(dialog.textContent ?? "", /Fact status: Unknown.*Business review: Unknown/);
  await within(dialog).findByLabelText("Full source text");
});

test("empty and failed related rule requests never fall back to direct or previous rule evidence", async () => {
  for (const failed of [false, true]) {
    routeSources(directView, { ...ruleBView, evidence: [], sources: [], status: "no_evidence" }, failed ? 503 : 200);
    const view = render(<SourceEvidencePanel kind="node" id="role-1" />);
    await openSources(view);
    assert.equal(view.getByRole("dialog").querySelector("mark")?.textContent, "直接证据。");
    chooseContext(view, "复核规则");
    await view.findByRole("button", { name: /Primary.*A002/ });
    chooseContext(view, "审批规则");
    if (failed) assert.match((await view.findByRole("alert")).textContent ?? "", /could not be loaded.*503/);
    else await view.findByText(/No explicit evidence is linked/);
    const dialog = view.getByRole("dialog");
    assert.equal(dialog.querySelector("mark"), null);
    assert.equal(within(dialog).queryByLabelText("Full source text"), null);
    assert.equal(within(dialog).queryByRole("button", { name: /A002|D001/ }), null);
    assert.ok(within(dialog).getByText("Related rule evidence"));
    cleanup();
  }
});

test("rapid context switches clear material immediately and ignore an aborted rule's late response", async () => {
  const pendingB = deferredResponse();
  const pendingA = deferredResponse();
  let visitsA = 0;
  let signalB: AbortSignal | null | undefined;
  globalThis.fetch = async (input, init) => {
    if (requestedId(input) === "rule-b") { signalB = init?.signal; return pendingB.promise; }
    if (requestedId(input) === "rule-a") return visitsA++ === 0 ? response(ruleAView) : pendingA.promise;
    return response(relatedView);
  };
  const view = render(<SourceEvidencePanel kind="node" id="role-1" />);
  await openSources(view);
  await view.findByLabelText("Full source text");
  chooseContext(view, "审批规则");
  assert.equal(view.queryByLabelText("Full source text"), null);
  assert.equal(view.getByRole("dialog").querySelector("mark"), null);
  chooseContext(view, "复核规则");
  assert.equal(signalB?.aborted, true);
  await act(async () => { pendingB.resolve(response(ruleBView)); await pendingB.promise; });
  assert.equal(view.queryByLabelText("Full source text"), null);
  assert.equal(view.queryByRole("button", { name: /B002/ }), null);
  await act(async () => { pendingA.resolve(response(ruleAView)); await pendingA.promise; });
  assert.equal(view.getByRole("dialog").querySelector("mark")?.textContent, "需复核。");
  assert.equal(view.queryByRole("button", { name: /B002/ }), null);
});

test("node changes close the related source dialog and abort its pending rule request", async () => {
  const pending = deferredResponse();
  let ruleSignal: AbortSignal | null | undefined;
  globalThis.fetch = async (input, init) => {
    if (requestedId(input) === "rule-a") { ruleSignal = init?.signal; return pending.promise; }
    if (requestedId(input) === "role-2") return response({ ...relatedView, selection: { kind: "node", id: "role-2", label: "其他角色" }, related_rules: [] });
    return response(relatedView);
  };
  const view = render(<SourceEvidencePanel kind="node" id="role-1" />);
  await openSources(view);
  view.rerender(<SourceEvidencePanel kind="node" id="role-2" />);
  assert.equal(ruleSignal?.aborted, true);
  assert.equal(view.queryByRole("dialog"), null);
  await view.findByText(/No explicit evidence or source material/);
  await act(async () => { pending.resolve(response(ruleAView)); await pending.promise; });
  assert.equal(view.queryByRole("dialog"), null);
  assert.equal(view.queryByRole("button", { name: "Open source material" }), null);
});

test("a business relationship opens rule context and changing the selected relationship closes it", async () => {
  const edge = "https://example.test/business-edge?a=1&b=审批";
  const requests: string[] = [];
  globalThis.fetch = async (input) => {
    requests.push(String(input));
    return response(requestedId(input) === "rule-a" ? ruleAView : { ...relatedView, selection: { kind: "edge", id: edge, label: "performedBy" } });
  };
  const view = render(<RelationshipSourceEvidence edgeIds={[edge, "other-edge"]} />);
  fireEvent.change(view.getByRole("combobox", { name: "Relationship for evidence" }), { target: { value: edge } });
  const dialog = await openSources(view);
  await within(dialog).findByLabelText("Full source text");
  assert.equal(new URL(requests[0], "http://localhost").searchParams.get("edge_id"), edge);
  assert.equal(new URL(requests[1], "http://localhost").searchParams.get("node_id"), "rule-a");
  assert.ok(within(dialog).getByText("Related rule evidence"));
  fireEvent.change(view.getByRole("combobox", { name: "Relationship for evidence" }), { target: { value: "other-edge" } });
  assert.equal(view.queryByRole("dialog"), null);
  await view.findByRole("button", { name: "Open source material" });
  assert.equal(view.queryByRole("dialog"), null);
});

test("retained workspaces hide related rule portals and restore the selected rule and supporting citation", async () => {
  const content = <SourceEvidencePanel kind="node" id="role-1" />;
  const view = render(<RetainedWorkspace active>{content}</RetainedWorkspace>);
  await openSources(view);
  await view.findByLabelText("Full source text");
  chooseContext(view, "审批规则");
  fireEvent.click(await view.findByRole("button", { name: /Supporting.*B001/ }));
  assert.equal(view.getByRole("dialog").querySelector("mark")?.textContent, "第二规则");
  view.rerender(<RetainedWorkspace active={false}>{content}</RetainedWorkspace>);
  assert.equal(view.queryByRole("dialog"), null);
  view.rerender(<RetainedWorkspace active>{content}</RetainedWorkspace>);
  const dialog = view.getByRole("dialog");
  assert.equal(dialog.querySelector("mark")?.textContent, "第二规则");
  assert.equal(within(dialog).getByRole("option", { name: "审批规则" }).getAttribute("value"), (within(dialog).getByRole("combobox", { name: "Evidence context" }) as HTMLSelectElement).value);
  assert.equal(document.activeElement, within(dialog).getByRole("button", { name: "Close source material" }));
});

test("related context applies the existing strict source identity and citation validation", async () => {
  routeSources(relatedView, { ...ruleBView, evidence: [{ ...primaryB, source_sha256: "0".repeat(64) }] });
  const view = render(<SourceEvidencePanel kind="node" id="role-1" />);
  await openSources(view);
  await view.findByLabelText("Full source text");
  chooseContext(view, "审批规则");
  await view.findByRole("button", { name: /Primary.*B002/ });
  assert.equal(view.getByRole("dialog").querySelector("mark"), null);
  assert.equal(view.queryByLabelText("Full source text"), null);
  assert.match(view.getByRole("status").textContent ?? "", /Not located.*could not be verified/);
});

test("old responses without related rules keep direct evidence and requested citation behavior", async () => {
  globalThis.fetch = async () => response(ruleAView);
  const view = render(<SourceEvidencePanel kind="node" id="rule-a" initialEvidenceId="support-a" />);
  const dialog = await openSources(view);
  assert.equal(within(dialog).queryByRole("combobox", { name: "Evidence context" }), null);
  assert.equal(dialog.querySelector("mark")?.textContent, "支持😀条款。");
  assert.equal(within(dialog).queryByText("Related rule evidence"), null);
});
