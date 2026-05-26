# Task 4.1 — Memory(对话历史接入)

**Milestone**: M4
**Depends on**: task-3.2
**预计**: 1-2 天

## 目标

把对话历史真正接入 prompt,让多轮问答能保持上下文。

**范围明确**:第一版只做"近 N 条问答对接入 prompt"。不做事实抽取、用户画像、概念掌握度等高级能力。

## 必读文档

- [`../06-memory.md`](../06-memory.md) ← **主要参考**
- [`../05-generation.md`](../05-generation.md)(history 在 prompt 中的位置)

## 输出文件

```
src/memory/store.py            # 补全 list_interactions / get_interaction / set_feedback
src/api/routes/history.py      # 若 task-3.1 还没补全则补全
tests/test_memory.py           # 至少 3 个测试
```

实际上**核心代码 task-1.3 已基本实现**(create_interaction_placeholder / finalize_interaction / get_recent_interactions / format_history_section 都已存在)。本 Task 的工作是:

1. 补全 memory store 缺失的 CRUD(分页、单查、反馈)
2. 验证多轮对话在实际使用中表现正确
3. 调优 history_window 的默认值
4. 加 SQLite 的索引(若 task-1.3 没加)

## 实现细节

### 补全 `src/memory/store.py`

按 [`../06-memory.md`](../06-memory.md) 第 6.3 节,确保下列函数全部实现:

- ✅ `create_interaction_placeholder`(task-1.3)
- ✅ `finalize_interaction`(task-1.3)
- ✅ `mark_interaction_failed`(task-1.3)
- ✅ `get_recent_interactions`(task-1.3)
- ⏳ `set_feedback`
- ⏳ `list_interactions`(分页)
- ⏳ `get_interaction`(单条)

### 验证多轮对话

**人工验证脚本**(用 CLI 跑):

```bash
# 第 1 问
uv run python scripts/ask.py "What is self-attention?"

# 第 2 问(应该能用第 1 问的上下文)
uv run python scripts/ask.py "How does it differ from cross-attention?"

# 第 3 问(应能识别"its")
uv run python scripts/ask.py "What's its computational complexity?"
```

**验收**:第 2、3 问的回答应能正确解析"it"指代 self-attention,不是从头解释。

### Prompt 中的 history 截断

当前实现:每条 answer 截断到 500 字符,最多 3 条。

若发现 LLM 上下文太挤(prompt tokens 接近 limit),调整方案:
- 减少 `history_window`(默认 3 → 2)
- 减少每条 answer 截断长度
- 把 retrieved_chunks 从 history 中完全剥离(已经是这样了)

## Tests

### `tests/test_memory.py`

至少 3 个测试,均使用临时 SQLite 文件(`tempfile`):

1. **test_create_and_finalize_interaction**:
   - 创建占位,补全字段,查回来验证字段正确
   
2. **test_get_recent_interactions_skips_failed**:
   - 写 3 条 interaction:1 成功、1 标记失败、1 空 answer
   - `get_recent_interactions(limit=10)` 只返回 1 条

3. **test_list_interactions_pagination**:
   - 写 25 条
   - `list_interactions(page=1, page_size=10)` 返回 (10 条, total=25)
   - `list_interactions(page=3, page_size=10)` 返回 (5 条, total=25)

## Verify

```bash
# 1. 单测
uv run pytest tests/test_memory.py -v

# 2. 多轮对话人工验证(见上面)

# 3. 历史 API
curl -s "http://localhost:8000/api/history?page=1&page_size=5" | jq
# 期望:items 数组、total 字段

# 4. 反馈 API
curl -s -X POST http://localhost:8000/api/feedback \
  -H "Content-Type: application/json" \
  -d '{"interaction_id":1,"feedback":1}'
# 期望:204

# 5. UI 上的 History 页应能正常分页和打开详情
```

## Notes for Implementation

- 如果在本 Task 才发现 task-1.3 实现得不对,**优先修复 task-1.3 的实现**,不要在这里写绕过
- SQLAlchemy 2.0 的查询用 `select(Interaction).where(...).order_by(...)`,不是旧的 `query()` API
- 分页用 `.offset((page-1)*size).limit(size)`,total 用单独的 `select(func.count())`
- session 用 `async with get_session() as s:` 自动 commit/rollback

## 完成后

进入 Task 4.2(Self-RAG with LangGraph)。

---

*Related Tasks: [task-1.3-generation-cli.md](task-1.3-generation-cli.md), [task-3.2-ui.md](task-3.2-ui.md), [task-4.2-self-rag-langgraph.md](task-4.2-self-rag-langgraph.md)*
