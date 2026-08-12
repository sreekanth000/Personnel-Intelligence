/**
 * TypeScript interfaces matching Personal Intelligence V0 backend domain models.
 */

export type EntityType =
  | "person"
  | "organization"
  | "project"
  | "product"
  | "role"
  | "location"
  | "event"
  | "document"
  | "concept"
  | "decision"
  | "claim"
  | "commitment"
  | "goal";

export type RelationshipType =
  | "WORKS_FOR"
  | "WORKS_WITH"
  | "MANAGES"
  | "REPORTS_TO"
  | "OWNS"
  | "CREATED"
  | "INVOLVED_IN"
  | "RELATED_TO"
  | "DEPENDS_ON"
  | "PART_OF"
  | "MENTIONS"
  | "REQUESTS"
  | "ASSIGNS"
  | "COMMUNICATES_WITH"
  | "INTERESTED_IN"
  | "RESPONSIBLE_FOR";

export type ReconciliationOutcome =
  "NOVEL" | "CONFIRM" | "REFINE" | "UPDATE" | "CONFLICT" | "UNCERTAIN";

export interface ConfidenceScore {
  score: number;
}

export interface Provenance {
  source_observation_ids: string[];
  extraction_timestamp: string;
  extractor_id: string;
}

export interface EvidenceSpan {
  start_offset?: number;
  end_offset?: number;
  text_snippet: string;
  confidence: ConfidenceScore;
}

export interface Evidence {
  id: string;
  observation_id: string;
  source_message_id?: string;
  source_thread_id?: string;
  target_id: string;
  target_type: string;
  evidence_span: EvidenceSpan;
  recorded_at: string;
}

export interface TemporalValidity {
  valid_from?: string;
  valid_to?: string;
  is_open_ended: boolean;
}

export interface Entity {
  id: string;
  entity_type: EntityType;
  name: string;
  aliases: string[];
  canonical_name?: string;
  email?: string;
  domain?: string;
  confidence: ConfidenceScore;
  provenance: Provenance;
  created_at: string;
  updated_at: string;
  attributes: Record<string, unknown>;
}

export interface Relationship {
  id: string;
  subject: string;
  predicate: RelationshipType | string;
  object: string;
  validity: TemporalValidity;
  confidence: ConfidenceScore;
  evidence_span?: EvidenceSpan;
  source_observation_id?: string;
  provenance: Provenance;
  created_at: string;
}

export interface Decision extends Entity {
  question?: string;
  alternatives?: string[];
  context?: string;
  constraints?: string[];
  reasoning?: string;
  decision?: string;
  status?: string;
  made_at?: string;
}

export interface StateChange {
  id: string;
  observation_id: string;
  entity_id?: string;
  relationship_id?: string;
  outcome: ReconciliationOutcome;
  previous_state?: Record<string, unknown>;
  new_state?: Record<string, unknown>;
  description: string;
  previous_value?: string;
  new_value?: string;
  requires_review: boolean;
  changed_at: string;
  provenance: Provenance;
}

export interface SynthesizedCurrentState {
  timestamp: string;
  active_people_relationships: Relationship[];
  active_projects: Entity[];
  active_goals: Entity[];
  recent_decisions: Entity[];
  recent_events: Entity[];
  important_constraints: Entity[];
  recent_state_changes: StateChange[];
  unresolved_conflicts: Record<string, unknown>[];
}

export interface UIExtractionItem {
  id: string;
  extraction_type: string;
  value: string;
  entity_type?: string;
  predicate?: string;
  subject?: string;
  object?: string;
  confidence: number;
  evidence_span: EvidenceSpan;
}

export interface UIEmailDetail {
  id: string;
  message_id: string;
  thread_id: string;
  sender: string;
  recipients: string[];
  subject: string;
  timestamp: string;
  snippet: string;
  body: string;
  labels: string[];
  extractions: UIExtractionItem[];
}

export interface UIRelationship {
  id: string;
  subject_id: string;
  subject_name: string;
  predicate: string;
  object_id: string;
  object_name: string;
  confidence: number;
  status: string;
  valid_from?: string;
  valid_to?: string;
}

export interface UIEvidence {
  id: string;
  observation_id: string;
  source_message_id?: string;
  target_id: string;
  target_type: string;
  text_snippet: string;
  confidence: number;
  recorded_at: string;
}

export interface UITimelineItem {
  id: string;
  timestamp: string;
  type: string;
  title: string;
  description: string;
  outcome?: string;
  requires_review?: boolean;
}

export interface ContextRequest {
  id?: string;
  task_intent: string;
  query?: string;
  target_entity_ids?: string[];
  max_items?: number;
  purpose?: string;
}

export interface ContextPackage {
  id: string;
  request_id: string;
  purpose: string;
  entities: Entity[];
  relationships: Relationship[];
  claims: unknown[];
  decisions: Entity[];
  events: Entity[];
  commitments: Entity[];
  evidence: Evidence[];
  state_changes: StateChange[];
  summary: string;
  assembled_at: string;
  filtered_count: number;
}

export interface AskRequest {
  question: string;
  purpose?: string;
}

export interface AskResponse {
  answer: str;
  supporting_context: ContextPackage;
  evidence: Evidence[];
  uncertainties: string[];
}

export type str = string;

export interface HealthCheckResponse {
  status: string;
  app_name: string;
  app_version: string;
  databases: {
    duckdb: string;
    kuzu: string;
  };
}

export interface UIGraphNode {
  id: string;
  type: string;
  label: string;
  metadata: Record<string, unknown>;
}

export interface UIGraphEdge {
  id: string;
  source: string;
  target: string;
  relationship_type: string;
  confidence: number;
  status: string;
  evidence_count: number;
  valid_from?: string;
  valid_to?: string;
}

export interface UIGraphDTO {
  nodes: UIGraphNode[];
  edges: UIGraphEdge[];
}
