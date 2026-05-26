# 03 — Ingestion

**职责**:把原始文件转换为带 metadata 的 chunks,嵌入并存入 Qdrant + BM25。

## 模块文件

```
src/ingestion/
├── __init__.py
├── loaders.py       # 各类文件读取
├── chunker.py       # 切块策略
└── pipeline.py      # 端到端流程
```

## 3.1 `loaders.py`

```python
from pathlib import Path
from llama_index.core import Document

def load_pdf(path: Path) -> list[Document]:
    """使用 LlamaIndex PDFReader。每页一个 Document。
    
    Returns:
        Documents,每个 metadata 包含:
          - source (str): 相对路径
          - source_type: "paper"
          - page (int): 页码,从 1 起
    """


def load_markdown(path: Path) -> list[Document]:
    """整文件一个 Document。
    
    Returns:
        单元素列表,metadata 包含 source, source_type。
    """


def load_code(path: Path) -> list[Document]:
    """整文件一个 Document。
    
    Returns:
        单元素列表,metadata 额外含:
          - language (str): 从扩展名映射,如 "python" / "javascript" / "go"
    """


def load_html(path: Path) -> list[Document]:
    """使用 trafilatura 抽取正文,过滤导航、广告等。"""


def auto_load(path: Path, source_type: str) -> list[Document]:
    """按扩展名分派。
    
    扩展名映射:
      .pdf → load_pdf
      .md, .markdown → load_markdown
      .py → load_code (language="python")
      .js, .ts → load_code
      .go, .rs, .java, .cpp, .c, .h → load_code
      .html, .htm → load_html
      .txt → load_markdown 处理
    
    Args:
        source_type: 来源类型(paper/code/article/transcript),用于 metadata
    
    Returns:
        Documents,统一注入 source 和 source_type 到 metadata
    
    Raises:
        ValueError: 扩展名不支持
    """
```

**编码注意**:
- PDF 解析用 `from llama_index.readers.file import PDFReader`
- HTML 抽取用 `trafilatura.extract`,失败回退到 `bs4` 取所有文字
- 文件路径统一相对 `settings.raw_dir`,存到 metadata.source 时用相对路径

## 3.2 `chunker.py`

```python
from llama_index.core.schema import TextNode, Document

def chunk_documents(
    docs: list[Document],
    source_type: str
) -> list[TextNode]:
    """切块,返回带 metadata 的 nodes。
    
    切块策略:
      - source_type == "code":
          使用 CodeSplitter
          chunk_lines=40, chunk_lines_overlap=15, max_chars=1500
          language 从 doc.metadata["language"] 读
          
      - 其他:
          使用 MarkdownNodeParser 优先按标题切
          若切出的 node 文本超过 settings.chunk_size,二次切:
              SentenceSplitter(
                  chunk_size=settings.chunk_size,
                  chunk_overlap=settings.chunk_overlap
              )
    
    每个返回的 TextNode 必须有 metadata:
      - chunk_index (int): 在该文档内的序号,从 0 起
      - heading_path (list[str]): 标题路径,可为 []
      - 保留原 Document 的所有 metadata(source, source_type, page 等)
    
    标题路径构造:
      MarkdownNodeParser 会在 metadata 中给 "Header_1", "Header_2" 等,
      把它们按层级顺序合并为 heading_path 列表。
    """
```

**关键点**:
- chunk_index 必须按 node 在文档中出现顺序赋值
- 切块前过滤空文档(`len(doc.text.strip()) < 50` 跳过)
- 切块后过滤过短 chunk(`len(node.text.strip()) < 100` 跳过)

## 3.3 `pipeline.py`

