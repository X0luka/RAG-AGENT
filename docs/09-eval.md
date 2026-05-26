# 09 — Evaluation

**职责**:量化系统检索和生成质量。每次重要改动后跑一次,看指标是否提升。

## 模块文件

```
eval/
├── golden_set.json       # 评估数据集
├── run_eval.py           # 执行脚本
└── results/              # 按 tag 归档的结果
    └── {tag}/
        ├── scores.json
        ├── details.csv
        └── config_snapshot.json
```

## 9.1 Golden Set 格式

`eval/golden_set.json`:

```json
[
  {
    "id": "q001",
    "question": "What is the difference between attention and self-attention?",
    "ground_truth": "Self-attention is a special case of attention where query, key, and value all come from the same sequence. Attention in general can compute relationships between two different sequences (encoder-decoder).",
    "expected_sources": ["papers/attention.pdf"],
    "difficulty": "easy",
    "tags": ["transformer", "attention"]
  }
]
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | str | ✓ | 唯一标识,格式 `q001`, `q002`... |
| `question` | str | ✓ | 用户问题 |
| `ground_truth` | str | ✓ | 期望答案文本(评估用) |
| `expected_sources` | list[str] | ✓ | 期望被检索到的文件路径(相对 `data/raw/`) |
| `difficulty` | "easy"/"medium"/"hard" | ✓ | 主观难度,用于分层分析 |
| `tags` | list[str] | ✓ | 标签,用于过滤分析 |

### 数量目标

- M2 阶段:**20 题**(粗略 baseline)
- M5 阶段:**30 题以上**(可信比较)
- 长期:每周加 2-3 题,从真实使用中挑

## 9.2 评估指标

使用 RAGAS,计算 4 个指标:

| 指标 | 含义 | 通过线 |
|---|---|---|
| `context_recall` | 检索是否覆盖了正确答案所需的信息 | ≥ 0.80 |
| `context_precision` | 检索结果中相关 chunk 的比例 | ≥ 0.70 |
| `faithfulness` | 生成的答案是否忠于检索内容 | ≥ 0.85 |
| `answer_relevancy` | 答案是否回答了问题 | ≥ 0.80 |

```python
# eval/run_eval.py
THRESHOLDS = {
    "context_recall": 0.80,
    "context_precision": 0.70,
    "faithfulness": 0.85,
    "answer_relevancy": 0.80,
}
```

## 9.3 评估流程

```python
import asyncio
import json
import httpx
from pathlib import Path
from datetime import datetime, UTC
import argparse


async def run_eval(tag: str, api_base: str = "http://localhost:8000") -> int:
    """跑评估。
    
    返回值用作 exit code:
        0 = 全部指标通过
        1 = 任一指标未达 THRESHOLD
        2 = 执行错误
    
    流程:
    1. 加载 golden_set.json
    2. 对每条:
       a. POST {api_base}/api/query/sync
          payload: {query, include_history: False, use_cheap_model: False}
       b. 收集 (question, ground_truth, contexts, answer)
       c. contexts 从返回的 citations 反查:用 source + text_preview
          注:理想是 API 同时返回检索到的 chunks 完整文本,可在 QueryResponse 加字段
    3. 构造 ragas Dataset
    4. 跑 ragas.evaluate(),得到四个指标
    5. 输出到 eval/results/{tag}/:
       - scores.json: 各指标均值
       - details.csv: 每题详情(含每题各指标分数)
       - config_snapshot.json: 当时的 settings 全量快照(便于回溯哪个配置)
    6. 与上一次评估对比(若 results/ 下有其他 tag):
       - 找最近的非当前 tag,读其 scores.json
       - 计算 delta,打印对比表
    7. 检查 THRESHOLDS,所有通过返回 0,否则 1
    
    日志:
    - 每条 query 完成后打印一行进度
    - 总耗时和总成本估算
    """


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True, help="结果标签,如 'baseline'")
    parser.add_argument("--api", default="http://localhost:8000")
    args = parser.parse_args()
    
    exit_code = asyncio.run(run_eval(args.tag, args.api))
    sys.exit(exit_code)
```

## 9.4 评估结果格式

### `scores.json`

```json
{
  "tag": "v1-with-rerank",
  "timestamp": "2026-05-25T15:30:00Z",
  "n_questions": 20,
  "metrics": {
    "context_recall": 0.85,
    "context_precision": 0.78,
    "faithfulness": 0.91,
    "answer_relevancy": 0.83
  },
  "thresholds_passed": true,
  "total_cost_usd": 0.45,
  "total_latency_seconds": 120.5
}
```

### `details.csv`

```csv
id,question,difficulty,context_recall,context_precision,faithfulness,answer_relevancy,cost_usd,latency_ms
q001,"What is attention?",easy,1.0,0.8,0.95,0.88,0.012,3200
q002,...
```

### `config_snapshot.json`

```json
{
  "embedding_model": "text-embedding-3-small",
  "embedding_provider": "aihubmix",
  "rerank_model": "rerank-v3.5",
  "openrouter_primary_model": "anthropic/claude-sonnet-4.6",
  "chunk_size": 512,
  "chunk_overlap": 50,
  "top_k_vector": 30,
  "top_k_bm25": 30,
  "top_k_rerank": 8,
  "rrf_k": 60,
  "temperature": 0.3
}
```

(从 settings 单例直接 dump)

## 9.5 评估时的特殊处理

### use_cheap_model 选择

评估时**默认用强模型**(`use_cheap_model=False`),因为评估的目的是检验系统上限。
若想评估廉价路径,跑两次,tag 区分(如 `v1-strong` 和 `v1-cheap`)。

### 不影响 production 数据

评估也会写 SQLite interactions,但可以接受——它们是真实的问答记录。
若想完全隔离,M5 之前不做。

### 评估期间的并发

不要并发跑 query,串行执行(避免触发 API 限流)。
20 题大概 5-10 分钟,可接受。

## 9.6 解读指标

| 现象 | 可能原因 | 排查方向 |
|---|---|---|
| context_recall 低 | 检索没找到正确信息 | 检查切块策略、嵌入模型、top_k |
| context_precision 低 | 检索找到了但混入太多噪音 | 检查 rerank 是否生效、top_k_rerank 是否合理 |
| faithfulness 低 | LLM 没基于 sources 回答 | 检查 prompt、context 是否实际包含信息 |
| answer_relevancy 低 | 答非所问 | 检查 prompt、温度参数 |

## 9.7 RAGAS 注意事项

- RAGAS 内部会调 LLM 做评判(LLM-as-judge)
- 第一版优先配置为 DeepSeek/OpenRouter 兼容接口,避免引入额外供应商 key
- 评估本身的成本估算:20 题 × ~5 次 LLM 评判调用/题 = 100 次低成本模型调用

---

*Related: [02-data-models.md](02-data-models.md), [05-generation.md](05-generation.md), [07-api.md](07-api.md)*
