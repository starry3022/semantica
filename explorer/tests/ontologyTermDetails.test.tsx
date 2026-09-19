import assert from "node:assert/strict";
import test from "node:test";
import { JSDOM } from "jsdom";
import React from "react";

(globalThis as typeof globalThis & { React: typeof React }).React = React;
const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost" });
Object.assign(globalThis, { window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement, Node: dom.window.Node });
Object.defineProperty(globalThis, "navigator", { configurable: true, value: dom.window.navigator });
const { act, cleanup, fireEvent, render, waitFor } = await import("@testing-library/react");
const { OntologyTermDetails } = await import("../src/workspaces/OntologyWorkspace/OntologyTermDetails.tsx");
const { canEditOwnedOntologyTerm } = await import("../src/workspaces/OntologyWorkspace/ontologyEditorModel.ts");

const ontologyUri = "https://example.test/business/";
const termUri = `${ontologyUri}PurchaseRequest`;
const revision = `sha256:${"a".repeat(64)}`;
const current = {
  ontology_uri: ontologyUri,
  term_uri: termUri,
  revision,
  scope: "session",
  term: {
    id: termUri,
    type: "owl:Class",
    label: "采购申请",
    comment: "采购发生前提出申请。\n引用保留换行与 emoji 😀。",
    parents: [`${ontologyUri}Request`, `${ontologyUri}BusinessRecord`],
    domain: [] as string[],
    range: [] as string[],
  },
};
const response = (payload: unknown, status = 200) => new Response(JSON.stringify(payload), { status });
type View = ReturnType<typeof render>;

function displayed(view: View, value: string) {
  const options = { exact: true, normalizer: (text: string) => text };
  return (view.container.textContent ?? "").includes(value) || view.queryAllByDisplayValue(value, options).length > 0;
}

test.afterEach(cleanup);

test("only explicitly owned supported OWL or RDFS terms receive a save editor", () => {
  for (const type of [
    "owl:Class", "http://www.w3.org/2002/07/owl#Class",
    "rdfs:Class", "http://www.w3.org/2000/01/rdf-schema#Class",
    "owl:ObjectProperty", "http://www.w3.org/2002/07/owl#ObjectProperty",
    "owl:DatatypeProperty", "http://www.w3.org/2002/07/owl#DatatypeProperty",
  ]) {
    const node = { id: termUri, type, properties: { scheme_uri: ontologyUri } };
    assert.equal(canEditOwnedOntologyTerm(node, ontologyUri), true, type);
    assert.equal(canEditOwnedOntologyTerm({ ...node, properties: { scheme_uri: "https://example.test/external/" } }, ontologyUri), false, `${type} from another ontology`);
    assert.equal(canEditOwnedOntologyTerm({ ...node, properties: {} }, ontologyUri), false, `${type} without an explicit owner`);
  }
  for (const type of ["rdf:Property", "http://www.w3.org/1999/02/22-rdf-syntax-ns#Property", "ProcessRule", "owl:Ontology"]) {
    assert.equal(canEditOwnedOntologyTerm({ id: termUri, type, properties: { scheme_uri: ontologyUri } }, ontologyUri), false, type);
  }
  assert.equal(canEditOwnedOntologyTerm(undefined, ontologyUri), false);
});

test("a selected class shows its current definition, immutable identity and session scope before editing", async () => {
  const requests: string[] = [];
  globalThis.fetch = async (input) => { requests.push(String(input)); return response(current); };
  const view = render(<OntologyTermDetails ontologyUri={ontologyUri} termUri={termUri} onSaved={() => assert.fail("read must not save")} />);
  await view.findByRole("button", { name: "Edit class" });
  assert.ok(displayed(view, current.term.label));
  assert.ok(displayed(view, current.term.comment));
  assert.ok(displayed(view, termUri));
  assert.ok(displayed(view, "owl:Class"));
  for (const parent of current.term.parents) assert.ok(displayed(view, parent));
  assert.match(view.container.textContent ?? "", /session/i);
  assert.match(view.container.textContent ?? "", /publish|source file/i);
  assert.equal(view.queryByRole("button", { name: "Save changes" }), null);
  for (const field of view.container.querySelectorAll("input, textarea, select")) {
    assert.ok(field.hasAttribute("readonly") || field.hasAttribute("disabled"), "default details must not expose an editable form");
  }
  const request = new URL(requests[0], "http://localhost");
  assert.equal(request.pathname, "/api/ontology/term");
  assert.equal(request.searchParams.get("ontology_uri"), ontologyUri);
  assert.equal(request.searchParams.get("term_uri"), termUri);
});

