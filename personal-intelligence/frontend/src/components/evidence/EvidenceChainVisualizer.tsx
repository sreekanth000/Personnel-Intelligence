import React from "react";
import {
  ArrowRight,
  Database,
  ExternalLink,
  FileText,
  Globe2,
  Link as LinkIcon,
  Mail,
} from "lucide-react";
import type { UIRelationship, UIEvidence, UIEmailDetail } from "../../types";

interface EvidenceChainVisualizerProps {
  relationship: UIRelationship;
  evidence: UIEvidence;
  email: UIEmailDetail | null;
  onNavigateToEntity?: (id: string) => void;
  onNavigateToEmail?: (id: string) => void;
}

export const EvidenceChainVisualizer: React.FC<
  EvidenceChainVisualizerProps
> = ({
  relationship,
  evidence,
  email,
  onNavigateToEntity,
  onNavigateToEmail,
}) => {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 overflow-x-auto">
      <div className="flex items-center min-w-max space-x-2">
        {/* Step 1: World Model */}
        <div className="flex flex-col items-center group cursor-default">
          <div className="w-10 h-10 rounded-full bg-blue-950/40 border border-blue-800/60 text-blue-400 flex items-center justify-center shadow-lg transition-transform group-hover:scale-105">
            <Globe2 className="w-5 h-5" />
          </div>
          <span className="text-[9px] font-bold uppercase tracking-wider text-gray-500 mt-2">
            World Model
          </span>
          <span className="text-[10px] text-gray-400 font-mono mt-0.5">
            Synthesized
          </span>
        </div>

        <ArrowRight className="w-4 h-4 text-gray-700 shrink-0" />

        {/* Step 2: Relationship */}
        <div
          className="flex flex-col items-center group cursor-pointer"
          onClick={() =>
            onNavigateToEntity && onNavigateToEntity(relationship.subject_id)
          }
        >
          <div className="w-10 h-10 rounded-full bg-purple-950/40 border border-purple-800/60 text-purple-400 flex items-center justify-center shadow-lg transition-transform group-hover:scale-105 relative">
            <LinkIcon className="w-5 h-5" />
            <ExternalLink className="w-3 h-3 absolute -top-1 -right-1 opacity-0 group-hover:opacity-100 transition-opacity text-purple-300 bg-gray-900 rounded-full p-0.5" />
          </div>
          <span className="text-[9px] font-bold uppercase tracking-wider text-gray-500 mt-2">
            Relationship
          </span>
          <span
            className="text-[10px] text-purple-400 font-mono mt-0.5 max-w-[80px] truncate"
            title={relationship.predicate}
          >
            {relationship.predicate}
          </span>
        </div>

        <ArrowRight className="w-4 h-4 text-gray-700 shrink-0" />

        {/* Step 3: Claim */}
        <div className="flex flex-col items-center group cursor-default">
          <div className="w-10 h-10 rounded-full bg-emerald-950/40 border border-emerald-800/60 text-emerald-400 flex items-center justify-center shadow-lg transition-transform group-hover:scale-105">
            <Database className="w-5 h-5" />
          </div>
          <span className="text-[9px] font-bold uppercase tracking-wider text-gray-500 mt-2">
            Claim
          </span>
          <span className="text-[10px] text-emerald-400 font-mono mt-0.5">
            Asserted
          </span>
        </div>

        <ArrowRight className="w-4 h-4 text-gray-700 shrink-0" />

        {/* Step 4: Evidence Span */}
        <div className="flex flex-col items-center group cursor-default relative">
          <div
            className={`w-10 h-10 rounded-full flex items-center justify-center shadow-lg transition-transform group-hover:scale-105 border ${evidence.confidence < 0.7 ? "bg-amber-950/40 border-amber-800/60 text-amber-400" : "bg-gray-800/60 border-gray-700 text-gray-300"}`}
          >
            <FileText className="w-5 h-5" />
          </div>
          <span className="text-[9px] font-bold uppercase tracking-wider text-gray-500 mt-2">
            Evidence
          </span>
          <span
            className={`text-[10px] font-mono mt-0.5 ${evidence.confidence < 0.7 ? "text-amber-400" : "text-gray-400"}`}
          >
            Span
          </span>
        </div>

        <ArrowRight className="w-4 h-4 text-gray-700 shrink-0" />

        {/* Step 5: Gmail Message */}
        <div
          className="flex flex-col items-center group cursor-pointer"
          onClick={() =>
            onNavigateToEmail && onNavigateToEmail(evidence.observation_id)
          }
        >
          <div className="w-10 h-10 rounded-full bg-red-950/40 border border-red-800/60 text-red-400 flex items-center justify-center shadow-lg transition-transform group-hover:scale-105 relative">
            <Mail className="w-5 h-5" />
            <ExternalLink className="w-3 h-3 absolute -top-1 -right-1 opacity-0 group-hover:opacity-100 transition-opacity text-red-300 bg-gray-900 rounded-full p-0.5" />
          </div>
          <span className="text-[9px] font-bold uppercase tracking-wider text-gray-500 mt-2">
            Gmail Msg
          </span>
          <span
            className="text-[10px] text-red-400 font-mono mt-0.5 truncate max-w-[80px]"
            title={email?.subject || evidence.observation_id}
          >
            {email ? "Loaded" : "Obs_ID"}
          </span>
        </div>
      </div>
    </div>
  );
};
