"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo, useState, useSyncExternalStore } from "react";

import { ErrorAlert } from "@/components/error-alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { factsApi, mindmapApi, type MindNodeOut, type Section } from "@/lib/api/client";
import { SECTION_LABELS, SECTION_ORDER } from "@/lib/profile-schema";

import { EDGE_LABELS, STATUS_STYLE, displayLabel } from "./labels";
import { SnapshotCompare } from "./snapshot-compare";

// The graph library is client-only and fairly large: load it on demand.
const MindGraph = dynamic(() => import("./graph").then((m) => m.MindGraph), {
  ssr: false,
  loading: () => <p>Drawing your map…</p>,
});

const noSubscription = () => () => {};

function storedDirection(): "RIGHT" | "DOWN" {
  try {
    return window.localStorage.getItem("nexscout.mindmap-direction") === "DOWN" ? "DOWN" : "RIGHT";
  } catch {
    return "RIGHT";
  }
}

export default function MindMapPage() {
  const { caseId } = useParams<{ caseId: string }>();
  const queryClient = useQueryClient();
  const map = useQuery({ queryKey: ["mindmap", caseId], queryFn: () => mindmapApi.get(caseId) });
  const [view, setView] = useState<"graph" | "list">("graph");
  const [section, setSection] = useState<Section | "">("");
  const [search, setSearch] = useState("");
  const [showHidden, setShowHidden] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["mindmap", caseId] });

  const saveNode = useMutation({
    mutationFn: ({ node, patch }: { node: MindNodeOut; patch: Partial<MindNodeOut> }) =>
      mindmapApi.setNode(caseId, node.key, {
        x: patch.x ?? node.x ?? null,
        y: patch.y ?? node.y ?? null,
        hidden: patch.hidden ?? node.hidden,
        label: patch.label_override !== undefined ? patch.label_override : node.label_override,
      }),
    onSuccess: invalidate,
  });
  const resetAll = useMutation({
    mutationFn: () => mindmapApi.resetAll(caseId),
    onSuccess: invalidate,
  });
  // The remembered direction is browser-only; the server render uses the default.
  const stored = useSyncExternalStore(noSubscription, storedDirection, () => "RIGHT" as const);
  const [chosen, setDirection] = useState<"RIGHT" | "DOWN" | null>(null);
  const direction = chosen ?? stored;
  const [arrangeNonce, setArrangeNonce] = useState(0);
  const arrange = useMutation({
    mutationFn: () => mindmapApi.autoArrange(caseId),
    onSuccess: () => {
      setArrangeNonce((n) => n + 1);
      invalidate();
    },
  });
  const changeDirection = (d: "RIGHT" | "DOWN") => {
    setDirection(d);
    try {
      window.localStorage.setItem("nexscout.mindmap-direction", d);
    } catch {
      // remembered for this visit only
    }
  };

  const { nodes, edges } = useMemo(() => {
    const all = map.data?.nodes ?? [];
    const q = search.trim().toLowerCase();
    const keep = all.filter((n) => {
      if (n.kind === "candidate") return true;
      if (n.hidden && !showHidden) return false;
      if (section && n.section !== section && n.kind !== "organization") return false;
      if (q && n.kind === "fact" && !displayLabel(n).toLowerCase().includes(q)) return false;
      return true;
    });
    const keys = new Set(keep.map((n) => n.key));
    return {
      nodes: keep,
      edges: (map.data?.edges ?? []).filter((e) => keys.has(e.source) && keys.has(e.target)),
    };
  }, [map.data, search, section, showHidden]);

  const selectedNode = map.data?.nodes.find((n) => n.key === selected) ?? null;
  const factNodes = nodes.filter((n) => n.kind === "fact");

  return (
    <div className="flex max-w-6xl flex-col gap-4">
      <header>
        <h1 className="text-2xl font-semibold">Mind Map</h1>
        <p className="text-muted-foreground">
          Your confirmed profile as a map. Solid lines come straight from your profile. Dashed lines
          are <strong>suggested connections</strong> (for example, a skill mentioned in a job
          description). They are not confirmed facts.
        </p>
      </header>

      <div className="flex flex-wrap items-end gap-3" role="toolbar" aria-label="Map options">
        <Button
          variant="outline"
          aria-pressed={view === "list"}
          onClick={() => setView((v) => (v === "graph" ? "list" : "graph"))}
        >
          {view === "graph" ? "Show as list" : "Show as map"}
        </Button>
        <div className="flex flex-col gap-1">
          <Label htmlFor="mm-section">Section</Label>
          <select
            id="mm-section"
            className="h-8 rounded-lg border bg-background px-2 text-sm"
            value={section}
            onChange={(e) => setSection(e.target.value as Section | "")}
          >
            <option value="">All sections</option>
            {SECTION_ORDER.map((s) => (
              <option key={s} value={s}>
                {SECTION_LABELS[s]}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="mm-search">Search</Label>
          <Input id="mm-search" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={showHidden}
            onChange={(e) => setShowHidden(e.target.checked)}
          />
          Show hidden items
        </label>
        <div className="flex flex-col gap-1">
          <Label htmlFor="mm-direction">Layout</Label>
          <select
            id="mm-direction"
            className="h-8 rounded-lg border bg-background px-2 text-sm"
            value={direction}
            onChange={(e) => changeDirection(e.target.value as "RIGHT" | "DOWN")}
          >
            <option value="RIGHT">Left to right</option>
            <option value="DOWN">Top to bottom</option>
          </select>
        </div>
        <Button
          variant="outline"
          disabled={arrange.isPending}
          onClick={() => arrange.mutate()}
          title="Place every item neatly again (your renames and hidden items stay)"
        >
          {arrange.isPending ? "Arranging…" : "Auto-arrange"}
        </Button>
        <Button variant="ghost" onClick={() => invalidate()}>
          Regenerate
        </Button>
        <Button
          variant="ghost"
          onClick={() => {
            if (window.confirm("Reset all positions, renames, and hidden items?"))
              resetAll.mutate();
          }}
        >
          Reset layout
        </Button>
      </div>

      {map.isPending && <p>Loading…</p>}
      <ErrorAlert error={map.error ?? saveNode.error ?? resetAll.error ?? arrange.error} />
      {map.data && factNodes.length === 0 && (
        <p className="rounded-md border border-dashed p-4 text-sm">
          Your map is empty because no profile entries are confirmed yet.{" "}
          <Link className="underline" href={`/cases/${caseId}/profile`}>
            Review your profile
          </Link>{" "}
          first. Only confirmed entries appear here.
        </p>
      )}
      {map.data && map.data.orphaned_overrides.length > 0 && (
        <p className="text-sm text-muted-foreground">
          {map.data.orphaned_overrides.length} saved layout change(s) belong to entries that no
          longer exist. They are kept but not shown. “Reset layout” removes them.
        </p>
      )}

      <div className="flex flex-col gap-4 lg:flex-row">
        <div className="min-w-0 flex-1">
          {map.data && view === "graph" && (
            <MindGraph
              nodes={nodes}
              edges={edges}
              selectedKey={selected}
              onSelect={setSelected}
              direction={direction}
              arrangeNonce={arrangeNonce}
              onMove={(key, x, y) => {
                const node = map.data!.nodes.find((n) => n.key === key);
                if (node) saveNode.mutate({ node, patch: { x, y } });
              }}
            />
          )}
          {map.data && view === "list" && (
            <MapList nodes={nodes} edges={edges} onSelect={setSelected} />
          )}
        </div>
        {selectedNode && selectedNode.kind !== "candidate" && (
          <NodePanel
            key={selectedNode.key}
            node={selectedNode}
            pending={saveNode.isPending}
            onClose={() => setSelected(null)}
            onSave={(patch) => saveNode.mutate({ node: selectedNode, patch })}
            onReset={() => mindmapApi.resetNode(caseId, selectedNode.key).then(invalidate)}
          />
        )}
      </div>

      <SnapshotCompare caseId={caseId} />
    </div>
  );
}

function MapList({
  nodes,
  edges,
  onSelect,
}: {
  nodes: MindNodeOut[];
  edges: {
    source: string;
    target: string;
    kind: string;
    derived: boolean;
    basis?: string | null;
  }[];
  onSelect: (key: string) => void;
}) {
  const byKey = new Map(nodes.map((n) => [n.key, n]));
  const sections = SECTION_ORDER.filter((s) =>
    nodes.some((n) => n.kind === "fact" && n.section === s),
  );
  return (
    <div className="flex flex-col gap-4">
      {sections.map((s) => (
        <section key={s} aria-labelledby={`list-${s}`}>
          <h2 id={`list-${s}`} className="font-semibold">
            {SECTION_LABELS[s]}
          </h2>
          <ul className="mt-1 flex flex-col gap-2">
            {nodes
              .filter((n) => n.kind === "fact" && n.section === s)
              .map((n) => {
                const links = edges.filter(
                  (e) => e.derived && (e.source === n.key || e.target === n.key),
                );
                return (
                  <li key={n.key} className="rounded border p-2 text-sm">
                    <button
                      type="button"
                      className="font-medium underline"
                      onClick={() => onSelect(n.key)}
                    >
                      {displayLabel(n)}
                    </button>{" "}
                    <span className="text-muted-foreground">
                      ({STATUS_STYLE[n.status ?? ""]?.text ?? n.status}; {n.evidence_count} source
                      {n.evidence_count === 1 ? "" : "s"}
                      {n.hidden ? "; hidden" : ""})
                    </span>
                    {links.length > 0 && (
                      <ul className="mt-1 list-disc pl-5 text-xs text-muted-foreground">
                        {links.map((e, i) => {
                          const other = byKey.get(e.source === n.key ? e.target : e.source);
                          return (
                            <li key={i}>
                              Suggested link ({EDGE_LABELS[e.kind] || e.kind}):{" "}
                              {other ? displayLabel(other) : "?"}. {e.basis}
                            </li>
                          );
                        })}
                      </ul>
                    )}
                  </li>
                );
              })}
          </ul>
        </section>
      ))}
    </div>
  );
}

function NodePanel({
  node,
  pending,
  onClose,
  onSave,
  onReset,
}: {
  node: MindNodeOut;
  pending: boolean;
  onClose: () => void;
  onSave: (patch: Partial<MindNodeOut>) => void;
  onReset: () => void;
}) {
  const [label, setLabel] = useState(node.label_override ?? "");
  const evidence = useQuery({
    queryKey: ["evidence", node.fact_id],
    queryFn: () => factsApi.evidence(node.fact_id!),
    enabled: !!node.fact_id,
  });
  return (
    <aside
      aria-labelledby="node-panel-title"
      className="w-full shrink-0 rounded-lg border p-3 lg:w-80"
    >
      <div className="flex items-start justify-between gap-2">
        <h2 id="node-panel-title" className="font-semibold">
          {displayLabel(node)}
        </h2>
        <Button size="sm" variant="ghost" onClick={onClose} aria-label="Close details">
          ✕
        </Button>
      </div>
      <p className="text-sm text-muted-foreground">
        {node.kind === "fact"
          ? STATUS_STYLE[node.status ?? ""]?.text
          : node.kind === "organization"
            ? "A grouping of entries that name the same organization (suggested, not confirmed)."
            : "Section"}
      </p>
      {node.kind === "fact" && (
        <div className="mt-2 text-sm">
          <h3 className="font-medium">Sources</h3>
          {evidence.isPending && <p>Loading…</p>}
          {evidence.data?.map((ev) => (
            <blockquote key={ev.id} className="mt-1 whitespace-pre-line border-l-2 pl-2 text-xs">
              {ev.excerpt ?? (ev.kind === "user_entry" ? "Entered by you." : ev.kind)}
            </blockquote>
          ))}
        </div>
      )}
      <div className="mt-3 flex flex-col gap-2">
        <Label htmlFor="node-label">Display name on the map</Label>
        <Input
          id="node-label"
          value={label}
          maxLength={300}
          onChange={(e) => setLabel(e.target.value)}
        />
        <p className="text-xs text-muted-foreground">
          Only changes how the map shows it. Your profile entry is not changed.
        </p>
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            disabled={pending}
            onClick={() => onSave({ label_override: label || null })}
          >
            Save name
          </Button>
          <Button size="sm" variant="outline" onClick={() => onSave({ hidden: !node.hidden })}>
            {node.hidden ? "Show on map" : "Hide from map"}
          </Button>
          <Button size="sm" variant="ghost" onClick={onReset}>
            Reset
          </Button>
        </div>
      </div>
    </aside>
  );
}