test("saving a class sends only editable fields and the revision, preserving unchanged schema arrays", async () => {
  let saved = 0;
  const patches: { url: string; payload: unknown }[] = [];
  const returned = { ...current, revision: `sha256:${"b".repeat(64)}`, changed: true, term: { ...current.term, label: "已保存采购申请", comment: "服务端确认的完整定义。" } };
  globalThis.fetch = async (input, init) => {
    if (init?.method === "PATCH") {
      patches.push({ url: String(input), payload: JSON.parse(String(init.body)) });
      return response(returned);
    }
    return response(current);
  };
  const view = render(<OntologyTermDetails ontologyUri={ontologyUri} termUri={termUri} onSaved={() => { saved += 1; }} />);
  fireEvent.click(await view.findByRole("button", { name: "Edit class" }));
  assert.equal(view.getByRole<HTMLInputElement>("textbox", { name: "Label" }).value, current.term.label);
  assert.equal(view.getByRole<HTMLTextAreaElement>("textbox", { name: "Definition and source notes" }).value, current.term.comment);
  assert.equal(view.getByRole<HTMLTextAreaElement>("textbox", { name: "Parent class IRIs" }).value, current.term.parents.join("\n"));
  fireEvent.change(view.getByRole("textbox", { name: "Label" }), { target: { value: "已保存采购申请" } });
  fireEvent.change(view.getByRole("textbox", { name: "Definition and source notes" }), { target: { value: "提交的完整定义。" } });
  for (const field of view.container.querySelectorAll<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>("input, textarea, select")) {
    if (field.value === termUri || field.value === "owl:Class") assert.ok(field.hasAttribute("readonly") || field.disabled, "identity and type must be immutable");
  }
  fireEvent.click(view.getByRole("button", { name: "Save changes" }));
  await waitFor(() => assert.equal(saved, 1));
  assert.equal(patches.length, 1);
  assert.deepEqual(patches[0].payload, {
    expected_revision: revision,
    label: "已保存采购申请",
    comment: "提交的完整定义。",
    parents: current.term.parents,
    domain: [],
    range: [],
  });
  const request = new URL(patches[0].url, "http://localhost");
  assert.equal(request.pathname, "/api/ontology/term");
  assert.equal(request.searchParams.get("ontology_uri"), ontologyUri);
  assert.equal(request.searchParams.get("term_uri"), termUri);
  assert.ok(displayed(view, returned.term.comment), "the saved details must use the server response");
  assert.ok(displayed(view, returned.term.label));
  assert.equal(view.queryByRole("button", { name: "Save changes" }), null);
  fireEvent.click(view.getByRole("button", { name: "Edit class" }));
  assert.equal(view.getByRole<HTMLTextAreaElement>("textbox", { name: "Definition and source notes" }).value, returned.term.comment);
  fireEvent.change(view.getByRole("textbox", { name: "Label" }), { target: { value: "再次保存采购申请" } });
  fireEvent.click(view.getByRole("button", { name: "Save changes" }));
  await waitFor(() => assert.equal(saved, 2));
  assert.deepEqual(patches[1].payload, {
    expected_revision: returned.revision,
    label: "再次保存采购申请",
    comment: returned.term.comment,
    parents: returned.term.parents,
    domain: returned.term.domain,
    range: returned.term.range,
  });
});

