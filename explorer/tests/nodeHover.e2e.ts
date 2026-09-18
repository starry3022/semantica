import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { setTimeout as delay } from "node:timers/promises";
import test from "node:test";
import { chromium, type Page } from "playwright";
import type Sigma from "sigma";

const BASE_URL = "http://127.0.0.1:4177";
const nodes = [
  { id: "manager", type: "Role", content: "直属主管", properties: {} },
  { id: "group", type: "ApprovalGroup", content: "审批组 (all) 中文😀", properties: { mode: "all" } },
  { id: "rule", type: "ProcessRule", content: "采购审批 · 审批 [C007]", properties: { source_clause_id: "C007" } },
];
const edges = [
  { id: "actor", source: "rule", target: "manager", type: "hasActor", weight: 1, properties: {} },
  { id: "member", source: "group", target: "manager", type: "hasRole", weight: 1, properties: {} },
  { id: "approval", source: "rule", target: "group", type: "hasApprovalGroup", weight: 1, properties: {} },
];

type CanvasFrames = Record<string, string[]>;
type TracedWindow = Window & { __nodeLabelFrames: CanvasFrames };

// Read renderer coordinates only. Interaction below uses real pointer events.
async function nodePosition(page: Page, nodeId: string) {
  return page.evaluate((id) => {
    type Hook = { memoizedState?: { current?: Sigma }; next?: Hook };
    type Fiber = { memoizedState?: Hook; return?: Fiber };
    const canvas = document.querySelector("canvas.sigma-mouse");
    for (let element = canvas?.parentElement; element; element = element.parentElement) {
      const key = Object.keys(element).find((name) => name.startsWith("__reactFiber$"));
      const fields = element as unknown as Record<string, Fiber>;
      for (let fiber = key ? fields[key] : undefined; fiber; fiber = fiber.return) {
        for (let hook = fiber.memoizedState; hook && typeof hook === "object"; hook = hook.next) {
          const renderer = hook.memoizedState?.current;
          if (typeof renderer?.getGraph !== "function" || typeof renderer.graphToViewport !== "function") continue;
          const attrs = renderer.getGraph().getNodeAttributes(id);
          const point = renderer.graphToViewport({ x: attrs.x, y: attrs.y });
          const bounds = canvas!.getBoundingClientRect();
          return { x: bounds.x + point.x, y: bounds.y + point.y, label: String(attrs.label) };
        }
      }
    }
    throw new Error("Graph renderer not found");
  }, nodeId);
}

test("node hover replaces its label chip with one card and restores the chip on leave", async (t) => {
  const server = spawn("npm", ["run", "dev", "--", "--host", "127.0.0.1", "--port", "4177", "--strictPort"], { stdio: "ignore" });
  t.after(() => { server.kill(); });
  let ready = false;
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try { if ((await fetch(BASE_URL)).ok) { ready = true; break; } } catch { /* Vite is starting. */ }
    await delay(100);
  }
  assert.ok(ready, "Isolated Vite server must start");
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.CHROMIUM_PATH || (existsSync("/usr/bin/chromium") ? "/usr/bin/chromium" : undefined),
  });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  t.after(async () => {
    if (process.env.NODE_HOVER_SCREENSHOT) {
      await page.screenshot({ path: process.env.NODE_HOVER_SCREENSHOT });
      t.diagnostic(await page.locator("body").innerText());
    }
    await browser.close();
  });
  page.setDefaultTimeout(10_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.addInitScript(() => {
    const frames = (window as TracedWindow).__nodeLabelFrames = {};
    const fillText = CanvasRenderingContext2D.prototype.fillText;
    const clearRect = CanvasRenderingContext2D.prototype.clearRect;
    CanvasRenderingContext2D.prototype.clearRect = function (...args) {
      frames[this.canvas.className] = [];
      return clearRect.apply(this, args);
    };
    CanvasRenderingContext2D.prototype.fillText = function (text, ...args) {
      (frames[this.canvas.className] ??= []).push(String(text));
      return fillText.call(this, text, ...args);
    };
  });
  await page.routeWebSocket("**/ws/graph-updates", () => {});
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let json: unknown = {};
    if (path === "/api/info") json = { capabilities: { agent_memory: false } };
    if (path === "/api/graph/stats") json = { node_count: nodes.length, edge_count: edges.length };
    if (path === "/api/graph/nodes") json = { nodes, total: nodes.length, next_cursor: null };
    if (path === "/api/graph/edges") json = { edges, total: edges.length, next_cursor: null };
    if (path === "/api/graph/search") {
      const query = String(route.request().postDataJSON()?.query ?? "");
      json = { results: nodes.filter((node) => node.content.includes(query)).map((node) => ({ node, score: 1 })) };
    }
    if (path === "/api/temporal/bounds") json = { min: null, max: null };
    if (path === "/api/temporal/snapshot") json = { active_node_ids: nodes.map((node) => node.id), active_node_count: nodes.length };
    await route.fulfill({ json });
  });
  await page.goto(BASE_URL + "/?workspace=explore");
  await page.getByRole("textbox", { name: "Search graph nodes" }).fill("直属主管");
  await page.getByRole("option").filter({ hasText: "直属主管" }).click();
  if (await page.getByRole("button", { name: "Pause", exact: true }).count()) {
    await page.getByRole("button", { name: "Pause", exact: true }).click();
  }
  for (const mode of ["Focus", "Full Graph"]) {
    await page.getByRole("button", { name: mode, exact: true }).click();
    await page.waitForTimeout(650); // Camera fit animation, with force layout paused.
    for (const id of ["manager", "group", "rule"]) {
      await page.mouse.move(100, 45);
      const target = await nodePosition(page, id);
      if (id === "group") assert.equal(target.label, "审批组 (all) 中文😀 [C007]");
      const meta = nodes.find((node) => node.id === id)!.type.toUpperCase();
      const baseline = await page.evaluate(() => (window as TracedWindow).__nodeLabelFrames["sigma-labels"] ?? []);
      await page.mouse.move(target.x, target.y, { steps: 5 });
      await page.waitForFunction((type) => Object.values((window as TracedWindow).__nodeLabelFrames).some((texts) => texts.includes(type)), meta);
      await page.waitForTimeout(100); // Allow the interaction reducer to redraw the label layer.
      const frames = await page.evaluate(() => (window as TracedWindow).__nodeLabelFrames);
      const titleCount = ["sigma-labels", "sigma-hovers"].flatMap((layer) => frames[layer] ?? []).filter((text) => text === target.label).length;
      assert.equal(titleCount, 1, `${mode}: hovered ${target.label} must have one title, without a second label chip`);
      if (id !== "manager") assert.ok(frames["sigma-labels"].includes("直属主管"), "Other selected-node labels remain visible");
      await page.mouse.move(100, 45);
      await page.waitForFunction((type) => !Object.values((window as TracedWindow).__nodeLabelFrames).some((texts) => texts.includes(type)), meta);
      if (baseline.includes(target.label)) {
        await page.waitForFunction((label) => (window as TracedWindow).__nodeLabelFrames["sigma-labels"]?.includes(label), target.label);
      }
    }
  }
  await page.getByRole("textbox", { name: "Search graph nodes" }).fill("审批组");
  const suggestion = page.getByRole("option").filter({ hasText: "审批组 (all) 中文😀 [C007]" });
  await suggestion.click();
  await page.getByRole("heading", { name: "审批组 (all) 中文😀 [C007]", exact: true }).waitFor();
  assert.deepEqual(errors, []);
});
