import { ArrowRight, Clock, FileText, GitCommit } from "lucide-react";
import React, { useEffect, useState } from "react";
import { worldApi } from "../../api";
import type { StateChange, UIEmailDetail } from "../../types";
import { formatDate, getOutcomeBadgeColor } from "../../utils/formatters";
import { LoadingState } from "../LoadingState";

interface ReconciliationDetailPanelProps {
  change: StateChange;
  onNavigateToEmail?: (id: string) => void;
}

export const ReconciliationDetailPanel: React.FC<
  ReconciliationDetailPanelProps
> = ({ change, onNavigateToEmail }) => {
  const [email, setEmail] = useState<UIEmailDetail | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let mounted = true;
    const loadEmail = async () => {
      if (!change.observation_id) return;
      setLoading(true);
      try {
        const res = await worldApi.getEmailDetail(
          `email_${change.observation_id}`,
        );
        if (mounted) setEmail(res);
      } catch (err) {
        console.warn("Could not load email detail for", change.observation_id);
      } finally {
        if (mounted) setLoading(false);
      }
    };
    void loadEmail();
    return () => {
      mounted = false;
    };
  }, [change.observation_id]);

  if (loading) {
    return (
      <LoadingState message="Loading reconciliation details..." rows={2} />
    );
  }

  const badgeColor = getOutcomeBadgeColor(change.outcome);

  return (
    <div className="space-y-6 animate-in fade-in duration-300">
      {/* Header */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center space-x-3 mb-2">
              <span
                className={`text-[11px] font-bold uppercase px-2.5 py-0.5 rounded border ${badgeColor}`}
              >
                {change.outcome}
              </span>
              <div className="flex items-center space-x-1">
                <Clock className="w-3.5 h-3.5 text-gray-400" />
                <span className="text-xs text-gray-400 font-mono">
                  {formatDate(change.changed_at)}
                </span>
              </div>
            </div>
            <h3 className="text-lg font-bold text-white tracking-tight">
              {change.description}
            </h3>
            {change.requires_review && (
              <p className="text-xs text-amber-400 mt-2 font-medium bg-amber-950/40 inline-block px-2 py-1 rounded border border-amber-900/60">
                ⚠️ Requires User Review
              </p>
            )}
          </div>
        </div>
      </div>

      {/* State Transition Blocks */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* BEFORE */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 flex flex-col">
          <h4 className="text-[10px] font-bold text-gray-500 uppercase tracking-wider mb-3 flex items-center space-x-1">
            <GitCommit className="w-3 h-3" />
            <span>Before</span>
          </h4>
          <div className="flex-1 bg-gray-950 rounded-lg border border-gray-800/60 p-3 flex items-center justify-center min-h-[80px]">
            {change.previous_value ? (
              <span className="text-sm font-mono text-gray-400 break-words text-center">
                {change.previous_value}
              </span>
            ) : (
              <span className="text-xs text-gray-600 italic">
                No previous state
              </span>
            )}
          </div>
        </div>

        {/* NEW EVIDENCE */}
        <div className="bg-blue-950/20 border border-blue-900/40 rounded-xl p-4 flex flex-col relative">
          {/* Arrow Overlays */}
          <div className="hidden md:block absolute -left-3 top-1/2 -translate-y-1/2 bg-gray-900 rounded-full text-gray-600">
            <ArrowRight className="w-5 h-5" />
          </div>
          <div className="hidden md:block absolute -right-3 top-1/2 -translate-y-1/2 bg-gray-900 rounded-full text-gray-600">
            <ArrowRight className="w-5 h-5" />
          </div>

          <h4 className="text-[10px] font-bold text-blue-400 uppercase tracking-wider mb-3 flex items-center space-x-1">
            <FileText className="w-3 h-3" />
            <span>New Evidence</span>
          </h4>
          <div className="flex-1 flex flex-col justify-center min-h-[80px]">
            {email ? (
              <div
                className="cursor-pointer group"
                onClick={() =>
                  onNavigateToEmail && onNavigateToEmail(change.observation_id)
                }
              >
                <p className="text-sm text-blue-300 italic font-serif leading-relaxed line-clamp-4 group-hover:text-blue-200 transition-colors">
                  "{email.snippet}"
                </p>
                <div className="mt-2 text-[10px] text-blue-500/80 uppercase font-bold group-hover:underline">
                  View Source Observation →
                </div>
              </div>
            ) : (
              <p className="text-xs text-gray-500 font-mono break-all text-center">
                Obs ID: {change.observation_id}
              </p>
            )}
          </div>
        </div>

        {/* AFTER */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 flex flex-col">
          <h4 className="text-[10px] font-bold text-emerald-500 uppercase tracking-wider mb-3 flex items-center space-x-1">
            <GitCommit className="w-3 h-3" />
            <span>After</span>
          </h4>
          <div className="flex-1 bg-gray-950 rounded-lg border border-gray-800/60 p-3 flex items-center justify-center min-h-[80px]">
            {change.new_value ? (
              <span className="text-sm font-mono text-emerald-400 break-words text-center">
                {change.new_value}
              </span>
            ) : (
              <span className="text-xs text-gray-600 italic">
                State removed/unchanged
              </span>
            )}
          </div>
        </div>
      </div>

      {/* World Model Persistence Logic */}
      <div className="bg-gray-900/60 border border-gray-800 rounded-xl p-5 space-y-4">
        <h4 className="text-[10px] font-bold text-gray-500 uppercase tracking-wider">
          World Model Persistence
        </h4>

        <div className="space-y-3">
          {change.previous_value && (
            <div className="flex items-center space-x-4">
              <div className="w-32 shrink-0 text-right">
                <span className="text-xs font-bold text-gray-400">
                  HISTORICAL STATE
                </span>
              </div>
              <div className="flex-1 bg-gray-950 border border-gray-800 rounded-lg p-2 flex flex-col sm:flex-row sm:items-center justify-between">
                <span className="text-xs font-mono text-gray-400 px-2">
                  {change.previous_value}
                </span>
                <span className="text-[10px] font-bold text-amber-500 bg-amber-950/40 px-2 py-0.5 rounded border border-amber-900/60 mt-2 sm:mt-0">
                  Valid until {formatDate(change.changed_at)}
                </span>
              </div>
            </div>
          )}

          {change.new_value && (
            <div className="flex items-center space-x-4">
              <div className="w-32 shrink-0 text-right">
                <span className="text-xs font-bold text-emerald-500">
                  CURRENT STATE
                </span>
              </div>
              <div className="flex-1 bg-gray-950 border border-gray-800 rounded-lg p-2 flex flex-col sm:flex-row sm:items-center justify-between">
                <span className="text-xs font-mono text-emerald-400 px-2">
                  {change.new_value}
                </span>
                <span className="text-[10px] font-bold text-emerald-500 bg-emerald-950/40 px-2 py-0.5 rounded border border-emerald-900/60 mt-2 sm:mt-0">
                  Valid from {formatDate(change.timestamp)}
                </span>
              </div>
            </div>
          )}
        </div>

        <div className="mt-4 pt-4 border-t border-gray-800/60 flex justify-between items-center text-xs text-gray-500 font-mono">
          <span>Entity: {change.entity_id || "Global"}</span>
          <span>Record ID: {change.id}</span>
        </div>
      </div>
    </div>
  );
};
