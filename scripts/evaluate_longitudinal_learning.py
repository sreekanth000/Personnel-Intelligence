"""
Synthetic Longitudinal Evaluation for Personal Intelligence.

Generates 120+ synthetic reasoning episodes across 60 days with:
- specific vs generic recommendations
- intervention decisions
- longitudinal user responses & outcomes
- timing & message specificity

Evaluates:
- Discovery of empirical interaction patterns without hardcoded rules
- Non-causal association semantics
- Evidence accumulation & contradiction tracking
- Confidence & evidence strength categorization
- 7-stage pattern lifecycle progression
- Recency decay and recovery
- Full episode provenance chains
"""

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import random
import sys
import tempfile
from typing import Any, Dict, List, Tuple

# Ensure workspace root is in sys.path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from personal_intelligence.core.episodes.models import (
    EpisodeStatus,
    ReasoningEpisode,
    RecommendationResult,
)
from personal_intelligence.core.episodes.store import EpisodeStore
from personal_intelligence.core.events.models import format_iso8601
from personal_intelligence.core.patterns.engine import LearningEngine
from personal_intelligence.core.patterns.models import (
    EvidenceObservationType,
    Pattern,
    PatternStatus,
)
from personal_intelligence.core.patterns.store import PatternStore
from personal_intelligence.core.policy.models import PolicyAction, UserContext
from personal_intelligence.storage.db import DatabaseManager


def generate_longitudinal_episodes(
    base_time: datetime,
    total_episodes: int = 120,
    seed: int = 42,
) -> List[ReasoningEpisode]:
    """
    Generates 120+ longitudinal reasoning episodes over a 60-day window.
    Synthetic behavioral distribution:
    - Specific contextual recommendations (60% of total): ~80% acceptance rate
    - Generic reminders (40% of total): ~20% acceptance rate
    Contradictory evidence is naturally present in both groups.
    """
    rng = random.Random(seed)
    episodes: List[ReasoningEpisode] = []

    specific_templates = [
        ("Shift today's 10km tempo run to tomorrow at 16:00 and substitute a 20-minute restorative walk now.", "fitness_recovery"),
        ("Block 45 minutes of focus time before your 14:00 Executive Review to prepare slide deck notes.", "calendar_preparation"),
        ("Leave by 17:15 via Route 9 to avoid a 25-minute highway delay and catch the 18:00 express train.", "commute_transit"),
        ("Hydrate with 500ml water and take a 10-minute posture break after 120 minutes of continuous coding.", "ergonomics_health"),
        ("Reschedule your 16:30 sync to Friday morning to protect recovery after fragmented 4-hour sleep.", "workload_strain"),
    ]

    generic_templates = [
        ("Take a break.", "generic_nudge"),
        ("Check your calendar.", "generic_reminder"),
        ("Remember your workout today.", "generic_nudge"),
        ("Stay focused and drink water.", "generic_reminder"),
        ("Review upcoming tasks.", "generic_nudge"),
    ]

    for i in range(total_episodes):
        day_offset = int((i / total_episodes) * 60)  # Spanned over 60 days
        hour = rng.choice([8, 9, 11, 14, 16, 17, 19, 21])
        minute = rng.randint(0, 59)
        ep_time = (base_time - timedelta(days=60 - day_offset)).replace(hour=hour, minute=minute, second=0, microsecond=0)

        is_specific = (i % 5 != 0 and i % 5 != 1)  # 60% specific, 40% generic

        if is_specific:
            rec_text, rec_domain = specific_templates[i % len(specific_templates)]
            # ~80% positive response, ~20% negative/contradictory
            is_positive = (rng.random() < 0.80)
            rec_dict = {"content": rec_text, "specificity": "specific", "domain": rec_domain}
            urgency = "high" if "strain" in rec_domain or "transit" in rec_domain else "medium"
        else:
            rec_text, rec_domain = generic_templates[i % len(generic_templates)]
            # ~20% positive response, ~80% negative/contradictory
            is_positive = (rng.random() < 0.20)
            rec_dict = {"content": rec_text, "specificity": "generic", "domain": rec_domain}
            urgency = "low"

        # Assign user response & outcome based on behavioral distribution
        if is_positive:
            user_resp_val = rng.choice([RecommendationResult.ACCEPTED.value, RecommendationResult.COMPLETED.value])
            outcome_status_val = RecommendationResult.COMPLETED.value
            outcome_success = True
        else:
            user_resp_val = rng.choice([RecommendationResult.DISMISSED.value, RecommendationResult.IGNORED.value])
            outcome_status_val = RecommendationResult.DISMISSED.value
            outcome_success = False

        user_context_val = UserContext.AVAILABLE.value if hour in (8, 9, 17, 19) else UserContext.BUSY.value
        action_val = PolicyAction.INTERRUPT.value if urgency == "high" and user_context_val == UserContext.AVAILABLE.value else PolicyAction.BRIEFING.value

        ep = ReasoningEpisode(
            episode_id=f"ep-longitudinal-{i+1:03d}",
            situation_id=f"sit-synthetic-{i+1:03d}",
            hermes_task=f"Evaluation for {rec_domain}",
            urgency=urgency,
            actionability="high" if is_specific else "low",
            relevance="high",
            evidence_strength="strong" if is_specific else "moderate",
            recommendation=rec_dict,
            intervention_decision={
                "action": action_val,
                "user_context": user_context_val,
                "urgency": urgency,
            },
            user_response={
                "response": user_resp_val,
                "recorded_at": format_iso8601(ep_time + timedelta(minutes=5)),
            },
            outcome={
                "outcome_status": outcome_status_val,
                "success": outcome_success,
                "evaluation": f"User {user_resp_val.lower()} recommendation.",
                "recorded_at": format_iso8601(ep_time + timedelta(hours=2)),
            },
            status=EpisodeStatus.REASONING_COMPLETED.value,
            created_at=ep_time,
            ended_at=ep_time + timedelta(minutes=2),
        )
        episodes.append(ep)

    return episodes


