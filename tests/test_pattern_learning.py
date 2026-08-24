"""
Comprehensive Unit and Integration Tests for Personal Intelligence Pattern Learning.

Verifies:
  - Multi-Domain Pattern Discovery:
      * WORLD PATTERNS (Environmental rhythms, cross-source correlations)
      * BEHAVIORAL PATTERNS (Habit sequences e.g. late meetings followed by delayed work)
      * INTERACTION PATTERNS (Recommendation specificity, timing, urgency, context receptivity)
  - Strict Non-Causal Semantics (associations only, no causal claims)
  - Hypothesis-First Lifecycle (OBSERVED -> HYPOTHESIS -> EMERGING -> SUPPORTED -> ACTIVE -> DECAYING -> INACTIVE)
  - Supporting & Contradicting Reasoning Episode Provenance
  - Multi-Source Learning (observations, episodes, recommendations, user responses, outcomes)
  - Dynamic discovery without hard-coded rules
"""

from datetime import datetime, timedelta, timezone
import json
import os
import tempfile
import unittest
from typing import Any, Dict, List, Optional
import uuid

from personal_intelligence.core.episodes import (
    EpisodeStatus,
    EpisodeStore,
    ReasoningEpisode,
    RecommendationResult,
)
from personal_intelligence.core.events.models import Event
from personal_intelligence.core.events.store import EventStore
from personal_intelligence.core.patterns import (
    EvidenceObservationType,
    LearningEngine,
    Pattern,
    PatternEvidence,
    PatternStatus,
    PatternStore,
    PatternType,
)
from personal_intelligence.storage.db import DatabaseManager


def _make_episode(
    store: EpisodeStore,
    task: str = "task_test",
    recommendation: Optional[Dict[str, Any]] = None,
    user_response: Optional[Dict[str, Any]] = None,
    outcome: Optional[Dict[str, Any]] = None,
    created_at: Optional[datetime] = None,
    urgency: str = "medium",
    outcome_eval: str = "Test episode evaluation",
) -> ReasoningEpisode:
    now = created_at or datetime.now(timezone.utc)
    ep = store.create_episode(
        trigger_type="reasoning_cycle",
        created_at=now,
        metadata={
            "task": task,
            "recommendation": recommendation or {"content": "Sample recommendation"},
            "user_response": user_response or {"response": "ACCEPTED"},
            "outcome": outcome or {"status": "COMPLETED", "success": True},
            "urgency": urgency,
        },
    )

    store.update_episode(
        episode_id=ep.id,
        outcome_evaluation=outcome_eval,
        ended_at=now + timedelta(minutes=5),
        metadata={
            "task": task,
            "recommendation": recommendation or {"content": "Sample recommendation"},
            "user_response": user_response or {"response": "ACCEPTED"},
            "outcome": outcome or {"status": "COMPLETED", "success": True},
            "urgency": urgency,
        },
    )
    return store.get_episode(ep.id) or ep


