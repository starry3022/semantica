import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { setTimeout as delay } from "node:timers/promises";
import test from "node:test";
import { chromium, type Page } from "playwright";
import type Sigma from "sigma";

const BASE_URL = "http://127.0.0.1:4176";
const namespace = "https://example.test/ontology/";
const nodes = [
  { id: "finance", type: namespace + "FinanceHead", content: "财务负责人", properties: { fact_status: "candidate", review_status: "unreviewed" } },
  { id: "purchase", type: namespace + "PurchaseRequest", content: "采购申请", properties: { fact_status: "candidate", review_status: "unreviewed" } },
];
const edges = [
  { id: "approval-standard", familyId: "approval-standard", source: "finance", target: "purchase", type: namespace + "approves", weight: 1, properties: { condition: "采购金额不超过十万元", review_status: "unreviewed" } },
  { id: "approval-exception", familyId: "approval-exception", source: "finance", target: "purchase", type: namespace + "approves", weight: 1, properties: { condition: "采购金额超过十万元且已取得总经理批准", review_status: "unreviewed" } },
];

async function sourceFacts(page: Page) {
  return page.evaluate(async () => {
    const storePath = "/src/store/graphStore.ts";
    const { graph } = await import(storePath);
    return {
      nodes: graph.nodes().sort().map((id: string) => {
        const { nodeType, content, properties } = graph.getNodeAttributes(id);
        return { id, nodeType, content, properties };
      }),
      edges: graph.edges().sort().map((id: string) => {
        const { edgeType, properties } = graph.getEdgeAttributes(id);
        return { id, source: graph.source(id), target: graph.target(id), edgeType, properties };
      }),
    };
  });
}

// Read the rendered edge and coordinates; selection uses actual pointer events.
async function renderedBundle(page: Page) {
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
          if (typeof renderer?.getGraph !== "function" || typeof renderer.graphToViewport !== "function") continue;
          const display = renderer.getGraph();
          const id = display.edges().find((edgeId) => display.getEdgeAttribute(edgeId, "isAggregated"));
          if (!id) throw new Error("Expected the two approvals to render as an aggregated edge");
          const attrs = display.getEdgeAttributes(id);
          const [source, target] = display.extremities(id).map((nodeId) => {
            const position = display.getNodeAttributes(nodeId);
            return renderer.graphToViewport({ x: position.x, y: position.y });
          });
          const curvature = Number((renderer.getEdgeDisplayData(id) as { curvature?: number } | undefined)?.curvature ?? 0);
          const bounds = canvas!.getBoundingClientRect();
          return {
            id,
            rawEdgeIds: attrs.rawEdgeIds as string[],
            x: bounds.x + (source.x + target.x) / 2 + (target.y - source.y) * curvature / 2,
            y: bounds.y + (source.y + target.y) / 2 - (target.x - source.x) * curvature / 2,
          };
        }
      }
    }
    throw new Error("Graph renderer not found");
  });
}

