import React, { useEffect, useState } from "react";
import { Activity, BrainCircuit, CheckCircle2, XCircle } from "lucide-react";
import {
  extractionApi,
  type ExtractionMetrics,
  type ExtractionSample,
} from "../api/extraction";
import { LoadingState } from "../components/LoadingState";
import { ErrorState } from "../components/ErrorState";
import { formatConfidence } from "../utils/formatters";

export const ExtractionQualityPage: React.FC = () => {
  const [metrics, setMetrics] = useState<ExtractionMetrics | null>(null);
  const [samples, setSamples] = useState<ExtractionSample[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [metricsRes, samplesRes] = await Promise.all([
        extractionApi.getMetrics(),
        extractionApi.getSamples(),
      ]);
      setMetrics(metricsRes);
      setSamples(samplesRes);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to fetch extraction data.",
      );
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void fetchData();
  }, []);

  const toggleReviewStatus = (id: string, isCorrect: boolean) => {
    setSamples((prev) =>
      prev.map((s) =>
        s.id === id
          ? { ...s, review_status: isCorrect ? "correct" : "incorrect" }
          : s,
      ),
    );
    // In a real app, this would POST to the backend
  };

  if (loading)
    return <LoadingState message="Loading extraction telemetry..." rows={4} />;
  if (error || !metrics)
    return (
      <ErrorState
        title="Telemetry Failed"
        message={error || "No data"}
        onRetry={fetchData}
      />
    );

  const MetricCard = ({
    title,
    value,
    type = "observed",
  }: {
    title: string;
    value: string | number;
    type?: "observed" | "estimated" | "reviewed";
  }) => {
    const isEstimated = type === "estimated";
    return (
      <div
        className={`p-4 rounded-xl border ${isEstimated ? "bg-gray-900/40 border-gray-800/60 border-dashed" : "bg-gray-900/80 border-gray-800"} flex flex-col space-y-1`}
      >
        <div className="flex justify-between items-start">
          <span className="text-[10px] uppercase font-bold text-gray-500 tracking-wider">
            {title}
          </span>
          {isEstimated && (
            <span className="text-[9px] text-gray-600 bg-gray-900 px-1 rounded border border-gray-800">
              EST
            </span>
          )}
        </div>
        <span
          className={`text-2xl font-mono font-bold ${isEstimated ? "text-gray-400" : "text-white"}`}
        >
          {value}
        </span>
      </div>
    );
  };

  return (
    <div className="flex flex-col space-y-6 h-full overflow-y-auto pr-2 pb-10">
      {/* Header */}
      <div>
        <h2 className="text-xl font-bold text-white tracking-tight flex items-center space-x-2">
          <BrainCircuit className="w-5 h-5 text-blue-400" />
          <span>Extraction Quality & Telemetry</span>
        </h2>
        <p className="text-xs text-gray-400 mt-1">
          Internal developer view for monitoring GPT-4.1 pipeline health and
          extraction accuracy.
        </p>
      </div>

      {/* Metrics Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-4">
        <MetricCard title="Emails Processed" value={metrics.emails_processed} />
        <MetricCard
          title="Entities Extracted"
          value={metrics.entities_extracted}
        />
        <MetricCard
          title="Rels Extracted"
          value={metrics.relationships_extracted}
        />
        <MetricCard title="Claims Extracted" value={metrics.claims_extracted} />
        <MetricCard title="Events Extracted" value={metrics.events_extracted} />

        <MetricCard
          title="Pending Review"
          value={metrics.pending_confirmations}
        />
        <MetricCard
          title="Conflicting Rels"
          value={metrics.conflicting_relationships}
        />
        <MetricCard
          title="Low Confidence"
          value={metrics.low_confidence_extractions}
        />

        <MetricCard
          title="Failed Extractions"
          value={metrics.extraction_failures}
          type="estimated"
        />
        <MetricCard
          title="Unresolved Entities"
          value={metrics.unresolved_entities}
          type="estimated"
        />
      </div>

      {/* Samples Table */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden mt-6">
        <div className="p-4 border-b border-gray-800 flex justify-between items-center bg-gray-950/40">
          <h3 className="text-sm font-bold text-white flex items-center space-x-2">
            <Activity className="w-4 h-4 text-emerald-400" />
            <span>Sample Extraction Records</span>
          </h3>
          <span className="text-xs text-gray-500 font-mono">
            Showing latest {samples.length}
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-gray-900/60 text-gray-400 border-b border-gray-800 font-mono text-[10px] uppercase">
              <tr>
                <th className="px-4 py-3 font-semibold">
                  Evidence Span (Email Snippet)
                </th>
                <th className="px-4 py-3 font-semibold">
                  Extraction (Subj → Pred → Obj)
                </th>
                <th className="px-4 py-3 font-semibold w-24">Conf</th>
                <th className="px-4 py-3 font-semibold">Final WM State</th>
                <th className="px-4 py-3 font-semibold text-center w-32">
                  Manual Review
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800/60">
              {samples.map((sample) => (
                <tr
                  key={sample.id}
                  className="hover:bg-gray-800/30 transition-colors"
                >
                  <td className="px-4 py-3">
                    <p className="text-gray-300 line-clamp-2 leading-relaxed italic border-l-2 border-gray-700 pl-2">
                      "{sample.email_snippet}"
                    </p>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center space-x-1.5 flex-wrap gap-y-1">
                      <span className="text-blue-400 font-semibold">
                        {sample.extraction_subject}
                      </span>
                      <span className="bg-purple-950/40 border border-purple-800/40 text-purple-300 px-1.5 py-0.5 rounded text-[9px] uppercase tracking-wide">
                        {sample.extraction_predicate}
                      </span>
                      <span className="text-emerald-400 font-semibold">
                        {sample.extraction_object}
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`font-mono font-bold ${sample.confidence < 0.7 ? "text-amber-400" : "text-emerald-400"}`}
                    >
                      {formatConfidence(sample.confidence)}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-gray-400 uppercase text-[10px] tracking-wider font-semibold border border-gray-700 px-2 py-0.5 rounded">
                      {sample.final_wm_status}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    {sample.review_status === "pending" ? (
                      <div className="flex items-center justify-center space-x-2">
                        <button
                          onClick={() => toggleReviewStatus(sample.id, true)}
                          className="p-1.5 bg-gray-800 text-gray-400 hover:text-emerald-400 hover:bg-emerald-950/30 rounded-lg transition-colors border border-transparent hover:border-emerald-800/50"
                          title="Mark Correct"
                        >
                          <CheckCircle2 className="w-4 h-4" />
                        </button>
                        <button
                          onClick={() => toggleReviewStatus(sample.id, false)}
                          className="p-1.5 bg-gray-800 text-gray-400 hover:text-red-400 hover:bg-red-950/30 rounded-lg transition-colors border border-transparent hover:border-red-800/50"
                          title="Mark Incorrect"
                        >
                          <XCircle className="w-4 h-4" />
                        </button>
                      </div>
                    ) : (
                      <div className="flex items-center justify-center">
                        {sample.review_status === "correct" ? (
                          <span className="text-emerald-500 font-semibold text-[10px] flex items-center space-x-1 uppercase">
                            <CheckCircle2 className="w-3.5 h-3.5" />
                            <span>Correct</span>
                          </span>
                        ) : (
                          <span className="text-red-500 font-semibold text-[10px] flex items-center space-x-1 uppercase">
                            <XCircle className="w-3.5 h-3.5" />
                            <span>Incorrect</span>
                          </span>
                        )}
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {samples.length === 0 && (
            <div className="p-8 text-center text-gray-500 text-xs">
              No sample records available.
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