test("property editing keeps its type and parent array while encoding domain and range as IRI lists", async () => {
  for (const type of ["owl:ObjectProperty", "owl:DatatypeProperty"]) {
    const propertyUri = `${ontologyUri}requiresApproval`;
    const property = { ...current, term_uri: propertyUri, term: { ...current.term, id: propertyUri, type, label: "所需审批", parents: [], domain: [termUri], range: [type === "owl:DatatypeProperty" ? "http://www.w3.org/2001/XMLSchema#string" : `${ontologyUri}Role`] } };
    const expectedDomain = [`${ontologyUri}ExpenseRequest`, `${ontologyUri}ApprovalRequest`];
    const expectedRange = type === "owl:DatatypeProperty" ? ["http://www.w3.org/2001/XMLSchema#decimal"] : [`${ontologyUri}Approver`];
    let body: unknown;
    let saved = 0;
    globalThis.fetch = async (_input, init) => {
      if (init?.method === "PATCH") {
        body = JSON.parse(String(init.body));
        return response({ ...property, revision: `sha256:${"b".repeat(64)}`, changed: true, term: { ...property.term, domain: expectedDomain, range: expectedRange } });
      }
      return response(property);
    };
    const view = render(<OntologyTermDetails ontologyUri={ontologyUri} termUri={propertyUri} onSaved={() => { saved += 1; }} />);
    fireEvent.click(await view.findByRole("button", { name: "Edit property" }));
    assert.equal(view.queryByRole("textbox", { name: "Parent class IRIs" }), null);
    assert.equal(view.getByRole<HTMLTextAreaElement>("textbox", { name: "Domain class IRIs" }).value, termUri);
    assert.equal(view.getByRole<HTMLTextAreaElement>("textbox", { name: "Range IRIs" }).value, property.term.range.join("\n"));
    fireEvent.change(view.getByRole("textbox", { name: "Domain class IRIs" }), { target: { value: ` \n${expectedDomain.join("\n")}\n` } });
    fireEvent.change(view.getByRole("textbox", { name: "Range IRIs" }), { target: { value: expectedRange.join("\n") } });
    fireEvent.click(view.getByRole("button", { name: "Save changes" }));
    await waitFor(() => assert.equal(saved, 1));
    assert.deepEqual(body, { expected_revision: revision, label: property.term.label, comment: property.term.comment, parents: [], domain: expectedDomain, range: expectedRange });
    assert.ok(displayed(view, type));
    cleanup();
  }
});

test("cancelling an edit discards the draft without mutating the service", async () => {
  const methods: string[] = [];
  globalThis.fetch = async (_input, init) => { methods.push(init?.method || "GET"); return response(current); };
  const view = render(<OntologyTermDetails ontologyUri={ontologyUri} termUri={termUri} onSaved={() => assert.fail("cancel must not save")} />);
  fireEvent.click(await view.findByRole("button", { name: "Edit class" }));
  fireEvent.change(view.getByRole("textbox", { name: "Label" }), { target: { value: "不应保存的名称" } });
  fireEvent.change(view.getByRole("textbox", { name: "Parent class IRIs" }), { target: { value: "" } });
  fireEvent.click(view.getByRole("button", { name: "Cancel editing" }));
  assert.ok(displayed(view, current.term.label));
  assert.equal(displayed(view, "不应保存的名称"), false);
  assert.equal(view.queryByRole("button", { name: "Save changes" }), null);
  fireEvent.click(view.getByRole("button", { name: "Edit class" }));
  assert.equal(view.getByRole<HTMLInputElement>("textbox", { name: "Label" }).value, current.term.label);
  assert.equal(view.getByRole<HTMLTextAreaElement>("textbox", { name: "Parent class IRIs" }).value, current.term.parents.join("\n"));
  assert.deepEqual(methods, ["GET"]);
});

