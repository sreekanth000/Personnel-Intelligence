import React, { useState, useEffect } from "react";
import { EmptyState } from "../components/EmptyState";
import { EntityCard } from "../components/EntityCard";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/LoadingState";
import { useEntities } from "../hooks/useWorldModel";
import { EntityDetailPage } from "./EntityDetailPage";

type EntityFilter =
  "all" | "people" | "organizations" | "projects" | "goals" | "decisions";

export const EntitiesPage: React.FC = () => {
  const [selectedEntityId, setSelectedEntityId] = useState<string | null>(null);
  const [activeFilter, setActiveFilter] = useState<EntityFilter>("all");
  const queryType = activeFilter === "all" ? undefined : activeFilter;
  const { entities, loading, error, refetch } = useEntities(queryType);

  useEffect(() => {
    const handleDeepLink = (e: Event) => {
      const customEvent = e as CustomEvent;
      if (customEvent.detail?.tab === "entities" && customEvent.detail?.id) {
        setSelectedEntityId(customEvent.detail.id);
      }
    };
    window.addEventListener("deeplink", handleDeepLink);
    return () => window.removeEventListener("deeplink", handleDeepLink);
  }, []);

  if (selectedEntityId) {
    return (
      <EntityDetailPage
        entityId={selectedEntityId}
        onBack={() => setSelectedEntityId(null)}
      />
    );
  }

  const filters: { id: EntityFilter; label: string }[] = [
    { id: "all", label: "All Entities" },
    { id: "people", label: "People" },
    { id: "organizations", label: "Organizations" },
    { id: "projects", label: "Projects" },
    { id: "goals", label: "Goals" },
    { id: "decisions", label: "Decisions" },
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-white tracking-tight">
            Entities & Knowledge Objects
          </h2>
          <p className="text-xs text-gray-400 mt-1">
            Resolved entities extracted from personal observations — click any
            card to inspect relationship topology & timeline
          </p>
        </div>

        <div className="flex flex-wrap gap-1.5 p-1 bg-gray-900 border border-gray-800 rounded-xl">
          {filters.map((f) => (
            <button
              key={f.id}
              onClick={() => setActiveFilter(f.id)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer ${
                activeFilter === f.id
                  ? "bg-blue-600 text-white shadow-sm"
                  : "text-gray-400 hover:text-gray-200 hover:bg-gray-800/60"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {loading && (
        <LoadingState message="Fetching resolved entities..." rows={3} />
      )}
      {error && (
        <ErrorState
          title="Failed to load entities"
          message={error}
          onRetry={refetch}
        />
      )}

      {!loading && !error && (
        <>
          {entities.length === 0 ? (
            <EmptyState
              title={`No ${activeFilter} entities found`}
              description="Ingest emails or execute the pipeline to resolve personal entities."
            />
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {entities.map((entity) => (
                <div
                  key={entity.id}
                  onClick={() => setSelectedEntityId(entity.id)}
                  className="cursor-pointer transition-transform hover:-translate-y-0.5"
                >
                  <EntityCard entity={entity} />
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
};
