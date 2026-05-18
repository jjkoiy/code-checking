# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project Summary

This project is a multi-agent code review system built with FastAPI, LangGraph, SQLAlchemy, Chroma, and an OpenAI-compatible LLM client. It accepts Git diffs through an API, creates review tasks, runs a sequential review pipeline, and returns structured findings plus a Markdown report.

Current phase: P1/P2 working skeleton with functional API, lightweight web console, database persistence, sequential agent orchestration, pattern-based static/security/style checks, mock/optional OpenAI-compatible LLM review, LLM safety gates/redaction, draft test generation, validation, reporting, and pytest coverage for the core flow.

## Development Commands

```powershell
# Create virtual environment and install dependencies
python -m venv myenv
.\myenv\Scripts\activate
pip install -r requirements.txt

# Run the FastAPI dev server
uvicorn app.main:app --reload --port 8000

# Run a Celery worker for review execution
# Requires Redis at REDIS_URL, for example redis://localhost:6379/0
celery -A app.worker.celery_app worker --pool=solo -l info

# Open the local web console after the server starts
# http://127.0.0.1:8000/

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
  -> enqueue durable Celery review task through Redis
  -> worker runs agents sequentially
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
| `POST /api/knowledge/index` | Index repository files into Chroma for review context |

The root web UI is served from `app/static/index.html` and provides a simple console for submitting unified Git diffs, polling review status, and viewing findings, Markdown, and JSON output.

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
| `app/models/findings.py` | Pydantic finding validation and normalization helpers |
| `app/models/report.py` | Pydantic report payload models |
| `app/models/schemas.py` | Pydantic request/response schemas |
| `app/models/state.py` | `ReviewState` and `Finding` TypedDicts |
| `app/routers/reviews.py` | Review task API routes |
| `app/routers/knowledge.py` | Knowledge indexing API route |
| `app/services/knowledge_base.py` | Repository file indexing service |
| `app/services/review_service.py` | Task CRUD, pipeline execution, result persistence |
| `app/services/llm_client.py` | OpenAI-compatible chat completions client |
| `app/services/llm_safety.py` | LLM mode selection and sensitive value redaction |
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
| `app/static/index.html` | Browser-based review console |
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

Finding output is normalized through `FindingModel`. Invalid findings are dropped with validation warnings so final reports consume only the normalized aggregate list.

## Input Validation and LLM Safety

API input validation currently enforces:

- `diff_text` must be a unified Git diff when provided.
- `changed_files` may be used with raw file content when no diff is available.
- `changed_files.file_path` must be a relative repository path without control characters, absolute paths, or `..`.
- `REVIEW_MAX_FILES`, `REVIEW_MAX_DIFF_CHARS`, `REVIEW_MAX_FILE_CONTENT_CHARS`, and `REVIEW_MAX_TOTAL_CONTENT_CHARS` are enforced by request schemas.

LLM safety currently works as follows:

- Default local mode is mock review (`LLM_PROVIDER=mock`, no API key required).
- External LLM calls require both an API key and `LLM_EXTERNAL_ENABLED=true`.
- Redaction is enabled by default through `LLM_REDACTION_ENABLED=true`.
- Sensitive patterns such as API keys, bearer tokens, passwords/secrets, private keys, and common connection strings are redacted before external calls when redaction is enabled.

## Configuration

All configuration is loaded from environment variables.

| Variable | Default | Purpose |
|---|---|---|
| `APP_ENV` | `development` | App environment |
| `DATABASE_URL` | `sqlite:///./data/app.db` | Database connection URL |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis broker/backend for Celery and rate limiting |
| `API_AUTH_ENABLED` | `false` | Require `X-API-Key` for review APIs |
| `API_KEYS` | empty | Comma-separated accepted API keys |
| `RATE_LIMIT_REQUESTS_PER_MINUTE` | `60` | Per-key/IP fixed-window API limit |
| `LLM_PROVIDER` | `mock` | LLM provider; use `mock` for local heuristic mode |
| `LLM_MODEL` | `mock-reviewer` | LLM model name |
| `LLM_API_KEY` | empty | LLM API key |
| `LLM_BASE_URL` | empty | OpenAI-compatible API base URL |
| `LLM_EXTERNAL_ENABLED` | `false` | Gate for making external LLM calls |
| `LLM_REDACTION_ENABLED` | `true` | Redact sensitive values before external LLM calls |
| `LLM_TIMEOUT_SECONDS` | `60` | LLM request timeout |
| `CHROMA_PATH` | `./data/chroma` | Chroma persistence path |
| `REVIEW_MAX_FILES` | `20` | Planned review file-count limit |
| `REVIEW_MAX_DIFF_CHARS` | `60000` | Diff characters sent to LLM prompt |
| `REVIEW_MAX_FILE_CONTENT_CHARS` | `200000` | Per-file raw content size limit |
| `REVIEW_MAX_TOTAL_CONTENT_CHARS` | `500000` | Total raw changed file content size limit |
| `AGENT_MAX_RETRY` | `2` | Planned agent retry limit |
| `VALIDATION_MAX_RETRY` | `2` | Planned validation retry limit |
| `AGENT_EXECUTION_MODE` | `sequential` | Review pipeline mode; use `parallel` to run independent analysis stages concurrently |
| `KNOWLEDGE_MAX_FILES` | `500` | Maximum files indexed per repository request |
| `KNOWLEDGE_MAX_FILE_CHARS` | `100000` | Maximum characters read from a single indexed file |
| `KNOWLEDGE_CHUNK_CHARS` | `2000` | Approximate text chunk size for repository indexing |

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
- mock LLM review returns local heuristic findings and avoids non-code/plain-text false positives
- external LLM calls are gated and redacted before use
- changed file metadata merge preserves request-provided content
- request schema validation covers missing input, unsafe paths, diff shape, file count, diff size, and content size limits
- security scan edge cases cover command execution, safe subprocess usage, and YAML safe loading
- aggregation normalizes findings and drops invalid entries with warnings
- report output includes metadata, review scope, empty/no-content states, severity counts, and normalized findings only
- report node marks pipeline errors as failed
- router behavior covers failed reports with and without partial output
- review service persists stage progress, completed reports, and findings

Run:

```powershell
.\myenv\Scripts\python.exe -m pytest tests -q
```

Last verified result:

```text
76 passed
```

## Docker

Build and run:

```powershell
docker build -t agent-review-system .
docker run --rm -p 8000:8000 agent-review-system
```

For persistent SQLite and Chroma data, mount a volume for `/app/data`.

## Current Limitations

- API Key authentication and Redis-backed rate limiting are available, but there is no user, role, or tenant model yet.
- Input size limits are enforced by request schemas, but API/server-level body limits are not configured yet.
- Review execution now uses Celery and Redis, but there is no task administration UI or dead-letter workflow yet.
- `current_stage` is persisted through stage callbacks, but there is still no durable job history table.
- LLM output is normalized before final reporting, but external LLM behavior still needs stronger production policy and observability.
- Diff or source content may contain secrets; external LLM calls are gated and redacted by default, but production deployments should still review policy and audit requirements.
- Chroma can index repository files for project context, but there is no scheduled re-indexing or deletion sync yet.
- Generated tests are drafts and are not automatically written to the target repo or executed.
- Type checking is not clean yet.

## Working Guidance for Codex

- Preserve the existing FastAPI + service + agent module structure.
- Prefer small incremental changes over broad rewrites.
- Read the relevant file before editing it.
- Keep tests focused on behavior, especially pipeline state, finding quality, persistence, and API responses.
- Avoid introducing network-dependent tests.
- Do not commit secrets or real API keys.
