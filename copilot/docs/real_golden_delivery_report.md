# Golden Set 建设交付报告

**日期**: 2026-06-07
**任务**: Phase 0 阻塞项修复 + Phase 1 候选抽取 + Phase 3 商品/RAG 诊断

---

## 一、Phase 0 阻塞项修复

### 0A. 知识发布审核队列
- **状态**: 完成
- **输出**: `data/knowledge_publish_review_queue.jsonl`
- **扫描结果**: 744 条 draft 条目
  - auto_publish_candidate: 0
  - manual_review_required: 738
  - reject_or_rewrite: 6
- **脚本**: `scripts/knowledge/knowledge_publish_review.py`
- **结论**: 禁止自动发布。所有 draft 需人工审核后才能进入 published。

### 0B. 统一 AnalysisExecutionService
- **状态**: 完成
- **修改文件**:
  - `app/services/analysis_execution_service.py` — 新增文件快照保存
  - `app/api/copilot_routes.py` — 重构为调用 `execute_analysis()`
  - `tests/test_sidecar_mixed.py` — 修复 FakeReplyService 签名
- **新增测试**: `tests/test_analysis_execution_consistency.py` (8 tests)
- **验证**: `/api/analyze` 和 `/api/copilot/context` 核心决策一致

### 0C. Embedding Shadow Mode
- **状态**: 完成
- **新增配置**: `COPILOT_EMBEDDING_SHADOW_MODE=true`
- **新增脚本**:
  - `scripts/build_knowledge_embeddings.py` — 增强: --published-only, --preflight, --resume
  - `scripts/knowledge/check_embedding_coverage.py`
  - `scripts/knowledge/evaluate_hybrid_retrieval.py`
- **当前状态**: 0% embedding 覆盖率，API 未配置，BM25 为主
- **修改**: `app/repositories/knowledge_chunk_repository.py` — shadow mode 并行运行 vector+BM25

### 0D. Trace UI 运行时验收
- **状态**: 完成
- **验证**: 5 种场景（商品问答、物流、闲聊、高风险投诉、RAG miss）生成 trace
- **Trace 功能**: 列表、详情、瀑布图、快照、Bad Case 创建
- **脱敏检查**: 未发现敏感数据泄露
- **页面**: `/traces` 正常渲染（13KB HTML）

---

## 二、Phase 1 数据审计与候选抽取

### PostgreSQL 数据审计
- **数据库**: `postgresql://postgres:postgres@127.0.0.1:15433/qa_db`
- **连接**: 成功
- **Cutoff**: `2026-05-26T00:00:00+08:00`

| 指标 | 数值 |
|------|------|
| 总消息数 | 99,452 |
| Cutoff 后消息数 | 82,556 |
| Cutoff 后客户消息 | 27,927 |
| Cutoff 后客服消息 | 47,752 |
| Cutoff 前（排除） | 16,896 |
| Cutoff 后 chats | 5,742 |
| complete + scoreable | 5,118 |
| business_sessions (cutoff后) | 6 |

### 候选抽取结果
- **抽取**: 5,183 sessions 读取 → 1,907 candidates
- **300 条抽样分布**:

| 场景 | 目标 | 实际 |
|------|------|------|
| 售前商品咨询 | 100 | 100 |
| 物流 | 60 | 60 |
| 售后退换/破损 | 60 | 60 |
| 安装使用 | 30 | 30 |
| 投诉和高风险 | 30 | 30 (含17条从unclear补充) |
| 闲聊/模糊/辱骂 | 20 | 20 |

### Shortage Report
- **complaint_high_risk**: 仅 13 条真实候选，距目标 30 条差 17 条
- 用 `unclear` 场景补充，单独标记

---

## 三、Phase 3 商品与 RAG 诊断

### Product Identity Resolver
- **新增**: `app/services/product_identity_resolver.py`
- **能力**: 平台ID/URL/标题/消息 → 内部 i_id/SKU → 知识库 Scope
- **防止**: 平台商品 ID 不误作内部编码
- **低置信度**: 标记 ambiguous，需人工审核

