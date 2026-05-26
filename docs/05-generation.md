# 05 — Generation

**职责**:基于检索结果调用 LLM 生成答案,支持流式。

## 模块文件

```
src/generation/
├── __init__.py
├── prompts.py     # Prompt 模板常量
├── llm.py         # LLM 客户端封装(DeepSeek/OpenRouter)
└── stream.py      # 流式问答完整流程
```

## 5.1 `prompts.py`

```python
SYSTEM_PROMPT = """You are an AI engineering learning assistant. The user is studying AI engineering and asks questions based on materials they have provided.

Rules:
1. Answer ONLY based on the provided sources below. If the sources don't contain the answer, respond exactly: "I don't have enough information in my knowledge base to answer this. Consider adding more materials."
2. Cite sources by including [source_N] immediately after each factual claim, where N is the source id from the sources block.
3. Be concise. Use code blocks with language tags for code. Use $...$ for inline math, $$...$$ for display math.
4. If the question is ambiguous, ask for clarification before answering.
5. Never invent source IDs. Only use IDs from the provided sources.
6. If conversation history is provided, you may reference it for context, but ground your factual claims in the sources.
"""

USER_PROMPT_TEMPLATE = """{history_section}Sources:
{sources_section}

User question:
{query}"""


def format_history_section(history: list["Interaction"]) -> str:
    """格式化最近对话历史。
    
    格式:
        Recent conversation:
        [1] User: {query}
            Assistant: {answer_truncated_500_chars}
        [2] User: ...
        
    每条 answer 截断到 500 字符。
    
    若 history 为空,返回空字符串(注意不要留多余换行)。
    若 history 非空,末尾加两个换行符与后续 Sources 分隔。
    """


def format_sources_section(chunks: list["SearchResult"]) -> str:
    """格式化 sources 区。
    
    格式:
        <source id="1" file="papers/attention.pdf" page="3">
        {chunk_text}
        </source>
        <source id="2" file="..." page="...">
        ...
        </source>
    
    source id 从 1 开始。
    若 page 为 None,属性写 page="N/A"。
    """


def parse_citations(answer: str, chunks: list["SearchResult"]) -> list["Citation"]:
    """从生成的 answer 中提取 [source_N] 标记,返回引用列表。
    
    正则: r"\\[source_(\\d+)\\]"
    
    去重(同一 source 多次引用只算一次)。
    
    返回 Citation 列表,按出现顺序排列。
    若某个 source_N 在 chunks 中不存在,跳过(LLM 可能编)。
    """
```

## 5.2 `llm.py`

```python
from dataclasses import dataclass
from typing import AsyncIterator, Literal
from openai import AsyncOpenAI

# ==================== Provider 客户端 ====================

# DeepSeek 客户端(用于廉价路径)
_deepseek_client = AsyncOpenAI(
    api_key=settings.deepseek_api_key,
    base_url=settings.deepseek_base_url,
    timeout=settings.request_timeout_seconds,
)

# OpenRouter 客户端(用于强模型路径)
_openrouter_client = AsyncOpenAI(
    api_key=settings.openrouter_api_key,
    base_url=settings.openrouter_base_url,
    timeout=settings.request_timeout_seconds,
    default_headers={
        "HTTP-Referer": settings.openrouter_site_url,
        "X-Title": settings.openrouter_site_name,
    },
)


# ==================== 数据结构 ====================

@dataclass
class LLMUsage:
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    model: str
    provider: str


@dataclass
class LLMResult:
    content: str
    usage: LLMUsage


@dataclass
class LLMChunk:
    delta: str                # 增量文本,可能为空字符串
    done: bool                # 最后一个 chunk 为 True
    usage: LLMUsage | None    # 仅最后一个 chunk 带


# ==================== Provider 选择 ====================

ProviderKind = Literal["cheap", "strong"]

def _get_client_and_model(kind: ProviderKind) -> tuple[AsyncOpenAI, str, str]:
    """返回 (client, model_string, provider_name)。"""
    if kind == "cheap":
        return _deepseek_client, settings.deepseek_model, "deepseek"
    else:
        return _openrouter_client, settings.openrouter_primary_model, "openrouter"


# ==================== 调用接口 ====================

async def call_llm(
    system: str,
    user: str,
    kind: ProviderKind = "strong",
) -> LLMResult:
    """非流式调用。
    
    流程:
    1. 选 client / model / provider
    2. client.chat.completions.create(
           model=model,
           messages=[
               {"role": "system", "content": system},
               {"role": "user", "content": user},
           ],
           temperature=settings.temperature,
           max_tokens=settings.max_tokens_response,
       )
    3. 解析响应,构造 LLMResult
    4. 计算 cost_usd(见 5.3)
    
    错误处理:
    - 429: 指数退避重试 3 次(1s, 2s, 4s)
    - 5xx / 网络错误: 重试 2 次
    - 其他: 包装为 LLMError 抛出
    """


async def stream_llm(
    system: str,
    user: str,
    kind: ProviderKind = "strong",
) -> AsyncIterator[LLMChunk]:
    """流式调用。
    
    流程:
    1. 选 client / model / provider
    2. async for chunk in client.chat.completions.create(..., stream=True):
       a. 提取 delta.content,产出 LLMChunk(delta=content, done=False)
       b. 最后一个 chunk(finish_reason 非 None)时:
          - 提取 usage 字段(可能在最后或 stream_options)
          - 产出 LLMChunk(delta="", done=True, usage=...)
    
    重要细节:
    - OpenAI 兼容流式必须传 stream_options={"include_usage": True} 才能拿到 token 统计
    - OpenRouter 在响应里直接返回真实成本(在 X-Total-Cost header 或 generation API),
      第一版可以根据 token + 价格表估算。后续可调 OpenRouter generation API 获取精确成本。
    """
```

