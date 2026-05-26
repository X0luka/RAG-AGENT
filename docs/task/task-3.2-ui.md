# Task 3.2 — Streamlit UI

**Milestone**: M3
**Depends on**: task-3.1
**预计**: 1 天

## 目标

用 Streamlit 做最小可用 UI:Chat 页 + History 页。

## 必读文档

- [`../07-api.md`](../07-api.md)(理解 SSE 协议)
- [`../02-data-models.md`](../02-data-models.md)

## 输出文件

```
ui/app.py                # Streamlit 入口
```

## UI 设计

### Streamlit 应用结构

用 `st.navigation` + Page,两个页面:

```
├── Chat        # 主页面
└── History     # 历史
└── Documents   # 文档管理
```

### Chat 页

- 上方:消息列表(用户问题 + AI 回答)
- 中间:每条 AI 回答下展开 Citations(可折叠)
- 下方:输入框(`st.chat_input`)
- 侧边栏:
  - 模式切换:Strong / Cheap(默认 Strong)
  - 切换是否带历史
  - 当前会话信息(累计花费)

每次输入:
1. 把用户消息加入会话状态
2. 调 `/api/query`(SSE)
3. 用 `st.write_stream` 流式显示
4. 完成后渲染 citations 区(可点击查看预览)
5. 反馈按钮(👍 / 👎),点击调 `/api/feedback`

### History 页

- 分页列表,每条显示:timestamp / query / answer 摘要 / cost / feedback
- 点开看完整 answer + retrieved chunks
- 支持按 feedback 过滤(全部 / 👍 / 👎 / 未评价)

### Documents 页

- 列出所有已摄入文档:source / type / chunks / ingested_at
- 删除按钮(调 `/api/documents/{id}`)
- 上传按钮:从本地选文件,选 type,调 `/api/ingest`

## 实现规约

### API client

`ui/app.py` 顶部:

```python
import httpx
import json
from typing import AsyncIterator

API_BASE = "http://localhost:8000"


def http_client() -> httpx.Client:
    return httpx.Client(base_url=API_BASE, timeout=120)


async def stream_query_events(query: str, **kwargs) -> AsyncIterator[tuple[str, dict]]:
    """调 /api/query 并解析 SSE 流。yield (event_type, data_dict)。"""
    async with httpx.AsyncClient(base_url=API_BASE, timeout=120) as client:
        async with client.stream(
            "POST", "/api/query",
            json={"query": query, **kwargs},
        ) as response:
            event_type = None
            async for line in response.aiter_lines():
                line = line.strip()
                if not line:
                    continue
                if line.startswith("event:"):
                    event_type = line[6:].strip()
                elif line.startswith("data:") and event_type:
                    data = json.loads(line[5:].strip())
                    yield event_type, data
```

### Streaming + Streamlit 集成

Streamlit 不原生支持 async generator,需要桥接:

```python
import asyncio

def sync_stream_query(query: str, **kwargs):
    """同步生成器,内部跑 async event loop。"""
    async def _impl():
        async for evt in stream_query_events(query, **kwargs):
            yield evt
    
    loop = asyncio.new_event_loop()
    agen = _impl()
    try:
        while True:
            try:
                yield loop.run_until_complete(agen.__anext__())
            except StopAsyncIteration:
                break
    finally:
        loop.close()


# 在 chat 页:
text_placeholder = st.empty()
citations_data = []
answer_parts = []

for event_type, data in sync_stream_query(prompt):
    if event_type == "delta":
        answer_parts.append(data["content"])
        text_placeholder.markdown("".join(answer_parts))
    elif event_type == "citations":
        citations_data = data["citations"]
    elif event_type == "done":
        usage = data["usage"]
    elif event_type == "error":
        st.error(f"{data['error_code']}: {data['error_message']}")
        break

# 渲染 citations
if citations_data:
    with st.expander(f"📎 Sources ({len(citations_data)})"):
        for c in citations_data:
            page_str = f" (p.{c['page']})" if c.get('page') else ""
            st.markdown(f"**[{c['source_id']}]** `{c['source']}`{page_str}")
            st.caption(c['text_preview'])
```

## Verify

```bash
# 1. 启 API
uv run uvicorn src.api.main:app --port 8000 &

# 2. 启 UI
uv run streamlit run ui/app.py
# 浏览器打开 http://localhost:8501

# 人工验证:
# - Chat 页能输入并看到流式输出
# - 输出下面显示 citations,可展开
# - 点击 👍/👎 能写入反馈(在 History 页验证)
# - History 页能看到 Chat 页的记录
# - Documents 页能看到已摄入文档,能上传新文档
```

## Notes for Implementation

- Streamlit 1.40+ 支持 `st.navigation` + `st.Page`,比 sidebar 切换更清爽
- 流式输出用 `st.empty()` + 不断 markdown 更新,而不是 `st.write_stream`(后者更适合纯文本流)
- `st.session_state` 用来存对话历史,**不要每次重新拉 API history**(那是另一个概念)
- 文件上传后,Streamlit 把文件存在内存里,需要先写到 `data/raw/` 才能调 ingest API
- Streamlit 在 WSL2 上可能默认监听 0.0.0.0,允许从 Windows 浏览器访问

## 完成后

**M3 完成**。进入 Task 4.1(memory 上下文)。

---

*Related Tasks: [task-3.1-api.md](task-3.1-api.md), [task-4.1-memory.md](task-4.1-memory.md)*
