# 客服 Copilot - LangGraph 完整链路架构文档

> 系统基于 **LangGraph StateGraph** 构建，用于电商客服（尹荷/INHE 儿童家具）的智能应答，集成聚水潭 ERP 和千牛卖家平台。

---

## 一、入口与调用链

```
千牛侧边栏 / CLI
       │
       ▼
  /api/copilot/context  (Flask)
       │
       ▼
  ReplyService.analyze()  ── 构造初始 AgentState
       │
       ▼
  customer_service_graph.invoke(state)  ── LangGraph 执行
       │
       ▼
  返回 ReplySuggestion (建议回复 + 元数据)
```

---

## 二、状态定义 (AgentState)

`TypedDict(total=False)`，约 **90+ 字段**，按职责分组：

### 2.1 输入字段
| 字段 | 类型 | 说明 |
|------|------|------|
| `customer_message` | str | 客户原始消息 |
| `conversation_id` | str | 会话 ID |
| `order_id` | str | 订单号（外部传入） |
| `tracking_no` | str | 物流单号（外部传入） |

### 2.2 意图与路由
| 字段 | 说明 |
|------|------|
| `normalized_message` | 清洗后的消息 |
| `intent` | 主意图（complaint / delivery_not_received / aftersales / installation / logistics_eta / product_question / general） |
| `skill` | 技能路由结果 |
| `response_strategy` | 7 种策略之一 |
| `router_decision` / `router_source` / `router_confidence` | LLM 路由器决策 |
| `answer_mode` | 回答模式（exact_faq / product_fact / policy / sop / clarification 等） |

### 2.3 槽位提取
| 字段 | 说明 |
|------|------|
| `slots` | 结构化槽位字典（order_id, tracking_no, carrier, product_name, sku_code 等） |
| `identifier_type` | 标识符类型（internal_order_id / platform_trade_id / tracking_no / unknown_identifier / none） |
| `identifier_value` | 标识符值 |

### 2.4 风险
| 字段 | 说明 |
|------|------|
| `risk_level` | low / medium / high / critical |
| `requires_human_review` | 是否需要人工审核 |
| `review_reason` | 审核原因 |

### 2.5 订单与物流
| 字段 | 说明 |
|------|------|
| `order` / `live_order` | 本地/实时订单数据 |
| `logistics` / `live_logistics` | 本地/实时物流数据 |
| `order_status` | 统一订单状态码（unpaid/canceled/refunded/aftersales/pending_shipment/presale/out_of_stock/partially_shipped/shipped/delivered/abnormal） |
| `logistics_trace` | 物流轨迹（status, carrier, tracking_no, events, latest, low_confidence） |
| `order_found` / `order_source` | 订单是否找到及来源 |

### 2.6 产品识别
| 字段 | 说明 |
|------|------|
| `product_candidates` | 产品候选列表 |
| `need_clarification` | 是否需要客户澄清 |
| `order_product_identity` | 订单产品标识 |
| `matched_product_name` | 匹配到的产品名 |
| `shipping_policy` | 匹配到的物流政策 |

### 2.7 证据层
| 字段 | 说明 |
|------|------|
| `evidence` | 7 桶证据（order_facts, logistics_facts, product_facts, policy_facts, sop_evidence, template_evidence, faq_evidence）+ unknowns, conflicts |
| `retrieved_chunks` | RAG 检索结果 |
| `filtered_evidence` | 过滤后的证据 |
| `knowledge_evidence` | 知识库证据 |
| `consistency_status` | 一致性校验结果（matched / conflict / need_order_lookup） |

### 2.8 工具注册表
| 字段 | 说明 |
|------|------|
| `allowed_tools` / `required_tools` / `forbidden_tools` | 工具权限列表 |
| `tool_plan` | 工具执行计划 |
| `tool_results` / `tool_traces` | 工具执行结果与追踪 |

### 2.9 并行理解层
| 字段 | 说明 |
|------|------|
| `parallel_understanding` | 8 个分析器的原始输出 |
| `decision_fusion` | 融合后的统一决策 |
| `safety_contract` | 安全合约（forbidden_claims, requires_evidence_for, must_escalate_if） |
| `final_intent` / `secondary_intents` | 融合后的意图 |
| `analyzer_durations` | 各分析器耗时 |

