export interface SourceMaterial {
  source_id: string | null;
  source_sha256: string | null;
  actual_sha256: string | null;
  title: string | null;
  version: string | null;
  source_uri: string | null;
  status: "available" | "source_missing" | "hash_mismatch";
  reason: string | null;
  text: string | null;
  character_count: number | null;
}

export interface SourceEvidence {
  id: string;
  clause_id: string | null;
  role: "primary" | "supporting" | "unknown";
  quote: string | null;
  start_char: number | null;
  end_char: number | null;
  source_id: string | null;
  source_sha256: string | null;
  status: "aligned" | "source_missing" | "hash_mismatch" | "invalid_offsets" | "quote_mismatch" | "invalid_evidence" | "source_mismatch";
  reason: string | null;
  fact_status: string | null;
  review_status: string | null;
}

export interface SourceRelatedRule {
  id: string;
  label: string;
  source_clause_id: string | null;
  fact_status: string | null;
  review_status: string | null;
}

export interface SourceView {
  selection: { kind: "node" | "edge"; id: string; label: string };
  evidence: SourceEvidence[];
  sources: SourceMaterial[];
  related_rules?: SourceRelatedRule[];
  assertions?: {
    assertion_id: string | null;
    qualifiers: Record<string, unknown>;
    evidence_ids: string[];
    fact_status: string | null;
    review_status: string | null;
  }[];
  related_relationships?: {
    edge_id: string;
    predicate: string;
    source_label: string;
    target_label: string;
    assertion_count: number;
  }[];
  status: "ok" | "no_evidence";
}

export function assertionSourceView(view: SourceView, evidenceIds: string[]): SourceView {
  const evidence = view.evidence.filter((item) => evidenceIds.includes(item.id));
  return {
    selection: view.selection,
    evidence,
    sources: view.sources.filter((source) => evidence.some((item) => item.source_id === source.source_id && item.source_sha256 === source.source_sha256)),
    status: evidence.length ? "ok" : "no_evidence",
  };
}

export function evidenceSourceIndex(sources: SourceMaterial[], evidence: SourceEvidence): number {
  return sources.findIndex((source) => source.source_id === evidence.source_id && source.source_sha256 === evidence.source_sha256);
}

export function sourceHighlight(source: SourceMaterial | undefined, evidence: SourceEvidence | undefined) {
  if (!source || !evidence || evidence.status !== "aligned" || source.status !== "available" || source.text == null) return null;
  if (source.source_id !== evidence.source_id || source.source_sha256 !== evidence.source_sha256 || source.actual_sha256 !== source.source_sha256) return null;
  const start = evidence.start_char;
  const end = evidence.end_char;
  if (start == null || end == null || !Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start < 0 || end <= start) return null;
  // Python offsets count Unicode code points; native String.slice counts UTF-16 units.
  const characters = Array.from(source.text);
  if (end > characters.length) return null;
  const match = characters.slice(start, end).join("");
  if (match !== evidence.quote) return null;
  return { before: characters.slice(0, start).join(""), match, after: characters.slice(end).join("") };
}

export async function readSourceView(kind: "node" | "edge", id: string, signal: AbortSignal): Promise<SourceView> {
  const query = new URLSearchParams({ [`${kind}_id`]: id });
  const response = await fetch(`/api/sources/view?${query}`, { signal });
  if (!response.ok) throw new Error(`Source material could not be loaded (${response.status}).`);
  const result = await response.json() as SourceView;
  if (!Array.isArray(result.sources) || !Array.isArray(result.evidence)) throw new Error("Source material could not be loaded: invalid server response.");
  return result;
}
