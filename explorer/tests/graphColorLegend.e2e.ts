import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { setTimeout as delay } from "node:timers/promises";
import test from "node:test";
import { chromium, type Page } from "playwright";
import type Sigma from "sigma";

const BASE_URL = "http://127.0.0.1:4175";
const initialNodes = [
  { id: "alice", type: "https://example.org/very/long/ontology/namespace#FinanceHead", content: "Alice", properties: {} },
  { id: "bob", type: "https://example.org/very/long/ontology/namespace#DepartmentHead", content: "Bob", properties: {} },
  { id: "acme", type: "https://example.org/very/long/ontology/namespace#Organization", content: "Acme", properties: {} },
  { id: "london", type: "https://example.org/very/long/ontology/namespace#Location", content: "London", properties: {} },
  { id: "research", type: "https://example.org/very/long/ontology/namespace#Project", content: "Research", properties: {} },
  { id: "report", type: "https://example.org/very/long/ontology/namespace#Document", content: "Report", properties: {} },
];
const edges = [
  ["alice", "acme", "WORKS_AT"], ["bob", "acme", "WORKS_AT"],
  ["acme", "london", "LOCATED_IN"], ["alice", "research", "LEADS"],
  ["bob", "report", "AUTHORED"], ["report", "research", "DESCRIBES"],
].map(([source, target, type], i) => ({
  id: `edge_${i}`, familyId: `edge_${i}`, source, target, type, weight: 1, properties: {},
}));

async function renderedNodeColors(page: Page) {
  return page.evaluate(() => {
    type Hook = { memoizedState?: { current?: Sigma }; next?: Hook };
    type Fiber = { memoizedState?: Hook; return?: Fiber };
    const canvas = document.querySelector("canvas.sigma-mouse");
    for (let element = canvas?.parentElement; element; element = element.parentElement) {
      const key = Object.keys(element).find((name) => name.startsWith("__reactFiber$"));
      const fields = element as unknown as Record<string, Fiber>;
      for (let fiber = key ? fields[key] : undefined; fiber; fiber = fiber.return) {
        for (let hook = fiber.memoizedState; hook && typeof hook === "object"; hook = hook.next) {
          const renderer = hook.memoizedState?.current;
          if (typeof renderer?.getGraph !== "function" || typeof renderer.getNodeDisplayData !== "function") continue;
          return renderer.getGraph().nodes().map((id) => ({
            id,
            storedColor: renderer.getGraph().getNodeAttribute(id, "baseColor") as string,
            type: renderer.getGraph().getNodeAttribute(id, "nodeType") as string,
            color: renderer.getNodeDisplayData(id)?.color,
          }));
        }
      }
    }
    throw new Error("Graph renderer not found");
  });
}

test("neutral canvas preserves space and interaction colors without a persistent type legend", async (t) => {
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
  await page.locator("canvas").first().waitFor({ state: "visible" });
  assert.equal(await legend.count(), 0, "No type or module legend occupies the main viewport");
  const original = await renderedNodeColors(page);
  assert.equal(new Set(original.map((node) => node.color)).size, 1, "Each class does not create a distinct rendered color");
  assert.ok(new Set(original.map((node) => node.storedColor)).size > 1, "Original color metadata is retained");
  for (const viewport of [{ width: 1440, height: 900 }, { width: 1280, height: 800 }, { width: 800, height: 800 }]) {
    await page.setViewportSize(viewport);
    await page.waitForFunction(() => {
      const canvas = document.querySelector("canvas.sigma-mouse")?.getBoundingClientRect();
      const stage = document.querySelector(".explore-scene-stage")?.getBoundingClientRect();
      return canvas && stage && Math.abs(canvas.width - stage.width) < 1 && Math.abs(canvas.height - stage.height) < 1;
    });
    const toolbar = await page.locator(".explore-command-deck").boundingBox();
    const canvas = await page.locator("canvas.sigma-mouse").boundingBox();
    assert.ok(toolbar && toolbar.height <= (viewport.width === 800 ? 180 : 160), "Primary controls must leave room for the graph");
    assert.ok(canvas && canvas.height >= viewport.height * .55);
    const search = await page.getByPlaceholder("Search command, node, or concept").boundingBox();
    assert.ok(search && toolbar && search.y + search.height <= toolbar.y + toolbar.height, "Search stays inside the compact toolbar");
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
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
  assert.equal(await legend.count(), 0);

  nodes = initialNodes.map((node) => ({ ...node, type: node.type.replace("FinanceHead", "Researcher") }));
  await page.getByText("Graph tools", { exact: true }).click();
  await page.getByRole("button", { name: "Reload graph data" }).click();
  assert.equal(await page.locator(".explore-tools-menu > summary").evaluate((element) => document.activeElement === element), true, "A tool action returns focus to the visible disclosure");
  await page.waitForFunction(async () => {
    const storePath = "/src/store/graphStore.ts";
    const { graph } = await import(storePath);
    return String(graph.getNodeAttribute("alice", "nodeType")).endsWith("#Researcher");
  });
  assert.equal(await legend.count(), 0);
  assert.equal(new Set((await renderedNodeColors(page)).map((node) => node.color)).size, 1);

  await page.getByPlaceholder("Search command, node, or concept").fill("Alice");
  await page.getByRole("option").filter({ hasText: "Alice" }).click();
  const heatmap = page.getByRole("button", { name: "Heatmap", exact: true });
  await page.getByText("Graph tools", { exact: true }).click();
  await heatmap.click();
  await page.getByText("Outside", { exact: true }).waitFor();
  assert.equal(await legend.count(), 0);
  assert.ok(new Set((await renderedNodeColors(page)).map((node) => node.color)).size > 1, "Explicit distance mode retains its colors");
  await page.getByText("Graph tools", { exact: true }).click();
  await heatmap.click();
  await page.getByText("Outside", { exact: true }).waitFor({ state: "hidden" });
  assert.equal(await legend.count(), 0);
  const focusButton = page.getByRole("button", { name: "Focus", exact: true });
  assert.equal(await focusButton.isDisabled(), false, "Focus is enabled once a node is selected");
  await focusButton.click();
  const focused = await renderedNodeColors(page);
  assert.deepEqual(focused.map((node) => node.id).sort(), ["acme", "alice", "research"]);
  assert.notEqual(focused.find((node) => node.id === "alice")?.color, focused.find((node) => node.id === "acme")?.color);
  assert.equal(focused.find((node) => node.id === "acme")?.color, focused.find((node) => node.id === "research")?.color);
  assert.equal(await legend.count(), 0);
  await page.getByRole("button", { name: "Full Graph", exact: true }).click();
  assert.equal((await renderedNodeColors(page)).length, initialNodes.length);
  assert.equal(await legend.count(), 0);
  assert.deepEqual(errors, []);
});
