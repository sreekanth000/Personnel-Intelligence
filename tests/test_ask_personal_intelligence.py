"""
Unit tests for Ask Personal Intelligence Interface & Query Engine.

Validates:
1. Grounded routing strictly through Personal World Model, Situations, Goals, Patterns, Timeline.
2. Canonical example question handling:
   - "What should I be aware of today?"
   - "Did anything important change?"
   - "What am I likely to forget?"
   - "Do I have conflicting commitments?"
   - "Why are you recommending this?"
   - "What patterns are you seeing?"
   - "What should I prepare for tomorrow?"
3. Strict 5-part response structure:
   - Answer
   - Evidence
   - Uncertainty
   - Sources
   - Recommended next step
4. Bounded Hermes investigation delegation when information gaps exist.
5. Zero hidden chain-of-thought leakage.
6. HTTP API `/api/pi/ask` integration.
"""

from datetime import datetime, timedelta, timezone
import json
import threading
import time
import unittest
import urllib.request

from personal_intelligence.api.server import (
    DashboardDataService,
    PersonalIntelligenceRequestHandler,
    create_dashboard_server,
)
from personal_intelligence.core.events.models import Event
from personal_intelligence.core.events.store import EventStore
from personal_intelligence.core.goals.models import Goal, GoalPriority, GoalStatus
from personal_intelligence.core.goals.store import GoalStore
from personal_intelligence.core.patterns.models import Pattern, PatternStatus
from personal_intelligence.core.patterns.store import PatternStore
from personal_intelligence.core.query.ask import (
    AskPersonalIntelligenceEngine,
    AskPersonalIntelligenceResponse,
)
from personal_intelligence.core.situations.models import Situation, SituationPriority
from personal_intelligence.core.situations.store import SituationStore
from personal_intelligence.hermes_bridge.commands import PersonalIntelligenceCommandHandler
from personal_intelligence.storage.db import DatabaseManager


