import { useContext, useEffect, useId, useRef, useState, type CSSProperties } from "react";
import { createPortal } from "react-dom";
import { BookOpen, X } from "lucide-react";
import { GRAPH_THEME } from "./graphTheme";
import { evidenceSourceIndex, readSourceView, sourceHighlight, type SourceEvidence, type SourceRelatedRule, type SourceView } from "./sourceEvidence";
import { WorkspaceActivityContext } from "../../WorkspaceActivityContext";

interface SourceEvidencePanelProps {
  kind: "node" | "edge";
  id: string;
  initialEvidenceId?: string;
}

export function SourceEvidencePanel(props: SourceEvidencePanelProps) {
  // A changed selection must not paint or reopen the previous source, even for one frame.
  return <SourceEvidenceSession key={JSON.stringify([props.kind, props.id, props.initialEvidenceId])} {...props} />;
}

function SourceEvidenceSession({ kind, id, initialEvidenceId }: SourceEvidencePanelProps) {
  const [view, setView] = useState<SourceView | null>(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    void readSourceView(kind, id, controller.signal).then((result) => {
      if (!controller.signal.aborted) setView(result);
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Source material could not be loaded.");
    });
    return () => controller.abort();
  }, [kind, id]);

  return (
    <section style={sectionStyle} aria-label="Source material & evidence">
      <div style={{ color: GRAPH_THEME.ui.text.strong, fontSize: 13, fontWeight: 700 }}>Source material & evidence</div>
      {error ? <div role="alert" style={mutedStyle}>{error}</div> : !view ? (
        <div style={mutedStyle}>Loading source references…</div>
      ) : view.sources.length || view.evidence.length || view.related_rules?.length ? (
        <>
          <div style={mutedStyle}>
            {view.sources.length || view.evidence.length ? <>
              {view.sources.length} source material{view.sources.length === 1 ? "" : "s"} · {view.evidence.length} evidence item{view.evidence.length === 1 ? "" : "s"}
              {view.related_rules?.length ? " · " : ""}
            </> : null}
            {view.related_rules?.length ? `${view.related_rules.length} related rule${view.related_rules.length === 1 ? "" : "s"}` : ""}
          </div>
          <button type="button" style={buttonStyle} onClick={() => setOpen(true)}>
            <BookOpen size={14} aria-hidden="true" /> Open source material
          </button>
        </>
      ) : <div style={mutedStyle}>No explicit evidence or source material is linked to this {kind === "edge" ? "relationship" : "node"}.</div>}
      {open && view ? <SourceMaterialDialog view={view} initialEvidenceId={initialEvidenceId} onClose={() => setOpen(false)} /> : null}
    </section>
  );
}

export function RelationshipSourceEvidence({ edgeIds }: { edgeIds: string[] }) {
  return <RelationshipSourceSelection key={JSON.stringify(edgeIds)} edgeIds={edgeIds} />;
}

function RelationshipSourceSelection({ edgeIds }: { edgeIds: string[] }) {
  const [id, setId] = useState(edgeIds.length === 1 ? edgeIds[0] : "");
  return (
    <div style={{ display: "grid", gap: 8 }}>
      {edgeIds.length > 1 ? (
        <label style={mutedStyle}>
          This bundle contains multiple relationships. Select one to view its explicit evidence.
          <select aria-label="Relationship for evidence" value={id} onChange={(event) => setId(event.target.value)} style={selectStyle}>
            <option value="">Choose a relationship</option>
            {edgeIds.map((edgeId, index) => <option key={edgeId} value={edgeId}>Relationship {index + 1}: {edgeId}</option>)}
          </select>
        </label>
      ) : null}
      {id ? <SourceEvidencePanel kind="edge" id={id} /> : null}
    </div>
  );
}

function SourceMaterialDialog({ view, onClose, initialEvidenceId }: { view: SourceView; onClose: () => void; initialEvidenceId?: string }) {
  const hasDirectEvidence = view.sources.length > 0 || view.evidence.length > 0;
  const [contextId, setContextId] = useState<string>();
  const selectedContextId = contextId ?? (hasDirectEvidence ? "" : view.related_rules?.[0]?.id || "");
  const relatedRule = view.related_rules?.find((rule) => rule.id === selectedContextId);
  return <SourceMaterialContext
    key={selectedContextId}
    selectionView={view}
    relatedRule={relatedRule}
    onContextChange={setContextId}
    focusContextOnMount={contextId !== undefined}
    initialEvidenceId={relatedRule ? undefined : initialEvidenceId}
    onClose={onClose}
  />;
}

