import { useEffect, useId, useState, type CSSProperties } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { SourceEvidencePanel } from "../GraphWorkspace/SourceEvidencePanel";
import { loadOntologyRelatedRules, type OntologyRelatedRules } from "./api";

type Props = { ontologyUri: string; termUri: string };

export function OntologyRuleEvidencePanel(props: Props) {
  // Two concepts can share a rule. Reset the entire disclosure and source dialog.
  return <RuleEvidenceSession key={JSON.stringify([props.ontologyUri, props.termUri])} {...props} />;
}

function RuleEvidenceSession({ ontologyUri, termUri }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [result, setResult] = useState<OntologyRelatedRules | null>(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<{ nodeId: string; evidenceId: string } | null>(null);
  const regionId = useId();

  useEffect(() => {
    if (!expanded) return;
    const controller = new AbortController();
    void loadOntologyRelatedRules(ontologyUri, termUri, controller.signal).then((payload) => {
      if (!controller.signal.aborted) setResult(payload);
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Rule evidence could not be loaded.");
    });
    return () => controller.abort();
  }, [expanded, ontologyUri, termUri]);

  return (
    <section aria-label="Related rules and evidence" style={panelStyle}>
      <button
        type="button"
        aria-expanded={expanded}
        aria-controls={regionId}
        style={{ ...buttonStyle, fontWeight: 700, display: "flex", alignItems: "center", gap: 6 }}
        onClick={() => { setExpanded(!expanded); setSelected(null); setResult(null); setError(""); }}
      >
        {expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
        Related rules & evidence{result ? ` · ${result.associations.length}` : ""}
      </button>
      {expanded ? (
        <div id={regionId} role="region" aria-label="Related rule citations" style={{ display: "grid", gap: 12 }}>
          {error ? <p role="alert" style={warningStyle}>{error}</p> : !result ? <p role="status" style={mutedStyle}>Loading related rule evidence…</p> : <>
            <p style={mutedStyle}>{result.notice || "Candidate associations from source citations. They do not establish business approval or complete coverage."}</p>
            {result.anchors.length ? <div aria-label="Source anchor status" style={{ display: "grid", gap: 6 }}>
              {result.anchors.map((anchor, index) => (
                <div key={`${anchor.term_uri}:${index}`} style={mutedStyle}>
                  <strong>{anchor.label || anchor.term_uri}</strong>: {anchor.status.replaceAll("_", " ")}
                  {anchor.reason ? <div style={warningStyle}>{anchor.reason}</div> : null}
                </div>
              ))}
            </div> : null}
            {result.evidence_issues?.length ? <div aria-label="Unavailable rule evidence" style={{ display: "grid", gap: 6 }}>
              {result.evidence_issues.map((issue) => <div key={issue.id} style={warningStyle}>
                <div>{issue.clause_id || issue.id} · {issue.status.replaceAll("_", " ")}</div>
                {issue.reason ? <div>{issue.reason}</div> : null}
              </div>)}
            </div> : null}
            {result.status !== "ready" ? <p style={warningStyle}>
              {result.status === "unconfigured" ? "Rule evidence is not configured for this ontology." : "Rule evidence is unavailable for this term."}
            </p> : !result.associations.length ? <p style={mutedStyle}>No rules with verified source overlap are linked to this term.</p> : result.associations.map((rule) => (
              <article key={rule.node_id} aria-label={rule.label || rule.node_id} style={ruleStyle}>
                <h4 style={{ margin: 0, fontSize: 13, overflowWrap: "anywhere" }}>{rule.label || rule.node_id}</h4>
                <div style={mutedStyle}>Fact: {rule.fact_status || "Unknown"} · Review: {rule.review_status || "Unknown"}{rule.modality ? ` · ${rule.modality}` : ""}</div>
                {rule.evidence.map((evidence) => (
                  <div key={evidence.id} style={{ display: "grid", gap: 5 }}>
                    <button
                      type="button"
                      aria-pressed={selected?.nodeId === rule.node_id && selected.evidenceId === evidence.id}
                      style={{ ...buttonStyle, textAlign: "left", display: "grid", gap: 6 }}
                      onClick={() => setSelected({ nodeId: rule.node_id, evidenceId: evidence.id })}
                    >
                      <strong>{evidence.role === "primary" ? "Primary" : evidence.role === "supporting" ? "Supporting" : "Evidence"} · {evidence.clause_id || "Unknown clause"}</strong>
                      <span style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{evidence.quote}</span>
                    </button>
                    {evidence.links.map((link, index) => (
                      <div key={`${link.term_uri}:${index}`} style={mutedStyle}>
                        {link.kind === "property" ? `Via property: ${link.label || link.term_uri}${link.relation ? ` (${link.relation})` : ""}` : "Direct term citation"}
                      </div>
                    ))}
                  </div>
                ))}
                {selected?.nodeId === rule.node_id ? <SourceEvidencePanel kind="node" id={rule.node_id} initialEvidenceId={selected.evidenceId} /> : null}
              </article>
            ))}
          </>}
        </div>
      ) : null}
    </section>
  );
}

const panelStyle: CSSProperties = { borderTop: "1px solid var(--ws-border, #29435c)", paddingTop: 12, display: "grid", gap: 12, color: "var(--ws-text, #ebf3ff)" };
const buttonStyle: CSSProperties = { border: "1px solid var(--ws-border, #29435c)", borderRadius: 7, padding: "9px 10px", background: "rgba(74,163,255,0.08)", color: "inherit", cursor: "pointer", fontSize: 12 };
const mutedStyle: CSSProperties = { fontSize: 12, lineHeight: 1.55, color: "var(--ws-text-muted, #8fa8c6)", margin: 0, overflowWrap: "anywhere" };
const warningStyle: CSSProperties = { ...mutedStyle, color: "#f2b66d" };
const ruleStyle: CSSProperties = { display: "grid", gap: 8, padding: 10, border: "1px solid var(--ws-border, #29435c)", borderRadius: 8, minWidth: 0 };
