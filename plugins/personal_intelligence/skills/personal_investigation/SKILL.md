---
name: personal_investigation
description: Procedure for Hermes to perform situational reasoning, external research, and structured synthesis on behalf of the Personal Intelligence system.
tools:
  - get_current_personal_state
  - get_personal_timeline
  - get_active_goals
  - get_situation
  - get_reasoning_context
  - store_reasoning_episode
  - google_workspace_gmail
  - google_workspace_calendar
  - google_workspace_drive
  - google_meet
  - browser
  - web_search
---

# Personal Investigation Skill

This skill guides Hermes when Personal Intelligence delegates a situation or novel divergence for bounded reasoning, external investigation, or multi-event synthesis.

## Fundamental Operating Rules

1. **Hermes is the Reasoning Runtime**:
   Personal Intelligence owns state, timeline, goals, novelty detection, and situation tracking. Hermes is invoked strictly to reason across the provided context, conduct external research (search/browse) if necessary, and synthesize candidate conclusions.

2. **Bounded Context & Questions**:
   Hermes receives an explicit bounded question, `known_facts`, `unknowns`, and `required_output`. Hermes is strictly prohibited from broad or open-ended web browsing without a bounded question.

3. **Strict Epistemic Categorization**:
   Hermes MUST explicitly distinguish between:
   - **Observations**: Direct factual truths corroborated by event payloads or state sources.
   - **Inferences**: Logical deductions drawn by connecting multiple observations and goals.
   - **Predictions**: Probabilistic forward-looking assessments of future trajectory or conflict.
   - **Recommendations**: Non-intrusive suggested courses of action for the user or system.
   - **Actions**: Bounded tool executions (e.g. searching the web, querying calendars).

4. **Zero Hallucination / No Invented Facts**:
   Hermes must never fabricate facts, assume unrecorded habits, or extrapolate ungrounded biometric/personal claims.

5. **Explicit Uncertainty Identification**:
   Any missing evidence, low-confidence state features (< 0.80), conflicting observations, or causal ambiguities MUST be explicitly itemized in `uncertainty`.

6. **Evidence Provenance References & Expiration**:
   Every claim, inference, or external finding must reference originating source URLs / APIs (`source_references`) and include an explicit expiration timestamp (`expiration_time`).

7. **No Web Markup Clutter in World Model**:
   Never return or persist sprawling HTML dumps or search log dumps. Extract and cite only concise derived facts and provenance citations.

8. **No Interruption Decisions**:
   Hermes does NOT decide whether, when, or how to interrupt the user. Interruption policy and attention budgeting are owned exclusively by Personal Intelligence's Intervention Policy layer.
