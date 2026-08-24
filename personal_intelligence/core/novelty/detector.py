"""
Deterministic NoveltyEngine for Personal Intelligence.
Purely statistical, deterministic divergence scoring without ML, LLMs, or vector embeddings.

Numerical statistics (z-scores, event frequencies, velocity rates, silence gap hours,
and multivariate distances) are used internally as implementation details but are NOT
fake probability or confidence values.

Public Personal Intelligence reasoning interfaces receive strictly categorical classifications:
- NORMAL
- UNUSUAL
- HIGHLY_UNUSUAL
- NOVEL_COMBINATION

Core Deterministic Capabilities:
1. z-score deviation (standardized distance from historical mean)
2. baseline comparison (empirical distribution parameters: mean, std, min, max)
3. event frequency (empirical categorical rarity)
4. event velocity (rate of event arrival vs historical distribution)
5. event silence (inactivity gap vs historical inter-arrival intervals)
6. historical state similarity (multivariate distance across state features)
7. cross-domain combination rarity (rarity of co-occurring multi-domain features)

NOVEL_COMBINATION states directly trigger candidate novel_situation generation in SituationEngine.
Hermes is explicitly permitted to conclude 'insufficient evidence' when history is sparse or
novelty cannot be conclusively explained.
"""

from collections import Counter
from datetime import datetime, timedelta, timezone
import math
from typing import Any, Dict, List, Optional, Set

from personal_intelligence.core.novelty.models import (
    FeatureNoveltyResult,
    NoveltyClassification,
    NoveltyResult,
    OverallNoveltyLevel,
)
from personal_intelligence.core.state.models import StateRepresentation


