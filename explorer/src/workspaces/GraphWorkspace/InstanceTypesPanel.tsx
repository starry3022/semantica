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
                    <strong>{type.label}</strong>
                    <code style={uriStyle}>{type.class_uri}</code>
                    {type.basis.map((basis, index) => <div key={`${basis.kind}:${basis.edge_id ?? index}`} style={noteStyle}>{describeTypeBasis(basis)}</div>)}
                    {!type.loaded ? <div style={noteStyle}>Definition not loaded</div> : null}
                    <button type="button" aria-label={`Open class ${type.label}`} style={buttonStyle} disabled={!type.loaded || !onOpenOntologyEntity} onClick={() => onOpenOntologyEntity?.(type.class_uri)}>Open class</button>
                  </li>)}
                </ul>}
        <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, marginTop: 10 }}>
          <input type="checkbox" checked={Boolean(current?.types.length && showTypes)} disabled={!current?.types.length || !onShowTypes} onChange={(event) => onShowTypes?.(event.target.checked)} />
          Show class links
        </label>
      </section>
      {current ? <section aria-label="Related business concepts via evidence" style={{ borderTop: `1px solid ${GRAPH_THEME.ui.surface.divider}`, paddingTop: 12, marginTop: 12 }}>
        <h4 style={headingStyle}>Related business concepts via evidence</h4>
        <p style={noteStyle}>Evidence associations do not declare instance membership or business approval.</p>
        {current.related_status === "unconfigured" ? <p style={noteStyle}>Business evidence context is not configured.</p>
          : current.related_status === "unavailable" ? <p style={noteStyle}>Business evidence associations are unavailable.</p>
            : current.related_concepts.length === 0 ? <p style={noteStyle}>No verified evidence associations for this node.</p>
              : <ul style={listStyle}>
                {current.related_concepts.map((concept) => <li key={concept.class_uri} style={itemStyle}>
                  <strong>{concept.label}</strong>
                  <code style={uriStyle}>{concept.class_uri}</code>
                  <div style={noteStyle}>{concept.evidence_ids.length} aligned evidence reference{concept.evidence_ids.length === 1 ? "" : "s"}</div>
                  <button type="button" aria-label={`Open class ${concept.label}`} style={buttonStyle} disabled={!onOpenOntologyEntity} onClick={() => onOpenOntologyEntity?.(concept.class_uri)}>Open class</button>
                </li>)}
              </ul>}
        {current.notice ? <p style={noteStyle}>{current.notice}</p> : null}
      </section> : null}
    </section>
  );
}

const panelStyle: CSSProperties = { padding: 14, border: `1px solid ${GRAPH_THEME.ui.surface.panelBorder}`, borderRadius: 10, color: GRAPH_THEME.ui.text.body };
const headingStyle: CSSProperties = { margin: "0 0 8px", color: GRAPH_THEME.ui.text.strong, fontSize: 13 };
const noteStyle: CSSProperties = { margin: "6px 0", color: GRAPH_THEME.ui.text.muted, fontSize: 12, lineHeight: 1.5, overflowWrap: "anywhere" };
const listStyle: CSSProperties = { padding: 0, margin: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 10 };
const itemStyle: CSSProperties = { padding: 10, borderRadius: 8, background: GRAPH_THEME.ui.surface.cardSubtle, fontSize: 13 };
const uriStyle: CSSProperties = { display: "block", marginTop: 4, color: GRAPH_THEME.ui.text.muted, fontSize: 11, overflowWrap: "anywhere" };
const buttonStyle: CSSProperties = { marginTop: 6, padding: "5px 9px", borderRadius: 6, border: `1px solid ${GRAPH_THEME.ui.surface.panelBorder}`, color: GRAPH_THEME.ui.text.body, background: "transparent", fontSize: 12, cursor: "pointer" };
