# UK Company Risk Monitor

An agentic AI pipeline that produces structured, cited risk reports for UK
limited companies using live data from Companies House.

Built as a portfolio project to demonstrate production-grade Python
engineering: async FastAPI, agentic tool-calling with the Anthropic SDK,
SQLAlchemy with Alembic migrations, and a fully tested pipeline from HTTP
layer to deterministic scoring.

---

## What it does

Given a Companies House number, the system:

1. Pulls live data across six endpoints (profile, officers, PSC, filing
   history, insolvency, charges) and caches it in Postgres
2. Runs a deterministic scoring pass to extract named risk signals
   (overdue accounts, insolvency history, director turnover, missing PSC
   data, outstanding charges)
3. Passes those signals to a Claude agent via a tool-calling loop — the
   agent gathers evidence, reasons across it, and calls a `submit_report`
   tool with a structured, cited report
4. Renders the report in an HTMX dashboard without a full page reload

---

## Architecture

```
Companies House API ──────────────────────────────┐
(profile, officers, PSC,                          │
 filings, insolvency, charges)                    ▼
                                        Agent orchestrator
NewsAPI / GDELT ───────── Phase 2 ──►  (Claude tool-calling loop)
(adverse media)                                   │
                                                  ▼
                                          Risk report
                                   (scored, cited findings)
                                          │         │
                                          ▼         ▼
                                      Dashboard  Scheduled
                                      (HTMX)     monitor
                                                 (Phase 2)
```

---

## Tech stack

| Layer | Technology |
|---|---|
| API | FastAPI + Python 3.11 |
| Agent | Anthropic SDK (claude-sonnet-4-6), custom tool-calling loop |
| Database | PostgreSQL (async via SQLAlchemy 2.0 + asyncpg) |
| Migrations | Alembic (async template) |
| Dashboard | Jinja2 + HTMX |
| Testing | pytest-asyncio, respx, FastAPI TestClient |
| Lint / types | ruff, mypy |
| CI | GitHub Actions |
| Deploy | Railway (Docker) |

---

## Risk signals

### Financial

| Signal | Weight |
|---|---|
| Company status is liquidation / administration / receivership | 50 |
| Insolvency practitioner cases on record | 40 |
| Annual accounts overdue | 25 |
| Outstanding charges (mortgages/debentures) | 5 per charge, max 20 |
| Confirmation statement overdue | 15 |
| No filings in 18+ months | 10 |

### Compliance / governance

| Signal | Weight |
|---|---|
| No active directors on record | 40 |
| No persons with significant control (PSC) registered | 20 |
| Director turnover rate > 50% (min 2 officers) | 20 |

Overall score = (financial × 0.6) + (compliance × 0.4), capped at 100.

---

## Known limitations

- **No court judgment data** — UK county court judgments (Trust Online)
  require a paid licence. The README documents this gap rather than
  scraping around it.
- **Adverse media is Phase 2** — news/media signals are not yet
  implemented. The architecture is designed to add them as a third scoring
  category without restructuring the agent or the report schema.
- **Agent tool calls hit the live API** — the cache warms before the agent
  runs, but the agent's own tool calls currently re-fetch live rather than
  reading from the cached row. This is a known limitation documented in
  `app/services/analysis.py` and is the first item on the Phase 2 list.

---

## Local development

### Prerequisites

- Python 3.11
- Docker and Docker Compose
- A free Companies House API key:
  https://developer.company-information.service.gov.uk
- An Anthropic API key: https://console.anthropic.com

### Setup

```bash
git clone https://github.com/mrDanbatta/UK_company_risk_monitor
cd UK_company_risk_monitor

python3.11 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

pip install -e ".[dev]"

cp .env.example .env
# fill in COMPANIES_HOUSE_API_KEY and ANTHROPIC_API_KEY in .env
```

### Run with SQLite (quickest)

```bash
alembic upgrade head
uvicorn app.main:app --reload
```

Open http://localhost:8000 and enter a Companies House number.

### Run with Docker Compose (Postgres parity)

```bash
docker compose up --build
```

Open http://localhost:8000.

---

## Running the tests

```bash
pytest -v
```

| Test file | What it covers |
|---|---|
| `test_connectors.py` | Companies House HTTP client, 404/429 handling |
| `test_scoring.py` | 23 deterministic risk signal assertions |
| `test_agent.py` | Agent loop control flow, tool error handling, max-turns cap |
| `test_routes.py` | HTTP status codes, error mapping, HTMX fragment shape |

All tests run without network access or real API keys — everything is
mocked at the boundary.

---

## Project structure

```
app/
├── agent/
│   ├── orchestrator.py   # tool-calling loop
│   ├── tools.py          # tool schemas + dispatch
│   └── prompts.py        # system prompt
├── connectors/
│   └── companies_house.py
├── models/
│   ├── company.py        # cached CH data
│   └── report.py         # risk reports
├── routes/
│   ├── companies.py      # JSON API
│   └── dashboard.py      # HTML dashboard
└── services/
    ├── analysis.py       # orchestrates cache + agent + persistence
    ├── cache.py          # get-or-fetch pattern
    └── risk_scoring.py   # deterministic scoring
```

---

## Phase 2 roadmap

- [ ] Adverse media signal (news/GDELT integration, LLM-classified relevance)
- [ ] Watchlist + scheduled re-monitoring (APScheduler, diff detection)
- [ ] Email alerts on material changes (new charge, director disqualified)
- [ ] Refactor agent tools to read from cache instead of re-fetching live
- [ ] Historical trend charts per company
