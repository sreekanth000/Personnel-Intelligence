import React from "react";
import {
  AlertOctagon,
  ArrowRight,
  Building2,
  CheckCircle2,
  Clock,
  Compass,
  FolderGit2,
  Mail,
  ShieldAlert,
  ShieldCheck,
  Target,
  Users,
} from "lucide-react";
import { AskBox } from "../components/AskBox";
import { EmptyState } from "../components/EmptyState";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/LoadingState";
import type { NavTab } from "../components/Sidebar";
import { useOverviewData } from "../hooks/useWorldModel";
import {
  formatConfidence,
  formatDate,
  getOutcomeBadgeColor,
} from "../utils/formatters";

interface OverviewPageProps {
  onNavigate?: (tab: NavTab, entityId?: string) => void;
}

export const OverviewPage: React.FC<OverviewPageProps> = ({ onNavigate }) => {
  const {
    overview,
    metrics,
    changes,
    decisions,
    goals,
    loading,
    error,
    refetch,
  } = useOverviewData();

  if (loading) {
    return (
      <LoadingState
        message="Synthesizing Personal World Model overview..."
        rows={5}
      />
    );
  }

  if (error) {
    return (
      <ErrorState
        title="Failed to load overview data"
        message={error}
        onRetry={refetch}
      />
    );
  }

  const activeProjects = overview?.active_projects || [];
  const activeRelationships = overview?.active_people_relationships || [];

  const statCards = [
    {
      label: "Total Observations",
      value: metrics?.totalObservations ?? 0,
      icon: <Mail className="w-4 h-4 text-blue-400" />,
      tab: "emails" as NavTab,
    },
    {
      label: "People",
      value: metrics?.peopleCount ?? 0,
      icon: <Users className="w-4 h-4 text-blue-400" />,
      tab: "entities" as NavTab,
    },
    {
      label: "Organizations",
      value: metrics?.organizationsCount ?? 0,
      icon: <Building2 className="w-4 h-4 text-indigo-400" />,
      tab: "entities" as NavTab,
    },
    {
      label: "Projects",
      value: metrics?.projectsCount ?? 0,
      icon: <FolderGit2 className="w-4 h-4 text-emerald-400" />,
      tab: "entities" as NavTab,
    },
    {
      label: "Active Relationships",
      value: metrics?.activeRelationshipsCount ?? 0,
      icon: <Users className="w-4 h-4 text-purple-400" />,
      tab: "overview" as NavTab,
    },
    {
      label: "Decisions",
      value: metrics?.decisionsCount ?? 0,
      icon: <Compass className="w-4 h-4 text-amber-400" />,
      tab: "decisions" as NavTab,
    },
    {
      label: "Unresolved Conflicts",
      value: metrics?.unresolvedConflictsCount ?? 0,
      icon: <AlertOctagon className="w-4 h-4 text-red-400" />,
      highlight: (metrics?.unresolvedConflictsCount ?? 0) > 0,
      tab: "timeline" as NavTab,
    },
    {
      label: "Pending Confirmations",
      value: metrics?.pendingConfirmationsCount ?? 0,
      icon: <ShieldAlert className="w-4 h-4 text-amber-400" />,
      tab: "timeline" as NavTab,
    },
  ];

  return (
    <div className="space-y-8">
      {/* Header Thesis Question */}
      <div className="border-b border-gray-800 pb-5">
        <h2 className="text-2xl font-bold text-white tracking-tight">
          What does my Personal Intelligence currently know about my world?
        </h2>
        <p className="text-xs text-gray-400 mt-1.5 leading-relaxed">
          Living, evidence-backed, temporally aware representation of active
          projects, key team members, decision history, and recent updates.
        </p>
      </div>

      {/* Top 8 Summary Metric Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3.5">
        {statCards.map((card, idx) => (
          <div
            key={idx}
            onClick={() => onNavigate?.(card.tab)}
            className={`p-3.5 bg-gray-900/60 hover:bg-gray-900 border rounded-xl space-y-1 transition-all cursor-pointer ${
              card.highlight
                ? "border-red-900/60 bg-red-950/20"
                : "border-gray-800 hover:border-gray-700"
            }`}
          >
            <div className="flex items-center justify-between text-xs text-gray-400">
              <span className="truncate pr-1">{card.label}</span>
              {card.icon}
            </div>
            <p
              className={`text-xl font-bold ${
                card.highlight ? "text-red-400" : "text-white"
              }`}
            >
              {card.value}
            </p>
          </div>
        ))}
      </div>

      {/* Ask World Model Section */}
      <AskBox />

      {/* CURRENT STATE SECTION */}
      <section className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-base font-bold text-white uppercase tracking-wider text-xs text-blue-400 flex items-center space-x-2">
            <span className="w-2 h-2 rounded-full bg-blue-500" />
            <span>Current State</span>
          </h3>
          <span className="text-xs text-gray-500">
            Active World Model Snapshot
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Active Projects */}
          <div className="p-5 bg-gray-900/40 border border-gray-800 rounded-xl space-y-3">
            <div className="flex items-center justify-between">
              <h4 className="text-xs font-semibold text-gray-200 uppercase tracking-wider flex items-center space-x-2">
                <FolderGit2 className="w-4 h-4 text-emerald-400" />
                <span>Active Projects ({activeProjects.length})</span>
              </h4>
            </div>

            {activeProjects.length === 0 ? (
              <EmptyState
                title="No active projects"
                description="No projects currently active."
              />
            ) : (
              <div className="space-y-2">
                {activeProjects.map((p) => (
                  <div
                    key={p.id}
                    onClick={() => onNavigate?.("entities", p.id)}
                    className="p-3 bg-gray-950 border border-gray-800 hover:border-gray-700 rounded-lg flex items-center justify-between transition-colors cursor-pointer"
                  >
                    <div>
                      <h5 className="text-xs font-semibold text-gray-100">
                        {p.name}
                      </h5>
                      <span className="text-[10px] text-gray-500 font-mono">
                        ID: {p.id}
                      </span>
                    </div>
                    <span className="text-[10px] bg-emerald-950 text-emerald-400 border border-emerald-800 px-2 py-0.5 rounded font-mono uppercase font-semibold">
                      Active
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Active Goals */}
          <div className="p-5 bg-gray-900/40 border border-gray-800 rounded-xl space-y-3">
            <div className="flex items-center justify-between">
              <h4 className="text-xs font-semibold text-gray-200 uppercase tracking-wider flex items-center space-x-2">
                <Target className="w-4 h-4 text-purple-400" />
                <span>Active Goals ({goals.length})</span>
              </h4>
            </div>

            {goals.length === 0 ? (
              <EmptyState
                title="No active goals"
                description="No active goals recorded."
              />
            ) : (
              <div className="space-y-2">
                {goals.map((g) => (
                  <div
                    key={g.id}
                    onClick={() => onNavigate?.("entities", g.id)}
                    className="p-3 bg-gray-950 border border-gray-800 hover:border-gray-700 rounded-lg flex items-center justify-between transition-colors cursor-pointer"
                  >
                    <div>
                      <h5 className="text-xs font-semibold text-gray-100">
                        {g.name}
                      </h5>
                      <span className="text-[10px] text-gray-500 font-mono">
                        Status: active
                      </span>
                    </div>
                    <span className="text-[10px] bg-purple-950 text-purple-300 border border-purple-800 px-2 py-0.5 rounded font-mono uppercase font-semibold">
                      Goal
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Important Recent Decisions */}
          <div className="p-5 bg-gray-900/40 border border-gray-800 rounded-xl space-y-3">
            <div className="flex items-center justify-between">
              <h4 className="text-xs font-semibold text-gray-200 uppercase tracking-wider flex items-center space-x-2">
                <Compass className="w-4 h-4 text-amber-400" />
                <span>Important Recent Decisions ({decisions.length})</span>
              </h4>
              <button
                onClick={() => onNavigate?.("decisions")}
                className="text-[11px] text-blue-400 hover:underline cursor-pointer"
              >
                View all
              </button>
            </div>

            {decisions.length === 0 ? (
              <EmptyState
                title="No recent decisions"
                description="Decisions will appear as choices are recorded."
              />
            ) : (
              <div className="space-y-2">
                {decisions.slice(0, 3).map((d) => {
                  const dStatus = String(getattr(d, "status", "MADE"));
                  const dChoice = getattr(d, "decision", null);
                  return (
                    <div
                      key={d.id}
                      onClick={() => onNavigate?.("decisions")}
                      className="p-3 bg-gray-950 border border-gray-800 hover:border-gray-700 rounded-lg space-y-1 transition-colors cursor-pointer text-xs"
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-semibold text-gray-100">
                          {d.name}
                        </span>
                        <span className="text-[10px] bg-amber-950 text-amber-400 border border-amber-800 px-1.5 py-0.5 rounded font-mono">
                          {dStatus}
                        </span>
                      </div>
                      {dChoice !== null && dChoice !== undefined && (
                        <p className="text-[11px] text-emerald-400 font-medium">
                          Selected: {String(dChoice)}
                        </p>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Recent Relationship Changes */}
          <div className="p-5 bg-gray-900/40 border border-gray-800 rounded-xl space-y-3">
            <div className="flex items-center justify-between">
              <h4 className="text-xs font-semibold text-gray-200 uppercase tracking-wider flex items-center space-x-2">
                <Users className="w-4 h-4 text-blue-400" />
                <span>
                  Recent Relationship Edges ({activeRelationships.length})
                </span>
              </h4>
            </div>

            {activeRelationships.length === 0 ? (
              <EmptyState
                title="No relationship edges"
                description="Team relationships recorded."
              />
            ) : (
              <div className="space-y-2">
                {activeRelationships.slice(0, 4).map((r) => (
                  <div
                    key={r.id}
                    className="p-3 bg-gray-950 border border-gray-800 rounded-lg flex items-center justify-between text-xs"
                  >
                    <div className="flex items-center space-x-2">
                      <span className="font-semibold text-gray-200">
                        {r.subject}
                      </span>
                      <ArrowRight className="w-3.5 h-3.5 text-gray-500" />
                      <span className="px-1.5 py-0.5 bg-blue-950 text-blue-300 border border-blue-800 rounded font-mono text-[10px]">
                        {r.predicate}
                      </span>
                      <ArrowRight className="w-3.5 h-3.5 text-gray-500" />
                      <span className="font-semibold text-gray-200">
                        {r.object}
                      </span>
                    </div>
                    <ShieldCheck className="w-4 h-4 text-emerald-400 shrink-0" />
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </section>

      {/* RECENT INTELLIGENCE UPDATES SECTION */}
      <section className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-base font-bold text-white uppercase tracking-wider text-xs text-purple-400 flex items-center space-x-2">
            <span className="w-2 h-2 rounded-full bg-purple-500" />
            <span>Recent Intelligence Updates</span>
          </h3>
          <button
            onClick={() => onNavigate?.("timeline")}
            className="text-xs text-blue-400 hover:underline cursor-pointer"
          >
            View Complete Timeline
          </button>
        </div>

        {changes.length === 0 ? (
          <EmptyState
            title="No recent intelligence updates"
            description="Updates appear when observations are processed."
          />
        ) : (
          <div className="space-y-3">
            {changes.map((change) => {
              const confidenceVal = getattr(
                change.provenance,
                "confidence",
                0.95,
              );
              const obsIds = getattr(
                change.provenance,
                "source_observation_ids",
                [change.observation_id],
              ) as string[];
              const sourceCount = Array.isArray(obsIds) ? obsIds.length : 1;
              const dateStr =
                change.changed_at || String(getattr(change, "changed_at", ""));

              return (
                <div
                  key={change.id}
                  onClick={() => onNavigate?.("timeline", change.entity_id)}
                  className="p-4 bg-gray-900/60 hover:bg-gray-900 border border-gray-800 hover:border-gray-700 rounded-xl flex flex-col md:flex-row md:items-center justify-between gap-3 transition-colors cursor-pointer group"
                >
                  <div className="space-y-1.5">
                    <div className="flex items-center space-x-2.5">
                      <span
                        className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded border ${getOutcomeBadgeColor(change.outcome)}`}
                      >
                        {change.outcome}
                      </span>
                      <h4 className="text-sm font-semibold text-gray-100 group-hover:text-blue-400 transition-colors">
                        {change.description}
                      </h4>
                    </div>

                    <div className="flex flex-wrap items-center gap-3 text-[11px] text-gray-400 pl-0.5">
                      <span className="flex items-center space-x-1 font-mono">
                        <Mail className="w-3.5 h-3.5 text-blue-400" />
                        <span>
                          Sources: {sourceCount} ({change.observation_id})
                        </span>
                      </span>
                      <span>•</span>
                      <span className="text-emerald-400 font-mono flex items-center space-x-1">
                        <CheckCircle2 className="w-3.5 h-3.5" />
                        <span>
                          Confidence:{" "}
                          {formatConfidence(
                            typeof confidenceVal === "number"
                              ? confidenceVal
                              : 0.95,
                          )}
                        </span>
                      </span>
                    </div>
                  </div>

                  <div className="flex items-center space-x-4 shrink-0 justify-between md:justify-end">
                    <span className="text-xs text-gray-500 font-mono flex items-center space-x-1">
                      <Clock className="w-3.5 h-3.5 text-gray-400" />
                      <span>{formatDate(dateStr)}</span>
                    </span>

                    <span className="text-xs text-blue-400 group-hover:translate-x-0.5 transition-transform">
                      <ArrowRight className="w-4 h-4" />
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
};

function getattr(obj: unknown, key: string, fallback: unknown): unknown {
  if (obj && typeof obj === "object" && key in obj) {
    return (obj as Record<string, unknown>)[key];
  }
  return fallback;
}
