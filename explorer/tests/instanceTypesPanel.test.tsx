import assert from "node:assert/strict";
import test from "node:test";
import { JSDOM } from "jsdom";
import React from "react";
import { loadInstanceTypes, type InstanceTypesSnapshot } from "../src/workspaces/GraphWorkspace/instanceTypes.ts";

(globalThis as typeof globalThis & { React: typeof React }).React = React;
const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost" });
Object.assign(globalThis, { window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement, Node: dom.window.Node });
Object.defineProperty(globalThis, "navigator", { configurable: true, value: dom.window.navigator });
const { cleanup, fireEvent, render, within } = await import("@testing-library/react");
const { InstanceTypesPanel } = await import("../src/workspaces/GraphWorkspace/InstanceTypesPanel.tsx");

const classUri = "https://example.test/technical/ProcessRule";
const relatedUri = "https://example.test/business/PurchaseRequest";
const snapshot: InstanceTypesSnapshot = {
  node_id: "rule-1", status: "declared",
  types: [{ class_uri: classUri, label: "Process rule", loaded: true, ontology_uri: null, basis: [{ kind: "graph_namespace", value: "https://example.test/technical/" }] }],
  related_concepts: [{ class_uri: relatedUri, label: "Purchase request", ontology_uri: "https://example.test/business/", evidence_ids: ["e-1"] }],
  related_status: "ready", notice: "Candidate associations do not change candidate / unreviewed status.",
};
const baseProps = { nodeId: "rule-1", snapshot, loading: false, error: null, showTypes: false, onShowTypes: () => {}, onOpenOntologyEntity: () => {} };
const response = (payload: unknown, status = 200) => new Response(JSON.stringify(payload), { status });
test.afterEach(cleanup);

test("primary class links remain direct while identity and evidence details are collapsed and reset for a new node", () => {
  const view = render(<InstanceTypesPanel {...baseProps} />);
  assert.ok(view.getByRole("button", { name: "Open class Process rule" }));
  const identity = view.getByText("Class details").closest("details");
  const related = view.getByText("Related concepts (1)").closest("details");
  assert.ok(identity);
  assert.ok(related);
  assert.equal(identity.open, false);
  assert.equal(related.open, false);
  identity.open = true;
  related.open = true;
  assert.ok(view.getByRole("button", { name: "Open class Purchase request" }));
  view.rerender(<InstanceTypesPanel {...baseProps} nodeId="rule-2" snapshot={{ ...snapshot, node_id: "rule-2" }} />);
  assert.equal(view.getByText("Class details").closest("details")?.open, false);
  assert.equal(view.getByText("Related concepts (1)").closest("details")?.open, false);
});

test("declared classes and evidence-related business concepts remain distinct and navigate exact URIs", () => {
  const opened: string[] = [];
  const toggles: boolean[] = [];
  const view = render(<InstanceTypesPanel {...baseProps} onOpenOntologyEntity={(uri) => opened.push(uri)} onShowTypes={(checked) => toggles.push(checked)} />);
  const declared = view.getByRole("region", { name: "Declared class" });
  const related = view.getByRole("region", { name: "Related business concepts via evidence" });
  const disclosure = related.querySelector("details");
  if (disclosure) disclosure.open = true;
  assert.ok(within(declared).getByText("Process rule"));
  assert.equal(within(declared).queryByText("Purchase request"), null);
  assert.ok(within(related).getByText("Purchase request"));
  assert.match(declared.textContent ?? "", /Graph namespace/);
  assert.match(related.textContent ?? "", /do not declare instance membership/i);
  assert.match(view.container.textContent ?? "", /candidate.*unreviewed/);
  fireEvent.click(within(declared).getByRole("button", { name: "Open class Process rule" }));
  fireEvent.click(within(related).getByRole("button", { name: "Open class Purchase request" }));
  fireEvent.click(view.getByRole("checkbox", { name: "Show class links" }));
  assert.deepEqual(opened, [classUri, relatedUri]);
  assert.deepEqual(toggles, [true]);
  assert.equal((view.getByRole("checkbox") as HTMLInputElement).checked, false, "toggle stays parent-controlled");
});

test("multiple declarations show each basis and an unloaded definition cannot navigate", () => {
  const unloaded = "urn:external:Policy";
  const view = render(<InstanceTypesPanel {...baseProps} snapshot={{ ...snapshot, types: [snapshot.types[0], { class_uri: unloaded, label: "External policy", loaded: false, ontology_uri: null, basis: [{ kind: "rdf_type_edge", value: "rdf:type", edge_id: "typed-edge" }, { kind: "rdf_type_property", value: "@type" }, { kind: "node_type", value: unloaded }] }] }} />);
  assert.ok(view.getByText(unloaded));
  assert.ok(view.getByText("Definition not loaded"));
  assert.equal((view.getByRole("button", { name: "Open class External policy" }) as HTMLButtonElement).disabled, true);
  assert.equal((view.getByRole("button", { name: "Open class Process rule" }) as HTMLButtonElement).disabled, false, "a loaded class can resolve its owner even when ontology_uri is unknown");
  assert.match(view.container.textContent ?? "", /RDF type edge/);
  assert.match(view.container.textContent ?? "", /RDF type property/);
  assert.match(view.container.textContent ?? "", /Node type/);
});

