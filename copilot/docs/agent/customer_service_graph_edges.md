# customer_service_graph 边条件表

> 本文档说明图中每条边的业务条件，方便非技术人员指导修改路由逻辑。

---

## 边总览

| 序号 | from_node | to_node | 条件类型 |
|:---:|---|---|:---:|
| 1 | __start__ | normalize_input | 无条件 |
| 2 | normalize_input | detect_intent | 无条件 |
| 3 | detect_intent | risk_check | 无条件 |
| 4 | risk_check | build_base_context | 无条件 |
| 5 | build_base_context | route_by_intent | 无条件 |
| 6 | route_by_intent | query_jst_order | **条件** |
| 7 | route_by_intent | match_product_from_message | **条件** |
| 8 | query_jst_order | query_local_order_fallback | 无条件 |
| 9 | query_local_order_fallback | check_shipment_status | 无条件 |
| 10 | check_shipment_status | match_order_products | 无条件 |
| 11 | match_order_products | match_product_from_message | **条件** |
| 12 | match_order_products | match_shipping_policy | **条件** |
| 13 | match_product_from_message | match_shipping_policy | 无条件 |
| 14 | match_shipping_policy | generate_reply | 无条件 |
| 15 | generate_reply | quality_guard | 无条件 |
| 16 | quality_guard | human_review_gate | 无条件 |
| 17 | human_review_gate | __end__ | 无条件 |

---

## 详细说明

### 边 6：route_by_intent → query_jst_order

| 属性 | 值 |
|---|---|
| **condition** | `intent ∈ {logistics_eta, shipping, logistics} AND has_order_id=true` |
| **中文解释** | 客户意图是物流/到货时间，并且提供了订单号，才走聚水潭实时查询链路。 |
| **对应测试用例** | `test_agent_graph::TestShippedOrder::test_shipped_order_has_logistics`<br/>`test_agent_graph::TestPendingOrder::test_pending_order_not_shipped` |
| **是否高风险路径** | 否 |
| **如何修改** | 编辑 `app/agent/nodes/route_by_intent.py` 中的 `should_query_order()` 函数。 |

> **示例**：若下一阶段需要支持"退款查询也走订单链路"，可将 `intent == "refund"` 加入条件。

---

### 边 7：route_by_intent → match_product_from_message

| 属性 | 值 |
|---|---|
| **condition** | `intent ∉ {logistics_eta, shipping, logistics} OR has_order_id=false` |
| **中文解释** | 客户意图不是物流，或者没有提供订单号，跳过聚水潭和本地订单查询，直接从消息匹配商品。 |
| **对应测试用例** | `test_agent_graph::TestNoOrderWithProduct::test_product_match`<br/>`test_agent_graph::TestNoOrderNoProduct::test_no_order_api_called` |
| **是否高风险路径** | 否 |
| **如何修改** | 同上，编辑 `should_query_order()` 函数。 |

---

### 边 8：query_jst_order → query_local_order_fallback

| 属性 | 值 |
|---|---|
| **condition** | 无条件（顺序执行） |
| **中文解释** | 无论聚水潭查询成功还是失败，都进入本地订单降级查询节点。本地节点内部会判断：如果 JST 已查到则跳过。 |
| **对应测试用例** | `test_agent_graph::TestShippedOrder::test_trace_has_order_lookup` |
| **是否高风险路径** | 否 |
| **如何修改** | 若不需要聚水潭而直接查本地，可删除 `query_jst_order` 节点，将 `route_by_intent` 直接连到 `query_local_order_fallback`。 |

---

### 边 9：query_local_order_fallback → check_shipment_status

| 属性 | 值 |
|---|---|
| **condition** | 无条件（顺序执行） |
| **中文解释** | 本地订单查询完成后（查到或未查到），统一进入发货状态检查。 |
| **对应测试用例** | `test_agent_graph::TestPendingOrder::test_pending_order_not_shipped` |
| **是否高风险路径** | 否 |

---

### 边 10：check_shipment_status → match_order_products

| 属性 | 值 |
|---|---|
| **condition** | 无条件（顺序执行） |
| **中文解释** | 发货状态检查完成后，进入订单商品匹配。若订单为空，该节点会标记跳过并在 trace 中记录。 |
| **对应测试用例** | `test_agent_graph::TestShippedOrder::test_shipped_order_has_logistics` |
| **是否高风险路径** | 否 |

---

