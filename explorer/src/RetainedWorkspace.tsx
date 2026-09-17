import { useState, type ReactNode } from "react";
import { WorkspaceActivityContext } from "./WorkspaceActivityContext";

/** Keep a visited canvas and its geometry intact while removing it from interaction. */
export function RetainedWorkspace({ active, children }: { active: boolean; children: ReactNode }) {
  const [visited, setVisited] = useState(active);
  if (active && !visited) setVisited(true);
  if (!active && !visited) return null;

  return <WorkspaceActivityContext.Provider value={active}><div
    aria-hidden={!active}
    inert={!active}
    // The timeline sets visibility on its own children; opacity isolates the entire layer.
    style={{ position: "absolute", inset: 0, display: "flex", visibility: active ? "visible" : "hidden", opacity: active ? 1 : 0 }}
  >{children}</div></WorkspaceActivityContext.Provider>;
}
