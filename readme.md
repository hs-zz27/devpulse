> **DevPulse** is an AI-powered code review and engineering analytics platform. It auto-reviews every GitHub pull request with a Gemini ReAct agent, tracks DORA metrics, and lets your team ask questions about engineering activity in plain English.
> 

**Live demo:** devpulse-three-mu.vercel.app

**Repository:** github.com/hs-zz27/devpulse

---

## Overview

DevPulse solves three problems engineering teams hit as they grow:

| Problem | How DevPulse helps |
| --- | --- |
| Code reviews are slow and inconsistent | An AI agent reviews every PR and posts structured, risk-scored feedback on GitHub |
| No clear view of delivery performance | Stores review and deployment data in PostgreSQL and computes the four DORA metrics |
| Analytics tools are expensive and opaque | Open source, self-hostable, and queryable in plain English through an AI chat |

The system is split into an **API server**, a **background worker**, and a **React dashboard**, connected by a **Redis Streams** queue for reliable, asynchronous PR processing.

---

## Features

- **Automated PR reviews** — a Gemini ReAct agent fetches the diff, scores risk, and posts a structured review comment back to the pull request.
- **Deterministic risk scoring** — a transparent heuristic (lines changed, files touched, migrations, auth/API changes, test ratio) produces a 0–100 score and a `LOW` / `MEDIUM` / `HIGH` level.
- **DORA metrics** — deployment frequency, lead time for changes, change failure rate, and mean time to restore, with elite/high/medium/low classification.
- **Natural-language analytics chat** — ask questions like *"which repo had the most critical issues last sprint?"* and get a plain-English answer backed by a safe, read-only SQL query.
- **Real-time updates** — Server-Sent Events stream review completions to the dashboard with no polling.
- **Production hardening** — HMAC-verified webhooks, JWT auth, per-user rate limiting, and a circuit breaker around the GitHub API.
- **Full observability** — Prometheus metrics and Grafana dashboards for webhooks, queue depth, and review durations.

---

## Architecture

```mermaid
flowchart TD
    GH["GitHub: PRs and Deployments"] -->|"POST /webhooks/github"| API["FastAPI API Server"]
    API -->|"XADD"| RQ["Redis Streams Queue"]
    API -->|"read / write"| DB[("PostgreSQL")]
    RQ -->|"XREADGROUP"| W["Background Worker"]
    W -->|"Gemini ReAct loop"| AI["Gemini API"]
    W -->|"post review comment"| GH
    W -->|"write review"| DB
    W -->|"SSE event"| API
    API -->|"text/event-stream"| FE["React Dashboard"]
    API -->|"/metrics"| PROM["Prometheus"]
    PROM --> GRAF["Grafana"]
```

**Flow in words:** GitHub sends a webhook, the API verifies it and enqueues a task, the worker pulls the task and runs the AI review, results are written to PostgreSQL and pushed live to the dashboard, and Prometheus/Grafana observe the whole pipeline.

---

## Tech Stack

### Backend

| Layer | Technology |
| --- | --- |
| Web framework | FastAPI + Uvicorn |
| Validation / config | Pydantic v2 + pydantic-settings |
| ORM / driver | SQLAlchemy (async) + asyncpg |
| Migrations | Alembic |
| Queue | Redis Streams (redis-py) |
| HTTP client | httpx |
| Auth | python-jose (JWT) + cryptography (HMAC) |
| AI / LLM | Google Generative AI SDK (Gemini), Groq (chat) |
| SQL safety | sqlglot (AST validation) |
| Metrics | prometheus-client |

### Frontend

| Technology | Role |
| --- | --- |
| React + Vite | UI and build tooling |
| Recharts | DORA metric visualizations |
| EventSource API | SSE live review feed |

### Infrastructure

| Tool | Role |
| --- | --- |
| Docker + Docker Compose | Local multi-service orchestration |
| GitHub Actions | Lint, test, build, and push pipeline |
| GitHub Container Registry | Docker image hosting |
| Prometheus + Grafana | Metrics and dashboards |

---

## Project Structure

```
devpulse/
├── backend/
│   ├── app/
│   │   ├── api/            # auth, repos, webhooks, reviews, metrics, chat
│   │   ├── agent/          # Gemini ReAct loop + prompts
│   │   ├── core/           # config, database, security, rate_limit, circuit_breaker
│   │   ├── queue/          # Redis Streams producer + consumer group
│   │   ├── models/         # SQLAlchemy ORM models
│   │   └── main.py         # FastAPI entrypoint
│   ├── tests/
│   └── alembic/            # migrations
├── worker/
│   ├── main.py             # background worker process
│   └── Dockerfile
├── frontend/               # React + Vite dashboard
├── monitoring/             # prometheus.yml + grafana provisioning
├── .github/workflows/ci.yml
├── docker-compose.yml
└── .env.example
```

