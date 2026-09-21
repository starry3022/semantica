import type { OntologyGraphEdge, OntologyGraphNode } from "./api";
import { compactNodeType } from "./ontologyEditorModel";
import { propertyDisplayLabel } from "./propertyDisplayLabel";

/** Read a declared schema projection. Instance edges never become declarations. */
export function relationshipShape(edge: OntologyGraphEdge) {
  const value = edge.properties;
  if (value?.schema_kind !== "relationship_shape"
    || typeof value.shape_uri !== "string" || typeof value.property_uri !== "string"
    || typeof value.ontology_uri !== "string" || typeof value.label !== "string"
    || typeof value.comment !== "string") return null;
  return {
    uri: value.shape_uri, propertyUri: value.property_uri, ontologyUri: value.ontology_uri,
    label: value.label, comment: value.comment, source: edge.source, target: edge.target,
    llm: value.definition_source === "llm",
    valueClasses: Array.isArray(value.value_classes) ? value.value_classes.filter((item): item is string => typeof item === "string") : [edge.target],
  };
}

export function isDeclaredRelationship(value?: Record<string, unknown>) {
  return value?.schema_kind === "relationship_shape" || value?.schema_kind === "object_property";
}

/** Edge names belong to the property; a shape's title describes its scope. */
export function relationshipEdgeLabel(edge: OntologyGraphEdge, nodes: OntologyGraphNode[]) {
  if (!isDeclaredRelationship(edge.properties)) return edge.type;
  const uri = String(edge.properties!.property_uri);
  const property = nodes.find((node) => node.id === uri);
  const label = property?.content || property?.properties?.["rdfs:label"];
  return propertyDisplayLabel(uri, typeof label === "string" ? label : uri);
}

/** Project existing named OWL endpoints; never derive declarations from usage. */
export function declaredRelationshipEdges(nodes: OntologyGraphNode[], edges: OntologyGraphEdge[]): OntologyGraphEdge[] {
  const result = [...edges];
  const classIds = new Set(nodes.filter((node) => ["owl:Class", "rdfs:Class", "external"].includes(compactNodeType(node.type)) && !node.id.startsWith("_:")).map((node) => node.id));
  for (const property of nodes.filter((node) => compactNodeType(node.type) === "owl:ObjectProperty")) {
    // Multiple global domains/ranges are conjunctive; do not reinterpret them
    // as alternatives, or flatten anonymous class expressions into simple links.
    if ((Array.isArray(property.properties?.domain_expressions) && property.properties.domain_expressions.length)
      || (Array.isArray(property.properties?.range_expressions) && property.properties.range_expressions.length)) continue;
    const endpoints = (kind: string) => [...new Set(edges.filter((edge) => edge.source === property.id && compactNodeType(edge.type) === kind).map((edge) => edge.target))];
    const domains = endpoints("rdfs:domain");
    const ranges = endpoints("rdfs:range");
    if (domains.length !== 1 || ranges.length !== 1 || !classIds.has(domains[0]) || !classIds.has(ranges[0])) continue;
    const source = domains[0], target = ranges[0];
    if (result.some((edge) => isDeclaredRelationship(edge.properties) && edge.source === source && edge.target === target && edge.type === property.id)) continue;
    result.push({
      id: `ontology-property:${JSON.stringify([property.id, source, target])}`, source, target, type: property.id,
      properties: { schema_kind: "object_property", property_uri: property.id,
        ontology_uri: property.properties?.scheme_uri, schema_role: property.properties?.schema_role,
        label: property.content, comment: property.properties?.["rdfs:comment"], definition_source: "ontology" },
    });
  }
  return result;
}
