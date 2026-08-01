# Personnel Intelligence (Autonomous Readiness Intelligence)

An autonomous personal intelligence agent that proactively monitors your communications, calendar, and financials to alert you of incoming commitments, risks, and actionable insights.

The system relies on a local world model powered by DuckDB (structured entities) and ChromaDB (semantic vectors). It uses Azure OpenAI for extraction and semantic reasoning. 

## Features
- **Proactive Readiness Engine**: Tracks upcoming meetings, travel, and sessions, and generates alerts if you are missing required evidence (like agendas or presentations).
- **Financial Reconciliation**: Automatically tracks incoming bills (e.g. Credit Cards) and dynamically links matching payments to maintain financial health.
- **Bank Account Monitoring**: Pulls account balance notifications from your messages and raises an alert if your balance drops below customizable thresholds.

---

## 1. Prerequisites

Before installing the project, ensure you have the following installed on your machine:
- **Python 3.10+**
- **Node.js 18+** (for the frontend web application)

## 2. Backend Setup

### Install Python Dependencies
Open your terminal in the project root directory and install the required Python packages:

```bash
pip install -r requirements.txt
```

### Configure Environment Variables
You need to configure your AI provider settings. Create a `.env` file in the root directory and configure it with your Azure OpenAI credentials:

```ini
AZURE_AI_ENDPOINT=https://<your-endpoint>.cognitiveservices.azure.com
AZURE_AI_API_KEY=<your-api-key>
AZURE_OPENAI_DEPLOYMENT=<your-deployment-name>
AZURE_AI_API_VERSION=2024-12-01-preview
```

*(Note: The repository relies on `core/policies.json` to define readiness thresholds and required evidence for various insights. You can customize this file to adjust what triggers an alert).*

### Google Credentials
This project connects to Gmail and Google Calendar to extract commitments. 
1. Place your `credentials.json` file in the root directory of the project.
2. The first time you run the backend, it will prompt you in the browser to authorize the application and generate a `token.json` file.

---

## 3. Frontend Setup

The dashboard interface is built using React and Vite. You need to install its dependencies to run it.

Open a new terminal window, navigate to the `frontend/` directory, and install the NPM packages:

```bash
cd frontend
npm install
```

---

## 4. Running the Application

To run the full stack, you will need two separate terminal windows.

**Terminal 1: Start the Backend (FastAPI + Background Workers)**
```bash
python main.py
```
*The backend will run on `http://localhost:8000`. This will automatically start syncing your emails, extracting entities, and running the readiness engine.*

**Terminal 2: Start the Frontend Application**
```bash
cd frontend
npm run dev
```
*The frontend will run on `http://localhost:5173`. Open this URL in your browser to view your live Autonomous Readiness Insights dashboard.*
