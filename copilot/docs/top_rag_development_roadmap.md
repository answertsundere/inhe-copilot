# INHE 客服 Copilot 顶级 RAG 开发路线图

> 目标：把当前“可内部试用的轻量 RAG”升级为“商品身份准确、证据字段匹配、安全可控、可持续人工验收迭代”的生产级母婴客服 RAG。

## 0. 总结

当前系统已经不是从零开始：

- 已有 LangGraph/Agent 主链路。
- 已有 Product Identity Resolver，能从 SKU、订单、侧边栏商品名、聚水潭查询映射到内部商品。
- 已有 RAG 检索、`source_type`、`product_scope`、`sku_scope`、`fact_type`、`fact_review_status` 等数据字段。
- 已有 Evidence Builder、Factual Guard、Hallucination Guard、Bad Case、Trace、人工测试面板。

但当前 RAG 仍偏轻量，核心短板是：

- `fact_type` 没有成为主检索和主门禁。
- 问题字段识别不稳定，很多场景靠关键词临时兜底。
- RAG 可以按商品/SKU 检索，但还不能稳定判断“这条证据是否能回答这个问题”。
- 知识库人工验收还没有形成“客服改答案 -> 结构化知识 -> 回归测试”的闭环。

因此升级方向不是推倒重做，而是把系统收敛成：

```text
商品身份识别
-> 意图识别
-> 问题字段识别 query_fact_type
-> 风险分级
-> fact_type-aware RAG
-> Evidence Gate
-> Grounded Reply
-> Safety Guard
-> Bad Case / 人工验收 / 评测闭环
```

## 1. 目标架构

### 1.1 主链路

```text
用户消息 / 千牛侧边栏 / 图片
↓
输入标准化 normalize_input
↓
上下文管理 conversation_context
↓
商品身份识别 ProductIdentityResolver
  - 售前：侧边栏天猫标题 -> 聚水潭 skumap/query -> SKU/i_id
  - 售后：订单号 / SKU -> 聚水潭订单/商品 -> SKU/i_id
↓
意图识别 intent_router
↓
问题字段识别 query_fact_type_classifier
↓
风险分级 risk_classifier
↓
策略路由 response_strategy_router
↓
工具调用 / RAG 检索
  - 订单/物流/售后进度：JST/API
  - 商品/安装/政策/安全知识：RAG
↓
Evidence Gate
  - 商品一致
  - SKU 一致
  - fact_type 一致
  - 审核状态允许
  - 风险等级允许
↓
回复生成 grounded_generation
↓
后置安全质检
↓
输出建议回复
↓
Trace / Bad Case / 人工验收 / 回归测试
```

### 1.2 五层知识体系

| 知识层 | source_type | 主要内容 | 是否可直接回复 |
|---|---|---|---|
| 产品事实库 | `product_facts` | 材质、尺寸、承重、适用年龄、配件清单 | 仅 verified/published |
| 安装库 | `installation_guide` | 安装步骤、配件位置、常见装反 | 低风险可直接答，高风险需复核 |
| 安全 SOP | `high_risk_sop` / `forbidden_rules` | 误吞、夹伤、倾倒、电池、小零件 | 多数需人工复核 |
| 售后政策库 | `aftersales_policy` / `shipping_policy` | 退换、补发、价保、发票、物流规则 | 按政策和订单状态 |
| FAQ/话术库 | `faq` / `response_templates` | 常见问法、客服表达 | 不能覆盖产品事实和安全 SOP |

### 1.3 核心原则

```text
Prompt 管语气。
规则管安全。
RAG 管知识。
工具管实时数据。
评测管质量。
```

## 2. 当前系统评估

### 2.1 已具备能力

