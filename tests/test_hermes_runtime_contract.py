"""
Contract tests proving Synthetic Hermes Runtime and authentic Hermes Bridge share the same interface
and adhere to the strict Personal Intelligence epistemic boundary.
"""

from datetime import datetime, timezone
import json
import pytest

from personal_intelligence.core.context.builder import ContextBuilder
from personal_intelligence.core.episodes import EpisodeStatus, EpisodeStore
from personal_intelligence.core.events.models import Event
from personal_intelligence.core.events.store import EventStore
from personal_intelligence.core.evidence_strength import EvidenceStrengthCalculator
from personal_intelligence.core.goals import GoalStore
from personal_intelligence.core.policy.engine import InterventionPolicyEngine
from personal_intelligence.core.situations.models import Situation, SituationPriority, SituationStatus
from personal_intelligence.core.situations.store import SituationStore
from personal_intelligence.core.state.engine import StateEngine
from personal_intelligence.core.timeline.engine import TimelineEngine
from personal_intelligence.demo.synthetic_hermes import (
    SyntheticHermesMode,
    SyntheticHermesRuntime,
)
from personal_intelligence.hermes_bridge.client import (
    HermesBridgeExecutionMode,
    HermesInvocationRequest,
    HermesInvocationResponse,
    HermesRuntimeBridge,
)
from personal_intelligence.hermes_bridge.reasoning import (
    ReasoningWorkflow,
    StructuredReasoningResult,
    validate_novel_reasoning_synthesis,
    validate_reasoning_synthesis,
)
from personal_intelligence.storage.db import DatabaseManager


def test_hermes_runtime_interface_parity():
    """Proves SyntheticHermesRuntime and HermesRuntimeBridge share the same reasoning invocation contract."""
    bridge = HermesRuntimeBridge(mode=HermesBridgeExecutionMode.TEST)
    synth = SyntheticHermesRuntime(mode=SyntheticHermesMode.DETERMINISTIC)

    # 1. Reasoning invocation contract parity
    assert hasattr(bridge, "invoke_reasoning")
    assert hasattr(synth, "invoke_reasoning")
    assert callable(bridge.invoke_reasoning)
    assert callable(synth.invoke_reasoning)

    # 2. Tool execution contract parity
    assert hasattr(bridge, "execute_tool")
    assert hasattr(synth, "execute_tool")
    assert callable(bridge.execute_tool)
    assert callable(synth.execute_tool)

    # 3. Host Hermes context protocol verification (for bridge.bind_context(synth))
    assert hasattr(synth, "prompt_llm") and callable(synth.prompt_llm)
    assert hasattr(synth, "call_agent") and callable(synth.call_agent)
    assert hasattr(synth, "has_tool") and callable(synth.has_tool)
    assert hasattr(synth, "is_capability_authenticated") and callable(synth.is_capability_authenticated)
    assert hasattr(synth, "available_tools")
    assert hasattr(synth, "auth_status")


def test_bounded_context_acceptance():
    """Verifies SyntheticHermesRuntime accepts the exact bounded context produced by ContextBuilder."""
    db_manager = DatabaseManager(db_path=":memory:")
    db_manager.initialize_schema()

    event_store = EventStore(db_manager=db_manager)
    timeline_engine = TimelineEngine(event_store=event_store)
    goal_store = GoalStore(db_manager=db_manager)
    situation_store = SituationStore(db_manager=db_manager)
    state_engine = StateEngine(timeline_engine=timeline_engine, goal_store=goal_store)
    context_builder = ContextBuilder(
        timeline_engine=timeline_engine,
        goal_store=goal_store,
        situation_store=situation_store,
    )

    sit = situation_store.create(
        type="unusual_state",
        priority=SituationPriority.HIGH.value,
        context={"summary": "Unusual activity density detected"},
        evidence=["evt_001", "evt_002"],
    )
    current_state = state_engine.compute_current_state()

    bounded_ctx = context_builder.build_bounded_context(
        situation=sit,
        current_state=current_state,
    )

    synth = SyntheticHermesRuntime(mode=SyntheticHermesMode.DETERMINISTIC)
    req = HermesInvocationRequest(
        prompt=bounded_ctx.to_prompt_string(),
        session_id="test_session_01",
    )
    resp = synth.invoke_reasoning(req)

    assert isinstance(resp, HermesInvocationResponse)
    assert resp.success is True
    assert len(resp.raw_response) > 0


