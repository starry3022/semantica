import { useEffect, useState } from "react";
import { loadInstanceTypes, type InstanceTypesSnapshot } from "./instanceTypes";

/** A response belongs to one node and one graph revision, including errors. */
export function useInstanceTypes(nodeId: string, graphVersion: number) {
  const key = JSON.stringify([nodeId, graphVersion]);
  const [result, setResult] = useState<{ key: string; snapshot: InstanceTypesSnapshot | null; error: string | null } | null>(null);
  useEffect(() => {
    if (!nodeId) return;
    const controller = new AbortController();
    let active = true;
    loadInstanceTypes(nodeId, controller.signal).then(
      snapshot => { if (active) setResult({ key, snapshot, error: null }); },
      error => { if (active) setResult({ key, snapshot: null, error: error instanceof Error ? error.message : "Class information unavailable." }); },
    );
    return () => { active = false; controller.abort(); };
  }, [key, nodeId]);
  const current = nodeId && result?.key === key ? result : null;
  return {
    snapshot: current?.snapshot ?? null,
    error: current?.error ?? null,
    loading: Boolean(nodeId && !current),
  };
}
