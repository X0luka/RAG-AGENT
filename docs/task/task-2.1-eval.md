# Task 2.1 — Evaluation Loop

**Milestone**: M2
**Depends on**: task-1.3
**预计**: 1 天

## 目标

建立评估闭环:20 题 golden set + RAGAS 跑通 + 结果归档。
**这是质量保证的关键,后续所有优化都靠它判断是否有效。**

## 必读文档

- [`../09-eval.md`](../09-eval.md) ← **主要参考**

## 输出文件

```
eval/golden_set.json          # 先生成 5 条示例,其余按已摄入语料补充
eval/run_eval.py              # 评估脚本
src/api/routes/query.py       # 增加 /api/query/sync 端点(若 task-3.1 还没做)
```

**注**:如果还没做 task-3.1(API),`run_eval.py` 暂时不走 API,
直接 import `retrieve_top_chunks` + `sync_query` 跑。
做完 task-3.1 后再改成走 HTTP API。

## 实现细节

### `eval/golden_set.json`

先生成 5 条示例(围绕 RAG / Transformer 等基础概念),
**剩下 15 条根据已摄入的文档补充**。

示例条目:

```json
[
  {
    "id": "q001",
    "question": "What is the difference between attention and self-attention?",
    "ground_truth": "Self-attention is a mechanism where the query, key, and value all come from the same input sequence, allowing each position to attend to all other positions. Attention in general (e.g., in encoder-decoder) computes relationships between two different sequences.",
    "expected_sources": ["papers/attention.pdf"],
    "difficulty": "easy",
    "tags": ["transformer", "attention"]
  },
  ...4 more examples
]
```

### `eval/run_eval.py`

完整按 [`../09-eval.md`](../09-eval.md) 第 9.3 节实现。

**第一版可以直接 import 内部模块跑**,不走 HTTP:

```python
async def run_one(question_item: dict) -> dict:
    chunks = await retrieve_top_chunks(question_item["question"])
    response = await sync_query(
        query=question_item["question"],
        history=[],
        chunks=chunks,
        kind="strong",
    )
    return {
        "question": question_item["question"],
        "ground_truth": question_item["ground_truth"],
        "answer": response.answer,
        "contexts": [c.text for c in chunks],  # ragas 需要的格式
    }
```

构造 ragas Dataset 后跑评估:

```python
from ragas import evaluate
from ragas.metrics import context_recall, context_precision, faithfulness, answer_relevancy
from datasets import Dataset

dataset = Dataset.from_list(rows)
result = evaluate(
    dataset,
    metrics=[context_recall, context_precision, faithfulness, answer_relevancy],
)
```

## Verify

```bash
# 1. 跑评估
uv run python eval/run_eval.py --tag baseline-v0
# 期望:
#   - 完成所有题目
#   - 在 eval/results/baseline-v0/ 生成 3 个文件
#   - 打印各指标均值

# 2. 文件齐全
ls eval/results/baseline-v0/
# 期望:scores.json  details.csv  config_snapshot.json

# 3. exit code 行为
uv run python eval/run_eval.py --tag baseline-v0; echo "exit=$?"
# 期望:若指标全过,exit=0;否则 exit=1
```

## Notes for Implementation

- RAGAS 在 v0.2+ 改了 API,注意按当前版本文档实现
- RAGAS 内部用 LLM 做 judge,第一版优先接 DeepSeek/OpenRouter 兼容接口
- 第一版 baseline 大概率不会全部达标,这是**正常的**,达标是 task-5.1 的目标
- 评估输出文件中 details.csv 必须包含每题的每个指标分数,便于看哪些题拖后腿

## 完成后

进入 Task 3.1(API)或 Task 5.1(优化到通过线)。

---

*Related Tasks: [task-1.3-generation-cli.md](task-1.3-generation-cli.md), [task-5.1-eval-pass.md](task-5.1-eval-pass.md)*
