# customer_service_graph 节点说明表

> 本文档面向非技术人员，用于指导修改节点逻辑时参考。
> 所有节点位于 `app/agent/nodes/` 目录下。

---

## 节点总览

| 序号 | node_name | 中文职责 | 类型 |
|:---:|---|---|:---:|
| 1 | normalize_input | 输入清洗 | 普通 |
| 2 | detect_intent | 意图识别 | 普通 |
| 3 | risk_check | 风险检测 | 守卫 |
| 4 | build_base_context | 基础上下文构建 | 普通 |
| 5 | route_by_intent | 意图路由 | 决策 |
| 6 | query_jst_order | 聚水潭实时订单查询 | 查询 |
| 7 | query_local_order_fallback | 本地订单降级查询 | 查询 |
| 8 | check_shipment_status | 发货状态检查 | 查询 |
| 9 | match_order_products | 订单商品匹配 | 决策 |
| 10 | match_product_from_message | 消息商品名匹配 | 查询 |
| 11 | match_shipping_policy | 物流政策匹配 | 查询 |
| 12 | generate_reply | 回复生成 | 普通 |
| 13 | quality_guard | 质量守卫 | 守卫 |
| 14 | human_review_gate | 人工复核门 | 决策 |

---

## 1. normalize_input

- **中文职责**：清洗客户输入消息和订单号，去除多余空格。
- **输入字段**：`customer_message`, `order_id`
- **输出字段**：`normalized_message`（清洗后的消息）, `order_id`
- **是否调用工具**：否
- **是否可能失败**：几乎不可能（纯字符串操作）
- **失败兜底**：直接透传原始消息
- **是否涉及隐私**：否
- **是否可能触发人工审核**：否

---

## 2. detect_intent

- **中文职责**：根据关键词匹配识别客户意图。物流/到货时间相关统一映射为 `logistics_eta`。
- **输入字段**：`normalized_message`
- **输出字段**：`intent`, `skill`, `matched_keywords`
- **是否调用工具**：复用 `SkillRouter`
- **是否可能失败**：否（纯规则匹配）
- **失败兜底**：intent = "general"
- **是否涉及隐私**：否
- **是否可能触发人工审核**：否

---

## 3. risk_check

- **中文职责**：检测客户消息中的风险关键词，判定风险等级和是否需要人工复核。
- **输入字段**：`normalized_message`
- **输出字段**：`risk_level`（low/medium/high）, `requires_human_review`, `review_reason`
- **是否调用工具**：复用 `RiskService`
- **是否可能失败**：否（纯规则匹配）
- **失败兜底**：risk_level = "low"
- **是否涉及隐私**：否
- **是否可能触发人工审核**：**是**（本节点是触发人工审核的核心来源之一）

---

## 4. build_base_context

- **中文职责**：组装基础业务上下文，包括订单、商品、知识库、SOP、话术模板。
- **输入字段**：`normalized_message`, `order_id`
- **输出字段**：`order`, `logistics`, `products`, `product_knowledge`, `knowledge`, `sop_scenarios`, `reply_templates`, `data_quality_warnings`
- **是否调用工具**：复用 `ContextBuilder`（内部调用多个 Repository）
- **是否可能失败**：单个 Repository 失败不影响整体（优雅降级）
- **失败兜底**：缺失的上下文字段为空列表/None
- **是否涉及隐私**：**是**（原始订单可能包含隐私，但后续会过滤）
- **是否可能触发人工审核**：否

---

## 5. route_by_intent

- **中文职责**：根据意图和是否有订单号，决定后续走物流查询链路还是跳过订单查询。
- **输入字段**：`intent`, `order_id`
- **输出字段**：`trace_steps`（记录分支决策）, `order_found`（默认值）
- **是否调用工具**：否
- **是否可能失败**：否
- **失败兜底**：无
- **是否涉及隐私**：否
- **是否可能触发人工审核**：否

---

## 6. query_jst_order

- **中文职责**：优先查询聚水潭实时订单数据。
- **输入字段**：`order_id`
- **输出字段**：`live_order`, `live_logistics`, `order_found`（若成功）, `order_source` = "jst"
- **是否调用工具**：**是**（`OrderAdapter.query_jst`，调用 `LiveQueryService`）
- **是否可能失败**：**是**（API 未配置、网络超时、认证失败等）
- **失败兜底**：`order_found = False`，进入下一节点 `query_local_order_fallback`
- **是否涉及隐私**：**是**（API 返回原始订单数据）
- **是否可能触发人工审核**：否

> **如何修改**：不要直接写聚水潭 API 逻辑，改 `app/agent/tools/order_adapter.py` 中的 `query_jst` 方法。

---

## 7. query_local_order_fallback

