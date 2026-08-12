/**
 * WorldGraphPage — Full-screen globe/cosmos visualization of the personal world model.
 * - Uses D3 force simulation (GlobeGraph) instead of React Flow
 * - No embedded timeline or side panel — those are separate screens
 * - Clicking a node opens a floating detail drawer
 * - Clicking an edge opens a floating edge inspector
 */
import {
  CheckCircle2,
  ChevronRight,
  Filter,
  Globe,
  RefreshCw,
  Search,
  X,
  Zap,
} from "lucide-react";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { worldApi } from "../api";
import { GlobeGraph } from "../components/graph/GlobeGraph";
import { RelationshipInspector } from "../components/relationship/RelationshipInspector";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/LoadingState";
import type { UIGraphDTO, UIGraphEdge, UIGraphNode } from "../types";
import { formatConfidence, getEntityTypeColor } from "../utils/formatters";

/* ─── Node detail drawer ─────────────────────────────────────────── */
const NodeDrawer: React.FC<{
  node: UIGraphNode | null;
  onClose: () => void;
}> = ({ node, onClose }) => {
  if (!node) return null;
  const confidence = (node.metadata?.confidence as number) ?? 1.0;
  return (
    <div
      className="absolute top-4 right-4 z-30 w-80 bg-[#0d1829]/90 backdrop-blur-xl border border-white/10 rounded-2xl shadow-2xl overflow-hidden"
      style={{ animation: "slideInRight 0.25s ease-out" }}
    >
      {/* Header */}
      <div className="flex items-start justify-between p-4 border-b border-white/10">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="text-base font-bold text-white leading-tight truncate">
              {node.label}
            </h3>
            <span
              className={`text-[9px] font-bold uppercase px-2 py-0.5 rounded border flex-shrink-0 ${getEntityTypeColor(node.type)}`}
            >
              {node.type}
            </span>
          </div>
          <p className="text-[10px] text-gray-500 font-mono mt-0.5 truncate">
            {node.id}
          </p>
        </div>
        <button
          id="node-drawer-close"
          onClick={onClose}
          className="ml-3 p-1.5 hover:bg-white/10 rounded-lg transition-colors text-gray-400 hover:text-white flex-shrink-0 cursor-pointer"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Attributes */}
      <div className="p-4 space-y-3">
        <div className="space-y-2">
          {/* Confidence */}
          <div className="flex items-center justify-between py-2 border-b border-white/5">
            <span className="text-xs text-gray-500">Confidence</span>
            <span className="flex items-center gap-1.5 text-xs font-mono text-emerald-400">
              <CheckCircle2 className="w-3.5 h-3.5" />
              {formatConfidence(confidence)}
            </span>
          </div>

          {/* Email */}
          {!!node.metadata?.email && (
            <div className="flex items-center justify-between py-2 border-b border-white/5">
              <span className="text-xs text-gray-500">Email</span>
              <span className="text-xs font-mono text-blue-400 truncate ml-4 text-right">
                {node.metadata.email as string}
              </span>
            </div>
          )}

          {/* Domain */}
          {!!node.metadata?.domain && (
            <div className="flex items-center justify-between py-2 border-b border-white/5">
              <span className="text-xs text-gray-500">Domain</span>
              <span className="text-xs font-mono text-indigo-300 truncate ml-4 text-right">
                {node.metadata.domain as string}
              </span>
            </div>
          )}

          {/* Aliases */}
          {Array.isArray(node.metadata?.aliases) && (node.metadata.aliases as string[]).length > 0 && (
            <div className="py-2 border-b border-white/5">
              <span className="text-xs text-gray-500 block mb-1">Aliases</span>
              <div className="flex flex-wrap gap-1">
                {(node.metadata.aliases as string[]).slice(0, 4).map((a: string, i: number) => (
                  <span
                    key={i}
                    className="text-[10px] bg-white/5 border border-white/10 rounded px-1.5 py-0.5 text-gray-300 font-mono"
                  >
                    {a}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Extra attributes */}
          {Object.entries(node.metadata ?? {})
            .filter(([k]) => !["confidence", "email", "domain", "aliases"].includes(k))
            .slice(0, 4)
            .map(([k, v]) => (
              <div key={k} className="flex items-start justify-between py-1.5 border-b border-white/5">
                <span className="text-[10px] text-gray-500 capitalize font-mono">{k}</span>
                <span className="text-[10px] text-gray-300 font-mono text-right ml-4 truncate max-w-[60%]">
                  {String(v)}
                </span>
              </div>
            ))}
        </div>
      </div>
    </div>
  );
};

/* ─── Edge detail drawer ─────────────────────────────────────────── */
const EdgeDrawer: React.FC<{
  edge: UIGraphEdge | null;
  onClose: () => void;
}> = ({ edge, onClose }) => {
  if (!edge) return null;
  return (
    <div
      className="absolute top-4 right-4 z-30 w-80 bg-[#0d1829]/90 backdrop-blur-xl border border-white/10 rounded-2xl shadow-2xl overflow-hidden"
      style={{ animation: "slideInRight 0.25s ease-out" }}
    >
      <div className="flex items-start justify-between p-4 border-b border-white/10">
        <div>
          <div className="flex items-center gap-2">
            <Zap className="w-4 h-4 text-amber-400" />
            <h3 className="text-sm font-bold text-white">
              {edge.relationship_type?.replace(/_/g, " ")}
            </h3>
          </div>
          <p className="text-[10px] text-gray-500 font-mono mt-0.5 truncate">{edge.id}</p>
        </div>
        <button
          id="edge-drawer-close"
          onClick={onClose}
          className="p-1.5 hover:bg-white/10 rounded-lg transition-colors text-gray-400 hover:text-white cursor-pointer"
        >
          <X className="w-4 h-4" />
        </button>
      </div>
      <div className="p-4">
        <RelationshipInspector
          relationshipId={edge.id}
          onViewEvidence={(id) => console.log("Evidence", id)}
        />
      </div>
    </div>
  );
};

/* ─── Main Page ──────────────────────────────────────────────────── */
export const WorldGraphPage: React.FC = () => {
  const [originalGraph, setOriginalGraph] = useState<UIGraphDTO | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selectedNode, setSelectedNode] = useState<UIGraphNode | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<UIGraphEdge | null>(null);
  const [highlightId, setHighlightId] = useState<string | null>(null);

  const [searchQuery, setSearchQuery] = useState("");
  const [entityTypeFilter, setEntityTypeFilter] = useState("all");
  const [depthFilter, setDepthFilter] = useState(2);

  /* ── fetch ── */
  const fetchGraph = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await worldApi.getUIGraph(undefined, depthFilter);
      setOriginalGraph(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load graph.");
    } finally {
      setLoading(false);
    }
  }, [depthFilter]);

  useEffect(() => {
    void fetchGraph();
  }, [fetchGraph]);

  /* ── deep link ── */
  useEffect(() => {
    const handler = (e: Event) => {
      const ce = e as CustomEvent;
      if (ce.detail?.tab === "graph" && ce.detail?.id) {
        const id = ce.detail.id as string;
        const node = originalGraph?.nodes.find((n) => n.id === id);
        if (node) {
          setSelectedNode(node);
          setSelectedEdge(null);
          setHighlightId(id);
        } else {
          const edge = originalGraph?.edges.find((e2) => e2.id === id);
          if (edge) {
            setSelectedEdge(edge);
            setSelectedNode(null);
          }
        }
      }
    };
    window.addEventListener("deeplink", handler);
    return () => window.removeEventListener("deeplink", handler);
  }, [originalGraph]);

  /* ── filter ── */
  const { filteredNodes, filteredEdges } = useMemo(() => {
    if (!originalGraph) return { filteredNodes: [], filteredEdges: [] };
    let fNodes = originalGraph.nodes;
    if (entityTypeFilter !== "all")
      fNodes = fNodes.filter((n) => n.type === entityTypeFilter);
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      fNodes = fNodes.filter((n) => n.label.toLowerCase().includes(q));
    }
    const fIds = new Set(fNodes.map((n) => n.id));
    const fEdges = originalGraph.edges.filter(
      (e) => fIds.has(e.source) && fIds.has(e.target),
    );
    return { filteredNodes: fNodes, filteredEdges: fEdges };
  }, [originalGraph, entityTypeFilter, searchQuery]);

  /* ── entity types for filter dropdown ── */
  const availableTypes = useMemo(() => {
    if (!originalGraph) return [];
    return Array.from(new Set(originalGraph.nodes.map((n) => n.type))).sort();
  }, [originalGraph]);

  const handleNodeClick = useCallback((node: UIGraphNode) => {
    setSelectedNode(node);
    setSelectedEdge(null);
    setHighlightId(node.id);
  }, []);

  const handleEdgeClick = useCallback((edge: UIGraphEdge) => {
    setSelectedEdge(edge);
    setSelectedNode(null);
    setHighlightId(null);
  }, []);

  const handlePaneClick = useCallback(() => {
    setSelectedNode(null);
    setSelectedEdge(null);
    setHighlightId(null);
  }, []);

  const handleReset = useCallback(() => {
    setSelectedNode(null);
    setSelectedEdge(null);
    setHighlightId(null);
    setSearchQuery("");
    setEntityTypeFilter("all");
    void fetchGraph();
  }, [fetchGraph]);

  if (error) {
    return (
      <div className="h-full">
        <ErrorState title="Graph Failed to Load" message={error} onRetry={handleReset} />
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col" style={{ minHeight: 0 }}>
      {/* ── Toolbar ── */}
      <div className="shrink-0 flex items-center justify-between bg-[#0d1829]/80 backdrop-blur border border-white/10 rounded-xl px-4 py-2.5 mb-3 gap-3 flex-wrap">
        {/* Left: title */}
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 bg-blue-600/20 border border-blue-500/30 rounded-lg flex items-center justify-center">
            <Globe className="w-4 h-4 text-blue-400" />
          </div>
          <div>
            <h2 className="text-sm font-bold text-white leading-none">World Graph</h2>
            <p className="text-[10px] text-gray-500 mt-0.5">
              {filteredNodes.length} entities · {filteredEdges.length} relations
            </p>
          </div>
        </div>

        {/* Center: search + filter */}
        <div className="flex items-center gap-2 flex-1 max-w-xl">
          <div className="relative flex-1">
            <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-500" />
            <input
              id="graph-search"
              type="text"
              placeholder="Search entities…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full bg-black/30 border border-white/10 rounded-lg pl-8 pr-3 py-1.5 text-xs text-white placeholder-gray-600 focus:outline-none focus:border-blue-500 transition-colors"
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery("")}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-white cursor-pointer"
              >
                <X className="w-3 h-3" />
              </button>
            )}
          </div>

          <div className="flex items-center gap-1.5 bg-black/30 border border-white/10 rounded-lg px-2.5 py-1.5">
            <Filter className="w-3 h-3 text-gray-500" />
            <select
              id="graph-type-filter"
              value={entityTypeFilter}
              onChange={(e) => setEntityTypeFilter(e.target.value)}
              className="bg-transparent text-xs text-gray-300 focus:outline-none cursor-pointer"
            >
              <option value="all">All Types</option>
              {availableTypes.map((t) => (
                <option key={t} value={t}>
                  {t.charAt(0).toUpperCase() + t.slice(1)}
                </option>
              ))}
            </select>
          </div>

          <div className="flex items-center gap-1.5 bg-black/30 border border-white/10 rounded-lg px-2.5 py-1.5">
            <ChevronRight className="w-3 h-3 text-gray-500" />
            <select
              id="graph-depth-filter"
              value={depthFilter}
              onChange={(e) => setDepthFilter(Number(e.target.value))}
              className="bg-transparent text-xs text-gray-300 focus:outline-none cursor-pointer"
            >
              <option value={1}>Depth 1</option>
              <option value={2}>Depth 2</option>
              <option value={3}>Depth 3</option>
            </select>
          </div>
        </div>

        {/* Right: reset */}
        <button
          id="graph-reset-btn"
          onClick={handleReset}
          className="p-1.5 bg-black/30 hover:bg-white/10 border border-white/10 rounded-lg text-gray-400 hover:text-white transition-colors cursor-pointer flex-shrink-0"
          title="Reset Graph"
        >
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {/* ── Main canvas area ── */}
      <div className="flex-1 relative min-h-0" onClick={handlePaneClick}>
        {loading ? (
          <div className="w-full h-full bg-[#020b18] rounded-xl flex items-center justify-center">
            <LoadingState message="Mapping your world model…" rows={1} />
          </div>
        ) : (
          <GlobeGraph
            nodes={filteredNodes}
            edges={filteredEdges}
            onNodeClick={handleNodeClick}
            onEdgeClick={handleEdgeClick}
            highlightId={highlightId}
          />
        )}

        {/* Floating drawers — stop propagation so click doesn't close them */}
        <div onClick={(e) => e.stopPropagation()}>
          {selectedNode && (
            <NodeDrawer
              node={selectedNode}
              onClose={() => { setSelectedNode(null); setHighlightId(null); }}
            />
          )}
          {selectedEdge && !selectedNode && (
            <EdgeDrawer
              edge={selectedEdge}
              onClose={() => setSelectedEdge(null)}
            />
          )}
        </div>
      </div>

      {/* animation keyframes */}
      <style>{`
        @keyframes slideInRight {
          from { opacity: 0; transform: translateX(24px); }
          to   { opacity: 1; transform: translateX(0); }
        }
      `}</style>
    </div>
  );
};
