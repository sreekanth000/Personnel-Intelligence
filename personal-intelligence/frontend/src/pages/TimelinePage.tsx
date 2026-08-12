import React, { useState, useEffect } from "react";
import { AlertCircle, Clock, GitCommit, ShieldCheck } from "lucide-react";
import { EmptyState } from "../components/EmptyState";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/LoadingState";
import { ReconciliationDetailPanel } from "../components/timeline/ReconciliationDetailPanel";
import { useChanges } from "../hooks/useWorldModel";
import type { StateChange } from "../types";
import { getOutcomeBadgeColor } from "../utils/formatters";

export const TimelinePage: React.FC = () => {
  const { changes, loading, error, refetch } = useChanges();
  const [selectedChange, setSelectedChange] = useState<StateChange | null>(
    null,
  );

  useEffect(() => {
    const handleDeepLink = (e: Event) => {
      const customEvent = e as CustomEvent;
      if (customEvent.detail?.tab === "timeline" && customEvent.detail?.id) {
        const matched = changes.find((c) => c.id === customEvent.detail.id);
        if (matched) {
          setSelectedChange(matched);
        }
      }
    };
    window.addEventListener("deeplink", handleDeepLink);
    return () => window.removeEventListener("deeplink", handleDeepLink);
  }, [changes]);

  // Auto-select the first change when loaded if nothing is selected
  if (!loading && changes.length > 0 && !selectedChange) {
    setSelectedChange(changes[0]);
  }

  if (loading)
    return (
      <LoadingState message="Fetching chronological timeline..." rows={4} />
    );
  if (error)
    return (
      <ErrorState
        title="Failed to load timeline"
        message={error}
        onRetry={refetch}
      />
    );

  return (
    <div className="h-[calc(100vh-8rem)] flex flex-col space-y-4">
      <div className="shrink-0">
        <h2 className="text-xl font-bold text-white tracking-tight">
          Timeline & Historical Lineage
        </h2>
        <p className="text-xs text-gray-400 mt-1">
          Chronological audit trail of all state changes, relationship updates,
          handovers, and reconciliation cycles
        </p>
      </div>

      <div className="flex-1 flex space-x-4 min-h-0">
        {/* LEFT COLUMN: Timeline Master List */}
        <div className="w-1/3 min-w-[320px] bg-gray-900 border border-gray-800 rounded-2xl overflow-hidden flex flex-col shrink-0">
          <div className="flex-1 overflow-y-auto p-4">
            {changes.length === 0 ? (
              <EmptyState
                title="No timeline entries recorded"
                description="State updates will populate here as observations are ingested."
              />
            ) : (
              <div className="relative pl-6 border-l-2 border-gray-800 space-y-4">
                {changes.map((c) => {
                  const isSelected = selectedChange?.id === c.id;

                  return (
                    <div key={c.id} className="relative group">
                      <div
                        className={`absolute -left-[31px] top-1.5 p-1 border-2 rounded-full transition-colors ${isSelected ? "bg-blue-900 border-blue-500 text-blue-200 shadow-[0_0_10px_rgba(59,130,246,0.5)]" : "bg-gray-950 border-gray-700 text-blue-400 group-hover:border-blue-500"}`}
                      >
                        <GitCommit className="w-3.5 h-3.5" />
                      </div>

                      <button
                        onClick={() => setSelectedChange(c)}
                        className={`w-full text-left p-3 border rounded-xl space-y-3 transition-colors cursor-pointer ${isSelected ? "bg-gray-800 border-gray-600 shadow-md" : "bg-gray-900/60 hover:bg-gray-900 border-gray-800"}`}
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center space-x-2.5">
                            <span
                              className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded border ${getOutcomeBadgeColor(c.outcome)}`}
                            >
                              {c.outcome}
                            </span>
                            <h4 className="text-sm font-semibold text-gray-200 truncate pr-2">
                              {c.description}
                            </h4>
                          </div>

                          <span className="text-[10px] text-gray-500 font-mono flex items-center space-x-1 shrink-0">
                            <Clock className="w-3 h-3 text-gray-400" />
                            <span>
                              {new Date(c.changed_at).toLocaleDateString([], {
                                month: "short",
                                day: "numeric",
                              })}
                            </span>
                          </span>
                        </div>

                        <div className="flex items-center justify-between text-[10px] text-gray-400 pt-2 border-t border-gray-800/60">
                          <span className="font-mono text-gray-500 truncate mr-2">
                            Obs:{" "}
                            <span className="text-gray-400">
                              {c.observation_id.substring(0, 15)}...
                            </span>
                          </span>

                          {c.requires_review ? (
                            <span className="flex items-center space-x-1 text-amber-400 font-medium shrink-0">
                              <AlertCircle className="w-3 h-3" />
                              <span>Review</span>
                            </span>
                          ) : (
                            <span className="flex items-center space-x-1 text-emerald-400 font-medium shrink-0">
                              <ShieldCheck className="w-3 h-3" />
                              <span>Reconciled</span>
                            </span>
                          )}
                        </div>
                      </button>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {/* RIGHT COLUMN: Reconciliation Detail Panel */}
        <div className="flex-1 bg-gray-900 border border-gray-800 rounded-2xl overflow-y-auto">
          {selectedChange ? (
            <div className="p-6">
              <ReconciliationDetailPanel
                change={selectedChange}
                onNavigateToEmail={(id) => console.log("Navigate to email", id)}
              />
            </div>
          ) : (
            <div className="h-full flex items-center justify-center">
              <EmptyState
                title="No Change Selected"
                description="Select an event from the timeline to view reconciliation details."
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
