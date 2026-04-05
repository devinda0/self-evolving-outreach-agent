# Signal to Action — Self-Evolving Outreach Agent

> A closed-loop, multi-agent growth intelligence platform built for **Veracity Deep Hack**.

Takes a product through a complete campaign cycle — live market research, content generation, multi-channel deployment, engagement feedback ingestion, and intelligence refinement — inside a single conversational interface, without tool switching or context loss.

---

## What It Does

1. **Research** — Parallel market intelligence across competitor, audience, channel, and market threads (Tavily + Gemini)
2. **Segment** — Derives target segments from findings, scores prospects, renders a clickable ProspectPicker
3. **Generate** — Creates traceable A/B content variants grounded in research findings, each with a hypothesis
4. **Deploy** — Personalizes and sends across email (Resend) and LinkedIn (Unipile) with full A/B cohort tracking
5. **Feedback** — Ingests webhook events, correlates to deployment records, updates finding confidence
6. **Loop** — Each cycle starts sharper than the last from accumulated intelligence

---

## Stack

| Layer | Technology |
|---|---|
| LLM | Gemini 2.5 Pro |
| Agent orchestration | LangGraph |
| Backend | FastAPI + WebSocket |
| Frontend | React + Zustand + Vite |
| Database | MongoDB Atlas (motor async) |
| Email | Resend |
| LinkedIn | Unipile |
| Search | Tavily |

---

## Project Structure

```
self-evolving-outreach-agent/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI entry point
│   │   ├── api/                 # Route handlers (campaign, webhooks, health)
│   │   ├── agents/              # LangGraph agent nodes
│   │   │   ├── graph.py         # Full graph topology
│   │   │   ├── orchestrator.py  # Intent classification + routing
│   │   │   ├── research/        # Research subgraph (fan-out/fan-in)
│   │   │   ├── segment_agent.py # Prospect scoring + selection
│   │   │   ├── content_agent.py # A/B variant generation
│   │   │   ├── deployment_agent.py
│   │   │   └── feedback_agent.py
│   │   ├── memory/              # Memory Manager + context bundles
│   │   ├── models/              # Pydantic schemas (CampaignState, etc.)
│   │   ├── tools/               # External tool wrappers (Tavily, Resend, Unipile)
│   │   └── db/                  # MongoDB motor client + CRUD
│   ├── tests/
│   │   └── integration/         # End-to-end loop tests
│   ├── Dockerfile
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── components/          # UI components (BriefingCard, VariantGrid, etc.)
│   │   ├── store/               # Zustand campaign store
│   │   ├── hooks/               # useWebSocket hook
│   │   └── App.tsx
│   └── .env.example
├── .github/
│   └── workflows/
│       ├── ci.yml               # Lint + type-check + unit tests on every push
│       ├── integration.yml      # Full loop integration tests on PR to main
│       └── deploy.yml           # Auto-deploy to Railway on merge to main
└── docker-compose.yml           # Local MongoDB + backend
```

---

## Local Setup

### Prerequisites

- Python 3.11+
- Node 20+
- Docker (for local MongoDB)
- API keys: Gemini, Tavily, Resend, Unipile

### 1. Clone and configure

```bash
git clone https://github.com/devinda0/self-evolving-outreach-agent.git
cd self-evolving-outreach-agent

cp backend/.env.example backend/.env
# Fill in your API keys in backend/.env

cp frontend/.env.example frontend/.env
```

### 2. Start MongoDB locally

```bash
docker-compose up mongodb -d
```

### 3. Run the backend

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
# → http://localhost:8000
```

### 4. Run the frontend

```bash
cd frontend
npm install
npm run dev
# → http://localhost:5173
```

### 5. Run tests

```bash
cd backend

# Unit tests only (no API keys needed)
pytest tests/ -m "not integration" -v

# Integration tests (needs MongoDB + USE_MOCK_LLM=true)
pytest tests/integration/ -m integration -v
```

---

## GitHub Issues & Roadmap

All 29 issues are tracked on the [Issues page](https://github.com/devinda0/self-evolving-outreach-agent/issues), broken down by phase:

| Phase | Days | Issues |
|---|---|---|
| Skeleton | 1–2 | #1–6, #27, #29 |
| Infra (CI/CD) | 1 | #7–8 |
| Research Agent | 3–4 | #9–12 |
| Segment Agent | 4–5 | #13–14 |
| Content Agent | 5–6 | #15–16, #18 |
| Feedback Agent | 7–8 | #19–21, #26 |
| Memory Manager | 8–9 | #22–23, #28 |
| Deploy Agent (real) | 9–10 | #17, #24–25 |

---

## CI/CD

- **Every push** → lint + type-check + unit tests (no API keys needed)
- **Every PR to main** → full integration test with real MongoDB service
- **Merge to main** → auto-deploy backend to Railway

### Required GitHub Secrets

```
GEMINI_API_KEY
TAVILY_API_KEY
RAILWAY_TOKEN
```

---

## Environment Variables

See `backend/.env.example` for the full list. Key flags:

```bash
USE_MOCK_SEND=true    # safe for local dev — no real emails/DMs sent
USE_MOCK_LLM=false    # set true to bypass Gemini in tests
```

---

## Team

Built by a 3-person team for Veracity Deep Hack.

- **Backend / LangGraph** — agents, graph topology, Memory Manager
- **Frontend / React** — UI components, WebSocket streaming, Zustand store
- **Data / Integrations** — MongoDB, Tavily, Resend, Unipile, webhooks