test("instance Properties opens each original parallel relationship in Full and Focus while canvas bundles remain selectable", async (t) => {
  const server = spawn("npm", ["run", "dev", "--", "--host", "127.0.0.1", "--port", "4176", "--strictPort"], { stdio: "ignore" });
  t.after(() => { server.kill(); });
  let ready = false;
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (server.exitCode !== null) break;
    try { if ((await fetch(BASE_URL)).ok) { ready = true; break; } } catch { /* Vite is starting. */ }
    await delay(100);
  }
  assert.ok(ready, "Isolated Vite server must start on port 4176");
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.CHROMIUM_PATH || (existsSync("/usr/bin/chromium") ? "/usr/bin/chromium" : undefined),
  });
  t.after(() => browser.close());
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.setDefaultTimeout(10_000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.routeWebSocket("**/ws/graph-updates", () => {});
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    let json: unknown = {};
    if (url.pathname === "/api/info") json = { capabilities: { agent_memory: false } };
    if (url.pathname === "/api/graph/stats") json = { node_count: nodes.length, edge_count: edges.length };
    if (url.pathname === "/api/graph/nodes") json = { nodes, total: nodes.length, next_cursor: null };
    if (url.pathname === "/api/graph/edges") json = { edges, total: edges.length, next_cursor: null };
    if (url.pathname === "/api/temporal/bounds") json = { min: null, max: null };
    if (url.pathname === "/api/temporal/snapshot") json = { active_node_ids: nodes.map((node) => node.id), active_node_count: nodes.length };
    if (url.pathname === "/api/graph/search") json = { results: [{ node: nodes[0], score: 1 }] };
    if (url.pathname === "/api/ontology/instance-types") {
      const node = nodes.find((candidate) => candidate.id === url.searchParams.get("node_id"));
      assert.ok(node, "Class lookup must identify an existing node");
      json = {
        node_id: node.id, status: "declared", types: [{ class_uri: node.type, label: node.content, loaded: true, ontology_uri: namespace, basis: [{ kind: "node_type", value: node.type }] }],
        related_concepts: [], related_status: "unconfigured", notice: "", property_definitions: [],
        object_properties: node.id === "finance" ? [{
          property_uri: namespace + "approves", label: "审批", loaded: true, ontology_uri: namespace,
          targets: [{ node_id: "purchase", label: "采购申请", edge_ids: ["approval-standard", "approval-exception"] }],
        }] : [],
      };
    }
    if (url.pathname === "/api/sources/view") {
      const kind = url.searchParams.has("edge_id") ? "edge" : "node";
      json = { selection: { kind, id: url.searchParams.get(`${kind}_id`), label: "" }, sources: [], evidence: [], related_rules: [], status: "no_evidence" };
    }
    await route.fulfill({ json });
  });
  await page.goto(BASE_URL + "/?workspace=explore");
  await page.getByPlaceholder("Search command, node, or concept").fill("财务负责人");
  await page.getByRole("option").filter({ hasText: "财务负责人" }).click();
  await page.getByRole("heading", { name: "财务负责人", exact: true }).waitFor();
  if (await page.getByRole("button", { name: "Pause", exact: true }).count()) {
    await page.getByRole("button", { name: "Pause", exact: true }).click();
  }
  const before = await sourceFacts(page);
  assert.deepEqual(before.edges.map((edge) => edge.id), ["approval-exception", "approval-standard"]);

  for (const mode of ["Full Graph", "Focus"]) {
    await page.getByRole("button", { name: mode, exact: true }).click();
    await page.waitForTimeout(650); // Wait for the camera fit animation with layout paused.
    const bundle = await renderedBundle(page);
    assert.deepEqual([...bundle.rawEdgeIds].sort(), ["approval-exception", "approval-standard"]);
    assert.ok(!edges.some((edge) => edge.id === bundle.id), "The canvas uses a synthetic bundle, not a raw edge ID");
    await page.mouse.click(bundle.x, bundle.y);
    await page.getByText("2 bundled edges", { exact: true }).waitFor();
    const evidenceChoices = await page.getByRole("combobox", { name: "Relationship for evidence" }).locator("option").evaluateAll((options) => options.map((option) => (option as HTMLOptionElement).value).filter(Boolean));
    assert.deepEqual(evidenceChoices.sort(), ["approval-exception", "approval-standard"], "Canvas selection retains both underlying relationships");
    await page.getByRole("button", { name: "Close", exact: true }).click();

    const propertiesSummary = page.locator("summary").filter({ hasText: /^Properties$/ });
    if (!(await propertiesSummary.evaluate((summary) => summary.parentElement!.hasAttribute("open")))) {
      await propertiesSummary.click();
    }
    for (const [index, edge] of edges.entries()) {
      await page.getByRole("button", { name: `View relationship 审批（approves） → 采购申请 (${index + 1}/2)`, exact: true }).click();
      const relationship = page.getByRole("region", { name: "Relationship properties", exact: true });
      await relationship.waitFor({ state: "visible", timeout: 5_000 }).catch(() => {
        assert.fail(`${mode}: Properties clicked ${edge.id}, but its Relationship properties did not open`);
      });
      assert.equal(await page.getByRole("combobox", { name: "Relationship for evidence" }).count(), 0, "A single raw relationship must not silently select its bundle");
      await relationship.getByLabel("View all relationship properties", { exact: true }).click();
      assert.equal(await relationship.getByText(edge.properties.condition, { exact: true }).isVisible(), true, `${mode}: selected raw edge must show its own condition`);
      assert.equal(await relationship.getByText(edges[1 - index].properties.condition, { exact: true }).count(), 0, "The other parallel edge's condition must not leak into the selection");
      await page.getByRole("button", { name: "Close", exact: true }).click();
    }
    assert.deepEqual(await sourceFacts(page), before, `${mode}: inspecting properties must not mutate the source graph`);
  }
  assert.deepEqual(errors, [], "No browser page errors");
});
