# Agent Review System 改进实施方案

本文档基于当前 Python 后端项目的审查结果，按优先级拆成可逐步落地的改进任务。建议按阶段推进：先修安全和输入边界，再增强任务可靠性，最后做架构和审查质量升级。

## 总体目标

- 避免代码、密钥、业务数据被意外发送到外部 LLM。
- 避免空输入或无内容输入返回“审查通过”的假阴性。
- 让后台审查任务可追踪、可恢复、可重试。
- 用结构化 schema 约束 agent 输出，减少脏数据导致的报告失败。
- 逐步把 P1 骨架演进成可扩展、可维护的审查平台。

## 推荐执行顺序

1. 安全基线修复
2. 输入校验和请求限制
3. Finding 结构化校验
4. 任务状态和错误可观测性
5. Agent 规则质量提升
6. 测试生成和报告一致性
7. 任务队列和架构分层
8. 部署与依赖治理

---

## 阶段 1：安全基线修复

优先级：高

### 1.1 移除示例密钥

涉及文件：

- `.env.example`
- `.gitignore`

当前问题：

- `.env.example` 中存在疑似真实 `LLM_API_KEY`。
- 示例配置默认指向外部 provider，容易在开发环境误外发代码。

建议修改：

```env
LLM_PROVIDER=mock
LLM_MODEL=mock-reviewer
LLM_API_KEY=
LLM_BASE_URL=
```

验收标准：

- `.env.example` 不包含任何 `sk-`、token、password、secret 等真实值。
- 本地默认启动不会调用外部 LLM。
- 如果该 key 曾经提交过，需要立即轮换，并检查 git 历史。

### 1.2 增加 LLM 外发门禁

涉及文件：

- `app/config.py`
- `app/agents/llm_review.py`
- `app/agents/test_generation.py`

建议新增配置：

```env
LLM_EXTERNAL_ENABLED=false
LLM_REDACTION_ENABLED=true
```

建议行为：

- 当 `LLM_EXTERNAL_ENABLED=false` 时，无论 provider 是否配置 key，都只走 mock/local review。
- 外部调用前执行 redaction，屏蔽疑似密钥、token、连接串、私钥块。
- 报告中记录 `llm_mode`: `mock` / `external_redacted` / `external_disabled`。

验收标准：

- 默认环境下 `pytest` 不依赖网络。
- 未显式开启时不会调用 `call_llm()`。
- 添加测试覆盖：有 API key 但 `LLM_EXTERNAL_ENABLED=false` 时仍走 mock。

---

## 阶段 2：输入校验和请求限制

优先级：高

### 2.1 防止空内容审查

涉及文件：

- `app/models/schemas.py`
- `tests/test_schemas.py`

当前问题：

- 只传 `changed_files=[{"file_path": "..."}]` 时也会创建任务，但没有 diff 或文件内容可审查。

建议规则：

- `diff_text` 和 `changed_files.content` 至少有一个必须提供。
- 如果没有 `diff_text`，每个 `changed_files` 至少应包含非空 `content`。
- `file_path` 不能为空，不能包含 `..`、绝对路径或控制字符。

验收标准：

- `CreateReviewRequest(changed_files=[ChangedFileIn(file_path="app/a.py")])` 应校验失败。
- `CreateReviewRequest(changed_files=[ChangedFileIn(file_path="app/a.py", content="print(1)")])` 应通过。

### 2.2 强制大小限制

涉及文件：

- `app/models/schemas.py`
- `app/config.py`
- `tests/test_schemas.py`

建议限制：

- `REVIEW_MAX_FILES`
- `REVIEW_MAX_DIFF_CHARS`
- `REVIEW_MAX_FILE_CONTENT_CHARS`
- `REVIEW_MAX_TOTAL_CONTENT_CHARS`

验收标准：

- 超出文件数量返回 422。
- 超出 diff 或内容长度返回 422。
- 错误信息明确指出哪个限制被触发。

---

## 阶段 3：Finding 结构化校验

优先级：高