test("legacy unmapped nodes state the absence of a declaration without claiming missing business references are reviewed", () => {
  const view = render(<InstanceTypesPanel {...baseProps} snapshot={{ ...snapshot, status: "unmapped", types: [], related_concepts: [], related_status: "unconfigured", notice: "No evidence context registered." }} />);
  assert.ok(view.getByText(/Unmapped/));
  assert.match(view.container.textContent ?? "", /No explicit class declaration/);
  assert.ok(view.getByText("No evidence context registered."));
  assert.equal((view.getByRole("checkbox", { name: "Show class links" }) as HTMLInputElement).disabled, true);
  assert.equal(view.queryByRole("button", { name: /Open class/ }), null);
});

test("loading, errors and another node's response never expose previous declarations", () => {
  const view = render(<InstanceTypesPanel {...baseProps} />);
  view.rerender(<InstanceTypesPanel {...baseProps} loading />);
  assert.ok(view.getByRole("status"));
  assert.equal(view.queryByText("Process rule"), null);
  view.rerender(<InstanceTypesPanel {...baseProps} error="Class lookup failed." />);
  assert.match(view.getByRole("alert").textContent ?? "", /Class lookup failed/);
  assert.equal(view.queryByText("Process rule"), null);
  view.rerender(<InstanceTypesPanel {...baseProps} nodeId="other" />);
  assert.equal(view.queryByText("Process rule"), null);
  assert.equal(view.queryByText("Purchase request"), null);
});

test("unavailable related evidence is distinguished from a ready empty result", () => {
  const view = render(<InstanceTypesPanel {...baseProps} snapshot={{ ...snapshot, related_status: "unavailable", related_concepts: [], notice: "Source hash mismatch." }} />);
  assert.match(view.getByRole("region", { name: "Related business concepts via evidence" }).textContent ?? "", /unavailable/i);
  assert.ok(view.getByText("Source hash mismatch."));
  view.rerender(<InstanceTypesPanel {...baseProps} snapshot={{ ...snapshot, related_concepts: [] }} />);
  assert.match(view.getByRole("region", { name: "Related business concepts via evidence" }).textContent ?? "", /No verified evidence associations/);
});

test("untrusted class labels and notices render as text without executable links", () => {
  const html = '<img src=x onerror="window.bad=1">';
  const view = render(<InstanceTypesPanel {...baseProps} snapshot={{ ...snapshot, types: [{ ...snapshot.types[0], label: html, class_uri: "javascript:alert(1)" }], notice: html }} />);
  assert.equal(view.container.querySelector("img,script,a[href]"), null);
  assert.ok(view.getAllByText(html).length > 0);
});

test("type requests encode identity, forward cancellation and validate response identity and shape", async () => {
  const id = "rule /?&😀";
  const controller = new AbortController();
  let request = "";
  let signal: AbortSignal | null | undefined;
  globalThis.fetch = async (input, init) => { request = String(input); signal = init?.signal; return response({ ...snapshot, node_id: id }); };
  assert.equal((await loadInstanceTypes(id, controller.signal)).node_id, id);
  assert.equal(new URL(request, "http://localhost").searchParams.get("node_id"), id);
  assert.equal(signal, controller.signal);
  for (const payload of [snapshot, { ...snapshot, node_id: id, types: null }, { ...snapshot, node_id: id, types: [{ ...snapshot.types[0], label: {} }] }, { ...snapshot, node_id: id, related_status: "reviewed" }, { ...snapshot, node_id: id, related_status: ["ready"] }, { ...snapshot, node_id: id, types: [{ ...snapshot.types[0], basis: [{ kind: ["graph_namespace"], value: "urn:example:" }] }] }]) {
    globalThis.fetch = async () => response(payload);
    await assert.rejects(loadInstanceTypes(id));
  }
  globalThis.fetch = async () => response({ detail: "Not found" }, 404);
  await assert.rejects(loadInstanceTypes(id), /404/);
});

const conceptReference = {
  node_id: "rule-1", label: "合法有效的合同", class_uri: "https://example.test/business/Contract", class_label: "合同",
  ontology_uri: "https://example.test/business/", rationale: "The rule requires a contract document.",
  status: "candidate", review_status: "unreviewed", evidence_ids: ["e-contract"],
} as const;