| 能力 | 当前状态 | 代码位置 |
|---|---|---|
| 意图路由 | 已有，多处规则 + LLM | `app/agent/nodes/detect_intent.py`, `llm_intent_router.py`, `router_validation.py` |
| 策略路由 | 已有 | `app/agent/nodes/response_strategy_router.py` |
| 商品身份识别 | 已有，含 JST 名称/订单/SKU 解析 | `app/agent/nodes/order_product_resolver.py` |
| RAG 检索 | 已有 SQLite hybrid/FTS + KBQA fallback | `app/agent/nodes/rag_retrieve.py`, `app/retrieval/current_sqlite_retriever.py` |
| Metadata | 已有字段但未完全主干化 | `app/models/knowledge_base.py` |
| Evidence Builder | 已有 | `app/agent/nodes/evidence_builder.py` |
| RAG Judge | 已有雏形 | `app/agent/nodes/rag_judge_node.py`, `app/services/rag_judge_service.py` |
| 安全守卫 | 已有 | `factual_guard.py`, `hallucination_guard.py`, `post_generation_grounding_guard.py` |
| 人工测试面板 | 已有 | `web/templates/real_test_panel.html` |
| Bad Case | 已有 | `data/bad_cases.jsonl`, `app/services/bad_case_service.py` |

### 2.2 主要短板

| 短板 | 表现 | 后果 |
|---|---|---|
| `query_fact_type` 不稳定 | “甲醛报告”可能按普通商品问答处理 | 召回承重/材质 FAQ 答非所问 |
| `fact_type` 未强过滤 | RAG 只要同 SKU 就可能直接答 | 同商品不同字段互串 |
| FAQ fallback 太宽 | KBQA 分数高就进入答案 | 问基础款差异却答材质，问检测报告却答承重 |
| 知识审核粒度不足 | draft/published 有，但字段级可答性不够 | 高风险事实容易误答或过度拒答 |
| 人工反馈未结构化 | Bad Case 能记录，但未自动转知识任务 | 迭代成本高 |

## 3. 数据标准

### 3.1 知识条目标准字段

每条可用于自动回复的知识，最终应至少具备：

```json
{
  "source_type": "product_facts",
  "intent": "product_question",
  "query_fact_type": "material",
  "fact_type": "material",
  "product_scope": ["九号防夹滑门收纳柜"],
  "sku_scope": ["YH06K53B05S13"],
  "risk_level": "medium",
  "fact_review_status": "verified",
  "auto_reply_allowed": true,
  "human_review_required": true,
  "content": "主要采用冷轧钢管/环保PP/无纺布等材质..."
}
```

### 3.2 fact_type 字典

第一版先使用以下枚举：

| fact_type | 含义 | 示例问法 | 默认风险 |
|---|---|---|---|
| `material` | 材质/材料 | 什么材质，安全吗，环保吗 | medium |
| `certification_report` | 检测/质检/甲醛/证书 | 有甲醛报告吗，有 3C 吗 | high |
| `load_capacity` | 承重/容量 | 承重多少，能放多重 | medium |
| `dimensions` | 尺寸/高度/长度 | 多高，多宽，占地多大 | medium |
| `age_range` | 适用年龄 | 多大宝宝能用 | high |
| `cleaning_care` | 清洁保养 | 可以水洗吗，脏了怎么清洁 | medium |
| `odor` | 气味/异味 | 有没有味道，刺鼻吗 | high |
| `installation` | 安装 | 怎么装，缺螺丝，装不上 | low/medium |
| `variant_compare` | 款式差异 | 基础款升级款差什么 | medium |
| `stock_shipping` | 库存/发货 | 今天能发吗，还有货吗 | low |
| `invoice_policy` | 发票 | 可以开发票吗 | low |
| `price_protection` | 价保 | 可以保价吗 | low |
| `promotion_policy` | 优惠/活动 | 有什么优惠，能送吗 | low |
| `safety_small_parts` | 小零件/电池/误吞 | 宝宝会不会吞，电池盖松 | high/critical |
| `aftersales_policy` | 售后规则 | 能退吗，能补发吗 | medium |

### 3.3 风险等级

| 等级 | 含义 | 自动回复策略 |
|---|---|---|
| L1 | 普通咨询 | 有 verified 证据可直接答 |
| L2 | 中等风险 | 有 verified 证据可答，建议保守措辞 |
| L3 | 高风险 | 必须带人工复核或明确下一步 |
| L4 | 紧急风险 | 不等 RAG，直接安全指引 + 人工升级 |

## 4. 分阶段开发路线

## Phase 1：稳定当前 RAG 主链路