class NoveltyEngine:
    """
    Deterministic novelty engine implementing 7 core statistical capabilities:
    1. z-score deviation
    2. baseline comparison
    3. event frequency
    4. event velocity
    5. event silence
    6. historical state similarity
    7. cross-domain combination rarity

    Produces strictly categorical results:
    - NORMAL
    - UNUSUAL
    - HIGHLY_UNUSUAL
    - NOVEL_COMBINATION
    """

    def __init__(
        self,
        min_history_samples: int = 3,
        categorical_rare_threshold: float = 0.10,
        numerical_unusual_z: float = 1.5,
        numerical_highly_unusual_z: float = 2.5,
        novel_combination_distance_threshold: float = 0.50,
        cross_domain_rarity_threshold: float = 0.05,
        baseline_window_samples: Optional[int] = None,
        baseline_window_days: Optional[float] = None,
    ) -> None:
        self.min_history_samples = min_history_samples
        self.categorical_rare_threshold = categorical_rare_threshold
        self.numerical_unusual_z = numerical_unusual_z
        self.numerical_highly_unusual_z = numerical_highly_unusual_z
        self.novel_combination_distance_threshold = novel_combination_distance_threshold
        self.cross_domain_rarity_threshold = cross_domain_rarity_threshold
        self.baseline_window_samples = baseline_window_samples
        self.baseline_window_days = baseline_window_days

    def evaluate_state(
        self,
        current_state: StateRepresentation,
        history: Optional[List[StateRepresentation]] = None,
    ) -> NoveltyResult:
        """Alias for detect."""
        return self.detect(current_state, history)

    def detect(
        self,
        current_state: StateRepresentation,
        history: Optional[List[StateRepresentation]] = None,
    ) -> NoveltyResult:
        """
        Evaluates deterministic statistical novelty of current_state against history.
        Returns categorical classification (NORMAL, UNUSUAL, HIGHLY_UNUSUAL, NOVEL_COMBINATION).
        """
        now = current_state.timestamp or datetime.now(timezone.utc)
        raw_history = history or []

        # Apply baseline window filtering if configured
        history_list = self._filter_baseline_window(raw_history, now)
        feature_results: List[FeatureNoveltyResult] = []

        # Handle missing / cold start history -> Hermes concludes 'insufficient evidence'
        if not history_list or len(history_list) < self.min_history_samples:
            for feat_name, feat in current_state.features.items():
                feature_results.append(
                    FeatureNoveltyResult(
                        feature=feat_name,
                        current_value=feat.value,
                        baseline={"count": len(history_list), "status": "insufficient_history"},
                        deviation=0.0,
                        classification=NoveltyClassification.NORMAL.value,
                        explanation=f"Insufficient history ({len(history_list)} samples < {self.min_history_samples}) for statistical baseline. Conclude insufficient evidence.",
                    )
                )
            return NoveltyResult(
                overall_level=OverallNoveltyLevel.NORMAL.value,
                feature_results=feature_results,
                timestamp=now,
                metadata={
                    "history_count": len(history_list),
                    "cold_start": True,
                    "reasoning_instruction": "insufficient_evidence",
                },
            )

        # 1. Evaluate each individual feature dimension using deterministic primitives
        for feat_name, feat in current_state.features.items():
            historical_values = [
                h.get_value(feat_name) for h in history_list if h.get_feature(feat_name) is not None
            ]
            res = self._evaluate_feature(feat_name, feat.value, historical_values)
            feature_results.append(res)

        # 2. Evaluate Historical State Similarity & Multivariate Distance
        similarity_analysis = self._evaluate_historical_state_similarity(
            current_state=current_state,
            history=history_list,
            feature_results=feature_results,
        )

        min_state_distance = similarity_analysis["min_state_distance"]
        similar_state_count = similarity_analysis["similar_state_count"]
        is_novel_by_distance = similarity_analysis["is_novel_combination"]

        # 3. Evaluate Cross-Domain Combination Rarity
        cross_domain_analysis = self._evaluate_cross_domain_combination_rarity(
            current_state=current_state,
            history=history_list,
            feature_results=feature_results,
        )
        is_rare_combination = cross_domain_analysis["is_rare_cross_domain_combination"]

        # 4. Determine Categorical Overall Novelty Level
        has_highly_unusual = any(
            f.classification == NoveltyClassification.HIGHLY_UNUSUAL.value
            for f in feature_results
        )
        has_unusual = any(
            f.classification == NoveltyClassification.UNUSUAL.value
            for f in feature_results
        )

        is_novel_combination = is_novel_by_distance or is_rare_combination

        if is_novel_combination:
            overall = OverallNoveltyLevel.NOVEL_COMBINATION.value
        elif has_highly_unusual:
            overall = OverallNoveltyLevel.HIGHLY_UNUSUAL.value
        elif has_unusual:
            overall = OverallNoveltyLevel.UNUSUAL.value
        else:
            overall = OverallNoveltyLevel.NORMAL.value

        metadata = {
            "history_count": len(history_list),
            "cold_start": False,
            "min_state_distance": round(min_state_distance, 4),
            "similar_state_count": similar_state_count,
            "is_novel_combination": is_novel_combination,
            "cross_domain_rarity": cross_domain_analysis.get("rarity_score"),
            "domains_analyzed": cross_domain_analysis.get("domains_present"),
        }

        return NoveltyResult(
            overall_level=overall,
            feature_results=feature_results,
            timestamp=now,
            metadata=metadata,
        )

    # -------------------------------------------------------------------------
    # Baseline Window Filtering
    # -------------------------------------------------------------------------

    def _filter_baseline_window(
        self,
        history: List[StateRepresentation],
        ref_time: datetime,
    ) -> List[StateRepresentation]:
        """Applies baseline window filtering by days or sample count."""
        filtered = list(history)
        if self.baseline_window_days is not None:
            cutoff = ref_time - timedelta(days=self.baseline_window_days)
            filtered = [h for h in filtered if h.timestamp and h.timestamp >= cutoff]

        if self.baseline_window_samples is not None and len(filtered) > self.baseline_window_samples:
            filtered = filtered[-self.baseline_window_samples:]

        return filtered

    # -------------------------------------------------------------------------
    # Feature Evaluation Dispatcher
    # -------------------------------------------------------------------------

    def _evaluate_feature(
        self,
        feature_name: str,
        current_val: Any,
        historical_vals: List[Any],
    ) -> FeatureNoveltyResult:
        """
        Evaluates numerical, velocity, silence, or categorical divergence for a single feature.
        """
        num_curr = self._extract_numerical_scalar(current_val)
        if num_curr is not None:
            num_history = [
                self._extract_numerical_scalar(v)
                for v in historical_vals
                if self._extract_numerical_scalar(v) is not None
            ]
            if len(num_history) >= self.min_history_samples:
                # Velocity vs Silence vs Standard Numerical Z-score
                if "velocity" in feature_name or "rate" in feature_name or "density" in feature_name:
                    return self._evaluate_velocity(feature_name, current_val, num_curr, num_history)
                elif "silence" in feature_name or "inactivity" in feature_name or "gap" in feature_name:
                    return self._evaluate_silence(feature_name, current_val, num_curr, num_history)
                else:
                    return self._evaluate_numerical(feature_name, current_val, num_curr, num_history)

        # Fallback to empirical event frequency / categorical evaluation
        return self._evaluate_categorical(feature_name, current_val, historical_vals)

    def _extract_numerical_scalar(self, val: Any) -> Optional[float]:
        """Extracts a primary scalar numeric representation from a value if possible."""
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            return float(val)
        if isinstance(val, dict):
            for k in ("hour", "pressure_score", "score", "rate_per_minute", "duration_minutes", "count", "velocity", "gap_hours", "density"):
                if k in val and isinstance(val[k], (int, float)) and not isinstance(val[k], bool):
                    return float(val[k])
        return None

    # -------------------------------------------------------------------------
    # 1. z-score Deviation & Baseline Comparison
    # -------------------------------------------------------------------------

    def _evaluate_numerical(
        self,
        feature_name: str,
        raw_current_val: Any,
        current_num: float,
        history_nums: List[float],
    ) -> FeatureNoveltyResult:
        """Computes deterministic Z-score z = (current - mean) / std."""
        n = len(history_nums)
        mean_val = sum(history_nums) / float(n)
        variance = sum((x - mean_val) ** 2 for x in history_nums) / float(n)
        std_val = math.sqrt(variance)

        baseline_dict = {
            "mean": round(mean_val, 3),
            "std": round(std_val, 3),
            "count": n,
            "min": round(min(history_nums), 3),
            "max": round(max(history_nums), 3),
        }

        # Zero variance handling
        if math.isclose(std_val, 0.0, abs_tol=1e-7):
            if math.isclose(current_num, mean_val, abs_tol=1e-7):
                return FeatureNoveltyResult(
                    feature=feature_name,
                    current_value=raw_current_val,
                    baseline=baseline_dict,
                    deviation=0.0,
                    classification=NoveltyClassification.NORMAL.value,
                    explanation=f"Value {current_num} matches zero-variance baseline constant {round(mean_val, 3)}.",
                )
            else:
                return FeatureNoveltyResult(
                    feature=feature_name,
                    current_value=raw_current_val,
                    baseline=baseline_dict,
                    deviation=999.0,
                    classification=NoveltyClassification.HIGHLY_UNUSUAL.value,
                    explanation=f"Value {current_num} deviates from zero-variance baseline constant {round(mean_val, 3)}.",
                )

        # Standard Z-Score calculation
        z = (current_num - mean_val) / std_val
        abs_z = abs(z)

        if abs_z < self.numerical_unusual_z:
            classification = NoveltyClassification.NORMAL.value
            expl = f"Within normal baseline bounds (|z|={abs_z:.2f} < {self.numerical_unusual_z})."
        elif abs_z < self.numerical_highly_unusual_z:
            classification = NoveltyClassification.UNUSUAL.value
            expl = f"Moderate numerical divergence (|z|={abs_z:.2f} >= {self.numerical_unusual_z})."
        else:
            classification = NoveltyClassification.HIGHLY_UNUSUAL.value
            expl = f"High numerical divergence (|z|={abs_z:.2f} >= {self.numerical_highly_unusual_z} from baseline mean {mean_val:.2f})."

        return FeatureNoveltyResult(
            feature=feature_name,
            current_value=raw_current_val,
            baseline=baseline_dict,
            deviation=round(abs_z, 3),
            classification=classification,
            explanation=expl,
        )

    # -------------------------------------------------------------------------
    # 2. Event Velocity Deviation
    # -------------------------------------------------------------------------

    def _evaluate_velocity(
        self,
        feature_name: str,
        raw_current_val: Any,
        current_num: float,
        history_nums: List[float],
    ) -> FeatureNoveltyResult:
        """Evaluates event velocity/arrival rate deviation against historical velocity distribution."""
        res = self._evaluate_numerical(feature_name, raw_current_val, current_num, history_nums)
        if res.classification == NoveltyClassification.HIGHLY_UNUSUAL.value:
            res.explanation = f"Sudden event velocity surge: {current_num:.2f} ({res.explanation})"
        elif res.classification == NoveltyClassification.UNUSUAL.value:
            res.explanation = f"Unusual event velocity shift: {current_num:.2f} ({res.explanation})"
        return res

    # -------------------------------------------------------------------------
    # 3. Event Silence / Inactivity Deviation
    # -------------------------------------------------------------------------

    def _evaluate_silence(
        self,
        feature_name: str,
        raw_current_val: Any,
        current_num: float,
        history_nums: List[float],
    ) -> FeatureNoveltyResult:
        """Evaluates event silence/inactivity gap against historical inter-arrival distribution."""
        res = self._evaluate_numerical(feature_name, raw_current_val, current_num, history_nums)
        if res.classification in {NoveltyClassification.UNUSUAL.value, NoveltyClassification.HIGHLY_UNUSUAL.value} and current_num > res.baseline.get("mean", 0.0):
            res.explanation = f"Abnormal inactivity/silence detected: {current_num:.2f} units elapsed ({res.explanation})"
        return res

    # -------------------------------------------------------------------------
    # 4. Event Frequency & Categorical Rarity
    # -------------------------------------------------------------------------

    def _evaluate_categorical(
        self,
        feature_name: str,
        raw_current_val: Any,
        historical_vals: List[Any],
    ) -> FeatureNoveltyResult:
        """Computes empirical categorical frequency and rare value classification."""
        n = len(historical_vals)
        norm_current = self._normalize_categorical_value(raw_current_val)
        norm_history = [self._normalize_categorical_value(v) for v in historical_vals]

        counts = Counter(norm_history)
        match_count = counts.get(norm_current, 0)
        freq = match_count / float(n) if n > 0 else 0.0
        rarity = 1.0 - freq

        baseline_dict = {
            "frequencies": {k: round(v / float(n), 3) for k, v in counts.items()},
            "count": n,
            "unique_values": len(counts),
        }

        if match_count == 0:
            classification = (
                NoveltyClassification.HIGHLY_UNUSUAL.value
                if n >= self.min_history_samples
                else NoveltyClassification.UNUSUAL.value
            )
            expl = f"Categorical value '{norm_current}' has never been observed in {n} historical snapshots."
        elif freq < self.categorical_rare_threshold:
            classification = NoveltyClassification.UNUSUAL.value
            expl = f"Categorical value '{norm_current}' is rare (frequency {freq:.1%} < {self.categorical_rare_threshold:.1%})."
        else:
            classification = NoveltyClassification.NORMAL.value
            expl = f"Categorical value '{norm_current}' is common (frequency {freq:.1%})."

        return FeatureNoveltyResult(
            feature=feature_name,
            current_value=raw_current_val,
            baseline=baseline_dict,
            deviation=round(rarity, 3),
            classification=classification,
            explanation=expl,
        )

    # -------------------------------------------------------------------------
    # 5. Historical State Similarity (Multivariate Distance)
    # -------------------------------------------------------------------------

    def _evaluate_historical_state_similarity(
        self,
        current_state: StateRepresentation,
        history: List[StateRepresentation],
        feature_results: List[FeatureNoveltyResult],
    ) -> Dict[str, Any]:
        """
        Computes multivariate historical state similarity to detect NOVEL_COMBINATION.
        Measures normalized distance across all dimensions between current_state and historical states.
        """
        if not history or not current_state.features:
            return {
                "min_state_distance": 0.0,
                "similar_state_count": len(history),
                "is_novel_combination": False,
            }

        std_map: Dict[str, float] = {}
        for f_res in feature_results:
            b_std = f_res.baseline.get("std")
            if isinstance(b_std, (int, float)) and b_std > 0:
                std_map[f_res.feature] = float(b_std)

        distances: List[float] = []
        feature_keys = list(current_state.features.keys())

        for h_state in history:
            diffs: List[float] = []
            for k in feature_keys:
                curr_val = current_state.get_value(k)
                hist_val = h_state.get_value(k)

                if hist_val is None:
                    diffs.append(0.5)  # Missing feature penalty
                    continue

                curr_num = self._extract_numerical_scalar(curr_val)
                hist_num = self._extract_numerical_scalar(hist_val)

                if curr_num is not None and hist_num is not None:
                    scale = std_map.get(k, 1.0)
                    scaled_diff = abs(curr_num - hist_num) / (3.0 * scale if scale > 0 else 1.0)
                    diffs.append(min(1.0, scaled_diff))
                else:
                    norm_c = self._normalize_categorical_value(curr_val)
                    norm_h = self._normalize_categorical_value(hist_val)
                    diffs.append(0.0 if norm_c == norm_h else 1.0)

            if diffs:
                avg_dist = sum(diffs) / float(len(diffs))
                distances.append(avg_dist)

        min_dist = min(distances) if distances else 0.0
        similar_count = sum(1 for d in distances if d < 0.25)

        deviating_dims = [
            f for f in feature_results
            if f.classification in {NoveltyClassification.UNUSUAL.value, NoveltyClassification.HIGHLY_UNUSUAL.value}
        ]

        is_novel = (
            (min_dist >= self.novel_combination_distance_threshold and len(feature_keys) >= 2)
            or (similar_count == 0 and len(deviating_dims) >= 2)
        )

        return {
            "min_state_distance": min_dist,
            "similar_state_count": similar_count,
            "is_novel_combination": is_novel,
        }

    # -------------------------------------------------------------------------
    # 6. Cross-Domain Combination Rarity
    # -------------------------------------------------------------------------

    def _evaluate_cross_domain_combination_rarity(
        self,
        current_state: StateRepresentation,
        history: List[StateRepresentation],
        feature_results: Optional[List[FeatureNoveltyResult]] = None,
    ) -> Dict[str, Any]:
        """
        Determines if current combination of cross-domain categorical features or multi-domain
        anomalies has ever co-occurred in historical state snapshots.
        """
        if not history or len(history) < self.min_history_samples:
            return {
                "is_rare_cross_domain_combination": False,
                "rarity_score": 0.0,
                "domains_present": [],
            }

        # Collect categorical features across domains
        cat_domain_features: Dict[str, str] = {}
        for feat_name, feat in current_state.features.items():
            num_val = self._extract_numerical_scalar(feat.value)
            if num_val is None:  # Strictly categorical
                cat_domain_features[feat_name] = self._normalize_categorical_value(feat.value)

        # Check if 2+ distinct domains have deviating features (|z| >= 1.5 or rare)
        deviating_domains: Set[str] = set()
        if feature_results:
            for f_res in feature_results:
                if f_res.classification in {NoveltyClassification.UNUSUAL.value, NoveltyClassification.HIGHLY_UNUSUAL.value}:
                    feat = current_state.get_feature(f_res.feature)
                    domain = getattr(feat, "source", "generic") or "generic"
                    deviating_domains.add(domain)

        is_rare = False
        co_occurrence_count = 0
        n = len(history)

        # Check if individual categorical features were each previously observed, but their co-occurrence is unseen
        all_individual_cats_known = True
        for f_name, cur_norm_val in cat_domain_features.items():
            hist_vals = [h_state.get_value(f_name) for h_state in history]
            norm_hist_vals = [self._normalize_categorical_value(v) for v in hist_vals if v is not None]
            if cur_norm_val not in norm_hist_vals:
                all_individual_cats_known = False
                break

        if len(cat_domain_features) >= 2 and all_individual_cats_known:
            for h_state in history:
                all_matched = True
                for f_name, cur_norm_val in cat_domain_features.items():
                    hist_val = h_state.get_value(f_name)
                    if hist_val is None or self._normalize_categorical_value(hist_val) != cur_norm_val:
                        all_matched = False
                        break
                if all_matched:
                    co_occurrence_count += 1

            co_occurrence_freq = co_occurrence_count / float(n)
            if co_occurrence_count == 0 and n >= self.min_history_samples:
                is_rare = True
            elif co_occurrence_freq < self.cross_domain_rarity_threshold:
                is_rare = True

        # Multi-domain simultaneous anomaly (2+ distinct domains deviating simultaneously)
        if len(deviating_domains) >= 2:
            is_rare = True

        return {
            "is_rare_cross_domain_combination": is_rare,
            "co_occurrence_count": co_occurrence_count,
            "co_occurrence_frequency": round(co_occurrence_count / float(n), 4) if n > 0 else 0.0,
            "rarity_score": round(1.0 - (co_occurrence_count / float(n)), 4) if n > 0 else 0.0,
            "domains_present": list(current_state.features.keys()),
            "deviating_domains": list(deviating_domains),
        }

    def _normalize_categorical_value(self, val: Any) -> str:
        """Converts arbitrary categorical value to normalized string key."""
        if isinstance(val, dict):
            if "bucket" in val:
                return str(val["bucket"])
            if "name" in val:
                return str(val["name"])
            return str(sorted(val.items()))
        return str(val)


# Backwards compatibility alias
StatisticalNoveltyDetector = NoveltyEngine