test("conflicts and save errors retain their reason without reporting success and allow reloading the current definition", async () => {
  for (const status of [409, 422, 500]) {
    let saved = 0;
    let reads = 0;
    const reason = status === 409 ? "Definition changed in another editor; reload before saving." : `Term could not be saved (${status}).`;
    const fresh = { ...current, revision: `sha256:${"c".repeat(64)}`, term: { ...current.term, label: "另一会话内编辑的当前名称" } };
    globalThis.fetch = async (_input, init) => {
      if (init?.method === "PATCH") return response({ detail: status === 409 ? { code: "ontology_term_revision_conflict", message: reason, current_revision: fresh.revision } : reason }, status);
      reads += 1;
      return response(reads > 1 ? fresh : current);
    };
    const view = render(<OntologyTermDetails ontologyUri={ontologyUri} termUri={termUri} onSaved={() => { saved += 1; }} />);
    fireEvent.click(await view.findByRole("button", { name: "Edit class" }));
    fireEvent.change(view.getByRole("textbox", { name: "Label" }), { target: { value: "本地未保存草稿" } });
    fireEvent.click(view.getByRole("button", { name: "Save changes" }));
    const alert = await view.findByRole("alert");
    assert.ok((alert.textContent ?? "").includes(reason));
    assert.equal(saved, 0);
    assert.equal(view.getByRole<HTMLInputElement>("textbox", { name: "Label" }).value, "本地未保存草稿");
    fireEvent.click(view.getByRole("button", { name: "Reload current definition" }));
    await waitFor(() => assert.ok(displayed(view, fresh.term.label)));
    assert.equal(view.queryByRole("alert"), null);
    assert.equal(view.queryByRole("button", { name: "Save changes" }), null);
    assert.equal(saved, 0);
    assert.equal(reads, 2);
    cleanup();
  }
});

test("a missing term and a failed request expose their reason with a retry and no editable stale definition", async () => {
  for (const failure of ["missing", "network"]) {
    let reads = 0;
    const reason = failure === "missing" ? "Ontology term not found." : "The request could not reach the service.";
    globalThis.fetch = async () => {
      reads += 1;
      if (reads > 1) return response(current);
      if (failure === "network") throw new Error(reason);
      return response({ detail: reason }, 404);
    };
    const view = render(<OntologyTermDetails ontologyUri={ontologyUri} termUri={termUri} onSaved={() => assert.fail("failed reads must not save")} />);
    const alert = await view.findByRole("alert");
    assert.ok((alert.textContent ?? "").includes(reason));
    assert.equal(view.queryByRole("button", { name: "Edit class" }), null);
    fireEvent.click(view.getByRole("button", { name: "Reload current definition" }));
    await view.findByRole("button", { name: "Edit class" });
    assert.ok(displayed(view, current.term.label));
    cleanup();
  }
});

test("switching terms aborts a pending read and ignores its late response", async () => {
  let finishOld: ((value: Response) => void) | undefined;
  let oldSignal: AbortSignal | null | undefined;
  const oldResponse = new Promise<Response>((resolve) => { finishOld = resolve; });
  const nextUri = `${ontologyUri}ApprovalRequest`;
  const next = { ...current, term_uri: nextUri, term: { ...current.term, id: nextUri, label: "审批申请", parents: [] } };
  globalThis.fetch = async (input, init) => {
    if (new URL(String(input), "http://localhost").searchParams.get("term_uri") === termUri) {
      oldSignal = init?.signal;
      return oldResponse;
    }
    return response(next);
  };
  const view = render(<OntologyTermDetails ontologyUri={ontologyUri} termUri={termUri} onSaved={() => assert.fail("reads must not save")} />);
  view.rerender(<OntologyTermDetails ontologyUri={ontologyUri} termUri={nextUri} onSaved={() => assert.fail("reads must not save")} />);
  assert.equal(oldSignal?.aborted, true);
  await view.findByRole("button", { name: "Edit class" });
  assert.ok(displayed(view, next.term.label));
  await act(async () => { finishOld?.(response(current)); await oldResponse; });
  assert.equal(displayed(view, current.term.label), false);
  assert.ok(displayed(view, next.term.label));
});

