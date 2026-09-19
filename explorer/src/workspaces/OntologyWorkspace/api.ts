import type {
  AlignmentRelation,
  AlignmentSuggestion,
  OntologyAlignment,
  OntologyEntry,
  OntologyHealthResponse,
  ShaclGenerateResponse,
  ShaclShapesResponse,
  ShaclValidationResponse,
} from "./types";
import { isClassExpression, type ClassExpression } from "./classExpressions";

export type OntologyEvidenceContext = {
  configured: boolean;
  business_ontologies: string[];
  support_ontologies: string[];
};

export type OntologyRuleEvidence = {
  id: string;
  clause_id: string | null;
  role: "primary" | "supporting" | "unknown";
  quote: string;
  start_char: number;
  end_char: number;
  source_id: string;
  source_sha256: string;
  links: { term_uri: string; label: string; kind: "direct" | "property"; relation: string | null }[];
};

export type OntologyRelatedRules = {
  ontology_uri: string;
  term_uri: string;
  status: "ready" | "unconfigured" | "unavailable";
  term: { id: string; label: string; type: string; description: string };
  association_status: "candidate";
  associations: {
    node_id: string;
    label: string;
    modality: string | null;
    fact_status: string | null;
    review_status: string | null;
    evidence: OntologyRuleEvidence[];
  }[];
  anchors: { term_uri: string; label: string; status: string; reason: string | null }[];
  evidence_issues?: { id: string; clause_id: string | null; status: string; reason: string | null }[];
  notice: string;
};

export async function loadOntologyEvidenceContext(signal?: AbortSignal): Promise<OntologyEvidenceContext> {
  const response = await fetch("/api/ontology/evidence-context", { signal });
  // Hosts predating source registration still support the existing ontology UI.
  if (response.status === 404) return { configured: false, business_ontologies: [], support_ontologies: [] };
  return parseResponse<OntologyEvidenceContext>(response);
}

export async function loadOntologyRelatedRules(ontologyUri: string, termUri: string, signal: AbortSignal): Promise<OntologyRelatedRules> {
  const query = new URLSearchParams({ ontology_uri: ontologyUri, term_uri: termUri });
  const result = await parseResponse<OntologyRelatedRules>(await fetch(`/api/ontology/related-rules?${query}`, { signal }));
  if (result.ontology_uri !== ontologyUri || result.term_uri !== termUri || !Array.isArray(result.associations) || !Array.isArray(result.anchors)) {
    throw new Error("Rule evidence could not be loaded: mismatched or invalid response.");
  }
  return result;
}

export type OntologyGraphNode = {
  id: string;
  type: string;
  content?: string;
  properties?: Record<string, unknown>;
};

export type OntologyGraphEdge = {
  id?: string;
  source: string;
  target: string;
  type: string;
  weight?: number;
  properties?: Record<string, unknown>;
};

export type OntologyGraphResponse = {
  uri: string;
  nodes: OntologyGraphNode[];
  edges: OntologyGraphEdge[];
};

export type OntologyTermSnapshot = {
  ontology_uri: string;
  term_uri: string;
  revision: string;
  scope: "session";
  changed?: boolean;
  term: {
    id: string;
    type: "owl:Class" | "owl:ObjectProperty" | "owl:DatatypeProperty";
    label: string;
    comment: string;
    parents: string[];
    domain: string[];
    range: string[];
    domain_expressions?: ClassExpression[];
    range_expressions?: ClassExpression[];
  };
};

export type OntologyTermEdit = Pick<OntologyTermSnapshot["term"], "label" | "comment" | "parents" | "domain" | "range"> & { expected_revision: string };

async function readOntologyTermResponse(response: Response, ontologyUri: string, termUri: string): Promise<OntologyTermSnapshot> {
  const data = await response.json();
  if (!response.ok) {
    const detail = data?.detail;
    const message = typeof detail === "string" ? detail : typeof detail?.message === "string" ? detail.message : Array.isArray(detail)
      ? detail.map((issue: { msg?: string }) => issue.msg || "Invalid field").join("; ")
      : `Term request failed (${response.status}).`;
    throw new Error(message);
  }
  const term = data?.term;
  const stringList = (value: unknown): value is string[] => Array.isArray(value) && value.every((item) => typeof item === "string");
  const expressionList = (value: unknown) => value === undefined || (Array.isArray(value) && value.every(isClassExpression));
  if (data?.ontology_uri !== ontologyUri || data?.term_uri !== termUri || data?.scope !== "session"
      || typeof data?.revision !== "string" || !data.revision || term?.id !== termUri
      || !["owl:Class", "owl:ObjectProperty", "owl:DatatypeProperty"].includes(term?.type)
      || typeof term?.label !== "string" || typeof term?.comment !== "string"
      || !stringList(term?.parents) || !stringList(term?.domain) || !stringList(term?.range)
      || !expressionList(term?.domain_expressions) || !expressionList(term?.range_expressions)) {
    throw new Error("Term definition could not be loaded: mismatched or invalid response.");
  }
  return data as OntologyTermSnapshot;
}

