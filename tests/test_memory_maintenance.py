"""
Unit & Invariant Test Suite for Memory Maintenance & Consolidation Subsystem.

Verifies:
1. Old observations remain available and immutable across maintenance cycles.
2. Patterns decay deterministically without synthesizing unsupported patterns.
3. Reasoning episodes remain strictly immutable (pre/post snapshot equality).
4. Provenance remains intact and unaltered.
5. No new inferences, facts, or entities are created during maintenance.
6. Salience decays deterministically and stays within [0.0, 1.0].
7. Stale situations are transitioned to closed/archived.
8. Database maintenance (WAL checkpoint & PRAGMA optimize) succeeds.
"""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from personal_intelligence.core.episodes.models import ReasoningEpisode
from personal_intelligence.core.events.models import Event, format_iso8601
from personal_intelligence.core.memory.maintenance import MemoryMaintenanceJob, MemoryMaintenanceSummary
from personal_intelligence.core.patterns.models import Pattern, PatternStatus
from personal_intelligence.core.situations.models import Situation, SituationPriority, SituationStatus
from personal_intelligence.core.world.model import PersonalWorldModel
from personal_intelligence.storage.db import DatabaseManager
from personal_intelligence.storage.local_store import LocalStateStore


class TestMemoryMaintenanceSubsystem(unittest.TestCase):
    """Rigorous invariant tests for MemoryMaintenanceJob."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "test_maintenance.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.db_manager.initialize_schema()
        self.local_store = LocalStateStore(db_manager=self.db_manager)
        self.world_model = PersonalWorldModel(db_manager=self.db_manager, local_store=self.local_store)
        self.maintenance_job = MemoryMaintenanceJob(
            db_manager=self.db_manager,
            local_store=self.local_store,
            pattern_store=self.local_store.pattern_store,
            situation_store=self.local_store.situation_store,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_old_observations_remain_immutable_and_available(self) -> None:
        """Verifies raw historical observations in event_log are strictly preserved."""
        now = datetime.now(timezone.utc)
        old_time = now - timedelta(days=120)

        # Record multiple historical events via append
        ev1 = Event(
            source="gmail",
            source_id="email-001",
            event_type="email_received",
            event_time=old_time,
            payload={"summary": "Historical budget planning discussion", "sender": "cfo@company.com"},
            provenance={"tool": "gmail_sync", "raw_message_id": "msg-999"},
        )
        ev2 = Event(
            source="calendar",
            source_id="cal-002",
            event_type="calendar_event",
            event_time=now - timedelta(days=60),
            payload={"summary": "Quarterly business review"},
            provenance={"tool": "gcal_sync", "event_uid": "uid-888"},
        )
        self.local_store.event_store.append(ev1)
        self.local_store.event_store.append(ev2)

        # Execute maintenance with aggressive retention parameters
        summary = self.maintenance_job.run_maintenance(
            retention_days=15,  # 15 days retention for allowed caches
            salience_decay_days=10.0,
            situation_stale_hours=24.0,
            optimize_db=True,
        )

        # Assert raw events in event_log are still present and unaltered
        all_events = self.local_store.event_store.get_recent(limit=50)
        self.assertEqual(len(all_events), 2)
        event_ids = [e.source_id for e in all_events]
        self.assertIn("email-001", event_ids)
        self.assertIn("cal-002", event_ids)

        retrieved_ev1 = next(e for e in all_events if e.source_id == "email-001")
        self.assertEqual(retrieved_ev1.payload["summary"], "Historical budget planning discussion")
        self.assertEqual(retrieved_ev1.provenance["tool"], "gmail_sync")
        self.assertEqual(retrieved_ev1.provenance["raw_message_id"], "msg-999")

    def test_reasoning_episodes_remain_strictly_immutable(self) -> None:
        """Verifies reasoning episodes are never altered or rewritten during maintenance."""
        now = datetime.now(timezone.utc)

        episode = ReasoningEpisode(
            id="ep-invariant-001",
            situation_id="sit-test-123",
            created_at=now - timedelta(days=45),
            observations=["User missed urgent standup meeting with team"],
            inferences=["User was likely engaged in unscheduled deep work"],
            predictions=["May require meeting summary request to organizer"],
            urgency="high",
            actionability="actionable",
            relevance="high",
            evidence_strength="strong",
            status="completed",
        )
        self.local_store.episode_store.create_episode(episode)

        # Snapshot episode state prior to maintenance
        pre_episodes = self.local_store.episode_store.get_episodes(limit=10)
        self.assertEqual(len(pre_episodes), 1)
        pre_dict = pre_episodes[0].to_dict()

        # Run maintenance
        self.maintenance_job.run_maintenance(
            retention_days=7,
            salience_decay_days=5.0,
            situation_stale_hours=12.0,
        )

        # Retrieve and compare post-maintenance
        post_episodes = self.local_store.episode_store.get_episodes(limit=10)
        self.assertEqual(len(post_episodes), 1)
        post_dict = post_episodes[0].to_dict()

        self.assertEqual(pre_dict, post_dict)
        self.assertEqual(post_episodes[0].inferences, ["User was likely engaged in unscheduled deep work"])
        self.assertEqual(post_episodes[0].predictions, ["May require meeting summary request to organizer"])

    def test_patterns_decay_deterministically_without_new_patterns(self) -> None:
        """Verifies patterns transition from ACTIVE to DECAYING and INACTIVE deterministically, with zero pattern creation."""
        now = datetime.now(timezone.utc)

        # Pattern 1: Recently seen, should stay ACTIVE
        pat_active = Pattern(
            id="pat-recent-001",
            description="Morning email checking routine between 8am and 9am",
            last_seen=now - timedelta(days=2),
            status=PatternStatus.ACTIVE.value,
            support_count=10,
        )
        # Pattern 2: Inactive for 45 days, should transition to DECAYING
        pat_decaying = Pattern(
            id="pat-stale-002",
            description="Friday evening gym workouts",
            last_seen=now - timedelta(days=45),
            status=PatternStatus.ACTIVE.value,
            support_count=5,
        )
        # Pattern 3: Inactive for 120 days and already DECAYING, should transition to INACTIVE
        pat_inactive = Pattern(
            id="pat-dead-003",
            description="Tuesday lunch meetings at cafe",
            last_seen=now - timedelta(days=120),
            status=PatternStatus.DECAYING.value,
            support_count=2,
        )

        self.local_store.pattern_store.create_pattern(pat_active)
        self.local_store.pattern_store.create_pattern(pat_decaying)
        self.local_store.pattern_store.create_pattern(pat_inactive)

        pre_count = len(self.local_store.pattern_store.list_patterns(limit=100))
        self.assertEqual(pre_count, 3)

        summary = self.maintenance_job.run_maintenance(
            pattern_decay_days=30.0,
        )

        post_patterns = self.local_store.pattern_store.list_patterns(limit=100)
        # Invariant: Pattern count must not increase (no new patterns created)
        self.assertEqual(len(post_patterns), 3)
        self.assertEqual(summary.patterns_evaluated, 3)
        self.assertEqual(summary.patterns_decayed, 2)

        p1 = self.local_store.pattern_store.get_pattern("pat-recent-001")
        self.assertIsNotNone(p1)
        self.assertEqual(p1.status, PatternStatus.ACTIVE.value)

        p2 = self.local_store.pattern_store.get_pattern("pat-stale-002")
        self.assertIsNotNone(p2)
        self.assertEqual(p2.status, PatternStatus.DECAYING.value)

        p3 = self.local_store.pattern_store.get_pattern("pat-dead-003")
        self.assertIsNotNone(p3)
        self.assertEqual(p3.status, PatternStatus.INACTIVE.value)

    def test_salience_decay_is_deterministic_and_bounded(self) -> None:
        """Verifies probabilistic fact salience decay applies smoothly and remains bounded in [0.0, 1.0]."""
        now = datetime.now(timezone.utc)
        conn = self.db_manager.get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO probabilistic_facts (id, subject, predicate, object, belief_score, salience_score, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "fact-001",
                        "User",
                        "prefers_focus_mode",
                        "Morning",
                        0.85,
                        0.90,
                        "active",
                        format_iso8601(now - timedelta(days=10)),
                        format_iso8601(now - timedelta(days=10)),
                    ),
                )
        finally:
            conn.close()

        summary = self.maintenance_job.run_maintenance(salience_decay_days=5.0)
        self.assertEqual(summary.salience_records_decayed, 1)

        conn = self.db_manager.get_connection()
        try:
            row = conn.execute("SELECT salience_score, belief_score, status FROM probabilistic_facts WHERE id = 'fact-001'").fetchone()
            self.assertIsNotNone(row)
            new_salience = float(row["salience_score"])
            # Salience should have decayed from 0.90
            self.assertLess(new_salience, 0.90)
            self.assertGreater(new_salience, 0.0)
            # Belief score and epistemic status must NOT be changed
            self.assertEqual(float(row["belief_score"]), 0.85)
            self.assertEqual(row["status"], "active")
        finally:
            conn.close()

    def test_stale_situations_transition_properly(self) -> None:
        """Verifies stale open situations are transitioned to closed/archived without creating new situations."""
        now = datetime.now(timezone.utc)

        # Situation 1: Fresh (1 hour old)
        sit_fresh = Situation(
            id="sit-fresh-01",
            type="goal_risk",
            status=SituationStatus.OPEN.value,
            priority=SituationPriority.HIGH.value,
            created_at=now - timedelta(hours=1),
            updated_at=now - timedelta(hours=1),
        )
        # Situation 2: Stale (96 hours old, threshold = 72 hours)
        sit_stale = Situation(
            id="sit-stale-02",
            type="unresolved_issue",
            status=SituationStatus.OPEN.value,
            priority=SituationPriority.MEDIUM.value,
            created_at=now - timedelta(hours=96),
            updated_at=now - timedelta(hours=96),
        )

        self.local_store.situation_store.create(sit_fresh)
        self.local_store.situation_store.create(sit_stale)

        summary = self.maintenance_job.run_maintenance(situation_stale_hours=72.0)
        self.assertEqual(summary.stale_situations_maintained, 1)

        ret_fresh = self.local_store.situation_store.get("sit-fresh-01")
        self.assertIsNotNone(ret_fresh)
        self.assertEqual(ret_fresh.status, SituationStatus.OPEN.value)

        ret_stale = self.local_store.situation_store.get("sit-stale-02")
        self.assertIsNotNone(ret_stale)
        self.assertEqual(ret_stale.status, SituationStatus.CLOSED.value)
        self.assertEqual(ret_stale.context.get("closed_reason"), "stale_inactivity")

    def test_no_new_inferences_or_facts_synthesized_during_maintenance(self) -> None:
        """Verifies that running maintenance never invents new facts, entities, edges, or inferences."""
        now = datetime.now(timezone.utc)

        # Seed some data with allowed source
        self.world_model.record_observation(
            source="filesystem",
            source_id="file-mod-12",
            timestamp=now - timedelta(days=5),
            observation_type="document_changed",
            summary="Feature documentation updated in workspace",
            provenance={"tool": "fs_watcher", "path": "docs/architecture.md"},
        )

        conn = self.db_manager.get_connection()
        try:
            pre_facts = conn.execute("SELECT COUNT(*) as c FROM epistemic_records").fetchone()["c"]
            pre_nodes = conn.execute("SELECT COUNT(*) as c FROM entity_nodes").fetchone()["c"]
            pre_edges = conn.execute("SELECT COUNT(*) as c FROM entity_edges").fetchone()["c"]
            pre_episodes = conn.execute("SELECT COUNT(*) as c FROM reasoning_episodes").fetchone()["c"]
        finally:
            conn.close()

        # Run maintenance
        self.world_model.run_memory_maintenance(
            retention_days=30,
            salience_decay_days=2.0,
            situation_stale_hours=48.0,
            optimize_db=True,
        )

        conn = self.db_manager.get_connection()
        try:
            post_facts = conn.execute("SELECT COUNT(*) as c FROM epistemic_records").fetchone()["c"]
            post_nodes = conn.execute("SELECT COUNT(*) as c FROM entity_nodes").fetchone()["c"]
            post_edges = conn.execute("SELECT COUNT(*) as c FROM entity_edges").fetchone()["c"]
            post_episodes = conn.execute("SELECT COUNT(*) as c FROM reasoning_episodes").fetchone()["c"]
        finally:
            conn.close()

        # Invariant: Counts must be strictly identical (zero synthesis during maintenance)
        self.assertEqual(pre_facts, post_facts)
        self.assertEqual(pre_nodes, post_nodes)
        self.assertEqual(pre_edges, post_edges)
        self.assertEqual(pre_episodes, post_episodes)


if __name__ == "__main__":
    unittest.main()