### 目标

先解决当前最常见的“同商品错字段回答”。

### 开发项

1. 新增 `query_fact_type_classifier`
   - 输入：用户消息、intent、商品身份、历史上下文。
   - 输出：`query_fact_type`、`confidence`、`matched_terms`、`risk_hint`。
   - 先规则为主，LLM fallback 为辅。

2. 将 `query_fact_type` 写入 state
   - 后续 RAG、Evidence Gate、测试面板都读取该字段。

3. 修改 RAG 检索参数
   - 当前参数：`query/source_types/product_scope/sku_scope`。
   - 新增：`fact_type=query_fact_type`。
   - 没有精确 fact_type 时允许同 intent fallback，但不得跨高风险字段。

4. 升级 `_best_faq_evidence`
   - 不再只看分数。
   - 必须通过 fact_type 相关性。

5. 测试面板显示
   - `query_fact_type`
   - 命中的 evidence `fact_type`
   - Evidence Gate 通过/拒绝原因。

### 验收标准

- 问“没有甲醛检查报告吗”不能用承重/材质 FAQ 直接回答。
- 问“什么材质”能用 material 证据回答。
- 问“基础款升级款差什么”不能用普通材质证据硬答。
- 问“适合几个月宝宝”不能用安装/承重证据硬答。

### 相关文件

- `app/agent/nodes/detect_intent.py`
- `app/agent/nodes/query_fact_type_classifier.py`（新增）
- `app/agent/nodes/rag_retrieve.py`
- `app/retrieval/current_sqlite_retriever.py`
- `app/agent/nodes/generate_reply.py`
- `web/templates/real_test_panel.html`

## Phase 2：结构化 Evidence Gate

### 目标

让系统回答前必须通过“证据资格审查”，不再靠生成阶段临时兜底。

### 开发项

1. 新增 `evidence_fact_gate`
   - 检查商品/SKU/fact_type/source_type/review_status/risk_level。

2. 证据分级
   - `direct_answer_allowed`
   - `reference_only`
   - `requires_human_review`
   - `blocked_wrong_fact_type`
   - `blocked_unverified`

3. 与现有 `rag_judge_node` 合并或串联
   - `rag_judge_node` 做确定性拒绝。
   - `evidence_fact_gate` 做结构化可答性判定。

4. 输出标准拒绝原因
   - `wrong_product`
   - `wrong_sku`
   - `wrong_fact_type`
   - `unverified_high_risk_fact`
   - `no_verified_evidence`

### 验收标准

- 每条最终回答都能在 debug 里看到采用了哪些证据。
- 每条被拒绝的证据都有拒绝原因。
- 高风险事实没有 verified 证据时不能直接给结论。

### 相关文件

- `app/agent/nodes/evidence_filter_node.py`
- `app/agent/nodes/rag_judge_node.py`
- `app/agent/nodes/evidence_builder.py`
- `app/services/rag_judge_service.py`
- `app/agent/nodes/build_response.py`

## Phase 3：知识库治理和人工验收闭环

### 目标

让客服部门优化知识库，而不是研发不断补规则。

### 开发项

1. 知识审核页面增加字段
   - `fact_type`
   - `risk_level`
   - `fact_review_status`
   - `auto_reply_allowed`
   - `human_review_required`
   - `applicable_skus`

2. Bad Case 转知识任务
   - Bad Case 可一键生成“待补知识”。
   - 人工最终回复可作为候选答案。
   - 必须人工审核后才 published。

3. 知识冲突检测
   - 同 SKU + 同 fact_type 出现多个不同答案，进入冲突队列。

4. 知识版本管理
   - 旧政策默认 archive，不参与自动回复。
   - 新版本发布后保留回滚能力。

### 验收标准

- 客服能在后台把一条 Bad Case 转成待审核知识。
- 审核通过后，该测试用例自动从失败变通过。
- 同 SKU 同 fact_type 冲突会提示人工处理。

### 相关文件

- `app/api/kb_admin_routes.py`
- `web/templates/knowledge_admin.html`
- `app/services/bad_case_service.py`
- `app/services/knowledge_lifecycle_service.py`
- `app/services/knowledge_quality_service.py`

