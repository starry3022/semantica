import type { GraphDisplayResult } from "./graphSceneState";
import type { DeclaredInstanceType, InstanceTypesSnapshot } from "./instanceTypes";

/** Add selected-node class references after aggregation and neighborhood limiting. */
export function projectInstanceTypes(
  base: GraphDisplayResult,
  snapshot: InstanceTypesSnapshot | null,
  source: GraphDisplayResult["graph"],
) {
  const links = new Map<string, DeclaredInstanceType>();
  const classReferences = new Set<string>();
  if (!snapshot?.types.length || !base.graph.hasNode(snapshot.node_id)) {
    return { ...base, links, classReferences };
  }
  const display = base.graph.copy();
  const anchor = display.getNodeAttributes(snapshot.node_id);
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  display.forEachNode((_id, attributes) => {
    const x = Number(attributes.x) || 0, y = Number(attributes.y) || 0;
    minX = Math.min(minX, x); maxX = Math.max(maxX, x);
    minY = Math.min(minY, y); maxY = Math.max(maxY, y);
  });
  const radius = Math.max(6, (maxX - minX + maxY - minY) / 4);
  snapshot.types.forEach((type, index) => {
    if (type.class_uri === snapshot.node_id) return;
    if (!display.hasNode(type.class_uri)) {
      const attrs = source.hasNode(type.class_uri) ? source.getNodeAttributes(type.class_uri) : null;
      const angle = -Math.PI / 3 + index * Math.PI * 2 / Math.max(snapshot.types.length, 3);
      display.addNode(type.class_uri, {
        ...attrs,
        x: (Number(anchor.x) || 0) + Math.cos(angle) * radius,
        y: (Number(anchor.y) || 0) + Math.sin(angle) * radius,
        label: type.loaded ? type.label : `${type.label} (class not loaded)`,
        content: type.label,
        nodeType: "Class reference",
        color: "#bc8cff", baseColor: "#bc8cff", size: 10,
        properties: { ...attrs?.properties, __classReference: true },
        labelVisibilityPolicy: "always",
      });
      classReferences.add(type.class_uri);
    }
    const prefix = `__instance_type__:${JSON.stringify([snapshot.node_id, type.class_uri])}`;
    let edgeId = prefix;
    while (display.hasEdge(edgeId) || source.hasEdge(edgeId)) edgeId += ":reference";
    display.addDirectedEdgeWithKey(edgeId, snapshot.node_id, type.class_uri, {
      edgeType: "rdf:type", weight: 1,
      color: "#bc8cff", baseColor: "#bc8cff", size: 2, type: "arrow",
      edgeVariant: "parallelCurve", visualPriority: 1,
      rawEdgeIds: [], properties: { __typeReference: true },
    });
    links.set(edgeId, type);
  });
  return {
    graph: display,
    state: {
      ...base.state,
      selectedVisibleNeighborIds: [...new Set([...base.state.selectedVisibleNeighborIds, ...[...links.values()].map(type => type.class_uri)])],
    },
    meta: { ...base.meta, layoutMode: "owned" as const, positionSource: "display" as const, tracksStoreNodePositions: false, hasSyntheticNodes: true },
    links,
    classReferences,
  };
}