### 2.10 客户状态
| 字段 | 说明 |
|------|------|
| `customer_emotion` | neutral / anxious / angry / frustrated / polite / confused |
| `customer_urgency` | 紧急程度 |
| `customer_concern` | 关注点（12 种类型） |

### 2.11 回复生成
| 字段 | 说明 |
|------|------|
| `suggested_reply` | 最终建议回复 |
| `reply_goal` | 回复目标 |
| `reply_style` | 回复风格 |
| `generation_mode` | 生成模式（rule / llm） |
| `policy_warnings` | 政策警告 |
| `hallucination_guard` | 幻觉检查结果 |

### 2.12 上下文与追踪
| 字段 | 说明 |
|------|------|
| `conversation_context` | 历史会话上下文 |
| `copilot_context` | 千牛侧边栏上下文 |
| `trace_steps` | 节点执行追踪（审计链） |
| `evidence_debug` | 隐私安全的证据摘要 |

---

## 三、完整图拓扑 (40 个节点)

### 3.1 线性前端（所有路径共享）

```
┌─────────────────────┐
│   normalize_input   │  ← 入口节点
└──────────┬──────────┘
           ▼
┌──────────────────────────────┐
│ load_conversation_context    │  ← 加载历史会话状态
└──────────┬───────────────────┘
           ▼
┌──────────────────────────────┐
│   parallel_understanding     │  ← 8 个分析器并行（ThreadPoolExecutor）
│   ┌────────────────────────┐ │
│   │ intent_classifier      │ │  意图分类（14 类）
│   │ risk_classifier        │ │  风险分级（3 级）
│   │ slot_entity_extractor  │ │  槽位/实体提取
│   │ context_resolver       │ │  上下文消歧
│   │ customer_state_analyzer│ │  客户情绪/关注点
│   │ tool_need_predictor    │ │  工具需求预测
│   │ knowledge_scope_pred.  │ │  知识范围预测
│   │ safety_precheck        │ │  安全预检（SafetyContract）
│   └────────────────────────┘ │
└──────────┬───────────────────┘
           ▼
┌──────────────────────────────┐
│     decision_fusion          │  ← 融合 8 个分析器输出
│  final_intent / risk_level   │  ← 统一决策（观察模式）
│  tool lists / safety_contract│
└──────────┬───────────────────┘
           ▼
┌──────────────────────────────┐
│      detect_intent           │  ← 规则优先级匹配意图
└──────────┬───────────────────┘
           ▼
┌──────────────────────────────┐
│       risk_check             │  ← 关键词风险检测
└──────────┬───────────────────┘
           ▼
┌──────────────────────────────┐
│    build_base_context        │  ← 加载订单/产品/知识/SOP/模板
└──────────┬───────────────────┘
           ▼
┌──────────────────────────────┐
│     route_by_intent          │  ← 记录路由决策到 trace
└──────────┬───────────────────┘
           ▼
┌──────────────────────────────┐
│       slot_extract           │  ← 正则提取所有标识符
└──────────┬───────────────────┘
           ▼
┌──────────────────────────────┐
│ apply_conversation_context   │  ← 用历史上下文消歧
└──────────┬───────────────────┘
           ▼
┌──────────────────────────────┐
│   order_product_resolver     │  ← 多路径产品身份解析
└──────────┬───────────────────┘
           ▼
┌──────────────────────────────┐
│    llm_intent_router         │  ← LLM 语义路由（Qwen）
└──────────┬───────────────────┘
           ▼
┌──────────────────────────────┐
│    router_validation         │  ← 硬规则覆盖 LLM 决策
└──────────┬───────────────────┘
           ▼
┌──────────────────────────────────┐
│ parallel_pre_strategy_controls   │  ← 高风险门控 + 意图覆盖
└──────────┬───────────────────────┘
           ▼
┌──────────────────────────────┐
│  customer_state_analyzer     │  ← LLM 情绪/关注点分析
└──────────┬───────────────────┘
           ▼
┌──────────────────────────────┐
│ response_strategy_router     │  ← ★ 核心策略决策节点
└──────────┬───────────────────┘
           ▼
┌──────────────────────────────────┐
│ parallel_post_strategy_controls  │  ← 策略后工具覆盖
└──────────┬───────────────────────┘
           │
           ▼
    ═══════════════════
    ║  策略分叉点 ★  ║
    ═══════════════════
```

