import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { JSDOM } from "jsdom";
import { graph } from "../src/store/graphStore.ts";
import { GraphInspectorPanel } from "../src/workspaces/GraphWorkspace/GraphInspectorPanel.tsx";

Object.assign(globalThis, { React });

test("the real inspector shows the derived approval title while its Markdown content stays original", () => {
  graph.clear();
  try {
    graph.addNode("rule", { label: "Rule", content: "Rule", nodeType: "ProcessRule", properties: { source_clause_id: "C007" } });
    graph.addNode("group", { label: "审批组 (all)", content: "审批组 (all)", nodeType: "ApprovalGroup", properties: { mode: "all" } });
    graph.addDirectedEdgeWithKey("approval", "rule", "group", { edgeType: "hasApprovalGroup" });
    const html = renderToStaticMarkup(<GraphInspectorPanel
      nodeId="group" predictions={[]} predictionType="" pathTargetId="" pathResult={null}
      onPredictionTypeChange={() => {}} onRunPredictions={() => {}}
      onPathTargetChange={() => {}} onTracePath={() => {}} onDownloadProvenance={() => {}}
    />);
    const document = new JSDOM(html).window.document;
    assert.equal(document.querySelector("h3")?.textContent, "审批组 (all) [C007]");
    const content = [...document.querySelectorAll("details")].find(details => details.querySelector("summary")?.textContent?.includes("Content"));
    assert.ok(content?.textContent?.includes("审批组 (all)"));
    assert.equal(content?.textContent?.includes("[C007]"), false);
    assert.equal(graph.getNodeAttribute("group", "label"), "审批组 (all)");
  } finally {
    graph.clear();
  }
});
