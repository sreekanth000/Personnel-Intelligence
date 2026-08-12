# Personal Intelligence System

> **A user-owned, evidence-grounded, privacy-first personal cognitive engine.**
> Maintains a living, temporally-aware graph of entities, relationships, commitments, decisions, events, and claims extracted across Gmail, Google Calendar, Google Drive, and personal notes.

---

## Architecture Diagram

```
+---------------------------------------------------------------------------------------------------+
|                                      MULTI-SOURCE CONNECTORS                                       |
|  +-------------------+  +-------------------+  +-------------------+  +------------------------+  |
|  |  Gmail Connector  |  | Calendar Connector|  |  Drive Connector  |  | Local Notes Connector  |  |
|  +---------+---------+  +---------+---------+  +---------+---------+  +-----------+------------+  |
+------------|----------------------|----------------------|------------------------|---------------+
             |                      |                      |                        |
             +----------------------+----------+-----------+------------------------+
                                               |
                                               v
+---------------------------------------------------------------------------------------------------+
|                                 UNIFIED MULTI-SOURCE PIPELINE                                     |
|                                                                                                   |
|  1. Normalization & Preprocessing                                                                 |
|  2. GPT-4.1 Extraction (Entities, Relationships, Claims, Decisions, Commitments, Events)           |
|  3. Lineage Grounding & Evidence Recording                                                        |
|  4. Fuzzy & Canonical Entity Resolution (EntityResolver)                                          |
|  5. Deterministic Reconciliation (ReconciliationEngine: NOVEL, CONFIRM, REFINE, UPDATE, CONFLICT)  |
|     --> Automatically closes previous validity intervals (valid_to = timestamp) on updates       |
+----------------------------------------------+----------------------------------------------------+
                                               |
                                               v
+---------------------------------------------------------------------------------------------------+
|                                    LOCAL PERSISTENCE LAYER                                        |
|  +-------------------------------------+   +---------------------------------------------------+  |
|  |     DuckDB Structured Data Store     |   |            Kuzu Embedded Graph Store              |  |
|  | (Entities, Claims, Evidence, Log) |   |    (Nodes & Typed Relationship Edges)             |  |
|  +------------------+------------------+   +-------------------------+-------------------------+  |
|                     |                                                |                            |
|                     +-----------------------+------------------------+                            |
|                                             |                                                     |
|  +------------------------------------------v--------------------------------------------------+  |
|  |                       SQLite Sync Store (data/gmail_sync_state.db)                          |  |
|  | (Tracks sync runs, historyId, message deduplication & 10,000 initial deployment state)       |  |
|  +---------------------------------------------------------------------------------------------+  |
+----------------------------------------------+----------------------------------------------------+
                                               |
                                               v
+---------------------------------------------------------------------------------------------------+
|                              EVIDENCE-WEIGHTED CONTEXT ENGINE                                     |
|  * Seed Entity Identification (0-Hop) & 2-Hop Graph Traversal                                     |
|  * Evidence Weighting Score: sum(Confidence) + 0.2 * Count(Spans)                                 |
|  * Temporal Filtering (start_date, end_date, as_of_date, recent_days)                             |
|  * Exponential Recency Decay: exp(-0.02 * days_old)                                              |
|  * Composite Ranking: 0.35*Text + 0.35*Graph + 0.20*Evidence + 0.10*Recency                       |
+----------------------------------------------+----------------------------------------------------+
                                               |
                                               v
+---------------------------------------------------------------------------------------------------+
|                           POLICY-DRIVEN PRIVACY & CONTEXT FIREWALL                                |
|  * PII Regex Scrubbing (Emails, Phone Numbers, SSNs, Credit Cards, Secrets/API Keys, Salary)     |
|  * Sensitive Property Stripping (password, ssn, api_key, auth_token, bank_account, private_key)   |
|  * Evidence Snippet Masking (Optional anonymization before external LLM exposure)                 |
+----------------------------------------------+----------------------------------------------------+
                                               |
                                               v
+---------------------------------------------------------------------------------------------------+
|                               REASONING LAYER & FRONTEND APPLICATION                              |
|  +----------------------------------+          +-----------------------------------------------+  |
|  |   GPT-4.1 Reasoning Service      |          |       React 19 + Three.js 3D Globe UI         |  |
|  | (Generates answers with explicit |          |  * Interactive 3D World Model Graph           |  |
|  |  provenance lineage citations)   |          |  * Interactive Timeline & Event Stream        |  |
|  |                                  |          |  * Entities & Relationships Explorer          |  |
|  |                                  |          |  * Email & Ingestion Monitor                  |  |
|  |                                  |          |  * Ask AI & Provenance Inspector              |  |
|  +----------------------------------+          +-----------------------------------------------+  |
+---------------------------------------------------------------------------------------------------+
```

---

## Key Features

- **Multi-Source Ingestion**:
  - Seamlessly ingests data from **Gmail**, **Google Calendar API**, **Google Drive API**, and **Local Notes (`.md`, `.txt`)**.
- **SQLite Continuous Sync Engine**:
  - Runs in the background (`scripts/continuous_sync.py`).
  - Executes a 10,000 email historical sync on initial deployment, followed by incremental sync cycles.
  - Persists cursor state (`historyId`) in `data/gmail_sync_state.db` after every single message.
- **Deterministic Reconciliation & Temporal Lifecycle**:
  - Reconciles candidate edges and claims against existing state.
  - Automates validity interval closing (`valid_to = now`) on relationship updates to preserve complete temporal lineage.