---

## Getting Started

### Prerequisites

- Docker and Docker Compose
- A GitHub OAuth App (client ID + secret)
- A Gemini API key (and optionally a Groq API key for the chat feature)

### Clone

```bash
git clone https://github.com/hs-zz27/devpulse.git
cd devpulse
cp .env.example .env
```

Fill in `.env` (see **Environment Variables** below), then start the stack.

---

## Environment Variables

Create a `.env` file in the project root:

```
# Core
ENVIRONMENT=development
SECRET_KEY=change_me_to_a_long_random_string

# Database (PostgreSQL)
DATABASE_URL=postgresql+asyncpg://devpulse:devpulse@postgres:5432/devpulse

# Redis
REDIS_URL=redis://redis:6379

# GitHub OAuth
GITHUB_CLIENT_ID=your_github_oauth_client_id
GITHUB_CLIENT_SECRET=your_github_oauth_client_secret

# AI
GEMINI_API_KEY=your_gemini_api_key
GROQ_API_KEY=your_groq_api_key
GROQ_MODEL=llama-3.1-8b-instant

# Webhooks
WEBHOOK_SECRET=change_me_to_a_strong_secret

# URLs
BASE_URL=http://localhost:8000
FRONTEND_URL=http://localhost:3000

# Misc
DISPLAY_TIMEZONE=Asia/Kolkata
```

<aside>
⚠️

Never commit `.env` — it is already in `.gitignore`. Generate strong secrets with `openssl rand -hex 32`.

</aside>

---

## Running Locally

Start the full six-service stack with Docker Compose:

```bash
docker compose up -d
```

This starts:

| Service | Port | Description |
| --- | --- | --- |
| api | 8000 | FastAPI server |
| worker | — | Background PR review processor |
| postgres | 5432 | Primary data store |
| redis | 6379 | Message queue + rate limiting |
| prometheus | 9090 | Metrics scraper |
| grafana | 3001 | Metrics dashboards |

For day-to-day development you can also run the pieces directly:

```bash
# Start only the infrastructure
docker compose up postgres redis -d

# API (terminal 1)
cd backend && uvicorn app.main:app --reload --port 8000

# Worker (terminal 2)
PYTHONPATH=backend python worker/main.py

# Frontend (terminal 3)
cd frontend && npm run dev
```

Useful URLs:

- API docs: `http://localhost:8000/docs`
- Raw metrics: `http://localhost:8000/metrics`
- Dashboard: `http://localhost:3000`

---

## Database Migrations

Migrations are managed with Alembic:

```bash
cd backend

# Create a new migration after changing models
alembic revision --autogenerate -m "describe change"

# Apply migrations
alembic upgrade head

# Roll back the latest migration
alembic downgrade -1
```

---

## API Reference

| Method | Endpoint | Description |
| --- | --- | --- |
| GET | `/auth/github/login` | Redirect to GitHub OAuth authorization |
| GET | `/auth/github/callback` | Exchange code for token, issue JWT cookies |
| GET | `/repos/github` | List the user's GitHub repositories |
| POST | `/repos/connect` | Connect a repo and register its webhook |
| PUT | `/repos/{id}/guidelines` | Set custom AI review rules for a repo |
| POST | `/webhooks/github` | Receive webhook, verify HMAC, enqueue review |
| GET | `/reviews/` | Review history and PR detail |
| GET | `/reviews/stream` | SSE live review feed |
| GET | `/metrics/dora/{repo_id}` | DORA metrics for a repository |
| POST | `/chat/` | Natural-language analytics query |
| GET | `/metrics` | Prometheus scrape endpoint |

---

## How a Review Works

1. A developer opens or updates a PR on a connected repository.
2. GitHub sends `POST /webhooks/github` with an `X-Hub-Signature-256` header.
3. The API verifies the HMAC signature against the repo's stored secret.
4. The API extracts the PR payload and `XADD`s a task to Redis Streams, then returns `200` immediately.
5. The worker pulls the task with `XREADGROUP` (blocking, 2s timeout).
6. The worker runs the Gemini ReAct agent, which calls its tools:
    - `fetch_pr_diff` — pulls the changed files from the GitHub API.
    - `calculate_risk_score` — deterministic 0–100 risk heuristic.
    - `post_pr_comment` — posts the structured review back to GitHub.
7. The worker writes the review and its issues to PostgreSQL and `XACK`s the message.
8. An SSE event is pushed so the dashboard updates live.

Typical end-to-end time: **15–60 seconds** from PR open to posted review.

### Risk score heuristic

| Factor | Points |
| --- | --- |
| Total lines over 500 | +30 |
| Total lines over 200 | +15 |
| Files changed over 20 | +20 |
| DB migrations present | +25 |
| Auth files touched | +20 |
| API contracts modified | +15 |
| Test file ratio over 30% | −10 |
| Zero test files | +10 |