## 5.3 成本计算

`src/generation/llm.py` 模块顶部维护价格表(USD per 1M tokens):

```python
PRICING_USD_PER_M = {
    # DeepSeek
    "deepseek-chat": {"input": 0.27, "output": 1.10},  # 价格随时间变,以官方为准
    
    # OpenRouter(常用模型)
    "anthropic/claude-sonnet-4.6": {"input": 3.00, "output": 15.00},
    "anthropic/claude-haiku-4.5": {"input": 1.00, "output": 5.00},
    "openai/gpt-5": {"input": 5.00, "output": 20.00},
    "google/gemini-2.5-pro": {"input": 1.25, "output": 5.00},
}


def calculate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """按价格表计算 USD。
    
    若 model 不在表中:
    - 打 warning log
    - 返回 0.0(避免崩溃)
    """
```

**未来优化**:OpenRouter 调用后可异步查询 `/api/v1/generation/{id}` 获取精确成本,
本期不做。

## 5.4 `stream.py`

```python
from typing import AsyncIterator

async def stream_query(
    query: str,
    history: list["Interaction"],
    chunks: list["SearchResult"],
    kind: ProviderKind = "strong",
) -> AsyncIterator["StreamEvent"]:
    """完整的流式问答管道。
    
    产出事件序列:
    1. StreamEvent(type="start", interaction_id=<新 id>)
    2. 多个 StreamEvent(type="delta", content="...")
    3. StreamEvent(type="citations", citations=[...])
    4. StreamEvent(type="done", usage={...}, latency_ms=...)
    
    若中途错误,产出:
       StreamEvent(type="error", error_code="...", error_message="...")
    
    完整流程:
    1. 记录起始时间
    2. 组装 prompt(format_history_section + format_sources_section)
    3. 在 SQLite 插入 interaction 占位记录,获取 interaction_id
        - 这一步用空 answer,后续 update
        - 也可以最后一次性 insert,但占位记录更便于追踪未完成请求
    4. 发 start 事件
    5. answer_buffer = []
       async for chunk in stream_llm(SYSTEM_PROMPT, user_prompt, kind):
           if chunk.delta:
               answer_buffer.append(chunk.delta)
               yield StreamEvent(type="delta", content=chunk.delta)
           if chunk.done:
               final_usage = chunk.usage
    6. answer = "".join(answer_buffer)
    7. citations = parse_citations(answer, chunks)
    8. 发 citations 事件
    9. update SQLite interaction:
       - answer = answer
       - retrieved_chunks = {"ids": [...], "scores": [...], "sources": [...]}
       - model_used, provider, tokens, cost_usd, latency_ms
    10. 发 done 事件
    
    错误处理:
    - 任一步异常,update SQLite 标记 interaction 失败(answer="[ERROR]"),
      产出 error 事件
    - 不要因为 SQLite 写入失败就影响用户体验,SQLite 失败只 log 不抛
    """


async def sync_query(
    query: str,
    history: list["Interaction"],
    chunks: list["SearchResult"],
    kind: ProviderKind = "strong",
) -> "QueryResponse":
    """非流式版本,供评估使用。
    
    内部调用 call_llm(非流式),组装 QueryResponse 返回。
    SQLite 写入逻辑同 stream_query。
    """
```

## 5.5 Langfuse 集成点

每次 `stream_query` / `sync_query` 必须在一个 Langfuse trace 内:

```
trace: query_pipeline
  metadata: {interaction_id, query_length, history_used, num_sources}
  ├── span: retrieval(由 retrieval 模块自己加)
  └── generation: llm_call(Langfuse 的 generation 类型)
        input: {system, user}
        output: answer
        usage: {prompt_tokens, completion_tokens, total_cost}
        model: model_string
```

具体集成代码见 `08-observability.md`。

---

*Related: [01-config.md](01-config.md), [04-retrieval.md](04-retrieval.md), [06-memory.md](06-memory.md), [08-observability.md](08-observability.md)*
