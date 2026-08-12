/**
 * Typed API client for World Model Query APIs (/world/*).
 */

import { request } from "./client";
import type {
  Entity,
  Evidence,
  Relationship,
  StateChange,
  SynthesizedCurrentState,
  UIEmailDetail,
  UIEvidence,
  UIGraphDTO,
  UIRelationship,
  UITimelineItem,
} from "../types";

export const worldApi = {
  getEntity: (id: string): Promise<Entity> =>
    request<Entity>(`/world/entities/${encodeURIComponent(id)}`),

  getEntityRelationships: (id: string): Promise<Relationship[]> =>
    request<Relationship[]>(
      `/world/entities/${encodeURIComponent(id)}/relationships`,
    ),

  getEntityTimeline: (id: string): Promise<Record<string, unknown>[]> =>
    request<Record<string, unknown>[]>(
      `/world/entities/${encodeURIComponent(id)}/timeline`,
    ),

  getEntityEvidence: (id: string): Promise<Evidence[]> =>
    request<Evidence[]>(`/world/entities/${encodeURIComponent(id)}/evidence`),

  getPeople: (): Promise<Entity[]> => request<Entity[]>("/world/people"),

  getOrganizations: (): Promise<Entity[]> =>
    request<Entity[]>("/world/organizations"),

  getProjects: (): Promise<Entity[]> => request<Entity[]>("/world/projects"),

  getGoals: (): Promise<Entity[]> => request<Entity[]>("/world/goals"),

  getDecisions: (): Promise<Entity[]> => request<Entity[]>("/world/decisions"),

  getUIRelationships: (
    page = 1,
    limit = 20,
  ): Promise<{ items: UIRelationship[]; total: number; has_more: boolean }> =>
    request<{ items: UIRelationship[]; total: number; has_more: boolean }>(
      `/api/v1/ui/relationships?page=${page}&limit=${limit}`,
    ),

  getUIRelationship: (id: string): Promise<UIRelationship> =>
    request<UIRelationship>(
      `/api/v1/ui/relationships/${encodeURIComponent(id)}`,
    ),

  getUIRelationshipTimeline: (id: string): Promise<UITimelineItem[]> =>
    request<UITimelineItem[]>(
      `/api/v1/ui/relationships/${encodeURIComponent(id)}/timeline`,
    ),

  getUIEntityRelationships: (id: string): Promise<UIRelationship[]> =>
    request<UIRelationship[]>(
      `/api/v1/ui/entities/${encodeURIComponent(id)}/relationships`,
    ),

  getUIEntityTimeline: (id: string): Promise<UITimelineItem[]> =>
    request<UITimelineItem[]>(
      `/api/v1/ui/entities/${encodeURIComponent(id)}/timeline`,
    ),

  getUIEvidence: (
    id: string,
    page = 1,
    limit = 20,
  ): Promise<{ items: UIEvidence[]; total: number; has_more: boolean }> =>
    request<{ items: UIEvidence[]; total: number; has_more: boolean }>(
      `/api/v1/ui/evidence/${encodeURIComponent(id)}?page=${page}&limit=${limit}`,
    ),

  getUIEntityEvidence: (
    id: string,
    page = 1,
    limit = 20,
  ): Promise<UIEvidence[]> =>
    request<{ items: UIEvidence[] }>(
      `/api/v1/ui/evidence/${encodeURIComponent(id)}?page=${page}&limit=${limit}`,
    ).then((res) => res.items),

  getEmailDetail: (id: string): Promise<UIEmailDetail> =>
    request<UIEmailDetail>(`/api/v1/ui/emails/${encodeURIComponent(id)}`),

  getCurrentState: (): Promise<SynthesizedCurrentState> =>
    request<SynthesizedCurrentState>("/world/current-state"),

  getChanges: (): Promise<StateChange[]> =>
    request<StateChange[]>("/world/changes"),

  getUIGraph: (
    entityIds?: string[],
    depth: number = 1,
  ): Promise<UIGraphDTO> => {
    let url = `/api/v1/ui/graph?depth=${depth}`;
    if (entityIds && entityIds.length > 0) {
      entityIds.forEach((id) => {
        url += `&entity_ids=${encodeURIComponent(id)}`;
      });
    }
    return request<UIGraphDTO>(url);
  },

  submitCorrection: (
    relationshipId: string,
    action: "confirm" | "reject" | "correct" | "outdate",
    reason: string,
    data?: {
      new_subject?: string;
      new_predicate?: string;
      new_object?: string;
    },
  ) => {
    return request<{
      status: string;
      new_target_id: string;
      observation_id: string;
    }>(
      `/api/v1/world/corrections/relationship/${encodeURIComponent(relationshipId)}`,
      {
        method: "POST",
        body: JSON.stringify({
          action,
          reason,
          ...data,
        }),
        headers: {
          "Content-Type": "application/json",
        },
      },
    );
  },
};