test("switching ontology identity discards an open edit even when the selected term URI is unchanged", async () => {
  const nextOntology = "https://example.test/other-ontology/";
  globalThis.fetch = async (input) => {
    const owner = new URL(String(input), "http://localhost").searchParams.get("ontology_uri");
    return response({ ...current, ontology_uri: owner, term: { ...current.term, label: owner === ontologyUri ? current.term.label : "新本体中的定义" } });
  };
  const view = render(<OntologyTermDetails ontologyUri={ontologyUri} termUri={termUri} onSaved={() => assert.fail("selection must not save")} />);
  fireEvent.click(await view.findByRole("button", { name: "Edit class" }));
  fireEvent.change(view.getByRole("textbox", { name: "Label" }), { target: { value: "原本体的草稿" } });
  view.rerender(<OntologyTermDetails ontologyUri={nextOntology} termUri={termUri} onSaved={() => assert.fail("selection must not save")} />);
  await view.findByRole("button", { name: "Edit class" });
  assert.ok(displayed(view, "新本体中的定义"));
  assert.equal(displayed(view, "原本体的草稿"), false);
  assert.equal(view.queryByRole("button", { name: "Save changes" }), null);
});

test("a save completing after term selection changes cannot repaint the old term or reopen its editor", async () => {
  let finishSave: ((value: Response) => void) | undefined;
  const saveResponse = new Promise<Response>((resolve) => { finishSave = resolve; });
  const nextUri = `${ontologyUri}ApprovalRequest`;
  const next = { ...current, term_uri: nextUri, term: { ...current.term, id: nextUri, label: "当前审批申请" } };
  let mutations = 0;
  let staleSaveCallbacks = 0;
  globalThis.fetch = async (input, init) => {
    if (init?.method === "PATCH") { mutations += 1; return saveResponse; }
    return response(new URL(String(input), "http://localhost").searchParams.get("term_uri") === termUri ? current : next);
  };
  const view = render(<OntologyTermDetails ontologyUri={ontologyUri} termUri={termUri} onSaved={() => { staleSaveCallbacks += 1; }} />);
  fireEvent.click(await view.findByRole("button", { name: "Edit class" }));
  fireEvent.change(view.getByRole("textbox", { name: "Label" }), { target: { value: "旧节点已保存名称" } });
  fireEvent.click(view.getByRole("button", { name: "Save changes" }));
  await waitFor(() => assert.equal(mutations, 1));
  view.rerender(<OntologyTermDetails ontologyUri={ontologyUri} termUri={nextUri} onSaved={() => undefined} />);
  await view.findByRole("button", { name: "Edit class" });
  await act(async () => {
    finishSave?.(response({ ...current, revision: `sha256:${"b".repeat(64)}`, changed: true, term: { ...current.term, label: "旧节点已保存名称" } }));
    await saveResponse;
  });
  assert.ok(displayed(view, next.term.label));
  assert.equal(displayed(view, "旧节点已保存名称"), false);
  assert.equal(view.queryByRole("button", { name: "Save changes" }), null);
  assert.equal(staleSaveCallbacks, 0, "an old save callback must not reset the new selection or its draft");
});

test("saving unchanged values accepts the no-op snapshot without changing its revision or showing an error", async () => {
  let saved = 0;
  const patches: unknown[] = [];
  globalThis.fetch = async (_input, init) => {
    if (init?.method === "PATCH") {
      patches.push(JSON.parse(String(init.body)));
      return response({ ...current, changed: false });
    }
    return response(current);
  };
  const view = render(<OntologyTermDetails ontologyUri={ontologyUri} termUri={termUri} onSaved={() => { saved += 1; }} />);
  fireEvent.click(await view.findByRole("button", { name: "Edit class" }));
  fireEvent.click(view.getByRole("button", { name: "Save changes" }));
  await waitFor(() => assert.equal(saved, 1));
  assert.equal(view.queryByRole("alert"), null);
  assert.ok(displayed(view, current.term.label));
  assert.ok(displayed(view, current.term.comment));
  assert.deepEqual(patches, [{ expected_revision: revision, label: current.term.label, comment: current.term.comment, parents: current.term.parents, domain: [], range: [] }]);
});

