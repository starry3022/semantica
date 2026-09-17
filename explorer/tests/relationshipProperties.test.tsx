import assert from "node:assert/strict";
import test from "node:test";
import { JSDOM } from "jsdom";
import React from "react";

(globalThis as typeof globalThis & { React: typeof React }).React = React;
const dom = new JSDOM("<!doctype html><html><body></body></html>");
Object.assign(globalThis, { window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement });
Object.defineProperty(globalThis, "navigator", { configurable: true, value: dom.window.navigator });
const { cleanup, fireEvent, render, within } = await import("@testing-library/react");
const { RelationshipProperties } = await import("../src/workspaces/GraphWorkspace/RelationshipProperties.tsx");

test.afterEach(cleanup);

const properties = {
  source_file: "source.txt",
  source_sha256: "a".repeat(64),
  source_notebook: "extraction.ipynb",
  source_variable: "text",
  review_status: "unreviewed",
  fact_status: "candidate",
  context: "Apple was founded by Steve Jobs.\n逐字引文😀\n",
  native_metadata: { provider: "local", flags: ["unverified", null], score: 0 },
  confidence: 0,
};

test("every property remains readable beyond the first four with stable source, context, and status sections", () => {
  const view = render(<RelationshipProperties properties={properties} />);
  fireEvent.click(view.getByLabelText("View all relationship properties"));
  assert.equal(view.container.querySelectorAll("dt").length, Object.keys(properties).length);
  assert.ok(view.getByText(/Properties · 9/));
  assert.ok(within(view.getByRole("region", { name: "Source properties" })).getByText("source.txt"));
  const context = view.getByRole("region", { name: "Context & evidence properties" });
  assert.equal(context.querySelector("dd")?.textContent, properties.context);
  const status = view.getByRole("region", { name: "Review & status properties" });
  assert.ok(within(status).getByText("unreviewed"));
  assert.ok(within(status).getByText("candidate"));
});

test("shuffled input preserves all values and the same section and field order", () => {
  const view = render(<RelationshipProperties properties={properties} />);
  const before = view.container.textContent;
  view.rerender(<RelationshipProperties properties={Object.fromEntries(Object.entries(properties).reverse())} />);
  assert.equal(view.container.textContent, before);
});

test("long multiline text and nested JSON retain complete content and readable formatting", () => {
  const context = "首行😀\n" + "完整原文，不应截断。".repeat(500) + "\n最后一行";
  const view = render(<RelationshipProperties properties={{ context, nested: properties.native_metadata }} />);
  fireEvent.click(view.getByLabelText("View all relationship properties"));
  const values = [...view.container.querySelectorAll("dd")].map((element) => element.textContent);
  assert.deepEqual(values, [context, JSON.stringify(properties.native_metadata, null, 2)]);
  for (const element of view.container.querySelectorAll("dd")) {
    assert.equal(element.style.whiteSpace, "pre-wrap");
    assert.equal(element.style.overflowWrap, "anywhere");
  }
  const scrollArea = view.getByRole("region", { name: "All relationship properties" });
  assert.equal(scrollArea.tabIndex, 0, "keyboard users can scroll the entire property list");
});

test("the disclosure preserves graph space and opens or collapses the complete list", () => {
  const view = render(<RelationshipProperties properties={properties} />);
  const disclosure = view.container.querySelector("details")!;
  assert.equal(disclosure.open, false);
  fireEvent.click(view.getByLabelText("View all relationship properties"));
  assert.equal(disclosure.open, true);
  assert.equal(view.container.querySelectorAll("dt").length, Object.keys(properties).length);
  fireEvent.click(view.getByLabelText("View all relationship properties"));
  assert.equal(disclosure.open, false);
});

test("null, empty text, false, zero, empty arrays and objects stay distinguishable", () => {
  const view = render(<RelationshipProperties properties={{ a: null, b: "", c: false, d: 0, e: [], f: {} }} />);
  assert.deepEqual([...view.container.querySelectorAll("dd")].map((element) => element.textContent), ["null", '""', "false", "0", "[]", "{}"]);
});

test("property keys and values render HTML as literal text", () => {
  const html = '<img src=x onerror="window.executed=true"><script>window.executed=true</script>';
  const view = render(<RelationshipProperties properties={{ [html]: html, nested: { html } }} />);
  assert.equal(view.container.querySelector("img,script,iframe"), null);
  assert.equal(view.container.querySelector("dt")?.textContent, html);
  assert.equal(view.container.querySelector("dd")?.textContent, html);
});

test("switching relationships removes previous values and old graphs have an explicit empty state", () => {
  const view = render(<RelationshipProperties properties={properties} />);
  view.rerender(<RelationshipProperties properties={{ context: "第二条关系" }} />);
  assert.equal(view.container.querySelectorAll("dt").length, 1);
  assert.equal(view.queryByText("source.txt"), null);
  assert.equal(view.queryByText("unreviewed"), null);
  assert.ok(view.getByText("第二条关系"));
  view.rerender(<RelationshipProperties properties={{}} />);
  assert.ok(view.getByText("No properties recorded for this relationship."));
  assert.equal(view.container.querySelectorAll("dt").length, 0);
});