---

### 3.2 策略分叉路由（7 条路径）

| 策略 | 目标节点 |
|------|----------|
| `high_risk` | → knowledge_scope_router |
| `aftersales` | → knowledge_scope_router |
| `installation` | → resolve_product_identity |
| `logistics_with_order` | → identifier_router |
| `logistics_policy_without_order` | → resolve_product_identity |
| `product_question` | → resolve_product_identity |
| `clarification`（默认） | → response_strategy_planner |

---

### 3.3 子链路详解

#### 链路 A：高风险 / 售后链路

```
knowledge_scope_router
        │
        ├─ high_risk ──→ tool_planner
        │                     │
        │                     ▼
        │              tool_executor_node
        │                     │
        │          ┌──────────┴──────────┐
        │          ▼                     ▼
        │    evidence_builder      jst_live_query (fallback)
        │          │
        │          ▼
        │  response_strategy_planner
        │          │
        │          ▼
        │   generate_reply
        │
        └─ aftersales ──→ rag_retrieve
                               │
                               ▼
                        evidence_filter_node
                               │
                               ▼
                        evidence_builder
                               │
                               ▼
                  response_strategy_planner
                               │
                               ▼
                        generate_reply
```

#### 链路 B：有订单物流链路

```
identifier_router
        │
        ├─ 高风险 ──→ human_review_gate
        │
        ├─ 有 order_id + tracking_no ──→ verify_consistency
        │                                      │
        │                           ┌──────────┴──────────┐
        │                           ▼                     ▼
        │                      matched → tool_planner   conflict → human_review_gate
        │                                      │
        │                                      ▼
        │                               tool_executor_node
        │                                      │
        │                                      ▼
        │                               evidence_builder
        │                                      │
        │                                      ▼
        │                         response_strategy_planner
        │                                      │
        │                                      ▼
        │                          generate_logistics_reply
        │
        ├─ 有 order_id / platform_trade_id ──→ tool_planner → ...
        │
        ├─ 有 product_name ──→ resolve_product_identity
        │
        └─ 无标识符 ──→ generate_reply (澄清)
```

#### 链路 C：产品 / 安装 / 无订单物流链路

```
resolve_product_identity
        │
        ├─ 有 order_id ──→ jst_live_query → resolve_order_status
        │                    → match_shipping_policy
        │                    → knowledge_scope_router → ...
        │
        ├─ 需澄清 ──→ generate_logistics_reply
        │
        ├─ product_question 策略 ──→ tool_planner → ...
        │
        └─ 其他 ──→ match_shipping_policy → ...
```

#### 链路 D：澄清链路

```
response_strategy_planner
        │
        ▼
generate_reply
```

---

### 3.4 通用尾链（所有路径汇聚）

```
generate_reply / generate_logistics_reply
        │
        ▼
┌──────────────────────────────┐
│  hallucination_guard         │  ← 产品事实幻觉检查（仅 generate_reply）
└──────────┬───────────────────┘
           ▼
┌──────────────────────────────┐
│  gold_csr_reply_builder      │  ← 金牌客服话术打磨
└──────────┬───────────────────┘
           ▼
┌──────────────────────────────┐
│  factual_guard               │  ← 6 维事实校验 + 安全合约执行
│  A. 订单事实保护             │
│  B. 物流政策保护             │
│  C. 产品事实保护             │
│  D. 售后保护                 │
│  E. 高风险保护               │
│  F. 知识证据质量门控 (P2.5)  │
└──────────┬───────────────────┘
           ▼
┌──────────────────────────────┐
│  build_response              │  ← 最终组装 + evidence_debug
└──────────┬───────────────────┘
           ▼
┌──────────────────────────────┐
│  update_conversation_context │  ← 持久化会话状态
└──────────┬───────────────────┘
           ▼
┌──────────────────────────────┐
│  quality_guard               │  ← 输出质量检查（OutputGuard）
└──────────┬───────────────────┘
           ▼
┌──────────────────────────────┐
│  human_review_gate           │  ← 人工审核标记
└──────────┬───────────────────┘
           ▼
          END
```

