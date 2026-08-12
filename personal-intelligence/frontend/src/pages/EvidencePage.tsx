import { Search, ShieldAlert, ShieldCheck } from "lucide-react";
import React, { useEffect, useState } from "react";
import { worldApi } from "../api";
import { EmptyState } from "../components/EmptyState";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/LoadingState";
import { RelationshipInspector } from "../components/relationship/RelationshipInspector";
import type { UIRelationship } from "../types";
import { formatConfidence } from "../utils/formatters";

export const EvidencePage: React.FC = () => {
  const [relationships, setRelationships] = useState<UIRelationship[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selectedRel, setSelectedRel] = useState<UIRelationship | null>(null);
  const [searchQuery, setSearchQuery] = useState("");

  useEffect(() => {
    let mounted = true;
    const fetchRels = async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await worldApi.getUIRelationships(1, 100);
        if (mounted) {
          setRelationships(res.items);
          // Auto-select first item if available
          if (res.items.length > 0) {
            setSelectedRel(res.items[0]);
          }
        }
      } catch (err) {
        if (mounted)
          setError(
            err instanceof Error ? err.message : "Failed to load claims.",
          );
      } finally {
        if (mounted) setLoading(false);
      }
    };
    void fetchRels();
    return () => {
      mounted = false;
    };
  }, []);

  if (loading)
    return <LoadingState message="Loading Evidence Explorer..." rows={3} />;
  if (error)
    return (
      <ErrorState
        title="Failed to load claims"
        message={error}
        onRetry={() => window.location.reload()}
      />
    );

  const filteredRels = relationships.filter((r) => {
    if (!searchQuery) return true;
    const q = searchQuery.toLowerCase();
    return (
      r.subject_name.toLowerCase().includes(q) ||
      r.object_name.toLowerCase().includes(q) ||
      r.predicate.toLowerCase().includes(q)
    );
  });

  return (
    <div className="h-[calc(100vh-8rem)] flex flex-col space-y-4">
      <div className="shrink-0">
        <h2 className="text-xl font-bold text-white tracking-tight">
          Evidence Explorer
        </h2>
        <p className="text-xs text-gray-400 mt-1">
          Inspect the complete provenance chain for every World Model claim:
          from logical assertion back to raw Gmail text spans.
        </p>
      </div>

      <div className="flex-1 flex space-x-4 min-h-0">
        {/* LEFT COLUMN: Claims Master List */}
        <div className="w-1/3 min-w-[320px] bg-gray-900 border border-gray-800 rounded-2xl flex flex-col overflow-hidden shrink-0">
          <div className="p-4 border-b border-gray-800 bg-gray-900/50 shrink-0">
            <div className="relative">
              <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
              <input
                type="text"
                placeholder="Search claims..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full bg-gray-950 border border-gray-800 rounded-lg pl-9 pr-3 py-2 text-xs text-white focus:outline-none focus:border-blue-500 transition-colors"
              />
            </div>
          </div>

          <div className="flex-1 overflow-y-auto p-2 space-y-1">
            {filteredRels.length === 0 ? (
              <div className="p-6 text-center text-gray-500 text-xs">
                No claims found.
              </div>
            ) : (
              filteredRels.map((rel) => {
                const isSelected = selectedRel?.id === rel.id;
                const isConfirmed =
                  rel.confidence >= 0.85 && rel.status === "active";
                const hasContradiction = rel.confidence < 0.7;

                return (
                  <button
                    key={rel.id}
                    onClick={() => setSelectedRel(rel)}
                    className={`w-full text-left p-3 rounded-xl border transition-all cursor-pointer ${
                      isSelected
                        ? "bg-gray-800 border-gray-600 shadow-md"
                        : "bg-transparent border-transparent hover:bg-gray-900/80 hover:border-gray-800"
                    }`}
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex items-center space-x-2">
                        {isConfirmed ? (
                          <ShieldCheck className="w-3.5 h-3.5 text-emerald-500 shrink-0" />
                        ) : hasContradiction ? (
                          <ShieldAlert className="w-3.5 h-3.5 text-amber-500 shrink-0" />
                        ) : (
                          <ShieldCheck className="w-3.5 h-3.5 text-blue-500 shrink-0" />
                        )}
                        <span className="text-[11px] font-bold text-gray-200 truncate">
                          {rel.subject_name}
                        </span>
                      </div>
                      <span
                        className={`text-[10px] font-mono font-bold ${hasContradiction ? "text-amber-500" : "text-emerald-500"}`}
                      >
                        {formatConfidence(rel.confidence)}
                      </span>
                    </div>

                    <div className="mt-1.5 pl-5.5 flex items-center space-x-1.5 opacity-80">
                      <span className="text-[9px] uppercase tracking-wider text-purple-400 bg-purple-950/40 border border-purple-800/40 px-1.5 py-0.5 rounded">
                        {rel.predicate}
                      </span>
                      <span className="text-[10px] text-gray-400 truncate">
                        {rel.object_name}
                      </span>
                    </div>
                  </button>
                );
              })
            )}
          </div>
        </div>

        {/* RIGHT COLUMN: Detail Panel */}
        <div className="flex-1 bg-gray-900 border border-gray-800 rounded-2xl overflow-y-auto">
          {selectedRel ? (
            <div className="h-full">
              <RelationshipInspector
                relationshipId={selectedRel.id}
                onOpenSubject={(id) => console.log("Navigate to entity", id)}
                onOpenObject={(id) => console.log("Navigate to entity", id)}
                onViewEvidence={(id) => console.log("Navigate to email", id)}
              />
            </div>
          ) : (
            <div className="h-full flex items-center justify-center">
              <EmptyState
                title="No Claim Selected"
                description="Select a claim from the list to explore its evidence lineage."
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