### 3.1 建立 Finding Pydantic 模型

涉及文件：

- `app/models/schemas.py` 或新增 `app/models/findings.py`
- `app/agents/finding_aggregator.py`
- `app/agents/report.py`
- `app/agents/llm_review.py`

建议字段：

```python
class FindingModel(BaseModel):
    agent_name: str
    severity: Literal["low", "medium", "high", "critical"]
    category: str
    file_path: str | None = None
    line_number: int | None = None
    title: str
    description: str
    evidence: str = ""
    suggestion: str = ""
    confidence: float = Field(ge=0.0, le=1.0)
    blocking: bool = False
    attack_scenario: str | None = None
    source_agents: list[str] = Field(default_factory=list)
```

建议行为：

- 所有 agent 输出都进入 normalize 函数。
- 无效 finding 不直接进入报告，而是记录到 `pipeline_errors` 或 `validation_warnings`。
- LLM findings 也经过 aggregator 去重、归一化、blocking 判断。

验收标准：

- LLM 返回缺字段、错误 severity、字符串 confidence 时不会打崩报告。
- 报告中不会出现重复或未归一化 finding。

---

## 阶段 4：任务状态和错误可观测性

优先级：中

### 4.1 持久化每个 pipeline stage

涉及文件：

- `app/services/review_service.py`
- `app/agents/orchestrator.py`
- `app/models/review_task.py`

当前问题：

- `current_stage` 只在开始和结束写入数据库。

建议方案：

- 在 orchestrator 中支持 `on_stage_start` / `on_stage_end` callback。
- service 层 callback 写入 `current_stage`、`updated_at`、最近错误。
- 可选新增 `review_task_events` 表记录 stage、耗时、错误。

验收标准：

- 执行中查询 `GET /api/reviews/{task_id}` 能看到真实 stage。
- agent 异常时能看到具体失败节点。

### 4.2 改进失败报告

涉及文件：

- `app/routers/reviews.py`
- `app/services/review_service.py`
- `app/agents/report.py`

建议行为：

- 即使 pipeline 部分失败，也尽量返回部分 findings 和部分 report。
- `failed` 状态下保留 `report_json.pipeline_errors`。
- 区分 `failed`、`completed_with_warnings`、`completed`。

验收标准：

- 单个 agent 失败时，最终响应不会只剩通用错误。
- 报告能显示已成功执行的 agent 输出。

---

## 阶段 5：Agent 规则质量提升

优先级：中

### 5.1 清理未实现的 style checks

涉及文件：

- `app/agents/style_check.py`
- `tests/test_agents.py`

当前问题：

- `_CHECKS` 中声明了长行、魔法数字、单字母变量、长函数，但实际只实现 TODO/FIXME/HACK。

两种可选方案：

- 短期：删除未实现声明，只保留真实能力。
- 中期：实现这些规则，并加入测试。

验收标准：

- 声明的规则和实际执行结果一致。
- 每个规则至少有一个正向测试和一个避免误报测试。

### 5.2 用 AST 降低 Python 规则误报

涉及文件：

- `app/agents/static_analysis.py`
- `app/agents/security_scan.py`

建议优先替换：

- mutable default argument
- broad exception
- bare except
- eval/exec/compile
- open without context manager
- subprocess shell usage

验收标准：

- `subprocess.run(["ls", path])` 不被误报为 command injection。
- `subprocess.run(command, shell=True)` 被标记为高危。
- `yaml.safe_load()` 不被误报为 insecure deserialization。

---

## 阶段 6：测试生成和报告一致性

优先级：中

### 6.1 修复 high-risk finding 只进 test_plan 的问题

涉及文件：

- `app/agents/test_generation.py`
- `tests/test_agents.py`

当前问题：

- high/critical finding 会添加 test plan，但不一定生成对应 draft test。

建议行为：

- 每个 high/critical finding 至少生成一个 draft test。
- 如果无法生成代码，明确标记 `generation_status="plan_only"`。

验收标准：

