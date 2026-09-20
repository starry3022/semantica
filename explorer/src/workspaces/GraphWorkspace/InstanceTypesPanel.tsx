import type { CSSProperties } from "react";
import { GRAPH_THEME } from "./graphTheme";
import { describeTypeBasis, type InstanceTypesSnapshot } from "./instanceTypes";

export interface InstanceTypesPanelProps {
  nodeId: string;
  snapshot: InstanceTypesSnapshot | null;
  loading: boolean;
  error: string | null;
  showTypes: boolean;
  onShowTypes?: (enabled: boolean) => void;
  onOpenOntologyEntity?: (uri: string) => void;
}

export function InstanceTypesPanel({ nodeId, snapshot, loading, error, showTypes, onShowTypes, onOpenOntologyEntity }: InstanceTypesPanelProps) {
  const current = !loading && !error && snapshot?.node_id === nodeId ? snapshot : null;
  const references = current?.concept_references ?? [];
  const referenceIssues = current?.concept_reference_issues ?? [];
  return (
    <section aria-label="Instance classes" style={panelStyle}>
      <section aria-label="Declared class">
        <h4 style={headingStyle}>Declared class</h4>
        {loading ? <p role="status" style={noteStyle}>Loading declared classes…</p>
          : error ? <p role="alert" style={noteStyle}>{error}</p>
            : !current ? <p style={noteStyle}>Class information is not available for this selection.</p>
              : current.status === "unmapped" ? <p style={noteStyle}><strong>Unmapped.</strong> No explicit class declaration could be resolved for this node.</p>
                : <ul style={listStyle}>
                  {current.types.map((type) => <li key={type.class_uri} style={itemStyle}>
                    <button type="button" aria-label={`Open class ${type.label}`} title={type.class_uri} style={buttonStyle} disabled={!type.loaded || !onOpenOntologyEntity} onClick={() => onOpenOntologyEntity?.(type.class_uri)}><span>{type.label}</span> <span aria-hidden="true">↗</span></button>
                    {!type.loaded ? <div style={noteStyle}>Definition not loaded</div> : null}
                  </li>)}
                </ul>}
        {current?.types.length ? <details key={nodeId} style={{ marginTop: 8 }}>
          <summary style={summaryStyle}>Class details</summary>
          {current.types.map((type) => <div key={type.class_uri}>
            <code style={uriStyle}>{type.class_uri}</code>
            {type.basis.map((basis, index) => <div key={`${basis.kind}:${basis.edge_id ?? index}`} style={noteStyle}>{describeTypeBasis(basis)}</div>)}
          </div>)}
        </details> : null}
        <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, marginTop: 10 }}>
          <input type="checkbox" checked={Boolean(current?.types.length && showTypes)} disabled={!current?.types.length || !onShowTypes} onChange={(event) => onShowTypes?.(event.target.checked)} />
          Show class links
        </label>
      </section>
      {references.length > 0 || referenceIssues.length > 0 ? <section aria-label="Business concept references" style={{ borderTop: `1px solid ${GRAPH_THEME.ui.surface.divider}`, paddingTop: 10, marginTop: 10 }}>
        {references.length > 0 ? <details key={`${nodeId}:concept-references`} style={{ marginTop: 4 }}>
          <summary style={summaryStyle}>Candidate concept references ({references.length})</summary>
          <p style={noteStyle}>Concept references are not instance declarations or business approval.</p>
          <ul style={listStyle}>
            {references.map((reference) => <li key={reference.class_uri} style={itemStyle}>
              <button type="button" aria-label={`Open concept ${reference.class_label}`} title={reference.class_uri} style={buttonStyle} disabled={!onOpenOntologyEntity} onClick={() => onOpenOntologyEntity?.(reference.class_uri)}><span>{reference.class_label}</span> <span aria-hidden="true">↗</span></button>
              <span style={{ ...noteStyle, marginLeft: 8 }}>candidate / unreviewed</span>
              <code style={uriStyle}>{reference.class_uri}</code>
              <p style={noteStyle}>{reference.rationale}</p>
              <p style={noteStyle}>{reference.evidence_ids.length} evidence reference{reference.evidence_ids.length === 1 ? "" : "s"}</p>
            </li>)}
          </ul>
        </details> : null}
        {referenceIssues.map((issue, index) => <p key={`${issue.class_uri}:${index}`} role="alert" style={noteStyle}>{issue.reason}</p>)}
      </section> : null}
      {current ? <section aria-label="Related business concepts via evidence" style={{ borderTop: `1px solid ${GRAPH_THEME.ui.surface.divider}`, paddingTop: 10, marginTop: 10 }}>
        <details key={nodeId}>
          <summary style={summaryStyle}>Related concepts ({current.related_concepts.length})</summary>
          <p style={noteStyle}>Evidence associations do not declare instance membership or business approval.</p>
          {current.related_status === "unconfigured" ? <p style={noteStyle}>Business evidence context is not configured.</p>
            : current.related_status === "unavailable" ? <p style={noteStyle}>Business evidence associations are unavailable.</p>
              : current.related_concepts.length === 0 ? <p style={noteStyle}>No verified evidence associations for this node.</p>
                : <ul style={listStyle}>
                  {current.related_concepts.map((concept) => <li key={concept.class_uri} style={itemStyle}>
                    <button type="button" aria-label={`Open class ${concept.label}`} title={concept.class_uri} style={buttonStyle} disabled={!onOpenOntologyEntity} onClick={() => onOpenOntologyEntity?.(concept.class_uri)}><span>{concept.label}</span> <span aria-hidden="true">↗</span></button>
                    <div style={noteStyle}>{concept.evidence_ids.length} aligned evidence reference{concept.evidence_ids.length === 1 ? "" : "s"}</div>
                  </li>)}
                </ul>}
          {current.notice ? <p style={noteStyle}>{current.notice}</p> : null}
        </details>
      </section> : null}
    </section>
  );
}

const panelStyle: CSSProperties = { padding: 12, border: `1px solid ${GRAPH_THEME.ui.surface.panelBorder}`, borderRadius: 10, color: GRAPH_THEME.ui.text.body };
const headingStyle: CSSProperties = { margin: "0 0 8px", color: GRAPH_THEME.ui.text.strong, fontSize: 13 };
const noteStyle: CSSProperties = { margin: "6px 0", color: GRAPH_THEME.ui.text.muted, fontSize: 12, lineHeight: 1.5, overflowWrap: "anywhere" };
const listStyle: CSSProperties = { padding: 0, margin: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 10 };
const itemStyle: CSSProperties = { fontSize: 13 };
const uriStyle: CSSProperties = { display: "block", marginTop: 4, color: GRAPH_THEME.ui.text.muted, fontSize: 11, overflowWrap: "anywhere" };
const buttonStyle: CSSProperties = { padding: "4px 0", border: 0, color: GRAPH_THEME.ui.text.strong, background: "transparent", fontSize: 13, textAlign: "left", overflowWrap: "anywhere", cursor: "pointer" };
const summaryStyle: CSSProperties = { color: GRAPH_THEME.ui.text.muted, fontSize: 12, cursor: "pointer" };
