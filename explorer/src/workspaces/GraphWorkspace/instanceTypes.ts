export interface InstanceTypeBasis {
  kind: "rdf_type_edge" | "rdf_type_property" | "node_type" | "graph_namespace";
  value: string;
  edge_id?: string;
}

export interface DeclaredInstanceType {
  class_uri: string;
  label: string;
  loaded: boolean;
  ontology_uri: string | null;
  basis: InstanceTypeBasis[];
}

export interface ConceptReference {
  node_id: string;
  label: string;
  class_uri: string;
  class_label: string;
  ontology_uri: string | null;
  rationale: string;
  status: "candidate";
  review_status: "unreviewed";
  evidence_ids: string[];
}

export interface ConceptReferenceIssue {
  node_id: string;
  class_uri: string;
  reason: string;
}

export interface ConceptReferencesSnapshot {
  class_uri: string;
  references: ConceptReference[];
  issues: ConceptReferenceIssue[];
  status: "ready" | "unconfigured" | "unavailable";
  notice: string;
}

export interface InstanceTypesSnapshot {
  node_id: string;
  status: "declared" | "unmapped";
  types: DeclaredInstanceType[];
  property_definitions?: {
    key: string;
    property_uri: string;
    label: string;
    loaded: boolean;
    ontology_uri: string | null;
  }[];
  related_concepts: {
    class_uri: string;
    label: string;
    ontology_uri: string | null;
    evidence_ids: string[];
  }[];
  related_status: "ready" | "unconfigured" | "unavailable";
  notice: string;
  concept_references?: ConceptReference[];
  concept_reference_issues?: ConceptReferenceIssue[];
}

