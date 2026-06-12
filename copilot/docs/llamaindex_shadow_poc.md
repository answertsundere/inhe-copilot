# LlamaIndex Shadow POC 设计文档

## 目标

在不改变正式检索结果的前提下，使用 LlamaIndex 作为旁路检索引擎，
与当前 SQLite BM25 + 可选向量检索进行 A/B 对比，评估是否值得切换。

## 前提

- 当前项目使用 LangGraph 进行 Agent 编排，不使用 LlamaIndex 的 Agent 功能。
- LlamaIndex 只负责检索和索引，不负责：意图路由、JST Function Calling、商品身份映射、
  风险判断、知识真实性审核、最终事实约束。
- 本轮不安装 LlamaIndex 依赖，不改变正式检索结果。

## 未来实现

### 文件

```
app/retrieval/llamaindex_retriever.py
```

### 配置

```bash
COPILOT_RETRIEVER_BACKEND=current_sqlite       # 正式后端不变
COPILOT_LLAMA_INDEX_SHADOW_ENABLED=false        # Shadow 开关
```

### Shadow 模式要求

1. 正式结果仍使用 `current_sqlite`。
2. 同一查询旁路调用 LlamaIndex。
3. LlamaIndex 只读取 `status=published AND index_status=ready` 的知识。
4. 保留 `product_scope`、`sku_scope`、`fact_type` 作为 metadata。
5. 比较：
   - Recall@1, Recall@3, Recall@5
   - MRR
   - Wrong product rate
   - Wrong SKU rate
   - Fact type mismatch rate
   - Latency p50/p95
6. LlamaIndex 不允许绕过 `evidence_filter`、RAG Judge 或 Grounded Generation。
7. 只有评测显著优于现有检索后才能申请切换。

### LlamaIndex 的职责边界

| 功能 | 负责方 |
|------|--------|
| 意图路由 | LangGraph |
| JST Function Calling | LangGraph Tool Registry |
| 商品身份映射 | resolve_product_identity |
| 风险判断 | risk_check + factual_guard |
| 知识真实性审核 | knowledge_quality_gate |
| 最终事实约束 | hallucination_guard |
| **知识检索和索引** | **LlamaIndex (本 POC)** |
| Agent 编排 | LangGraph |

### 切换流程

1. Shadow 模式运行 ≥ 2 周，收集对比数据。
2. 人工审核 bad case，确认 LlamaIndex 是否减少了错召回。
3. 如确认优势：修改 `COPILOT_RETRIEVER_BACKEND=llamaindex` 切换。
4. 切换后保留 `current_sqlite` 作为 fallback。

## Retriever 抽象层

当前已建立的抽象层：

```
app/retrieval/
├── __init__.py
├── base.py                          # BaseKnowledgeRetriever ABC
├── current_sqlite_retriever.py      # 当前实现
├── retriever_factory.py             # 工厂
└── (未来) llamaindex_retriever.py   # LlamaIndex 实现
```

Tool Registry 中的 `rag_search_tool` 和 `rag_retrieve` 节点
只依赖 `BaseKnowledgeRetriever` 接口，不直接依赖具体实现。

## 不做的事

- 不用 LlamaIndex 的 Agent 功能替换 LangGraph。
- 不在检索结果上绕过已有的安全守卫（evidence_filter、RAG Judge、hallucination_guard）。
- 不自动切换，必须经过人工审核的对比数据。