---

## 四、条件路由决策表

| 路由函数 | 位置 | 决策逻辑 |
|----------|------|----------|
| `_route_after_risk_check` | risk_check 之后 | 始终 → build_base_context |
| `_route_after_strategy` | parallel_post_strategy_controls 之后 | 7 路分支（见 3.2） |
| `_route_after_identifier` | identifier_router 之后 | 高风险→human_review；有 order+tracking→verify；有 order→tool_planner；有 product→resolve；无→clarification |
| `_route_after_verify_consistency` | verify_consistency 之后 | conflict→human_review；else→tool_planner |
| `_route_after_resolve_product` | resolve_product_identity 之后 | 有 order_id→jst_live_query；需澄清→clarification；product_question→tool_planner；else→match_shipping_policy |
| `_route_after_evidence` | evidence_builder 之后 | 物流策略→logistics_reply；else→general_reply |
| `_route_after_strategy_plan` | response_strategy_planner 之后 | 同上 |
| `_route_after_tool_executor` | tool_executor_node 之后 | JST 工具成功→evidence_builder；JST 未找到→jst_fallback |
| `_route_after_knowledge_scope` | knowledge_scope_router 之后 | high_risk→tool_planner；else→rag_retrieve |

---

## 五、工具注册表

| 工具名 | 功能 | 允许意图 | 超时 |
|--------|------|----------|------|
| `jst_lookup_order` | 聚水潭订单查询（o_id / so_id） | logistics_eta, logistics_trace, delivery_not_received, aftersales | 3000ms |
| `jst_lookup_outbound` | 聚水潭销售出库查询（outer_so_id） | logistics_eta, logistics_trace, delivery_not_received | 3000ms |
| `jst_lookup_tracking` | 聚水潭物流查询（tracking_no） | logistics_eta, logistics_trace, delivery_not_received | 3000ms |
| `rag_search` | 混合 RAG 检索（文本 + 向量） | 全意图 | 2000ms |
| `product_resolver` | 产品匹配 | product_question, installation, logistics | 1000ms |
| `sop_lookup` | SOP 和禁止声明查询 | complaint, aftersales, delivery_not_received | 1000ms |
| `template_select` | 回复模板选择 | 全意图 | 500ms |

---

## 六、并行理解层（Phase 1 观察模式）

8 个分析器在 `parallel_understanding` 节点中通过 `ThreadPoolExecutor` 并发执行：

```
parallel_understanding
    │
    ├── intent_classifier          → primary_intent, secondary_intents
    ├── risk_classifier            → risk_level, requires_human_review
    ├── slot_entity_extractor      → slots (order_id, tracking_no, product...)
    ├── context_resolver           → is_followup, active_issue
    ├── customer_state_analyzer    → emotion, concern, urgency
    ├── tool_need_predictor        → required/allowed/forbidden tools
    ├── knowledge_scope_predictor  → allowed/forbidden source types
    └── safety_precheck            → SafetyContract
    │
    ▼
decision_fusion
    │
    ├── final_intent          (融合意图)
    ├── risk_level            (取最高级)
    ├── tool lists            (合并权限)
    ├── answer_mode           (决定回答模式)
    ├── reply_goal            (回复目标)
    └── safety_contract       (安全合约)
```

当前为**观察模式** (`parallel_observation_mode=True`)：融合结果被记录，但仅在以下场景生效（通过配置开关控制）：

| 开关 | 默认 | 作用 |
|------|------|------|
| `ENABLE_PARALLEL_HIGH_RISK_GATE` | True | 高风险时强制人工审核 |
| `ENABLE_PARALLEL_SAFETY_CONTRACT` | True | 执行安全合约 |
| `ENABLE_PARALLEL_FUSION_ROUTING` | False | 允许融合结果覆盖规则意图 |
| `ENABLE_PARALLEL_IDENTIFIER_ROUTING` | False | 允许融合结果选择 JST 工具 |

