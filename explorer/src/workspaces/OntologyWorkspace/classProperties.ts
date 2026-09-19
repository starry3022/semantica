import type { OntologyGraphEdge, OntologyGraphNode } from "./api";
import { classifyNodeType, compactNodeType } from "./ontologyEditorModel";
import { readClassExpressions, type ClassExpression } from "./classExpressions";

export type ClassProperty = {
  node: OntologyGraphNode;
  domain: string[];
  range: string[];
  domainExpressions: ClassExpression[];
  rangeExpressions: ClassExpression[];
  inheritedFrom: string[];
};

export function classPropertyGroups(classUri: string, nodes: OntologyGraphNode[], edges: OntologyGraphEdge[]) {
  const groups: { declared: ClassProperty[]; inherited: ClassProperty[]; incoming: ClassProperty[] } = {
    declared: [], inherited: [], incoming: [],
  };
  const classIds = new Set(nodes.filter((node) => classifyNodeType(node.type) === "class" && !node.id.startsWith("_:" )).map((node) => node.id));
  if (!classIds.has(classUri)) return groups;
  const parents = new Map<string, Set<string>>();
  const domains = new Map<string, Set<string>>();
  const ranges = new Map<string, Set<string>>();
  for (const edge of edges) {
    const predicate = compactNodeType(edge.type);
    const index = predicate === "rdfs:subClassOf" ? parents : predicate === "rdfs:domain" ? domains : predicate === "rdfs:range" ? ranges : null;
    if (!index) continue;
    const values = index.get(edge.source) || new Set<string>();
    values.add(edge.target);
    index.set(edge.source, values);
  }
  const ancestors = new Set<string>();
  const pending = [...(parents.get(classUri) || [])];
  while (pending.length) {
    const parent = pending.pop()!;
    if (parent === classUri || ancestors.has(parent) || !classIds.has(parent)) continue;
    ancestors.add(parent);
    pending.push(...(parents.get(parent) || []));
  }
  const properties = nodes.filter((node) => classifyNodeType(node.type) === "property")
    .sort((left, right) => (left.content || left.id).localeCompare(right.content || right.id) || left.id.localeCompare(right.id));
  for (const node of properties) {
    const domain = [...(domains.get(node.id) || [])].sort();
    const range = [...(ranges.get(node.id) || [])].sort();
    const domainExpressions = readClassExpressions(node.properties?.domain_expressions);
    const rangeExpressions = readClassExpressions(node.properties?.range_expressions);
    const domainMembers = new Set([...domain, ...domainExpressions.flatMap((expression) => expression.kind === "unionOf" ? expression.members : [])]);
    const rangeMembers = new Set([...range, ...rangeExpressions.flatMap((expression) => expression.kind === "unionOf" ? expression.members : [])]);
    const inheritedFrom = [...domainMembers].filter((id) => ancestors.has(id)).sort();
    const row = { node, domain, range, domainExpressions, rangeExpressions, inheritedFrom };
    if (domainMembers.has(classUri)) groups.declared.push(row);
    else if (inheritedFrom.length) groups.inherited.push(row);
    if (rangeMembers.has(classUri)) groups.incoming.push(row);
  }
  return groups;
}
