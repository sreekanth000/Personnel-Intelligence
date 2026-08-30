"""
Unit tests for GoalMatcher and PersonalSignificanceEngine goal relevance.
"""

from datetime import datetime, timezone
import unittest

from personal_intelligence.core.goals.models import Goal, GoalPriority
from personal_intelligence.core.significance.engine import PersonalSignificanceEngine
from personal_intelligence.core.significance.matching import GoalMatcher, extract_bigrams, extract_keywords
from personal_intelligence.core.significance.models import SignificanceLevel
from personal_intelligence.core.world.changes import MeaningfulChange


class TestGoalMatching(unittest.TestCase):

    def setUp(self) -> None:
        self.matcher = GoalMatcher()
        self.engine = PersonalSignificanceEngine(goal_matcher=self.matcher)

    def test_extract_keywords_filters_stopwords_and_short(self) -> None:
        text = "This is a test of the Q3 OKR product launch and delivery"
        kw = extract_keywords(text, min_length=2)
        self.assertIn("q3", kw)
        self.assertIn("okr", kw)
        self.assertIn("product", kw)
        self.assertIn("launch", kw)
        self.assertIn("delivery", kw)
        self.assertNotIn("is", kw)
        self.assertNotIn("the", kw)
        self.assertNotIn("and", kw)

    def test_extract_bigrams(self) -> None:
        words = ["product", "launch", "delivery", "milestone"]
        bigrams = extract_bigrams(words)
        self.assertEqual(bigrams, ["product launch", "launch delivery", "delivery milestone"])

    def test_exact_phrase_match(self) -> None:
        is_rel, score, reason = self.matcher.is_relevant(
            goal_name="Ship v2.0 Product Launch",
            goal_description="Final release",
            goal_tags=["release"],
            context_text="The team is preparing to ship v2.0 product launch before Friday.",
        )
        self.assertTrue(is_rel)
        self.assertGreaterEqual(score, 0.9)
        self.assertIn("Exact phrase match", reason)

    def test_bigram_match(self) -> None:
        is_rel, score, reason = self.matcher.is_relevant(
            goal_name="Quarterly Financial Audit",
            goal_description="Complete annual reports",
            goal_tags=[],
            context_text="Received financial audit notification from external accountants.",
        )
        self.assertTrue(is_rel)
        self.assertGreaterEqual(score, 0.25)
        self.assertIn("financial audit", reason.lower())

    def test_false_positive_prevention(self) -> None:
        # A goal with multiple keywords should NOT match a completely unrelated event that merely has one generic word
        is_rel, score, reason = self.matcher.is_relevant(
            goal_name="Complete Mobile Application Architecture Overhaul",
            goal_description="Redesign React Native layers",
            goal_tags=[],
            context_text="The grocery delivery application is on sale today.",
        )
        self.assertFalse(is_rel)
        self.assertLess(score, self.matcher.match_threshold)

    def test_short_keyword_handling_okr(self) -> None:
        is_rel, score, reason = self.matcher.is_relevant(
            goal_name="Q3 OKR Review",
            goal_description="Quarterly performance review with leadership",
            goal_tags=["okr"],
            context_text="Calendar invitation for Q3 OKR Review meeting tomorrow at 10 AM.",
        )
        self.assertTrue(is_rel)
        self.assertGreaterEqual(score, 0.5)

    def test_tag_based_matching(self) -> None:
        is_rel, score, reason = self.matcher.is_relevant(
            goal_name="Alpha Milestone",
            goal_description="Project completion",
            goal_tags=["kubernetes", "infra"],
            context_text="Alert on kubernetes cluster production node failure.",
        )
        self.assertTrue(is_rel)
        self.assertGreaterEqual(score, 0.25)
        self.assertIn("kubernetes", reason.lower())

    def test_significance_engine_evaluates_critical_goal_match(self) -> None:
        critical_goal = Goal(
            name="Executive Board Presentation",
            description="Q3 strategic roadmap presentation",
            priority=GoalPriority.CRITICAL.value,
            tags=["board", "executive"],
        )
        change = MeaningfulChange(
            what_changed="Board presentation room rescheduled to 8 AM",
            why_it_matters="Directly impacts preparation time",
            evidence=["Calendar event update", "Room change email"],
            what_may_happen_next="Presentation starts without adequate prep",
            uncertainty="Room availability unconfirmed",
            domain="calendar",
        )

        assessment = self.engine.evaluate_change(
            change=change,
            active_goals=[critical_goal],
            reference_time=datetime.now(timezone.utc),
        )

        self.assertEqual(assessment.level, SignificanceLevel.CRITICAL.value)
        self.assertEqual(assessment.goal_relevance, "critical")
        self.assertTrue(any("Executive Board Presentation" in r for r in assessment.reasons))

    def test_significance_engine_unrelated_event_not_escalated(self) -> None:
        critical_goal = Goal(
            name="Executive Board Presentation",
            description="Q3 strategic roadmap presentation",
            priority=GoalPriority.CRITICAL.value,
            tags=["board"],
        )
        change = MeaningfulChange(
            what_changed="Spotify playlist updated with 5 new songs",
            why_it_matters="Routine media notification",
            evidence=["Spotify notification"],
            what_may_happen_next="More songs available",
            uncertainty="Low",
            domain="media",
        )

        assessment = self.engine.evaluate_change(
            change=change,
            active_goals=[critical_goal],
            reference_time=datetime.now(timezone.utc),
        )

        self.assertEqual(assessment.level, SignificanceLevel.NOT_SIGNIFICANT.value)
        self.assertEqual(assessment.goal_relevance, "none")


if __name__ == "__main__":
    unittest.main()