class TestPatternModelsAndLifecycle(unittest.TestCase):
    """Test Pattern models, PatternType classification, and 7-stage lifecycle."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_pat_models.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.pattern_store = PatternStore(db_manager=self.db_manager)
        self.engine = LearningEngine(pattern_store=self.pattern_store)
        self.base_time = datetime(2026, 8, 1, 10, 0, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_pattern_types_and_defaults(self) -> None:
        """Verify PatternType enum classification on Pattern."""
        pat = Pattern(
            description="Tuesday afternoons are frequently observed with high calendar density.",
            pattern_type=PatternType.WORLD_PATTERN,
            first_seen=self.base_time,
            last_seen=self.base_time,
        )
        self.assertEqual(pat.pattern_type, PatternType.WORLD_PATTERN.value)
        self.assertEqual(pat.confidence, 1.0)
        self.assertEqual(pat.status, PatternStatus.OBSERVED.value)

        # Dictionary round-trip
        d = pat.to_dict()
        self.assertEqual(d["pattern_type"], PatternType.WORLD_PATTERN.value)
        reconstituted = Pattern.from_dict(d)
        self.assertEqual(reconstituted.pattern_type, PatternType.WORLD_PATTERN.value)

    def test_hypothesis_first_initialization(self) -> None:
        """Verify candidate patterns default to HYPOTHESIS upon discovery."""
        pat = self.engine.register_candidate_pattern(
            description="Evening runs appear associated with deeper sleep.",
            pattern_type=PatternType.BEHAVIORAL_PATTERN,
            first_seen=self.base_time,
        )
        self.assertEqual(pat.status, PatternStatus.HYPOTHESIS.value)
        self.assertEqual(pat.pattern_type, PatternType.BEHAVIORAL_PATTERN.value)

    def test_complete_7_stage_lifecycle_and_decay(self) -> None:
        """
        Verify progression across all 7 stages:
        OBSERVED -> HYPOTHESIS -> EMERGING -> SUPPORTED -> ACTIVE -> DECAYING -> INACTIVE -> RECOVERY.
        """
        pat = self.engine.register_candidate_pattern(
            description="Deep work sessions over 3 hours are frequently followed by restorative breaks.",
            first_seen=self.base_time,
            initial_status=PatternStatus.OBSERVED,
        )
        self.assertEqual(pat.status, PatternStatus.OBSERVED.value)

        # Support 2: HYPOTHESIS
        pat, _ = self.engine.record_evidence(
            pattern_id=pat.id,
            observation_type=EvidenceObservationType.SUPPORT,
            observed_at=self.base_time + timedelta(days=1),
        )
        self.assertEqual(pat.status, PatternStatus.HYPOTHESIS.value)

        # Support 3-4: EMERGING
        for i in range(2):
            pat, _ = self.engine.record_evidence(
                pattern_id=pat.id,
                observation_type=EvidenceObservationType.SUPPORT,
                observed_at=self.base_time + timedelta(days=2 + i),
            )
        self.assertEqual(pat.status, PatternStatus.EMERGING.value)

        # Support 5-7: SUPPORTED
        for i in range(3):
            pat, _ = self.engine.record_evidence(
                pattern_id=pat.id,
                observation_type=EvidenceObservationType.SUPPORT,
                observed_at=self.base_time + timedelta(days=5 + i),
            )
        self.assertEqual(pat.status, PatternStatus.SUPPORTED.value)

        # Support 8-10: ACTIVE
        for i in range(3):
            pat, _ = self.engine.record_evidence(
                pattern_id=pat.id,
                observation_type=EvidenceObservationType.SUPPORT,
                observed_at=self.base_time + timedelta(days=9 + i),
            )
        self.assertEqual(pat.status, PatternStatus.ACTIVE.value)
        self.assertEqual(pat.evidence_strength, "strong")

        # Contradictions accumulate -> DECAYING
        for i in range(3):
            pat, _ = self.engine.record_evidence(
                pattern_id=pat.id,
                observation_type=EvidenceObservationType.CONTRADICTION,
                observed_at=self.base_time + timedelta(days=12 + i),
            )
        self.assertEqual(pat.status, PatternStatus.DECAYING.value)

        # Temporal silence (45+ days) -> INACTIVE
        stale_time = self.base_time + timedelta(days=60)
        new_status, _ = self.engine.evaluate_progression(pat, as_of=stale_time)
        self.assertEqual(new_status, PatternStatus.INACTIVE)

        # Fresh support after silence -> RECOVERY to HYPOTHESIS/EMERGING
        pat.status = PatternStatus.INACTIVE.value
        self.pattern_store.update_pattern(pat)
        pat, _ = self.engine.record_evidence(
            pattern_id=pat.id,
            observation_type=EvidenceObservationType.SUPPORT,
            observed_at=stale_time,
        )
        self.assertIn(pat.status, (PatternStatus.EMERGING.value, PatternStatus.HYPOTHESIS.value, PatternStatus.SUPPORTED.value))


class TestNonCausalSemantics(unittest.TestCase):
    """Test strict non-causal association semantics."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_non_causal.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.pattern_store = PatternStore(db_manager=self.db_manager)
        self.engine = LearningEngine(pattern_store=self.pattern_store)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_causal_verbs_sanitized(self) -> None:
        """Causal phrasing must be sanitized to association phrasing."""
        p1 = self.engine.register_candidate_pattern("Heavy meeting days cause delayed replies.")
        self.assertNotIn("causes", p1.description.lower())
        self.assertNotIn("cause", p1.description.lower())
        self.assertIn("associated with", p1.description.lower())

        p2 = self.engine.register_candidate_pattern("Late evening work leads to poor sleep.")
        self.assertNotIn("leads to", p2.description.lower())
        self.assertIn("appears correlated with", p2.description.lower())


        p3 = self.engine.register_candidate_pattern("Skipping lunch results in afternoon fatigue.")
        self.assertNotIn("results in", p3.description.lower())
        self.assertIn("frequently followed by", p3.description.lower())


