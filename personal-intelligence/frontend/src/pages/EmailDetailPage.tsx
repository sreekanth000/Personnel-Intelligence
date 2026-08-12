import React, { useEffect, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Brain,
  Building2,
  CheckCircle2,
  Clock,
  Compass,
  FileCode,
  FileText,
  FolderGit2,
  Highlighter,
  Mail,
  ShieldCheck,
  Tag,
  User,
} from "lucide-react";
import { worldApi } from "../api";
import { EmptyState } from "../components/EmptyState";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/LoadingState";
import type { UIEmailDetail, UIExtractionItem } from "../types";
import {
  formatConfidence,
  formatDate,
  getEntityTypeColor,
} from "../utils/formatters";

interface EmailDetailPageProps {
  emailId: string;
  onBack?: () => void;
}

export const EmailDetailPage: React.FC<EmailDetailPageProps> = ({
  emailId,
  onBack,
}) => {
  const [emailDetail, setEmailDetail] = useState<UIEmailDetail | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedItem, setSelectedItem] = useState<UIExtractionItem | null>(
    null,
  );

  useEffect(() => {
    const fetchDetail = async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await worldApi.getEmailDetail(emailId);
        setEmailDetail(res);
        if (res.extractions && res.extractions.length > 0) {
          setSelectedItem(res.extractions[0]);
        }
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Failed to fetch email details.",
        );
      } finally {
        setLoading(false);
      }
    };
    void fetchDetail();
  }, [emailId]);

  if (loading) {
    return (
      <LoadingState
        message="Loading normalized email and GPT-4.1 extractions..."
        rows={4}
      />
    );
  }

  if (error || !emailDetail) {
    return (
      <ErrorState
        title="Failed to load email inspection"
        message={error || "Email record not found."}
        onRetry={() => window.location.reload()}
      />
    );
  }

  const highlightSnippet = selectedItem?.evidence_span?.text_snippet;

  // Helper to render body with active evidence highlighting
  const renderHighlightedBody = (body: string) => {
    if (!highlightSnippet || !body.includes(highlightSnippet)) {
      return (
        <pre className="whitespace-pre-wrap font-sans text-sm text-gray-200 leading-relaxed">
          {body}
        </pre>
      );
    }

    const parts = body.split(highlightSnippet);
    return (
      <div className="font-sans text-sm text-gray-200 leading-relaxed whitespace-pre-wrap">
        {parts.map((part, idx) => (
          <React.Fragment key={idx}>
            {part}
            {idx < parts.length - 1 && (
              <mark className="bg-purple-950 text-purple-200 border-b-2 border-purple-400 px-1 py-0.5 rounded font-medium shadow-sm transition-all animate-pulse">
                {highlightSnippet}
              </mark>
            )}
          </React.Fragment>
        ))}
      </div>
    );
  };

  const getCategoryIcon = (type: string) => {
    switch (type.toLowerCase()) {
      case "entity":
      case "person":
        return <User className="w-3.5 h-3.5 text-blue-400" />;
      case "organization":
        return <Building2 className="w-3.5 h-3.5 text-indigo-400" />;
      case "project":
        return <FolderGit2 className="w-3.5 h-3.5 text-emerald-400" />;
      case "decision":
        return <Compass className="w-3.5 h-3.5 text-amber-400" />;
      default:
        return <FileCode className="w-3.5 h-3.5 text-purple-400" />;
    }
  };

  return (
    <div className="space-y-6">
      {/* Top Header & Visual Lineage Flow Banner */}
      <div className="flex items-center justify-between border-b border-gray-800 pb-4">
        <div className="flex items-center space-x-3">
          {onBack && (
            <button
              onClick={onBack}
              className="p-2 bg-gray-900 hover:bg-gray-800 border border-gray-800 rounded-lg text-gray-400 hover:text-white transition-colors cursor-pointer"
            >
              <ArrowLeft className="w-4 h-4" />
            </button>
          )}
          <div>
            <h2 className="text-xl font-bold text-white tracking-tight">
              GPT-4.1 Extraction Inspection
            </h2>
            <p className="text-xs text-gray-400 mt-0.5">
              Read-only quality inspection connecting raw text to evidence spans
              and World Model state
            </p>
          </div>
        </div>

        <span className="text-xs text-purple-400 bg-purple-950/60 border border-purple-800/60 px-3 py-1 rounded-full font-mono flex items-center space-x-1.5">
          <Brain className="w-3.5 h-3.5" />
          <span>GPT-4.1 Extractor Active</span>
        </span>
      </div>

      {/* Visual Lineage Connection Flow */}
      <div className="p-3.5 bg-gray-900/80 border border-purple-900/40 rounded-xl flex items-center justify-between text-xs text-gray-300 font-mono overflow-x-auto">
        <span className="flex items-center space-x-1.5 text-blue-400 shrink-0">
          <FileText className="w-4 h-4" />
          <span>Email Text</span>
        </span>
        <ArrowRight className="w-4 h-4 text-gray-600 shrink-0 mx-2" />
        <span className="flex items-center space-x-1.5 text-amber-400 shrink-0">
          <Highlighter className="w-4 h-4" />
          <span>Evidence Span</span>
        </span>
        <ArrowRight className="w-4 h-4 text-gray-600 shrink-0 mx-2" />
        <span className="flex items-center space-x-1.5 text-purple-400 shrink-0">
          <Brain className="w-4 h-4" />
          <span>GPT-4.1 Extraction</span>
        </span>
        <ArrowRight className="w-4 h-4 text-gray-600 shrink-0 mx-2" />
        <span className="flex items-center space-x-1.5 text-emerald-400 shrink-0">
          <ShieldCheck className="w-4 h-4" />
          <span>World Model Entity/Relation</span>
        </span>
      </div>

      {/* DESKTOP 3-COLUMN LAYOUT */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* LEFT COLUMN (3 cols): Email Metadata */}
        <div className="lg:col-span-3 bg-gray-900/60 border border-gray-800 rounded-xl p-5 space-y-4">
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider border-b border-gray-800 pb-2">
            Email Metadata
          </h3>

          <div className="space-y-3.5 text-xs">
            <div>
              <span className="text-gray-500 font-mono text-[11px] block">
                Sender
              </span>
              <span className="text-gray-200 font-semibold font-mono">
                {emailDetail.sender}
              </span>
            </div>

            <div>
              <span className="text-gray-500 font-mono text-[11px] block">
                Recipients
              </span>
              <div className="flex flex-wrap gap-1 mt-0.5">
                {emailDetail.recipients.map((r, i) => (
                  <span
                    key={i}
                    className="px-1.5 py-0.5 bg-gray-950 border border-gray-800 text-gray-300 rounded font-mono text-[11px]"
                  >
                    {r}
                  </span>
                ))}
              </div>
            </div>

            <div>
              <span className="text-gray-500 font-mono text-[11px] block">
                Subject
              </span>
              <span className="text-gray-200 font-medium">
                {emailDetail.subject}
              </span>
            </div>

            <div>
              <span className="text-gray-500 font-mono text-[11px] block">
                Timestamp
              </span>
              <span className="text-gray-300 font-mono flex items-center space-x-1 mt-0.5">
                <Clock className="w-3.5 h-3.5 text-gray-500" />
                <span>{formatDate(emailDetail.timestamp)}</span>
              </span>
            </div>

            <div>
              <span className="text-gray-500 font-mono text-[11px] block">
                Thread ID
              </span>
              <span className="text-blue-400 font-mono text-[11px]">
                {emailDetail.thread_id}
              </span>
            </div>

            <div>
              <span className="text-gray-500 font-mono text-[11px] block mb-1">
                Labels
              </span>
              <div className="flex flex-wrap gap-1.5">
                {emailDetail.labels.map((lbl, idx) => (
                  <span
                    key={idx}
                    className="px-2 py-0.5 bg-blue-950 text-blue-300 border border-blue-800/80 rounded text-[10px] font-semibold uppercase flex items-center space-x-1"
                  >
                    <Tag className="w-3 h-3" />
                    <span>{lbl}</span>
                  </span>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* CENTER COLUMN (5 cols): Normalized Email Content */}
        <div className="lg:col-span-5 bg-gray-900/60 border border-gray-800 rounded-xl p-5 space-y-4">
          <div className="flex items-center justify-between border-b border-gray-800 pb-2">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider flex items-center space-x-2">
              <Mail className="w-4 h-4 text-blue-400" />
              <span>Normalized Email Body</span>
            </h3>
            <span className="text-[11px] font-mono text-gray-500">
              Msg ID: {emailDetail.message_id}
            </span>
          </div>

          {selectedItem && (
            <div className="p-2.5 bg-purple-950/40 border border-purple-800/60 rounded-lg text-xs text-purple-200 flex items-center justify-between">
              <span className="flex items-center space-x-1.5 font-mono">
                <Highlighter className="w-3.5 h-3.5 text-purple-400 shrink-0" />
                <span>
                  Highlighting Evidence: "
                  {selectedItem.evidence_span.text_snippet}"
                </span>
              </span>
            </div>
          )}

          <div className="p-4 bg-gray-950 border border-gray-800 rounded-xl min-h-[300px]">
            {renderHighlightedBody(emailDetail.body)}
          </div>
        </div>

        {/* RIGHT COLUMN (4 cols): GPT-4.1 Extraction */}
        <div className="lg:col-span-4 bg-gray-900/60 border border-gray-800 rounded-xl p-5 space-y-4">
          <div className="flex items-center justify-between border-b border-gray-800 pb-2">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider flex items-center space-x-2">
              <Brain className="w-4 h-4 text-purple-400" />
              <span>
                GPT-4.1 Extracted Objects ({emailDetail.extractions.length})
              </span>
            </h3>
          </div>

          {emailDetail.extractions.length === 0 ? (
            <EmptyState
              title="No extractions found"
              description="No structured entities or relationships extracted."
            />
          ) : (
            <div className="space-y-3 max-h-[520px] overflow-y-auto pr-1">
              {emailDetail.extractions.map((item) => {
                const isSelected = selectedItem?.id === item.id;
                return (
                  <div
                    key={item.id}
                    onClick={() => setSelectedItem(item)}
                    className={`p-3.5 rounded-xl border transition-all cursor-pointer space-y-2 ${
                      isSelected
                        ? "bg-purple-950/50 border-purple-600 shadow-lg shadow-purple-500/10"
                        : "bg-gray-950 border-gray-800 hover:border-gray-700"
                    }`}
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex items-center space-x-2">
                        <div className="p-1.5 bg-gray-900 border border-gray-800 rounded">
                          {getCategoryIcon(item.extraction_type)}
                        </div>
                        <span className="text-xs font-bold text-gray-100">
                          {item.value}
                        </span>
                      </div>

                      <span
                        className={`text-[10px] font-semibold uppercase px-2 py-0.5 rounded border ${getEntityTypeColor(
                          item.extraction_type,
                        )}`}
                      >
                        {item.extraction_type}
                      </span>
                    </div>

                    {item.evidence_span?.text_snippet && (
                      <div className="p-2 bg-gray-900/80 border border-gray-800 rounded text-[11px] text-gray-300 font-mono">
                        <span className="text-gray-500 block text-[10px] uppercase font-semibold">
                          Evidence Span
                        </span>
                        "{item.evidence_span.text_snippet}"
                      </div>
                    )}

                    <div className="flex items-center justify-between text-[11px] text-gray-400 pt-1 border-t border-gray-800/60 font-mono">
                      <span className="flex items-center space-x-1 text-emerald-400">
                        <CheckCircle2 className="w-3.5 h-3.5" />
                        <span>
                          Confidence: {formatConfidence(item.confidence)}
                        </span>
                      </span>
                      {isSelected && (
                        <span className="text-purple-400 font-semibold">
                          Selected
                        </span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
