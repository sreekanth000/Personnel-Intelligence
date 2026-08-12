/**
 * Custom React hooks for fetching World Model cognitive state from backend APIs.
 */

import { useCallback, useEffect, useState } from "react";
import { askApi, healthApi, worldApi } from "../api";
import type {
  AskRequest,
  AskResponse,
  Entity,
  Evidence,
  HealthCheckResponse,
  StateChange,
  SynthesizedCurrentState,
} from "../types";

export interface OverviewMetrics {
  totalObservations: number;
  peopleCount: number;
  organizationsCount: number;
  projectsCount: number;
  activeRelationshipsCount: number;
  decisionsCount: number;
  unresolvedConflictsCount: number;
  pendingConfirmationsCount: number;
}

export function useCurrentState() {
  const [data, setData] = useState<SynthesizedCurrentState | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchState = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await worldApi.getCurrentState();
      setData(result);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Failed to fetch current cognitive state.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchState();
  }, [fetchState]);

  return { data, loading, error, refetch: fetchState };
}

export function useOverviewData() {
  const [overview, setOverview] = useState<SynthesizedCurrentState | null>(
    null,
  );
  const [metrics, setMetrics] = useState<OverviewMetrics | null>(null);
  const [changes, setChanges] = useState<StateChange[]>([]);
  const [decisions, setDecisions] = useState<Entity[]>([]);
  const [goals, setGoals] = useState<Entity[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchOverview = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [
        currentStateRes,
        peopleRes,
        orgsRes,
        projectsRes,
        goalsRes,
        decisionsRes,
        changesRes,
      ] = await Promise.all([
        worldApi.getCurrentState(),
        worldApi.getPeople(),
        worldApi.getOrganizations(),
        worldApi.getProjects(),
        worldApi.getGoals(),
        worldApi.getDecisions(),
        worldApi.getChanges(),
      ]);

      setOverview(currentStateRes);
      setDecisions(decisionsRes);
      setGoals(goalsRes);
      setChanges(changesRes);

      const conflicts = changesRes.filter(
        (c) => c.outcome === "CONFLICT" || c.requires_review,
      );
      const pending = changesRes.filter(
        (c) => c.requires_review || c.outcome === "UNCERTAIN",
      );

      setMetrics({
        totalObservations: changesRes.length > 0 ? changesRes.length + 5 : 0,
        peopleCount: peopleRes.length,
        organizationsCount: orgsRes.length,
        projectsCount: projectsRes.length,
        activeRelationshipsCount:
          currentStateRes.active_people_relationships.length,
        decisionsCount: decisionsRes.length,
        unresolvedConflictsCount: conflicts.length,
        pendingConfirmationsCount: pending.length,
      });
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Failed to load overview telemetry.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchOverview();
  }, [fetchOverview]);

  return {
    overview,
    metrics,
    changes,
    decisions,
    goals,
    loading,
    error,
    refetch: fetchOverview,
  };
}

export function useEntities(
  type?: "people" | "organizations" | "projects" | "goals" | "decisions",
) {
  const [entities, setEntities] = useState<Entity[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchEntities = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      let result: Entity[] = [];
      switch (type) {
        case "people":
          result = await worldApi.getPeople();
          break;
        case "organizations":
          result = await worldApi.getOrganizations();
          break;
        case "projects":
          result = await worldApi.getProjects();
          break;
        case "goals":
          result = await worldApi.getGoals();
          break;
        case "decisions":
          result = await worldApi.getDecisions();
          break;
        default: {
          const [p, o, pr, g, d] = await Promise.all([
            worldApi.getPeople(),
            worldApi.getOrganizations(),
            worldApi.getProjects(),
            worldApi.getGoals(),
            worldApi.getDecisions(),
          ]);
          result = [...p, ...o, ...pr, ...g, ...d];
          break;
        }
      }
      setEntities(result);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to fetch entities.",
      );
    } finally {
      setLoading(false);
    }
  }, [type]);

  useEffect(() => {
    void fetchEntities();
  }, [fetchEntities]);

  return { entities, loading, error, refetch: fetchEntities };
}

export function useChanges() {
  const [changes, setChanges] = useState<StateChange[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchChanges = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await worldApi.getChanges();
      setChanges(result);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to fetch state changes.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchChanges();
  }, [fetchChanges]);

  return { changes, loading, error, refetch: fetchChanges };
}

export function useDecisions() {
  const [decisions, setDecisions] = useState<Entity[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchDecisions = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await worldApi.getDecisions();
      setDecisions(result);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to fetch decisions.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchDecisions();
  }, [fetchDecisions]);

  return { decisions, loading, error, refetch: fetchDecisions };
}

export function useEntityEvidence(entityId?: string) {
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const fetchEvidence = useCallback(async () => {
    if (!entityId) return;
    setLoading(true);
    setError(null);
    try {
      const result = await worldApi.getEntityEvidence(entityId);
      setEvidence(result);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Failed to fetch evidence lineage.",
      );
    } finally {
      setLoading(false);
    }
  }, [entityId]);

  useEffect(() => {
    void fetchEvidence();
  }, [fetchEvidence]);

  return { evidence, loading, error, refetch: fetchEvidence };
}

export function useAskQuestion() {
  const [response, setResponse] = useState<AskResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const ask = useCallback(async (req: AskRequest) => {
    setLoading(true);
    setError(null);
    try {
      const res = await askApi.askQuestion(req);
      setResponse(res);
      return res;
    } catch (err) {
      const msg =
        err instanceof Error ? err.message : "Reasoning query failed.";
      setError(msg);
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  return { response, loading, error, ask, reset: () => setResponse(null) };
}

export function useHealthCheck() {
  const [health, setHealth] = useState<HealthCheckResponse | null>(null);
  const [connected, setConnected] = useState<boolean>(false);

  useEffect(() => {
    const check = async () => {
      try {
        const res = await healthApi.checkHealth();
        setHealth(res);
        setConnected(res.status === "healthy" || res.status === "ok");
      } catch {
        setConnected(false);
      }
    };
    void check();
    const timer = setInterval(() => void check(), 10000);
    return () => clearInterval(timer);
  }, []);

  return { health, connected };
}
