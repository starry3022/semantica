import { useEffect, useRef, type RefObject } from "react";
import type { FitViewOptions, Viewport } from "@xyflow/react";

export type OntologyFocusRequest = { nodeId: string | null };
export interface OntologyFocusFlow {
  viewportInitialized: boolean;
  getInternalNode: (id: string) => { measured?: { width?: number; height?: number }; internals: { positionAbsolute: { x: number; y: number } } } | undefined;
  setViewport: (viewport: Viewport, options?: { duration?: number }) => Promise<boolean>;
  fitView: (options?: FitViewOptions) => Promise<boolean>;
}

export function useOntologySelectionFocus(
  flow: OntologyFocusFlow | null,
  nodes: readonly { id: string }[],
  request: OntologyFocusRequest | null,
  container: RefObject<HTMLElement | null>,
) {
  const completed = useRef<OntologyFocusRequest | null>(null);
  useEffect(() => {
    const element = container.current;
    if (!flow?.viewportInitialized || !nodes.length || !request || !element || completed.current === request) return;
    let frame = 0;
    let cancelled = false;
    const focus = () => {
      frame = 0;
      if (cancelled || completed.current === request) return;
      const { width, height } = element.getBoundingClientRect();
      if (!(width > 0 && height > 0)) return;
      const targets = request.nodeId ? [request.nodeId] : nodes.map((node) => node.id);
      const measured = targets.map((id) => flow.getInternalNode(id));
      if (measured.some((node) => !(Number(node?.measured?.width) > 0 && Number(node?.measured?.height) > 0))) return;
      if (request.nodeId) {
        const node = measured[0]!;
        const nodeWidth = node.measured!.width!;
        const nodeHeight = node.measured!.height!;
        const { x, y } = node.internals.positionAbsolute;
        if (![x, y, nodeWidth, nodeHeight, width, height].every(Number.isFinite)) return;
        const zoom = Math.max(0.1, Math.min(1.1, (width - 96) / nodeWidth, (height - 96) / nodeHeight));
        // Use the actual remaining canvas, after the detail panel has laid out.
        // ReactFlow's stored dimensions may still be awaiting its resize observer.
        completed.current = request;
        void flow.setViewport({ x: width / 2 - (x + nodeWidth / 2) * zoom, y: height / 2 - (y + nodeHeight / 2) * zoom, zoom }, { duration: 320 });
      } else {
        completed.current = request;
        void flow.fitView({ padding: 0.22, duration: 320, maxZoom: 1.25 });
      }
    };
    const schedule = () => {
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(focus);
    };
    const observer = new ResizeObserver(schedule);
    observer.observe(element);
    schedule();
    return () => {
      cancelled = true;
      observer.disconnect();
      window.cancelAnimationFrame(frame);
    };
  }, [flow, nodes, request, container]);
}
