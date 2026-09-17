import { useCallback, useEffect, useState } from "react";
import { applyEntitySelection, hasOntologyUrlState, removeOntologyUrlState } from "./workspaces/OntologyWorkspace/ontologyUrlState";

const WORKSPACES = ["welcome", "explore", "analyze", "decisions", "enrich", "manage", "ontology-hub"] as const;
export type WorkspaceId = typeof WORKSPACES[number];
const WORKSPACE_PARAM = "workspace";
const HISTORY_KEY = "semanticaNavigation";

export function parseWorkspaceRoute(search: string): WorkspaceId {
  const workspace = new URLSearchParams(search).get(WORKSPACE_PARAM);
  return WORKSPACES.find(id => id === workspace) || (hasOntologyUrlState(search) ? "ontology-hub" : "welcome");
}

export function workspaceSearch(search: string, workspace: WorkspaceId, entityUri?: string): string {
  const params = new URLSearchParams(workspace === "ontology-hub" ? search : removeOntologyUrlState(search));
  params.set(WORKSPACE_PARAM, workspace);
  const next = `?${params.toString()}`;
  return workspace === "ontology-hub" && entityUri ? applyEntitySelection(next, entityUri) : next;
}

function readRoute() {
  const workspace = parseWorkspaceRoute(window.location.search);
  return {
    workspace,
    canReturnToExplorer: workspace === "ontology-hub" && window.history.state?.[HISTORY_KEY]?.returnToExplorer === true,
  };
}

/** Top-level navigation stays in this document; ontology details keep their existing URL protocol. */
export function useWorkspaceNavigation() {
  const [route, setRoute] = useState(() => ({ ...readRoute(), key: 0 }));
  const syncRoute = useCallback(() => setRoute(current => ({ ...readRoute(), key: current.key + 1 })), []);
  useEffect(() => {
    window.addEventListener("popstate", syncRoute);
    return () => window.removeEventListener("popstate", syncRoute);
  }, [syncRoute]);

  const navigate = useCallback((workspace: WorkspaceId, entityUri?: string) => {
    const search = workspaceSearch(window.location.search, workspace, entityUri);
    if (search === window.location.search) return;
    window.history.pushState({
      ...window.history.state,
      [HISTORY_KEY]: { returnToExplorer: workspace === "ontology-hub" && readRoute().workspace === "explore" },
    }, "", `${window.location.pathname}${search}${window.location.hash}`);
    syncRoute();
  }, [syncRoute]);

  const returnToExplorer = useCallback(() => {
    if (readRoute().canReturnToExplorer) window.history.back();
    else navigate("explore");
  }, [navigate]);

  return { route, navigate, returnToExplorer };
}
