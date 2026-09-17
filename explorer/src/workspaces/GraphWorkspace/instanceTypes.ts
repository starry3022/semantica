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

export interface InstanceTypesSnapshot {
  node_id: string;
  status: "declared" | "unmapped";
  types: DeclaredInstanceType[];
  related_concepts: {
    class_uri: string;
    label: string;
    ontology_uri: string | null;
    evidence_ids: string[];
  }[];
  related_status: "ready" | "unconfigured" | "unavailable";
  notice: string;
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
    && typeof value.notice === "string";
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

export function describeTypeBasis(basis: InstanceTypeBasis): string {
  const labels: Record<InstanceTypeBasis["kind"], string> = {
    rdf_type_edge: "RDF type edge",
    rdf_type_property: "RDF type property",
    node_type: "Node type",
    graph_namespace: "Graph namespace",
  };
  return `${labels[basis.kind]}: ${basis.value}`;
}
