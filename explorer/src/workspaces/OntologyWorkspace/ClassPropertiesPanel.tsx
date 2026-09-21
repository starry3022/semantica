import { useEffect, useState, type CSSProperties } from "react";
import type { OntologyGraphEdge, OntologyGraphNode } from "./api";
import { classPropertyGroups, type ClassProperty } from "./classProperties";
import { classifyNodeType, compactNodeType } from "./ontologyEditorModel";
import { formatClassConstraint, readClassExpressions } from "./classExpressions";
import { propertyDisplayLabel } from "./propertyDisplayLabel";
import { relationshipShape } from "./relationshipShapes";
import { loadClassInstances, type ClassInstancesSnapshot, type ObservedClassProperty } from "../GraphWorkspace/instanceTypes";

type Props = {
  classUri: string;
  nodes: OntologyGraphNode[];
  edges: OntologyGraphEdge[];
  graphRevision?: number;
  onSelectTerm: (uri: string, ontologyUri?: string | null) => void;
};

type PropertyRow = {
  uri: string;
  definition?: ClassProperty;
  observed?: ObservedClassProperty;
  declared: boolean;
  incoming: boolean;
  shapes?: NonNullable<ReturnType<typeof relationshipShape>>[];
};

export function ClassPropertiesPanel(props: Props) {
  return <ClassPropertiesSession key={`${props.classUri}:${props.graphRevision ?? 0}`} {...props} />;
}

