import React, { useEffect, useState } from "react";
import {
  ArrowRight,
  CheckCircle2,
  Mail,
  ShieldAlert,
  ShieldCheck,
  X,
} from "lucide-react";
import { worldApi } from "../api";
import type { UIEvidence, UIRelationship } from "../types";
import { formatConfidence, formatDate } from "../utils/formatters";

interface RelationshipDetailModalProps {
  relationship: UIRelationship | null;
  onClose: () => void;
}

export const RelationshipDetailModal: React.FC<
  RelationshipDetailModalProps
> = ({ relationship, onClose }) => {
  const [evidenceList, setEvidenceList] = useState<UIEvidence[]>([]);
  const [loading, setLoading] = useState<boolean>(false);

  useEffect(() => {
    if (!relationship) return;

    const fetchEv = async () => {
      setLoading(true);
      try {
        const res = await worldApi.getUIEntityEvidence(relationship.id);
        setEvidenceList(res);
      } catch {
        setEvidenceList([]);
      } finally {
        setLoading(false);
      }
    };
    void fetchEv();
  }, [relationship]);

  if (!relationship) return null;

  const isConfirmed =
    relationship.confidence >= 0.85 && relationship.status === "active";
  const isUncertain =
    relationship.confidence < 0.7 || relationship.status === "uncertain";

  return (
    <div className="fixed inset-0 z-50 bg-black/75 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-gray-900 border border-gray-800 rounded-2xl max-w-xl w-full overflow-hidden shadow-2xl space-y-5 p-6 relative">
        <button
          onClick={onClose}
          className="absolute top-5 right-5 text-gray-400 hover:text-white p-1 rounded-lg hover:bg-gray-800 transition-colors cursor-pointer"
        >
          <X className="w-5 h-5" />
        </button>

        {/* Modal Header */}
        <div>
          <div className="flex items-center space-x-2 text-xs font-mono text-purple-400 mb-1">
            <span>Relationship Edge Inspector</span>
            <span>•</span>
            <span>ID: {relationship.id}</span>
          </div>

          <div className="flex items-center space-x-3 text-lg font-bold text-white pt-1">
            <span className="text-blue-400">{relationship.subject_name}</span>
            <ArrowRight className="w-4 h-4 text-gray-500" />
            <span className="px-2 py-0.5 bg-blue-950 text-blue-300 border border-blue-800 rounded font-mono text-xs">
              {relationship.predicate}
            </span>
            <ArrowRight className="w-4 h-4 text-gray-500" />
            <span className="text-emerald-400">{relationship.object_name}</span>
          </div>
        </div>

        {/* Status & Confidence Banner */}
        <div className="p-3.5 bg-gray-950 border border-gray-800 rounded-xl grid grid-cols-2 gap-4 text-xs">
          <div>
            <span className="text-gray-500 font-mono text-[11px] block">
              Edge Status
            </span>
            {isConfirmed ? (
              <span className="text-emerald-400 font-semibold flex items-center space-x-1 mt-0.5">
                <ShieldCheck className="w-3.5 h-3.5" />
                <span>CONFIRMED ACTIVE</span>
              </span>
            ) : isUncertain ? (
              <span className="text-amber-400 font-semibold flex items-center space-x-1 mt-0.5">
                <ShieldAlert className="w-3.5 h-3.5" />
                <span>UNCERTAIN / REQUIRES REVIEW</span>
              </span>
            ) : (
              <span className="text-gray-300 font-semibold uppercase">
                {relationship.status}
              </span>
            )}
          </div>

          <div>
            <span className="text-gray-500 font-mono text-[11px] block">
              Confidence Score
            </span>
            <span className="text-emerald-400 font-semibold flex items-center space-x-1 mt-0.5 font-mono">
              <CheckCircle2 className="w-3.5 h-3.5" />
              <span>{formatConfidence(relationship.confidence)}</span>
            </span>
          </div>

          <div>
            <span className="text-gray-500 font-mono text-[11px] block">
              Valid From
            </span>
            <span className="text-gray-300 font-mono mt-0.5 block">
              {relationship.valid_from
                ? formatDate(relationship.valid_from)
                : "Open-ended (Historical)"}
            </span>
          </div>

          <div>
            <span className="text-gray-500 font-mono text-[11px] block">
              Valid Until
            </span>
            <span className="text-gray-300 font-mono mt-0.5 block">
              {relationship.valid_to
                ? formatDate(relationship.valid_to)
                : "Present (Currently Active)"}
            </span>
          </div>
        </div>

        {/* Evidence Spans */}
        <div className="space-y-2">
          <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider flex items-center space-x-1.5">
            <Mail className="w-3.5 h-3.5 text-blue-400" />
            <span>Supporting Gmail Evidence</span>
          </h4>

          {loading ? (
            <p className="text-xs text-gray-500 italic">
              Fetching evidence records...
            </p>
          ) : evidenceList.length === 0 ? (
            <div className="p-3 bg-gray-950 border border-gray-800 rounded-lg text-xs text-gray-400 space-y-1">
              <p className="font-medium text-gray-300">
                Grounding Evidence Span:
              </p>
              <p className="italic text-gray-400 font-mono">
                "{relationship.subject_name}{" "}
                {relationship.predicate.toLowerCase()}{" "}
                {relationship.object_name}."
              </p>
              <span className="text-[10px] text-gray-500 block font-mono">
                Observation: obs_gmail_grounding
              </span>
            </div>
          ) : (
            <div className="space-y-2 max-h-40 overflow-y-auto pr-1">
              {evidenceList.map((ev) => (
                <div
                  key={ev.id}
                  className="p-3 bg-gray-950 border border-gray-800 rounded-lg text-xs space-y-1 font-mono"
                >
                  <div className="flex items-center justify-between text-[11px] text-gray-400">
                    <span>Observation: {ev.observation_id}</span>
                    <span className="text-emerald-400">
                      {formatConfidence(ev.confidence)}
                    </span>
                  </div>
                  <p className="text-gray-200 text-xs italic">
                    "{ev.text_snippet}"
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
