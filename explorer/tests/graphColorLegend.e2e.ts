import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { setTimeout as delay } from "node:timers/promises";
import test from "node:test";
import { chromium, type Page } from "playwright";

const BASE_URL = "http://127.0.0.1:4175";
const initialNodes = [
  { id: "alice", type: "Person", content: "Alice", properties: {} },
  { id: "bob", type: "Person", content: "Bob", properties: {} },
  { id: "acme", type: "Organization", content: "Acme", properties: {} },
  { id: "london", type: "Location", content: "London", properties: {} },
  { id: "research", type: "Project", content: "Research", properties: {} },
  { id: "report", type: "Document", content: "Report", properties: {} },
];
const edges = [
  ["alice", "acme", "WORKS_AT"], ["bob", "acme", "WORKS_AT"],
  ["acme", "london", "LOCATED_IN"], ["alice", "research", "LEADS"],
  ["bob", "report", "AUTHORED"], ["report", "research", "DESCRIBES"],
].map(([source, target, type], i) => ({
  id: `edge_${i}`, familyId: `edge_${i}`, source, target, type, weight: 1, properties: {},
}));

async function assertLegendMatchesGraph(page: Page, nodeIds?: string[]) {
  const result = await page.evaluate(async (includedNodeIds) => {
    const storePath = "/src/store/graphStore.ts";
    const { graph } = await import(storePath);
    const colors: Record<string, string> = {};
    graph.forEachNode((id: string, attrs: { semanticGroup: string; baseColor: string }) => {
      if (includedNodeIds && !includedNodeIds.includes(id)) return;
      const hex = attrs.baseColor.replace("#", "");
      colors[attrs.semanticGroup] = `rgb(${[0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16)).join(", ")})`;
    });
    const items = [...document.querySelectorAll(".explore-color-legend-item")].map((item) => ({
      group: item.querySelector(".explore-color-legend-name")?.textContent,
      color: getComputedStyle(item.querySelector(".explore-color-legend-mark")!).backgroundColor,
    }));
    return { colors, items };
  }, nodeIds);
  assert.equal(result.items.length, Object.keys(result.colors).length);
  for (const item of result.items) {
    assert.equal(item.color, result.colors[item.group!], `Swatch for ${item.group} must match the loaded canvas color`);
  }
}

