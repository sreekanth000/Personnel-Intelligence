"""
Personal Intelligence Local State Store.
Encapsulates all 7 core SQLite tables belonging to the Personal Intelligence plugin:
1. event_log (normalized relevant observations with provenance)
2. entity_state (tracked multi-dimensional entity states)
3. goals (contextual intentions and objectives)
4. situations (tension and situational context frames)
5. patterns (discovered non-causal empirical associations)
6. pattern_evidence (empirical observation evidence links)
7. reasoning_episodes (complete bounded reasoning traces and outcomes)

Does NOT mirror external services; ingests only normalized, relevant observations
delegating all external data retrieval to Hermes capabilities.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union
import uuid

from personal_intelligence.core.episodes.store import EpisodeStore
from personal_intelligence.core.events.models import Event
from personal_intelligence.core.events.store import EventStore
from personal_intelligence.core.goals.store import GoalStore
from personal_intelligence.core.patterns.store import PatternStore
from personal_intelligence.core.situations.store import SituationStore
from personal_intelligence.core.state.entity_store import EntityStateStore
from personal_intelligence.storage.db import DatabaseManager



class LocalStateStore:
    """
    Unified manager for the Personal Intelligence SQLite state store.
    Directly owns the 7 relational tables belonging to the plugin.
    """

    ALLOWED_SOURCES = {
        "gmail",
        "drive",
        "calendar",
        "meet",
        "filesystem",
        "hermes",
        "user",
    }

    RELEVANT_OBSERVATION_TYPES = {
        "email_received",
        "calendar_event",
        "meeting_completed",
        "document_changed",
        "task_commitment_detected",
        "routine_change",
        "unusual_state",
    }

    def __init__(self, db_manager: Optional[DatabaseManager] = None) -> None:
        self.db_manager = db_manager or DatabaseManager()
        self.db_manager.initialize_schema()

        self.event_store = EventStore(db_manager=self.db_manager)
        self.entity_store = EntityStateStore(db_manager=self.db_manager)
        self.goal_store = GoalStore(db_manager=self.db_manager)
        self.situation_store = SituationStore(db_manager=self.db_manager)
        self.pattern_store = PatternStore(db_manager=self.db_manager)
        self.episode_store = EpisodeStore(db_manager=self.db_manager)
        self._world_model: Optional[Any] = None

    @property
    def world_model(self) -> Any:
        """Returns the PersonalWorldModel instance backed by this LocalStateStore."""
        if self._world_model is None:
            from personal_intelligence.core.world.model import PersonalWorldModel
            self._world_model = PersonalWorldModel(db_manager=self.db_manager, local_store=self)
        return self._world_model

    def record_observation(
        self,
        source: str,
        source_id: Optional[str] = None,
        timestamp: Optional[Union[datetime, str]] = None,
        observation_type: Optional[str] = None,
        summary: Optional[str] = None,
        evidence: Optional[Union[Dict[str, Any], List[Any], str]] = None,
        provenance: Optional[Dict[str, Any]] = None,
        # Backwards compatibility kwargs:
        payload: Optional[Dict[str, Any]] = None,
        subject_id: Optional[str] = None,
        confidence: float = 1.0,
    ) -> Event:
        """
        Records a normalized observation in the event_log table with preserved provenance.
        Validates source, observation_type, summary, and provenance structure without mirroring external APIs.
        """
        eff_obs_type = observation_type or "unusual_state"
        eff_source_id = source_id or (payload.get("source_id") if payload else None) or (payload.get("id") if payload else None) or str(uuid.uuid4())
        eff_summary = summary or (payload.get("summary") if payload else None) or (payload.get("description") if payload else None) or f"Observation from {source}"
        eff_evidence = evidence if evidence is not None else (payload or {})
        eff_timestamp = timestamp or datetime.now(timezone.utc)

        from personal_intelligence.core.events.observation import record_observation as core_record_obs

        return core_record_obs(
            source=source,
            source_id=eff_source_id,
            timestamp=eff_timestamp,
            observation_type=eff_obs_type,
            summary=eff_summary,
            evidence=eff_evidence,
            provenance=provenance or {"source": source},
            subject_id=subject_id or "user",
            confidence=confidence,
            event_store=self.event_store,
        )

    def get_table_counts(self) -> Dict[str, int]:
        """Returns the record counts across all 7 core tables."""
        conn = self.db_manager.get_connection()
        try:
            cursor = conn.cursor()
            counts = {}
            for table in [
                "event_log",
                "entity_state",
                "goals",
                "situations",
                "patterns",
                "pattern_evidence",
                "reasoning_episodes",
            ]:
                cursor.execute(f"SELECT COUNT(*) as cnt FROM {table};")
                row = cursor.fetchone()
                counts[table] = int(row["cnt"]) if row else 0
            return counts
        finally:
            conn.close()
