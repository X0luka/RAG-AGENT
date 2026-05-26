# Task 3.1 — FastAPI Service

**Milestone**: M3
**Depends on**: task-1.3
**预计**: 1 天

## 目标

把 CLI 能力包成 HTTP 服务,支持 SSE 流式。

## 必读文档

- [`../07-api.md`](../07-api.md) ← **主要参考**
- [`../02-data-models.md`](../02-data-models.md)

## 输出文件

```
src/api/main.py
src/api/schemas.py
src/api/errors.py             # 若 task-1.1 已建,补全
src/api/routes/ingest.py
src/api/routes/query.py
src/api/routes/history.py
```

## 实现细节

完整规约见 [`../07-api.md`](../07-api.md)。

**关键点**:

1. **lifespan**:启动时 `init_db()` + `bm25_index.load()` + `get_langfuse()`;关闭时 flush Langfuse
2. **SSE**:`/api/query` 返回 `StreamingResponse(generator, media_type="text/event-stream")`
3. **错误处理**:全局 exception handler,统一 ErrorResponse 格式
4. **不做鉴权**:单用户本地项目
5. **健康检查**:`/health` 检查 Qdrant 和 SQLite,不打 LLM API

## Verify

```bash
# 1. 启动
uv run uvicorn src.api.main:app --reload --port 8000 &
sleep 3

# 2. 健康检查
curl -s http://localhost:8000/health | jq
# 期望:status 为 ok 或 degraded,所有 checks 字段都有结果

# 3. OpenAPI 文档
curl -s http://localhost:8000/openapi.json | jq '.paths | keys'
# 期望:看到所有 routes

# 4. 文档列表
curl -s http://localhost:8000/api/documents | jq
# 期望:JSON 响应,含 items 字段

# 5. 同步问答
curl -s -X POST http://localhost:8000/api/query/sync \
  -H "Content-Type: application/json" \
  -d '{"query":"what is attention","include_history":false}' | jq
# 期望:返回 answer + citations

# 6. SSE 流式问答
curl -N -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"query":"what is attention","include_history":false}'
# 期望:看到流式事件序列(start → delta * N → citations → done)

# 7. 反馈
curl -s -X POST http://localhost:8000/api/feedback \
  -H "Content-Type: application/json" \
  -d '{"interaction_id":1,"feedback":1}'
# 期望:204 无内容
```

## Notes for Implementation

- FastAPI 的 lifespan 用 `asynccontextmanager` 装饰的函数,不是旧的 `@app.on_event`
- SSE 字符串构造要小心:`f"event: {type}\ndata: {json}\n\n"`(两个 `\n` 结尾)
- StreamingResponse 的 generator 是 async generator
- model_dump_json() 不要忘加(Pydantic v2)
- 全局异常处理器要覆盖所有自定义异常和通用 Exception 兜底

## 完成后

进入 Task 3.2(UI)。

---

*Related Tasks: [task-1.3-generation-cli.md](task-1.3-generation-cli.md), [task-3.2-ui.md](task-3.2-ui.md)*