test("visible legend follows loaded data, reloads, focused views, and distance mode", async (t) => {
  const server = spawn("npm", ["run", "dev", "--", "--host", "127.0.0.1", "--port", "4175", "--strictPort"], { stdio: "ignore" });
  t.after(() => { server.kill(); });
  let ready = false;
  for (let i = 0; i < 100; i += 1) {
    try { if ((await fetch(BASE_URL)).ok) { ready = true; break; } } catch { /* Starting Vite. */ }
    await delay(100);
  }
  assert.ok(ready, "Vite must start");
  const browser = await chromium.launch({
    headless: true,
    executablePath:
      process.env.CHROMIUM_PATH || (existsSync("/usr/bin/chromium") ? "/usr/bin/chromium" : undefined),
  });
  t.after(() => browser.close());
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.setDefaultTimeout(10_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => { if (message.type() === "error") errors.push(message.text()); });
  let nodes = initialNodes;
  await page.routeWebSocket("**/ws/graph-updates", () => {});
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let json: unknown = {};
    if (path === "/api/info") json = { capabilities: { agent_memory: false } };
    if (path === "/api/graph/stats") json = { node_count: nodes.length, edge_count: edges.length };
    if (path === "/api/graph/nodes") json = { nodes, total: nodes.length, next_cursor: null };
    if (path === "/api/graph/edges") json = { edges, total: edges.length, next_cursor: null };
    if (path === "/api/temporal/bounds") json = { min: null, max: null };
    if (path === "/api/temporal/snapshot") json = { active_node_ids: nodes.map((n) => n.id), active_node_count: nodes.length };
    if (path === "/api/graph/search") json = { results: [{ node: nodes[0], score: 1 }] };
    await route.fulfill({ json });
  });
  await page.goto(BASE_URL);
  await page.getByRole("button", { name: "Open Semantica Explorer" }).click();
  const legend = page.getByRole("group", { name: "Node colors" });
  await legend.waitFor();
  await page.locator("canvas").first().waitFor({ state: "visible" });
  for (const viewport of [{ width: 1440, height: 900 }, { width: 1280, height: 800 }]) {
    await page.setViewportSize(viewport);
    await page.waitForFunction(() => {
      const canvas = document.querySelector("canvas.sigma-mouse")?.getBoundingClientRect();
      const stage = document.querySelector(".explore-scene-stage")?.getBoundingClientRect();
      return canvas && stage && Math.abs(canvas.width - stage.width) < 1 && Math.abs(canvas.height - stage.height) < 1;
    });
    const toolbar = await page.locator(".explore-command-deck").boundingBox();
    const canvas = await page.locator("canvas.sigma-mouse").boundingBox();
    assert.ok(toolbar && toolbar.height <= 160, "Primary controls must leave room for the graph on laptop screens");
    assert.ok(canvas && canvas.height >= viewport.height * .55);
    await page.getByText("Graph tools", { exact: true }).click();
    assert.equal((await page.locator("canvas.sigma-mouse").boundingBox())?.height, canvas.height, "Tools open over the graph without shrinking it");
    await page.getByRole("checkbox", { name: "Include ontology schema" }).focus();
    await page.keyboard.press("Escape");
    assert.equal(await page.locator(".explore-tools-menu").getAttribute("open"), null);
  }
  await page.setViewportSize({ width: 800, height: 800 });
  await page.getByText("Graph tools", { exact: true }).click();
  const popup = await page.locator(".explore-tools-popover").boundingBox();
  const workspace = await page.locator(".explore-shell").boundingBox();
  assert.ok(popup && workspace && popup.x >= workspace.x && popup.x + popup.width <= workspace.x + workspace.width, "Narrow-screen tools stay inside the workspace, clear of the sidebar");
  await page.getByRole("checkbox", { name: "Include ontology schema" }).check();
  await page.getByRole("checkbox", { name: "Include ontology schema" }).uncheck();
  await page.keyboard.press("Escape");
  await page.setViewportSize({ width: 1280, height: 800 });
  await assertLegendMatchesGraph(page);
  assert.equal(await legend.getByText("Person", { exact: true }).count(), 1);
  assert.equal(await legend.getByText("Biomolecule", { exact: true }).count(), 0);

  nodes = initialNodes.map((node) => ({ ...node, type: node.type === "Person" ? "Researcher" : node.type }));
  await page.getByText("Graph tools", { exact: true }).click();
  await page.getByRole("button", { name: "Reload graph data" }).click();
  assert.equal(await page.locator(".explore-tools-menu > summary").evaluate((element) => document.activeElement === element), true, "A tool action returns focus to the visible disclosure");
  await legend.getByText("Researcher", { exact: true }).waitFor();
  assert.equal(await legend.getByText("Person", { exact: true }).count(), 0);
  await assertLegendMatchesGraph(page);

  await page.getByPlaceholder("Search command, node, or concept").fill("Alice");
  await page.getByRole("option").filter({ hasText: "Alice" }).click();
  const heatmap = page.getByRole("button", { name: "Heatmap", exact: true });
  await page.getByText("Graph tools", { exact: true }).click();
  await heatmap.click();
  await legend.waitFor({ state: "hidden" });
  await page.getByText("Graph tools", { exact: true }).click();
  await heatmap.click();
  await legend.waitFor();
  await assertLegendMatchesGraph(page);
  const focusButton = page.getByRole("button", { name: "Focus", exact: true });
  assert.equal(await focusButton.isDisabled(), false, "Focus is enabled once a node is selected");
  await focusButton.click();
  await legend.getByText("Document", { exact: true }).waitFor({ state: "hidden" });
  await assertLegendMatchesGraph(page, ["alice", "acme", "research"]);
  assert.equal(await legend.getByText("Researcher", { exact: true }).count(), 1);
  await page.getByRole("button", { name: "Full Graph", exact: true }).click();
  await legend.getByText("Document", { exact: true }).waitFor();
  await assertLegendMatchesGraph(page);
  assert.deepEqual(errors, []);
});