export async function loadOntologyTerm(ontologyUri: string, termUri: string, signal: AbortSignal): Promise<OntologyTermSnapshot> {
  const query = new URLSearchParams({ ontology_uri: ontologyUri, term_uri: termUri });
  return readOntologyTermResponse(await fetch(`/api/ontology/term?${query}`, { signal }), ontologyUri, termUri);
}

export async function saveOntologyTerm(ontologyUri: string, termUri: string, edit: OntologyTermEdit): Promise<OntologyTermSnapshot> {
  const query = new URLSearchParams({ ontology_uri: ontologyUri, term_uri: termUri });
  return readOntologyTermResponse(await fetch(`/api/ontology/term?${query}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(edit),
  }), ontologyUri, termUri);
}

export type OntologyEntityOwner = {
  // Optional on purpose, unlike OntologyGraphNode.entity_type. There, a missing
  // field degrades to a read-only node — benign. Here it would be read as an
  // authoritative "nothing owns this entity", which now suppresses selection
  // outright, so presence has to be checked rather than assumed.
  owning_ontology?: string | null;
};

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = `Request failed with status ${response.status}`;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // Keep the generic HTTP detail.
    }
    throw new Error(detail);
  }
  const data = await response.json();
  if (response.status === 207) {
    console.warn("Partial Success:", data.message || "Warning: 207 Multi-Status");
  }
  return data as T;
}

export async function loadOntologyRegistry(): Promise<OntologyEntry[]> {
  return parseResponse<OntologyEntry[]>(await fetch("/api/ontology/registry"));
}

export async function loadOntologyGraph(uri: string, signal?: AbortSignal): Promise<OntologyGraphResponse> {
  return parseResponse<OntologyGraphResponse>(
    await fetch(`/api/ontology/graph?uri=${encodeURIComponent(uri)}`, { signal }),
  );
}

// Three-state verdict: a string names the owner, null is the backend's
// authoritative "no known ontology owns this entity", and undefined means the
// request failed so there is no verdict to act on.
export type OntologyOwnerVerdict = string | null | undefined;

export async function loadOntologyEntityOwner(uri: string): Promise<OntologyOwnerVerdict> {
  const response = await fetch(`/api/ontology/entity/${encodeURIComponent(uri)}`);
  if (!response.ok) return undefined;
  const owner = await response.json() as OntologyEntityOwner | null;
  // Only a field that is actually there carries the verdict. Coercing an absent
  // field to null would assert the strongest available claim — "nothing owns
  // this" — on the weakest possible evidence, and that claim now stops the
  // editor selecting an ontology at all.
  const verdict = owner?.owning_ontology;
  return verdict === undefined ? undefined : verdict;
}

export async function loadAlignments(uri?: string): Promise<OntologyAlignment[]> {
  const query = uri ? `?uri=${encodeURIComponent(uri)}` : "";
  return parseResponse<OntologyAlignment[]>(await fetch(`/api/ontology/alignments${query}`));
}

export async function saveAlignment(payload: {
  source_uri: string;
  target_uri: string;
  relation: AlignmentRelation;
  confidence: number;
  provenance?: string;
  source?: string;
  reviewer?: string;
}): Promise<OntologyAlignment> {
  return parseResponse<OntologyAlignment>(
    await fetch("/api/ontology/alignments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  );
}

export async function removeAlignment(id: string): Promise<void> {
  await parseResponse<{ status: string }>(
    await fetch(`/api/ontology/alignments?id=${encodeURIComponent(id)}`, { method: "DELETE" }),
  );
}

export async function suggestAlignments(payload: {
  source_ontology_uri?: string;
  target_ontology_uri?: string;
  threshold: number;
  limit: number;
}): Promise<AlignmentSuggestion[]> {
  return parseResponse<AlignmentSuggestion[]>(
    await fetch("/api/ontology/suggest-alignments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  );
}

export async function loadOntologyHealth(uri: string): Promise<OntologyHealthResponse> {
  return parseResponse<OntologyHealthResponse>(
    await fetch(`/api/ontology/health?uri=${encodeURIComponent(uri)}`),
  );
}

export async function generateShacl(uri: string, qualityTier: "standard" | "strict" = "strict"): Promise<ShaclGenerateResponse> {
  return parseResponse<ShaclGenerateResponse>(
    await fetch("/api/ontology/shacl/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ uri, quality_tier: qualityTier }),
    }),
  );
}

export async function loadShaclShapes(uri: string): Promise<ShaclShapesResponse> {
  return parseResponse<ShaclShapesResponse>(
    await fetch(`/api/ontology/shacl/shapes?uri=${encodeURIComponent(uri)}`),
  );
}

export async function validateShacl(uri: string, shaclTurtle: string): Promise<ShaclValidationResponse> {
  return parseResponse<ShaclValidationResponse>(
    await fetch("/api/ontology/shacl/validate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ uri, shacl_turtle: shaclTurtle }),
    }),
  );
}
