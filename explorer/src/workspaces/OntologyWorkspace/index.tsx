import { useCallback, useEffect, useRef, useState } from "react";
import {
  BookMarked,
  GitMerge,
  HeartPulse,
  Layers,
  Shield,
  Sliders,
} from "lucide-react";
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

const TABS: { id: OntologyHubTab; label: string; icon: typeof GitMerge }[] = [
  { id: "registry", label: "Registry", icon: BookMarked },
  { id: "editor", label: "Editor", icon: Sliders },
  { id: "versions", label: "Versions", icon: Layers },
  { id: "alignments", label: "Alignments", icon: GitMerge },
  { id: "health", label: "Health", icon: HeartPulse },
  { id: "shacl", label: "SHACL", icon: Shield },
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
  const [advancedOpen, setAdvancedOpen] = useState(false);
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
        setAdvancedOpen(tab !== "editor");
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

  const renderTab = () => {
    switch (activeTab) {
      case "registry":
        return <OntologyManager />;
      case "editor":
        return <OntologyEditor evidenceContext={evidenceContext || undefined} onJumpToGraphNode={onJumpToGraphNode} />;
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

  const tabButton = ({ id, label, icon: Icon }: (typeof TABS)[number]) => {
    const active = activeTab === id;
    return <button
      key={id}
      onClick={() => handleTabChange(id)}
      aria-pressed={active}
      style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "6px 13px", borderRadius: 999, border: `1px solid ${active ? "var(--ws-border-strong)" : "transparent"}`, background: active ? "var(--ws-accent-soft)" : "transparent", color: active ? "var(--ws-text)" : "var(--ws-text-muted)", fontSize: 12, fontWeight: 600, cursor: "pointer", transition: "160ms ease" }}
    ><Icon size={13} />{evidenceContext?.configured && id === "editor" ? "Business graph" : label}</button>;
  };

  return (
    <div className="ws-page">
      {/* Internal sub-tab bar */}
      <div style={{ display: "flex", gap: 4, padding: "8px 16px", borderBottom: "1px solid var(--ws-border)", background: "rgba(0,0,0,0.18)", flexShrink: 0, flexWrap: "wrap" }}>
        {evidenceContext?.configured ? <>
          {TABS.filter((tab) => tab.id === "editor").map(tabButton)}
          <details open={advancedOpen} onToggle={(event) => setAdvancedOpen(event.currentTarget.open)} style={{ color: "var(--ws-text-muted)", fontSize: 12 }}>
            <summary style={{ cursor: "pointer", padding: "6px 13px" }}>Advanced ontology tools</summary>
            <div style={{ display: "flex", gap: 4, flexWrap: "wrap", paddingTop: 6 }}>{TABS.filter((tab) => tab.id !== "editor").map(tabButton)}</div>
          </details>
        </> : TABS.map(tabButton)}
      </div>
      {contextError ? <div role="status" style={{ padding: "8px 16px", color: "#f2b66d", fontSize: 12 }}>{contextError}</div> : null}
      <div style={{ flex: 1, minHeight: 0, overflow: "hidden" }}>{evidenceContext ? renderTab() : <div role="status" style={{ padding: 20 }}>Loading ontology context…</div>}</div>
    </div>
  );
}