---

## 七、数据流分层架构

```
Layer 0 ─ Input           客户消息 + 千牛侧边栏上下文
    │
Layer 1 ─ Parallel        8 个并发分析器
    │
Layer 2 ─ Intent/Risk     意图识别 + 风险分级 + 槽位提取
    │
Layer 3 ─ Product         多源产品身份解析（本地 + JST + RAG）
    │
Layer 4 ─ Strategy        策略路由 + 工具规划
    │
Layer 5 ─ Fact Collection JST 实时查询 + RAG 检索
    │
Layer 6 ─ Evidence        7 桶证据分层 + 质量元数据
    │
Layer 7 ─ Generation      基于证据的回复生成（规则 / LLM）
    │
Layer 8 ─ Safety Guards   幻觉检查 → 事实校验 → 输出守卫 → 人工审核
```

---

## 八、回复生成策略

### 8.1 非物流回复 (`generate_reply`)

| 场景 | 处理方式 |
|------|----------|
| `exact_faq_answer` | 精确匹配 FAQ，直接渲染（无 LLM） |
| `product_fact_answer` | 产品事实，直接渲染（无 LLM） |
| `no_evidence_clarification` | 无证据时返回澄清提示 |
| policy / sop 模式 | LLM 生成 + 严格证据约束 |
| 社交问候 / 高风险 | 规则兜底 |

### 8.2 物流回复 (`generate_logistics_reply`)

| 场景 | 处理方式 |
|------|----------|
| 冲突 | 转人工审核 |
| 需澄清 | 澄清问题 |
| delivery_not_received | 共情 + 核实引导 |
| 有订单 | 按 order_status 分支（8 种状态） |
| 有物流轨迹无订单 | 物流信息展示 |
| 有 tracking_no 无订单 | 尝试查询 |
| 有 order_id 未找到 | 告知未找到 |
| 有产品匹配 | 基于物流政策的 ETA 回复 |
| 无标识符 | 请求订单号 |
| 时间承诺场景 | 边界设定回复 |

---

## 九、安全管线

```
generate_reply / generate_logistics_reply
        │
        ▼
  ┌─────────────────┐
  │ hallucination_   │  检查 HIGH_RISK_TERMS（实木/承重/尺寸...）
  │ guard            │  不支持 → 回退 FAQ 或澄清
  └────────┬────────┘
           ▼
  ┌─────────────────┐
  │ gold_csr_reply_  │  按 reply_goal 打磨话术
  │ builder          │  保留 grounded 答案
  └────────┬────────┘
           ▼
  ┌─────────────────┐
  │ factual_guard    │  6 维事实校验：
  │                  │  A. 订单事实保护
  │                  │  B. 物流政策保护（禁止承诺）
  │                  │  C. 产品事实保护
  │                  │  D. 售后保护（禁止自动承诺退款）
  │                  │  E. 高风险保护
  │                  │  F. 知识证据质量门控
  │                  │  + SafetyContract 禁止声明执行
  └────────┬────────┘
           ▼
  ┌─────────────────┐
  │ quality_guard    │  OutputGuard 禁止内容检查
  └────────┬────────┘
           ▼
  ┌─────────────────┐
  │ human_review_    │  标记人工审核（Phase 1 不中断）
  │ gate             │
  └─────────────────┘
```

---

## 十、会话上下文管理

三个节点管理跨轮次状态：

| 节点 | 时机 | 作用 |
|------|------|------|
| `load_conversation_context` | 链路开头 | 从内存 ContextStore 加载历史状态 |
| `apply_conversation_context` | 槽位提取后 | 消歧跟发消息（裸数字 + 上下文 → 标识符） |
| `update_conversation_context` | 回复生成后 | 持久化当前状态供下轮使用 |

`ConversationContext` 追踪 22 个字段，包括已知标识符、活跃问题、客户情绪、未解决槽位、上次回复等。

---

## 十一、外部集成

