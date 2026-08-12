import React, { useEffect, useState, useMemo } from "react";
import {
  ShieldAlert,
  ShieldCheck,
  Link as LinkIcon,
  AlertTriangle,
} from "lucide-react";
import { worldApi } from "../../api";
import type { UIRelationship, UIEvidence, UITimelineItem } from "../../types";
import { formatConfidence, formatDate } from "../../utils/formatters";
import { LoadingState } from "../LoadingState";
import { ErrorState } from "../ErrorState";
import { EvidenceChainVisualizer } from "../evidence/EvidenceChainVisualizer";
import { CorrectionWorkflow } from "./CorrectionWorkflow";

interface RelationshipInspectorProps {
  relationshipId: string;
  onOpenSubject?: (id: string) => void;
  onOpenObject?: (id: string) => void;
  onViewEvidence?: (id: string) => void;
  onViewTimeline?: (id: string) => void;
}

export const RelationshipInspector: React.FC<RelationshipInspectorProps> = ({
  relationshipId,
  onOpenSubject,
  onOpenObject,
  onViewEvidence,
  onViewTimeline: _onViewTimeline,
}) => {
  const [relationship, setRelationship] = useState<UIRelationship | null>(null);
  const [evidence, setEvidence] = useState<UIEvidence[]>([]);
  const [timeline, setTimeline] = useState<UITimelineItem[]>([]);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [activeTab, setActiveTab] = useState<
    "overview" | "evidence" | "timeline"
  >("overview");

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [relRes, evRes, tlRes] = await Promise.all([
        worldApi.getUIRelationship(relationshipId),
        worldApi.getUIEvidence(relationshipId, 1, 100),
        worldApi.getUIRelationshipTimeline(relationshipId),
      ]);
      setRelationship(relRes);
      setEvidence(evRes.items);
      setTimeline(tlRes);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Failed to fetch relationship data.",
      );
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void fetchData();
  }, [relationshipId]);

  const contradictions = useMemo(() => {
    // Basic contradiction detection: anything below 0.6 confidence or explicit CONFLICT outcome in timeline
    return evidence.filter((e) => e.confidence < 0.6);
  }, [evidence]);

  if (loading)
    return <LoadingState message="Inspecting relationship..." rows={3} />;
  if (error || !relationship)
    return (
      <ErrorState
        title="Failed to load Inspector"
        message={error || "Not found"}
        onRetry={fetchData}
      />
    );

  const isConfirmed =
    relationship.confidence >= 0.85 && relationship.status === "active";
  const isUncertain =
    relationship.confidence < 0.7 || relationship.status === "uncertain";

  const firstObserved =
    timeline.length > 0 ? timeline[timeline.length - 1].timestamp : null;
  const lastConfirmed = timeline.length > 0 ? timeline[0].timestamp : null;

  return (
    <div className="flex flex-col h-full bg-gray-900 overflow-hidden text-sm">
      {/* HEADER: Subject -> Predicate -> Object */}
      <div className="p-5 border-b border-gray-800 shrink-0 bg-gray-950/40">
        <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-4 flex items-center space-x-1.5">
          <LinkIcon className="w-3.5 h-3.5" />
          <span>Relationship Inspector</span>
        </h3>

        <div className="flex flex-col space-y-3">
          <button
            onClick={() => onOpenSubject?.(relationship.subject_id)}
            className="text-left group"
          >
            <span className="text-base text-blue-400 font-semibold group-hover:text-blue-300 transition-colors">
              {relationship.subject_name}
            </span>
          </button>

          <div className="flex items-center space-x-2 pl-3 border-l-2 border-gray-700 ml-1">
            <span className="px-2 py-0.5 bg-purple-950 text-purple-300 border border-purple-800 rounded font-mono text-[11px] font-bold">
              {relationship.predicate}
            </span>
          </div>

          <button
            onClick={() => onOpenObject?.(relationship.object_id)}
            className="text-left group ml-1"
          >
            <span className="text-base text-emerald-400 font-semibold group-hover:text-emerald-300 transition-colors">
              {relationship.object_name}
            </span>
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex items-center space-x-1 border-b border-gray-800 px-4 pt-2 shrink-0 bg-gray-950/20">
        <button
          onClick={() => setActiveTab("overview")}
          className={`px-3 py-2 text-xs font-semibold border-b-2 transition-colors ${activeTab === "overview" ? "border-blue-500 text-blue-400" : "border-transparent text-gray-400 hover:text-gray-200"}`}
        >
          Overview
        </button>
        <button
          onClick={() => setActiveTab("evidence")}
          className={`px-3 py-2 text-xs font-semibold border-b-2 transition-colors flex items-center space-x-1.5 ${activeTab === "evidence" ? "border-blue-500 text-blue-400" : "border-transparent text-gray-400 hover:text-gray-200"}`}
        >
          <span>Evidence</span>
          <span className="bg-gray-800 text-gray-300 px-1.5 py-0.5 rounded-full text-[9px]">
            {evidence.length}
          </span>
        </button>
        <button
          onClick={() => setActiveTab("timeline")}
          className={`px-3 py-2 text-xs font-semibold border-b-2 transition-colors flex items-center space-x-1.5 ${activeTab === "timeline" ? "border-blue-500 text-blue-400" : "border-transparent text-gray-400 hover:text-gray-200"}`}
        >
          <span>History</span>
          <span className="bg-gray-800 text-gray-300 px-1.5 py-0.5 rounded-full text-[9px]">
            {timeline.length}
          </span>
        </button>
      </div>

      {/* CONTENT PANE */}
      <div className="flex-1 overflow-y-auto p-5">
        {/* OVERVIEW TAB */}
        {activeTab === "overview" && (
          <div className="space-y-6 animate-in fade-in duration-200">
            {/* Status & Confidence */}
            <div className="bg-gray-900/60 border border-gray-800 rounded-xl p-4 grid grid-cols-2 gap-4">
              <div>
                <span className="text-gray-500 font-mono text-[10px] block mb-1">
                  Status
                </span>
                {isConfirmed ? (
                  <span className="text-emerald-400 font-semibold flex items-center space-x-1.5">
                    <ShieldCheck className="w-4 h-4" />
                    <span>CONFIRMED ACTIVE</span>
                  </span>
                ) : isUncertain ? (
                  <span className="text-amber-400 font-semibold flex items-center space-x-1.5">
                    <ShieldAlert className="w-4 h-4" />
                    <span>UNCERTAIN</span>
                  </span>
                ) : (
                  <span className="text-gray-300 font-semibold uppercase">
                    {relationship.status}
                  </span>
                )}
              </div>

              <div>
                <span className="text-gray-500 font-mono text-[10px] block mb-1">
                  Confidence
                </span>
                <span className="text-emerald-400 font-semibold font-mono text-base">
                  {formatConfidence(relationship.confidence)}
                </span>
              </div>
            </div>

            <CorrectionWorkflow
              relationshipId={relationship.id}
              currentSubject={relationship.subject_name}
              currentPredicate={relationship.predicate}
              currentObject={relationship.object_name}
              onCorrected={fetchData}
            />

            {/* Temporal Validity & Metadata */}
            <div className="bg-gray-900/60 border border-gray-800 rounded-xl p-4 space-y-4">
              <div>
                <span className="text-gray-500 font-mono text-[10px] block mb-1">
                  Temporal Bounds
                </span>
                <span className="text-gray-300 font-mono text-xs">
                  {relationship.valid_from
                    ? formatDate(relationship.valid_from)
                    : "Open-ended"}
                  {" → "}
                  {relationship.valid_to
                    ? formatDate(relationship.valid_to)
                    : "Present"}
                </span>
              </div>

              <div className="grid grid-cols-2 gap-4 border-t border-gray-800 pt-3">
                <div>
                  <span className="text-gray-500 font-mono text-[10px] block mb-0.5">
                    First Observed
                  </span>
                  <span className="text-gray-400 font-mono text-[11px]">
                    {firstObserved ? formatDate(firstObserved) : "Unknown"}
                  </span>
                </div>
                <div>
                  <span className="text-gray-500 font-mono text-[10px] block mb-0.5">
                    Last Confirmed
                  </span>
                  <span className="text-gray-400 font-mono text-[11px]">
                    {lastConfirmed ? formatDate(lastConfirmed) : "Unknown"}
                  </span>
                </div>
              </div>
            </div>

            {/* Contradiction Warning */}
            {contradictions.length > 0 && (
              <div className="bg-red-950/20 border border-red-900/50 rounded-xl p-4 flex items-start space-x-3">
                <AlertTriangle className="w-5 h-5 text-red-500 shrink-0 mt-0.5" />
                <div>
                  <h4 className="text-sm font-bold text-red-400">
                    Contradictions Detected
                  </h4>
                  <p className="text-xs text-red-300 mt-1">
                    There are {contradictions.length} evidence records with low
                    confidence or conflicting values. Review the Evidence tab.
                  </p>
                </div>
              </div>
            )}

            <div className="pt-2 border-t border-gray-800">
              <span className="text-gray-500 font-mono text-[10px] block">
                Relationship ID
              </span>
              <span className="text-gray-600 font-mono text-[10px] break-all">
                {relationship.id}
              </span>
            </div>
          </div>
        )}

        {/* EVIDENCE TAB */}
        {activeTab === "evidence" && (
          <div className="space-y-6 animate-in fade-in duration-200">
            {evidence.length === 0 ? (
              <p className="text-gray-500 text-xs text-center py-4">
                No evidence records available.
              </p>
            ) : (
              <div className="space-y-8">
                {evidence.map((ev, i) => (
                  <div key={ev.id} className="space-y-4 relative">
                    {/* Visual Connector Line */}
                    {i !== evidence.length - 1 && (
                      <div className="absolute left-6 top-10 bottom-[-2rem] w-[2px] bg-gray-800 z-0"></div>
                    )}

                    <div className="relative z-10">
                      <EvidenceChainVisualizer
                        relationship={relationship}
                        evidence={ev}
                        email={null}
                        onNavigateToEmail={onViewEvidence}
                      />
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* TIMELINE TAB */}
        {activeTab === "timeline" && (
          <div className="space-y-4 animate-in fade-in duration-200">
            {timeline.length === 0 ? (
              <p className="text-gray-500 text-xs text-center py-4">
                No historical records available.
              </p>
            ) : (
              <div className="relative pl-5 border-l-2 border-gray-800 space-y-5">
                {timeline.map((sc) => (
                  <div key={sc.id} className="relative group">
                    <div className="absolute -left-[27px] top-1.5 w-3 h-3 bg-gray-900 border-2 border-blue-500 rounded-full" />
                    <div className="bg-gray-900/60 border border-gray-800 rounded-xl p-3">
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-[10px] font-bold text-gray-400 uppercase tracking-wider">
                          {sc.outcome}
                        </span>
                        <span className="text-[10px] text-gray-500 font-mono">
                          {formatDate(sc.timestamp)}
                        </span>
                      </div>
                      <p className="text-xs text-gray-300 leading-relaxed">
                        {sc.description}
                      </p>

                      {sc.requires_review && (
                        <div className="mt-2 text-[10px] text-amber-500 flex items-center space-x-1">
                          <AlertTriangle className="w-3 h-3" />
                          <span>Requires Review</span>
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