test("mismatched or malformed successful responses never become an editable definition", async () => {
  const malformed = [
    { ...current, ontology_uri: "https://example.test/wrong/" },
    { ...current, term_uri: `${ontologyUri}AnotherTerm` },
    { ...current, term: { ...current.term, id: `${ontologyUri}AnotherTerm` } },
    { ...current, term: { ...current.term, type: "ProcessRule" } },
    { ...current, term: { ...current.term, parents: [null] } },
    { ...current, revision: "" },
    { ...current, scope: "published" },
    null,
  ];
  for (const payload of malformed) {
    globalThis.fetch = async () => response(payload);
    const view = render(<OntologyTermDetails ontologyUri={ontologyUri} termUri={termUri} onSaved={() => assert.fail("invalid responses must not save")} />);
    const alert = await view.findByRole("alert");
    assert.match(alert.textContent ?? "", /mismatched or invalid response/);
    assert.equal(view.queryByRole("button", { name: "Edit class" }), null);
    assert.equal(view.queryByRole("button", { name: "Edit property" }), null);
    assert.ok(view.getByRole("button", { name: "Reload current definition" }));
    cleanup();
  }
});

test("untrusted labels, definitions and errors remain literal text in both viewing and editing", async () => {
  const label = '<img src=x onerror="window.termBad=1">';
  const comment = '<script>window.termBad=1</script>\n逐字定义😀';
  const malicious = { ...current, term: { ...current.term, label, comment } };
  globalThis.fetch = async (_input, init) => init?.method === "PATCH" ? response({ detail: label }, 422) : response(malicious);
  const view = render(<OntologyTermDetails ontologyUri={ontologyUri} termUri={termUri} onSaved={() => assert.fail("failed saves must not succeed")} />);
  fireEvent.click(await view.findByRole("button", { name: "Edit class" }));
  assert.equal(view.getByRole<HTMLInputElement>("textbox", { name: "Label" }).value, label);
  assert.equal(view.getByRole<HTMLTextAreaElement>("textbox", { name: "Definition and source notes" }).value, comment);
  fireEvent.change(view.getByRole("textbox", { name: "Definition and source notes" }), { target: { value: `${comment}\n补充定义` } });
  fireEvent.click(view.getByRole("button", { name: "Save changes" }));
  const alert = await view.findByRole("alert");
  assert.ok((alert.textContent ?? "").includes(label));
  assert.equal(view.container.querySelector("img"), null);
  assert.equal(view.container.querySelector("script"), null);
});

for (const side of ["domain", "range"] as const) {
  test(`a union ${side} stays read-only while the other side and label remain editable`, async () => {
    const uri = `${ontologyUri}name`;
    const original = {
      ...current, term_uri: uri,
      term: { ...current.term, id: uri, type: "owl:ObjectProperty", parents: [], domain: [`${ontologyUri}NamedDomain`], range: [`${ontologyUri}NamedRange`], [`${side}_expressions`]: [{ kind: "unionOf", members: [`${ontologyUri}Role`, `${ontologyUri}Activity`] }] },
    };
    const editable = side === "domain" ? "range" : "domain";
    const editableLabel = editable === "domain" ? "Domain class IRIs" : "Range IRIs";
    const lockedLabel = side === "domain" ? "Domain class IRIs" : "Range IRIs";
    let patch: Record<string, unknown> | undefined;
    globalThis.fetch = async (_input, init) => {
      if (init?.method === "PATCH") {
        patch = JSON.parse(String(init.body));
        return response({ ...original, term: { ...original.term, label: "新名称", [editable]: [`${ontologyUri}Changed`] } });
      }
      return response(original);
    };
    const view = render(<OntologyTermDetails ontologyUri={ontologyUri} termUri={uri} onSaved={() => undefined} />);
    fireEvent.click(await view.findByRole("button", { name: "Edit property" }));
    assert.match(view.container.textContent ?? "", /read.only/i);
    assert.match(view.container.textContent ?? "", new RegExp(`${original.term[side][0]} AND \\(${ontologyUri}Role OR ${ontologyUri}Activity\\)`));
    assert.equal(view.queryByRole("textbox", { name: lockedLabel }), null);
    assert.ok(view.getByRole("textbox", { name: editableLabel }));
    fireEvent.change(view.getByRole("textbox", { name: "Label" }), { target: { value: "新名称" } });
    fireEvent.change(view.getByRole("textbox", { name: editableLabel }), { target: { value: `${ontologyUri}Changed` } });
    fireEvent.click(view.getByRole("button", { name: "Save changes" }));
    await waitFor(() => assert.ok(patch));
    assert.deepEqual(patch, { expected_revision: revision, label: "新名称", comment: original.term.comment, parents: [], domain: original.term.domain, range: original.term.range, [editable]: [`${ontologyUri}Changed`] });
    assert.equal(`${side}_expressions` in patch!, false);
    await view.findByRole("button", { name: "Edit property" });
    assert.match(view.container.textContent ?? "", /Role OR .*Activity/);
  });
}

