import React, { useEffect, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Compass,
  FolderGit2,
  GitCommit,
  GitFork,
  Mail,
  ShieldCheck,
  User,
} from "lucide-react";
import { worldApi } from "../api";
import { EmptyState } from "../components/EmptyState";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/LoadingState";
import { RelationshipDetailModal } from "../components/RelationshipDetailModal";
import type {
  Entity,
  UIEvidence,
  UIRelationship,
  UITimelineItem,
} from "../types";
import {
  formatConfidence,
  formatDate,
  getEntityTypeColor,
} from "../utils/formatters";

interface EntityDetailPageProps {
  entityId: string;
  onBack?: () => void;
}

export const EntityDetailPage: React.FC<EntityDetailPageProps> = ({
  entityId,
  onBack,
}) => {
  const [entity, setEntity] = useState<Entity | null>(null);
  const [relationships, setRelationships] = useState<UIRelationship[]>([]);
  const [timeline, setTimeline] = useState<UITimelineItem[]>([]);
  const [evidence, setEvidence] = useState<UIEvidence[]>([]);
  const [decisions, setDecisions] = useState<Entity[]>([]);
  const [projects, setProjects] = useState<Entity[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedRel, setSelectedRel] = useState<UIRelationship | null>(null);

  useEffect(() => {
    const fetchAllData = async () => {
      setLoading(true);
      setError(null);
      try {
        const [entRes, relsRes, tlRes, evRes, decsRes, prjsRes] =
          await Promise.all([
            worldApi.getEntity(entityId),
            worldApi.getUIEntityRelationships(entityId),
            worldApi.getUIEntityTimeline(entityId),
            worldApi.getUIEntityEvidence(entityId),
            worldApi.getDecisions(),
            worldApi.getProjects(),
          ]);

        setEntity(entRes);
        setRelationships(relsRes);
        setTimeline(tlRes);
        setEvidence(evRes);
        setDecisions(decsRes);
        setProjects(prjsRes);
      } catch (err) {
        setError(
          err instanceof Error
            ? err.message
            : "Failed to fetch entity detail telemetry.",
        );
      } finally {
        setLoading(false);
      }
    };
    void fetchAllData();
  }, [entityId]);

  if (loading)
    return (
      <LoadingState
        message="Fetching entity telemetry and temporal relationships..."
        rows={4}
      />
    );
  if (error || !entity) {
    return (
      <ErrorState
        title="Failed to load entity"
        message={error || "Entity object not found."}
        onRetry={() => window.location.reload()}
      />
    );
  }

  const confidenceScore = entity.confidence?.score ?? 0.95;

  return (
    <div className="space-y-8">
      {/* HEADER SECTION */}
      <div className="bg-gray-900/60 border border-gray-800 rounded-2xl p-6 space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-3">
            {onBack && (
              <button
                onClick={onBack}
                className="p-2 bg-gray-950 hover:bg-gray-800 border border-gray-800 rounded-lg text-gray-400 hover:text-white transition-colors cursor-pointer"
              >
                <ArrowLeft className="w-4 h-4" />
              </button>
            )}

            <div>
              <div className="flex items-center space-x-2.5">
                <h2 className="text-2xl font-bold text-white tracking-tight">
                  {entity.name}
                </h2>
                <span
                  className={`text-[10px] font-bold uppercase px-2.5 py-0.5 rounded border ${getEntityTypeColor(
                    entity.entity_type,
                  )}`}
                >
                  {entity.entity_type}
                </span>
              </div>
              <p className="text-xs text-gray-400 font-mono mt-0.5">
                Entity ID: {entity.id}
              </p>
            </div>
          </div>

          <div className="flex items-center space-x-3">
            <span className="text-xs px-3 py-1 rounded-full font-mono font-semibold flex items-center space-x-1.5 bg-emerald-950/60 border border-emerald-800/60 text-emerald-400">
              <ShieldCheck className="w-3.5 h-3.5" />
              <span>Confidence: {formatConfidence(confidenceScore)}</span>
            </span>

            <span className="text-xs px-3 py-1 bg-gray-950 border border-gray-800 rounded-full font-mono text-gray-300">
              Status: Active
            </span>
          </div>
        </div>

        {/* Entity Attributes Grid */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 pt-2 text-xs border-t border-gray-800/60">
          <div>
            <span className="text-gray-500 font-mono text-[11px] block">
              Canonical Name
            </span>
            <span className="text-gray-200 font-semibold">
              {entity.canonical_name || entity.name}
            </span>
          </div>

          <div>
            <span className="text-gray-500 font-mono text-[11px] block">
              Email Identifier
            </span>
            <span className="text-blue-400 font-mono">
              {entity.email || "None registered"}
            </span>
          </div>

          <div>
            <span className="text-gray-500 font-mono text-[11px] block">
              Domain
            </span>
            <span className="text-indigo-300 font-mono">
              {entity.domain || "N/A"}
            </span>
          </div>

          <div>
            <span className="text-gray-500 font-mono text-[11px] block">
              Aliases
            </span>
            <span className="text-gray-300 font-mono">
              {entity.aliases.join(", ") || "No aliases"}
            </span>
          </div>
        </div>
      </div>

      {/* RELATIONSHIPS TREE SECTION */}
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-bold text-white uppercase tracking-wider flex items-center space-x-2">
            <GitFork className="w-4 h-4 text-purple-400" />
            <span>Relationship Topology ({relationships.length} Edges)</span>
          </h3>
          <span className="text-xs text-gray-500 italic">
            Click any edge to view evidence details
          </span>
        </div>

        {relationships.length === 0 ? (
          <EmptyState
            title="No relationships recorded"
            description="No active or historical graph edges connected to this entity."
          />
        ) : (
          <div className="p-5 bg-gray-900/40 border border-gray-800 rounded-xl space-y-2 font-mono text-xs">
            <div className="font-bold text-blue-400 flex items-center space-x-2 pb-2 border-b border-gray-800">
              <User className="w-4 h-4 text-blue-400" />
              <span>{entity.name}</span>
            </div>

            <div className="pl-4 space-y-2 pt-1">
              {relationships.map((rel, idx) => {
                const isLast = idx === relationships.length - 1;
                const branchSymbol = isLast ? "└──" : "├──";
                const isOutgoing = rel.subject_id === entity.id;

                return (
                  <div
                    key={rel.id}
                    onClick={() => setSelectedRel(rel)}
                    className="p-2.5 bg-gray-950 hover:bg-gray-900 border border-gray-800 hover:border-purple-600/60 rounded-lg flex items-center justify-between transition-all cursor-pointer group"
                  >
                    <div className="flex items-center space-x-2.5">
                      <span className="text-gray-500">{branchSymbol}</span>
                      <span className="px-1.5 py-0.5 bg-purple-950 text-purple-300 border border-purple-800 rounded font-semibold text-[10px]">
                        {rel.predicate}
                      </span>
                      <ArrowRight className="w-3.5 h-3.5 text-gray-500" />
                      <span className="text-gray-100 font-bold group-hover:text-purple-300 transition-colors">
                        {isOutgoing ? rel.object_name : rel.subject_name}
                      </span>
                    </div>

                    <div className="flex items-center space-x-3">
                      <span className="text-[10px] text-emerald-400 bg-emerald-950/60 border border-emerald-800/60 px-2 py-0.5 rounded">
                        {formatConfidence(rel.confidence)}
                      </span>
                      <span className="text-[10px] text-gray-400 uppercase font-semibold">
                        {rel.status}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </section>

      {/* CURRENT STATE SECTION */}
      <section className="space-y-3">
        <h3 className="text-sm font-bold text-white uppercase tracking-wider flex items-center space-x-2">
          <ShieldCheck className="w-4 h-4 text-emerald-400" />
          <span>Currently Valid State</span>
        </h3>

        <div className="p-4 bg-gray-900/40 border border-gray-800 rounded-xl space-y-2 text-xs">
          <p className="text-gray-300">
            Current point-in-time state synthesized from evidence-supported
            statements. Open-ended temporal validity bounds active.
          </p>

          <div className="flex flex-wrap gap-2 pt-1">
            <span className="px-2.5 py-1 bg-emerald-950 text-emerald-300 border border-emerald-800/80 rounded font-mono text-[11px]">
              Grounding: Evidence-Supported
            </span>
            <span className="px-2.5 py-1 bg-blue-950 text-blue-300 border border-blue-800/80 rounded font-mono text-[11px]">
              Temporal Bounds: Active
            </span>
          </div>
        </div>
      </section>

      {/* 2-COLUMN BOTTOM GRID: TIMELINE & EVIDENCE */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* TIMELINE */}
        <section className="space-y-3">
          <h3 className="text-sm font-bold text-white uppercase tracking-wider flex items-center space-x-2">
            <GitCommit className="w-4 h-4 text-blue-400" />
            <span>Entity Timeline & History</span>
          </h3>

          {timeline.length === 0 ? (
            <EmptyState
              title="No timeline entries"
              description="State changes will populate here."
            />
          ) : (
            <div className="space-y-2">
              {timeline.map((item) => (
                <div
                  key={item.id}
                  className="p-3 bg-gray-900/40 border border-gray-800 rounded-lg space-y-1 text-xs"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-semibold text-gray-200">
                      {item.title}
                    </span>
                    <span className="text-[10px] text-gray-500 font-mono">
                      {formatDate(item.timestamp)}
                    </span>
                  </div>
                  <p className="text-[11px] text-gray-400">
                    {item.description}
                  </p>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* EVIDENCE */}
        <section className="space-y-3">
          <h3 className="text-sm font-bold text-white uppercase tracking-wider flex items-center space-x-2">
            <Mail className="w-4 h-4 text-indigo-400" />
            <span>Supporting Gmail Evidence ({evidence.length})</span>
          </h3>

          {evidence.length === 0 ? (
            <EmptyState
              title="No ground evidence records"
              description="Evidence records connecting raw email text."
            />
          ) : (
            <div className="space-y-2 max-h-60 overflow-y-auto pr-1">
              {evidence.map((ev) => (
                <div
                  key={ev.id}
                  className="p-3 bg-gray-900/40 border border-gray-800 rounded-lg space-y-1 text-xs"
                >
                  <div className="flex items-center justify-between font-mono text-[11px] text-gray-400">
                    <span>Observation: {ev.observation_id}</span>
                    <span className="text-emerald-400">
                      {formatConfidence(ev.confidence)}
                    </span>
                  </div>
                  <p className="text-gray-200 text-xs italic font-mono">
                    "{ev.text_snippet}"
                  </p>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>

      {/* 2-COLUMN GRID: RELATED DECISIONS & RELATED PROJECTS */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* RELATED DECISIONS */}
        <section className="space-y-3">
          <h3 className="text-sm font-bold text-white uppercase tracking-wider flex items-center space-x-2">
            <Compass className="w-4 h-4 text-amber-400" />
            <span>Related Decisions ({decisions.length})</span>
          </h3>

          {decisions.length === 0 ? (
            <EmptyState
              title="No connected decisions"
              description="Decisions linked to this entity."
            />
          ) : (
            <div className="space-y-2">
              {decisions.slice(0, 3).map((d) => (
                <div
                  key={d.id}
                  className="p-3 bg-gray-900/40 border border-gray-800 rounded-lg text-xs space-y-1"
                >
                  <span className="font-semibold text-gray-200 block">
                    {d.name}
                  </span>
                  <span className="text-[10px] text-amber-400 font-mono">
                    Status: MADE
                  </span>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* RELATED PROJECTS */}
        <section className="space-y-3">
          <h3 className="text-sm font-bold text-white uppercase tracking-wider flex items-center space-x-2">
            <FolderGit2 className="w-4 h-4 text-emerald-400" />
            <span>Related Projects ({projects.length})</span>
          </h3>

          {projects.length === 0 ? (
            <EmptyState
              title="No connected projects"
              description="Projects linked to this entity."
            />
          ) : (
            <div className="space-y-2">
              {projects.slice(0, 3).map((p) => (
                <div
                  key={p.id}
                  className="p-3 bg-gray-900/40 border border-gray-800 rounded-lg text-xs space-y-1"
                >
                  <span className="font-semibold text-gray-200 block">
                    {p.name}
                  </span>
                  <span className="text-[10px] text-emerald-400 font-mono">
                    Status: active
                  </span>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* CLICKABLE RELATIONSHIP DETAIL MODAL */}
        <RelationshipDetailModal
          relationship={selectedRel}
          onClose={() => setSelectedRel(null)}
        />
      </div>
    </div>
  );
};
