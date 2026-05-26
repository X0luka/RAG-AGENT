# 00 — Conventions(编码与协作规约)

**适用范围**:所有 Task 执行前必读。

## 0. 执行协议

### 0.1 任务粒度

执行单位是 **Task**(见 `tasks/` 目录)。每个 Task 有:

- 输入:依赖的前置 Task ID(必须先完成)
- 输出:`outputs` 字段列出的文件 / 接口
- 验收:`verify` 字段定义的可自动化检查

### 0.2 工作流

```
1. 读取本文档(00-conventions.md)
2. 读取目标 Task 文档(tasks/task-x.y.md)
3. 读取 Task 中引用的其他 spec 文档
4. 检查前置 Task 已完成(对应 outputs 文件存在)
5. 报告执行计划,等待用户确认
6. 执行,产出 outputs
7. 跑 verify,必须通过
8. 按本文档第 5 节格式报告完成
9. 等待下一指令,不自动进下一 Task
```

### 0.3 禁止行为

- 禁止修改 `docs/` 下的技术契约文档,除非当前任务明确要求
- 禁止修改 `pyproject.toml` 的依赖版本(若版本冲突,报告问题)
- 禁止使用本文档第 2 节"禁用库"清单中的库
- 禁止跳过 verify 步骤
- 禁止为了通过 verify 而硬编码返回值
- 禁止自动进入下一个 Task

## 1. 项目目录结构(锁定)

任何文件必须放在以下位置之一,不允许创建新的顶层目录。

```
ai-learning-companion/
├── pyproject.toml
├── docker-compose.yml
├── .env.example
├── .env                        # 不进 git
├── .gitignore
├── README.md                   # 仅含运行命令,无设计内容
│
├── docs/                       # 设计与规约(本目录)
│
├── src/
│   ├── __init__.py
│   ├── config.py
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── loaders.py
│   │   ├── chunker.py
│   │   └── pipeline.py
│   ├── retrieval/
│   │   ├── __init__.py
│   │   ├── vector.py
│   │   ├── bm25.py
│   │   ├── hybrid.py
│   │   └── rerank.py
│   ├── generation/
│   │   ├── __init__.py
│   │   ├── prompts.py
│   │   ├── llm.py
│   │   └── stream.py
│   ├── orchestration/
│   │   ├── __init__.py
│   │   └── self_rag.py
│   ├── memory/
│   │   ├── __init__.py
│   │   ├── models.py
│   │   └── store.py
│   ├── api/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── schemas.py
│   │   ├── errors.py
│   │   └── routes/
│   │       ├── __init__.py
│   │       ├── ingest.py
│   │       ├── query.py
│   │       └── history.py
│   └── observability/
│       ├── __init__.py
│       └── tracing.py
│
├── ui/
│   └── app.py
│
├── eval/
│   ├── golden_set.json
│   ├── run_eval.py
│   └── results/
│
├── data/
│   ├── raw/                    # 原始文档
│   ├── processed/              # BM25 索引等
│   ├── logs/                   # 应用日志
│   └── memory.db               # SQLite
│
├── scripts/
│   ├── ingest_one.py
│   ├── ask.py
│   ├── test_llm.py
│   └── reset_db.py
│
└── tests/
    ├── __init__.py
    └── test_*.py
```

## 2. 技术栈(锁定)

```yaml
language: Python 3.11+
package_manager: uv
rag_framework: llama-index>=0.13
vector_db_client: qdrant-client>=1.13
bm25: rank_bm25>=0.2
embedding_provider: aihubmix  # text-embedding-3-small, dim=1536, OpenAI-compatible API
rerank_provider: cohere     # rerank-v3.5
llm_sdk: openai>=1.50       # async,通用于 DeepSeek 和 OpenRouter
orchestration: langgraph>=0.2
web_framework: fastapi>=0.115
http_server: uvicorn[standard]>=0.32
db_orm: sqlalchemy>=2.0
db_async_driver: aiosqlite>=0.20
http_client: httpx>=0.27
ui: streamlit>=1.40
eval: ragas>=0.2
observability: langfuse>=2.50
config: pydantic-settings>=2.5
logging: loguru>=0.7
```

**禁用库**:`chromadb`, `gradio`, `pinecone-client`, `chainlit`, `anthropic`(改走 OpenRouter)

**LangGraph 例外规则**:
- 允许直接依赖 `langgraph`,只用于 `Task 4.2: Self-RAG with LangGraph`
- 不允许把 `langchain` / `langchain-*` 作为业务应用框架使用
- 如果 `langgraph` 安装时引入必要的传递依赖,只接受传递依赖,业务代码不得直接 import `langchain`