## Phase 4：混合检索升级

### 目标

从当前 SQLite 轻量检索升级为更稳定的 hybrid retrieval。

### 开发项

1. 保留 SQLite 作为主库和回归基线。
2. 接入 embedding。
3. 支持 dense vector + keyword/BM25 融合。
4. 支持 metadata filter：
   - `source_type`
   - `product_scope`
   - `sku_scope`
   - `fact_type`
   - `risk_level`
   - `status`
5. 引入 rerank：
   - 先取 top 20。
   - rerank 后保留 top 3。

### 技术路线

先不急着换框架：

```text
阶段 A：SQLite + FTS + 规则 rerank
阶段 B：SQLite + embedding_json + hybrid score
阶段 C：接 Qdrant/其他向量库 shadow mode
阶段 D：稳定后切主检索
```

### 验收标准

- Recall@5 高于当前 SQLite baseline。
- 错字段召回率下降。
- SKU 精确词、配件名、螺丝型号不被向量语义冲掉。

### 相关文件

- `app/retrieval/current_sqlite_retriever.py`
- `app/retrieval/retriever_factory.py`
- `app/services/embedding_service.py`
- `copilot/docs/llamaindex_shadow_poc.md`

## Phase 5：上下文和多轮对话

### 目标

让 Agent 理解“这个/它/刚才那个/换一个商品”的上下文，但人工可以一键换上下文。

### 开发项

1. 当前测试面板已有 conversation_id，要继续强化。
2. conversation_context 存储：
   - confirmed_product
   - confirmed_sku
   - last_intent
   - last_query_fact_type
   - unresolved_slots
   - customer_state
3. 新对话按钮清空上下文。
4. 切换商品时重置商品相关上下文。
5. 多商品场景必须要求确认，不自动猜。

### 验收标准

- 用户问“这个什么材质”，能继承侧边栏商品。
- 用户下一句问“那适合几岁”，能继承同 SKU。
- 人工点击“新对话”后不再沿用上一商品。

### 相关文件

- `app/agent/context/conversation_context.py`
- `web/templates/real_test_panel.html`
- `app/services/reply_service.py`

## Phase 6：图片/VLM 融合

### 目标

客户发图时，VLM 只做观察和问题分类，不直接替代 Evidence Gate。

### 开发项

1. VLM 输出标准字段：
   - `image_type`
   - `issue_type`
   - `visible_text`
   - `detected_product`
   - `damage_or_missing_parts`
   - `requires_human_review`
2. 图片结果进入 query_fact_type。
3. 图片仅作为待核实证据，不直接承诺赔付/质量结论。
4. 高风险图片自动转人工。

### 验收标准

- 破损图：要求订单/清晰照片/人工核实。
- 缺件图：要求平铺图和订单明细核对。
- 安装图：能结合安装知识库给下一步。

### 相关文件

- `app/services/customer_image_vlm_service.py`
- `app/api/analyze_routes.py`
- `app/agent/nodes/generate_reply.py`

## Phase 7：评测系统

### 目标

每次改 RAG、prompt、知识库，都能知道有没有退化。

### 开发项

1. 建立固定评测集：
   - 商品事实 100 条。
   - 售后政策 50 条。
   - 物流工具 30 条。
   - 安全高风险 50 条。
   - 图片场景 30 条。
2. 每条评测用例包含：
   - 输入消息。
   - 侧边栏上下文。
   - 期望 intent。
   - 期望 query_fact_type。
   - 期望工具。
   - 必须命中的 evidence。
   - 禁止出现的错误话术。
3. 输出指标：
   - intent accuracy
   - fact_type accuracy
   - retrieval hit rate
   - evidence gate accuracy
   - answer correctness
   - safety recall
   - human review accuracy

### 验收标准

- 每次发版前跑核心评测集。
- P0/P1 Bad Case 必须有回归测试。
- 测试报告能定位失败层：路由、商品身份、检索、证据门禁、生成、安全守卫。

### 相关文件

- `tests/`
- `tests/golden_case_runner.py`
- `tests/simulated_customer_runner.py`
- `data/bad_cases.jsonl`
- `docs/manual_acceptance_test_cases_100.md`

