import React, { useState, useEffect } from "react";
import { Mail, RefreshCw, ShieldCheck } from "lucide-react";
import { EmptyState } from "../components/EmptyState";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/LoadingState";
import { useChanges } from "../hooks/useWorldModel";
import { EmailDetailPage } from "./EmailDetailPage";
import { formatDate } from "../utils/formatters";

export const EmailsPage: React.FC = () => {
  const [selectedEmailId, setSelectedEmailId] = useState<string | null>(null);
  const { changes, loading, error, refetch } = useChanges();

  useEffect(() => {
    const handleDeepLink = (e: Event) => {
      const customEvent = e as CustomEvent;
      if (customEvent.detail?.tab === "emails" && customEvent.detail?.id) {
        setSelectedEmailId(customEvent.detail.id);
      }
    };
    window.addEventListener("deeplink", handleDeepLink);
    return () => window.removeEventListener("deeplink", handleDeepLink);
  }, []);

  if (selectedEmailId) {
    return (
      <EmailDetailPage
        emailId={selectedEmailId}
        onBack={() => setSelectedEmailId(null)}
      />
    );
  }

  if (loading)
    return (
      <LoadingState message="Loading Gmail observation history..." rows={3} />
    );
  if (error)
    return (
      <ErrorState
        title="Failed to load observations"
        message={error}
        onRetry={refetch}
      />
    );

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-white tracking-tight">
            Emails & Raw Observations
          </h2>
          <p className="text-xs text-gray-400 mt-1">
            Immutable raw Gmail observations ingested into DuckDB & Kuzu graph —
            click any email to inspect GPT-4.1 extraction
          </p>
        </div>

        <button
          onClick={refetch}
          className="px-3.5 py-1.5 bg-gray-900 hover:bg-gray-800 border border-gray-800 text-xs font-medium text-gray-300 rounded-lg flex items-center space-x-2 transition-colors cursor-pointer"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          <span>Refresh Lineage</span>
        </button>
      </div>

      <div className="p-4 bg-blue-950/30 border border-blue-900/40 rounded-xl flex items-center justify-between text-xs">
        <div className="flex items-center space-x-3 text-blue-300">
          <Mail className="w-5 h-5 text-blue-400 shrink-0" />
          <div>
            <p className="font-semibold">Gmail OAuth 2.0 Connector Active</p>
            <p className="text-blue-300/70 mt-0.5">
              Historical & incremental synchronization enabled.
            </p>
          </div>
        </div>

        <div className="flex items-center space-x-1.5 text-emerald-400 font-mono text-[11px] bg-emerald-950/60 border border-emerald-800/60 px-2.5 py-1 rounded-full">
          <ShieldCheck className="w-3.5 h-3.5" />
          <span>Privacy Protected (No Raw Storage Leak)</span>
        </div>
      </div>

      {changes.length === 0 ? (
        <EmptyState
          title="No ingested emails"
          description="Sync your Gmail connector or run the automated pipeline demo to ingest emails."
        />
      ) : (
        <div className="bg-gray-900/40 border border-gray-800 rounded-xl overflow-hidden">
          <div className="px-5 py-3 border-b border-gray-800 bg-gray-950 flex items-center justify-between text-xs font-semibold text-gray-400 uppercase tracking-wider">
            <span>Observation / Message ID</span>
            <span>Reconciliation Outcome</span>
            <span>Timestamp</span>
          </div>

          <div className="divide-y divide-gray-800/60">
            {changes.map((c) => (
              <div
                key={c.id}
                onClick={() => setSelectedEmailId(c.observation_id)}
                className="p-4 flex items-center justify-between hover:bg-gray-900/80 transition-colors text-xs cursor-pointer group"
              >
                <div className="space-y-1">
                  <div className="flex items-center space-x-2">
                    <Mail className="w-4 h-4 text-blue-400 shrink-0 group-hover:scale-110 transition-transform" />
                    <span className="font-semibold text-gray-200 font-mono group-hover:text-blue-400 transition-colors">
                      {c.observation_id}
                    </span>
                  </div>
                  <p className="text-gray-400 text-[11px] pl-6">
                    {c.description}
                  </p>
                </div>

                <div className="flex items-center space-x-6">
                  <span className="px-2 py-0.5 bg-gray-800 border border-gray-700 text-gray-300 rounded font-mono text-[10px]">
                    {c.outcome}
                  </span>
                  <span className="text-gray-500 font-mono text-[11px]">
                    {formatDate(c.timestamp)}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
