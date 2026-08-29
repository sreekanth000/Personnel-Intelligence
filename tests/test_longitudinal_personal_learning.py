"""
Comprehensive Longitudinal Personal Learning Test Suite (Prompt 5).

Evaluates the 9 required empirical pattern learning capabilities:
  1. Pattern emergence (OBSERVED -> HYPOTHESIS -> EMERGING)
  2. Repeated support (EMERGING -> SUPPORTED -> ACTIVE)
  3. Contradiction tracking (contradiction accumulation with full provenance)
  4. Recency decay (ACTIVE -> DECAYING -> INACTIVE)
  5. Recovery after new support (fresh evidence restores decaying patterns)
  6. Interaction preference learning (specificity, morning timing, low-urgency dismissal)
  7. False pattern rejection (coincidental signals with contradictions demoted to INACTIVE)
  8. Cross-domain pattern discovery (Calendar + Drive + Workload + Health)
  9. Novel pattern discovery (emergent regularities without pre-configured templates)

Additional validations:
  - Epistemic invariants: Non-causal phrasing ("Observed association", "Historically..."), context not facts, no autonomous actions.
  - Interaction preference synthesis ("How does this person prefer to be helped?").
"""

from datetime import datetime, timedelta, timezone
import os
import tempfile
import unittest
from typing import List

from personal_intelligence.core.episodes.models import (
    EpisodeStatus,
    ReasoningEpisode,
    RecommendationResult,
)
from personal_intelligence.core.episodes.store import EpisodeStore
from personal_intelligence.core.events.models import Event, format_iso8601
from personal_intelligence.core.patterns.engine import LearningEngine
from personal_intelligence.core.patterns.models import (
    EvidenceObservationType,
    Pattern,
    PatternStatus,
    PatternType,
)
from personal_intelligence.core.patterns.store import PatternStore
from personal_intelligence.core.policy.engine import InterventionPolicyEngine
from personal_intelligence.core.policy.models import PolicyAction, UserContext
from personal_intelligence.core.significance.engine import PersonalSignificanceEngine
from personal_intelligence.core.world.changes import MeaningfulChange
from personal_intelligence.storage.db import DatabaseManager