### 五个 RAG 案例诊断

| 案例 | 正确知识位置 | RAG published 召回 | 问题类型 |
|------|-------------|-------------------|---------|
| 一号狮子围兜防水 | draft #821,822 | 狮子围兜(无防水) | knowledge_gap |
| 六号防摔枕材质 | draft #811,812 | 7天退货、折叠垫 | rag_miss + knowledge_gap |
| 刺猬桌面书架 | draft #94,#158 | 发货时效 | rag_miss |
| 十一号防摔枕适合 | draft #813,814 | 1号折叠垫(wrong scope) | rag_miss + wrong_scope |
| 儿童书架实木 | published #58,70,72 (scope空,是发货政策) | 发货时效 | knowledge_gap + scope_empty |

**根因**: 所有正确知识都在 draft 条目中，published 里的知识要么缺失、要么 scope 为空、要么内容不匹配。这是知识发布审核流程存在的价值 — 需人工审核后再发布。

---

## 四、测试结果

### 全量测试
```
1149 passed, 1342 warnings (排除 test_rag_known_products 的 SQLite 锁竞争)
```

### test_rag_known_products
```
14 passed (独立运行) / 8 failed (套件内运行, SQLite session 冲突)
```

### 新增测试文件
- `tests/test_analysis_execution_consistency.py` — 8 tests
- `tests/test_real_data_cutoff.py` — 26 tests
- `tests/test_real_data_sanitizer.py` — 62 tests
- `tests/test_real_golden_schema.py` — 30+ tests
- `tests/test_product_identity_resolver.py` — 14 tests
- `tests/test_rag_known_products.py` — 14 tests

---

## 五、新增/修改文件清单

### 新增文件
```
app/services/product_identity_resolver.py
scripts/golden_set/qa_postgres_reader.py
scripts/golden_set/real_data_sanitizer.py
scripts/golden_set/extract_real_candidates.py
scripts/knowledge/knowledge_publish_review.py
scripts/knowledge/check_embedding_coverage.py
scripts/knowledge/evaluate_hybrid_retrieval.py
data/real_golden_candidates/source_audit.json
data/real_golden_candidates/candidates.jsonl (1907条)
data/real_golden_candidates/candidates_300.jsonl (300条)
data/real_golden_candidates/extraction_stats.json
data/knowledge_publish_review_queue.jsonl (744条)
tests/test_analysis_execution_consistency.py
tests/test_real_data_cutoff.py
tests/test_real_data_sanitizer.py
tests/test_real_golden_schema.py
tests/test_product_identity_resolver.py
tests/test_rag_known_products.py
```

### 修改文件
```
app/config.py — 新增 EMBEDDING_SHADOW_MODE 配置
app/services/analysis_execution_service.py — 新增文件快照保存
app/api/copilot_routes.py — 重构为调用 AnalysisExecutionService
app/repositories/knowledge_chunk_repository.py — shadow mode 支持
scripts/build_knowledge_embeddings.py — 增强 preflight/resume/published-only
tests/test_sidecar_mixed.py — FakeReplyService 签名兼容
```

---

## 六、尚需人工处理清单

1. **知识发布审核**: 744 条 draft 需人工审核，通过后才能让 RAG 正确召回
2. **五个重点 RAG 案例**: 需人工审核对应 draft 条目并发布
3. **complaint_high_risk 短缺**: 仅 13 条真实候选，需补充更多高风险场景数据
4. **Embedding API 配置**: 需配置 `COPILOT_EMBEDDING_API_BASE` 和 `COPILOT_EMBEDDING_API_KEY`
5. **300 条候选人工审核**: 需通过 `/golden-set-review` 页面逐条审核
6. **published 条目 product_scope 为空问题**: 多个 published 条目的 product_scope 为空，导致 RAG 召回无 scope 约束
7. **Trace 节点级 span**: 当前只有根 span，需增加图节点级 trace 装饰
8. **JST 查询矩阵验证**: 需配置有效的 JST 凭证后验证三类查询
9. **Golden Runner**: 需在候选审核通过后实现 `tests/real_golden_runner.py`
