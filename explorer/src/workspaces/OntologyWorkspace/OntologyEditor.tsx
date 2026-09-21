import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  addEdge,
  useNodesState,
  useEdgesState,
  MarkerType,
  Handle,
  Position,
} from "@xyflow/react";
import type { Connection, Edge, Node, OnEdgesChange, OnNodesChange, ReactFlowInstance } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  Plus,
  GitBranch,
  User,
  Shield,
  FileText,
  Layout,
  Send,
  Pencil,
  Trash2,
  ChevronDown,
} from "lucide-react";
import { loadOntologyEntityOwner, loadOntologyGraph } from "./api";
import type { OntologyEvidenceContext, OntologyGraphEdge, OntologyGraphNode } from "./api";
import { OntologyRuleEvidencePanel } from "./OntologyRuleEvidencePanel";
import { OntologyTermDetails } from "./OntologyTermDetails";
import { ClassPropertiesPanel } from "./ClassPropertiesPanel";
import { declaredRelationshipEdges, isDeclaredRelationship, relationshipEdgeLabel } from "./relationshipShapes";
import { ClassInstancesPanel } from "./ClassInstancesPanel";
import {
  canEditOwnedOntologyTerm,
  classifyNodeType,
  isEditableEntityType,
  ONTOLOGY_MINIMAP_THEME,
  resolveEditorOntology,
} from "./ontologyEditorModel";
import type { EditorEntityType, RegistryEntry } from "./ontologyEditorModel";
import { clearEntitySelection, readOntologyUrlState, writeEntitySelection } from "./ontologyUrlState";
import { useOntologySelectionFocus, type OntologyFocusRequest } from "./useOntologySelectionFocus";

type OntologyNodeData = {
  label?: string;
  type?: string;
  entityType?: EditorEntityType;
  schemaRole?: string;
  description?: string;
};

type OntologyNode = Node<OntologyNodeData>;
type OntologyEdge = Edge<Record<string, unknown>>;

const nodeTypes = {
  classNode: ({ data, selected }: { data: OntologyNodeData; selected?: boolean }) => (
    <div data-ontology-selected={selected || undefined} style={selected ? { ...classNodeStyle, border: "1px solid #f2b66d", boxShadow: "0 0 0 2px rgba(242, 182, 109, 0.45), 0 4px 18px rgba(0, 0, 0, 0.35)" } : classNodeStyle}>
      <Handle type="target" position={Position.Left} style={handleStyle} />
      <div style={classNodeHeader}>{data.label}</div>
      <div style={classNodeSub}>{data.type}</div>
      <Handle type="source" position={Position.Right} style={handleStyle} />
    </div>
  ),
};

const handleStyle: React.CSSProperties = {
  width: 8,
  height: 8,
  border: "1px solid rgba(235, 243, 255, 0.8)",
  background: "#4aa3ff",
};

const ontologyFlowThemeCss = `
  .ontology-editor-flow .react-flow__edge-textwrapper {
    pointer-events: all;
    cursor: pointer;
  }
  .ontology-editor-flow .react-flow__controls {
    overflow: hidden;
    border: 1px solid rgba(127, 208, 255, 0.2);
    border-radius: 9px;
    background: rgba(6, 13, 26, 0.96);
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.38);
  }

  .ontology-editor-flow .react-flow__controls-button {
    width: 30px;
    height: 30px;
    background: transparent;
    border-bottom-color: rgba(127, 208, 255, 0.14);
    color: #8fa8c6;
    transition: color 140ms ease, background 140ms ease;
  }

  .ontology-editor-flow .react-flow__controls-button:hover {
    background: rgba(74, 163, 255, 0.14);
    color: #ebf3ff;
  }

  .ontology-editor-flow .react-flow__controls-button:focus-visible {
    position: relative;
    z-index: 1;
    outline: 2px solid #7fd0ff;
    outline-offset: -2px;
  }

  .ontology-editor-flow .react-flow__controls-button:disabled {
    background: rgba(3, 9, 18, 0.32);
    color: #40566f;
  }
`;

const classNodeStyle: React.CSSProperties = {
  padding: "12px 16px",
  borderRadius: "8px",
  background: "linear-gradient(135deg, #172b43, #0d1c2e)",
  border: "1px solid rgba(127, 208, 255, 0.3)",
  color: "#ebf3ff",
  fontSize: "13px",
  fontWeight: "600",
  width: "200px",
  boxSizing: "border-box",
  overflowWrap: "anywhere",
  textAlign: "center",
  boxShadow: "0 4px 12px rgba(0, 0, 0, 0.2)",
};

const classNodeHeader: React.CSSProperties = {
  fontSize: "14px",
  fontWeight: "700",
  marginBottom: "4px",
  lineHeight: 1.5,
};

const classNodeSub: React.CSSProperties = {
  fontSize: "11px",
  color: "#8fa8c6",
  fontWeight: "500",
  lineHeight: 1.5,
};

