import type Graph from "graphology";
import type { EdgeAttributes, NodeAttributes, graph } from "../../store/graphStore";

type SourceGraph = typeof graph | Graph<NodeAttributes, EdgeAttributes>;

function termName(value: unknown): string {
  return typeof value === "string" ? value.split(/[/#:]/).at(-1) ?? "" : "";
}

/** Resolve display context from declared relationships, without rewriting Markdown content. */
export function getNodeDisplayLabel(sourceGraph: SourceGraph, nodeId: string, fallback = nodeId): string {
  if (!sourceGraph.hasNode(nodeId)) return fallback;
  const attributes = sourceGraph.getNodeAttributes(nodeId);
  const label = String(attributes.label ?? attributes.content ?? fallback);
  if (termName(attributes.nodeType) !== "ApprovalGroup") return label;

  const clauses = new Set<string>();
  let hasUnknownClause = false;
  sourceGraph.forEachInEdge(nodeId, (_edgeId, edge, _source, target, rule) => {
    if (target !== nodeId || termName(edge.edgeType) !== "hasApprovalGroup" || termName(rule.nodeType) !== "ProcessRule") return;
    const clause = rule.properties?.source_clause_id;
    if (typeof clause === "string" && clause.trim()) clauses.add(clause.trim());
    else hasUnknownClause = true;
  });
  const clauseLabels = [...clauses].sort();
  if (hasUnknownClause) clauseLabels.push("未知条款");
  if (!clauseLabels.length) return label;

  // Reusing this resolver on a projected label must not duplicate its suffix.
  // Strip only trailing brackets made entirely of the current, declared clauses.
  let base = label.trimEnd();
  let suffix = /\s*\[([^[\]]*)\]$/.exec(base);
  while (suffix && suffix[1].split(",").every(value => clauseLabels.includes(value.trim()))) {
    base = base.slice(0, suffix.index).trimEnd();
    suffix = /\s*\[([^[\]]*)\]$/.exec(base);
  }
  return `${base} [${clauseLabels.join(", ")}]`;
}

/** Resolve before Focus trims relationships; clone only when a title changes. */
export function projectApprovalGroupLabels(sourceGraph: SourceGraph): SourceGraph {
  let display = sourceGraph;
  sourceGraph.forEachNode((nodeId, attributes) => {
    if (termName(attributes.nodeType) !== "ApprovalGroup") return;
    const label = getNodeDisplayLabel(sourceGraph, nodeId);
    if (label === attributes.label) return;
    if (display === sourceGraph) display = sourceGraph.copy();
    display.mergeNodeAttributes(nodeId, { label });
  });
  return display;
}
