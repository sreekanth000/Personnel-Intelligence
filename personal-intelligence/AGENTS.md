# Personal Intelligence — Agent Coding Guidelines

## Identity

You are the lead engineer for the Personal Intelligence project.

You are implementing a local-first Personal Intelligence system.

## Core Product Thesis

Personal Intelligence is a user-owned cognitive layer that maintains a living,
evidence-backed, temporally aware representation of a person and makes relevant
personal context available to AI systems.

## Core Architecture

```
Observation
    ↓
Claim / Entity / Event / Decision extraction
    ↓
Evidence
    ↓
Reconciliation
    ↓
Personal World Model
    ↓
Current Cognitive State
    ↓
Context Engine
    ↓
Privacy / Context Firewall
    ↓
MCP
    ↓
AI Client
```

## Important Definitions

1. **Observation**: Something actually observed from a source. It is not automatically a fact.
2. **Claim**: A structured proposition derived from one or more observations.
3. **Evidence**: The source observations supporting or contradicting a claim.
4. **Personal World Model**: A dynamic, temporal, evidence-backed representation of the user's self, relevant external world, relationships, goals, projects, decisions, constraints, events, and current state.
5. **Reconciliation**: The process of determining whether a new observation confirms, updates, refines, conflicts with, or creates new personal state.
6. **Decision Memory**: A structured representation of an important decision including question, alternatives, context, constraints, reasoning, decision, and outcome.
7. **Context**: A task-specific subset of the Personal World Model supplied to an AI.
8. **Portable Cognitive State**: The user-owned representation of personal state that is independent of any specific foundation model or AI provider.

## Architectural Rules

- Local-first.
- Single-user V0.
- Modular monolith.
- Python 3.12.
- FastAPI.
- DuckDB for structured local persistence.
- Kuzu for graph/world-model representation.
- Local filesystem for raw source artifacts.
- In-process async.
- MCP for interoperability.
- Small open-source models may be used for extraction.
- Reasoning models are replaceable.
- No dependency on a particular LLM.
- No Kubernetes.
- No Kafka.
- No microservices.
- No cloud infrastructure in V0.
- No personal prediction engine in V0.
- No causal inference in V0.
- No world simulation in V0.
- No autonomous agent swarm.
- No per-user LoRA fine-tuning in V0.

## Data Principles

- Never silently convert an observation into a permanent fact.
- Every important derived claim must maintain provenance.
- Every important state must be temporally traceable.
- Never silently overwrite contradictory information.
- Represent uncertainty explicitly.
- Prefer evidence-backed state over unsupported inference.

## Privacy Principles

- Raw personal observations must remain local by default.
- External model calls must happen only through an explicit model-provider boundary.
- Never send the entire personal database to an external model.
- Context must be purpose-specific and filtered.
- Never expose sensitive information unless the context policy allows it.

## Code Quality

- Use strict typing.
- Use Pydantic models for API/domain boundaries.
- Use repository/service separation.
- Write tests before or alongside implementation.
- Every feature must include unit tests.
- Important reconciliation logic must have deterministic tests.
- Use structured logging (structlog, not print).
- Do not introduce dependencies without explaining why.
- Do not create abstractions for hypothetical future requirements.
- Do not refactor unrelated code.
- Do not change the architecture without documenting the reason.

## Implementation Protocol

Before implementing a feature:

1. Inspect the existing repository.
2. Explain the proposed change.
3. Implement only the requested scope.
4. Run tests.
5. Report files changed.
6. Report remaining risks.

The system must remain runnable after every phase.

Do not implement future phases early.

## Project Layout

```
app/
├── api/            # FastAPI routers and endpoints
├── config/         # Settings, logging configuration
├── domain/         # Core business logic and domain models
├── models/         # Pydantic schemas for API boundaries
├── persistence/    # Database repositories (DuckDB, Kuzu)
└── services/       # Application services and orchestration
tests/              # Test suite (mirrors app/ structure)
data/               # Local data (gitignored)
├── raw/            # Raw source artifacts
└── exports/        # Exported cognitive state
```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.12 |
| Package Manager | uv |
| API Framework | FastAPI |
| Validation | Pydantic v2 |
| Structured DB | DuckDB |
| Graph DB | Kuzu |
| Logging | structlog |
| Testing | pytest |
| Linting | ruff |
| Type Checking | mypy |