def run_longitudinal_evaluation():
    print("=" * 80)
    print("PERSONAL INTELLIGENCE: SYNTHETIC LONGITUDINAL PATTERN LEARNING EVALUATION")
    print("=" * 80)
    print("Evaluating empirical discovery over 120+ longitudinal episodes across 60 days.")
    print("Testing: Evidence Accumulation, Contradiction Tracking, Lifecycle, Decay, Provenance.")
    print("-" * 80)

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "pi_eval.db")
        db_manager = DatabaseManager(db_path=db_path)
        db_manager.initialize_schema()

        episode_store = EpisodeStore(db_manager=db_manager)
        pattern_store = PatternStore(db_manager=db_manager)
        learning_engine = LearningEngine(
            pattern_store=pattern_store,
            db_manager=db_manager,
            decay_after_days=14,
            inactivate_after_days=45,
        )

        base_time = datetime(2026, 8, 22, 12, 0, 0, tzinfo=timezone.utc)

        # ---------------------------------------------------------
        # Step 1: Generate & Ingest 120 Longitudinal Episodes
        # ---------------------------------------------------------
        episodes = generate_longitudinal_episodes(base_time=base_time, total_episodes=120)
        for ep in episodes:
            episode_store.create_episode(
                situation_id=ep.situation_id,
                hermes_task=ep.hermes_task,
                urgency=ep.urgency,
                actionability=ep.actionability,
                evidence_strength=ep.evidence_strength,
                recommendation=ep.recommendation,
                intervention_decision=ep.intervention_decision,
                user_response=ep.user_response,
                outcome=ep.outcome,
                created_at=ep.created_at,
                episode_id=ep.id,
            )

        print(f"\n[1] LONGITUDINAL DATASET INGESTED:")
        print(f"    - Total Episodes: {len(episodes)} over 60 days ({episodes[0].created_at.strftime('%Y-%m-%d')} to {episodes[-1].created_at.strftime('%Y-%m-%d')})")
        specific_count = sum(1 for ep in episodes if learning_engine._is_specific_recommendation(ep))
        generic_count = len(episodes) - specific_count
        print(f"    - Specific Contextual Recommendations: {specific_count}")
        print(f"    - Generic Reminders: {generic_count}")

        # ---------------------------------------------------------
        # Step 2: Learning Engine Scans Episodes for Interaction Patterns
        # ---------------------------------------------------------
        discovered_patterns = learning_engine.scan_intervention_preferences(episodes)
        print(f"\n[2] PATTERN DISCOVERY SCAN:")
        print(f"    - Discovered Interaction Patterns: {len(discovered_patterns)}")

        target_pattern = next(
            (p for p in discovered_patterns if "specific" in p.description.lower()),
            None,
        )
        assert target_pattern is not None, "Target specificity pattern must be discovered from empirical data!"

        print(f"\n[3] DISCOVERED INTERACTION PATTERN:")
        print(f"    - Description: \"{target_pattern.description}\"")
        print(f"    - Semantics: Non-causal association ('appears more responsive to')")
        print(f"    - Support Count: {target_pattern.support_count}")
        print(f"    - Initial Status: {target_pattern.status}")
        print(f"    - Evidence Strength: {target_pattern.evidence_strength.upper()}")
        print(f"    - Specific Acceptance Rate: {target_pattern.metadata.get('specific_acceptance_rate', 0.0) * 100:.1f}%")
        print(f"    - Generic Acceptance Rate: {target_pattern.metadata.get('generic_acceptance_rate', 0.0) * 100:.1f}%")

        # ---------------------------------------------------------
        # Step 3: Provenance Verification
        # ---------------------------------------------------------
        evidence_records = pattern_store.list_evidence_for_pattern(target_pattern.id, limit=100)
        print(f"\n[4] PROVENANCE AUDIT:")
        print(f"    - Pattern Evidence Records in SQLite: {len(evidence_records)}")
        print(f"    - Sample Provenance Pointer: Evidence '{evidence_records[0].evidence_id}' linked to Episode '{evidence_records[0].episode_id}'")
        for ev in evidence_records[:3]:
            linked_ep = episode_store.get_episode(ev.episode_id)
            print(f"      * [Provenance Chain] Evidence {ev.evidence_id} -> Episode {ev.episode_id} (Response: {linked_ep.user_response.get('response')})")

        # ---------------------------------------------------------
        # Step 4: Contradictory Evidence & Lifecycle Promotion
        # ---------------------------------------------------------
        print(f"\n[5] CONTRADICTORY EVIDENCE & LIFECYCLE PROMOTION:")
        # Evaluate progression towards ACTIVE
        new_status, strength = learning_engine.evaluate_progression(target_pattern, as_of=base_time)
        target_pattern.status = new_status.value
        target_pattern.evidence_strength = strength
        pattern_store.update_pattern(target_pattern)
        print(f"    - Lifecycle Progression: {target_pattern.status} (Evidence Strength: {target_pattern.evidence_strength.upper()})")
        print(f"    - Confidence Ratio: {target_pattern.confidence * 100:.1f}%")

        # Introduce 4 contradictory observations (specific recommendation dismissed)
        for c in range(4):
            t_contra = base_time + timedelta(hours=c+1)
            contra_ep = episode_store.create_episode(
                situation_id=f"sit-contra-{c}",
                hermes_task="Contradiction test",
                urgency="medium",
                actionability="high",
                evidence_strength="strong",
                created_at=t_contra,
            )
            learning_engine.record_evidence(
                pattern_id=target_pattern.id,
                observation_type=EvidenceObservationType.CONTRADICTION,
                observed_at=t_contra,
                episode_id=contra_ep.id,
                details={"reason": "User dismissed specific recommendation during deep focus."},
            )

        updated_pat = pattern_store.get_pattern(target_pattern.id)
        print(f"    - After 4 Contradictions:")
        print(f"      * Support Count: {updated_pat.support_count} | Contradiction Count: {updated_pat.contradiction_count}")
        print(f"      * Empirical Confidence: {updated_pat.confidence * 100:.1f}%")
        print(f"      * Status Maintained Without Premature Inactivation: {updated_pat.status}")

        # ---------------------------------------------------------
        # Step 5: Recency Decay & Recovery
        # ---------------------------------------------------------
        print(f"\n[6] RECENCY DECAY & RECOVERY SIMULATION:")
        # Advance time by 20 days with no new observations -> Should enter DECAYING
        decay_time = base_time + timedelta(days=20)
        decayed_status, decay_strength = learning_engine.evaluate_progression(updated_pat, as_of=decay_time)
        updated_pat.status = decayed_status.value
        updated_pat.evidence_strength = decay_strength
        pattern_store.update_pattern(updated_pat)
        print(f"    - After 20 Days Silence (Decay Threshold = 14d): Status = {updated_pat.status} ({updated_pat.evidence_strength.upper()})")

        # Re-observation of fresh support evidence -> Should RECOVER to SUPPORTED / ACTIVE
        recovery_time = decay_time + timedelta(days=1)
        rec_ep = episode_store.create_episode(
            situation_id="sit-recovery-01",
            hermes_task="Recovery test",
            urgency="high",
            actionability="high",
            evidence_strength="strong",
            created_at=recovery_time,
        )
        recovered_pat, _ = learning_engine.record_evidence(
            pattern_id=updated_pat.id,
            observation_type=EvidenceObservationType.SUPPORT,
            observed_at=recovery_time,
            episode_id=rec_ep.id,
            details={"reason": "User accepted specific contextual guidance upon returning."},
        )
        print(f"    - After Fresh Support Re-Observation: Recovered Status = {recovered_pat.status} ({recovered_pat.evidence_strength.upper()})")
        print(f"    - Historical Evidence Preserved: Total Evidence Records = {len(pattern_store.list_evidence_for_pattern(recovered_pat.id))}")

    print("\n" + "=" * 80)
    print("LONGITUDINAL EVALUATION COMPLETED SUCCESSFULLY")
    print("=" * 80)


if __name__ == "__main__":
    run_longitudinal_evaluation()