function SourceMaterialContext({ selectionView, relatedRule, onContextChange, focusContextOnMount, onClose, initialEvidenceId }: {
  selectionView: SourceView;
  relatedRule?: SourceRelatedRule;
  onContextChange: (id: string) => void;
  focusContextOnMount: boolean;
  onClose: () => void;
  initialEvidenceId?: string;
}) {
  const isActive = useContext(WorkspaceActivityContext);
  const [ruleView, setRuleView] = useState<SourceView | null>(null);
  const [error, setError] = useState("");
  const view = relatedRule ? ruleView : selectionView;
  const initialEvidence = initialEvidenceId ? view?.evidence.find((evidence) => evidence.id === initialEvidenceId) : view?.evidence[0];
  const [selectedEvidence, setSelectedEvidence] = useState<SourceEvidence | undefined>(initialEvidence);
  const [sourceIndex, setSourceIndex] = useState(() => initialEvidence && view ? evidenceSourceIndex(view.sources, initialEvidence) : 0);
  const source = view?.sources[sourceIndex];
  const highlight = sourceHighlight(source, selectedEvidence);
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const contextSelectRef = useRef<HTMLSelectElement>(null);
  const contextFocusRef = useRef(focusContextOnMount);
  const markRef = useRef<HTMLElement>(null);
  const textRef = useRef<HTMLPreElement>(null);
  const titleId = useId();
  useEffect(() => {
    if (!relatedRule) return;
    const controller = new AbortController();
    void readSourceView("node", relatedRule.id, controller.signal).then((result) => {
      if (controller.signal.aborted) return;
      const evidence = result.evidence[0];
      setRuleView(result);
      setSelectedEvidence(evidence);
      setSourceIndex(evidence ? evidenceSourceIndex(result.sources, evidence) : 0);
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Source material could not be loaded.");
    });
    return () => controller.abort();
  }, [relatedRule]);
  useEffect(() => {
    if (!isActive) { contextFocusRef.current = false; return; }
    const previousFocus = document.activeElement;
    const initialFocus = contextFocusRef.current ? contextSelectRef.current : closeRef.current;
    initialFocus?.focus({ preventScroll: true });
    return () => { if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus({ preventScroll: true }); };
  }, [isActive]);
  useEffect(() => {
    const text = textRef.current;
    if (!isActive || !text) return;
    if (markRef.current) {
      const markBounds = markRef.current.getBoundingClientRect();
      const textBounds = text.getBoundingClientRect();
      // Scroll only the source viewport; scrollIntoView also moves the dialog.
      text.scrollTop = Math.max(0, text.scrollTop + markBounds.top - textBounds.top - text.clientTop - (text.clientHeight - markBounds.height) / 2);
    } else text.scrollTop = 0;
  }, [sourceIndex, selectedEvidence, isActive]);

  const selectEvidence = (evidence: SourceEvidence) => {
    if (!view) return;
    setSelectedEvidence(evidence);
    setSourceIndex(evidenceSourceIndex(view.sources, evidence));
  };
  const evidenceStatus = selectedEvidence
    ? highlight
      ? "Citation aligned · Located in source text."
      : `Not located: ${selectedEvidence.reason || selectedEvidence.status.replaceAll("_", " ")}${selectedEvidence.status === "aligned" ? " — the source identity or text range could not be verified." : ""}`
    : initialEvidenceId && !initialEvidence
      ? "The requested evidence is unavailable. Select an available citation to locate it."
      : "No evidence selected. Full source material is shown when available.";
  if (!isActive) return null;
  return createPortal(
    <div style={backdropStyle}>
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        style={dialogStyle}
        onKeyDown={(event) => {
          if (event.key === "Escape") { event.stopPropagation(); onClose(); }
          if (event.key !== "Tab") return;
          const controls = dialogRef.current?.querySelectorAll<HTMLElement>('button, select, summary, [tabindex="0"]');
          const first = controls?.[0];
          const last = controls?.[controls.length - 1];
          if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
          if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
        }}
      >
        <header style={{ display: "flex", gap: 16, alignItems: "flex-start", justifyContent: "space-between", flexShrink: 0 }}>
          <div style={{ minWidth: 0 }}>
            <h2 id={titleId} style={{ fontSize: 19, margin: "0 0 8px", color: GRAPH_THEME.ui.text.strong }}>Source material & evidence</h2>
            <div style={{ ...mutedStyle, overflowWrap: "anywhere", maxHeight: "3.2em", overflowY: "auto" }} title={selectionView.selection.label || selectionView.selection.id}>{selectionView.selection.label || selectionView.selection.id}</div>
          </div>
          <button ref={closeRef} type="button" aria-label="Close source material" style={buttonStyle} onClick={onClose}><X size={16} /> Close</button>
        </header>
        {selectionView.related_rules?.length ? (
          <section style={{ ...sectionStyle, gap: 5, padding: "10px 12px", flexShrink: 0 }} aria-label="Evidence context">
            <div style={{ display: "flex", flexWrap: "wrap", gap: "6px 16px", alignItems: "center" }}>
              <label style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8, flex: "1 1 360px", minWidth: 0 }}>
                <strong style={headingStyle}>{relatedRule ? "Related rule evidence" : "Evidence context"}</strong>
                <select ref={contextSelectRef} aria-label="Evidence context" value={relatedRule?.id || ""} style={{ ...selectStyle, marginTop: 0, width: "auto", flex: "1 1 200px", minWidth: 0 }} onChange={(event) => onContextChange(event.target.value)}>
                  {selectionView.sources.length || selectionView.evidence.length ? <option value="">Direct evidence</option> : null}
                  {selectionView.related_rules.map((rule) => <option key={rule.id} value={rule.id}>{rule.label || rule.id}</option>)}
                </select>
              </label>
              {relatedRule ? <div style={metadataStyle}>Fact status: {relatedRule.fact_status || "Unknown"} · Business review: {relatedRule.review_status || "Unknown"} · Source clause: {relatedRule.source_clause_id || "Unknown"}</div> : null}
            </div>
            {relatedRule ? <div style={mutedStyle}>References belong to this rule and do not establish field- or relationship-specific support.</div> : null}
          </section>
        ) : null}
        {error ? <div role="alert" style={mutedStyle}>{error}</div> : !view ? (
          <div role="status" style={mutedStyle}>Loading related rule evidence…</div>
        ) : <div style={{ display: "flex", flexWrap: "wrap", gap: 20, minHeight: 0, overflowY: "auto", flex: "1 1 auto" }}>
          <aside style={{ flex: "1 1 230px", minWidth: 0, minHeight: 0, maxHeight: "100%", display: "flex", flexDirection: "column", gap: 12 }} aria-label="Evidence list">
            <h3 style={headingStyle}>Evidence · {view.evidence.length}</h3>
            <div style={mutedStyle}>Citation alignment does not mean business approval. Extraction and review statuses are preserved.</div>
            {view.evidence.length ? (
              <div style={{ display: "grid", gap: 8, overflowY: "auto", maxHeight: "52vh", padding: 2 }}>
                {view.evidence.map((evidence) => (
                  <button
                    key={evidence.id}
                    type="button"
                    aria-pressed={selectedEvidence?.id === evidence.id}
                    onClick={() => selectEvidence(evidence)}
                    style={{ ...evidenceButtonStyle, borderColor: selectedEvidence?.id === evidence.id ? GRAPH_THEME.ui.timeline.playhead : GRAPH_THEME.ui.surface.panelBorder }}
                  >
                    <strong>{evidence.role === "primary" ? "Primary" : evidence.role === "supporting" ? "Supporting" : "Evidence"} · {evidence.clause_id || "Unknown clause"}</strong>
                    <span style={{ fontSize: 12, whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{evidence.quote || "Quote unavailable"}</span>
                    <span style={mutedStyle}>{evidence.status === "aligned" ? "Citation aligned" : "Not located"}</span>
                  </button>
                ))}
              </div>
            ) : <div style={mutedStyle}>No explicit evidence is linked to this selection.</div>}
          </aside>
          <div style={{ flex: "3 1 450px", minWidth: 0, minHeight: 0, height: "100%", display: "flex", flexDirection: "column", gap: 12 }}>
            {view.sources.length > 1 ? (
              <label style={mutedStyle}>Source material
                <select aria-label="Source material" value={sourceIndex} style={selectStyle} onChange={(event) => { setSelectedEvidence(undefined); setSourceIndex(Number(event.target.value)); }}>
                  {sourceIndex < 0 ? <option value="-1">Source unavailable</option> : null}
                  {view.sources.map((item, index) => <option key={`${item.source_id}:${item.source_sha256}`} value={index}>{item.title || item.source_id}</option>)}
                </select>
              </label>
            ) : null}
            <section style={{ ...sectionStyle, gap: 6 }} aria-label="Source identity">
              <h3 style={headingStyle}>{source?.title || source?.source_id || selectedEvidence?.source_id || "Source unavailable"}</h3>
              <div style={metadataStyle}>Version: {source?.version || "Unknown"}</div>
              <div style={metadataStyle}>Material status: {source?.status.replaceAll("_", " ") || "source missing"}{source?.character_count != null ? ` · ${source.character_count} Unicode characters` : ""}</div>
              <details style={metadataStyle}>
                <summary style={{ ...mutedStyle, cursor: "pointer" }}>Source details &amp; SHA-256</summary>
                <div>Source ID: {source?.source_id || selectedEvidence?.source_id || "Unknown"}</div>
                {source?.source_uri ? <div>Source URI: {source.source_uri}</div> : null}
                <div>Expected SHA-256: {source?.source_sha256 || selectedEvidence?.source_sha256 || "Unknown"}</div>
                <div>Actual SHA-256: {source?.actual_sha256 || "Unknown"}</div>
              </details>
              {source?.reason ? <div style={{ ...mutedStyle, color: "#f0bd85" }}>{source.reason}</div> : null}
            </section>
            <div role="status" style={{ ...statusStyle, borderColor: highlight ? "rgba(98,226,205,0.35)" : "rgba(240,189,133,0.35)" }}>
              <div>{evidenceStatus}</div>
              {selectedEvidence ? <>
                <div style={{ ...mutedStyle, marginTop: 6 }}>Fact status: {selectedEvidence.fact_status || "Unknown"} · Business review: {selectedEvidence.review_status || "Unknown"}</div>
                <div style={mutedStyle}>Unicode character range: [{selectedEvidence.start_char ?? "?"}, {selectedEvidence.end_char ?? "?"})</div>
              </> : null}
            </div>
            {source?.status === "available" && source.text != null ? (
              <pre ref={textRef} aria-label="Full source text" tabIndex={0} style={sourceTextStyle}>
                {highlight ? <>{highlight.before}<mark ref={markRef} style={{ color: "#15201f", background: "#f5d485", borderRadius: 2 }}>{highlight.match}</mark>{highlight.after}</> : source.text}
              </pre>
            ) : <div style={mutedStyle}>Full source text is unavailable. {source?.reason || "No matching registered material was found."}</div>}
          </div>
        </div>}
      </div>
    </div>,
    document.body,
  );
}

