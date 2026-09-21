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
export function createKnowledgeGraphScope(sourceGraph: SourceGraph, includeOntologySchema = false, includeProvenance = false) {
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

  // Use only explicit, loaded ontology roles and type declarations. Labels,
  // local names, and proximity to an evidence node do not classify a node.
  const provenanceTerms = new Set([...definitions].filter((nodeId) =>
    sourceGraph.getNodeAttributes(nodeId).properties?.schema_role === "provenance"));
  const provenanceNodeIds = new Set<string>();
  sourceGraph.forEachNode((nodeId, attributes) => {
    if (schemaNodeIds.has(nodeId)) return;
    const properties = attributes.properties ?? {};
    const types: unknown[] = [attributes.nodeType, properties["rdf:type"], properties["http://www.w3.org/1999/02/22-rdf-syntax-ns#type"]].flat();
    if (types.some((type) => typeof type === "string" && provenanceTerms.has(type))) provenanceNodeIds.add(nodeId);
  });
  sourceGraph.forEachEdge((_edgeId, attributes, source, target) => {
    if (compactTerm(attributes.edgeType) === "rdf:type" && provenanceTerms.has(target) && !schemaNodeIds.has(source)) {
      provenanceNodeIds.add(source);
    }
  });
  const provenanceEdgeIds = new Set<string>();
  sourceGraph.forEachEdge((edgeId, attributes, source, target) => {
    if (provenanceTerms.has(attributes.edgeType) || provenanceNodeIds.has(source) || provenanceNodeIds.has(target)) {
      provenanceEdgeIds.add(edgeId);
    }
  });

  const hiddenNodeIds = new Set([
    ...(!includeOntologySchema ? schemaNodeIds : []),
    ...(!includeProvenance ? provenanceNodeIds : []),
  ]);
  const needsProjection = hiddenNodeIds.size > 0 || (!includeProvenance && provenanceEdgeIds.size > 0);
  const scopedGraph = needsProjection ? sourceGraph.copy() : sourceGraph;
  if (needsProjection) {
    hiddenNodeIds.forEach((nodeId) => scopedGraph.dropNode(nodeId));
    if (!includeProvenance) provenanceEdgeIds.forEach((edgeId) => {
      if (scopedGraph.hasEdge(edgeId)) scopedGraph.dropEdge(edgeId);
    });
  }
  return {
    graph: scopedGraph,
    schemaNodeIds,
    provenanceNodeIds,
    provenanceEdgeIds,
    hiddenSchemaNodeCount: includeOntologySchema ? 0 : schemaNodeIds.size,
    hiddenProvenanceNodeCount: includeProvenance ? 0 : provenanceNodeIds.size,
    hiddenNodeCount: sourceGraph.order - scopedGraph.order,
    hiddenEdgeCount: sourceGraph.size - scopedGraph.size,
  };
}
