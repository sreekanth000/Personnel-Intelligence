/**
 * MyWorldBento — Modern Bento Grid view for My World Canvas.
 * Displays categorised cards with status badges, confidence rings, search highlight, and connection count.
 */
import {
  AlertTriangle,
  BrainCircuit,
  HelpCircle,
  History,
  ShieldCheck,
  Zap,
} from "lucide-react";
import React from "react";
import type { MyWorldEdge, MyWorldNode } from "../../api/myworld";
import { formatConfidence } from "../../utils/formatters";

interface Props {
  nodes: MyWorldNode[];
  edges: MyWorldEdge[];
  onSelectNode: (node: MyWorldNode) => void;
  selectedNodeId: string | null;
  searchQuery: string;
  selectedCategory: string;
  selectedState: string;
}

const CATEGORY_META: Record<
  string,
  { title: string; subtitle: string; icon: string; border: string; bg: string; badge: string }
> = {
  people: {
    title: "Key People & Contacts",
    subtitle: "Collaborators, managers, advisors & network",
    icon: "👥",
    border: "border-blue-500/30",
    bg: "from-blue-950/20 to-transparent",
    badge: "bg-blue-500/10 text-blue-400 border-blue-500/30",
  },
  organizations: {
    title: "Organizations & Partners",
    subtitle: "Companies, vendors, banks & institutions",
    icon: "🏢",
    border: "border-indigo-500/30",
    bg: "from-indigo-950/20 to-transparent",
    badge: "bg-indigo-500/10 text-indigo-400 border-indigo-500/30",
  },
  projects: {
    title: "Active Projects",
    subtitle: "Deliverables, initiatives & workstreams",
    icon: "🚀",
    border: "border-emerald-500/30",
    bg: "from-emerald-950/20 to-transparent",
    badge: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
  },
  goals: {
    title: "Goals & Objectives",
    subtitle: "Milestones, targets & strategic intents",
    icon: "🎯",
    border: "border-purple-500/30",
    bg: "from-purple-950/20 to-transparent",
    badge: "bg-purple-500/10 text-purple-400 border-purple-500/30",
  },
  decisions: {
    title: "Decisions & Commitments",
    subtitle: "Logged choices, trade-offs & resolutions",
    icon: "⚖️",
    border: "border-amber-500/30",
    bg: "from-amber-950/20 to-transparent",
    badge: "bg-amber-500/10 text-amber-400 border-amber-500/30",
  },
};

const getStatusBadge = (state: string) => {
  switch (state) {
    case "USER_CONFIRMED":
      return {
        label: "CONFIRMED",
        icon: <ShieldCheck className="w-3 h-3 text-emerald-400" />,
        style: "bg-emerald-500/15 text-emerald-300 border-emerald-500/40",
      };
    case "CONFLICTING":
      return {
        label: "CONFLICT",
        icon: <AlertTriangle className="w-3 h-3 text-rose-400 animate-pulse" />,
        style: "bg-rose-500/20 text-rose-300 border-rose-500/50 shadow-[0_0_10px_rgba(244,63,94,0.3)]",
      };
    case "UNCERTAIN":
      return {
        label: "UNCERTAIN",
        icon: <HelpCircle className="w-3 h-3 text-amber-400" />,
        style: "bg-amber-500/15 text-amber-300 border-amber-500/40 border-dashed",
      };
    case "HISTORICAL":
      return {
        label: "HISTORICAL",
        icon: <History className="w-3 h-3 text-gray-500" />,
        style: "bg-gray-800/40 text-gray-500 border-gray-700/40",
      };
    default:
      return {
        label: "OBSERVED",
        icon: <BrainCircuit className="w-3 h-3 text-blue-400" />,
        style: "bg-blue-500/15 text-blue-300 border-blue-500/30",
      };
  }
};

