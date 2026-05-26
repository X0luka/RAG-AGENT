# Task 5.1 — Eval Pass Line

**Milestone**: M5
**Depends on**: task-4.1(或在 task-3.2 之后,顺序灵活)
**预计**: 2-4 天(可能反复)

## 目标

把 golden set 扩到 30+ 题,通过调参把 RAGAS 四指标都拉到 [`../09-eval.md`](../09-eval.md) THRESHOLDS 之上,与 baseline 对比有显著提升。

**这是 M1-M4 的"质量收尾",确认 M1-M4 都跑通后再进入。**

## 必读文档

- [`../09-eval.md`](../09-eval.md) ← **主要参考**
- [`../03-ingestion.md`](../03-ingestion.md)、[`../04-retrieval.md`](../04-retrieval.md)、[`../05-generation.md`](../05-generation.md)(调参指南)

## 输出文件

```
eval/golden_set.json          # 扩到 30+ 题
eval/results/<tag>/...        # 多次实验的归档
log/spec.log.md               # 记录每次调参的 spec 变更
```

## 工作流程(迭代式)

```
1. 跑 baseline,看哪些指标低,看哪些题失败
   ↓
2. 假设:可能的原因是什么?
   ↓
3. 改一个变量(只改一个,否则归因不准)
   ↓
4. 跑评估,新 tag
   ↓
5. 对比上次,确认有/无提升
   ↓
6. 若有提升:固化(更新 settings 或 spec)
   若无提升:回滚,试下一个假设
   ↓
   循环,直到所有指标过线
```

## 调参手册

### 若 `context_recall` 低(< 0.80)

意味着相关 chunks 没被检索到。尝试:

| 假设 | 改动 | 工作量 |
|---|---|---|
| 检索召回太少 | `top_k_vector` / `top_k_bm25`: 30 → 50 | 改 settings,1 行 |
| 切块太大 / 太小 | `chunk_size`: 512 → 256 或 1024 | 改 settings,需重新摄入 |
| 切块没保留语义 | 改 chunker 策略(MarkdownNodeParser → 自定义) | 改 chunker.py |
| 嵌入模型不行 | 换 `text-embedding-3-large`(贵 6 倍但更强) | 改 settings,重摄入 |
| 文档没覆盖到 | 添加更多源材料 | 摄入更多文档 |

### 若 `context_precision` 低(< 0.70)

检索回来太多噪音。尝试:

| 假设 | 改动 |
|---|---|
| Rerank 没生效 | 检查 rerank 是否报错降级了 |
| top_k_rerank 太大 | 8 → 5 |
| RRF 融合权重不对 | 试纯向量(skip BM25)或调整 RRF k 参数 |

### 若 `faithfulness` 低(< 0.85)

LLM 编造、不基于 context。尝试:

| 假设 | 改动 |
|---|---|
| Prompt 不够严格 | 强化 SYSTEM_PROMPT 中"只基于 sources"措辞 |
| Temperature 太高 | 0.3 → 0.0 或 0.1 |
| 上下文不够明确 | 在 source 区加更清楚的边界标记 |
| 模型不够强 | 评估时用 strong 模型(已是) |

### 若 `answer_relevancy` 低(< 0.80)

答非所问。尝试:

| 假设 | 改动 |
|---|---|
| 模型偏题 | 在 prompt 末尾重申"Answer this question:" |
| 问题被截断 | 检查 max_tokens_response 是否足够 |
| LLM 自己加了不必要内容 | prompt 加 "Be direct and concise" |

## 实施规约

### 每次实验必须

1. **取一个清晰的 tag**:`v1-chunk-256`、`v2-rerank-top5`、`v3-temp-0`
2. **更新 settings 或 spec**:不要硬编码新值
3. **完整跑评估**:不要凭"感觉这次更好"
4. **结果归档**:`eval/results/{tag}/` 必须完整
5. **写一行记录**:在 `log/spec.log.md` 写一条变更,包括:
   - 改了什么(参数名 / 旧值 / 新值)
   - 假设是什么
   - 结果(指标变化)
   - 结论(保留 / 回滚)

### 不要做的事

- ❌ 一次改多个参数(归因不准)
- ❌ 跳过评估,凭感觉"这次答得更好"
- ❌ 为通过指标而过拟合 golden set(增加题目分散评估)
- ❌ 改 RAGAS 的指标实现来"通过"

## 通过条件(必须全部满足)

- [ ] golden set ≥ 30 题
- [ ] 四个 RAGAS 指标全部在 THRESHOLDS 之上
- [ ] 与 baseline-v0 对比,至少 3 项指标有 ≥ 5% 提升
- [ ] 评估结果可复现(同一 tag 配置重跑,指标差异 < 3%)
- [ ] 所有保留的参数变更都写进了 `log/spec.log.md`

## 调参提醒

这一步的目标是建立可复现的质量优化流程,而不是只把指标调到通过线:

- 保持**假设-实验-观察-结论**闭环
- 每次只改一个变量,确保指标变化可归因
- 对保留参数给出明确依据
- 不被偶然结果误导(同一配置跑两次结果可能有 3-5% 波动)

如果某个指标长期无法通过,优先回到错误样本和 trace 分析:
检查检索召回、chunk 边界、rerank 是否生效、prompt 是否让模型忠于 sources。

## Notes for Implementation

- 不要主动改 `THRESHOLDS`,除非有明确评估依据
- 调参建议可在 Task 报告中提供,实际参数变更要记录到 spec/log
- 每次"完成一轮实验"算一个里程碑式的 commit,commit message 说清楚 tag 和指标变化

## 完成后

**M5 达成**。项目核心质量保证完成。
后续是 M6+ 可选扩展(见 `../../roadmap.md`),按使用反馈决定优先级。

M5 完成后建议先运行一段时间,根据真实问题记录决定下一批功能。

---

*Related Tasks: [task-2.1-eval.md](task-2.1-eval.md), [task-4.1-memory.md](task-4.1-memory.md)*