const mutedStyle: CSSProperties = { color: GRAPH_THEME.ui.text.muted, fontSize: 12, lineHeight: 1.6 };
const headingStyle: CSSProperties = { color: GRAPH_THEME.ui.text.strong, fontSize: 14, margin: 0, overflowWrap: "anywhere" };
const metadataStyle: CSSProperties = { color: GRAPH_THEME.ui.text.body, fontSize: 12, lineHeight: 1.6, overflowWrap: "anywhere" };
const sectionStyle: CSSProperties = { display: "flex", flexDirection: "column", gap: 9, padding: 12, borderRadius: 10, border: `1px solid ${GRAPH_THEME.ui.surface.panelBorder}`, background: "rgba(98,226,205,0.035)" };
const buttonStyle: CSSProperties = { display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 7, padding: "9px 12px", borderRadius: 8, border: `1px solid ${GRAPH_THEME.ui.control.activeBorder}`, background: GRAPH_THEME.ui.control.primaryBg, color: GRAPH_THEME.ui.text.strong, fontSize: 12, fontWeight: 600, cursor: "pointer", flexShrink: 0 };
const selectStyle: CSSProperties = { display: "block", width: "100%", marginTop: 6, padding: 8, borderRadius: 8, background: "#152322", border: `1px solid ${GRAPH_THEME.ui.surface.panelBorder}`, color: GRAPH_THEME.ui.text.strong };
const backdropStyle: CSSProperties = { position: "fixed", inset: 0, zIndex: 1000, display: "grid", placeItems: "center", padding: 16, background: "rgba(0,0,0,0.7)" };
const dialogStyle: CSSProperties = { display: "flex", flexDirection: "column", gap: 16, width: "min(1160px, 100%)", height: "calc(100dvh - 32px)", overflow: "hidden", padding: "clamp(12px, 2.5vw, 24px)", borderRadius: 16, border: `1px solid ${GRAPH_THEME.ui.control.activeBorder}`, background: "#111c1d", boxShadow: "0 24px 100px rgba(0,0,0,0.5)" };
const evidenceButtonStyle: CSSProperties = { display: "flex", flexDirection: "column", alignItems: "flex-start", textAlign: "left", gap: 7, padding: 11, borderRadius: 8, border: "1px solid", background: "rgba(255,255,255,0.025)", color: GRAPH_THEME.ui.text.body, cursor: "pointer" };
const statusStyle: CSSProperties = { border: "1px solid", borderRadius: 8, padding: "10px 12px", fontSize: 12, color: GRAPH_THEME.ui.text.strong, lineHeight: 1.6 };
const sourceTextStyle: CSSProperties = { margin: 0, padding: 20, minHeight: 160, maxHeight: "48vh", overflowY: "auto", whiteSpace: "pre-wrap", overflowWrap: "anywhere", lineHeight: 1.9, fontSize: 14, fontFamily: "inherit", color: GRAPH_THEME.ui.text.strong, borderRadius: 10, border: `1px solid ${GRAPH_THEME.ui.surface.panelBorder}`, background: "#0b1415" };