### 边 11：match_order_products → match_product_from_message

| 属性 | 值 |
|---|---|
| **condition** | `should_match_product() == "match_product"` → 无订单 或 订单无商品明细 |
| **中文解释** | 如果订单不存在或订单中没有商品信息，需要从客户消息中匹配商品名。 |
| **对应测试用例** | `test_agent_graph::TestNoOrderWithProduct::test_product_match`<br/>`test_agent_graph::TestNoOrderNoProduct::test_guide_user` |
| **是否高风险路径** | 否 |
| **如何修改** | 编辑 `app/agent/nodes/route_by_intent.py` 中的 `should_match_product()` 函数。 |

---

### 边 12：match_order_products → match_shipping_policy

| 属性 | 值 |
|---|---|
| **condition** | `should_match_product() == "skip_product"` → 已匹配到订单商品 |
| **中文解释** | 订单中有商品，直接跳过"消息匹配商品"，进入物流政策匹配。 |
| **对应测试用例** | `test_agent_graph::TestShippedOrder::test_shipped_order_has_logistics`<br/>`test_agent_graph::TestPendingOrder::test_pending_has_product_fallback` |
| **是否高风险路径** | 否 |
| **如何修改** | 同上，编辑 `should_match_product()` 函数。 |

---

### 边 13：match_product_from_message → match_shipping_policy

| 属性 | 值 |
|---|---|
| **condition** | 无条件（顺序执行） |
| **中文解释** | 无论是否从消息中匹配到商品，都进入物流政策匹配（匹配不到时返回通用政策）。 |
| **对应测试用例** | `test_agent_graph::TestNoOrderWithProduct::test_product_reply_has_policy` |
| **是否高风险路径** | 否 |

---

### 边 14：match_shipping_policy → generate_reply

| 属性 | 值 |
|---|---|
| **condition** | 无条件（顺序执行） |
| **中文解释** | 物流政策匹配完成后，进入回复生成。这是所有路径的统一收口节点之一。 |
| **对应测试用例** | 所有回复生成相关测试 |
| **是否高风险路径** | 否 |

---

### 边 15：generate_reply → quality_guard

| 属性 | 值 |
|---|---|
| **condition** | 无条件（顺序执行） |
| **中文解释** | 回复生成后必须经过质量守卫检查。 |
| **对应测试用例** | `test_agent_graph::TestTraceSteps::test_has_key_nodes` |
| **是否高风险路径** | 是（守卫节点可能拦截不安全回复） |

---

### 边 16：quality_guard → human_review_gate

| 属性 | 值 |
|---|---|
| **condition** | 无条件（顺序执行） |
| **中文解释** | 守卫通过后进入人工复核门。即使守卫通过，若风险等级为 high，仍会被标记需要人工复核。 |
| **对应测试用例** | `test_agent_graph::TestHighRisk::test_complaint_needs_review` |
| **是否高风险路径** | **是**（最终确认人工复核标记） |

---

## 修改边的操作指南

### 场景 A：新增一种意图（例如 "refund" 也查订单）

1. 打开 `app/agent/nodes/route_by_intent.py`
2. 修改 `should_query_order()`：
   ```python
   if intent in ("logistics_eta", "shipping", "logistics", "refund") and order_id:
       return "query_order"
   ```
3. 同步修改 `docs/agent/customer_service_graph_edges.md` 中边 6 的条件说明。
4. 重新运行 `python scripts/export_customer_service_graph.py` 更新流程图。

### 场景 B：在 JST 失败后不再查本地，直接返回兜底回复

1. 打开 `app/agent/graph.py`
2. 将 `builder.add_edge("query_jst_order", "query_local_order_fallback")` 删除。
3. 添加条件边：`query_jst_order` → `check_shipment_status`（成功）或 `generate_reply`（失败）。
4. 修改 `docs/agent/customer_service_graph_edges.md` 和 `.mmd`。

### 场景 C：在 generate_reply 和 quality_guard 之间增加一个新节点

1. 在 `app/agent/nodes/` 新建 `my_new_node.py`，实现 `def my_new_node(state: dict) -> dict:`。
2. 在 `app/agent/graph.py` 中：
   ```python
   builder.add_node("my_new_node", my_new_node)
   builder.add_edge("generate_reply", "my_new_node")
   builder.add_edge("my_new_node", "quality_guard")
   ```
3. 重新运行导出脚本更新文档。