interface DraftDiff {
  added_classes: string[];
  removed_classes: string[];
  modified_classes: Record<string, Record<string, any>>;
  added_properties: string[];
  removed_properties: string[];
  modified_properties: Record<string, Record<string, any>>;
  added_restrictions: Record<string, any>[];
  removed_restrictions: Record<string, any>[];
  added_axioms: Record<string, any>[];
  removed_axioms: Record<string, any>[];
  annotation_changes: Record<string, Record<string, any>>;
}

function requestedEntityUri(): string {
  return readOntologyUrlState().entityUri || "";
}

function nodeLabel(node: OntologyGraphNode): string {
  const explicit = String(node.content || node.properties?.["rdfs:label"] || "").trim();
  if (explicit && explicit !== node.id) {
    return explicit;
  }
  const trimmed = node.id.replace(/[/#]+$/, "");
  return trimmed.split("#").pop() || trimmed.split("/").pop() || node.id;
}

function classifyEditorNode(node: OntologyGraphNode): OntologyNodeData["entityType"] {
  return classifyNodeType(node.type);
}

function layoutEditorNodes(inputNodes: OntologyNode[]): OntologyNode[] {
  const properties = inputNodes.filter((node) => node.data.entityType === "property");
  const targets = inputNodes.filter((node) => (
    (node.data.entityType === "class" || node.data.entityType === "external") && node.data.schemaRole !== "provenance"
  ));
  const provenance = inputNodes.filter((node) => (node.data.entityType === "class" || node.data.entityType === "external") && node.data.schemaRole === "provenance");
  const context = inputNodes.filter((node) => (
    node.data.entityType !== "property"
    && node.data.entityType !== "class"
    && node.data.entityType !== "external"
  ));
  const columns = Math.min(3, Math.max(1, Math.ceil(Math.sqrt(targets.length))));
  const rows = Math.ceil(targets.length / columns);
  const height = Math.max(360, properties.length * 130, rows * 160, provenance.length * 160);
  const positions = new Map<string, { x: number; y: number }>();

  properties.forEach((node, index) => {
    positions.set(node.id, { x: 0, y: (height - (properties.length - 1) * 130) / 2 + index * 130 });
  });
  targets.forEach((node, index) => {
    positions.set(node.id, { x: 500 + (index % columns) * 340, y: (height - (rows - 1) * 160) / 2 + Math.floor(index / columns) * 160 });
  });
  provenance.forEach((node, index) => {
    positions.set(node.id, { x: 620 + columns * 340, y: height / 2 + (index - (provenance.length - 1) / 2) * 160 });
  });
  context.forEach((node, index) => {
    positions.set(node.id, { x: 300 + index * 220, y: height + 120 });
  });

  return inputNodes.map((node) => ({
    ...node,
    position: positions.get(node.id) || node.position,
  }));
}

function buildEditorElements(apiNodes: OntologyGraphNode[], apiEdges: OntologyGraphEdge[]) {
  const sortedNodes = [...apiNodes].sort((left, right) => {
    const typeDelta = left.type.localeCompare(right.type);
    return typeDelta || left.id.localeCompare(right.id);
  });
  const nodes = layoutEditorNodes(sortedNodes.map((node) => ({
    id: node.id,
    type: "classNode",
    position: { x: 0, y: 0 },
    data: {
      label: nodeLabel(node),
      type: node.type,
      entityType: classifyEditorNode(node),
      schemaRole: typeof node.properties?.schema_role === "string" ? node.properties.schema_role : undefined,
      description: typeof node.properties?.["rdfs:comment"] === "string" ? node.properties["rdfs:comment"] : undefined,
    },
  })));
  const nodeById = new Map(apiNodes.map((node) => [node.id, node]));
  const edges: OntologyEdge[] = declaredRelationshipEdges(apiNodes, apiEdges).map((edge, index) => {
    const provenance = edge.properties?.schema_role === "provenance"
      || nodeById.get(edge.source)?.properties?.schema_role === "provenance";
    const color = provenance ? "#91b6ba" : "#8abce3";
    return {
      id: edge.id || `${edge.source}:${edge.type}:${edge.target}:${index}`,
      source: edge.source,
      target: edge.target,
      label: relationshipEdgeLabel(edge, apiNodes),
      data: { ...edge.properties },
      type: "default",
      markerEnd: { type: MarkerType.ArrowClosed, color },
      style: { stroke: color, strokeWidth: provenance ? 1 : 1.4, strokeOpacity: provenance ? 0.55 : 0.8 },
      zIndex: -1,
      labelStyle: { fill: "#c8dcf5", fontSize: 12, fontWeight: 500 },
      labelBgStyle: { fill: "#07111f", fillOpacity: 1 },
    };
  });
  return { nodes, edges };
}

function selectedRelationshipDiagram(nodes: OntologyNode[], edges: OntologyEdge[], selected: OntologyNode | OntologyEdge | null, entire: boolean) {
  const classId = selected && "source" in selected
    ? isDeclaredRelationship(selected.data) ? selected.source : null
    : selected?.data.entityType === "class" ? selected.id : null;
  const declarations = edges.filter((edge) => isDeclaredRelationship(edge.data) && (edge.source === classId || edge.target === classId));
  if (!declarations.length || entire) return { nodes, edges, scoped: false, available: !!declarations.length };
  // In the relationship view, the property is the labelled edge. Its definition
  // opens on selection; displaying it again as an unconnected box is misleading.
  const ids = new Set(declarations.flatMap((edge) => [edge.source, edge.target]));
  const related = nodes.filter((node) => ids.has(node.id));
  const incoming = related.filter((node) => node.id !== classId && declarations.some((edge) => edge.source === node.id && edge.target === classId));
  const outgoing = related.filter((node) => node.id !== classId && !incoming.includes(node));
  const height = Math.max(0, (Math.max(incoming.length, outgoing.length) - 1) * 160);
  const centerX = incoming.length ? 560 : 0;
  return {
    scoped: true, available: true,
    nodes: related.map((node) => ({ ...node, position: node.id === classId
      ? { x: centerX, y: height / 2 }
      : incoming.includes(node) ? { x: 0, y: height / 2 + (incoming.indexOf(node) - (incoming.length - 1) / 2) * 160 }
        : { x: centerX + 560, y: height / 2 + (outgoing.indexOf(node) - (outgoing.length - 1) / 2) * 160 } })),
    edges: declarations,
  };
}

export function OntologyEditor({ evidenceContext, onJumpToGraphNode, toolbarStart }: { evidenceContext?: OntologyEvidenceContext; onJumpToGraphNode?: (nodeId: string) => void; toolbarStart?: ReactNode }) {
  const [nodes, setNodes, onNodesChange] = useNodesState<OntologyNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<OntologyEdge>([]);
  const [selectedElement, setSelectedElement] = useState<OntologyNode | OntologyEdge | null>(null);
  const selectedNodeId = selectedElement && !("source" in selectedElement) ? selectedElement.id : "";
  const selectedEdgeId = selectedElement && "source" in selectedElement ? selectedElement.id : "";
  const [entireOntology, setEntireOntology] = useState(false);
  const [hoveredEdgeId, setHoveredEdgeId] = useState<string | null>(null);
  const diagram = useMemo(() => selectedRelationshipDiagram(nodes, edges, selectedElement, entireOntology), [nodes, edges, selectedElement, entireOntology]);
  const displayedNodes = useMemo(() => diagram.nodes.map((node) => ({ ...node, selected: node.id === selectedNodeId })), [diagram.nodes, selectedNodeId]);
  const displayedEdges = useMemo(() => diagram.edges.map((edge) => ({ ...edge,
    selected: edge.id === selectedEdgeId,
    // Overview labels compete with node text. Reveal one on hover/selection;
    // keep all property labels visible in the selected class neighborhood.
    label: diagram.scoped || edge.id === selectedEdgeId || edge.id === hoveredEdgeId ? edge.label : undefined,
    style: { ...edge.style, ...(edge.id === selectedEdgeId || edge.id === hoveredEdgeId ? { strokeOpacity: 1 } : {}) },
  })), [diagram.edges, diagram.scoped, selectedEdgeId, hoveredEdgeId]);
  const [registry, setRegistry] = useState<RegistryEntry[]>([]);
  const [ontologyUri, setOntologyUri] = useState<string>("");
  const [flowInstance, setFlowInstance] = useState<ReactFlowInstance<OntologyNode, OntologyEdge> | null>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const [focusRequest, setFocusRequest] = useState<OntologyFocusRequest | null>(null);
  const relationshipFocus = useMemo(() => {
    if (!focusRequest?.nodeId) return focusRequest;
    const relatedNodeIds = edges.filter((edge) => isDeclaredRelationship(edge.data)
      && (edge.source === focusRequest.nodeId || edge.target === focusRequest.nodeId))
      .flatMap((edge) => diagram.scoped ? [edge.source, edge.target] : [edge.source, edge.target, String(edge.data!.property_uri)]);
    return relatedNodeIds.length ? { ...focusRequest, relatedNodeIds: [...new Set(relatedNodeIds)] } : focusRequest;
  }, [focusRequest, edges, diagram.scoped]);
  useOntologySelectionFocus(flowInstance, diagram.nodes, relationshipFocus, canvasRef);
  const [isLoadingGraph, setIsLoadingGraph] = useState(false);
  const [graphError, setGraphError] = useState("");
  const [schema, setSchema] = useState<{ nodes: OntologyGraphNode[]; edges: OntologyGraphEdge[] }>({ nodes: [], edges: [] });
  const [graphRevision, setGraphRevision] = useState(0);
  const [saveNotice, setSaveNotice] = useState("");
  const [unownedEntity, setUnownedEntity] = useState("");
  const [draftDiff, setDraftDiff] = useState<DraftDiff>({
    added_classes: [],
    removed_classes: [],
    modified_classes: {},
    added_properties: [],
    removed_properties: [],
    modified_properties: {},
    added_restrictions: [],
    removed_restrictions: [],
    added_axioms: [],
    removed_axioms: [],
    annotation_changes: {},
  });
  const [isSaving, setIsSaving] = useState(false);
  const [showContext, setShowContext] = useState<{ x: number; y: number; type: string; element: OntologyNode | OntologyEdge } | null>(null);
  const toolsRef = useRef<HTMLDetailsElement>(null);
  const [editing, setEditing] = useState(false);
  const readOnly = Boolean(evidenceContext?.configured && !editing);
  const businessOntology = Boolean(evidenceContext?.configured && evidenceContext.business_ontologies.includes(ontologyUri));

  useEffect(() => {
    const dismissOutside = (event: Event) => {
      const menu = toolsRef.current;
      if (menu?.open && event.target instanceof window.Node && !menu.contains(event.target)) menu.open = false;
    };
    const dismissOnEscape = (event: KeyboardEvent) => {
      const menu = toolsRef.current;
      if (event.key === "Escape" && menu?.open) {
        menu.open = false;
        menu.querySelector("summary")?.focus();
      }
    };
    document.addEventListener("pointerdown", dismissOutside);
    document.addEventListener("focusin", dismissOutside);
    document.addEventListener("keydown", dismissOnEscape);
    return () => {
      document.removeEventListener("pointerdown", dismissOutside);
      document.removeEventListener("focusin", dismissOutside);
      document.removeEventListener("keydown", dismissOnEscape);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const requested = requestedEntityUri();
    Promise.all([
      fetch("/api/ontology/registry").then((response) => (response.ok ? response.json() : [])),
      requested
        ? loadOntologyEntityOwner(requested).catch(() => undefined)
        : Promise.resolve(undefined),
    ])
      .then(([entries, ownerVerdict]: [RegistryEntry[], string | null | undefined]) => {
        if (cancelled) return;
        setRegistry(entries);
        const resolution = resolveEditorOntology(entries, requested, ownerVerdict, evidenceContext);
        // The registry default is the right landing place for "no entity asked
        // for", but not for "the backend says nothing owns the entity that was
        // asked for" — that would open an arbitrary ontology whose graph
        // excludes the entity, and report nothing about why.
        if (resolution.status === "unowned") {
          setUnownedEntity(resolution.entityUri);
          return;
        }
        setUnownedEntity("");
        const resolvedOntology = resolution.status === "resolved" ? resolution.uri : undefined;
        setOntologyUri((current) => current || resolvedOntology || (!evidenceContext?.configured ? entries[0]?.uri : "") || "");
      })
      .catch((error) => {
        console.error("Failed to load ontology registry:", error);
      });
    return () => {
      cancelled = true;
    };
  }, [evidenceContext]);

  useEffect(() => {
    if (!ontologyUri) {
      setSchema({ nodes: [], edges: [] });
      setNodes([]);
      setEdges([]);
      setSelectedElement(null);
      return;
    }

    const controller = new AbortController();
    setSchema({ nodes: [], edges: [] });
    setSelectedElement(null);
    setNodes([]);
    setEdges([]);
    setIsLoadingGraph(true);
    setGraphError("");
    loadOntologyGraph(ontologyUri, controller.signal)
      .then((payload) => {
        if (controller.signal.aborted) return;
        setSchema({ nodes: payload.nodes, edges: payload.edges });
        const elements = buildEditorElements(payload.nodes, payload.edges);
        setNodes(elements.nodes);
        setEdges(elements.edges);
        const requested = requestedEntityUri();
        const selected = elements.nodes.find((node) => node.id === requested) || null;
        setSelectedElement(selected);
        setFocusRequest((current) => current || { nodeId: selected?.id || null });
      })
      .catch((error) => {
        if (controller.signal.aborted) return;
        setNodes([]);
        setEdges([]);
        setSelectedElement(null);
        setGraphError(error instanceof Error ? error.message : "Failed to load ontology graph");
      })
      .finally(() => {
        if (!controller.signal.aborted) setIsLoadingGraph(false);
      });

    return () => controller.abort();
  }, [ontologyUri, setEdges, setNodes, graphRevision]);

  const onConnect = useCallback(
    (params: Connection) => setEdges((eds) => addEdge({ ...params, markerEnd: { type: MarkerType.ArrowClosed } }, eds)),
    [setEdges]
  );

  const addClass = useCallback(() => {
    const newId = `class_${Date.now()}`;
    const newNode: OntologyNode = {
      id: newId,
      type: "classNode",
      position: { x: Math.random() * 400, y: Math.random() * 300 },
      data: { label: "NewClass", type: "owl:Class", entityType: "class" },
    };
    setNodes((nds) => [...nds, newNode]);
    setDraftDiff((prev) => ({
      ...prev,
      added_classes: [...prev.added_classes, newId],
    }));
  }, [setNodes]);

  const addProperty = useCallback(() => {
    if (nodes.length < 2) {
      alert("Add at least two classes before creating a property edge.");
      return;
    }
    const newId = `prop_${Date.now()}`;
    const newEdge: OntologyEdge = {
      id: newId,
      source: nodes[0].id,
      target: nodes[1].id,
      label: "hasProperty",
      type: "smoothstep",
      animated: true,
    };
    setEdges((eds) => [...eds, newEdge]);
    setDraftDiff((prev) => ({
      ...prev,
      added_properties: [...prev.added_properties, newId],
    }));
  }, [nodes, setEdges]);

  const addIndividual = useCallback(() => {
    const newId = `ind_${Date.now()}`;
    const newNode: OntologyNode = {
      id: newId,
      type: "classNode",
      position: { x: Math.random() * 400, y: Math.random() * 300 },
      data: { label: "NewIndividual", type: "owl:NamedIndividual", entityType: "external" },
    };
    setNodes((nds) => [...nds, newNode]);
  }, [setNodes]);

  const addRestriction = useCallback(() => {
    setDraftDiff((prev) => ({
      ...prev,
      added_restrictions: [...prev.added_restrictions, { type: "someValuesFrom", value: "" }],
    }));
  }, []);

  const addAxiom = useCallback(() => {
    setDraftDiff((prev) => ({
      ...prev,
      added_axioms: [...prev.added_axioms, { type: "subClassOf", value: "" }],
    }));
  }, []);

  const autoLayout = useCallback(() => {
    setNodes(layoutEditorNodes(nodes));
    setFocusRequest({ nodeId: null });
  }, [nodes, setNodes]);

  const selectNode = useCallback((node: OntologyNode) => {
    setSelectedElement(node);
    setFocusRequest({ nodeId: node.id });
    writeEntitySelection(node.id);
  }, []);

  const handleNodesChange: OnNodesChange<OntologyNode> = useCallback((changes) => {
    onNodesChange(changes);
    const selected = changes.find((change) => change.type === "select" && change.selected);
    if (selected?.type === "select") {
      const node = nodes.find((candidate) => candidate.id === selected.id);
      if (node) {
        setSelectedElement(node);
        writeEntitySelection(node.id);
      }
    } else if (changes.some((change) => change.type === "select" && change.id === selectedNodeId && !change.selected)) {
      setSelectedElement(null);
      setFocusRequest(null);
      clearEntitySelection();
    }
  }, [nodes, onNodesChange, selectedNodeId]);

  const handleEdgesChange: OnEdgesChange<OntologyEdge> = useCallback((changes) => {
    onEdgesChange(changes);
    const selected = changes.find((change) => change.type === "select" && change.selected);
    if (selected?.type === "select") {
      const edge = edges.find((candidate) => candidate.id === selected.id);
      if (edge) {
        setSelectedElement(edge);
        setFocusRequest(null);
        clearEntitySelection();
      }
    } else if (changes.some((change) => change.type === "select" && change.id === selectedEdgeId && !change.selected)) {
      setSelectedElement(null);
      setFocusRequest(null);
      clearEntitySelection();
    }
  }, [edges, onEdgesChange, selectedEdgeId]);

  const saveDraft = useCallback(async () => {
    if (!ontologyUri) {
      alert("Please select an ontology first");
      return;
    }
    setIsSaving(true);
    try {
      const response = await fetch("/api/ontology/draft", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ontology_uri: ontologyUri,
          diff: draftDiff,
          author: "user",
          summary: "Visual editor changes",
        }),
      });
      if (response.ok) {
        const data = await response.json();
        alert(`Draft saved: ${data.draft_id}`);
      }
    } catch (error) {
      console.error("Failed to save draft:", error);
      alert("Failed to save draft");
    } finally {
      setIsSaving(false);
    }
  }, [ontologyUri, draftDiff]);

  const handleNodeContextMenu = useCallback((event: React.MouseEvent, node: OntologyNode) => {
    event.preventDefault();
    selectNode(node);
    setShowContext({ x: event.clientX, y: event.clientY, type: "node", element: node });
  }, [selectNode]);

  const handleEdgeContextMenu = useCallback((event: React.MouseEvent, edge: OntologyEdge) => {
    event.preventDefault();
    setSelectedElement(edge);
    setFocusRequest(null);
    setShowContext({ x: event.clientX, y: event.clientY, type: "edge", element: edge });
  }, []);

  const deleteSelected = useCallback(() => {
    const target = showContext?.element ?? selectedElement;
    if (target) {
      if ("source" in target) {
        setEdges((eds) => eds.filter((e) => e.id !== target.id));
        setDraftDiff((prev) => ({
          ...prev,
          removed_properties: [...prev.removed_properties, target.id],
        }));
      } else if (isEditableEntityType(target.data.entityType)) {
        setNodes((nds) => nds.filter((n) => n.id !== target.id));
        setDraftDiff((prev) => target.data.entityType === "property"
          ? { ...prev, removed_properties: [...prev.removed_properties, target.id] }
          : { ...prev, removed_classes: [...prev.removed_classes, target.id] });
      }
      setSelectedElement(null);
      setFocusRequest(null);
    }
    setShowContext(null);
  }, [selectedElement, setNodes, setEdges, showContext]);

  const renameSelected = useCallback(() => {
    const target = showContext?.element ?? selectedElement;
    if (target && !("source" in target) && isEditableEntityType(target.data.entityType)) {
      const newLabel = prompt("Enter new name:", String(target.data.label ?? ""));
      if (newLabel) {
        setNodes((nds) =>
          nds.map((n) => (n.id === target.id ? { ...n, data: { ...n.data, label: newLabel } } : n))
        );
        setDraftDiff((prev) => target.data.entityType === "property"
          ? {
              ...prev,
              modified_properties: { ...prev.modified_properties, [target.id]: { label: newLabel } },
            }
          : {
              ...prev,
              modified_classes: { ...prev.modified_classes, [target.id]: { label: newLabel } },
            });
      }
    }
    setShowContext(null);
  }, [selectedElement, setNodes, showContext]);

  useEffect(() => {
    const handleClick = () => setShowContext(null);
    window.addEventListener("click", handleClick);
    return () => window.removeEventListener("click", handleClick);
  }, []);

  const toolbarStyle: React.CSSProperties = {
    display: "flex",
    alignItems: "center",
    gap: "8px",
    padding: "8px 12px",
    background: "rgba(3, 9, 18, 0.92)",
    borderBottom: "1px solid rgba(140, 192, 255, 0.12)",
    flexShrink: 0,
    position: "relative",
    zIndex: 10,
  };

  const toolbarButtonStyle: React.CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    gap: "6px",
    padding: "8px 12px",
    borderRadius: "8px",
    border: "1px solid rgba(127, 208, 255, 0.18)",
    background: "rgba(74, 163, 255, 0.08)",
    color: "#ebf3ff",
    fontSize: "12px",
    fontWeight: "600",
    cursor: "pointer",
    transition: "160ms ease",
    whiteSpace: "nowrap",
    flexShrink: 0,
  };

  const selectStyle: React.CSSProperties = {
    padding: "8px 12px",
    borderRadius: "8px",
    border: "1px solid rgba(127, 208, 255, 0.18)",
    background: "rgba(3, 9, 18, 0.88)",
    color: "#ebf3ff",
    fontSize: "12px",
    minWidth: 0,
    maxWidth: "340px",
    flex: "1 1 200px",
  };

  const contextMenuStyle: React.CSSProperties = {
    position: "fixed",
    background: "rgba(9, 19, 34, 0.95)",
    border: "1px solid rgba(127, 208, 255, 0.3)",
    borderRadius: "8px",
    padding: "8px 0",
    minWidth: "180px",
    boxShadow: "0 8px 24px rgba(0, 0, 0, 0.4)",
    zIndex: 1000,
  };

  const contextItemStyle: React.CSSProperties = {
    padding: "8px 16px",
    display: "flex",
    alignItems: "center",
    gap: "10px",
    color: "#ebf3ff",
    fontSize: "13px",
    cursor: "pointer",
    transition: "160ms ease",
  };

  const detailPanelStyle: React.CSSProperties = {
    flex: businessOntology ? "0 0 380px" : "0 0 320px",
    width: businessOntology ? "380px" : "320px",
    minWidth: "280px",
    maxWidth: "45%",
    boxSizing: "border-box",
    background: "rgba(9, 19, 34, 0.95)",
    borderLeft: "1px solid rgba(140, 192, 255, 0.12)",
    padding: "20px",
    overflow: "auto",
    backdropFilter: "blur(18px)",
  };

  const changeOntology = (uri: string) => {
    setOntologyUri(uri);
    setSelectedElement(null);
    setFocusRequest(null);
    setShowContext(null);
    setUnownedEntity("");
    setEditing(false);
    clearEntitySelection();
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", background: "#07111f" }}>
      <style>{ontologyFlowThemeCss}</style>
      <div role="toolbar" aria-label="Ontology graph tools" style={toolbarStyle}>
        {toolbarStart}
        <select
          aria-label="Active ontology"
          value={ontologyUri}
          onChange={(event) => changeOntology(event.target.value)}
          style={selectStyle}
        >
          <option value="">Select ontology...</option>
          {registry.map((entry) => (
            <option key={entry.uri} value={entry.uri}>
              {entry.name || entry.uri}
            </option>
          ))}
        </select>
        <button style={toolbarButtonStyle} onClick={autoLayout}>
          <Layout size={14} />
          Auto Layout
        </button>
        {diagram.available ? <label style={{ color: "#b9d8ce", fontSize: 12, display: "flex", alignItems: "center", gap: 6 }}>
          <input type="checkbox" checked={entireOntology} onChange={(event) => {
            setEntireOntology(event.target.checked);
            setFocusRequest({ nodeId: null });
          }} />Show entire ontology
        </label> : null}
        <div style={{ flex: 1 }} />
        <details ref={toolsRef} style={{ position: "relative", color: "#8fa8c6", fontSize: 12, flexShrink: 0 }}>
          <summary style={toolbarButtonStyle}>Tools <ChevronDown size={13} /></summary>
          <div style={{ position: "absolute", top: "calc(100% + 6px)", right: 0, width: 220, display: "grid", gap: 8, padding: 12, border: "1px solid rgba(127, 208, 255, 0.2)", borderRadius: 8, background: "#091322", boxShadow: "0 8px 24px rgba(0, 0, 0, 0.4)" }} onClick={(event) => {
            if (event.target instanceof Element && event.target.closest("button:not(:disabled)") && toolsRef.current) {
              toolsRef.current.open = false;
              toolsRef.current.querySelector("summary")?.focus();
            }
          }}>
            {evidenceContext?.configured ? <label style={{ display: "flex", gap: 7, alignItems: "center", padding: "4px 0" }}>
              <input type="checkbox" checked={editing} onChange={(event) => { setEditing(event.target.checked); setShowContext(null); }} />
              Enable advanced editing
            </label> : null}
            {!readOnly ? <>
              <button style={toolbarButtonStyle} onClick={addClass}><Plus size={14} />Add Class</button>
              <button style={toolbarButtonStyle} onClick={addProperty} disabled={nodes.length < 2}><GitBranch size={14} />Add Property</button>
              <button style={toolbarButtonStyle} onClick={addIndividual}><User size={14} />Add Individual</button>
              <button style={toolbarButtonStyle} onClick={addRestriction}><Shield size={14} />Add Restriction</button>
              <button style={toolbarButtonStyle} onClick={addAxiom}><FileText size={14} />Add Axiom</button>
            </> : null}
          </div>
        </details>
        {!readOnly ? <button style={toolbarButtonStyle} onClick={saveDraft} disabled={isSaving}>
          <Send size={14} />
          {isSaving ? "Saving..." : "Save draft"}
        </button> : null}
      </div>

      <div style={{ display: "flex", flex: 1, minHeight: 0, minWidth: 0 }}>
        <div ref={canvasRef} style={{ flex: 1, minHeight: 0, minWidth: 0, position: "relative" }}>
          <ReactFlow
            className="ontology-editor-flow"
            minZoom={0.1}
            nodes={displayedNodes}
            edges={displayedEdges}
            onNodesChange={handleNodesChange}
            onEdgesChange={handleEdgesChange}
            onConnect={readOnly ? undefined : onConnect}
            nodesDraggable={!readOnly && !diagram.scoped}
            nodesConnectable={!readOnly && !diagram.scoped}
            deleteKeyCode={readOnly ? null : "Backspace"}
            onInit={setFlowInstance}
            onNodeClick={(_, node) => selectNode(node)}
            onEdgeClick={(_, edge) => { setSelectedElement(edges.find((item) => item.id === edge.id) || edge); setFocusRequest(null); }}
            onEdgeMouseEnter={(_, edge) => setHoveredEdgeId(edge.id)}
            onEdgeMouseLeave={() => setHoveredEdgeId(null)}
            elevateEdgesOnSelect={false}
            onPaneClick={() => { setSelectedElement(null); setFocusRequest(null); clearEntitySelection(); }}
            onNodeContextMenu={readOnly ? undefined : handleNodeContextMenu}
            onEdgeContextMenu={readOnly ? undefined : handleEdgeContextMenu}
            nodeTypes={nodeTypes}
            style={{ background: "#07111f" }}
          >
            <Background color="#1a2d3d" gap={20} />
            <Controls />
            <MiniMap {...ONTOLOGY_MINIMAP_THEME} />
          </ReactFlow>

          {isLoadingGraph && (
            <div style={canvasMessageStyle}>Loading ontology structure…</div>
          )}
          {!isLoadingGraph && graphError && (
            <div style={{ ...canvasMessageStyle, color: "#ff9a8d" }}>{graphError}</div>
          )}
          {!isLoadingGraph && !graphError && unownedEntity && (
            <div style={{ ...canvasMessageStyle, color: "#f2b66d" }}>
              No registered ontology owns {unownedEntity}. Pick an ontology above to start editing.
            </div>
          )}
          {!isLoadingGraph && !graphError && !unownedEntity && ontologyUri && nodes.length === 0 && (
            <div style={canvasMessageStyle}>This ontology has no editable classes or properties.</div>
          )}
          {!isLoadingGraph && !graphError && !unownedEntity && !ontologyUri && evidenceContext?.configured && (
            <div style={canvasMessageStyle}>No configured business ontology is loaded. Choose Registry in the view menu to load one, or select another ontology above.</div>
          )}

          {showContext && (
            <div style={{ ...contextMenuStyle, left: showContext.x, top: showContext.y }}>
              {"source" in showContext.element || isEditableEntityType(showContext.element.data.entityType) ? (
                <>
                  {!("source" in showContext.element) && (
                    <div style={contextItemStyle} onClick={renameSelected}>
                      <Pencil size={14} />
                      Rename
                    </div>
                  )}
                  <div style={contextItemStyle} onClick={deleteSelected}>
                    <Trash2 size={14} />
                    Delete
                  </div>
                </>
              ) : (
                <div style={{ ...contextItemStyle, cursor: "default", color: "#8fa8c6" }}>
                  This term is read-only
                </div>
              )}
            </div>
          )}
        </div>

        {selectedElement && (
          <div style={detailPanelStyle}>
            <h3 style={{ margin: "0 0 16px", color: "#ebf3ff", fontSize: "16px" }}>
              {"source" in selectedElement
                ? "Relationship Details"
                : selectedElement.data.entityType === "property"
                  ? "Property Details"
                  : selectedElement.data.entityType === "ontology"
                    ? "Ontology Details"
                    : selectedElement.data.entityType === "external"
                      ? "External Term Details"
                      : "Class Details"}
            </h3>
            {saveNotice ? <p role="status" style={{ color: "#97d8b6", fontSize: 12 }}>{saveNotice}</p> : null}
            {!("source" in selectedElement) && canEditOwnedOntologyTerm(schema.nodes.find((node) => node.id === selectedElement.id), ontologyUri) ? <>
              <OntologyTermDetails
                ontologyUri={ontologyUri}
                termUri={selectedElement.id}
                onSaved={() => {
                  setSaveNotice("Changes saved to the current session.");
                  setGraphRevision((revision) => revision + 1);
                }}
              />
            </> : <>
              <div style={{ color: "#8fa8c6", fontSize: 12, marginBottom: 4 }}>ID</div>
              <div style={{ color: "#ebf3ff", fontSize: 13, overflowWrap: "anywhere", marginBottom: 12 }}>{selectedElement.id}</div>
              {!("source" in selectedElement) ? <>
                <div style={{ color: "#ebf3ff", fontSize: 13, marginBottom: 12 }}>{selectedElement.data.label}</div>
                <div style={{ color: "#8fa8c6", fontSize: 12, marginBottom: 6 }}>Definition & source notes</div>
                <div style={{ color: "#ebf3ff", fontSize: 13, lineHeight: 1.6, whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{selectedElement.data.description || "Not declared"}</div>
                <div style={{ color: "#8fa8c6", fontSize: 12, marginTop: 12 }}>{selectedElement.data.type}</div>
              </> : null}
              {"source" in selectedElement && isDeclaredRelationship(selectedElement.data) ? <section aria-label="Declared relationship" style={{ display: "grid", gap: 10, color: "#c8dcf5", fontSize: 13 }}>
                <strong>{nodes.find((node) => node.id === selectedElement.source)?.data.label} → {String(selectedElement.label)} → {nodes.find((node) => node.id === selectedElement.target)?.data.label}</strong>
                <div>{String(selectedElement.data?.label || "")}</div>
                <div>{String(selectedElement.data?.comment || "")}</div>
                <div>Declared relationship · {selectedElement.data?.definition_source === "llm" ? "LLM draft · " : ""}{selectedElement.data?.schema_kind === "relationship_shape" ? "No minimum count" : "OWL domain / range"}</div>
                <button type="button" style={toolbarButtonStyle} onClick={() => {
                  const property = nodes.find((node) => node.id === selectedElement.data?.property_uri);
                  if (property) selectNode(property);
                }}>View property definition</button>
              </section> : null}
            </>}
            {!("source" in selectedElement) && selectedElement.data.entityType === "class" ? <ClassInstancesPanel key={`${selectedElement.id}:${graphRevision}`} classUri={selectedElement.id} onJumpToGraphNode={onJumpToGraphNode} /> : null}
            {!("source" in selectedElement) && selectedElement.data.entityType === "class" ? <ClassPropertiesPanel
              classUri={selectedElement.id}
              nodes={schema.nodes}
              edges={schema.edges}
              graphRevision={graphRevision}
              onSelectTerm={(termUri, ownerUri) => {
                if (ownerUri && ownerUri !== ontologyUri) {
                  writeEntitySelection(termUri);
                  setSelectedElement(null);
                  setFocusRequest({ nodeId: termUri });
                  setShowContext(null);
                  setUnownedEntity("");
                  setEditing(false);
                  setOntologyUri(ownerUri);
                  return;
                }
                const term = nodes.find((node) => node.id === termUri);
                if (term) selectNode(term);
              }}
            /> : null}
            {!("source" in selectedElement) && businessOntology && isEditableEntityType(selectedElement.data.entityType) ? <OntologyRuleEvidencePanel key={graphRevision} ontologyUri={ontologyUri} termUri={selectedElement.id} /> : null}
          </div>
        )}
      </div>
    </div>
  );
}

const canvasMessageStyle: React.CSSProperties = {
  position: "absolute",
  left: "50%",
  top: "50%",
  transform: "translate(-50%, -50%)",
  padding: "10px 14px",
  borderRadius: "8px",
  border: "1px solid rgba(127, 208, 255, 0.18)",
  background: "rgba(3, 9, 18, 0.9)",
  color: "#8fa8c6",
  fontSize: "13px",
  pointerEvents: "none",
};
