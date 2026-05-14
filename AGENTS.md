# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project Summary

This project is a multi-agent code review system built with FastAPI, LangGraph, SQLAlchemy, Chroma, and an OpenAI-compatible LLM client. It accepts Git diffs through an API, creates review tasks, runs a sequential review pipeline, and returns structured findings plus a Markdown report.

Current phase: P1 skeleton with functional API, database persistence, sequential agent orchestration, pattern-based static/security/style checks, mock/optional LLM review, draft test generation, validation, reporting, and pytest coverage for the core flow.

## Development Commands

```powershell
# Create virtual environment and install dependencies
python -m venv myenv
.\myenv\Scripts\activate
pip install -r requirements.txt

# Run the FastAPI dev server
uvicorn app.main:app --reload --port 8000

# Run tests
python -m pytest tests -q

# Compile check
python -m compileall app tests

# Optional type checking
pip install mypy
mypy app/
```

Notes:

- The project currently uses `pytest` for tests.
- `mypy` is not yet configured as a clean quality gate. There are known type-checking issues around SQLAlchemy ORM declarations and third-party stubs.

## Runtime Flow

```text
POST /api/reviews
  -> create ReviewTask in DB with status=pending
  -> schedule background review pipeline
  -> run agents sequentially
  -> save findings_json, report_json, report_markdown
  -> set task status to completed or failed

GET /api/reviews/{task_id}
  -> return current task status and metadata

GET /api/reviews/{task_id}/report
  -> return Markdown report, JSON report, and generated test drafts
```

## API Endpoints

| Endpoint | Purpose |
|---|---|
| `GET /health` | Health check |
| `POST /api/reviews` | Create a review task from diff and/or changed files |
| `GET /api/reviews/{task_id}` | Get task status |
| `GET /api/reviews/{task_id}/report` | Get final or in-progress report response |

## Architecture

The app is organized around a service layer plus a sequential LangGraph agent pipeline.

```text
FastAPI router
  -> review_service
  -> database ReviewTask
  -> orchestrator StateGraph
  -> agents
  -> report
  -> persisted task result
```

### Agent Pipeline

```text
ContextBuilder
  -> StaticAnalysis
  -> StyleCheck
  -> SecurityScan
  -> TestImpact
  -> FindingAggregator
  -> LLMReview
  -> TestGeneration
  -> Validation
  -> Report
```

Each node reads and updates `ReviewState`. If a node records an error, the final report includes `pipeline_errors`, and the task is marked as failed by the service layer.

## Key Files

| File | Purpose |
|---|---|
| `app/main.py` | FastAPI app with lifespan-managed database initialization |
| `app/config.py` | `Settings` dataclass loaded from environment variables |
| `app/database.py` | SQLAlchemy engine/session/Base and schema initialization |
| `app/models/review_task.py` | `ReviewTask` ORM model |
| `app/models/schemas.py` | Pydantic request/response schemas |
| `app/models/state.py` | `ReviewState` and `Finding` TypedDicts |
| `app/routers/reviews.py` | Review task API routes |
| `app/services/review_service.py` | Task CRUD, pipeline execution, result persistence |
| `app/services/llm_client.py` | OpenAI-compatible chat completions client |
| `app/services/vector_store.py` | Chroma vector search wrapper with seed documents |
| `app/agents/orchestrator.py` | LangGraph `StateGraph` construction and execution |
| `app/agents/context_builder.py` | Diff parsing, language detection, project context construction |
| `app/agents/diff_utils.py` | Unified diff added-line parsing and line-number mapping |
| `app/agents/static_analysis.py` | Pattern-based static analysis |
| `app/agents/security_scan.py` | Pattern-based security scanning |
| `app/agents/style_check.py` | TODO/FIXME/HACK checks on added lines |
| `app/agents/finding_aggregator.py` | Deduplication, severity normalization, blocking marker |
| `app/agents/llm_review.py` | LLM or mock heuristic review |
| `app/agents/test_impact.py` | Test impact analysis and suggested test types |
| `app/agents/test_generation.py` | Draft test plan and generated test snippets |
| `app/agents/validation.py` | Structural validation for generated tests |
| `app/agents/report.py` | Markdown and JSON report generation |
| `tests/` | pytest suite for core behavior |

