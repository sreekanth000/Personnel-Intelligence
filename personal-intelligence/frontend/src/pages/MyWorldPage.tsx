/**
 * MyWorldPage — Personal World Canvas Dashboard.
 * Provides a high-level executive map of active relationships, projects, goals, decisions,
 * and organizations with interactive Orbital Constellation and Bento Grid visualization modes.
 */
import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  Filter,
  Grid,
  Layers,
  Orbit,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  UserCheck,
  X,
  Zap,
} from "lucide-react";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { myWorldApi, type MyWorldDTO, type MyWorldNode } from "../api/myworld";
import { MyWorldBento } from "../components/myworld/MyWorldBento";
import { MyWorldConstellation } from "../components/myworld/MyWorldConstellation";
import { RelationshipInspector } from "../components/relationship/RelationshipInspector";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/LoadingState";
import { formatConfidence, getEntityTypeColor } from "../utils/formatters";

export const MyWorldPage: React.FC = () => {
  const [data, setData] = useState<MyWorldDTO | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters & Controls
  const [viewMode, setViewMode] = useState<"constellation" | "bento">("constellation");
  const [selectedCategory, setSelectedCategory] = useState<string>("all");
  const [selectedState, setSelectedState] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [showHistorical, setShowHistorical] = useState(false);

  // Selected item drawer
  const [selectedNode, setSelectedNode] = useState<MyWorldNode | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await myWorldApi.getCanvas();
      setData(res);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load My World Canvas data"
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  // Derived metrics
  const metrics = useMemo(() => {
    if (!data) return { total: 0, confirmed: 0, conflicts: 0, uncertain: 0, activeEdges: 0 };
    const nodes = data.nodes;
    return {
      total: nodes.length,
      confirmed: nodes.filter((n) => n.epistemic_state === "USER_CONFIRMED").length,
      conflicts: nodes.filter((n) => n.epistemic_state === "CONFLICTING").length,
      uncertain: nodes.filter((n) => n.epistemic_state === "UNCERTAIN").length,
      activeEdges: data.edges.length,
    };
  }, [data]);

  // Display nodes after historical toggle
  const displayNodes = useMemo(() => {
    if (!data) return [];
    return data.nodes.filter((n) => showHistorical || n.epistemic_state !== "HISTORICAL");
  }, [data, showHistorical]);

  const displayEdges = useMemo(() => {
    if (!data) return [];
    return data.edges;
  }, [data]);

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center bg-gray-950">
        <LoadingState message="Assembling your Personal World Model Canvas..." rows={4} />
      </div>
    );
  }

  if (error) {
    return (
      <div className="h-full p-6">
        <ErrorState title="Failed to Load World Model" message={error} onRetry={fetchData} />
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col space-y-4" style={{ minHeight: 0 }}>
      {/* ── Executive Intelligence Header ── */}
      <div className="shrink-0 bg-[#091120]/80 backdrop-blur-xl border border-white/10 rounded-2xl p-5 shadow-2xl space-y-4">
        {/* Top title row */}
        <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
          <div className="flex items-center space-x-3">
            <div className="w-10 h-10 bg-gradient-to-br from-blue-600 to-indigo-600 rounded-xl flex items-center justify-center shadow-lg shadow-blue-500/20">
              <Layers className="w-5 h-5 text-white" />
            </div>
            <div>
              <h2 className="text-xl font-bold text-white tracking-tight flex items-center gap-2">
                <span>My World Canvas</span>
                <span className="text-[10px] font-mono font-bold bg-blue-500/10 text-blue-400 border border-blue-500/30 px-2 py-0.5 rounded-full">
                  Synthesized World Model
                </span>
              </h2>
              <p className="text-xs text-gray-400 mt-0.5">
                Curated intelligence topology across your people, organizations, projects, goals & decisions
              </p>
            </div>
          </div>

          {/* Mode Switcher & Reload */}
          <div className="flex items-center space-x-2">
            <div className="bg-black/40 border border-white/10 rounded-xl p-1 flex items-center space-x-1">
              <button
                onClick={() => setViewMode("constellation")}
                className={`flex items-center space-x-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
                  viewMode === "constellation"
                    ? "bg-blue-600 text-white shadow-md shadow-blue-600/30"
                    : "text-gray-400 hover:text-gray-200"
                }`}
              >
                <Orbit className="w-3.5 h-3.5" />
                <span>Constellation</span>
              </button>

              <button
                onClick={() => setViewMode("bento")}
                className={`flex items-center space-x-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
                  viewMode === "bento"
                    ? "bg-blue-600 text-white shadow-md shadow-blue-600/30"
                    : "text-gray-400 hover:text-gray-200"
                }`}
              >
                <Grid className="w-3.5 h-3.5" />
                <span>Matrix Grid</span>
              </button>
            </div>

            <button
              onClick={fetchData}
              className="p-2 bg-black/40 hover:bg-white/10 border border-white/10 rounded-xl text-gray-400 hover:text-white transition-colors cursor-pointer"
              title="Refresh Canvas"
            >
              <RefreshCw className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Intelligence Stat Summary Bar */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-2 border-t border-white/5">
          <div className="bg-black/30 border border-white/5 rounded-xl p-3 flex items-center space-x-3">
            <Sparkles className="w-4 h-4 text-blue-400" />
            <div>
              <p className="text-[10px] font-mono text-gray-400 uppercase">Entities</p>
              <p className="text-sm font-bold text-white font-mono">{metrics.total}</p>
            </div>
          </div>

          <div className="bg-black/30 border border-white/5 rounded-xl p-3 flex items-center space-x-3">
            <Zap className="w-4 h-4 text-emerald-400" />
            <div>
              <p className="text-[10px] font-mono text-gray-400 uppercase">Active Relations</p>
              <p className="text-sm font-bold text-emerald-400 font-mono">{metrics.activeEdges}</p>
            </div>
          </div>

          <div className="bg-black/30 border border-white/5 rounded-xl p-3 flex items-center space-x-3">
            <ShieldCheck className="w-4 h-4 text-indigo-400" />
            <div>
              <p className="text-[10px] font-mono text-gray-400 uppercase">Confirmed</p>
              <p className="text-sm font-bold text-indigo-300 font-mono">{metrics.confirmed}</p>
            </div>
          </div>

          <div className="bg-black/30 border border-white/5 rounded-xl p-3 flex items-center space-x-3">
            <AlertTriangle className="w-4 h-4 text-amber-400" />
            <div>
              <p className="text-[10px] font-mono text-gray-400 uppercase">Conflicts / Review</p>
              <p className="text-sm font-bold text-amber-400 font-mono">
                {metrics.conflicts + metrics.uncertain}
              </p>
            </div>
          </div>
        </div>

        {/* Filter Controls Bar */}
        <div className="flex flex-wrap items-center justify-between gap-3 pt-2">
          <div className="flex items-center gap-2 flex-1 max-w-2xl flex-wrap">
            {/* Search */}
            <div className="relative flex-1 min-w-[200px]">
              <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
              <input
                type="text"
                placeholder="Search world canvas..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full bg-black/40 border border-white/10 rounded-xl pl-9 pr-3 py-1.5 text-xs text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 transition-colors"
              />
              {searchQuery && (
                <button
                  onClick={() => setSearchQuery("")}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-white cursor-pointer"
                >
                  <X className="w-3 h-3" />
                </button>
              )}
            </div>

            {/* Category Filter */}
            <div className="flex items-center space-x-1.5 bg-black/40 border border-white/10 rounded-xl px-3 py-1.5">
              <Filter className="w-3 h-3 text-gray-500" />
              <select
                value={selectedCategory}
                onChange={(e) => setSelectedCategory(e.target.value)}
                className="bg-transparent text-xs text-gray-300 focus:outline-none cursor-pointer"
              >
                <option value="all">All Categories</option>
                <option value="people">Key People</option>
                <option value="organizations">Organizations</option>
                <option value="projects">Active Projects</option>
                <option value="goals">Goals & Objectives</option>
                <option value="decisions">Decisions</option>
              </select>
            </div>

            {/* Epistemic State Filter */}
            <div className="flex items-center space-x-1.5 bg-black/40 border border-white/10 rounded-xl px-3 py-1.5">
              <ChevronRight className="w-3 h-3 text-gray-500" />
              <select
                value={selectedState}
                onChange={(e) => setSelectedState(e.target.value)}
                className="bg-transparent text-xs text-gray-300 focus:outline-none cursor-pointer"
              >
                <option value="all">All States</option>
                <option value="USER_CONFIRMED">User Confirmed</option>
                <option value="OBSERVED">Observed</option>
                <option value="CONFLICTING">Conflicting</option>
                <option value="UNCERTAIN">Uncertain</option>
              </select>
            </div>
          </div>

          {/* Historical Toggle */}
          <label className="flex items-center space-x-2 text-xs text-gray-400 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={showHistorical}
              onChange={(e) => setShowHistorical(e.target.checked)}
              className="rounded bg-black border-white/10 text-blue-500 focus:ring-0"
            />
            <span>Include Historical</span>
          </label>
        </div>
      </div>

      {/* ── Main Canvas View Area ── */}
      <div className="flex-1 relative min-h-0">
        {viewMode === "constellation" ? (
          <MyWorldConstellation
            nodes={displayNodes}
            edges={displayEdges}
            onSelectNode={setSelectedNode}
            selectedNodeId={selectedNode?.id || null}
            searchQuery={searchQuery}
            selectedCategory={selectedCategory}
          />
        ) : (
          <MyWorldBento
            nodes={displayNodes}
            edges={displayEdges}
            onSelectNode={setSelectedNode}
            selectedNodeId={selectedNode?.id || null}
            searchQuery={searchQuery}
            selectedCategory={selectedCategory}
            selectedState={selectedState}
          />
        )}

        {/* Floating Detail Drawer when item is selected */}
        {selectedNode && (
          <div
            className="absolute top-4 right-4 z-40 w-80 sm:w-96 bg-[#0c1425]/95 backdrop-blur-2xl border border-white/15 rounded-2xl shadow-2xl overflow-hidden"
            style={{ animation: "slideInRight 0.2s ease-out" }}
          >
            <div className="flex items-start justify-between p-4 border-b border-white/10">
              <div className="flex-1 min-w-0 pr-2">
                <div className="flex items-center space-x-2">
                  <h3 className="text-base font-bold text-white truncate">{selectedNode.label}</h3>
                  <span
                    className={`text-[9px] font-bold uppercase px-2 py-0.5 rounded border ${getEntityTypeColor(
                      selectedNode.category
                    )}`}
                  >
                    {selectedNode.category}
                  </span>
                </div>
                <p className="text-[10px] font-mono text-gray-500 mt-1 truncate">ID: {selectedNode.id}</p>
              </div>
              <button
                onClick={() => setSelectedNode(null)}
                className="p-1 hover:bg-white/10 rounded-lg text-gray-400 hover:text-white cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="p-4 space-y-4">
              <div className="bg-black/40 border border-white/10 rounded-xl p-3 space-y-2 text-xs">
                <div className="flex items-center justify-between">
                  <span className="text-gray-400">Epistemic Status</span>
                  <span className="font-mono font-bold text-blue-400">{selectedNode.epistemic_state}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-gray-400">Confidence Score</span>
                  <span className="font-mono font-bold text-emerald-400">
                    {formatConfidence(selectedNode.confidence)}
                  </span>
                </div>
              </div>

              <div className="pt-2">
                <h4 className="text-xs font-semibold text-gray-300 mb-2">Connected Relationships</h4>
                <RelationshipInspector
                  relationshipId={selectedNode.id}
                  onViewEvidence={(id) => console.log("Evidence", id)}
                />
              </div>
            </div>
          </div>
        )}
      </div>

      <style>{`
        @keyframes slideInRight {
          from { opacity: 0; transform: translateX(20px); }
          to   { opacity: 1; transform: translateX(0); }
        }
      `}</style>
    </div>
  );
};
