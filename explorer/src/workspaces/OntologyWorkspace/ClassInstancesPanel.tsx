import { useEffect, useState, type CSSProperties } from "react";
import { describeTypeBasis, loadClassInstances, type ClassInstancesSnapshot } from "../GraphWorkspace/instanceTypes";

interface ClassInstancesPanelProps {
  classUri: string;
  onJumpToGraphNode?: (nodeId: string) => void;
}

export function ClassInstancesPanel(props: ClassInstancesPanelProps) {
  return <ClassInstancesSession key={props.classUri} {...props} />;
}

function ClassInstancesSession({ classUri, onJumpToGraphNode }: ClassInstancesPanelProps) {
  const [expanded, setExpanded] = useState(false);
  const [skip, setSkip] = useState(0);
  return <section aria-label="Class instances" style={panelStyle}>
    <button type="button" aria-expanded={expanded} style={headingButtonStyle} onClick={() => setExpanded((value) => !value)}>Declared instances</button>
    {expanded ? <>
      <p style={noteStyle}>Evidence associations are not instance declarations. This list shows explicit types only.</p>
      <ClassInstancesPage key={skip} classUri={classUri} skip={skip} onPageChange={setSkip} onJumpToGraphNode={onJumpToGraphNode} />
    </> : null}
  </section>;
}

function ClassInstancesPage({ classUri, skip, onPageChange, onJumpToGraphNode }: ClassInstancesPanelProps & { skip: number; onPageChange: (skip: number) => void }) {
  const limit = 20;
  const [snapshot, setSnapshot] = useState<ClassInstancesSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    void loadClassInstances(classUri, skip, limit, controller.signal).then(
      (value) => { if (active) setSnapshot(value); },
      (cause: unknown) => { if (active) setError(cause instanceof Error ? cause.message : "Unable to load declared instances."); },
    );
    return () => { active = false; controller.abort(); };
  }, [classUri, skip]);

  if (error) return <p role="alert" style={noteStyle}>{error}</p>;
  if (!snapshot) return <p role="status" style={noteStyle}>Loading declared instances…</p>;
  return <>
    <p style={noteStyle}>{snapshot.total} declared instance{snapshot.total === 1 ? "" : "s"}</p>
    {snapshot.instances.length === 0 ? <p style={noteStyle}>{snapshot.total === 0 ? "No declared instances in the current graph." : "No declared instances on this page."}</p> : <ul style={listStyle}>
      {snapshot.instances.map((instance) => <li key={instance.node_id} style={itemStyle}>
        <strong>{instance.label}</strong>
        <code style={idStyle}>{instance.node_id}</code>
        {instance.basis.map((basis, index) => <div style={noteStyle} key={`${basis.kind}:${basis.edge_id ?? index}`}>{describeTypeBasis(basis)}</div>)}
        <button type="button" aria-label={`Open instance ${instance.label}`} style={buttonStyle} disabled={!onJumpToGraphNode} onClick={() => onJumpToGraphNode?.(instance.node_id)}>Open instance</button>
      </li>)}
    </ul>}
    {snapshot.total > limit || skip > 0 ? <div style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: 8, marginTop: 10 }}>
      <button type="button" aria-label="Previous instances" style={buttonStyle} disabled={skip === 0} onClick={() => onPageChange(Math.max(0, skip - limit))}>Previous</button>
      <span style={noteStyle}>{snapshot.instances.length ? skip + 1 : 0}–{skip + snapshot.instances.length} of {snapshot.total}</span>
      <button type="button" aria-label="Next instances" style={buttonStyle} disabled={skip + limit >= snapshot.total} onClick={() => onPageChange(skip + limit)}>Next</button>
    </div> : null}
  </>;
}

const panelStyle: CSSProperties = { borderTop: "1px solid rgba(127, 208, 255, 0.18)", paddingTop: 14, marginTop: 16, color: "#ebf3ff" };
const headingButtonStyle: CSSProperties = { padding: 0, color: "#ebf3ff", border: 0, background: "transparent", fontSize: 13, fontWeight: 600, cursor: "pointer", textAlign: "left" };
const noteStyle: CSSProperties = { margin: "6px 0", color: "#8fa8c6", fontSize: 12, lineHeight: 1.5, overflowWrap: "anywhere" };
const listStyle: CSSProperties = { listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 10 };
const itemStyle: CSSProperties = { padding: 10, background: "rgba(3, 9, 18, 0.4)", borderRadius: 8, fontSize: 13 };
const idStyle: CSSProperties = { display: "block", color: "#8fa8c6", marginTop: 4, fontSize: 11, overflowWrap: "anywhere" };
const buttonStyle: CSSProperties = { padding: "5px 9px", borderRadius: 6, border: "1px solid rgba(127, 208, 255, 0.2)", background: "transparent", color: "#ebf3ff", fontSize: 12, cursor: "pointer" };
