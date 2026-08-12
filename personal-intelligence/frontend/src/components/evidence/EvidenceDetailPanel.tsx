import {
  AlertTriangle,
  Calendar,
  CheckCircle2,
  FileCheck,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import React, { useEffect, useState } from "react";
import { worldApi } from "../../api";
import type {
  StateChange,
  UIEmailDetail,
  UIEvidence,
  UIRelationship,
} from "../../types";
import { formatConfidence, formatDate } from "../../utils/formatters";
import { ErrorState } from "../ErrorState";
import { LoadingState } from "../LoadingState";
import { EvidenceChainVisualizer } from "./EvidenceChainVisualizer";

interface EvidenceDetailPanelProps {
  relationship: UIRelationship;
  onNavigateToEntity?: (id: string) => void;
  onNavigateToEmail?: (id: string) => void;
}

export const EvidenceDetailPanel: React.FC<EvidenceDetailPanelProps> = ({
  relationship,
  onNavigateToEntity,
  onNavigateToEmail,
}) => {
  const [evidenceList, setEvidenceList] = useState<UIEvidence[]>([]);
  const [emails, setEmails] = useState<Record<string, UIEmailDetail>>({});
  const [history, setHistory] = useState<StateChange[]>([]);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;

    const loadData = async () => {
      setLoading(true);
      setError(null);

      try {
        // Fetch evidence for this relationship/claim
        const evidenceRes = await worldApi.getUIEvidence(
          relationship.id,
          1,
          50,
        );
        const evidenceData = evidenceRes.items;

        // Fetch full email details for each unique observation
        const emailMap: Record<string, UIEmailDetail> = {};
        for (const ev of evidenceData) {
          if (!emailMap[ev.observation_id]) {
            try {
              // try to fetch the email detail
              const email = await worldApi.getEmailDetail(
                `email_${ev.observation_id}`,
              );
              emailMap[ev.observation_id] = email;
            } catch (e) {
              console.warn(
                "Could not load email detail for",
                ev.observation_id,
              );
            }
          }
        }

        // Fetch reconciliation history by filtering global changes for this relationship or its subject
        // In reality, a proper endpoint would be better, but we can filter global changes
        const allChanges = await worldApi.getChanges();
        // Since we don't strictly have relationship_id on StateChange in the DTO if it's not exposed,
        // we'll loosely filter by the description containing the relationship subject or object, or entity_id matching
        const relHistory = allChanges
          .filter(
            (c) =>
              c.entity_id === relationship.subject_id ||
              c.entity_id === relationship.object_id ||
              c.description.includes(relationship.predicate),
          )
          .slice(0, 5); // Just take the most recent 5 relevant ones

        if (mounted) {
          setEvidenceList(evidenceData);
          setEmails(emailMap);
          setHistory(relHistory);
        }
      } catch (err) {
        if (mounted)
          setError(
            err instanceof Error
              ? err.message
              : "Failed to load evidence details.",
          );
      } finally {
        if (mounted) setLoading(false);
      }
    };

    void loadData();

    return () => {
      mounted = false;
    };
  }, [
    relationship.id,
    relationship.subject_id,
    relationship.object_id,
    relationship.predicate,
  ]);

  if (loading) {
    return <LoadingState message="Tracing evidence lineage..." rows={4} />;
  }

  if (error) {
    return <ErrorState title="Lineage Error" message={error} />;
  }

  const primaryEvidence = evidenceList.length > 0 ? evidenceList[0] : null;
  const isConfirmed =
    relationship.confidence >= 0.85 && relationship.status === "active";

  // Group evidence by observation_id to identify contradictions easily
  // If we have multiple evidence items with different text_snippets or confidences, we show them
  const contradictions = evidenceList.filter((e) => e.confidence < 0.7);

  return (
    <div className="space-y-6 animate-in fade-in duration-300">
      {/* 1. Header Information */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
        <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-2">
          Claim Validation
        </h3>
        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center space-x-3 text-lg font-bold text-white tracking-tight mb-2">
              <span
                className="text-blue-400 cursor-pointer hover:underline"
                onClick={() =>
                  onNavigateToEntity &&
                  onNavigateToEntity(relationship.subject_id)
                }
              >
                {relationship.subject_name}
              </span>
              <span className="px-2 py-0.5 bg-purple-950/60 text-purple-300 border border-purple-800/60 rounded font-mono text-xs">
                {relationship.predicate}
              </span>
              <span
                className="text-emerald-400 cursor-pointer hover:underline"
                onClick={() =>
                  onNavigateToEntity &&
                  onNavigateToEntity(relationship.object_id)
                }
              >
                {relationship.object_name}
              </span>
            </div>
            <div className="flex items-center space-x-4 mt-3">
              <span
                className={`text-xs font-semibold px-2 py-1 rounded flex items-center space-x-1.5 ${isConfirmed ? "bg-emerald-950 text-emerald-400 border border-emerald-800" : "bg-amber-950 text-amber-400 border border-amber-800"}`}
              >
                {isConfirmed ? (
                  <ShieldCheck className="w-4 h-4" />
                ) : (
                  <ShieldAlert className="w-4 h-4" />
                )}
                <span>{isConfirmed ? "CONFIRMED" : "UNCERTAIN"}</span>
              </span>
              <span className="text-xs font-mono text-gray-400 flex items-center space-x-1.5">
                <CheckCircle2 className="w-4 h-4 text-emerald-500" />
                <span>
                  Confidence: {formatConfidence(relationship.confidence)}
                </span>
              </span>
              <span className="text-[10px] text-gray-500 font-mono">
                ID: {relationship.id}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* 2. Visual Chain */}
      {primaryEvidence && (
        <div className="space-y-2">
          <h4 className="text-xs font-bold text-gray-300 uppercase tracking-wider">
            Provenance Chain
          </h4>
          <EvidenceChainVisualizer
            relationship={relationship}
            evidence={primaryEvidence}
            email={emails[primaryEvidence.observation_id] || null}
            onNavigateToEntity={onNavigateToEntity}
            onNavigateToEmail={onNavigateToEmail}
          />
        </div>
      )}

      {/* 3. Evidence Records & Contradictions */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h4 className="text-xs font-bold text-gray-300 uppercase tracking-wider flex items-center space-x-2">
            <FileCheck className="w-4 h-4 text-gray-500" />
            <span>Underlying Evidence ({evidenceList.length} sources)</span>
          </h4>
        </div>

        {contradictions.length > 0 && (
          <div className="bg-red-950/40 border border-red-900/60 rounded-xl p-4 flex items-start space-x-3">
            <AlertTriangle className="w-5 h-5 text-red-500 shrink-0 mt-0.5" />
            <div>
              <h5 className="text-sm font-bold text-red-400">
                Contradictory Evidence Detected
              </h5>
              <p className="text-xs text-red-300/80 mt-1 leading-relaxed">
                The world model contains evidence with low confidence or
                conflicting assertions regarding this claim. Do not treat this
                claim as an absolute fact until reconciled.
              </p>
            </div>
          </div>
        )}

        <div className="space-y-3">
          {evidenceList.map((ev, idx) => {
            const email = emails[ev.observation_id];
            const isContradiction = ev.confidence < 0.7;

            return (
              <div
                key={`${ev.id}-${idx}`}
                className={`p-4 rounded-xl border ${isContradiction ? "bg-red-950/20 border-red-900/50" : "bg-gray-900/40 border-gray-800"}`}
              >
                <div className="flex items-start justify-between mb-3">
                  <div className="space-y-1">
                    <div className="flex items-center space-x-2">
                      <span
                        className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded ${isContradiction ? "bg-red-900/40 text-red-400" : "bg-gray-800 text-gray-300"}`}
                      >
                        {isContradiction ? "CONFLICTING" : "SUPPORTING"}
                      </span>
                      <span className="text-[10px] font-mono text-gray-500">
                        Record: {ev.id}
                      </span>
                    </div>
                    {email && (
                      <div
                        className="flex items-center space-x-2 text-xs text-gray-400 cursor-pointer hover:text-blue-400 transition-colors"
                        onClick={() =>
                          onNavigateToEmail &&
                          onNavigateToEmail(ev.observation_id)
                        }
                      >
                        <Calendar className="w-3.5 h-3.5" />
                        <span>
                          {formatDate(email.timestamp)} at{" "}
                          {new Date(email.timestamp).toLocaleTimeString([], {
                            hour: "2-digit",
                            minute: "2-digit",
                          })}
                        </span>
                        <span>•</span>
                        <span
                          className="truncate max-w-[200px]"
                          title={email.subject}
                        >
                          Subj: {email.subject}
                        </span>
                      </div>
                    )}
                  </div>
                  <div className="text-right">
                    <span
                      className={`text-xs font-mono font-bold ${isContradiction ? "text-red-400" : "text-emerald-400"}`}
                    >
                      {formatConfidence(ev.confidence)}
                    </span>
                    <p className="text-[9px] text-gray-500 uppercase">
                      Extraction Conf.
                    </p>
                  </div>
                </div>

                <div className="relative">
                  <div className="absolute left-0 top-0 bottom-0 w-1 bg-gray-700 rounded-l"></div>
                  <p className="pl-4 text-sm text-gray-300 font-serif leading-relaxed italic">
                    "{ev.text_snippet}"
                  </p>
                </div>
              </div>
            );
          })}

          {evidenceList.length === 0 && (
            <div className="p-6 bg-gray-900/40 border border-gray-800 rounded-xl text-center text-gray-500 text-xs">
              No direct evidence spans found for this claim.
            </div>
          )}
        </div>
      </div>

      {/* 4. Reconciliation History */}
      {history.length > 0 && (
        <div className="space-y-3">
          <h4 className="text-xs font-bold text-gray-300 uppercase tracking-wider flex items-center space-x-2">
            <RefreshCw className="w-4 h-4 text-gray-500" />
            <span>Reconciliation History</span>
          </h4>
          <div className="bg-gray-900/40 border border-gray-800 rounded-xl p-4 space-y-4">
            {history.map((change, idx) => (
              <div key={change.id} className="relative pl-4">
                {idx !== history.length - 1 && (
                  <div className="absolute left-1.5 top-5 bottom-[-1rem] w-px bg-gray-800"></div>
                )}
                <div className="absolute left-0 top-1.5 w-3 h-3 rounded-full bg-blue-900 border-2 border-gray-950"></div>

                <div className="mb-1 flex items-center space-x-2">
                  <span className="text-[10px] text-gray-500 font-mono">
                    {formatDate(change.timestamp)}
                  </span>
                  <span className="text-[10px] font-bold uppercase text-blue-400 bg-blue-950/40 px-1.5 rounded">
                    {change.outcome}
                  </span>
                </div>
                <p className="text-xs text-gray-300">{change.description}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