- **Evidence-Weighted Context Engine**:
  - Traverses the knowledge graph up to 2-hops.
  - Applies evidence weighting, temporal filtering (`start_date`, `end_date`, `recent_days`), and exponential recency decay.
  - Ranks context using composite scoring: `0.35*Text + 0.35*Graph + 0.20*Evidence + 0.10*Recency`.
- **Policy-Driven Privacy Firewall**:
  - Intercepts all context packages before sending to external AI models.
  - Scrubs PII (Emails, Phone, SSNs, Credit Cards, Secrets, Salary) and strips sensitive property keys.
- **3D Globe & Interactive Visualizations**:
  - Beautiful Three.js/Three-Globe dynamic graph visualization.
  - Bounded detail panels, search, filters, timeline event streams, and evidence grounding inspector.

---

## Directory Structure

```
personal-intelligence/
├── app/
│   ├── api/                   # FastAPI REST API endpoints (/api/v1/world, /api/v1/ask, etc.)
│   ├── config/                # Environment settings, structlog config, feature flags
│   ├── connectors/            # Data source connectors (Gmail, Google Calendar, Google Drive)
│   ├── domain/                # Pydantic v2 core domain models (Entities, Relationships, Claims, Evidence)
│   ├── persistence/           # Storage repositories (DuckDB, Kuzu Graph, SQLite Sync Store)
│   └── services/              # Pipeline, ReconciliationEngine, ContextEngine, PrivacyFilter, Reasoning
├── frontend/                  # React 19 + TypeScript + Vite + Three.js frontend dashboard
│   ├── src/
│   │   ├── components/        # UI components (GlobeGraph, Timeline, Bento, Header, Navbar)
│   │   ├── pages/             # App pages (Dashboard, WorldGraph, Timeline, Entities, Emails, Ask)
│   │   └── services/          # Frontend API client & types
├── scripts/                   # Continuous sync and setup scripts
│   ├── continuous_sync.py     # Background multi-source continuous sync loop
│   └── gmail_auth_only.py     # Interactive Google OAuth authentication setup
├── data/                      # Local data stores (DuckDB, Kuzu Graph, SQLite DB)
├── tests/                     # Comprehensive Pytest suite (162 tests)
├── pyproject.toml             # Python dependencies and tooling configuration
└── README.md                  # System documentation
```

---

## Setup & Running Instructions

### Prerequisites

- **Python**: `Python 3.11+`
- **Node.js**: `Node.js 18+` & `npm`
- **Google Cloud OAuth Credentials**: Saved at `data/credentials/credentials.json` with Gmail, Calendar, and Drive API access enabled.
- **Azure OpenAI or OpenAI API Key**: Configured in `.env`.

---

### Step 1: Environment Setup

Create and activate a Python virtual environment, then install dependencies:

```bash
# Windows (PowerShell)
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Linux / macOS
python3 -m venv .venv
source .venv/bin/activate

# Install Python package in editable mode with all dev dependencies
pip install -e .
```

---

### Step 2: Environment Configuration

Create a `.env` file in the project root:

```env
# Server Configuration
PI_ENVIRONMENT=development
PI_LOG_LEVEL=INFO

# Azure OpenAI / OpenAI LLM Configuration
PI_AZURE_AI_ENDPOINT=https://your-azure-openai-endpoint.openai.azure.com/
PI_AZURE_AI_API_KEY=your-azure-api-key-here
PI_AZURE_OPENAI_DEPLOYMENT=gpt-4o
PI_AZURE_AI_API_VERSION=2024-08-01-preview

# Storage Paths
PI_DUCKDB_PATH=data/world_model.duckdb
PI_KUZU_PATH=data/world_model.kuzu
```

---

### Step 3: Google OAuth Authentication Setup

Place your Google OAuth client secrets file at `data/credentials/credentials.json`. Then run the authentication setup script:

```bash
python scripts/gmail_auth_only.py
```

*This opens your browser to grant read-only access to Gmail, Google Calendar, and Google Drive.*

---

### Step 4: Run the Backend API Server

Start the FastAPI server using Uvicorn:

```bash
python -m uvicorn app.main:app --port 8001 --reload
```

- API Base URL: `http://localhost:8001`
- OpenAPI Swagger Docs: `http://localhost:8001/docs`
- Health Check: `http://localhost:8001/health`

---

### Step 5: Start Continuous Multi-Source Sync (Background Process)

In a separate terminal window, launch the continuous background ingestion process:

```bash
python scripts/continuous_sync.py
```

*This process continuously fetches emails, calendar events, and drive notes, running them through extraction, entity resolution, and deterministic reconciliation into DuckDB, Kuzu, and SQLite.*

---

### Step 6: Launch the Frontend Web Dashboard

In a separate terminal window, navigate to the `frontend/` directory and start the Vite dev server:

```bash
cd frontend
npm install
npm run dev
```

Open your browser at `http://localhost:5173` to interact with the 3D Globe, Timeline, Entities, and Ask AI Inspector!

---

## Running Automated Tests

Run the complete test suite (162 tests) with Pytest:

```bash
pytest tests/ -v
```

To run a specific test module:

```bash
pytest tests/test_services/test_context_engine.py -v
pytest tests/test_services/test_privacy_filter.py -v
pytest tests/test_connectors/test_multi_source_connectors.py -v
```

---

## License

Personal Intelligence is open-source and user-owned software.