export interface ClassInstancesSnapshot {
  class_uri: string;
  instances: { node_id: string; label: string; basis: InstanceTypeBasis[] }[];
  total: number;
  skip: number;
  limit: number;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function isBasis(value: unknown): value is InstanceTypeBasis[] {
  return Array.isArray(value) && value.every((basis: unknown) => isRecord(basis)
    && typeof basis.kind === "string" && ["rdf_type_edge", "rdf_type_property", "node_type", "graph_namespace"].includes(basis.kind)
    && typeof basis.value === "string"
    && (basis.edge_id === undefined || typeof basis.edge_id === "string"));
}

function isConceptReference(value: unknown): value is ConceptReference {
  return isRecord(value)
    && typeof value.node_id === "string" && typeof value.label === "string"
    && typeof value.class_uri === "string" && typeof value.class_label === "string"
    && isNullableString(value.ontology_uri) && typeof value.rationale === "string"
    && value.status === "candidate" && value.review_status === "unreviewed"
    && Array.isArray(value.evidence_ids) && value.evidence_ids.every((id: unknown) => typeof id === "string");
}

function isConceptReferenceIssue(value: unknown): value is ConceptReferenceIssue {
  return isRecord(value) && typeof value.node_id === "string"
    && typeof value.class_uri === "string" && typeof value.reason === "string";
}

function isInstanceTypes(value: unknown): value is InstanceTypesSnapshot {
  if (!isRecord(value)) return false;
  return typeof value.node_id === "string"
    && (value.status === "declared" || value.status === "unmapped")
    && Array.isArray(value.types)
    && (value.status === "declared" ? value.types.length > 0 : value.types.length === 0)
    && value.types.every((type: unknown) => isRecord(type)
      && typeof type.class_uri === "string" && typeof type.label === "string"
      && typeof type.loaded === "boolean" && isNullableString(type.ontology_uri) && isBasis(type.basis))
    && Array.isArray(value.related_concepts)
    && value.related_concepts.every((concept: unknown) => isRecord(concept)
      && typeof concept.class_uri === "string" && typeof concept.label === "string"
      && isNullableString(concept.ontology_uri)
      && Array.isArray(concept.evidence_ids) && concept.evidence_ids.every((id: unknown) => typeof id === "string"))
    && typeof value.related_status === "string" && ["ready", "unconfigured", "unavailable"].includes(value.related_status)
    && typeof value.notice === "string"
    && (value.property_definitions === undefined || (Array.isArray(value.property_definitions)
      && value.property_definitions.every((property: unknown) => isRecord(property)
        && typeof property.key === "string" && typeof property.property_uri === "string"
        && typeof property.label === "string" && typeof property.loaded === "boolean"
        && isNullableString(property.ontology_uri))))
    && (value.concept_references === undefined || (Array.isArray(value.concept_references)
      && value.concept_references.every((reference: unknown) => isConceptReference(reference) && reference.node_id === value.node_id)))
    && (value.concept_reference_issues === undefined || (Array.isArray(value.concept_reference_issues)
      && value.concept_reference_issues.every((issue: unknown) => isConceptReferenceIssue(issue) && issue.node_id === value.node_id)));
}

export async function loadInstanceTypes(nodeId: string, signal?: AbortSignal): Promise<InstanceTypesSnapshot> {
  const query = new URLSearchParams({ node_id: nodeId });
  const response = await fetch(`/api/ontology/instance-types?${query}`, { signal });
  if (!response.ok) throw new Error(`Unable to load declared classes (${response.status}).`);
  const value: unknown = await response.json();
  if (!isInstanceTypes(value) || value.node_id !== nodeId) throw new Error("The declared-class response does not match the selected node.");
  return value;
}

export async function loadClassInstances(classUri: string, skip: number, limit: number, signal?: AbortSignal): Promise<ClassInstancesSnapshot> {
  const query = new URLSearchParams({ class_uri: classUri, skip: String(skip), limit: String(limit) });
  const response = await fetch(`/api/ontology/class-instances?${query}`, { signal });
  if (!response.ok) throw new Error(`Unable to load declared instances (${response.status}).`);
  const value: unknown = await response.json();
  if (!isRecord(value) || value.class_uri !== classUri || value.skip !== skip || value.limit !== limit
    || typeof value.total !== "number" || !Number.isSafeInteger(value.total) || value.total < 0
    || !Array.isArray(value.instances) || value.instances.length > limit
    || !value.instances.every((instance: unknown) => isRecord(instance)
      && typeof instance.node_id === "string" && typeof instance.label === "string" && isBasis(instance.basis))) {
    throw new Error("The declared-instance response does not match the selected class or page.");
  }
  return value as unknown as ClassInstancesSnapshot;
}

export async function loadConceptReferences(classUri: string, signal?: AbortSignal): Promise<ConceptReferencesSnapshot> {
  const query = new URLSearchParams({ class_uri: classUri });
  const response = await fetch(`/api/ontology/concept-references?${query}`, { signal });
  if (!response.ok) throw new Error(`Unable to load concept references (${response.status}).`);
  const value: unknown = await response.json();
  if (!isRecord(value) || value.class_uri !== classUri
    || typeof value.status !== "string" || !["ready", "unconfigured", "unavailable"].includes(value.status)
    || typeof value.notice !== "string"
    || !Array.isArray(value.references)
    || (value.status !== "ready" && value.references.length > 0)
    || !value.references.every((reference: unknown) => isConceptReference(reference) && reference.class_uri === classUri)
    || !Array.isArray(value.issues)
    || !value.issues.every((issue: unknown) => isConceptReferenceIssue(issue) && issue.class_uri === classUri)) {
    throw new Error("The concept-reference response does not match the selected class.");
  }
  return value as unknown as ConceptReferencesSnapshot;
}

export function describeTypeBasis(basis: InstanceTypeBasis): string {
  const labels: Record<InstanceTypeBasis["kind"], string> = {
    rdf_type_edge: "RDF type edge",
    rdf_type_property: "RDF type property",
    node_type: "Node type",
    graph_namespace: "Graph namespace",
  };
  return `${labels[basis.kind]}: ${basis.value}`;
}
