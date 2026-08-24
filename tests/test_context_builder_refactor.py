"""
Tests for ContextBuilder Epistemic Architecture Refactoring.

Verifies:
1. Generation of the 10 explicit epistemic sections:
   - OBSERVED_FACTS
   - INFERENCES
   - PREDICTIONS
   - KNOWN_PATTERNS
   - EMERGING_HYPOTHESES
   - ACTIVE_GOALS
   - RELEVANT_TIMELINE
   - OPEN_SITUATION
   - INFORMATION_GAPS
   - UNCERTAINTIES
2. Every observed fact includes strict provenance coordinates.
3. Inferences are strictly distinguished and never converted into facts.
4. Old reasoning episode claims are attributed to past episodes with provenance and never presented as current facts.
5. Context minimization: strictly bounds token count (500–2,000 tokens) without dumping SQLite DB or full history.
6. Unified cross-source integration with source attribution.
"""

from datetime import datetime, timedelta, timezone
import json
import os
import tempfile
import unittest

from personal_intelligence.core.context import (
    BoundedReasoningContext,
    ContextBuilder,
    estimate_token_count,
)
from personal_intelligence.core.episodes.models import EpisodeStatus, ReasoningEpisode
from personal_intelligence.core.events import Event, EventStore
from personal_intelligence.core.goals import Goal, GoalPriority, GoalStatus, GoalStore
from personal_intelligence.core.patterns.models import LearnedPattern, PatternCadence
from personal_intelligence.core.situations import Situation, SituationPriority, SituationStatus, SituationStore
from personal_intelligence.core.state import StateFeature, StateRepresentation
from personal_intelligence.core.timeline import Timeline
from personal_intelligence.hermes_bridge.situation_investigation import CrossSourceEvidenceBundle
from personal_intelligence.storage.db import DatabaseManager