- 报告中的 test suggestions 和 generated test drafts 不互相矛盾。
- 测试覆盖 high-risk finding 的 draft 生成。

### 6.2 改善报告数据来源

涉及文件：

- `app/agents/report.py`
- `app/agents/finding_aggregator.py`

建议：

- 报告只消费已归一化后的 final findings。
- JSON 报告增加 `metadata`：agent 数、耗时、llm_mode、pipeline_status。
- Markdown 报告显示“审查范围”：文件数、语言、是否只审查新增行。

验收标准：

- 用户能从报告判断审查覆盖范围。
- 无 findings 时能区分“确实无问题”和“没有可审查内容”。

---

## 阶段 7：任务队列和架构分层

优先级：中到高，取决于是否要生产化

### 7.1 替换 FastAPI BackgroundTasks

涉及文件：

- `app/routers/reviews.py`
- `app/services/review_service.py`
- 新增 `app/workers/`

建议方案：

- 开发期可继续保留同步 runner。
- 生产期引入 RQ/Celery/Arq/Temporal 之一。
- API 只负责创建任务并入队。
- Worker 负责执行 pipeline 并写回结果。

验收标准：

- 服务重启不会丢失 pending/running 任务。
- 任务有超时、重试和失败原因。

### 7.2 拆分 service 职责

涉及文件：

- `app/services/review_service.py`

建议拆分：

- `ReviewTaskRepository`：数据库 CRUD。
- `ReviewStateBuilder`：从任务构建 pipeline state。
- `ReviewRunner`：执行 pipeline。
- `ReviewResultPersister`：保存 findings 和 report。

验收标准：

- 单元测试可以分别覆盖 DB、state 构建、pipeline 执行和结果保存。
- service 文件体积和职责明显下降。

---

## 阶段 8：部署与依赖治理

优先级：低到中

### 8.1 固定依赖版本

涉及文件：

- `requirements.txt`
- 可新增 `constraints.txt` 或锁文件

当前问题：

- 依赖全部使用 `>=`，构建结果不稳定。

建议：

- 固定当前已验证版本。
- 或使用 `pip-tools` 生成锁文件。

验收标准：

- 本地和 Docker 构建使用一致依赖。
- CI 中不会因为上游包升级突然失败。

### 8.2 加固 Dockerfile

涉及文件：

- `Dockerfile`

建议：

- 使用非 root 用户运行。
- 增加 healthcheck。
- 根据生产需要挂载 `/app/data`。

验收标准：

- 容器内进程不是 root。
- `/health` 可被容器健康检查调用。

---

## 推荐的第一轮 Pull Request 范围

建议第一轮只做高优先级基础修复，避免一次改太多：

1. 清理 `.env.example` 中的密钥和默认外部 LLM 配置。
2. 新增 `LLM_EXTERNAL_ENABLED=false` 默认门禁。
3. 修改 `CreateReviewRequest`，禁止无 diff 且无 content 的请求。
4. 增加请求大小限制。
5. 为上述行为补充 tests。

第一轮验收命令：

```powershell
.\myenv\Scripts\python.exe -m pytest tests -q
.\myenv\Scripts\python.exe -m compileall app tests
```

## 推荐的第二轮 Pull Request 范围

1. 新增 Finding Pydantic schema。
2. 所有 agent 输出统一 normalize。
3. LLM findings 接入 aggregator。
4. 报告消费 final normalized findings。
5. 增加脏 LLM 输出测试。

## 推荐的第三轮 Pull Request 范围

1. 持久化 pipeline stage。
2. 增加 task event 或 stage log。
3. 区分 `completed`、`completed_with_warnings`、`failed`。
4. 改善失败报告。

## 长期演进方向

- 将 regex 规则逐步迁移到 AST/Semgrep/Tree-sitter。
- 引入真实队列和 worker。
- 将规则、LLM provider、报告模板做成插件化。
- 支持项目级知识库、repo index、历史 review 对比。
- 增加认证、授权、租户隔离、审计日志和速率限制。