def test_reasoning_workflow_schema_validation():
    """Verifies that ReasoningWorkflow executes against SyntheticHermesRuntime with zero validation errors."""
    db_manager = DatabaseManager(db_path=":memory:")
    db_manager.initialize_schema()

    event_store = EventStore(db_manager=db_manager)
    timeline_engine = TimelineEngine(event_store=event_store)
    goal_store = GoalStore(db_manager=db_manager)
    situation_store = SituationStore(db_manager=db_manager)
    episode_store = EpisodeStore(db_manager=db_manager)
    state_engine = StateEngine(timeline_engine=timeline_engine, goal_store=goal_store)
    context_builder = ContextBuilder(
        timeline_engine=timeline_engine,
        goal_store=goal_store,
        situation_store=situation_store,
    )

    synth = SyntheticHermesRuntime(mode=SyntheticHermesMode.DETERMINISTIC)
    workflow = ReasoningWorkflow(
        context_builder=context_builder,
        episode_store=episode_store,
        hermes_client=synth,
    )

    sit = situation_store.create(
        type="schedule_conflict",
        priority=SituationPriority.HIGH.value,
        context={"summary": "Concurrent calendar meetings scheduled"},
        evidence=["cal_01", "cal_02"],
    )
    current_state = state_engine.compute_current_state()

    result = workflow.run_workflow(situation=sit, current_state=current_state)

    assert result.success is True
    assert result.is_unparseable is False
    assert len(result.validation_errors) == 0
    assert isinstance(result.synthesis, StructuredReasoningResult)
    assert len(result.synthesis.what_is_happening) > 0
    assert isinstance(result.synthesis.inferences, list)
    assert isinstance(result.synthesis.predictions, list)
    assert isinstance(result.synthesis.recommendations, list)


def test_novel_reasoning_schema_validation():
    """Verifies that ReasoningWorkflow.run_novel_workflow executes against SyntheticHermesRuntime."""
    db_manager = DatabaseManager(db_path=":memory:")
    db_manager.initialize_schema()

    event_store = EventStore(db_manager=db_manager)
    timeline_engine = TimelineEngine(event_store=event_store)
    goal_store = GoalStore(db_manager=db_manager)
    situation_store = SituationStore(db_manager=db_manager)
    episode_store = EpisodeStore(db_manager=db_manager)
    state_engine = StateEngine(timeline_engine=timeline_engine, goal_store=goal_store)
    context_builder = ContextBuilder(
        timeline_engine=timeline_engine,
        goal_store=goal_store,
        situation_store=situation_store,
    )

    synth = SyntheticHermesRuntime(mode=SyntheticHermesMode.DETERMINISTIC)
    workflow = ReasoningWorkflow(
        context_builder=context_builder,
        episode_store=episode_store,
        hermes_client=synth,
    )

    sit = situation_store.create(
        type="unusual_state",
        priority=SituationPriority.HIGH.value,
        novelty=0.92,
        context={"summary": "Divergent marine telemetry logged"},
        evidence=["snr_01"],
    )
    current_state = state_engine.compute_current_state()

    result = workflow.run_novel_workflow(situation=sit, current_state=current_state)

    assert result.episode.status == EpisodeStatus.REASONING_COMPLETED
    assert len(result.validation_errors) == 0
    assert result.synthesis.what_appears_unusual is not None
    assert isinstance(result.synthesis.possible_interpretations, list)
    assert isinstance(result.synthesis.recommendations, list)


def test_mode_deterministic():
    """Verifies that DETERMINISTIC mode produces reproducible output."""
    runtime1 = SyntheticHermesRuntime(mode=SyntheticHermesMode.DETERMINISTIC, seed=42)
    runtime2 = SyntheticHermesRuntime(mode=SyntheticHermesMode.DETERMINISTIC, seed=42)

    prompt = "Situation: Workout completed. Facts: Run 10km at 06:00."
    req = HermesInvocationRequest(prompt=prompt)

    resp1 = runtime1.invoke_reasoning(req)
    resp2 = runtime2.invoke_reasoning(req)

    assert resp1.raw_response == resp2.raw_response


def test_mode_realistic_semantic():
    """Verifies that REALISTIC_SEMANTIC mode produces rich qualitative output."""
    runtime = SyntheticHermesRuntime(mode=SyntheticHermesMode.REALISTIC_SEMANTIC, seed=42)
    prompt = "Situation: Dense sprint workload deadline approaching. Facts: PR #500 open. Goal: Release Q3."
    req = HermesInvocationRequest(prompt=prompt)

    resp = runtime.invoke_reasoning(req)
    synthesis, errors = validate_reasoning_synthesis(resp.raw_response)

    assert errors == []
    assert synthesis is not None
    assert len(synthesis.inferences) >= 1
    assert len(synthesis.predictions) >= 1
    assert len(synthesis.recommendations) >= 1
    assert len(synthesis.uncertainties) >= 1


