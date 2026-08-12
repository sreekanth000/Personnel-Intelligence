import React from "react";
import { CheckCircle2, Compass, HelpCircle, Lightbulb } from "lucide-react";
import { EmptyState } from "../components/EmptyState";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/LoadingState";
import { useDecisions } from "../hooks/useWorldModel";
import type { Decision } from "../types";
import { formatConfidence, formatDate } from "../utils/formatters";

export const DecisionsPage: React.FC = () => {
  const { decisions, loading, error, refetch } = useDecisions();

  if (loading)
    return (
      <LoadingState message="Loading decision memory records..." rows={3} />
    );
  if (error)
    return (
      <ErrorState
        title="Failed to load decisions"
        message={error}
        onRetry={refetch}
      />
    );

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-white tracking-tight">
          Decision Memory
        </h2>
        <p className="text-xs text-gray-400 mt-1">
          Structured representations of key personal and architectural decisions
          (question, alternatives, context, decision, status)
        </p>
      </div>

      {decisions.length === 0 ? (
        <EmptyState
          title="No decisions recorded"
          description="Decisions are extracted when choices and selections are mentioned in observations."
        />
      ) : (
        <div className="space-y-4">
          {decisions.map((d: Decision) => (
            <div
              key={d.id}
              className="p-5 bg-gray-900/60 border border-gray-800 rounded-xl space-y-4"
            >
              <div className="flex items-start justify-between">
                <div className="flex items-center space-x-2.5">
                  <div className="p-2 bg-amber-950/60 border border-amber-800/60 rounded-lg text-amber-400">
                    <Compass className="w-5 h-5" />
                  </div>
                  <div>
                    <h4 className="text-sm font-semibold text-gray-100">
                      {d.name}
                    </h4>
                    <span className="text-[10px] font-mono text-gray-500">
                      ID: {d.id}
                    </span>
                  </div>
                </div>

                <div className="flex items-center space-x-2">
                  <span className="text-[10px] font-semibold uppercase px-2 py-0.5 bg-amber-950 text-amber-400 border border-amber-800 rounded">
                    {d.status || "MADE"}
                  </span>
                  <span className="text-[11px] text-gray-400 font-mono">
                    {formatConfidence(d.confidence?.score)}
                  </span>
                </div>
              </div>

              {d.question && (
                <div className="p-3 bg-gray-950 border border-gray-800 rounded-lg space-y-1 text-xs">
                  <span className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider flex items-center space-x-1">
                    <HelpCircle className="w-3 h-3 text-blue-400" />
                    <span>Decision Question</span>
                  </span>
                  <p className="text-gray-200 font-medium">{d.question}</p>
                </div>
              )}

              {d.decision && (
                <div className="p-3 bg-emerald-950/40 border border-emerald-900/50 rounded-lg space-y-1 text-xs">
                  <span className="text-[10px] font-semibold text-emerald-400 uppercase tracking-wider flex items-center space-x-1">
                    <CheckCircle2 className="w-3 h-3 text-emerald-400" />
                    <span>Selected Decision</span>
                  </span>
                  <p className="text-emerald-200 font-semibold">{d.decision}</p>
                </div>
              )}

              {d.alternatives && d.alternatives.length > 0 && (
                <div className="space-y-1 text-xs">
                  <span className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider flex items-center space-x-1">
                    <Lightbulb className="w-3 h-3 text-amber-400" />
                    <span>Considered Alternatives</span>
                  </span>
                  <div className="flex flex-wrap gap-1.5 pt-0.5">
                    {d.alternatives.map((alt, i) => (
                      <span
                        key={i}
                        className="text-xs bg-gray-800 text-gray-300 border border-gray-700 px-2 py-0.5 rounded"
                      >
                        {alt}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              <div className="flex items-center justify-between text-[11px] text-gray-500 pt-2 border-t border-gray-800/60">
                <span>
                  Context: {d.context || "Personal Intelligence architecture"}
                </span>
                <span>Recorded: {formatDate(d.created_at)}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
