import assert from "node:assert/strict";
import test from "node:test";
import { createHash } from "node:crypto";
import { JSDOM } from "jsdom";
import React from "react";

(globalThis as typeof globalThis & { React: typeof React }).React = React;
const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost" });
Object.assign(globalThis, { window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement, Node: dom.window.Node });
Object.defineProperty(globalThis, "navigator", { configurable: true, value: dom.window.navigator });
const { act, cleanup, fireEvent, render, within } = await import("@testing-library/react");
const { SourceEvidencePanel } = await import("../src/workspaces/GraphWorkspace/SourceEvidencePanel.tsx");
const { OntologyRuleEvidencePanel } = await import("../src/workspaces/OntologyWorkspace/OntologyRuleEvidencePanel.tsx");

const text = "采购😀申请。\n审批支持条款。\n<script>window.bad=1</script>";
const hash = createHash("sha256").update(text).digest("hex");
const primary = { id: "e-main", clause_id: "C001", role: "primary", quote: "采购😀申请。", start_char: 0, end_char: 6, source_id: "policy", source_sha256: hash, status: "aligned", reason: null, fact_status: "candidate", review_status: "unreviewed" };
const supporting = { ...primary, id: "e-support", clause_id: "C002", role: "supporting", quote: "审批支持条款。", start_char: 7, end_char: 14 };
const sourceView = {
  selection: { kind: "node", id: "rule-shared", label: "采购审批规则" },
  evidence: [primary, supporting],
  sources: [{ source_id: "policy", source_sha256: hash, actual_sha256: hash, title: "采购制度", version: null, source_uri: null, status: "available", reason: null, text, character_count: Array.from(text).length }],
  status: "ok",
};
const response = (payload: unknown, status = 200) => new Response(JSON.stringify(payload), { status });
const ontologyUri = "https://example.test/business/";
const termUri = `${ontologyUri}PurchaseRequest`;
const related = {
  ontology_uri: ontologyUri, term_uri: termUri, status: "ready",
  term: { id: termUri, label: "采购申请", type: "owl:Class", description: "采购申请的类型。" },
  association_status: "candidate",
  associations: [{
    node_id: "rule-shared", label: "采购审批规则", modality: "must", fact_status: "candidate", review_status: "unreviewed",
    evidence: [
      { ...primary, links: [{ term_uri: termUri, label: "采购申请", kind: "direct", relation: null }] },
      { ...supporting, links: [{ term_uri: `${ontologyUri}requiresApproval`, label: "所需审批", kind: "property", relation: "rdfs:domain" }] },
    ],
  }],
  anchors: [],
  notice: "Candidate associations only. Source overlap does not imply business approval or complete coverage.",
};

function mockRelatedResponse(payload: unknown = related, status = 200) {
  globalThis.fetch = async (input) => String(input).startsWith("/api/sources/") ? response(sourceView) : response(payload, status);
}

async function expandRelated(view: ReturnType<typeof render>) {
  fireEvent.click(view.getByRole("button", { name: /Related rules.*evidence/ }));
  return view;
}

test.afterEach(cleanup);

test("an explicitly selected supporting citation is initially highlighted and other rule evidence remains accessible", async () => {
  globalThis.fetch = async () => response(sourceView);
  const view = render(<SourceEvidencePanel kind="node" id="rule-shared" initialEvidenceId="e-support" />);
  fireEvent.click(await view.findByRole("button", { name: "Open source material" }));
  const dialog = view.getByRole("dialog");
  assert.equal(dialog.querySelector("mark")?.textContent, "审批支持条款。");
  fireEvent.click(within(dialog).getByRole("button", { name: /Primary.*C001/ }));
  assert.equal(dialog.querySelector("mark")?.textContent, "采购😀申请。");
  view.rerender(<SourceEvidencePanel kind="node" id="rule-shared" initialEvidenceId="e-main" />);
  assert.equal(view.queryByRole("dialog"), null);
});

test("an unavailable requested citation is explained instead of selecting an unrelated citation", async () => {
  globalThis.fetch = async () => response(sourceView);
  const view = render(<SourceEvidencePanel kind="node" id="rule-shared" initialEvidenceId="removed-evidence" />);
  fireEvent.click(await view.findByRole("button", { name: "Open source material" }));
  assert.equal(view.getByRole("dialog").querySelector("mark"), null);
  assert.match(view.getByRole("status").textContent ?? "", /requested evidence.*unavailable/i);
});

test("related rules start collapsed and explain direct versus property-linked primary and supporting evidence", async () => {
  const requests: string[] = [];
  globalThis.fetch = async (input) => { requests.push(String(input)); return response(related); };
  const view = render(<OntologyRuleEvidencePanel ontologyUri={ontologyUri} termUri={termUri} />);
  assert.equal(view.getByRole("button", { name: /Related rules.*evidence/ }).getAttribute("aria-expanded"), "false");
  assert.equal(requests.length, 0);
  await expandRelated(view);
  await view.findByText("采购审批规则");
  assert.ok(view.getByText("Direct term citation"));
  assert.ok(view.getByText(/Via property: 所需审批/));
  assert.ok(view.getByRole("button", { name: /Primary.*C001/ }));
  assert.ok(view.getByRole("button", { name: /Supporting.*C002/ }));
  assert.match(view.container.textContent ?? "", /candidate.*unreviewed/);
  assert.match(view.container.textContent ?? "", /does not imply business approval or complete coverage/);
  const request = new URL(requests[0], "http://localhost");
  assert.equal(request.searchParams.get("ontology_uri"), ontologyUri);
  assert.equal(request.searchParams.get("term_uri"), termUri);
});

