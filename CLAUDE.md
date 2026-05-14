# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development commands

```bash
# Create virtual environment and install dependencies
python -m venv myenv
source myenv/Scripts/activate  # Windows
pip install -r requirements.txt

# Run the FastAPI dev server
uvicorn app.main:app --reload --port 8000

# Run type checking (no config yet — use basic mypy)
pip install mypy && mypy app/
```

No test suite or linter is configured yet (P0 skeleton phase).

## Architecture

This is a **multi-agent code review system** built on FastAPI + LangGraph (planned) + Chroma (planned) + SQLAlchemy. It accepts Git diffs via API, runs them through a pipeline of specialized review agents, and returns structured findings with a Markdown report.

**Current phase: P0 skeleton.** The REST API and database layer are functional. All agent logic is stubbed out — each agent returns empty results. The orchestrator runs a sequential no-op pipeline.

### Request flow

```
POST /api/reviews  →  creates task (DB INSERT, status=pending)
                    →  background task triggers review pipeline
                    →  pipeline updates task with findings + report (status=completed/failed)
GET  /api/reviews/{id}         →  returns task status + current stage
GET  /api/reviews/{id}/report  →  returns Markdown + JSON report
```

### Key files

| File | Purpose |
|---|---|
| `app/main.py` | FastAPI app with lifespan-managed DB init |
| `app/config.py` | `Settings` dataclass — all config from env vars with defaults |
| `app/database.py` | SQLAlchemy engine/session/Base; `init_db()` imports model + creates tables |
| `app/models/review_task.py` | `ReviewTask` ORM model — includes `findings_json`, `report_json`, `report_markdown` |
| `app/models/schemas.py` | Pydantic request/response schemas including `ReviewReportResponse` |
| `app/models/state.py` | `ReviewState` and `Finding` TypedDicts — the shared state shape for the LangGraph pipeline |
| `app/routers/reviews.py` | `POST /api/reviews`, `GET /api/reviews/{task_id}`, `GET /api/reviews/{task_id}/report` |
| `app/services/review_service.py` | DB CRUD + `run_review_and_save()` wires pipeline execution to API |
| `app/agents/orchestrator.py` | LangGraph `StateGraph` — builds and invokes the sequential P1 pipeline |
| `app/agents/context_builder.py` | Parses git diff, detects languages, builds `project_context` |
| `app/agents/static_analysis.py` | Pattern-based analysis: bare except, SQL f-strings, mutable defaults, etc. (8 rules) |
| `app/agents/security_scan.py` | Pattern-based security scan: SQL injection, hardcoded secrets, eval, pickle, etc. (8 rules) |
| `app/agents/style_check.py` | Basic style checks: TODO/FIXME detection in changed files |
| `app/agents/finding_aggregator.py` | Dedup by file+category+title similarity, severity normalization, blocking marker |
| `app/agents/llm_review.py` | Mock LLM review — generates findings based on keyword heuristics (auth, db, api, error, input) |
| `app/agents/report.py` | Generates Markdown + JSON report from aggregated + LLM findings |
| `app/agents/test_*.py` | P2 stubs — return empty results |
| `app/agents/validation.py` | P2 stub — returns `not_run` |

### Configuration

All settings live in env vars:

- `DATABASE_URL` — defaults to `sqlite:///./data/app.db`
- `LLM_PROVIDER` / `LLM_MODEL` / `LLM_API_KEY` — LLM config (used by `llm_review.py` for logging; real calls deferred to P2)
- `AGENT_MAX_RETRY` / `VALIDATION_MAX_RETRY` — retry limits (not yet wired into the graph)

### Agent pipeline (P1 — sequential)

```
ContextBuilder → StaticAnalysis → StyleCheck → SecurityScan → TestImpact
→ FindingAggregator → LLMReview (mock) → TestGeneration (stub) → Validation (stub) → Report
```

Each node reads/writes `ReviewState`. The LangGraph `StateGraph` is in `orchestrator.py`. P2 will add parallel fan-out for the analysis phase and conditional routing (skip security scan for low-risk diffs, validation loop for test generation).

The full target architecture (parallel agents, validation loop, Chroma retrieval) is documented in `AGENT_SYSTEM_TECHNICAL_DESIGN.md`.

### Database

Single `review_tasks` table with columns: task metadata, `diff_text`, `findings_json`, `report_json`, `report_markdown`. Auto-created on startup. The design doc specifies additional tables (`changed_files`, `findings`, `reports`) for future phases.

### Findings data model

Each finding dict: `agent_name`, `severity` (low/medium/high/critical), `category`, `file_path`, `line_number`, `title`, `description`, `evidence`, `suggestion`, `confidence` (0-1), `blocking` (bool). Security findings add `attack_scenario`. The aggregator sets `source_agents` (list of agent names that found this issue).