## Implemented Review Capabilities

Static analysis currently detects:

- Bare `except:`
- Empty `except` blocks
- Mutable default arguments
- `print()` in Python code
- SQL f-string interpolation
- Broad `except Exception`
- Hardcoded absolute paths
- `open()` without a context manager

Security scan currently detects:

- Potential SQL injection
- Hardcoded secrets or credentials
- Command injection patterns
- `eval` / `exec` / `compile`
- Insecure deserialization
- Weak hash algorithms
- Hardcoded HTTP URLs
- Debug mode enabled

Style check currently detects:

- `TODO`
- `FIXME`
- `HACK`

Findings include:

- `agent_name`
- `severity`
- `category`
- `file_path`
- `line_number`
- `title`
- `description`
- `evidence`
- `suggestion`
- `confidence`
- `blocking`
- optional `attack_scenario`
- optional `source_agents`

## Configuration

All configuration is loaded from environment variables.

| Variable | Default | Purpose |
|---|---|---|
| `APP_ENV` | `development` | App environment |
| `DATABASE_URL` | `sqlite:///./data/app.db` | Database connection URL |
| `LLM_PROVIDER` | `openai` | LLM provider; use `mock` for local heuristic mode |
| `LLM_MODEL` | `gpt-4.1-mini` | LLM model name |
| `LLM_API_KEY` | empty | LLM API key |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible API base URL |
| `LLM_TIMEOUT_SECONDS` | `60` | LLM request timeout |
| `CHROMA_PATH` | `./data/chroma` | Chroma persistence path |
| `REVIEW_MAX_FILES` | `20` | Planned review file-count limit |
| `REVIEW_MAX_DIFF_CHARS` | `60000` | Diff characters sent to LLM prompt |
| `AGENT_MAX_RETRY` | `2` | Planned agent retry limit |
| `VALIDATION_MAX_RETRY` | `2` | Planned validation retry limit |

## Database

The current database has one main table:

`review_tasks`

Important columns:

- task metadata: `id`, `source_type`, `repo_name`, `repo_path`, `base_ref`, `head_ref`
- input: `diff_text`, `changed_files_json`
- status: `status`, `current_stage`, `error_message`
- output: `findings_json`, `report_json`, `report_markdown`
- timestamps: `created_at`, `updated_at`

The schema is auto-created on startup. A tiny SQLite migration helper currently adds `changed_files_json` if missing.

## Tests

The test suite lives in `tests/`.

Current coverage:

- diff parsing and new-file line-number mapping
- static/security/style findings include file path and line number
- mock LLM review returns local heuristic findings
- changed file metadata merge preserves request-provided content
- report node marks pipeline errors as failed
- review service persists completed reports and findings

Run:

```powershell
.\myenv\Scripts\python.exe -m pytest tests -q
```

Last known result:

```text
7 passed
```

## Docker

Build and run:

```powershell
docker build -t agent-review-system .
docker run --rm -p 8000:8000 agent-review-system
```

For persistent SQLite and Chroma data, mount a volume for `/app/data`.

## Current Limitations

- No authentication, authorization, rate limiting, or tenant isolation yet.
- Input size limits are configured but not fully enforced at the API/service boundary.
- FastAPI `BackgroundTasks` is not a durable job queue. Long-running production use should move to a real worker system.
- `current_stage` is not persisted after every pipeline node.
- LLM output needs stricter schema validation and safer fallback behavior before production use.
- Diff or source content may contain secrets; external LLM calls should be gated by policy and redaction.
- Chroma currently uses seed docs and deterministic hash embeddings, not a real project knowledge base.
- Generated tests are drafts and are not automatically written to the target repo or executed.
- Type checking is not clean yet.

## Working Guidance for Codex

- Preserve the existing FastAPI + service + agent module structure.
- Prefer small incremental changes over broad rewrites.
- Read the relevant file before editing it.
- Keep tests focused on behavior, especially pipeline state, finding quality, persistence, and API responses.
- Avoid introducing network-dependent tests.
- Do not commit secrets or real API keys.