class TestAskPersonalIntelligence(unittest.TestCase):
    """
    Unit test suite for Ask Personal Intelligence query processing.
    """

    def setUp(self) -> None:
        self.db = DatabaseManager(db_path=":memory:")
        self.db.initialize_schema()

        self.event_store = EventStore(self.db)
        self.situation_store = SituationStore(self.db)
        self.goal_store = GoalStore(self.db)
        self.pattern_store = PatternStore(self.db)

        self.now = datetime.now(timezone.utc)

        # Ingest baseline sample data
        self.goal = self.goal_store.create_goal(
            name="Architecture Review Milestone",
            description="Finalize threat modeling and distributed lock specifications.",
            priority=GoalPriority.HIGH.value,
            status=GoalStatus.ACTIVE.value,
        )

        self.event1 = Event(
            id="evt-gmail-01",
            source="gmail",
            event_type="email_message",
            event_time=self.now - timedelta(hours=2),
            payload={"summary": "Request from Security team for threat modeling section", "subject": "Architecture Doc Review"},
        )
        self.event_store.append(self.event1)

        self.event2 = Event(
            id="evt-cal-01",
            source="calendar",
            event_type="calendar_event",
            event_time=self.now + timedelta(hours=14),
            payload={"title": "Executive Architecture Review", "duration_minutes": 60},
        )
        self.event_store.append(self.event2)

        self.situation = self.situation_store.create(
            type="unfinished_deliverable_risk",
            priority=SituationPriority.HIGH.value,
            novelty=0.75,
            context={
                "summary": "Threat modeling section incomplete before tomorrow's executive review.",
                "why_detected": "Email request pending with review meeting scheduled in 14 hours.",
            },
            evidence=["event:evt-gmail-01", "event:evt-cal-01", "goal:" + self.goal.id],
        )

        self.pattern = self.pattern_store.create_pattern(
            description="Deep work sessions before 11:00 yield highest documentation throughput.",
            pattern_type="behavioral",
            evidence_strength="strong",
            status=PatternStatus.SUPPORTED.value,
            support_count=12,
        )

        self.engine = AskPersonalIntelligenceEngine(db_manager=self.db)

    def test_ask_what_should_i_be_aware_of_today(self) -> None:
        res = self.engine.ask("What should I be aware of today?")
        self.assertIsInstance(res, AskPersonalIntelligenceResponse)
        self.assertIn("Unfinished Deliverable Risk", res.answer)
        self.assertTrue(len(res.evidence) > 0)
        self.assertTrue(any("Gmail" in s or "Calendar" in s or "Personal World Model" in s for s in res.sources))
        self.assertIsNotNone(res.uncertainty)
        self.assertTrue(len(res.recommended_next_step) > 0)

    def test_ask_did_anything_important_change(self) -> None:
        res = self.engine.ask("Did anything important change?")
        self.assertIsInstance(res, AskPersonalIntelligenceResponse)
        self.assertTrue(len(res.answer) > 0)
        self.assertTrue(len(res.evidence) > 0)
        self.assertTrue(len(res.sources) > 0)
        self.assertTrue(len(res.recommended_next_step) > 0)

    def test_ask_what_am_i_likely_to_forget(self) -> None:
        res = self.engine.ask("What am I likely to forget?")
        self.assertIsInstance(res, AskPersonalIntelligenceResponse)
        self.assertIn("deliverable", res.answer.lower())
        self.assertTrue(len(res.evidence) > 0)
        self.assertIn("threat mitigation", res.recommended_next_step.lower())

    def test_ask_do_i_have_conflicting_commitments(self) -> None:
        res = self.engine.ask("Do I have conflicting commitments?")
        self.assertIsInstance(res, AskPersonalIntelligenceResponse)
        self.assertTrue(len(res.answer) > 0)
        self.assertTrue(len(res.sources) > 0)
        self.assertTrue(len(res.recommended_next_step) > 0)

    def test_ask_why_are_you_recommending_this(self) -> None:
        res = self.engine.ask("Why are you recommending this?")
        self.assertIsInstance(res, AskPersonalIntelligenceResponse)
        self.assertIn("grounded", res.answer.lower())
        self.assertTrue(len(res.evidence) > 0)
        self.assertIn("diagnostic", res.recommended_next_step.lower())

    def test_ask_what_patterns_are_you_seeing(self) -> None:
        res = self.engine.ask("What patterns are you seeing?")
        self.assertIsInstance(res, AskPersonalIntelligenceResponse)
        self.assertIn("Deep work", res.answer)
        self.assertTrue(len(res.evidence) > 0)
        self.assertIn("morning", res.recommended_next_step.lower())

    def test_ask_what_should_i_prepare_for_tomorrow(self) -> None:
        res = self.engine.ask("What should I prepare for tomorrow?")
        self.assertIsInstance(res, AskPersonalIntelligenceResponse)
        self.assertIn("review", res.answer.lower())
        self.assertTrue(len(res.recommended_next_step) > 0)

    def test_no_hidden_chain_of_thought_leakage(self) -> None:
        res = self.engine.ask("What should I be aware of today?")
        for field_val in (res.answer, res.uncertainty, res.recommended_next_step, str(res.evidence)):
            self.assertNotIn("thought:", field_val.lower())
            self.assertNotIn("<thought>", field_val.lower())
            self.assertNotIn("internal reasoning:", field_val.lower())

    def test_command_handler_integration(self) -> None:
        handler = PersonalIntelligenceCommandHandler(db_manager=self.db)
        out = handler.execute("/pi ask What should I be aware of today?")
        self.assertIn("Personal Intelligence Response", out)
        self.assertIn("Answer", out)
        self.assertIn("Supporting Evidence", out)
        self.assertIn("Consulted Sources", out)
        self.assertIn("Recommended Next Step", out)


class TestAskPIHttpEndpoint(unittest.TestCase):
    """
    Tests HTTP endpoint POST /api/pi/ask.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.db = DatabaseManager(db_path=":memory:")
        cls.db.initialize_schema()
        cls.port = 18898
        cls.server = create_dashboard_server(
            host="127.0.0.1",
            port=cls.port,
            db_manager=cls.db,
            ui_dir="ui",
        )
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.3)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def test_post_ask_endpoint(self) -> None:
        url = f"http://127.0.0.1:{self.port}/api/pi/ask"
        req_body = json.dumps({"query": "What should I be aware of today?"}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=req_body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["status"], "success")
            self.assertIn("answer", data)
            self.assertIn("evidence", data)
            self.assertIn("uncertainty", data)
            self.assertIn("sources", data)
            self.assertIn("recommended_next_step", data)


if __name__ == "__main__":
    unittest.main()