test("choosing a matching support citation opens that range while preserving all rule evidence", async () => {
  mockRelatedResponse();
  const view = render(<OntologyRuleEvidencePanel ontologyUri={ontologyUri} termUri={termUri} />);
  await expandRelated(view);
  fireEvent.click(await view.findByRole("button", { name: /Supporting.*C002/ }));
  fireEvent.click(await view.findByRole("button", { name: "Open source material" }));
  const dialog = view.getByRole("dialog");
  assert.equal(dialog.querySelector("mark")?.textContent, "审批支持条款。");
  fireEvent.click(within(dialog).getByRole("button", { name: /Primary.*C001/ }));
  assert.equal(dialog.querySelector("mark")?.textContent, "采购😀申请。");
});

test("changing concept closes a shared rule's open material and resets the rule disclosure", async () => {
  const secondTerm = `${ontologyUri}Approval`;
  globalThis.fetch = async (input) => String(input).startsWith("/api/sources/") ? response(sourceView) : response({ ...related, term_uri: new URL(String(input), "http://localhost").searchParams.get("term_uri") });
  const view = render(<OntologyRuleEvidencePanel ontologyUri={ontologyUri} termUri={termUri} />);
  await expandRelated(view);
  fireEvent.click(await view.findByRole("button", { name: /Primary.*C001/ }));
  fireEvent.click(await view.findByRole("button", { name: "Open source material" }));
  assert.ok(view.getByRole("dialog"));
  view.rerender(<OntologyRuleEvidencePanel ontologyUri={ontologyUri} termUri={secondTerm} />);
  assert.equal(view.queryByRole("dialog"), null);
  assert.equal(view.queryByText("采购审批规则"), null);
  assert.equal(view.getByRole("button", { name: /Related rules.*evidence/ }).getAttribute("aria-expanded"), "false");
});

test("a previous term's late response never replaces the current term's empty result", async () => {
  let finishOld: ((value: Response) => void) | undefined;
  let oldSignal: AbortSignal | null | undefined;
  const oldResponse = new Promise<Response>((resolve) => { finishOld = resolve; });
  const secondTerm = `${ontologyUri}Unlinked`;
  globalThis.fetch = async (input, init) => {
    if (String(input).includes("PurchaseRequest")) { oldSignal = init?.signal; return oldResponse; }
    return response({ ...related, term_uri: secondTerm, associations: [] });
  };
  const view = render(<OntologyRuleEvidencePanel ontologyUri={ontologyUri} termUri={termUri} />);
  await expandRelated(view);
  view.rerender(<OntologyRuleEvidencePanel ontologyUri={ontologyUri} termUri={secondTerm} />);
  assert.equal(oldSignal?.aborted, true);
  await expandRelated(view);
  await view.findByText(/No rules with verified source overlap/);
  await act(async () => { finishOld?.(response(related)); await oldResponse; });
  assert.equal(view.queryByText("采购审批规则"), null);
});

test("unconfigured and unavailable evidence show reasons without inventing a rule", async () => {
  for (const status of ["unconfigured", "unavailable"]) {
    mockRelatedResponse({ ...related, status, associations: [], anchors: [{ term_uri: termUri, label: "采购申请", status: "hash_mismatch", reason: "The registered source hash differs." }] });
    const view = render(<OntologyRuleEvidencePanel ontologyUri={ontologyUri} termUri={termUri} />);
    await expandRelated(view);
    await view.findByText(/The registered source hash differs/);
    assert.equal(view.queryByText("采购审批规则"), null);
    assert.equal(view.queryByRole("button", { name: "Open source material" }), null);
    cleanup();
  }
});

test("HTTP errors and mismatched term responses stay explicit and contain no stale rules", async () => {
  for (const [payload, status] of [[{ detail: "Term unavailable" }, 404], [{ ...related, term_uri: "wrong-term" }, 200]] as const) {
    mockRelatedResponse(payload, status);
    const view = render(<OntologyRuleEvidencePanel ontologyUri={ontologyUri} termUri={termUri} />);
    await expandRelated(view);
    await view.findByRole("alert");
    assert.equal(view.queryByText("采购审批规则"), null);
    cleanup();
  }
});

test("invalid rule evidence remains visible as a reason even when there are no verified associations", async () => {
  mockRelatedResponse({ ...related, associations: [], evidence_issues: [{ id: "broken-evidence", clause_id: "C003", status: "quote_mismatch", reason: "The rule quote no longer matches its source." }] });
  const view = render(<OntologyRuleEvidencePanel ontologyUri={ontologyUri} termUri={termUri} />);
  await expandRelated(view);
  await view.findByText(/The rule quote no longer matches its source/);
  assert.match(view.container.textContent ?? "", /C003.*quote mismatch/);
  assert.equal(view.queryByRole("button", { name: "Open source material" }), null);
});

test("untrusted rule labels, quotations and association notices remain literal text", async () => {
  const html = '<img src=x onerror="window.bad=1">';
  mockRelatedResponse({ ...related, notice: html, associations: [{ ...related.associations[0], label: html, evidence: [{ ...related.associations[0].evidence[0], quote: html }] }] });
  const view = render(<OntologyRuleEvidencePanel ontologyUri={ontologyUri} termUri={termUri} />);
  await expandRelated(view);
  await view.findAllByText(html);
  assert.equal(view.container.querySelector("img"), null);
  assert.equal(view.container.querySelector("script"), null);
});
