-- Local-First SQLite Storage Schema for Personal Intelligence

-- Append-only event log table
CREATE TABLE IF NOT EXISTS event_log (
    id TEXT PRIMARY KEY,
    event_time TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    event_type TEXT NOT NULL,
    source TEXT NOT NULL,
    subject_id TEXT,
    source_id TEXT,
    provenance_json TEXT,
    payload_json TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    event_hash TEXT UNIQUE NOT NULL
);

-- Required indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_event_log_event_time ON event_log(event_time);
CREATE INDEX IF NOT EXISTS idx_event_log_event_type ON event_log(event_type);
CREATE INDEX IF NOT EXISTS idx_event_log_source ON event_log(source);
CREATE INDEX IF NOT EXISTS idx_event_log_subject_id ON event_log(subject_id);
CREATE INDEX IF NOT EXISTS idx_event_log_source_id ON event_log(source_id);

-- Entity state tracking table
CREATE TABLE IF NOT EXISTS entity_state (
    entity_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    state_json TEXT NOT NULL,
    last_updated_at TEXT NOT NULL,
    source_event_ids_json TEXT,
    metadata_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_entity_state_type ON entity_state(entity_type);
CREATE INDEX IF NOT EXISTS idx_entity_state_updated ON entity_state(last_updated_at);

-- Timeline entries table
CREATE TABLE IF NOT EXISTS timeline_entries (
    entry_id TEXT PRIMARY KEY,
    entry_type TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    end_timestamp TEXT,
    title TEXT NOT NULL,
    description TEXT,
    associated_event_ids_json TEXT,
    associated_goal_ids_json TEXT,
    payload_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_timeline_timestamp ON timeline_entries(timestamp);

-- State snapshots table
CREATE TABLE IF NOT EXISTS state_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    user_state_json TEXT NOT NULL,
    entities_json TEXT NOT NULL,
    active_goal_ids_json TEXT,
    active_situation_ids_json TEXT,
    version INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_state_timestamp ON state_snapshots(timestamp);

-- Goals table (contextual intentions)
CREATE TABLE IF NOT EXISTS goals (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    priority TEXT NOT NULL DEFAULT 'medium',
    status TEXT NOT NULL DEFAULT 'active',
    parent_goal_id TEXT,
    sub_goal_ids_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_goals_status ON goals(status);

-- Situations table (generic situational context frames)
CREATE TABLE IF NOT EXISTS situations (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_evaluated_at TEXT,
    next_evaluation_at TEXT,
    priority TEXT NOT NULL DEFAULT 'medium',
    novelty REAL NOT NULL DEFAULT 0.0,
    context_json TEXT NOT NULL DEFAULT '{}',
    evidence_json TEXT NOT NULL DEFAULT '[]',
    related_goals_json TEXT NOT NULL DEFAULT '[]',
    expires_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_situations_status ON situations(status);
CREATE INDEX IF NOT EXISTS idx_situations_type ON situations(type);
CREATE INDEX IF NOT EXISTS idx_situations_expires_at ON situations(expires_at);
CREATE INDEX IF NOT EXISTS idx_situations_next_evaluation_at ON situations(next_evaluation_at);

-- V1_DEFERRED: Novelty scores are transient and computed on-demand by NoveltyEngine.
-- This table is retained for schema compatibility but should not be actively written in V1.
CREATE TABLE IF NOT EXISTS novelty_scores (
    assessment_id TEXT PRIMARY KEY,
    score REAL NOT NULL,
    novelty_type TEXT NOT NULL,
    explanation TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    confidence REAL DEFAULT 1.0,
    contributing_factors_json TEXT,
    baseline_reference TEXT,
    metrics_json TEXT
);

-- V1_DEFERRED: Legacy pattern representation superseded by the 'patterns' table below.
-- Retained for backward compatibility only. New code should use 'patterns' + 'pattern_evidence'.
CREATE TABLE IF NOT EXISTS learned_patterns (
    pattern_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    cadence TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.5,
    observation_count INTEGER DEFAULT 1,
    first_observed_at TEXT NOT NULL,
    last_observed_at TEXT NOT NULL,
    typical_time_window TEXT,
    typical_days_json TEXT,
    associated_events_json TEXT,
    attributes_json TEXT,
    is_active INTEGER DEFAULT 1
);

-- Personal Learning Engine: patterns table
CREATE TABLE IF NOT EXISTS patterns (
    id TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    support_count INTEGER DEFAULT 1,
    contradiction_count INTEGER DEFAULT 0,
    evidence_strength TEXT NOT NULL,
    status TEXT NOT NULL,
    metadata_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_patterns_status ON patterns(status);
CREATE INDEX IF NOT EXISTS idx_patterns_last_seen ON patterns(last_seen);

-- Personal Learning Engine: pattern_evidence table
CREATE TABLE IF NOT EXISTS pattern_evidence (
    evidence_id TEXT PRIMARY KEY,
    pattern_id TEXT NOT NULL,
    observation_type TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    episode_id TEXT,
    event_ids_json TEXT,
    details_json TEXT,
    FOREIGN KEY (pattern_id) REFERENCES patterns(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_pattern_evidence_pattern ON pattern_evidence(pattern_id);
CREATE INDEX IF NOT EXISTS idx_pattern_evidence_observed ON pattern_evidence(observed_at);

-- Intervention decisions table
CREATE TABLE IF NOT EXISTS intervention_decisions (
    decision_id TEXT PRIMARY KEY,
    situation_id TEXT NOT NULL,
    delivery_mode TEXT NOT NULL,
    reasoning TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    recommended_content TEXT,
    user_feedback TEXT,
    feedback_notes TEXT,
    feedback_received_at TEXT,
    metadata_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_interventions_situation ON intervention_decisions(situation_id);

-- Unified reasoning episodes table (One table preserving the complete reasoning lifecycle)
CREATE TABLE IF NOT EXISTS reasoning_episodes (
    id TEXT PRIMARY KEY,
    situation_id TEXT,
    created_at TEXT NOT NULL,
    context_snapshot_json TEXT,
    observations_json TEXT,
    inferences_json TEXT,
    predictions_json TEXT,
    hermes_task TEXT,
    hermes_result_json TEXT,
    recommendation_json TEXT,
    urgency TEXT,
    actionability TEXT,
    relevance TEXT,
    evidence_strength TEXT,
    intervention_decision_json TEXT,
    user_response_json TEXT,
    outcome_json TEXT,
    follow_up_at TEXT,
    status TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_episodes_situation ON reasoning_episodes(situation_id);
CREATE INDEX IF NOT EXISTS idx_episodes_created ON reasoning_episodes(created_at);
CREATE INDEX IF NOT EXISTS idx_episodes_status ON reasoning_episodes(status);

-- Sensitive Context Access Audit Log
CREATE TABLE IF NOT EXISTS context_access_audit (
    audit_id TEXT PRIMARY KEY,
    accessed_at TEXT NOT NULL,
    accessor TEXT NOT NULL,
    situation_id TEXT,
    events_accessed_count INTEGER NOT NULL DEFAULT 0,
    features_accessed_json TEXT,
    sensitivity_level TEXT NOT NULL DEFAULT 'standard',
    purpose TEXT NOT NULL,
    metadata_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_accessed_at ON context_access_audit(accessed_at);
CREATE INDEX IF NOT EXISTS idx_audit_accessor ON context_access_audit(accessor);
CREATE INDEX IF NOT EXISTS idx_audit_situation ON context_access_audit(situation_id);

-- V1_DEFERRED: Vector embeddings for semantic search — deferred to post-V1.
-- Retained for schema compatibility. Not actively used by V1 reasoning pipeline.
CREATE TABLE IF NOT EXISTS vector_embeddings (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    content_text TEXT NOT NULL,
    embedding_blob BLOB NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_vec_source ON vector_embeddings(source_type, source_id);

-- Entity Nodes for Personal Knowledge Graph
CREATE TABLE IF NOT EXISTS entity_nodes (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    aliases_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_entity_nodes_name ON entity_nodes(name);
CREATE INDEX IF NOT EXISTS idx_entity_nodes_type ON entity_nodes(entity_type);

-- Entity Edges for Personal Knowledge Graph
-- Blueprint §7: Temporal validity (valid_from/valid_to) prevents treating past relationships as permanent.
CREATE TABLE IF NOT EXISTS entity_edges (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    relationship TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 1.0,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    valid_from TEXT,
    valid_to TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    FOREIGN KEY (source_id) REFERENCES entity_nodes(id) ON DELETE CASCADE,
    FOREIGN KEY (target_id) REFERENCES entity_nodes(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_entity_edges_source ON entity_edges(source_id);
CREATE INDEX IF NOT EXISTS idx_entity_edges_target ON entity_edges(target_id);
CREATE INDEX IF NOT EXISTS idx_entity_edges_rel ON entity_edges(relationship);
CREATE INDEX IF NOT EXISTS idx_entity_edges_status ON entity_edges(status);

-- V1_DEFERRED: Probabilistic facts with Bayesian belief scores — deferred to post-V1.
-- Retained for schema compatibility. Not actively used in V1 deterministic reasoning.
CREATE TABLE IF NOT EXISTS probabilistic_facts (
    id TEXT PRIMARY KEY,
    subject TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object TEXT NOT NULL,
    belief_score REAL NOT NULL DEFAULT 0.5,
    salience_score REAL NOT NULL DEFAULT 1.0,
    status TEXT NOT NULL DEFAULT 'active',
    provenance_json TEXT NOT NULL DEFAULT '{}',
    evidence_ids_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_facts_triple ON probabilistic_facts(subject, predicate, object);
CREATE INDEX IF NOT EXISTS idx_facts_status ON probabilistic_facts(status);

-- V1_DEFERRED: Person profiles for interpersonal dynamics — deferred to post-V1.
-- Retained for schema compatibility. Not actively used in V1 reasoning.
CREATE TABLE IF NOT EXISTS person_profiles (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    relationship_role TEXT NOT NULL DEFAULT 'collaborator',
    email TEXT,
    avg_response_delay_mins REAL NOT NULL DEFAULT 60.0,
    priority_sensitivity REAL NOT NULL DEFAULT 0.5,
    preferred_channel TEXT NOT NULL DEFAULT 'email',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_person_profiles_name ON person_profiles(name);

-- V1_DEFERRED: Predictive processing expectation baselines — deferred to post-V1.
-- Retained for schema compatibility. Not actively used in V1 deterministic novelty detection.
CREATE TABLE IF NOT EXISTS predictive_baselines (
    id TEXT PRIMARY KEY,
    time_window_key TEXT NOT NULL,
    expected_location TEXT NOT NULL DEFAULT 'Primary Workspace',
    expected_activity TEXT NOT NULL DEFAULT 'Deep Work',
    expected_cognitive_load REAL NOT NULL DEFAULT 0.5,
    sample_count INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pred_baseline_key ON predictive_baselines(time_window_key);

