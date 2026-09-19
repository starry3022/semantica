import type { CSSProperties } from "react";
import type { OntologyGraphEdge, OntologyGraphNode } from "./api";
import { classPropertyGroups, type ClassProperty } from "./classProperties";
import { compactNodeType } from "./ontologyEditorModel";
import { formatClassConstraint } from "./classExpressions";

type Props = {
  classUri: string;
  nodes: OntologyGraphNode[];
  edges: OntologyGraphEdge[];
  onSelectTerm: (uri: string) => void;
};

export function ClassPropertiesPanel({ classUri, nodes, edges, onSelectTerm }: Props) {
  const groups = classPropertyGroups(classUri, nodes, edges);
  const names = new Map(nodes.map((node) => [node.id, node.content || node.id]));
  const name = (uri: string) => names.get(uri) || uri;
  const rows = (items: ClassProperty[]) => items.map(({ node, domain, range, domainExpressions, rangeExpressions, inheritedFrom }) => <article key={node.id} style={rowStyle}>
    <button type="button" aria-label={`View property ${name(node.id)}`} onClick={() => onSelectTerm(node.id)} style={buttonStyle}>{name(node.id)}</button>
    <div style={mutedStyle}>{compactNodeType(node.type) === "owl:DatatypeProperty" ? "Data property" : compactNodeType(node.type) === "owl:ObjectProperty" ? "Object property" : compactNodeType(node.type)}</div>
    <div style={mutedStyle}>Domain: {formatClassConstraint(domain, domainExpressions, name)}</div>
    <div style={mutedStyle}>Range: {formatClassConstraint(range, rangeExpressions, name)}</div>
    {inheritedFrom.length ? <div style={mutedStyle}>Declared on parent: {inheritedFrom.map(name).join(" · ")}</div> : null}
    {typeof node.properties?.["rdfs:comment"] === "string" && node.properties["rdfs:comment"] ? <details>
      <summary style={{ ...mutedStyle, cursor: "pointer" }}>Definition & source notes</summary>
      <div style={{ ...mutedStyle, whiteSpace: "pre-wrap" }}>{node.properties["rdfs:comment"]}</div>
    </details> : null}
  </article>);
  return <section aria-label="Class properties" style={sectionStyle}>
    <h4 style={headingStyle}>Declared properties · {groups.declared.length}</h4>
    <p style={mutedStyle}>Properties whose domain includes this class. Open a property to inspect or edit its definition.</p>
    {groups.declared.length ? rows(groups.declared) : <p style={mutedStyle}>No properties are declared directly for this class in the loaded schema.</p>}
    {groups.inherited.length ? <>
      <h4 style={headingStyle}>Inherited properties · {groups.inherited.length}</h4>
      {rows(groups.inherited)}
    </> : null}
    {groups.incoming.length ? <details>
      <summary style={{ ...headingStyle, cursor: "pointer" }}>Referenced as range · {groups.incoming.length}</summary>
      <div style={{ display: "grid", gap: 8, marginTop: 8 }}>{rows(groups.incoming)}</div>
    </details> : null}
    <p style={mutedStyle}>Domain and range describe the schema; they do not make a field mandatory. Shared property edits apply to every class using that property.</p>
  </section>;
}

const sectionStyle: CSSProperties = { display: "grid", gap: 10, margin: "16px 0", borderTop: "1px solid #29435c", paddingTop: 14 };
const headingStyle: CSSProperties = { fontSize: 13, margin: 0, color: "#ebf3ff" };
const mutedStyle: CSSProperties = { fontSize: 12, color: "#8fa8c6", margin: 0, lineHeight: 1.6, overflowWrap: "anywhere" };
const rowStyle: CSSProperties = { display: "grid", gap: 5, padding: 10, borderRadius: 8, border: "1px solid #29435c" };
const buttonStyle: CSSProperties = { padding: 0, border: 0, background: "transparent", color: "#a6dcff", textAlign: "left", cursor: "pointer", fontWeight: 700, fontSize: 13, overflowWrap: "anywhere" };