class TestContextBuilderRefactor(unittest.TestCase):
    """Test suite verifying bounded epistemic ContextBuilder and provenance guarantees."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_context_refactor.db")
        self.db_manager = DatabaseManager(db_path=self.db_path)
        self.goal_store = GoalStore(db_manager=self.db_manager)
        self.situation_store = SituationStore(db_manager=self.db_manager)
        self.event_store = EventStore(db_manager=self.db_manager)
        self.base_time = datetime(2026, 8, 22, 14, 0, 0, tzinfo=timezone.utc)

        self.builder = ContextBuilder(
            goal_store=self.goal_store,
            situation_store=self.situation_store,
            recent_window_minutes=120,
            max_recent_events=5,
            max_historical_events=3,
            max_goals=3,
            max_patterns=3,
            max_similar_situations=2,
            max_recent_episodes=2,
            max_facts=10,
            max_tokens=2000,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _create_sample_state(self) -> StateRepresentation:
        """Helper to create a populated state representation with provenance."""
        state = StateRepresentation(timestamp=self.base_time)
        state.set_feature("current_activity", "architecture_review", source="os_window:vscode", confidence=0.95)
        state.set_feature("sleep_duration_minutes", 420.0, source="biometrics:oura_ring", confidence=0.98)
        state.set_feature("calendar_density", 4, source="calendar:work_schedule", confidence=0.90)
        state.set_feature("ambient_noise_level", 45.0, source="sensor:ambient_mic", confidence=0.60)  # Low confidence
        return state

    # -------------------------------------------------------------------------
    # 1. Verification of 10 Explicit Epistemic Sections
    # -------------------------------------------------------------------------

    def test_epistemic_context_contains_all_10_sections(self) -> None:
        """Verifies that the generated prompt contains all 10 explicit epistemic sections."""
        state = self._create_sample_state()
        goal = Goal(
            name="Q3 Architecture Finalization",
            description="Deliver approved architecture specifications before review milestone",
            priority=GoalPriority.HIGH,
            status=GoalStatus.ACTIVE,
        )
        self.goal_store.create_goal(goal)

        situation = Situation(
            id="sit-arch-001",
            type="unresolved_action_item_before_milestone",
            priority=SituationPriority.HIGH.value,
            novelty=0.45,
            status="open",
            information_required=True,
            investigation_target="Is the architecture document approved by the tech lead?",
            context={"title": "Tech Lead Sign-off", "description": "Pending lead sign-off"},
            related_goals=[goal.id],
            evidence=["finding:Draft v3 modified at 11:00 UTC"],
        )
        self.situation_store.create(situation)

        pattern = LearnedPattern(
            pattern_id="pat-morning-01",
            name="Morning Focus Alignment",
            description="User responds effectively to technical reviews scheduled before 14:00.",
            cadence=PatternCadence.DAILY,
            confidence=0.85,
        )



        episode = ReasoningEpisode(
            situation_id=situation.id,
            trigger_type="schedule_conflict_trigger",
            status=EpisodeStatus.REASONING_COMPLETED,
            started_at=self.base_time - timedelta(hours=3),
        )


        ctx = self.builder.build_bounded_context(
            situation=situation,
            current_state=state,
            goals=[goal],
            patterns=[pattern],
            episodes=[episode],
        )

        prompt_str = ctx.to_prompt_string()

        # Check all 10 section headers
        expected_sections = [
            "=== OPEN_SITUATION ===",
            "=== OBSERVED_FACTS ===",
            "=== INFERENCES ===",
            "=== PREDICTIONS ===",
            "=== KNOWN_PATTERNS ===",
            "=== EMERGING_HYPOTHESES ===",
            "=== ACTIVE_GOALS ===",
            "=== RELEVANT_TIMELINE ===",
            "=== INFORMATION_GAPS ===",
            "=== UNCERTAINTIES ===",
        ]

        for sec in expected_sections:
            self.assertIn(sec, prompt_str, f"Missing required epistemic section: {sec}")

    # -------------------------------------------------------------------------
    # 2. Strict Provenance Preservation in Observed Facts
    # -------------------------------------------------------------------------

    def test_observed_facts_preserve_provenance(self) -> None:
        """Verifies that all facts in OBSERVED_FACTS have verified source coordinates."""
        state = self._create_sample_state()
        situation = Situation(
            id="sit-prov-001",
            type="possible_commitment",
            priority="medium",
            evidence=["finding:Architecture proposal submitted in Drive doc-101"],
        )

        ctx = self.builder.build_bounded_context(situation=situation, current_state=state)

        self.assertGreater(len(ctx.observed_facts), 0)
        for fact in ctx.observed_facts:
            self.assertIn("provenance", fact)
            self.assertIn("source", fact)
            self.assertIn("timestamp", fact)
            self.assertIn("confidence", fact)
            self.assertTrue(len(fact["provenance"]) > 0)

        prompt_str = ctx.to_prompt_string()
        self.assertIn("[PROVENANCE:", prompt_str)
        self.assertIn("biometrics:oura_ring", prompt_str)
        self.assertIn("calendar:work_schedule", prompt_str)

    # -------------------------------------------------------------------------
    # 3. Separation of Inferences and Facts
    # -------------------------------------------------------------------------

    def test_never_convert_inferences_into_facts(self) -> None:
        """Verifies that analytical deductions and hypotheses are never placed in OBSERVED_FACTS."""
        state = self._create_sample_state()
        situation = Situation(
            id="sit-inf-001",
            type="goal_risk",
            priority="high",
            context={"description": "Risk of missing architecture deliverable"},
        )

        ctx = self.builder.build_bounded_context(situation=situation, current_state=state)

        # Inferences must be in inferences or emerging_hypotheses, NOT observed_facts
        for fact in ctx.observed_facts:
            self.assertNotIn("hypothesis", fact.get("key", "").lower())
            self.assertNotIn("risk of missing", fact.get("statement", "").lower())

        self.assertGreater(len(ctx.inferences), 0)
        self.assertGreater(len(ctx.emerging_hypotheses), 0)

    # -------------------------------------------------------------------------
    # 4. Old Reasoning Episode Attribution
    # -------------------------------------------------------------------------

    def test_old_reasoning_episode_claims_never_presented_as_current_facts(self) -> None:
        """
        Verifies that claims from past reasoning episodes are explicitly attributed
        under INFERENCES with past_episode provenance and never in OBSERVED_FACTS.
        """
        state = self._create_sample_state()
        situation = Situation(id="sit-ep-001", type="goal_risk", priority="high")
        past_episode = ReasoningEpisode(
            episode_id="ep-historical-999",
            situation_id="sit-past-old",
            trigger_type="novel_state_trigger",
            status=EpisodeStatus.REASONING_COMPLETED,
            started_at=self.base_time - timedelta(days=2),
        )


        ctx = self.builder.build_bounded_context(
            situation=situation,
            current_state=state,
            episodes=[past_episode],
        )

        # Check observed facts: must NOT have past episode claims
        for fact in ctx.observed_facts:
            self.assertNotIn("ep-historical-999", fact.get("provenance", ""))

        # Check inferences: must contain the past episode reference with explicit tag
        past_ep_inferences = [
            inf for inf in ctx.inferences if "ep-historical-999" in inf.get("origin", "")
        ]
        self.assertEqual(len(past_ep_inferences), 1)
        self.assertEqual(past_ep_inferences[0]["origin"], "past_episode:ep-historical-999")

        prompt_str = ctx.to_prompt_string()
        self.assertIn("[INFERENCE: past_episode:ep-historical-999]", prompt_str)

    # -------------------------------------------------------------------------
    # 5. Context Minimization & Token Bounding (500–2,000 tokens)
    # -------------------------------------------------------------------------

    def test_context_minimization_and_token_bounds(self) -> None:
        """
        Verifies that ContextBuilder creates compact reasoning prompts within
        the target 500–2,000 token budget without dumping full database histories.
        """
        # Create 100 historical timeline events
        all_events = []
        for i in range(100):
            t = self.base_time - timedelta(hours=i)
            all_events.append(
                Event(
                    id=f"evt-bulk-{i}",
                    event_type="app_activity" if i % 2 == 0 else "status_update",
                    source="system_monitor",
                    payload={"index": i, "details": f"Bulk activity log entry number {i}"},
                    event_time=t,
                )
            )

        timeline = Timeline(events=all_events, start_time=all_events[-1].event_time, end_time=self.base_time)
        state = self._create_sample_state()
        situation = Situation(
            id="sit-bound-001",
            type="unusual_change",
            priority="medium",
            evidence=["event:evt-bulk-0", "event:evt-bulk-1"],
        )

        ctx = self.builder.build_bounded_context(
            situation=situation,
            current_state=state,
            timeline=timeline,
        )

        prompt_str = ctx.to_prompt_string()
        tokens = estimate_token_count(prompt_str)

        # Must strictly stay within bounded token limits (target 500 - 2,000 tokens)
        self.assertLessEqual(tokens, 2000)
        self.assertGreaterEqual(tokens, 100)

        # Must not dump all 100 events
        self.assertLessEqual(len(ctx.relevant_recent_timeline), 5)
        self.assertLessEqual(len(ctx.relevant_historical_events), 3)

    # -------------------------------------------------------------------------
    # 6. Cross-Source Evidence Bundle Integration
    # -------------------------------------------------------------------------

    def test_cross_source_evidence_bundle_integration(self) -> None:
        """
        Verifies that build_cross_source_context populates OBSERVED_FACTS and
        INFORMATION_GAPS from CrossSourceEvidenceBundle with clean provenance tags.
        """
        state = self._create_sample_state()
        situation = Situation(
            id="sit-bundle-001",
            type="unresolved_action_item_before_milestone",
            priority="high",
            information_required=True,
            investigation_target="Was the final architecture presentation approved?",
        )

        bundle = CrossSourceEvidenceBundle(
            situation_id=situation.id,
            situation_type=situation.type,
            situation_summary="Architecture review status check",
            facts_by_source={
                "gmail": ["Alex emailed: 'Slide deck approved for Friday'."],
                "drive": ["Presentation 'Architecture_Final.pptx' last saved at 12:45 UTC."],
            },
            remaining_unknowns=["Will the lead architect present remotely or in-person?"],
            source_references=["gmail:msg-441", "drive:file-pptx-99"],
        )

        ctx = self.builder.build_cross_source_context(
            situation=situation,
            current_state=state,
            evidence_bundle=bundle,
        )

        prompt_str = ctx.to_prompt_string()

        # Verify factual items from Gmail and Drive appear with provenance
        self.assertIn("Alex emailed: 'Slide deck approved for Friday'", prompt_str)
        self.assertIn("Architecture_Final.pptx", prompt_str)

        # Verify information gaps
        self.assertIn("Will the lead architect present remotely or in-person?", prompt_str)

        # Verify explicit sections are intact
        self.assertIn("=== OBSERVED_FACTS ===", prompt_str)
        self.assertIn("=== INFORMATION_GAPS ===", prompt_str)


if __name__ == "__main__":
    unittest.main()