The score is clamped to 0–100. Levels: `LOW` (under 30), `MEDIUM` (30–60), `HIGH` (60 and above).

---

## AI Chat (Natural Language to SQL)

The chat endpoint turns a plain-English question into a safe, read-only SQL query, runs it, and summarizes the result.

```
User question
  -> LLM generates SQL (JSON output, temperature 0)
  -> sqlglot AST parsing and validation
  -> PostgreSQL execution (statement timeout + LIMIT 100 + RLS)
  -> LLM summarizes rows into a human answer
```

Both a **Gemini** and a **Groq** implementation share the same endpoint contract; Groq (`llama-3.1-8b-instant`) is used when `GROQ_API_KEY` is set, otherwise it falls back to Gemini. The PR review agent itself remains Gemini-based because it relies on Gemini function calling.

---

## Security

- **Webhook verification** — HMAC-SHA256 with `hmac.compare_digest` (timing-safe) against a per-repo secret.
- **Authentication** — short-lived JWT access tokens and long-lived refresh tokens, delivered as HttpOnly cookies; OAuth `state` is compared with `secrets.compare_digest` for CSRF protection.
- **Rate limiting** — sliding-window limiter backed by Redis sorted sets; IP-based on login, user-based on the chat endpoint (20/min, 500/day).
- **Circuit breaker** — wraps GitHub API calls (threshold 5 failures, 60s recovery) to fail fast during outages.
- **NL-to-SQL defense in depth:**
    - Column allow-list — sensitive fields like `webhook_secret` and `agent_trace` are never exposed to the model.
    - Forbidden statements and functions — `INSERT`, `UPDATE`, `DELETE`, `DROP`, `pg_sleep`, `pg_read_file`, and more are blocked.
    - `SELECT *` blocked; single statement only.
    - sqlglot AST validation instead of fragile regex.
    - `SET LOCAL statement_timeout` and a hard `LIMIT 100`.
    - PostgreSQL Row-Level Security via `app.current_user_id` for per-user isolation.

---

## Observability

Prometheus scrapes the API's `/metrics` endpoint every 15 seconds. Key metrics:

| Metric | Type | Meaning |
| --- | --- | --- |
| `devpulse_webhooks_total` | Counter | GitHub webhooks received, labeled by event and action |
| `devpulse_reviews_completed_total` | Counter | AI reviews completed, labeled by status |
| `devpulse_review_duration_seconds` | Histogram | AI review duration |
| `devpulse_queue_depth` | Gauge | Current Redis review-queue depth |

Grafana visualizes these for live monitoring of throughput and latency.

<aside>
📌

The API and worker are separate processes, so worker metrics are exposed on their own port rather than through the API's `/metrics`.

</aside>

---

## CI/CD

GitHub Actions runs on every push and pull request:

1. **lint** — Ruff and mypy.
2. **test** — pytest with coverage.
3. **build** — builds the API and worker Docker images and pushes them to GitHub Container Registry on the `main` branch.

Images are published to:

```
ghcr.io/hs-zz27/devpulse/devpulse-api:latest
ghcr.io/hs-zz27/devpulse/devpulse-worker:latest
```

---

## Deployment

DevPulse runs as a hybrid cloud deployment:

| Component | Platform |
| --- | --- |
| Frontend | Vercel — devpulse-three-mu.vercel.app |
| API + Worker | Render (Docker) |
| PostgreSQL | Neon |
| Redis | Upstash |
| Images | GitHub Container Registry |

After deploying, point your GitHub OAuth app and repository webhooks at the API:

- OAuth callback: `https://<your-api-domain>/auth/github/callback`
- Webhook URL: `https://<your-api-domain>/webhooks/github` (content type `application/json`, secret matching `WEBHOOK_SECRET`)

You can also self-host the entire stack on a single VM with the provided `docker-compose.yml`.

---

## Testing

```bash
cd backend
pytest tests/ -v --cov=app
```

The suite covers the API routes, webhook signature verification, and the NL-to-SQL validation layer (allowed/blocked statements, sensitive-column rejection, multi-statement rejection, and more).

---

## Contributing

Contributions are welcome.

1. Fork the repository and create a feature branch (`git checkout -b feature/your-feature`).
2. Bring up the stack locally with `docker compose up -d` and make your changes.
3. Run the linters and tests and make sure they pass:
    
    ```bash
    cd backend
    ruff check .
    mypy app
    pytest tests/ -v --cov=app
    ```
    
4. Commit, push, and open a pull request with a clear description — DevPulse will review it automatically. 🙂

Please keep PRs focused and include tests for new behavior.

---

## License

Released under the MIT License. See `LICENSE` for details.