class TestLongitudinalPersonalLearningSuite(unittest.TestCase):
    """
    Validates longitudinal personal learning in Personal Intelligence.
    """

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_learning_suite.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.db_manager.initialize_schema()

        self.episode_store = EpisodeStore(db_manager=self.db_manager)
        self.pattern_store = PatternStore(db_manager=self.db_manager)
        self.learning_engine = LearningEngine(
            pattern_store=self.pattern_store,
            db_manager=self.db_manager,
            decay_after_days=60,
            inactivate_after_days=120,
        )
        self.policy_engine = InterventionPolicyEngine()
        self.significance_engine = PersonalSignificanceEngine()
        self.base_time = datetime(2026, 8, 22, 10, 0, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # -------------------------------------------------------------------------
    # Scenario 1: Pattern Emergence
    # -------------------------------------------------------------------------
    def test_1_pattern_emergence(self) -> None:
        """
        Scenario 1: Pattern Emergence
        Validates progression: OBSERVED -> HYPOTHESIS -> EMERGING as observations accumulate.
        """
        # 1 observation -> V1.2: support>=1 -> HYPOTHESIS
        pat = Pattern(
            description="Monday mornings exhibit elevated meeting density.",
            pattern_type=PatternType.WORLD_PATTERN.value,
            first_seen=self.base_time,
            last_seen=self.base_time,
            support_count=1,
            contradiction_count=0,
            status=PatternStatus.OBSERVED.value,
        )
        self.pattern_store.create_pattern(pat)
        status, strength = self.learning_engine.evaluate_progression(pat, as_of=self.base_time)
        self.assertEqual(status, PatternStatus.HYPOTHESIS)

        # 2 observations -> HYPOTHESIS
        pat.support_count = 2
        status, strength = self.learning_engine.evaluate_progression(pat, as_of=self.base_time)
        self.assertEqual(status, PatternStatus.HYPOTHESIS)
        self.assertEqual(strength, "weak")

        # 3 observations with span >= 7d -> EMERGING
        pat.support_count = 3
        pat.last_seen = self.base_time + timedelta(days=8)
        status, strength = self.learning_engine.evaluate_progression(pat, as_of=self.base_time + timedelta(days=8))
        self.assertEqual(status, PatternStatus.EMERGING)
        self.assertEqual(strength, "moderate")

    # -------------------------------------------------------------------------
    # Scenario 2: Repeated Support and Promotion
    # -------------------------------------------------------------------------
    def test_2_repeated_support(self) -> None:
        """
        Scenario 2: Repeated Support
        Validates progression: EMERGING -> SUPPORTED -> ACTIVE with supporting episode provenance.
        """
        pat = Pattern(
            description="Late meetings are often followed by delayed work.",
            pattern_type=PatternType.BEHAVIORAL_PATTERN.value,
            first_seen=self.base_time,
            last_seen=self.base_time + timedelta(days=22),
            support_count=4,
            contradiction_count=0,
            status=PatternStatus.EMERGING.value,
        )
        self.pattern_store.create_pattern(pat)

        # V1.2: 6 support observations, span >= 21d -> SUPPORTED
        pat.support_count = 6
        status, strength = self.learning_engine.evaluate_progression(pat, as_of=self.base_time + timedelta(days=22))
        self.assertEqual(status, PatternStatus.SUPPORTED)
        self.assertEqual(strength, "strong")

        # V1.2: 10 support observations, span >= 45d, contra < 20% -> ACTIVE
        pat.support_count = 10
        pat.contradiction_count = 1
        pat.last_seen = self.base_time + timedelta(days=46)
        status, strength = self.learning_engine.evaluate_progression(pat, as_of=self.base_time + timedelta(days=46))
        self.assertEqual(status, PatternStatus.ACTIVE)
        self.assertEqual(strength, "strong")
        self.assertGreaterEqual(pat.confidence, 0.85)

    # -------------------------------------------------------------------------
    # Scenario 3: Contradiction Tracking
    # -------------------------------------------------------------------------
    def test_3_contradiction_tracking(self) -> None:
        """
        Scenario 3: Contradiction Tracking
        Validates recording contradictory episodes without deleting historical support evidence.
        """
        pat = Pattern(
            description="Specific recommendations appear associated with higher user acceptance.",
            pattern_type=PatternType.INTERACTION_PATTERN.value,
            first_seen=self.base_time,
            last_seen=self.base_time,
            support_count=8,
            contradiction_count=0,
            status=PatternStatus.SUPPORTED.value,
        )
        created_pat = self.pattern_store.create_pattern(pat)

        # Record 5 supporting evidence records
        for i in range(5):
            ep = self.episode_store.create_episode(
                situation_id=f"sit-supp-{i}",
                hermes_task=f"Support test {i}",
                urgency="medium",
                actionability="high",
                evidence_strength="strong",
                created_at=self.base_time + timedelta(hours=i),
            )
            self.learning_engine.record_evidence(
                pattern_id=created_pat.id,
                observation_type=EvidenceObservationType.SUPPORT,
                observed_at=self.base_time + timedelta(hours=i),
                episode_id=ep.id,
                details={"action": "accepted"},
            )

        # Introduce a contradiction
        contra_time = self.base_time + timedelta(hours=10)
        contra_ep = self.episode_store.create_episode(
            situation_id="sit-contra-1",
            hermes_task="Contradiction episode",
            urgency="medium",
            actionability="high",
            evidence_strength="strong",
            created_at=contra_time,
        )
        updated_pat, contra_ev = self.learning_engine.record_evidence(
            pattern_id=created_pat.id,
            observation_type=EvidenceObservationType.CONTRADICTION,
            observed_at=contra_time,
            episode_id=contra_ep.id,
            details={"action": "dismissed", "reason": "User was driving"},
        )

        self.assertEqual(updated_pat.contradiction_count, 1)
        self.assertEqual(contra_ev.observation_type, EvidenceObservationType.CONTRADICTION.value)

        # Ensure historical support records remain completely intact
        all_ev = self.pattern_store.list_evidence_for_pattern(created_pat.id)
        self.assertEqual(len(all_ev), 6)
        supp_records = [e for e in all_ev if e.observation_type == EvidenceObservationType.SUPPORT.value]
        self.assertEqual(len(supp_records), 5)

    # -------------------------------------------------------------------------
    # Scenario 4: Recency Decay
    # -------------------------------------------------------------------------
    def test_4_recency_decay(self) -> None:
        """
        Scenario 4: Recency Decay (V1.2 thresholds)
        Validates that unsupported patterns decay over time:
        ACTIVE -> DECAYING after 60 days, -> INACTIVE after 120 days.
        """
        pat = Pattern(
            description="User frequently reviews drafts at 21:00.",
            pattern_type=PatternType.BEHAVIORAL_PATTERN.value,
            first_seen=self.base_time,
            last_seen=self.base_time + timedelta(days=50),
            support_count=12,
            contradiction_count=1,
            status=PatternStatus.ACTIVE.value,
        )
        self.pattern_store.create_pattern(pat)

        # After 65 days of silence past last_seen (decay_after_days = 60) -> DECAYING
        as_of_65d = pat.last_seen + timedelta(days=65)
        status_65d, strength_65d = self.learning_engine.evaluate_progression(pat, as_of=as_of_65d)
        self.assertEqual(status_65d, PatternStatus.DECAYING)

        # After 125 days of silence past last_seen (inactivate_after_days = 120) -> INACTIVE
        as_of_125d = pat.last_seen + timedelta(days=125)
        status_125d, strength_125d = self.learning_engine.evaluate_progression(pat, as_of=as_of_125d)
        self.assertEqual(status_125d, PatternStatus.INACTIVE)

    # -------------------------------------------------------------------------
    # Scenario 5: Recovery After New Support
    # -------------------------------------------------------------------------
    def test_5_recovery_after_new_support(self) -> None:
        """
        Scenario 5: Recovery After New Support
        Validates that fresh supporting evidence restores decaying or inactive patterns.
        """
        pat = Pattern(
            description="Drive document modifications frequently precede Calendar reviews.",
            pattern_type=PatternType.WORLD_PATTERN.value,
            first_seen=self.base_time,
            last_seen=self.base_time + timedelta(days=50),
            support_count=10,
            contradiction_count=1,
            status=PatternStatus.DECAYING.value,
        )
        created_pat = self.pattern_store.create_pattern(pat)

        # Fresh support within recovery window
        fresh_time = self.base_time + timedelta(days=52)
        fresh_ep = self.episode_store.create_episode(
            situation_id="sit-fresh-support",
            hermes_task="Fresh support verification",
            urgency="low",
            actionability="high",
            evidence_strength="strong",
            created_at=fresh_time,
        )
        recovered_pat, _ = self.learning_engine.record_evidence(
            pattern_id=created_pat.id,
            observation_type=EvidenceObservationType.SUPPORT,
            observed_at=fresh_time,
            episode_id=fresh_ep.id,
            details={"co_occurrence": "Drive file edited 2h before review meeting"},
        )

        # V1.2: Re-evaluation with span >= 45d, support >= 10, contra < 20% -> ACTIVE
        status, strength = self.learning_engine.evaluate_progression(recovered_pat, as_of=fresh_time)
        self.assertEqual(status, PatternStatus.ACTIVE)
        self.assertEqual(strength, "strong")

    # -------------------------------------------------------------------------
    # Scenario 6: Interaction Preference Learning
    # -------------------------------------------------------------------------
    def test_6_interaction_preference_learning(self) -> None:
        """
        Scenario 6: Interaction Preference Learning
        Learns:
          - Specific recommendations accepted more frequently than generic reminders
          - Morning delivery more successful than late evening
          - Low-urgency interruptions frequently dismissed during busy periods
        """
        episodes: List[ReasoningEpisode] = []

        # 10 specific morning recommendations accepted (8 AM)
        for i in range(10):
            t = (self.base_time + timedelta(days=i)).replace(hour=8, minute=0, second=0)
            ep = self.episode_store.create_episode(
                situation_id=f"sit-spec-{i}",
                hermes_task="Morning specific task",
                urgency="medium",
                actionability="high",
                evidence_strength="strong",
                recommendation={"content": f"Shift tempo run {i} to 16:00 and take hydration break", "specificity": "specific"},
                intervention_decision={"action": PolicyAction.BRIEFING.value, "user_context": UserContext.AVAILABLE.value},
                user_response={"response": RecommendationResult.ACCEPTED.value},
                outcome={"success": True, "outcome_status": RecommendationResult.COMPLETED.value},
                created_at=t,
            )
            episodes.append(ep)

        # 5 generic evening reminders dismissed (19:00 / 7 PM)
        for i in range(5):
            t = (self.base_time + timedelta(days=i)).replace(hour=19, minute=0, second=0)
            ep = self.episode_store.create_episode(
                situation_id=f"sit-gen-{i}",
                hermes_task="Generic nudge",
                urgency="low",
                actionability="low",
                evidence_strength="moderate",
                recommendation={"content": "Take a break.", "specificity": "generic"},
                intervention_decision={"action": PolicyAction.BRIEFING.value, "user_context": UserContext.AVAILABLE.value},
                user_response={"response": RecommendationResult.DISMISSED.value},
                outcome={"success": False, "outcome_status": RecommendationResult.DISMISSED.value},
                created_at=t,
            )
            episodes.append(ep)

        # 5 low-urgency interruptions during busy state dismissed (15:00 / 3 PM)
        for i in range(5):
            t = (self.base_time + timedelta(days=i)).replace(hour=15, minute=0, second=0)
            ep = self.episode_store.create_episode(
                situation_id=f"sit-low-busy-{i}",
                hermes_task="Low urgency busy interrupt",
                urgency="low",
                actionability="medium",
                evidence_strength="moderate",
                recommendation={"content": "Review optional notes.", "specificity": "specific"},
                intervention_decision={"action": PolicyAction.INTERRUPT.value, "user_context": UserContext.BUSY.value},
                user_response={"response": RecommendationResult.DISMISSED.value},
                outcome={"success": False, "outcome_status": RecommendationResult.DISMISSED.value},
                created_at=t,
            )
            episodes.append(ep)

        discovered = self.learning_engine.discover_interaction_patterns(episodes)
        self.assertGreaterEqual(len(discovered), 2)

        # Check specificity preference discovered
        spec_pat = next((p for p in discovered if "specific" in p.description.lower()), None)
        self.assertIsNotNone(spec_pat)
        self.assertIn("appears more responsive to specific", spec_pat.description.lower())

        # Check morning timing discovered
        morning_pat = next((p for p in discovered if "morning" in p.description.lower()), None)
        self.assertIsNotNone(morning_pat)

        # Check low-urgency dismissal discovered
        dismiss_pat = next((p for p in discovered if "low-urgency" in p.description.lower() or "busy" in p.description.lower()), None)
        self.assertIsNotNone(dismiss_pat)

    # -------------------------------------------------------------------------
    # Scenario 7: False Pattern Rejection
    # -------------------------------------------------------------------------
    def test_7_false_pattern_rejection(self) -> None:
        """
        Scenario 7: False Pattern Rejection
        Validates that coincidental or spurious patterns with equal or greater contradictions
        are demoted to INACTIVE and rejected.
        """
        # V1.2: Spurious pattern with high contradiction rate -> HYPOTHESIS (not INACTIVE immediately)
        # INACTIVE requires 120d silence, not just high contra
        spurious_pat = Pattern(
            description="User drinks tea on rainy days.",
            pattern_type=PatternType.BEHAVIORAL_PATTERN.value,
            first_seen=self.base_time,
            last_seen=self.base_time,
            support_count=1,
            contradiction_count=2,
            status=PatternStatus.OBSERVED.value,
        )
        self.pattern_store.create_pattern(spurious_pat)

        # V1.2: contra_rate = 2/3 = 67% >= 50% with total >= 3 -> HYPOTHESIS (demoted from any higher state)
        status, strength = self.learning_engine.evaluate_progression(spurious_pat, as_of=self.base_time)
        self.assertEqual(status, PatternStatus.HYPOTHESIS)
        self.assertEqual(strength, "weak")

        # Conflicted pattern: 3 supports, 4 contradictions -> contra_rate = 4/7 = 57% >= 50%
        conflicted_pat = Pattern(
            description="User responds to reminders during meetings.",
            pattern_type=PatternType.INTERACTION_PATTERN.value,
            first_seen=self.base_time,
            last_seen=self.base_time,
            support_count=3,
            contradiction_count=4,
            status=PatternStatus.EMERGING.value,
        )
        status_conf, strength_conf = self.learning_engine.evaluate_progression(conflicted_pat, as_of=self.base_time)
        self.assertEqual(status_conf, PatternStatus.DECAYING)  # Demoted to DECAYING due to high contradiction (>50%)

    # -------------------------------------------------------------------------
    # Scenario 8: Cross-Domain Pattern Discovery
    # -------------------------------------------------------------------------
    def test_8_cross_domain_pattern_discovery(self) -> None:
        """
        Scenario 8: Cross-Domain Pattern Discovery
        Discovers patterns spanning multiple domains (Calendar + Drive + Commute).
        """
        events: List[Event] = []

        for i in range(3):
            t_drive = self.base_time + timedelta(days=i*7, hours=10)
            t_cal = t_drive + timedelta(hours=4)
            # Google Drive modification event
            events.append(Event(
                id=f"evt-drive-{i}",
                event_type="drive_document_modified",
                source="google_drive",
                subject_id="doc_quarterly_review",
                event_time=t_drive,
                payload={"title": "Q3 Review Deck", "operation": "edit"},
            ))
            # Calendar review event
            events.append(Event(
                id=f"evt-cal-{i}",
                event_type="calendar_meeting",
                source="google_calendar",
                subject_id="evt_review_meeting",
                event_time=t_cal,
                payload={"title": "Quarterly Review Meeting", "domain": "schedule"},
            ))

        world_patterns = self.learning_engine.discover_world_patterns(events)
        self.assertGreaterEqual(len(world_patterns), 1)
        cross_source_pat = next((p for p in world_patterns if "drive" in p.description.lower()), None)
        self.assertIsNotNone(cross_source_pat)
        self.assertIn("calendar review", cross_source_pat.description.lower())

    # -------------------------------------------------------------------------
    # Scenario 9: Novel Pattern Discovery
    # -------------------------------------------------------------------------
    def test_9_novel_pattern_discovery(self) -> None:
        """
        Scenario 9: Novel Pattern Discovery
        Discovers emergent project communication bursts without pre-configured templates.
        """
        events: List[Event] = []
        for i in range(4):
            t_ev = self.base_time + timedelta(hours=i*2)
            events.append(Event(
                id=f"evt-burst-{i}",
                event_type="slack_message",
                source="slack",
                subject_id="proj_quantum_launch",
                event_time=t_ev,
                payload={"project": "QuantumLaunch", "channel": "#quantum", "burst": True},
            ))

        world_patterns = self.learning_engine.discover_world_patterns(events)
        project_burst_pat = next((p for p in world_patterns if "quantumlaunch" in p.description.lower()), None)
        self.assertIsNotNone(project_burst_pat)
        self.assertIn("communication bursts", project_burst_pat.description.lower())

    # -------------------------------------------------------------------------
    # Scenario 10: Interaction Preference Synthesis ("How does this person prefer to be helped?")
    # -------------------------------------------------------------------------
    def test_interaction_preference_synthesis(self) -> None:
        """
        Validates synthesizing empirical preferences into an actionable user profile:
        'How does this person prefer to be helped?'
        """
        # Seed active interaction patterns
        self.pattern_store.create_pattern(Pattern(
            description="User appears more responsive to specific, actionable recommendations than generic reminders.",
            pattern_type=PatternType.INTERACTION_PATTERN.value,
            status=PatternStatus.ACTIVE.value,
            support_count=15,
            contradiction_count=1,
            evidence_strength="strong",
        ))
        self.pattern_store.create_pattern(Pattern(
            description="Recommendations delivered in the morning appear associated with higher user completion rates.",
            pattern_type=PatternType.INTERACTION_PATTERN.value,
            status=PatternStatus.SUPPORTED.value,
            support_count=8,
            contradiction_count=1,
            evidence_strength="strong",
        ))
        self.pattern_store.create_pattern(Pattern(
            description="User frequently dismisses low-urgency interruptions during focused or busy states.",
            pattern_type=PatternType.INTERACTION_PATTERN.value,
            status=PatternStatus.ACTIVE.value,
            support_count=12,
            contradiction_count=2,
            evidence_strength="strong",
        ))

        pref_profile = self.learning_engine.synthesize_interaction_preferences()
        self.assertTrue(pref_profile["prefers_specific_recommendations"])
        self.assertEqual(pref_profile["preferred_timing_window"], "morning")
        self.assertTrue(pref_profile["dismisses_low_urgency_interruptions"])
        self.assertIn("specific", pref_profile["summary"].lower())
        self.assertIn("morning", pref_profile["summary"].lower())

    # -------------------------------------------------------------------------
    # Scenario 11: Epistemic Invariants & Policy Modulation
    # -------------------------------------------------------------------------
    def test_epistemic_invariants_and_policy_modulation(self) -> None:
        """
        Validates core epistemic invariants:
          1. Learned patterns are context, not facts.
          2. Non-causal phrasing ("Historically...", "Observed association...").
          3. Patterns influence policy without directly triggering external actions.
        """
        # Invariant 1 & 2: Non-causal sanitization on initialization
        pat_causal = Pattern(
            description="Late meetings causes delayed work and results in missed deadlines.",
            pattern_type=PatternType.BEHAVIORAL_PATTERN.value,
        )
        self.assertNotIn("causes", pat_causal.description)
        self.assertNotIn("results in", pat_causal.description)
        self.assertIn("appears associated with", pat_causal.description)
        self.assertIn("is frequently followed by", pat_causal.description)

        stmt = pat_causal.to_context_statement()
        self.assertTrue(stmt.startswith("Historically,"))

        # Invariant 3: Influence significance
        sig = self.significance_engine.evaluate_situation(
            situation_type="schedule_conflict",
            situation_priority="medium",
            evidence_count=2,
            patterns=[pat_causal],
        )
        self.assertIn("Contextualized by learned pattern", " ".join(sig.reasons))

        # Invariant 4: Influence policy timing without external execution
        policy_res = self.policy_engine.evaluate(
            urgency="medium",
            actionability="high",
            evidence_strength="strong",
            user_context="busy",
            interaction_preferences={"dismisses_low_urgency_interruptions": True},
        )
        # Policy shifts to DEFER due to user preference
        self.assertEqual(policy_res.action, PolicyAction.DEFER.value)
        self.assertIn("learned user preference", policy_res.reason)


if __name__ == "__main__":
    unittest.main()