export const MyWorldBento: React.FC<Props> = ({
  nodes,
  edges,
  onSelectNode,
  selectedNodeId,
  searchQuery,
  selectedCategory,
  selectedState,
}) => {
  // Edge count per node map
  const edgeCountMap = React.useMemo(() => {
    const map: Record<string, number> = {};
    edges.forEach((e) => {
      map[e.source] = (map[e.source] || 0) + 1;
      map[e.target] = (map[e.target] || 0) + 1;
    });
    return map;
  }, [edges]);

  // Filter nodes
  const filteredNodes = React.useMemo(() => {
    return nodes.filter((n) => {
      if (selectedCategory !== "all" && n.category !== selectedCategory) return false;
      if (selectedState !== "all" && n.epistemic_state !== selectedState) return false;
      if (searchQuery) {
        const q = searchQuery.toLowerCase();
        return (n.label || "").toLowerCase().includes(q) || (n.category || "").toLowerCase().includes(q);
      }
      return true;
    });
  }, [nodes, selectedCategory, selectedState, searchQuery]);

  // Group by category
  const categories = ["people", "organizations", "projects", "goals", "decisions"];

  return (
    <div className="space-y-6 overflow-y-auto max-h-full pr-1">
      {categories
        .filter((cat) => selectedCategory === "all" || selectedCategory === cat)
        .map((category) => {
          const catNodes = filteredNodes.filter((n) => n.category === category);
          const meta = CATEGORY_META[category] ?? {
            title: category.toUpperCase(),
            subtitle: "Category items",
            icon: "📁",
            border: "border-gray-800",
            bg: "bg-transparent",
            badge: "bg-gray-800 text-gray-400",
          };

          if (catNodes.length === 0 && selectedCategory !== "all") {
            return (
              <div key={category} className="p-8 text-center bg-gray-900/40 border border-gray-800/80 rounded-2xl">
                <p className="text-gray-500 text-xs">No items match your filter in {meta.title}.</p>
              </div>
            );
          }

          if (catNodes.length === 0) return null;

          return (
            <div
              key={category}
              className={`bg-[#080d19]/80 backdrop-blur-xl border ${meta.border} rounded-2xl p-5 shadow-xl relative overflow-hidden bg-gradient-to-b ${meta.bg}`}
            >
              {/* Header */}
              <div className="flex items-center justify-between mb-4 border-b border-white/5 pb-3">
                <div className="flex items-center space-x-3">
                  <span className="text-2xl">{meta.icon}</span>
                  <div>
                    <h3 className="text-base font-bold text-white tracking-tight flex items-center gap-2">
                      <span>{meta.title}</span>
                      <span className={`text-[10px] font-mono font-semibold px-2 py-0.5 rounded-full border ${meta.badge}`}>
                        {catNodes.length}
                      </span>
                    </h3>
                    <p className="text-xs text-gray-400">{meta.subtitle}</p>
                  </div>
                </div>
              </div>

              {/* Cards Grid */}
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3.5">
                {catNodes.map((node) => {
                  const isSelected = selectedNodeId === node.id;
                  const status = getStatusBadge(node.epistemic_state);
                  const connCount = edgeCountMap[node.id] || 0;

                  return (
                    <div
                      key={node.id}
                      onClick={() => onSelectNode(node)}
                      className={`group relative p-4 rounded-xl border transition-all cursor-pointer flex flex-col justify-between space-y-3 ${
                        isSelected
                          ? "bg-blue-950/60 border-blue-500 shadow-[0_0_20px_rgba(59,130,246,0.35)] scale-[1.01]"
                          : "bg-[#0c1425]/90 hover:bg-[#111c33] border-white/10 hover:border-white/20 hover:shadow-lg"
                      }`}
                    >
                      {/* Top Row: Title + Status Badge */}
                      <div className="flex items-start justify-between gap-2">
                        <h4 className="text-sm font-semibold text-gray-100 group-hover:text-blue-300 transition-colors line-clamp-2 leading-snug">
                          {node.label}
                        </h4>
                        <span
                          className={`shrink-0 flex items-center space-x-1 text-[9px] font-bold font-mono px-2 py-0.5 rounded-full border ${status.style}`}
                        >
                          {status.icon}
                          <span>{status.label}</span>
                        </span>
                      </div>

                      {/* Bottom Row: Confidence & Connections */}
                      <div className="flex items-center justify-between text-[10px] text-gray-400 pt-2 border-t border-white/5 font-mono">
                        <span className="flex items-center space-x-1 text-gray-400">
                          <Zap className="w-3 h-3 text-amber-400" />
                          <span>{connCount} relations</span>
                        </span>

                        <div className="flex items-center space-x-1">
                          <span className="text-gray-500">Conf:</span>
                          <span className="text-emerald-400 font-bold">
                            {formatConfidence(node.confidence)}
                          </span>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
    </div>
  );
};
