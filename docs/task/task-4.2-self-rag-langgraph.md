# Task 4.2 — Self-RAG with LangGraph

**Milestone**: M4
**Depends on**: task-4.1
**预计**: 1-2 天

## 目标

把线性的 `retrieve → generate` 查询流程重构为 LangGraph `StateGraph`,在检索质量不足时自动评估、改写 query 并重新检索。

本 Task 只做受控 Self-RAG 编排,不扩展为开放式 Agent。

## 必读文档

- [`../00-conventions.md`](../00-conventions.md)
- [`../04-retrieval.md`](../04-retrieval.md)
- [`../05-generation.md`](../05-generation.md)
- [`../08-observability.md`](../08-observability.md)
- [`task-4.1-memory.md`](task-4.1-memory.md)

## 输出文件

```
src/orchestration/__init__.py
src/orchestration/self_rag.py
src/api/routes/query.py              # /query 和 /query/sync 改走 Self-RAG 入口
src/api/schemas.py                   # 如需暴露 debug metadata,补充响应字段
tests/test_self_rag.py
```

## StateGraph 设计

### State 字段

```python
from typing import TypedDict
from src.retrieval import SearchResult


class SelfRagState(TypedDict):
    original_query: str
    current_query: str
    rewrite_count: int
    chunks: list[SearchResult]
    retrieval_score: float
    retrieval_reason: str
    answer: str
```

### 节点

1. `retrieve`
   - 调用 `retrieve_top_chunks(state["current_query"])`
   - 写入 `chunks`

2. `evaluate_retrieval`
   - 用低成本 LLM 路径为检索质量打分
   - 分数范围为 `1-5`
   - 输出 JSON: `{"score": 4.2, "reason": "..."}`
   - 失败时降级为 `score=5.0`,避免评分故障阻断问答

3. `rewrite_query`
   - 当 `retrieval_score < settings.self_rag_min_retrieval_score` 且 `rewrite_count < settings.self_rag_max_rewrites` 时触发
   - 用低成本 LLM 改写 `current_query`
   - `rewrite_count += 1`
   - 改写必须保持原始意图,不能引入新实体或新约束

4. `generate`
   - 使用最终 `current_query` 和当前 `chunks` 调用既有生成逻辑
   - 写入 `answer`

### 条件边

```text
START → retrieve → evaluate_retrieval

evaluate_retrieval → rewrite_query
  when retrieval_score < 3.5 and rewrite_count < 2

evaluate_retrieval → generate
  when retrieval_score >= 3.5 or rewrite_count >= 2

rewrite_query → retrieve
generate → END
```

阈值和循环上限从 settings 读取:

- `self_rag_min_retrieval_score = 3.5`
- `self_rag_max_rewrites = 2`

总检索次数最多 3 次:原始 query 1 次 + 改写 query 2 次。

## 对外接口

`self_rag.py` 暴露稳定入口:

```python
async def run_self_rag(
    query: str,
    history: list[dict],
    kind: ProviderKind = "strong",
) -> SelfRagResult:
    """运行 Self-RAG 查询流程。"""
```

`SelfRagResult` 至少包含:

```python
@dataclass
class SelfRagResult:
    answer: str
    chunks: list[SearchResult]
    final_query: str
    rewrite_count: int
    retrieval_score: float
    retrieval_reason: str
```

`/api/query` 和 `/api/query/sync` 对外协议不变。若需要把 Self-RAG metadata 返回给 UI,只能作为可选 debug 字段加入,不得破坏现有字段。

## Prompt 约束

### 检索评分 Prompt

输入:

- original query
- current query
- top chunks 的 `source/page/text preview`

输出必须是 JSON,字段固定为:

```json
{"score": 4.0, "reason": "retrieved chunks directly discuss the requested concept"}
```

评分参考:

- `5`:检索结果直接、充分、来源清晰
- `4`:大体相关,信息足够生成答案
- `3`:部分相关,但关键依据不足
- `2`:弱相关,需要改写 query
- `1`:明显不相关或无有效 chunk

### Query 改写 Prompt

输入:

- original query
- current query
- retrieval_reason

输出只返回改写后的 query 文本。禁止输出解释、编号或 Markdown。

## Observability

在 Langfuse trace 中记录:

- span:`self_rag_graph`
- span:`evaluate_retrieval`
- span:`rewrite_query`
- metadata:`rewrite_count`
- metadata:`retrieval_score`
- metadata:`retrieval_reason`
- metadata:`final_query`

达到最大循环次数但仍低分时,不再循环,使用当前最佳 chunks 生成,并把低分原因写入 trace metadata。

## Tests

### `tests/test_self_rag.py`

至少 4 个测试:

1. **test_high_score_generates_without_rewrite**
   - mock `evaluate_retrieval` 返回 `4.0`
   - 验证只检索 1 次,不调用 `rewrite_query`

2. **test_low_score_rewrites_and_retrieves_again**
   - 第一次评分 `2.0`,第二次评分 `4.0`
   - 验证改写 1 次,检索 2 次

3. **test_max_two_rewrites**
   - 连续返回低分
   - 验证 `rewrite_count == 2`,检索次数为 3,随后进入 generate

4. **test_evaluator_failure_falls_back_to_generate**
   - mock 评分节点抛异常
   - 验证流程不失败,`retrieval_score == 5.0`,直接生成

## Verify

```bash
# 1. 单测
uv run pytest tests/test_self_rag.py -v

# 2. 同步问答仍可用
uv run python scripts/ask.py "What is self-attention?"

# 3. API 协议不破坏
curl -s -X POST http://localhost:8000/api/query/sync \
  -H "Content-Type: application/json" \
  -d '{"query":"What is self-attention?","include_history":false}' | jq

# 4. Langfuse 中能看到 self_rag_graph / evaluate_retrieval / rewrite_query span
```

## Notes for Implementation

- 只允许直接使用 `langgraph`,业务代码不得直接 import `langchain`
- 不改 `retrieve_top_chunks` 的对外签名
- 不改 `/api/query` 和 `/api/query/sync` 的必填请求字段
- query 改写只用于检索,最终回答仍应忠于检索到的 chunks
- 评分和改写建议走低成本 LLM 路径,最终生成默认走强模型路径

## 完成后

M4 完成。进入 Task 5.1(评估通过线)。

---

*Related Tasks: [task-4.1-memory.md](task-4.1-memory.md), [task-5.1-eval-pass.md](task-5.1-eval-pass.md)*
