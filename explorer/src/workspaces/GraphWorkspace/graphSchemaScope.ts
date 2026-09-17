import type Graph from "graphology";
import type { EdgeAttributes, NodeAttributes, graph } from "../../store/graphStore";

type SourceGraph = typeof graph | Graph<NodeAttributes, EdgeAttributes>;

const VOCABULARIES = [
  ["http://www.w3.org/2002/07/owl#", "owl:"],
  ["http://www.w3.org/2000/01/rdf-schema#", "rdfs:"],
  ["http://www.w3.org/1999/02/22-rdf-syntax-ns#", "rdf:"],
] as const;

const SCHEMA_TYPES = new Set([
  "owl:Ontology", "owl:Class", "rdfs:Class", "rdf:Property", "rdfs:Property",
  "owl:ObjectProperty", "owl:DatatypeProperty", "owl:AnnotationProperty",
  "owl:FunctionalProperty", "owl:InverseFunctionalProperty", "owl:TransitiveProperty",
  "owl:SymmetricProperty", "owl:AsymmetricProperty", "owl:ReflexiveProperty", "owl:IrreflexiveProperty",
  "owl:Restriction", "rdfs:Datatype", "owl:DataRange", "owl:Axiom", "owl:AllDisjointClasses",
  "owl:AllDisjointProperties",
]);

const SCHEMA_RELATIONS = new Set([
  "rdfs:subClassOf", "rdfs:subPropertyOf", "rdfs:domain", "rdfs:range",
  "owl:equivalentClass", "owl:equivalentProperty", "owl:disjointWith", "owl:propertyDisjointWith",
  "owl:inverseOf", "owl:imports", "owl:onProperty", "owl:onClass", "owl:onDataRange",
  "owl:someValuesFrom", "owl:allValuesFrom", "owl:complementOf",
]);

function compactTerm(value: unknown): string {
  if (typeof value !== "string") return "";
  for (const [iri, prefix] of VOCABULARIES) {
    if (value.startsWith(iri)) return `${prefix}${value.slice(iri.length)}`;
  }
  return value;
}

function isSchemaDefinition(attributes: NodeAttributes): boolean {
  if (SCHEMA_TYPES.has(compactTerm(attributes.nodeType))) return true;
  const properties = attributes.properties ?? {};
  return [properties["rdf:type"], properties["http://www.w3.org/1999/02/22-rdf-syntax-ns#type"]]
    .flatMap((value: unknown) => Array.isArray(value) ? value : [value])
    .some((value: unknown) => SCHEMA_TYPES.has(compactTerm(value)));
}

/** A display projection only: never remove nodes or rewrite attributes in the store. */
export function createKnowledgeGraphScope(sourceGraph: SourceGraph, includeOntologySchema = false) {
  const definitions = new Set<string>();
  sourceGraph.forEachNode((nodeId, attributes) => {
    if (isSchemaDefinition(attributes as NodeAttributes)) definitions.add(nodeId);
  });
  sourceGraph.forEachEdge((_edgeId, attributes, source, target) => {
    if (compactTerm(attributes.edgeType) === "rdf:type" && SCHEMA_TYPES.has(compactTerm(target))) {
      definitions.add(source);
    }
  });

  // Only direct structural endpoints of declared schema are considered. A
  // business node's rdf:type link to a class never makes that node schema.
  const endpoints = new Set<string>();
  sourceGraph.forEachEdge((_edgeId, attributes, source, target) => {
    const relation = compactTerm(attributes.edgeType);
    if (SCHEMA_RELATIONS.has(relation)) {
      if (definitions.has(source)) endpoints.add(target);
      if (definitions.has(target)) endpoints.add(source);
    } else if (relation === "rdf:type" && definitions.has(source)) {
      endpoints.add(target);
    }
  });

  const schemaNodeIds = new Set(definitions);
  for (const nodeId of endpoints) {
    if (schemaNodeIds.has(nodeId)) continue;
    const nodeType = sourceGraph.getNodeAttributes(nodeId).nodeType;
    if (nodeType && nodeType !== "entity") continue;
    const schemaOnly = sourceGraph.everyEdge(nodeId, (_id, attributes) => {
      const relation = compactTerm(attributes.edgeType);
      return relation === "rdf:type" || SCHEMA_RELATIONS.has(relation);
    });
    if (schemaOnly) schemaNodeIds.add(nodeId);
  }

  const scopedGraph = includeOntologySchema || schemaNodeIds.size === 0 ? sourceGraph : sourceGraph.copy();
  if (scopedGraph !== sourceGraph) schemaNodeIds.forEach((nodeId) => scopedGraph.dropNode(nodeId));
  return {
    graph: scopedGraph,
    schemaNodeIds,
    hiddenNodeCount: sourceGraph.order - scopedGraph.order,
    hiddenEdgeCount: sourceGraph.size - scopedGraph.size,
  };
}