function ClassPropertiesSession({ classUri, nodes, edges, onSelectTerm }: Props) {
  const [snapshot, setSnapshot] = useState<ClassInstancesSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    loadClassInstances(classUri, 0, 1, controller.signal).then((value) => {
      if (active) setSnapshot(value);
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : "Unable to load property usage.");
    });
    return () => { active = false; controller.abort(); };
  }, [classUri]);

  const groups = classPropertyGroups(classUri, nodes, edges);
  const names = new Map(nodes.map((node) => [node.id, node.content || node.id]));
  const name = (uri: string) => names.get(uri) || uri;
  const rows = new Map<string, PropertyRow>();
  for (const [group, definitions] of Object.entries(groups)) {
    for (const definition of definitions) {
      const row = rows.get(definition.node.id) || { uri: definition.node.id, definition, declared: false, incoming: false };
      if (group === "declared") row.declared = true;
      if (group === "incoming") row.incoming = true;
      rows.set(row.uri, row);
    }
  }
  for (const observed of snapshot?.observed_properties ?? []) {
    const row = rows.get(observed.property_uri) || { uri: observed.property_uri, declared: false, incoming: false };
    if (!row.definition) {
      const node = nodes.find((candidate) => candidate.id === row.uri && classifyNodeType(candidate.type) === "property");
      if (node) row.definition = {
        node,
        domain: [...new Set(edges.filter((edge) => edge.source === row.uri && compactNodeType(edge.type) === "rdfs:domain").map((edge) => edge.target))].sort(),
        range: [...new Set(edges.filter((edge) => edge.source === row.uri && compactNodeType(edge.type) === "rdfs:range").map((edge) => edge.target))].sort(),
        domainExpressions: readClassExpressions(node.properties?.domain_expressions),
        rangeExpressions: readClassExpressions(node.properties?.range_expressions),
        inheritedFrom: [],
      };
    }
    row.observed = observed;
    rows.set(row.uri, row);
  }
  for (const edge of edges) {
    const shape = relationshipShape(edge);
    if (!shape || shape.source !== classUri) continue;
    const node = nodes.find((candidate) => candidate.id === shape.propertyUri && classifyNodeType(candidate.type) === "property");
    const row: PropertyRow = rows.get(shape.propertyUri) || { uri: shape.propertyUri, declared: false, incoming: false };
    if (!row.definition && node) row.definition = {
      node,
      domain: edges.filter((item) => item.source === node.id && compactNodeType(item.type) === "rdfs:domain").map((item) => item.target),
      range: edges.filter((item) => item.source === node.id && compactNodeType(item.type) === "rdfs:range").map((item) => item.target),
      domainExpressions: readClassExpressions(node.properties?.domain_expressions),
      rangeExpressions: readClassExpressions(node.properties?.range_expressions), inheritedFrom: [],
    };
    if (!row.shapes?.some((existing) => existing.uri === shape.uri)) row.shapes = [...(row.shapes || []), shape];
    rows.set(row.uri, row);
  }
  const properties: PropertyRow[] = [];
  const provenance: PropertyRow[] = [];
  const observedProvenance: PropertyRow[] = [];
  const references: PropertyRow[] = [];
  for (const row of rows.values()) {
    if (row.observed?.schema_role === "provenance" || row.definition?.node.properties?.schema_role === "provenance") {
      (row.declared || row.shapes?.length || row.definition?.inheritedFrom.length ? provenance : row.observed ? observedProvenance : references).push(row);
      continue;
    }
    (row.declared || row.shapes?.length || row.definition?.inheritedFrom.length || row.observed ? properties : references).push(row);
  }
  const renderRows = (items: PropertyRow[]) => items.map(({ uri, definition, observed, declared, incoming, shapes }) => {
      const label = propertyDisplayLabel(uri, definition?.node.content || observed?.label || uri);
      const owner = definition?.node.properties?.scheme_uri;
      const ontologyUri = typeof owner === "string" ? owner : observed?.ontology_uri;
      const canOpen = !!definition || !!(observed?.loaded && ontologyUri);
      const type = definition ? compactNodeType(definition.node.type) : null;
      const kind = type === "owl:DatatypeProperty" ? "Data property" : type === "owl:ObjectProperty" ? "Object property" : type;
      const missingDefinition = observed?.loaded
        ? ontologyUri ? "Definition in another ontology" : "Definition not available in this view"
        : "Definition not loaded";
      const context = [
        declared ? "Declared on this class" : null,
        shapes?.length ? "Declared relationship for this class" : null,
        definition?.inheritedFrom.length ? `Declared on parent: ${definition.inheritedFrom.map(name).join(" · ")}` : null,
        incoming ? "Class appears in range" : null,
        observed ? `Used by ${observed.instance_count} of ${snapshot!.total} ${snapshot!.total === 1 ? "instance" : "instances"}` : null,
        observed && !declared && !shapes?.length && !definition?.inheritedFrom.length ? "Observed usage only" : null,
        observed && definition && !shapes?.length && !definition.domain.length && !definition.domainExpressions.length ? "Domain not declared" : null,
        !definition ? missingDefinition : null,
      ].filter(Boolean).join(" · ");
      const comment = definition?.node.properties?.["rdfs:comment"];
      return <article key={uri} data-property-uri={uri} style={rowStyle}>
        <button type="button" aria-label={`View property ${label}`} title={uri} disabled={!canOpen} onClick={() => onSelectTerm(uri, ontologyUri)} style={{ ...buttonStyle, ...(!canOpen ? { cursor: "default", color: mutedStyle.color } : {}) }}>{label}</button>
        <div style={mutedStyle}>{context}</div>
        {shapes?.map((shape) => <div key={shape.uri} style={mutedStyle}>
          {shape.valueClasses.length > 1 ? "Target alternatives: " : "Target: "}
          {shape.valueClasses.map((target, index) => <span key={target}>
            {index ? " or " : ""}<button type="button" style={buttonStyle} onClick={() => onSelectTerm(target)}>{name(target)}</button>
          </span>)}
          {shape.llm ? " · LLM draft" : ""}
          <div>{shape.comment}</div>
        </div>)}
        {definition ? <details>
          <summary style={{ ...mutedStyle, cursor: "pointer" }}>Definition{kind ? ` · ${kind}` : ""}</summary>
          <div style={mutedStyle}>Domain: {formatClassConstraint(definition.domain, definition.domainExpressions, name)}</div>
          <div style={mutedStyle}>Range: {formatClassConstraint(definition.range, definition.rangeExpressions, name)}</div>
          {typeof comment === "string" && comment ? <div style={{ ...mutedStyle, whiteSpace: "pre-wrap" }}>{comment}</div> : null}
        </details> : null}
      </article>;
    });
  return <section aria-label="Class properties" style={sectionStyle}>
    <h4 style={headingStyle}>Properties{properties.length || snapshot?.observed_properties ? ` · ${properties.length}` : ""}</h4>
    {renderRows(properties)}
    {provenance.length ? <section aria-label="Declared provenance relationships">
      <h4 style={headingStyle}>Declared provenance relationships · {provenance.length}</h4>
      {renderRows(provenance)}
    </section> : null}
    {observedProvenance.length ? <section aria-label="Observed provenance usage">
      <h4 style={headingStyle}>Observed provenance usage · {observedProvenance.length}</h4>
      {renderRows(observedProvenance)}
    </section> : null}
    {error ? <p role="alert" style={mutedStyle}>Instance property usage unavailable: {error}</p>
      : !snapshot ? <p role="status" style={mutedStyle}>Loading instance property usage…</p>
      : snapshot.observed_properties === undefined ? <p style={mutedStyle}>Instance property usage unavailable on this server.</p>
      : !properties.length && !provenance.length && !observedProvenance.length ? <p style={mutedStyle}>No declared or observed properties in the current graph.</p> : null}
    {references.length ? <details>
      <summary style={{ ...headingStyle, cursor: "pointer" }}>Referenced as range · {references.length}</summary>
      {renderRows(references)}
    </details> : null}
    <p style={mutedStyle}>Usage does not declare a domain or make a field mandatory. Property edits apply to every class using that property.</p>
  </section>;
}

const sectionStyle: CSSProperties = { display: "grid", gap: 10, margin: "16px 0", borderTop: "1px solid #29435c", paddingTop: 14 };
const headingStyle: CSSProperties = { fontSize: 13, margin: 0, color: "#ebf3ff" };
const mutedStyle: CSSProperties = { fontSize: 12, color: "#8fa8c6", margin: 0, lineHeight: 1.6, overflowWrap: "anywhere" };
const rowStyle: CSSProperties = { display: "grid", gap: 3, padding: "6px 0", borderBottom: "1px solid #29435c" };
const buttonStyle: CSSProperties = { padding: 0, border: 0, background: "transparent", color: "#a6dcff", textAlign: "left", cursor: "pointer", fontWeight: 700, fontSize: 13, overflowWrap: "anywhere" };