| 系统 | 用途 | 接口 |
|------|------|------|
| 聚水潭 OpenAPI | 订单/出库/物流实时查询 | REST API（JST_APP_KEY/SECRET/TOKEN） |
| 通义千问 (Qwen) | 意图路由、情绪分析、工具选择、回复生成 | OpenAI-compatible API (DashScope) |
| 钉钉多维表格 | 知识管理 | DingTalk Multi-table API |
| 千牛侧边栏 | 客服操作界面 | HTTP + SidecarContext |

---

## 十二、配置开关

| 开关 | 默认值 | 说明 |
|------|--------|------|
| `USE_LLM_FOR_EXACT_FAQ` | False | FAQ 答案是否用 LLM |
| `USE_LLM_FOR_PRODUCT_FACTS` | False | 产品事实是否用 LLM |
| `USE_LLM_FOR_POLICY_REWRITE` | True | 政策回复是否 LLM 润色 |
| `USE_LLM_FOR_SOP_REWRITE` | True | SOP 回复是否 LLM 润色 |
| `FAQ_EXACT_SCORE_THRESHOLD` | 0.45 | FAQ 精确匹配最低分 |
| `EMBEDDING_ENABLED` | False | 向量嵌入 RAG |
| `ENABLE_PARALLEL_FUSION_ROUTING` | False | 融合结果覆盖规则意图 |
| `ENABLE_PARALLEL_SAFETY_CONTRACT` | True | 执行安全合约 |
| `ENABLE_PARALLEL_IDENTIFIER_ROUTING` | False | 融合结果选择 JST 工具 |
| `ENABLE_PARALLEL_HIGH_RISK_GATE` | True | 高风险门控 |

---

## 十三、完整执行示例（物流查询场景）

```
客户: "我的订单 SF1234567890 到哪了"

normalize_input
  → load_conversation_context (无历史)
  → parallel_understanding (8 分析器并发)
      intent: logistics_eta
      risk: low
      slots: { tracking_no: "SF1234567890" }
      tools: { required: [jst_lookup_tracking] }
  → decision_fusion
      final_intent: logistics_eta, risk: low
  → detect_intent → logistics_eta
  → risk_check → low
  → build_base_context (加载产品/知识)
  → route_by_intent
  → slot_extract → identifier_type: tracking_no
  → apply_conversation_context
  → order_product_resolver
  → llm_intent_router → logistics_eta (高置信度)
  → router_validation → 通过
  → parallel_pre_strategy_controls
  → customer_state_analyzer → neutral
  → response_strategy_router → logistics_with_order
  → parallel_post_strategy_controls
  → identifier_router → has tracking_no → tool_planner
  → tool_planner → [jst_lookup_tracking]
  → tool_executor_node → 查询聚水潭
  → evidence_builder → logistics_facts 填充
  → response_strategy_planner → query_order_status
  → generate_logistics_reply → "已发货，顺丰 SF1234567890，当前状态：派送中..."
  → gold_csr_reply_builder → 润色
  → factual_guard → 通过
  → build_response → 组装最终结果
  → update_conversation_context → 保存 tracking_no
  → quality_guard → 通过
  → human_review_gate → 不需要审核
  → END
```

---

## 十四、架构亮点与当前状态

### 亮点
1. **分层证据架构**：7 桶证据 + 质量元数据，确保回复有据可查
2. **多层安全防线**：幻觉检查 → 事实校验 → 输出守卫 → 人工审核
3. **并行理解层**：8 个分析器并发，通过 observation mode 渐进式上线
4. **LLM + 规则双轨**：关键路径用规则兜底，非关键路径用 LLM 增强
5. **会话上下文管理**：支持多轮对话消歧和跟发消息理解

### 当前阶段
- 并行理解层处于**观察模式**，4 个开关控制渐进式切换
- 工具注册表为**新增路径**，与传统 JST 直查路径并存
- 40 个节点的图较为复杂，部分路径存在功能重叠（如 `resolve_order_status` 与 `tool_executor_node` 的状态映射）

---

> **文件位置**: `copilot/app/agent/graph.py` (图定义), `copilot/app/agent/state.py` (状态), `copilot/app/agent/tools/registry.py` (工具)
