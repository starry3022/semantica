import assert from "node:assert/strict";
import test from "node:test";
import React, { useEffect, useState } from "react";
import { JSDOM } from "jsdom";
import { parseWorkspaceRoute, workspaceSearch, useWorkspaceNavigation } from "../src/workspaceNavigation";
import { RetainedWorkspace } from "../src/RetainedWorkspace";
import { applyEntitySelection, readOntologyUrlState, writeTab } from "../src/workspaces/OntologyWorkspace/ontologyUrlState";

(globalThis as typeof globalThis & { React: typeof React }).React = React;
const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost" });
Object.assign(globalThis, { window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement, Node: dom.window.Node });
Object.defineProperty(globalThis, "navigator", { configurable: true, value: dom.window.navigator });
const { act, cleanup, fireEvent, render, waitFor } = await import("@testing-library/react");
test.afterEach(cleanup);

test("workspace routes accept legacy ontology links and reject unknown workspaces", () => {
  assert.equal(parseWorkspaceRoute(""), "welcome");
  assert.equal(parseWorkspaceRoute("?workspace=explore"), "explore");
  assert.equal(parseWorkspaceRoute(applyEntitySelection("", "urn:Class")), "ontology-hub");
  assert.equal(parseWorkspaceRoute("?workspace=unknown"), "welcome");
  assert.equal(parseWorkspaceRoute(applyEntitySelection("?workspace=explore", "urn:Class")), "explore");
});

test("a class route preserves exact Unicode/hash IRIs and unrelated URL parameters", () => {
  const uri = "https://example.org/业务#采购😀/&?=";
  const hub = workspaceSearch("?keep=1", "ontology-hub", uri);
  assert.equal(parseWorkspaceRoute(hub), "ontology-hub");
  assert.deepEqual(readOntologyUrlState(hub), { tab: "editor", entityUri: uri });
  const explorer = workspaceSearch(hub, "explore");
  assert.deepEqual(readOntologyUrlState(explorer), { tab: undefined, entityUri: undefined });
  assert.equal(new URLSearchParams(explorer).get("keep"), "1");
});

test("retained workspaces mount lazily and keep draft, selection and DOM identity while inert", () => {
  let mounts = 0;
  let unmounts = 0;
  function Explorer() {
    const [draft, setDraft] = useState("original");
    useEffect(() => { mounts++; return () => { unmounts++; }; }, []);
    return <textarea aria-label="Draft" value={draft} onChange={event => setDraft(event.target.value)} />;
  }
  const view = render(<RetainedWorkspace active={false}><Explorer /></RetainedWorkspace>);
  assert.equal(mounts, 0);
  view.rerender(<RetainedWorkspace active><Explorer /></RetainedWorkspace>);
  const editor = view.getByRole("textbox", { name: "Draft" });
  fireEvent.change(editor, { target: { value: "unsaved selection" } });
  view.rerender(<RetainedWorkspace active={false}><Explorer /></RetainedWorkspace>);
  assert.equal(view.queryByRole("textbox", { name: "Draft" }), null);
  assert.ok(editor.closest("[inert]"));
  assert.equal(editor.parentElement?.style.visibility, "hidden");
  assert.equal(editor.parentElement?.style.opacity, "0", "timeline descendants can override inherited visibility, so the whole layer must stop painting");
  assert.notEqual(editor.parentElement?.style.display, "none");
  assert.equal(unmounts, 0);
  view.rerender(<RetainedWorkspace active><Explorer /></RetainedWorkspace>);
  assert.equal(view.getByRole("textbox", { name: "Draft" }), editor);
  assert.equal((editor as HTMLTextAreaElement).value, "unsaved selection");
  assert.equal(mounts, 1);
});

test("native history returns to Explorer and forwards to the exact class without reloading", async () => {
  window.history.replaceState({ hostState: "keep" }, "", "/?keep=1#section");
  function Navigation() {
    const { route, navigate, returnToExplorer } = useWorkspaceNavigation();
    return <>
      <output data-testid="route">{route.workspace}</output>
      <output data-testid="token">{route.key}</output>
      <button onClick={() => navigate("explore")}>Explore</button>
      <button onClick={() => navigate("ontology-hub", "urn:ClassA")}>Class A</button>
      <button onClick={() => navigate("ontology-hub", "urn:ClassB")}>Class B</button>
      {route.canReturnToExplorer && <button onClick={returnToExplorer}>Back to Explorer</button>}
    </>;
  }
  const view = render(<Navigation />);
  const initialLength = window.history.length;
  fireEvent.click(view.getByText("Explore"));
  assert.equal(window.history.length, initialLength + 1);
  fireEvent.click(view.getByText("Explore"));
  assert.equal(window.history.length, initialLength + 1);
  fireEvent.click(view.getByText("Class A"));
  assert.equal(window.history.length, initialLength + 2);
  assert.equal(window.location.hash, "#section");
  assert.equal(window.history.state.hostState, "keep");
  act(() => writeTab("editor"));
  assert.equal(window.history.state.hostState, "keep");
  fireEvent.click(view.getByText("Back to Explorer"));
  await waitFor(() => assert.equal(view.getByTestId("route").textContent, "explore"));
  assert.equal(readOntologyUrlState().entityUri, undefined);
  act(() => window.history.forward());
  await waitFor(() => assert.equal(view.getByTestId("route").textContent, "ontology-hub"));
  assert.equal(readOntologyUrlState().entityUri, "urn:ClassA");
  const firstToken = view.getByTestId("token").textContent;
  fireEvent.click(view.getByText("Class B"));
  assert.equal(readOntologyUrlState().entityUri, "urn:ClassB");
  assert.notEqual(view.getByTestId("token").textContent, firstToken);
  act(() => window.history.back());
  await waitFor(() => assert.equal(readOntologyUrlState().entityUri, "urn:ClassA"));
  assert.equal(view.getByTestId("route").textContent, "ontology-hub");
});
