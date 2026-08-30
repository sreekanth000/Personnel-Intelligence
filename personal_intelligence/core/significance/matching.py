"""
Improved goal-to-event relevance matching for Personal Significance Engine.

Uses multi-strategy matching:
1. Exact phrase matching (highest confidence)
2. Bigram overlap (medium confidence)
3. Keyword overlap with Jaccard-like weighting (medium confidence)
4. Tag/category matching from goal metadata (medium confidence)
"""

import re
from typing import List, Optional, Set, Tuple

# Common English stop words to exclude from keyword matching
STOP_WORDS: Set[str] = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "must",
    "and", "but", "or", "not", "no", "nor", "so", "yet",
    "in", "on", "at", "to", "for", "of", "with", "by", "from", "into",
    "about", "between", "through", "during", "before", "after",
    "this", "that", "these", "those", "it", "its",
    "my", "your", "his", "her", "our", "their",
    "what", "which", "who", "whom", "how", "when", "where", "why",
    "all", "each", "every", "both", "few", "more", "most", "some", "any",
    "very", "just", "also", "than", "then", "now", "here", "there",
}


def extract_keywords(text: str, min_length: int = 2) -> List[str]:
    """Extract meaningful keywords, filtering stop words and short tokens."""
    words = re.findall(r"[a-zA-Z0-9]+", text.lower())
    return [w for w in words if len(w) >= min_length and w not in STOP_WORDS]


def extract_bigrams(words: List[str]) -> List[str]:
    """Extract consecutive word pairs for phrase matching."""
    return [f"{words[i]} {words[i+1]}" for i in range(len(words) - 1)]


class GoalMatcher:
    """
    Multi-strategy goal relevance matcher.

    Scores relevance between a goal and a text context using:
    - Exact phrase substring match (score: 1.0)
    - Bigram overlap (score: 0.40 - 0.70 per matching bigram)
    - Weighted keyword overlap using Jaccard-like coefficient (score: 0.0 - 0.60)
    - Goal tags/category match (score: 0.35 - 0.50)
    """

    def __init__(
        self,
        phrase_boost: float = 1.0,
        bigram_boost: float = 0.7,
        keyword_boost: float = 0.5,
        tag_boost: float = 0.5,
        match_threshold: float = 0.25,
    ) -> None:
        self.phrase_boost = phrase_boost
        self.bigram_boost = bigram_boost
        self.keyword_boost = keyword_boost
        self.tag_boost = tag_boost
        self.match_threshold = match_threshold

    def compute_relevance(
        self,
        goal_name: str,
        goal_description: str = "",
        goal_tags: Optional[List[str]] = None,
        context_text: str = "",
    ) -> Tuple[float, str]:
        """
        Returns (score, reason) where score is 0.0-1.0 and reason explains the match.
        """
        goal_full = f"{goal_name} {goal_description or ''}".lower()
        context_lower = context_text.lower()
        score = 0.0
        reasons: List[str] = []

        # Strategy 1: Exact phrase match (goal name appears in context)
        goal_name_lower = goal_name.lower().strip()
        if len(goal_name_lower) > 3 and goal_name_lower in context_lower:
            return (self.phrase_boost, f"Exact phrase match: '{goal_name}'")

        # Strategy 2: Bigram overlap
        goal_keywords = extract_keywords(goal_full)
        context_keywords = extract_keywords(context_text)
        goal_bigrams = set(extract_bigrams(goal_keywords))
        context_bigrams = set(extract_bigrams(context_keywords))

        if goal_bigrams:
            bigram_overlap = goal_bigrams & context_bigrams
            if bigram_overlap:
                bigram_score = max(0.40, min(self.bigram_boost, self.bigram_boost * (len(bigram_overlap) / len(goal_bigrams))))
                score = max(score, bigram_score)
                reasons.append(f"Bigram match: {', '.join(list(bigram_overlap)[:3])}")

        # Strategy 3: Weighted keyword overlap (Jaccard-like)
        goal_kw_set = set(goal_keywords)
        context_kw_set = set(context_keywords)

        if goal_kw_set:
            overlap = goal_kw_set & context_kw_set
            if overlap:
                # Weight by fraction of goal keywords found
                jaccard = len(overlap) / len(goal_kw_set)
                # If goal has 3+ keywords and only 1 matches, guard against single weak word false-positives
                if len(goal_kw_set) >= 3 and len(overlap) == 1 and jaccard < 0.35:
                    kw_score = 0.10
                else:
                    kw_score = max(0.25, self.keyword_boost * jaccard)
                score = max(score, kw_score)
                reasons.append(f"Keyword overlap ({len(overlap)}/{len(goal_kw_set)}): {', '.join(list(overlap)[:4])}")

        # Strategy 4: Tag/category match
        if goal_tags:
            tag_set = {t.lower().strip() for t in goal_tags if t.strip()}
            if tag_set:
                tag_overlap = tag_set & context_kw_set
                if tag_overlap:
                    tag_score = max(0.35, min(self.tag_boost, self.tag_boost * (len(tag_overlap) / len(tag_set))))
                    score = max(score, tag_score)
                    reasons.append(f"Tag match: {', '.join(tag_overlap)}")

        reason = "; ".join(reasons) if reasons else "No match"
        return (score, reason)

    def is_relevant(
        self,
        goal_name: str,
        goal_description: str = "",
        goal_tags: Optional[List[str]] = None,
        context_text: str = "",
    ) -> Tuple[bool, float, str]:
        """Returns (is_relevant, score, reason)."""
        score, reason = self.compute_relevance(
            goal_name=goal_name,
            goal_description=goal_description,
            goal_tags=goal_tags,
            context_text=context_text,
        )
        return (score >= self.match_threshold, score, reason)