```python
from dataclasses import dataclass
from pathlib import Path

@dataclass
class IngestResult:
    document_id: int
    chunk_count: int
    skipped: bool


async def ingest_file(
    path: Path,
    source_type: str,
    force: bool = False
) -> IngestResult:
    """端到端摄入单个文件。
    
    流程:
    1. 计算 file_hash = sha256(file bytes)
    
    2. 查 SQLite documents 表 by source:
       - 已存在且 hash 相同且 force=False:
           → 返回 IngestResult(skipped=True, document_id=existing.id, chunk_count=existing.chunk_count)
       - 已存在但 hash 不同(文件被修改):
           a. Qdrant: client.delete(filter by payload.source == path)
           b. BM25: bm25_index.remove_by_source(path)
           c. SQLite: 删除旧 Document 记录
       - 不存在:继续
    
    3. docs = auto_load(path, source_type)
    
    4. nodes = chunk_documents(docs, source_type)
       若 nodes 为空,抛 ValueError("No content extracted")
    
    5. 嵌入:
       - 按 batch_size=100 分批
       - 通过 AIHubMix OpenAI 兼容接口调 embeddings API
       - 出错重试 3 次(指数退避 1s, 2s, 4s)
    
    6. 构造 Qdrant Points 并 upsert:
       - point_id = uuid4().hex
       - payload 严格按 02-data-models.md 的 Schema
       - 包括 ingested_at = datetime.now(UTC).isoformat()
    
    7. 更新 BM25 索引:
       bm25_index.add_documents(chunk_ids, texts)
       bm25_index.save()
    
    8. 在 SQLite 插入 Document 记录,获取 document_id
    
    9. 返回 IngestResult(document_id, chunk_count, skipped=False)
    
    错误处理:
    - 第 4-7 步任一失败,必须回滚:
        - 删除已 upsert 的 Qdrant points(by source filter)
        - 重新加载 BM25 索引旧版本(若已 save 过)
    - 用 try/except,捕获到异常时记录详细 log 后 raise IngestionFailedError
    """


async def delete_document(source: str) -> None:
    """按 source 删除文档及其所有数据。
    
    流程:
    1. Qdrant delete by filter payload.source == source
    2. BM25 remove_by_source
    3. BM25 save
    4. SQLite delete Document
    """
```

## 3.4 BM25 索引(`src/retrieval/bm25.py`)

虽然文件在 retrieval/,但摄入时也需要写入。

```python
import pickle
from pathlib import Path
from rank_bm25 import BM25Okapi


class BM25Index:
    """BM25 索引的持久化封装。
    
    存储结构(pickle 文件):
      {
        "chunk_ids": list[str],   # 与 documents 对齐的 Qdrant point_ids
        "documents": list[list[str]],  # tokenized texts
        "raw_texts": list[str]   # 原文,用于返回
      }
    """
    
    def __init__(self, path: Path):
        self.path = path
        self.chunk_ids: list[str] = []
        self.documents: list[list[str]] = []  # tokenized
        self.raw_texts: list[str] = []
        self._bm25: BM25Okapi | None = None
    
    def add_documents(self, chunk_ids: list[str], texts: list[str]) -> None:
        """追加文档到索引。调用后必须 save() 才持久化。"""
    
    def remove_by_source(self, source: str) -> None:
        """按 source 删除。需要外部传入 source → chunk_ids 的映射,
        或在初始化时把 source 也存进去。
        
        实现方式 2:在 add_documents 时额外接受 sources 参数,
        内部维护 sources 列表,删除时按 source 过滤所有列表。
        
        签名调整为:
            add_documents(chunk_ids, texts, sources)
            remove_by_source(source)
        """
    
    def search(self, query: str, top_k: int) -> list[tuple[str, float]]:
        """返回 [(chunk_id, score), ...],按 score 降序。
        
        tokenize: 简单按空格 split + 小写。中文场景未来可换 jieba。
        """
    
    def save(self) -> None:
        """pickle 到 self.path,父目录自动创建。"""
    
    def load(self) -> None:
        """从 self.path 加载;文件不存在则初始化为空。"""
```

**全局实例**:`bm25_index = BM25Index(settings.bm25_index_path)`,模块级单例。
应用启动时调用 `bm25_index.load()`。

## 3.5 Tokenize 策略

第一版:简单 `text.lower().split()`。

英文文档 OK,中文文档 BM25 效果会差但不影响整体可用性。
中文优化在 M5 之后再考虑(加 jieba 分词)。

## 3.6 错误类型

`src/api/errors.py` 中定义对应业务异常:

```python
class IngestionFailedError(Exception):
    def __init__(self, source: str, stage: str, original: Exception):
        self.source = source
        self.stage = stage      # "load" / "chunk" / "embed" / "index" / "store"
        self.original = original


class UnsupportedFileTypeError(Exception):
    pass
```

---

*Related: [01-config.md](01-config.md), [02-data-models.md](02-data-models.md), [04-retrieval.md](04-retrieval.md)*