## Phase 8：生产监控和灰度

### 目标

让系统可上线、可回滚、可观测。

### 开发项

1. Trace Dashboard
   - 每次请求显示路由、工具、RAG、证据、回复、人工反馈。
2. 知识版本灰度
   - 新知识先 shadow 检索，不直接影响自动回复。
3. 安全告警
   - L4 安全风险立即标记。
   - 高风险未转人工告警。
4. 成本和延迟监控
   - LLM 调用次数。
   - VLM 调用次数。
   - RAG 耗时。
   - JST 耗时。

### 验收标准

- 任意错误回答都能回放完整链路。
- 新知识发布后能对比发布前后效果。
- 高风险场景有监控和人工处理队列。

## 5. 推荐实施顺序

### 近期 1-3 天

1. 新增 `query_fact_type_classifier`。
2. RAG 支持 fact_type 过滤。
3. 测试面板显示 query_fact_type 和 evidence fact_type。
4. 补 20 条核心回归测试：
   - 材质
   - 甲醛报告
   - 承重
   - 适用年龄
   - 清洁
   - 款式差异
   - 发票
   - 价保
   - 库存
   - 赠品

### 近期 1 周

1. Evidence Gate 结构化。
2. Bad Case 一键转待补知识。
3. 知识后台补 fact_type 审核字段。
4. 评测集跑通 50-100 条。

### 中期 2-4 周

1. 知识库人工验收流程正式化。
2. 混合检索 + rerank 升级。
3. VLM 图片场景进入完整链路。
4. Trace Dashboard 补全。

### 长期 1-2 月

1. 向量库 shadow mode。
2. 灰度发布和版本回滚。
3. 安全事件工单/售后工单工具接入。
4. 生产指标看板。

## 6. 第一批落地任务清单

第一批不要大改架构，先做最能减少答非所问的核心闭环。

```text
Task 1: 新增 query_fact_type_classifier
Task 2: 在 state / debug / trace 中显示 query_fact_type
Task 3: RAG 检索加入 fact_type 过滤或 rerank 加权
Task 4: Evidence Gate 拒绝 wrong_fact_type
Task 5: real-test 面板展示 Evidence Gate 决策
Task 6: 增加 20 条回归测试
Task 7: 将 Bad Case 的 failure_type 映射到失败层
```

## 7. 不建议现在做的事

现在不要优先做：

- 直接替换成 LlamaIndex/LangChain。
- 直接上复杂向量库作为主链路。
- 无限扩写 prompt。
- 无限补关键词但不做 fact_type。
- 让 LLM 自由判断是否可答。

原因：当前核心问题不是框架弱，而是业务证据结构不够强。

## 8. 判断是否进入下一阶段的标准

进入 Phase 2 前：

- `query_fact_type` 准确率在核心测试集达到 90% 以上。
- 错字段回答 P0 明显减少。

进入 Phase 3 前：

- Evidence Gate 能解释每条证据通过/拒绝原因。
- 测试面板能看到完整证据链。

进入 Phase 4 前：

- SQLite baseline 指标稳定。
- 有可对比的 Recall@K / Answer Accuracy 报告。

进入 Phase 8 前：

- P0/P1 Bad Case 都有回归测试。
- 高风险场景都能稳定转人工或给安全边界。

## 9. 最终验收标准

顶级 RAG 不以“知识库多”为标准，而以这些结果为标准：

- 商品身份解析稳定。
- SKU/fact_type 证据匹配稳定。
- 高风险问题不漏判。
- 没有证据不编造。
- 有证据时不模板化拒答。
- 客服部门能持续维护知识。
- 每次改动都有评测报告。
- 任意错误都能追踪到失败层。

最终系统应该做到：

```text
售前：天猫商品名 -> 聚水潭 SKU -> fact_type RAG -> 证据门禁 -> 客服建议
售后：订单号/SKU -> JST 订单/商品 -> policy/SOP/RAG -> 证据门禁 -> 客服建议
图片：VLM 观察 -> issue_type/fact_type -> SOP/RAG/人工核实 -> 客服建议
```