test("opaque expressions remain explicit and read-only without interpreting or rendering their RDF", async () => {
  const uri = `${ontologyUri}opaque`;
  const opaque = '<script>window.expressionBad=1</script>';
  const term = { ...current, term_uri: uri, term: { ...current.term, id: uri, type: "owl:ObjectProperty", parents: [], domain_expressions: [{ kind: "unsupported", rdf: opaque, root: "_:anonymous", rdf_format: "nt", reason: "Nested expression" }], range_expressions: [{ kind: "unionOf", members: [`${ontologyUri}Role`, `${ontologyUri}Activity`] }] } };
  globalThis.fetch = async () => response(term);
  const view = render(<OntologyTermDetails ontologyUri={ontologyUri} termUri={uri} onSaved={() => undefined} />);
  fireEvent.click(await view.findByRole("button", { name: "Edit property" }));
  assert.match(view.container.textContent ?? "", /Unsupported OWL expression/);
  assert.equal(view.queryByRole("textbox", { name: "Domain class IRIs" }), null);
  assert.equal(view.queryByRole("textbox", { name: "Range IRIs" }), null);
  assert.ok(view.getByRole("textbox", { name: "Label" }));
  assert.ok(view.getByRole("textbox", { name: "Definition and source notes" }));
  assert.equal(view.container.querySelector("script"), null);
  assert.equal(view.container.textContent?.includes(opaque), false);
});

test("malformed optional class expressions cannot become an editable term", async () => {
  for (const expression of [null, { kind: "unionOf", members: [null] }, { kind: "unionOf", members: [] }, { kind: "unionOf", members: "Role" }, { kind: "invented", members: [termUri] }]) {
    globalThis.fetch = async () => response({ ...current, term: { ...current.term, domain_expressions: [expression] } });
    const view = render(<OntologyTermDetails ontologyUri={ontologyUri} termUri={termUri} onSaved={() => assert.fail("invalid expressions must not save")} />);
    assert.match((await view.findByRole("alert")).textContent ?? "", /mismatched or invalid response/);
    assert.equal(view.queryByRole("button", { name: "Edit class" }), null);
    cleanup();
  }
});

test("switching from an expression property clears its read-only state for a legacy simple property", async () => {
  const unionUri = `${ontologyUri}unionProperty`;
  const simpleUri = `${ontologyUri}simpleProperty`;
  globalThis.fetch = async (input) => {
    const id = new URL(String(input), "http://localhost").searchParams.get("term_uri")!;
    return response({ ...current, term_uri: id, term: { ...current.term, id, type: "owl:ObjectProperty", parents: [], ...(id === unionUri ? { domain_expressions: [{ kind: "unionOf", members: [`${ontologyUri}Role`, `${ontologyUri}Activity`] }] } : {}) } });
  };
  const view = render(<OntologyTermDetails ontologyUri={ontologyUri} termUri={unionUri} onSaved={() => undefined} />);
  fireEvent.click(await view.findByRole("button", { name: "Edit property" }));
  assert.equal(view.queryByRole("textbox", { name: "Domain class IRIs" }), null);
  view.rerender(<OntologyTermDetails ontologyUri={ontologyUri} termUri={simpleUri} onSaved={() => undefined} />);
  fireEvent.click(await view.findByRole("button", { name: "Edit property" }));
  assert.ok(view.getByRole("textbox", { name: "Domain class IRIs" }));
  assert.equal(view.container.textContent?.includes("Role OR"), false);
});