- **中文职责**：聚水潭不可用或无结果时，降级查询本地预加载订单。
- **输入字段**：`order_id`, `order_found`（若 JST 已找到则跳过）
- **输出字段**：`order`, `logistics`, `order_found`, `order_source` = "local"
- **是否调用工具**：**是**（`OrderAdapter.query_local`，调用 `JsonOrderRepository`）
- **是否可能失败**：**是**（本地数据文件缺失）
- **失败兜底**：`order_found = False`
- **是否涉及隐私**：**是**（本地 JSON 含原始订单）
- **是否可能触发人工审核**：否

> **如何修改**：改 `app/agent/tools/order_adapter.py` 中的 `query_local` 方法，或替换 `local_order_repo` 实现。

---

## 8. check_shipment_status

- **中文职责**：根据订单数据判断发货状态（已签收 / 已发货 / 未发货 / 未知）。
- **输入字段**：`order` 或 `live_order`
- **输出字段**：`shipment_status`（signed/shipped/pending/unknown）
- **是否调用工具**：否
- **是否可能失败**：若订单数据格式异常可能判断错误
- **失败兜底**：`shipment_status = "unknown"`
- **是否涉及隐私**：否（只读取 status/l_id 等字段）
- **是否可能触发人工审核**：否

---

## 9. match_order_products

- **中文职责**：根据订单中的 SKU/i_id 匹配商品知识和库存信息。
- **输入字段**：`order` 或 `live_order`
- **输出字段**：`products`, `product_knowledge`
- **是否调用工具**：**是**（`ProductAdapter`）
- **是否可能失败**：**是**（商品库缺失）
- **失败兜底**：空列表
- **是否涉及隐私**：否
- **是否可能触发人工审核**：否

---

## 10. match_product_from_message

- **中文职责**：无订单号时，从客户消息中匹配商品名（关键词 + 商品库搜索）。
- **输入字段**：`normalized_message`
- **输出字段**：`matched_product_name`, `product_knowledge`
- **是否调用工具**：**是**（`ProductAdapter.match_product_from_message`）
- **是否可能失败**：**是**（消息中无 recognizable 商品名）
- **失败兜底**：`matched_product_name = ""`
- **是否涉及隐私**：否
- **是否可能触发人工审核**：否

---

## 11. match_shipping_policy

- **中文职责**：匹配物流时效政策（常用快递、发出后预计天数）。
- **输入字段**：`normalized_message`, `matched_product_name`
- **输出字段**：`shipping_policy`
- **是否调用工具**：**是**（`KnowledgeAdapter.match_shipping_policy`，搜索知识库）
- **是否可能失败**：**是**（知识库为空）
- **失败兜底**：空 policy（`default_courier=""`, `eta_days_min/max=None`）
- **是否涉及隐私**：否
- **是否可能触发人工审核**：否

---

## 12. generate_reply

- **中文职责**：生成建议回复。优先尝试 LLM，LLM 不可用时降级到规则引擎。
- **输入字段**：`normalized_message`, `intent`, `risk_level`, `order`, `shipment_status`, `matched_product_name`, `shipping_policy`, `reply_templates`, `sop_scenarios`, `product_knowledge`, `knowledge`
- **输出字段**：`suggested_reply`, `customer_emotion`, `reply_style`, `policy_warnings`, `action_proposal`, `llm_skipped`, `llm_error`
- **是否调用工具**：**是**（`LLMClient.chat`，可选）
- **是否可能失败**：**是**（LLM 超时、JSON 解析失败、Schema 校验失败）
- **失败兜底**：规则引擎生成回复（根据订单状态/商品名/通用模板）
- **是否涉及隐私**：否（生成回复时不输出隐私信息）
- **是否可能触发人工审核**：否（由 risk_check 和 quality_guard 负责）

> **第一阶段约束**：
> - 只回复 `suggested_reply`，不自动发送。
> - 不承诺"一定明天到"、"保证"等确定性表述。
> - LLM key 为空时，规则引擎兜底。

---

## 13. quality_guard

- **中文职责**：检查建议回复是否包含禁止承诺，清洗不安全表述，确保高风险必须人工复核。
- **输入字段**：`suggested_reply`, `risk_level`, `requires_human_review`
- **输出字段**：`suggested_reply`（可能已被清洗）, `guard_warnings`
- **是否调用工具**：复用 `OutputGuard`
- **是否可能失败**：否（纯规则替换）
- **失败兜底**：原样返回
- **是否涉及隐私**：否
- **是否可能触发人工审核**：**是**（若 risk_level=high 但未标记复核，自动补标记）

---

## 14. human_review_gate

- **中文职责**：人工复核门。第一阶段不真正 interrupt 阻塞接口，仅设置标记和原因。
- **输入字段**：`requires_human_review`, `review_reason`
- **输出字段**：`requires_human_review`, `review_reason`
- **是否调用工具**：否
- **是否可能失败**：否
- **失败兜底**：无
- **是否涉及隐私**：否
- **是否可能触发人工审核**：**是**（本节点是人工复核标记的最终确认点）

> **如何修改**：若要真正阻塞并等待人工决策，可在此节点接入 `langgraph.types.interrupt`。当前实现只需改 `app/agent/nodes/human_review_gate.py` 中的返回逻辑。
