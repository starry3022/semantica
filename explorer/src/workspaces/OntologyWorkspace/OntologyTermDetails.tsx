import { useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { loadOntologyTerm, saveOntologyTerm } from "./api";
import type { OntologyTermSnapshot } from "./api";
import { formatClassConstraint } from "./classExpressions";

type Props = { ontologyUri: string; termUri: string; onSaved: () => void };
type Fields = { label: string; comment: string; parents: string; domain: string; range: string };
const fieldStyle: CSSProperties = { display: "block", width: "100%", boxSizing: "border-box", marginTop: 5, padding: 8, borderRadius: 6, border: "1px solid #36536e", background: "#07111f", color: "#ebf3ff", font: "inherit" };
const buttonStyle: CSSProperties = { padding: "7px 10px", borderRadius: 6, border: "1px solid #36536e", background: "#132a40", color: "#ebf3ff", cursor: "pointer", font: "inherit" };
const listValue = (text: string) => [...new Set(text.split(/\r?\n/).map((item) => item.trim()).filter(Boolean))];
const formFields = (term: OntologyTermSnapshot["term"]): Fields => ({ label: term.label, comment: term.comment, parents: term.parents.join("\n"), domain: term.domain.join("\n"), range: term.range.join("\n") });

export function OntologyTermDetails(props: Props) {
  return <TermDetails key={`${props.ontologyUri}\u0000${props.termUri}`} {...props} />;
}

function TermDetails({ ontologyUri, termUri, onSaved }: Props) {
  const [snapshot, setSnapshot] = useState<OntologyTermSnapshot | null>(null);
  const [draft, setDraft] = useState<Fields | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [reload, setReload] = useState(0);
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    const controller = new AbortController();
    loadOntologyTerm(ontologyUri, termUri, controller.signal)
      .then((value) => { if (!controller.signal.aborted) setSnapshot(value); })
      .catch((reason: unknown) => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Term could not be loaded."); });
    return () => { active.current = false; controller.abort(); };
  }, [ontologyUri, termUri, reload]);

  const reloadCurrent = () => {
    setSnapshot(null); setDraft(null); setError(""); setSaved(false); setReload((value) => value + 1);
  };
  const save = async () => {
    if (!snapshot || !draft || saving) return;
    setSaving(true); setError(""); setSaved(false);
    try {
      const result = await saveOntologyTerm(ontologyUri, termUri, {
        expected_revision: snapshot.revision,
        label: draft.label, comment: draft.comment,
        parents: listValue(draft.parents),
        domain: snapshot.term.domain_expressions?.length ? snapshot.term.domain : listValue(draft.domain),
        range: snapshot.term.range_expressions?.length ? snapshot.term.range : listValue(draft.range),
      });
      if (active.current) { setSnapshot(result); setDraft(null); setSaved(true); onSaved(); }
    } catch (reason) {
      if (active.current) setError(reason instanceof Error ? reason.message : "Term could not be saved.");
    } finally {
      if (active.current) setSaving(false);
    }
  };
  const field = (key: keyof Fields, label: string, multiline = true) => <label style={{ display: "block", marginBottom: 12 }}>
    {label}
    {multiline ? <textarea aria-label={label} rows={key === "comment" ? 7 : 3} style={fieldStyle} disabled={saving} value={draft?.[key] ?? ""} onChange={(event) => setDraft((value) => value && { ...value, [key]: event.target.value })} />
      : <input aria-label={label} style={fieldStyle} disabled={saving} value={draft?.[key] ?? ""} onChange={(event) => setDraft((value) => value && { ...value, [key]: event.target.value })} />}
  </label>;
  const definition = (label: string, value: string) => <div style={{ marginBottom: 12 }}><div style={{ color: "#8fa8c6", marginBottom: 5 }}>{label}</div><div style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{value || "Not declared"}</div></div>;
  const isClass = snapshot?.term.type === "owl:Class";
  const sideDefinition = (side: "domain" | "range", label: string) => {
    if (!snapshot) return null;
    const expressions = snapshot.term[`${side}_expressions`] || [];
    return definition(label, formatClassConstraint(snapshot.term[side], expressions));
  };
  const sideEditor = (side: "domain" | "range", label: string, editableLabel: string) => snapshot?.term[`${side}_expressions`]?.length
    ? sideDefinition(side, `${label} (read-only)`)
    : field(side, editableLabel);
  const hasExpressions = !!(snapshot?.term.domain_expressions?.length || snapshot?.term.range_expressions?.length);

  return <section aria-label="Term definition" style={{ color: "#ebf3ff", fontSize: 13, lineHeight: 1.5 }}>
    {definition("IRI", termUri)}
    <p style={{ color: "#8fa8c6", fontSize: 12 }}>Edits apply to the current session. They do not update the source file, publish a version, or change review status.</p>
    {error ? <><div role="alert" style={{ color: "#ffada3", overflowWrap: "anywhere", marginBottom: 8 }}>{error}</div><button style={buttonStyle} disabled={saving} onClick={reloadCurrent}>Reload current definition</button></> : null}
    {!snapshot && !error ? <p role="status">Loading term definition…</p> : null}
    {snapshot ? <>
      {definition("Type", snapshot.term.type)}
      {draft ? <form onSubmit={(event) => { event.preventDefault(); void save(); }}>
        {field("label", "Label", false)}
        {field("comment", "Definition and source notes")}
        {isClass ? field("parents", "Parent class IRIs") : <>{sideEditor("domain", "Domain", "Domain class IRIs")}{sideEditor("range", "Range", "Range IRIs")}</>}
        <p style={{ color: "#8fa8c6", fontSize: 12 }}>One IRI per line; multiple IRIs apply together (AND). Class and XSD datatype references must already be loaded. {hasExpressions ? "OWL expressions are read-only and kept unchanged. " : ""}{isClass ? "" : "Shared property edits affect all classes using this property."}</p>
        <div style={{ display: "flex", gap: 8 }}><button type="submit" style={buttonStyle} disabled={saving}>{saving ? "Saving…" : "Save changes"}</button><button type="button" style={buttonStyle} disabled={saving} onClick={() => { setDraft(null); setError(""); }}>Cancel editing</button></div>
      </form> : <>
        {definition("Label", snapshot.term.label)}
        {definition("Definition & source notes", snapshot.term.comment)}
        {isClass ? definition("Parent classes", snapshot.term.parents.join("\n")) : <>{sideDefinition("domain", "Domain")}{sideDefinition("range", "Range")}</>}
        <button style={buttonStyle} onClick={() => { setDraft(formFields(snapshot.term)); setError(""); setSaved(false); }}>{isClass ? "Edit class" : "Edit property"}</button>
      </>}
      {saved ? <p role="status" style={{ color: "#97d8b6" }}>Saved to the current session.</p> : null}
    </> : null}
  </section>;
}
