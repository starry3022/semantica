import { useCallback, useEffect, useRef, useState } from "react";
import { AlignmentsTab } from "./AlignmentsTab";
import { HealthTab } from "./HealthTab";
import { OntologyManager } from "./OntologyManager";
import { OntologyEditor } from "./OntologyEditor";
import { ShaclStudio } from "./ShaclStudio";
import { VersionsTab } from "./VersionsTab";
import { readOntologyUrlState, writeEntitySelection, writeTab } from "./ontologyUrlState";
import { initialOntologyTab, type OntologyTab } from "./ontologyEditorModel";
import { loadOntologyEvidenceContext, type OntologyEvidenceContext } from "./api";

export type OntologyHubTab = OntologyTab;

const TABS: { id: OntologyHubTab; label: string }[] = [
  { id: "editor", label: "Graph" },
  { id: "registry", label: "Registry" },
  { id: "versions", label: "Versions" },
  { id: "alignments", label: "Alignments" },
  { id: "health", label: "Health" },
  { id: "shacl", label: "SHACL" },
];

function readInitialTab(): OntologyHubTab {
  return initialOntologyTab(readOntologyUrlState(), false);
}

interface OntologyWorkspaceProps {
  onJumpToGraphNode?: (nodeId: string) => void;
}

export function OntologyWorkspace({ onJumpToGraphNode }: OntologyWorkspaceProps) {
  const [activeTab, setActiveTab] = useState<OntologyHubTab>(readInitialTab);
  const [evidenceContext, setEvidenceContext] = useState<OntologyEvidenceContext | null>(null);
  const [contextError, setContextError] = useState("");
  const initialUrl = useRef(readOntologyUrlState());
  const userSelectedTab = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    void loadOntologyEvidenceContext(controller.signal).then((context) => {
      if (controller.signal.aborted) return;
      setEvidenceContext(context);
      if (!userSelectedTab.current) {
        const tab = initialOntologyTab(initialUrl.current, context.configured);
        setActiveTab(tab);
      }
    }).catch(() => {
      if (controller.signal.aborted) return;
      setEvidenceContext({ configured: false, business_ontologies: [], support_ontologies: [] });
      setContextError("Business evidence context could not be loaded. The ontology registry remains available.");
    });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    writeTab(activeTab);
  }, [activeTab]);

  const handleTabChange = useCallback((tab: OntologyHubTab) => {
    userSelectedTab.current = true;
    setActiveTab(tab);
  }, []);

  const handleFixInEditor = useCallback((entityUri: string) => {
    userSelectedTab.current = true;
    writeEntitySelection(entityUri);
    setActiveTab("editor");
  }, []);

  const viewNavigation = <select
    aria-label="Ontology view"
    value={activeTab}
    onChange={(event) => handleTabChange(event.target.value as OntologyHubTab)}
    style={{ padding: "8px 10px", borderRadius: 8, border: "1px solid var(--ws-border)", background: "var(--ws-surface)", color: "var(--ws-text)", fontSize: 12, flexShrink: 0 }}
  >{TABS.map((tab) => <option key={tab.id} value={tab.id}>{tab.label}</option>)}</select>;

  const renderTab = () => {
    switch (activeTab) {
      case "registry":
        return <OntologyManager />;
      case "editor":
        return <OntologyEditor toolbarStart={viewNavigation} evidenceContext={evidenceContext || undefined} onJumpToGraphNode={onJumpToGraphNode} />;
      case "versions":
        return <VersionsTab />;
      case "alignments":
        return <AlignmentsTab />;
      case "health":
        return <HealthTab onFixInEditor={handleFixInEditor} />;
      case "shacl":
        return <ShaclStudio onJumpToNode={onJumpToGraphNode} />;
    }
  };

  return (
    <div className="ws-page">
      {activeTab !== "editor" || !evidenceContext ? <div style={{ display: "flex", padding: "8px 12px", borderBottom: "1px solid var(--ws-border)", flexShrink: 0 }}>{viewNavigation}</div> : null}
      {contextError ? <div role="status" style={{ padding: "8px 16px", color: "#f2b66d", fontSize: 12 }}>{contextError}</div> : null}
      <div style={{ flex: 1, minHeight: 0, overflow: "hidden" }}>{evidenceContext ? renderTab() : <div role="status" style={{ padding: 20 }}>Loading ontology context…</div>}</div>
    </div>
  );
}
