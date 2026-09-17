import type { CSSProperties } from "react";
import { GRAPH_THEME } from "./graphTheme";

const groups = ["Source", "Context & evidence", "Review & status", "Other"] as const;

function propertyGroup(key: string): (typeof groups)[number] {
  const name = key.toLowerCase();
  if (name === "status" || name.endsWith("_status") || name.startsWith("review")) return "Review & status";
  if (/^(source|provenance)(_|$)/.test(name)) return "Source";
  if (/^(context|quote|evidence)(_|$)/.test(name) || ["clause_id", "start_char", "end_char"].includes(name)) return "Context & evidence";
  return "Other";
}

export function RelationshipProperties({ properties }: { properties: Record<string, unknown> }) {
  const entries = Object.entries(properties).sort(([left], [right]) => left.localeCompare(right));
  return (
    <section aria-label="Relationship properties" style={{ minWidth: 0 }}>
      {entries.length ? (
        <details>
          <summary aria-label="View all relationship properties" style={{ color: GRAPH_THEME.ui.text.strong, fontSize: 13, fontWeight: 700, cursor: "pointer" }}>
            Properties · {entries.length} <span style={{ color: GRAPH_THEME.ui.text.muted, fontWeight: 400 }}>— View all / collapse</span>
          </summary>
          <div role="region" aria-label="All relationship properties" tabIndex={0} className="hud-scrollbar" style={listStyle}>
            {groups.map((group) => {
              const items = entries.filter(([key]) => propertyGroup(key) === group);
              return items.length ? (
                <section key={group} aria-label={`${group} properties`} style={{ minWidth: 0 }}>
                  <h3 style={{ color: GRAPH_THEME.ui.text.muted, fontSize: 12, margin: "0 0 8px" }}>{group}</h3>
                  <dl style={{ display: "grid", gap: 8, margin: 0 }}>
                    {items.map(([key, value]) => (
                      <div key={key} style={propertyStyle}>
                        <dt style={{ color: GRAPH_THEME.ui.text.muted, fontSize: 11, overflowWrap: "anywhere" }}>{key}</dt>
                        <dd style={valueStyle}>
                          {typeof value === "string"
                            ? value.length ? value : '""'
                            : typeof value === "object" ? JSON.stringify(value, null, 2) : String(value)}
                        </dd>
                      </div>
                    ))}
                  </dl>
                </section>
              ) : null;
            })}
          </div>
        </details>
      ) : <div style={{ color: GRAPH_THEME.ui.text.muted, fontSize: 12 }}>No properties recorded for this relationship.</div>}
    </section>
  );
}

const listStyle: CSSProperties = {
  display: "grid",
  gap: 16,
  maxHeight: 320,
  overflowY: "auto",
  padding: 2,
  marginTop: 8,
};

const propertyStyle: CSSProperties = {
  minWidth: 0,
  borderRadius: 10,
  padding: 10,
  background: "rgba(255, 255, 255, 0.03)",
  border: `1px solid ${GRAPH_THEME.ui.surface.panelBorder}`,
};

const valueStyle: CSSProperties = {
  color: GRAPH_THEME.ui.text.body,
  fontSize: 12,
  lineHeight: 1.6,
  margin: "4px 0 0",
  whiteSpace: "pre-wrap",
  overflowWrap: "anywhere",
};
