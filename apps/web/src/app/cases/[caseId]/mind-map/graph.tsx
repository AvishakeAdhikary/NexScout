"use client";

import "@xyflow/react/dist/style.css";

import {
  Background,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import ELK from "elkjs/lib/elk.bundled.js";
import { useEffect, useMemo, useState } from "react";

import type { MindEdgeOut, MindNodeOut } from "@/lib/api/client";

import { EDGE_LABELS, STATUS_STYLE, displayLabel } from "./labels";

const elk = new ELK();
const NODE_W = 230;
const NODE_H = 64;
const LAYOUT_EDGES = new Set(["has_section", "has_entry", "at_organization"]);

type MindNodeData = { node: MindNodeOut; selected: boolean };

function MindNode({ data }: NodeProps<Node<MindNodeData>>) {
  const n = data.node;
  const style = STATUS_STYLE[n.kind === "fact" ? (n.status ?? "") : n.kind] ?? STATUS_STYLE.section;
  return (
    <div
      className={`rounded-lg border-2 bg-background px-2 py-1 text-xs shadow-sm ${style.border} ${data.selected ? "ring-2 ring-ring" : ""}`}
      style={{ width: NODE_W }}
    >
      <Handle type="target" position={Position.Left} className="!opacity-0" />
      <div className="truncate font-medium" title={displayLabel(n)}>
        {displayLabel(n)}
      </div>
      <div className="mt-0.5 flex flex-wrap gap-1 text-[10px] text-muted-foreground">
        <span>{style.text}</span>
        {n.kind === "fact" && <span>· {n.evidence_count} source{n.evidence_count === 1 ? "" : "s"}</span>}
        {n.is_private && <span>· private</span>}
        {(n.start || n.end) && <span>· {[n.start, n.end].filter(Boolean).join("–")}</span>}
      </div>
      <Handle type="source" position={Position.Right} className="!opacity-0" />
    </div>
  );
}

const nodeTypes = { mind: MindNode };

export function MindGraph({
  nodes,
  edges,
  selectedKey,
  onSelect,
  onMove,
}: {
  nodes: MindNodeOut[];
  edges: MindEdgeOut[];
  selectedKey: string | null;
  onSelect: (key: string) => void;
  onMove: (key: string, x: number, y: number) => void;
}) {
  const [layout, setLayout] = useState<Record<string, { x: number; y: number }>>({});
  const layoutKey = useMemo(
    () => nodes.map((n) => n.key).join("|") + "#" + edges.length,
    [nodes, edges],
  );

  useEffect(() => {
    let cancelled = false;
    const keys = new Set(nodes.map((n) => n.key));
    elk
      .layout({
        id: "root",
        layoutOptions: {
          "elk.algorithm": "layered",
          "elk.direction": "RIGHT",
          "elk.spacing.nodeNode": "18",
          "elk.layered.spacing.nodeNodeBetweenLayers": "70",
        },
        children: nodes.map((n) => ({ id: n.key, width: NODE_W, height: NODE_H })),
        edges: edges
          .filter((e) => LAYOUT_EDGES.has(e.kind) && keys.has(e.source) && keys.has(e.target))
          .map((e, i) => ({ id: `e${i}`, sources: [e.source], targets: [e.target] })),
      })
      .then((res) => {
        if (cancelled) return;
        const pos: Record<string, { x: number; y: number }> = {};
        for (const child of res.children ?? []) pos[child.id] = { x: child.x ?? 0, y: child.y ?? 0 };
        setLayout(pos);
      })
      .catch(() => setLayout({}));
    return () => {
      cancelled = true;
    };
    // Re-layout only when the set of nodes/edges changes, not on every override.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layoutKey]);

  const rfNodes: Node<MindNodeData>[] = nodes.map((n) => ({
    id: n.key,
    type: "mind",
    position:
      n.x != null && n.y != null ? { x: n.x, y: n.y } : (layout[n.key] ?? { x: 0, y: 0 }),
    data: { node: n, selected: n.key === selectedKey },
    ariaLabel: `${displayLabel(n)} (${n.kind === "section" ? "section" : n.status ?? n.kind})`,
  }));
  const keys = new Set(nodes.map((n) => n.key));
  const rfEdges: Edge[] = edges
    .filter((e) => keys.has(e.source) && keys.has(e.target))
    .map((e, i) => ({
      id: `${e.kind}-${e.source}-${e.target}-${i}`,
      source: e.source,
      target: e.target,
      label: e.derived ? EDGE_LABELS[e.kind] : undefined,
      animated: false,
      style: e.derived ? { strokeDasharray: "5 5" } : undefined,
      markerEnd: e.kind === "followed_by" ? { type: MarkerType.ArrowClosed } : undefined,
      labelStyle: { fontSize: 10 },
    }));

  return (
    <div className="h-[600px] w-full rounded-lg border" aria-label="Mind map graph">
      <ReactFlow
        nodes={rfNodes}
        edges={rfEdges}
        nodeTypes={nodeTypes}
        fitView
        minZoom={0.2}
        nodesConnectable={false}
        onNodeClick={(_, node) => onSelect(node.id)}
        onNodeDragStop={(_, node) => onMove(node.id, node.position.x, node.position.y)}
        proOptions={{ hideAttribution: false }}
      >
        <Background />
        <Controls showInteractive={false} />
        <MiniMap pannable zoomable />
      </ReactFlow>
      <p className="sr-only">
        A list version of this map is available with the “Show as list” button.
      </p>
    </div>
  );
}