class TestBehavioralPatternLearning(unittest.TestCase):
    """Test dynamic learning of Behavioral Patterns."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_behavioral.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.pattern_store = PatternStore(db_manager=self.db_manager)
        self.episode_store = EpisodeStore(db_manager=self.db_manager)
        self.engine = LearningEngine(pattern_store=self.pattern_store)
        self.base_time = datetime(2026, 8, 10, 8, 0, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_late_meetings_followed_by_delayed_work_pattern(self) -> None:
        """
        Verify dynamic discovery of:
        'Late meetings are often followed by delayed work.'
        """
        events = []
        for day in range(3):
            day_base = self.base_time + timedelta(days=day)
            # Late meeting at 17:30 (hour 17)
            m_event = Event(
                id=f"evt-late-meeting-{day}",
                event_type="calendar_meeting",
                source="calendar",
                event_time=day_base.replace(hour=17, minute=30),
                payload={"title": "Late architectural sync", "duration_minutes": 60},
            )
            # Delayed subsequent work at 19:30
            w_event = Event(
                id=f"evt-delayed-work-{day}",
                event_type="task_work",
                source="filesystem",
                event_time=day_base.replace(hour=19, minute=30),
                payload={"task": "delayed deliverable writeup", "overrun": True},
            )
            events.extend([m_event, w_event])

        episodes = [
            _make_episode(
                store=self.episode_store,
                task="late_meeting_investigation",
                outcome_eval="Late meeting caused delayed project work writeup.",
                created_at=self.base_time + timedelta(days=1),
            )
        ]

        patterns = self.engine.discover_behavioral_patterns(events=events, episodes=episodes)

        self.assertGreater(len(patterns), 0)
        late_meeting_pat = next((p for p in patterns if "late meeting" in p.description.lower()), None)
        self.assertIsNotNone(late_meeting_pat)
        self.assertEqual(late_meeting_pat.pattern_type, PatternType.BEHAVIORAL_PATTERN.value)
        self.assertIn("delayed work", late_meeting_pat.description.lower())
        # Episode provenance referenced
        self.assertIn(episodes[0].id, late_meeting_pat.supporting_episodes)


class TestInteractionPatternLearning(unittest.TestCase):
    """Test dynamic learning of Interaction Patterns with supporting and contradicting episodes."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_interaction.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.pattern_store = PatternStore(db_manager=self.db_manager)
        self.episode_store = EpisodeStore(db_manager=self.db_manager)
        self.engine = LearningEngine(pattern_store=self.pattern_store)
        self.base_time = datetime(2026, 8, 1, 9, 0, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_specific_recommendations_vs_generic_reminders(self) -> None:
        """
        Verify: 'Specific recommendations are more often accepted than generic reminders.'
        Must reference supporting and contradicting reasoning episodes.
        """
        episodes = []

        # 3 Specific recommendations (2 ACCEPTED, 1 DISMISSED)
        for i in range(2):
            ep = _make_episode(
                store=self.episode_store,
                task=f"task_specific_{i}",
                recommendation={"content": "Shift today's 17:30 sync by 15 minutes to allow recovery before client demo."},
                user_response={"response": RecommendationResult.ACCEPTED.value},
                created_at=self.base_time + timedelta(days=i),
            )
            episodes.append(ep)

        ep_spec_diss = _make_episode(
            store=self.episode_store,
            task="task_specific_diss",
            recommendation={"content": "Postpone sprint planning by 30 minutes to permit travel buffer at 14:00."},
            user_response={"response": RecommendationResult.DISMISSED.value},
            created_at=self.base_time + timedelta(days=2),
        )
        episodes.append(ep_spec_diss)

        # 2 Generic reminders (2 DISMISSED)
        for i in range(2):
            ep = _make_episode(
                store=self.episode_store,
                task=f"task_generic_{i}",
                recommendation={"content": "Take a break."},
                user_response={"response": RecommendationResult.DISMISSED.value},
                created_at=self.base_time + timedelta(days=3 + i),
            )
            episodes.append(ep)

        patterns = self.engine.discover_interaction_patterns(episodes)

        self.assertGreater(len(patterns), 0)
        spec_pat = next((p for p in patterns if "specific" in p.description.lower()), None)
        self.assertIsNotNone(spec_pat)
        self.assertEqual(spec_pat.pattern_type, PatternType.INTERACTION_PATTERN.value)


        # Check supporting episodes: specific accepted + generic dismissed
        supp_eps = self.pattern_store.get_supporting_episodes(spec_pat.id)
        self.assertGreater(len(supp_eps), 0)
        self.assertIn(episodes[0].id, supp_eps)
        self.assertIn(episodes[1].id, supp_eps)

        # Check contradicting episodes: specific dismissed
        contra_eps = self.pattern_store.get_contradicting_episodes(spec_pat.id)
        self.assertIn(ep_spec_diss.id, contra_eps)

    def test_timing_receptivity_pattern(self) -> None:
        """Verify discovery of morning vs evening recommendation acceptance preferences."""
        episodes = []

        # 3 Morning recommendations (3 ACCEPTED)
        for i in range(3):
            ep = _make_episode(
                store=self.episode_store,
                task=f"morning_task_{i}",
                recommendation={"content": f"Morning focus block recommendation {i}."},
                user_response={"response": RecommendationResult.ACCEPTED.value},
                created_at=self.base_time.replace(hour=9) + timedelta(days=i),
            )
            episodes.append(ep)

        # 2 Evening recommendations (2 DISMISSED)
        for i in range(2):
            ep = _make_episode(
                store=self.episode_store,
                task=f"evening_task_{i}",
                recommendation={"content": f"Evening task adjustment reminder {i}."},
                user_response={"response": RecommendationResult.DISMISSED.value},
                created_at=self.base_time.replace(hour=20) + timedelta(days=i),
            )
            episodes.append(ep)

        patterns = self.engine.discover_interaction_patterns(episodes)
        timing_pat = next((p for p in patterns if "morning" in p.description.lower()), None)
        self.assertIsNotNone(timing_pat)
        self.assertEqual(timing_pat.pattern_type, PatternType.INTERACTION_PATTERN.value)


class TestWorldPatternLearning(unittest.TestCase):
    """Test dynamic learning of World Patterns (environmental rhythms, cross-source coordination)."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_world.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.pattern_store = PatternStore(db_manager=self.db_manager)
        self.engine = LearningEngine(pattern_store=self.pattern_store)
        # Tuesday: 2026-08-11
        self.tuesday_time = datetime(2026, 8, 11, 9, 0, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_weekday_meeting_density_pattern(self) -> None:
        """Verify dynamic discovery of elevated meeting density on specific days."""
        events = []
        for week in range(3):
            tuesday = self.tuesday_time + timedelta(weeks=week)
            for m in range(4):
                events.append(
                    Event(
                        id=f"evt-tues-meeting-{week}-{m}",
                        event_type="calendar_meeting",
                        source="calendar",
                        event_time=tuesday + timedelta(hours=2 * m),
                        payload={"summary": f"Tuesday sync {m}"},
                    )
                )

        patterns = self.engine.discover_world_patterns(events=events)
        self.assertGreater(len(patterns), 0)
        tues_pat = next((p for p in patterns if "tuesdays" in p.description.lower()), None)
        self.assertIsNotNone(tues_pat)
        self.assertEqual(tues_pat.pattern_type, PatternType.WORLD_PATTERN.value)

    def test_drive_doc_preceding_calendar_review_pattern(self) -> None:
        """Verify cross-source coordination pattern between Drive and Calendar."""
        events = []
        for cycle in range(2):
            base_d = self.tuesday_time + timedelta(days=cycle * 7)
            # Drive doc modified on Monday
            d_ev = Event(
                id=f"evt-drive-mod-{cycle}",
                event_type="document_modified",
                source="drive",
                event_time=base_d,
                payload={"title": "architecture_v2.docx modified"},
            )
            # Calendar review on Tuesday (24h later)
            c_ev = Event(
                id=f"evt-cal-review-{cycle}",
                event_type="calendar_event",
                source="calendar",
                event_time=base_d + timedelta(hours=24),
                payload={"title": "Architecture Review sync"},
            )
            events.extend([d_ev, c_ev])

        patterns = self.engine.discover_world_patterns(events=events)
        coord_pat = next((p for p in patterns if "google drive" in p.description.lower() or "review" in p.description.lower()), None)
        self.assertIsNotNone(coord_pat)
        self.assertEqual(coord_pat.pattern_type, PatternType.WORLD_PATTERN.value)


class TestUnifiedMultiSourcePatternLearning(unittest.TestCase):
    """Test unified multi-source learning from observations, episodes, outcomes."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_unified_learning.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.pattern_store = PatternStore(db_manager=self.db_manager)
        self.episode_store = EpisodeStore(db_manager=self.db_manager)
        self.engine = LearningEngine(pattern_store=self.pattern_store)
        self.base_time = datetime(2026, 8, 1, 9, 0, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_unified_learn_patterns_pipeline(self) -> None:
        """Test learn_patterns orchestrator across World, Behavioral, Interaction patterns."""
        events = [
            Event(
                id="evt-sleep-1",
                event_type="sleep_session",
                source="sleep_tracker",
                event_time=self.base_time,
                payload={"duration_minutes": 240},
            ),
            Event(
                id="evt-sleep-2",
                event_type="sleep_session",
                source="sleep_tracker",
                event_time=self.base_time + timedelta(days=1),
                payload={"duration_minutes": 220},
            ),
        ]

        episodes = [
            _make_episode(
                store=self.episode_store,
                task="test_ep_1",
                recommendation={"content": "Specific recovery recommendation to rest early at 21:30."},
                user_response={"response": "ACCEPTED"},
                created_at=self.base_time,
            ),
            _make_episode(
                store=self.episode_store,
                task="test_ep_2",
                recommendation={"content": "Take break."},
                user_response={"response": "DISMISSED"},
                created_at=self.base_time + timedelta(days=1),
            ),
        ]

        results = self.engine.learn_patterns(events=events, episodes=episodes, as_of=self.base_time + timedelta(days=2))

        self.assertIn("world_patterns", results)
        self.assertIn("behavioral_patterns", results)
        self.assertIn("interaction_patterns", results)
        self.assertIn("decayed_patterns", results)

        # Check list_patterns_by_type
        all_behavioral = self.pattern_store.list_patterns_by_type(PatternType.BEHAVIORAL_PATTERN)
        self.assertIsInstance(all_behavioral, list)


if __name__ == "__main__":
    unittest.main()