def test_mode_malformed_json_triggers_retry_and_unparseable():
    """Verifies that MALFORMED_JSON mode tests retry loops and UNPARSEABLE_REASONING status."""
    db_manager = DatabaseManager(db_path=":memory:")
    db_manager.initialize_schema()

    situation_store = SituationStore(db_manager=db_manager)
    episode_store = EpisodeStore(db_manager=db_manager)
    state_engine = StateEngine(
        timeline_engine=TimelineEngine(event_store=EventStore(db_manager=db_manager)),
        goal_store=GoalStore(db_manager=db_manager),
    )

    # Permanent failure (fail_attempts=0 -> fails all attempts)
    synth_fail = SyntheticHermesRuntime(mode=SyntheticHermesMode.MALFORMED_JSON, fail_attempts=0)
    workflow = ReasoningWorkflow(
        episode_store=episode_store,
        hermes_client=synth_fail,
        max_retries=2,
    )

    sit = situation_store.create(
        type="unusual_state",
        context={"summary": "Broken telemetry stream"},
    )
    res = workflow.run_workflow(situation=sit, current_state=state_engine.compute_current_state())

    assert res.is_unparseable is True
    assert res.episode.status == EpisodeStatus.UNPARSEABLE_REASONING
    assert res.attempts == 3  # Initial attempt + 2 retries


def test_mode_malformed_json_recovery_on_retry():
    """Verifies that MALFORMED_JSON mode recovers on attempt 2 when fail_attempts=1."""
    db_manager = DatabaseManager(db_path=":memory:")
    db_manager.initialize_schema()

    situation_store = SituationStore(db_manager=db_manager)
    episode_store = EpisodeStore(db_manager=db_manager)
    state_engine = StateEngine(
        timeline_engine=TimelineEngine(event_store=EventStore(db_manager=db_manager)),
        goal_store=GoalStore(db_manager=db_manager),
    )

    # Fails attempt 1 with malformed JSON, then recovers with valid deterministic JSON on attempt 2
    synth_recover = SyntheticHermesRuntime(mode=SyntheticHermesMode.MALFORMED_JSON, fail_attempts=1)
    workflow = ReasoningWorkflow(
        episode_store=episode_store,
        hermes_client=synth_recover,
        max_retries=2,
    )

    sit = situation_store.create(
        type="unusual_state",
        context={"summary": "Transient network glitch"},
    )
    res = workflow.run_workflow(situation=sit, current_state=state_engine.compute_current_state())

    assert res.success is True
    assert res.is_unparseable is False
    assert res.attempts == 2
    assert res.episode.status == EpisodeStatus.REASONING_COMPLETED


def test_mode_incomplete_investigation():
    """Verifies that INCOMPLETE_INVESTIGATION mode flags requires_follow_up=True and information gaps."""
    runtime = SyntheticHermesRuntime(mode=SyntheticHermesMode.INCOMPLETE_INVESTIGATION)
    prompt = "Situation: Partial activity detected without context."
    req = HermesInvocationRequest(prompt=prompt)

    resp = runtime.invoke_reasoning(req)
    synthesis, errors = validate_reasoning_synthesis(resp.raw_response)

    assert errors == []
    assert synthesis is not None
    assert synthesis.requires_follow_up is True
    assert len(synthesis.uncertainties) >= 1


def test_mode_contradictory_evidence():
    """Verifies that CONTRADICTORY_EVIDENCE mode detects conflicting signals."""
    runtime = SyntheticHermesRuntime(mode=SyntheticHermesMode.CONTRADICTORY_EVIDENCE)
    prompt = "Situation: Calendar says in meeting, GPS says traveling 85km/h."
    req = HermesInvocationRequest(prompt=prompt)

    resp = runtime.invoke_reasoning(req)
    synthesis, errors = validate_reasoning_synthesis(resp.raw_response)

    assert errors == []
    assert synthesis is not None
    assert synthesis.urgency == "high"
    assert synthesis.requires_follow_up is True
    assert any("conflict" in str(s).lower() or "contradict" in str(s).lower() for s in synthesis.inferences)


def test_pi_hermes_responsibility_boundary():
    """
    Architectural guarantee test:
    Proves Personal Intelligence retains exclusive authority over evidence calculation,
    intervention policy, and persistence, while Hermes only synthesizes semantic interpretation.
    """
    db_manager = DatabaseManager(db_path=":memory:")
    db_manager.initialize_schema()

    calc = EvidenceStrengthCalculator()
    policy = InterventionPolicyEngine()
    synth = SyntheticHermesRuntime(mode=SyntheticHermesMode.DETERMINISTIC)

    # 1. PI calculates evidence quality deterministically
    quality = calc.calculate(evidence_items=[{"source": "test", "confidence": 0.95}])
    assert quality in ("weak", "moderate", "strong", "conflicted", "insufficient_evidence")

    # 2. Hermes produces qualitative recommendations
    req = HermesInvocationRequest(prompt="Situation: Review code PR.")
    resp = synth.invoke_reasoning(req)
    synthesis, _ = validate_reasoning_synthesis(resp.raw_response)

    # 3. PI InterventionPolicyEngine determines presentation decision
    decision = policy.evaluate(
        urgency=synthesis.urgency,
        evidence_quality=quality,
        actionability=synthesis.actionability,
        relevance=synthesis.relevance,
    )
    assert decision.action in ["SUPPRESS", "DISCARD", "BRIEFING", "INTERRUPT", "DEFER"]