**版本策略**:`pyproject.toml` 中用 `>=` 而非 `==`,但锁文件 `uv.lock` 必须进 git。

## 3. 编码规则

### 3.1 Python 风格

- Python ≥ 3.11 语法:`list[str]`、`X | None`,不要 `List[str]`、`Optional[X]`
- 全部 async,数据库用 `aiosqlite`,HTTP 用 `httpx.AsyncClient`,LLM 用 `AsyncOpenAI`
- 类型注解必填,函数签名必须完整
- 不允许 `print` 调试,用 `loguru.logger`
- 不允许硬编码模型名、路径、数值参数,全部从 `settings` 读
- 单个函数超过 50 行必须拆分
- 单个文件超过 300 行必须拆分模块
- 所有外部 API 调用必须有超时(默认 30s)和重试(见各模块规约)

### 3.2 错误处理

- 精确捕获异常类型,**不允许裸 `except:`**
- 不允许 `except Exception:` 除非紧接着 `raise` 或转换为业务异常
- 业务异常定义在 `src/api/errors.py`,统一格式

### 3.3 配置访问

```python
# ✅ 正确
from src.config import settings
client = AsyncOpenAI(api_key=settings.openrouter_api_key)

# ❌ 禁止
import os
client = AsyncOpenAI(api_key=os.environ["OPENROUTER_API_KEY"])
```

### 3.4 日志

```python
from loguru import logger

logger.info("Ingesting {source}", source=path)  # 用 {} 占位,不要 f-string
logger.error("Failed: {err}", err=str(e))
```

### 3.5 Docstring

每个模块顶部必须有 docstring 说明用途。公开函数必须有 docstring 说明:
- 做什么(一句话)
- 关键参数(Args)
- 返回值(Returns)
- 可能抛出的异常(Raises)

## 4. Git 规范

### 4.1 Commit 粒度

- 一个 Task 完成 = 一个 commit(或几个原子 commit)
- 不允许"半个 Task" commit
- 文档变更必须和代码变更同一 commit

### 4.2 Commit message

使用 conventional commits:

```
<type>(<scope>): <subject>

<body>
```

`type`: `feat` / `fix` / `docs` / `refactor` / `test` / `chore`
`scope`: 模块名,如 `ingestion` / `retrieval` / `eval`

例:
```
feat(ingestion): implement PDF loader and chunker

- Add load_pdf using LlamaIndex PDFReader
- Add chunk_documents with MarkdownNodeParser
- Add tests for both
- Verified by manual ingest of attention.pdf

Task: 1.1
```

### 4.3 .gitignore 必含

```
.env
.venv/
__pycache__/
*.pyc
data/raw/*
!data/raw/.gitkeep
data/processed/*
!data/processed/.gitkeep
data/logs/*
!data/logs/.gitkeep
data/memory.db
data/memory.db-journal
eval/results/*
!eval/results/.gitkeep
.pytest_cache/
.mypy_cache/
.ruff_cache/
```

## 5. Task 完成报告格式

每完成一个 Task,按以下格式输出:

```markdown
## Task {id} 完成

### Outputs created/modified
- path/to/file1.py (new)
- path/to/file2.py (modified)
- ...

### Verify results
- [✓] uv sync: passed
- [✓] pytest tests/test_xxx.py: 5 passed, 0 failed
- [✓] docker compose ps: qdrant healthy
- [✓] curl http://localhost:6333: 200 OK
- [✗] Langfuse trace check: 需用户人工查看

### Spec deviations
任何偏离 spec 的地方,以及原因。没有则写 "None"。

### Spec issues found
执行中发现的 spec 不清晰、有矛盾、不可实现之处。
仅报告,不擅自修改。没有则写 "None"。

### Notes
其他需要用户知晓的事项(如选了某条 spec 没明确的小决策)。
没有则写 "None"。

### Ready for next task
是 / 否(若否,说明阻塞原因)
```

## 6. SPEC 变更提议

执行 Task 时若发现 spec 不合理或不可执行:

1. **不要**自己改 spec
2. 在 Task 报告的 "Spec issues found" 中详细描述
3. 提议修订内容(可选)
4. 等待用户决定

维护者确认后,再修改对应 spec 文档并同步变更日志。

---

*Related: [01-config.md](01-config.md), [02-data-models.md](02-data-models.md)*