test("candidate concept references stay collapsed behind the actual class and reset on selection", () => {
  const opened: string[] = [];
  const mapped = { ...snapshot, concept_references: [{ ...conceptReference, evidence_ids: ["e-contract"] }], concept_reference_issues: [] };
  const view = render(<InstanceTypesPanel {...baseProps} snapshot={mapped} onOpenOntologyEntity={(uri) => opened.push(uri)} />);
  const concepts = view.getByRole("region", { name: "Business concept references" });
  const declared = view.getByRole("region", { name: "Declared class" });
  assert.equal(within(declared).queryByText("合同"), null);
  const disclosure = within(concepts).getByText("Candidate concept references (1)").closest("details");
  assert.ok(disclosure);
  assert.equal(disclosure.open, false);
  fireEvent.click(within(concepts).getByText("Candidate concept references (1)"));
  const button = within(concepts).getByRole("button", { name: "Open concept 合同" });
  assert.ok(button.closest("details") === disclosure);
  fireEvent.click(button);
  assert.deepEqual(opened, ["https://example.test/business/Contract"]);
  assert.match(concepts.textContent ?? "", /candidate\s*\/\s*unreviewed/i);
  assert.match(concepts.textContent ?? "", /not.*instance declaration/i);
  assert.ok(within(declared).getByText("Process rule"));
  view.rerender(<InstanceTypesPanel {...baseProps} nodeId="rule-2" snapshot={{ ...mapped, node_id: "rule-2" }} />);
  assert.equal(view.getByText("Candidate concept references (1)").closest("details")?.open, false);
  view.rerender(<InstanceTypesPanel {...baseProps} nodeId="other" snapshot={mapped} />);
  assert.equal(view.queryByText("合同"), null);
  view.rerender(<InstanceTypesPanel {...baseProps} snapshot={mapped} loading />);
  assert.equal(view.queryByRole("region", { name: "Business concept references" }), null);
});

test("invalid concept references report their reason and never become a clickable mapping", () => {
  const unavailable = { ...snapshot, concept_references: [], concept_reference_issues: [{ node_id: "rule-1", class_uri: conceptReference.class_uri, reason: "Candidate RDF fingerprint does not match." }] };
  const view = render(<InstanceTypesPanel {...baseProps} snapshot={unavailable} />);
  const concepts = view.getByRole("region", { name: "Business concept references" });
  assert.match(concepts.textContent ?? "", /Candidate RDF fingerprint does not match/);
  assert.equal(within(concepts).queryByRole("button", { name: /Open concept/ }), null);
  assert.doesNotMatch(concepts.textContent ?? "", /references \(0\)/i);
  view.rerender(<InstanceTypesPanel {...baseProps} />);
  assert.equal(view.queryByRole("region", { name: "Business concept references" }), null, "legacy responses do not gain a misleading mapping section");
});

test("concept labels and rationale remain literal text and have no external HTML navigation", () => {
  const html = '<img src=x onerror="window.bad=1">';
  const mapped = { ...snapshot, concept_references: [{ ...conceptReference, class_label: html, rationale: html, evidence_ids: ["e-contract"] }], concept_reference_issues: [] };
  const view = render(<InstanceTypesPanel {...baseProps} snapshot={mapped} onOpenOntologyEntity={undefined} />);
  fireEvent.click(view.getByText("Candidate concept references (1)"));
  const button = view.getByRole("button", { name: `Open concept ${html}` });
  assert.equal((button as HTMLButtonElement).disabled, true);
  assert.equal(view.container.querySelector("img,script,a[href]"), null);
});

test("instance-type client rejects foreign, reviewed, or malformed concept references while accepting legacy payloads", async () => {
  const mapped = { ...snapshot, concept_references: [{ ...conceptReference, evidence_ids: ["e-contract"] }], concept_reference_issues: [] };
  for (const payload of [
    { ...mapped, concept_references: [{ ...conceptReference, node_id: "other" }] },
    { ...mapped, concept_references: [{ ...conceptReference, status: "accepted" }] },
    { ...mapped, concept_references: [{ ...conceptReference, review_status: "reviewed" }] },
    { ...mapped, concept_references: [{ ...conceptReference, evidence_ids: [42] }] },
    { ...mapped, concept_references: [{ ...conceptReference, class_uri: {} }] },
    { ...mapped, concept_reference_issues: [{ node_id: "other", class_uri: conceptReference.class_uri, reason: "Missing node." }] },
    { ...mapped, concept_reference_issues: null },
  ]) {
    globalThis.fetch = async () => response(payload);
    await assert.rejects(loadInstanceTypes("rule-1"));
  }
  globalThis.fetch = async () => response(snapshot);
  assert.equal((await loadInstanceTypes("rule-1")).node_id, "rule-1");
  globalThis.fetch = async () => response(mapped);
  assert.equal((await loadInstanceTypes("rule-1")).node_id, "rule-1");
});
