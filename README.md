![CI](https://github.com/jjkoiy/code-checking/actions/workflows/ci.yml/badge.svg)

# Agent Review System

## 项目简介

Agent Review System 是一个基于 FastAPI、LangGraph、SQLAlchemy、Chroma 和 OpenAI 兼容接口构建的多 Agent 代码审查系统。它可以接收 Git diff、本地 Git 分支对比、GitHub PR 或变更文件内容，创建持久化审查任务，并通过静态分析、安全扫描、RAG 风险规则、LLM 评审和测试建议生成结构化审查结果。项目适合用于代码变更预审、安全风险排查、自动化审查原型和 AI Agent 工程实践。

## 项目识别

- 项目类型：后端服务 / AI Agent / 代码审查工具
- 启动入口：`app.main:app`
- 依赖管理：`requirements.txt`
- 配置文件：`.env.example`，运行时会读取根目录 `.env`
- 测试方式：`pytest`
- 部署方式：提供 `Dockerfile` 和 `docker-compose.yml`
- 前端形态：`app/static/index.html` 提供轻量 Web 控制台
- 当前仓库未发现：`package.json`、`pyproject.toml`、`pom.xml`

## 核心功能

- 通过 API 创建代码审查任务，支持统一 Git diff、原始变更文件内容、本地 Git ref 对比和 GitHub PR 输入。
- 使用 Celery + Redis 执行持久化后台审查任务。
- 基于 LangGraph 串联多阶段 Agent 流水线：上下文构建、静态分析、风格检查、安全扫描、RAG 风险审查、测试影响分析、发现聚合、LLM 评审、测试草案生成、验证和报告生成。
- 将任务状态、阶段进度、事件历史、审查发现和 Markdown/JSON 报告持久化到数据库。
- 内置轻量 Web 控制台，可提交 diff、轮询状态并查看报告。
- 支持知识库索引，将仓库代码切片写入 Chroma，并为 RAG 风险审查导入结构化风险规则。
- 默认支持 mock LLM 模式；外部 LLM 调用需要显式开启，并支持敏感信息脱敏。

## 技术栈

- 后端：Python、FastAPI、Pydantic、Uvicorn
- Agent 编排：LangGraph
- 数据库：SQLAlchemy，默认 SQLite
- 后台任务：Celery、Redis
- 向量知识库：Chroma，支持 hash 本地 embedding 和 OpenAI 兼容 embedding 接口
- AI/LLM：OpenAI 兼容 Chat Completions 客户端，默认 `LLM_PROVIDER=mock`
- 前端：原生 HTML/CSS/JavaScript 静态页面
- 测试：pytest
- 部署：Docker

## 项目结构

```text
.
|-- app/
|   |-- main.py                 # FastAPI 应用入口、生命周期初始化、路由和静态资源挂载
|   |-- config.py               # 从环境变量和 .env 加载 Settings
|   |-- database.py             # SQLAlchemy engine/session/Base 和轻量 SQLite schema 补丁
|   |-- worker.py               # Celery 应用和后台审查任务入口
|   |-- agents/                 # LangGraph 审查流水线节点
|   |-- models/                 # ORM 模型、Pydantic schema、ReviewState 类型
|   |-- routers/                # reviews 和 knowledge API 路由
|   |-- services/               # 审查服务、认证、LLM、知识库、向量存储、Git/PR 集成
|   `-- static/
|       `-- index.html          # 浏览器 Web 控制台
|-- tests/                      # pytest 测试
|-- data/                       # 本地运行数据，默认 SQLite 和 Chroma 持久化目录
|-- requirements.txt            # Python 依赖
|-- Dockerfile                  # 容器构建和启动配置
|-- docker-compose.yml          # API + Redis 本地编排配置
|-- .dockerignore               # Docker 构建上下文忽略规则
|-- .env.example                # 环境变量示例
|-- AGENT_SYSTEM_TECHNICAL_DESIGN.md
|-- IMPROVEMENT_PLAN.md
`-- PRODUCT_IMPROVEMENT_ROADMAP.md
```

## 快速开始

### 1. 克隆项目

```powershell
git clone <your-repo-url>
cd code-checking
```

### 2. 创建虚拟环境并安装依赖

```powershell
python -m venv myenv
.\myenv\Scripts\activate
pip install -r requirements.txt
```

### 3. 配置环境变量

```powershell
Copy-Item .env.example .env
```

本地开发默认使用 SQLite、mock LLM 和 `redis://localhost:6379/0`。如果需要让 `/api/reviews` 创建的任务真正进入后台执行，请确保 Redis 可用，并启动 Celery worker。

### 4. 启动 API 服务

```powershell
uvicorn app.main:app --reload --port 8000
```

### 5. 启动 Celery worker

```powershell
celery -A app.worker.celery_app worker --pool=solo -l info
```

### 6. 访问地址

- Web 控制台：http://127.0.0.1:8000/
- OpenAPI 文档：http://127.0.0.1:8000/docs
- 健康检查：http://127.0.0.1:8000/health

## 配置说明

项目会在启动时读取根目录 `.env`，未设置时使用 `app/config.py` 中的默认值。仓库已经提供 `.env.example`。

| 变量 | 默认值 | 说明 |
|---|---|---|
| `APP_ENV` | `development` | 应用环境 |
| `DATABASE_URL` | `sqlite:///./data/app.db` | 数据库连接 |
| `REDIS_URL` | `redis://localhost:6379/0` | Celery broker/backend 和限流 Redis |
| `REDIS_HOST` | `localhost` | 未设置 `REDIS_URL` 时使用的 Redis 主机名；Compose 中为 `redis` |
| `REDIS_PORT` | `6379` | 未设置 `REDIS_URL` 时使用的 Redis 端口 |
| `CELERY_TASK_SOFT_TIME_LIMIT_SECONDS` | `600` | Celery 软超时时间 |
| `CELERY_TASK_TIME_LIMIT_SECONDS` | `660` | Celery 硬超时时间 |
| `CELERY_TASK_MAX_RETRIES` | `2` | Celery 自动重试次数 |
| `API_AUTH_ENABLED` | `false` | 是否开启 `X-API-Key` 鉴权 |
| `API_KEYS` | 空 | 逗号分隔的 API Key 列表 |
| `RATE_LIMIT_REQUESTS_PER_MINUTE` | `60` | 每分钟请求限制，鉴权开启后生效 |
| `LLM_PROVIDER` | `mock` | LLM 提供方，默认本地 mock |
| `LLM_MODEL` | `mock-reviewer` | LLM 模型名 |
| `LLM_API_KEY` | 空 | 外部 LLM API Key |
| `LLM_BASE_URL` | 空 | OpenAI 兼容 API Base URL |
| `LLM_EXTERNAL_ENABLED` | `false` | 是否允许调用外部 LLM |
| `LLM_REDACTION_ENABLED` | `true` | 外部 LLM 调用前是否脱敏 |
| `LLM_TIMEOUT_SECONDS` | `60` | LLM 请求超时 |
| `CHROMA_PATH` | `./data/chroma` | Chroma 持久化目录 |
| `EMBEDDING_PROVIDER` | `hash` | embedding 提供方，可用 `hash` 或 `openai_compatible` |
| `EMBEDDING_MODEL` | `hash-64` | embedding 模型名 |
| `EMBEDDING_API_KEY` | 空 | embedding API Key |
| `EMBEDDING_BASE_URL` | 空 | OpenAI 兼容 embedding Base URL |
| `EMBEDDING_EXTERNAL_ENABLED` | `false` | 是否允许调用外部 embedding 服务 |
| `EMBEDDING_TIMEOUT_SECONDS` | `60` | embedding 请求超时 |
| `RAG_RETRIEVAL_MODE` | `hybrid` | RAG 检索模式：`hybrid`、`vector`、`keyword` |
| `RAG_VECTOR_TOP_K` | `8` | 向量检索数量 |
| `RAG_KEYWORD_TOP_K` | `8` | 关键词检索数量 |
| `RAG_SCORE_THRESHOLD` | `0.0` | RAG 分数阈值 |
| `REVIEW_MAX_FILES` | `20` | 单次审查最大文件数 |
| `REVIEW_MAX_DIFF_CHARS` | `60000` | diff 最大字符数 |
| `REVIEW_MAX_FILE_CONTENT_CHARS` | `200000` | 单文件内容最大字符数 |
| `REVIEW_MAX_TOTAL_CONTENT_CHARS` | `500000` | 总文件内容最大字符数 |
| `AGENT_MAX_RETRY` | `2` | Agent 重试配置 |
| `VALIDATION_MAX_RETRY` | `2` | 验证重试配置 |
| `AGENT_EXECUTION_MODE` | `sequential` | 审查执行模式，可设为 `parallel` |
| `KNOWLEDGE_MAX_FILES` | `500` | 知识库索引最大文件数 |
| `KNOWLEDGE_MAX_FILE_CHARS` | `100000` | 知识库单文件最大字符数 |
| `KNOWLEDGE_CHUNK_CHARS` | `2000` | 知识库切片字符数 |

## 常用命令

```powershell
# 启动开发服务
uvicorn app.main:app --reload --port 8000

# 启动后台 worker
celery -A app.worker.celery_app worker --pool=solo -l info

# 运行测试
python -m pytest tests -q

# 编译检查
python -m compileall app tests

# Docker 构建
docker build -t agent-review-system .

# Docker 运行
docker run --rm -p 8000:8000 agent-review-system

# Docker Compose 一键启动 API + Redis
docker compose up --build
```

当前仓库未发现独立的代码格式化命令、构建脚本或正式数据库迁移工具。数据库表会在 FastAPI 启动时通过 `init_db()` 自动创建，SQLite 目前只有轻量 schema 补丁逻辑。

## 使用说明

### 使用 Web 控制台

1. 启动 Redis、FastAPI 服务和 Celery worker。
2. 打开 http://127.0.0.1:8000/。
3. 在页面中提交统一 Git diff。
4. 等待任务状态完成后查看 Markdown 报告、JSON 报告和生成的测试草案。

### 使用 API 提交 diff

```powershell
$body = @{
  source_type = "cli"
  repo_name = "example-repo"
  diff_text = @"
diff --git a/app.py b/app.py
index 1111111..2222222 100644
--- a/app.py
+++ b/app.py
@@ -1,2 +1,2 @@
-print("old")
+print("new")
"@
  changed_files = @()
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/reviews -ContentType "application/json" -Body $body
```

返回 `task_id` 后，可通过状态和报告接口查询结果。

## API 文档

### `GET /health`

健康检查。

返回示例：

```json
{"status": "ok"}
```

### `POST /api/reviews`

创建审查任务。任务创建后会通过 Celery 分发执行。

请求体字段：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `source_type` | string | 否 | 默认 `cli`；`github_pr` 会尝试通过 GitHub CLI 拉取 PR diff |
| `repo_name` | string | 否 | 仓库名；GitHub PR 模式必填 |
| `pull_request_number` | integer | 否 | GitHub PR 编号；GitHub PR 模式必填 |
| `repo_path` | string | 否 | 本地仓库路径 |
| `base_ref` | string | 否 | 基准 ref |
| `head_ref` | string | 否 | 目标 ref |
| `diff_text` | string | 否 | 统一 Git diff，需包含 `diff --git` 和 hunk header |
| `changed_files` | array | 否 | 变更文件列表；无 `diff_text` 时每个文件必须提供非空 `content` |

返回：

```json
{
  "task_id": "abc123def456",
  "status": "pending"
}
```

### `POST /api/reviews/from-git`

从本地 Git 仓库生成 `base_ref...head_ref` diff 并创建审查任务。

请求体字段：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `repo_path` | string | 是 | 本地 Git 仓库目录 |
| `base_ref` | string | 否 | 默认 `main` |
| `head_ref` | string | 是 | 目标 ref |
| `repo_name` | string | 否 | 仓库显示名 |

### `GET /api/reviews/{task_id}`

查询审查任务状态。

返回包含：

- `task_id`
- `status`
- `source_type`
- `repo_name`
- `current_stage`
- `error_message`
- `created_at`
- `updated_at`

### `GET /api/reviews/{task_id}/events`

查询任务阶段事件历史。

返回列表字段：

- `id`
- `task_id`
- `stage`
- `status`
- `error_message`
- `created_at`

### `GET /api/reviews/{task_id}/report`

查询审查报告。任务仍为 `pending` 时返回 HTTP 202；`running` 时返回当前阶段摘要；完成或失败后返回报告内容。

返回包含：

- `task_id`
- `status`
- `summary`
- `markdown_report`
- `json_report`
- `generated_tests`

### `POST /api/knowledge/index`

将指定仓库文件索引到 Chroma，用于 RAG 上下文检索。

请求体字段：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `repo_name` | string | 否 | 仓库名，默认使用路径目录名 |
| `repo_path` | string | 是 | 本地仓库路径 |

返回包含索引状态、索引文件数、切片数、跳过文件数和 embedding 跳过原因。

### `POST /api/knowledge/risk-rules`

导入结构化风险规则卡片，用于 RAG 风险审查 Agent。

请求体字段：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `rules` | array | 是 | 至少 1 条风险规则 |

单条规则包含 `risk_id`、`title`、`severity`、`category`、`bad_examples`、`safe_examples`、`source_patterns`、`sink_patterns`、`sanitizer_patterns`、`evidence_requirements`、`suggestion`、`attack_scenario`、`cwe`、`languages`、`frameworks` 和 `tags` 等字段。其中 `risk_id`、`title`、`severity`、`category`、`suggestion` 不可为空。

## 开发说明

- 新增审查能力时，优先在 `app/agents/` 中添加或扩展节点，并在 `app/agents/orchestrator.py` 中接入流水线。
- 新增 API 时，放在 `app/routers/`，业务逻辑放在 `app/services/`，请求/响应模型放在 `app/models/schemas.py`。
- 新增持久化字段时，需要同步更新 ORM 模型和数据库初始化逻辑；当前项目尚未引入 Alembic 等迁移工具。
- 新增行为应补充 `tests/` 下的 pytest 覆盖，尤其是 schema 校验、Agent 输出、报告结构和服务层持久化。
- 如果开启 `API_AUTH_ENABLED=true`，请求审查和知识库接口需要携带 `X-API-Key`。
- GitHub PR 输入依赖本机安装并登录 `gh` CLI。

## 部署说明

### Docker

```powershell
docker build -t agent-review-system .
docker run --rm -p 8000:8000 agent-review-system
```

Docker 镜像会启动 Uvicorn 服务并暴露 8000 端口。默认 `DATABASE_URL=sqlite:///./data/app.db`，如需持久化 SQLite 和 Chroma 数据，应挂载 `/app/data`。

示例：

```powershell
docker run --rm -p 8000:8000 -v ${PWD}/data:/app/data agent-review-system
```

### Docker Compose

```powershell
docker compose config
docker compose up --build
```

Compose 会启动 `api` 和 `redis` 两个服务，并将宿主机 `8000` 端口映射到 API 容器的 `8000` 端口。`api` 服务通过 `REDIS_HOST=redis`、`REDIS_PORT=6379` 连接 Redis，容器间通信不要使用 `localhost`。

启动后访问：

- Web 控制台：http://127.0.0.1:8000/
- OpenAPI 文档：http://127.0.0.1:8000/docs
- 健康检查：http://127.0.0.1:8000/health

注意：当前 Compose 只编排 API 和 Redis，不会启动 Celery worker。需要后台消费审查任务时，可在本地或另一个容器中启动 `celery -A app.worker.celery_app worker --pool=solo -l info`，并使用同一个 Redis。

## TODO / 后续优化

- 引入正式数据库迁移工具，替代当前轻量 SQLite schema 补丁。
- 补充 Celery worker 的 Compose 编排和任务管理能力。
- 增加任务管理 UI、失败任务重试/死信处理和更完整的任务事件查询能力。
- 强化外部 LLM 调用的生产策略、审计日志和观测指标。
- 完善 API/server 级请求体大小限制，和 schema 层限制形成双重保护。
- 为生成的测试草案增加可选落盘、执行和结果回写能力。
- 清理并配置 mypy，使类型检查成为稳定质量门禁。
- 扩展 RAG 风险规则库和项目知识库同步/删除策略。
