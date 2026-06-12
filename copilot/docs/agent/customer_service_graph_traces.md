# customer_service_graph 典型运行轨迹

> 本文档记录 7 个典型场景在 graph 中的完整运行路径，用于非技术人员验收。
> 每个场景包含：输入 → 预期意图 → 节点路径 → context_used → 人工审核标记 → 回复摘要。

---

## 场景 1：有订单号且已发货

| 项目 | 内容 |
|---|---|
| **输入消息** | "我快递大概几天会到？" |
| **order_id** | `202501010001` |
| **预期 intent** | `logistics_eta` |
| **预期节点路径** | `normalize_input → detect_intent → risk_check → build_base_context → route_by_intent → query_jst_order → query_local_order_fallback → check_shipment_status → match_order_products → match_shipping_policy → generate_reply → quality_guard → human_review_gate` |
| **预期 context_used** | `has_order=true`, `has_logistics=true`, `order_status="已发货"`, `order_items=[{name:"北欧实木书桌", sku_name:"...", quantity:1, category:"书桌"}]`, `sources=["local_order", "product_knowledge"]` |
| **预期 need_human_review** | `false` |
| **预期 suggested_reply 摘要** | "亲，您的订单（北欧实木书桌）已由中通快递发货，物流单号：ZT2025052101。您可以到快递公司官网查询最新物流动态。具体送达时间以实际物流更新为准……" |
| **关键约束验证** | ① 回复中包含快递公司、运单号；② 不承诺"一定明天到"；③ context_used 不含手机号/地址/buyer_id。 |

---

## 场景 2：有订单号但未发货

| 项目 | 内容 |
|---|---|
| **输入消息** | "快递大概几天会到？" |
| **order_id** | `202501010003` |
| **预期 intent** | `logistics_eta` |
| **预期节点路径** | `normalize_input → detect_intent → risk_check → build_base_context → route_by_intent → query_jst_order → query_local_order_fallback → check_shipment_status → match_order_products → match_shipping_policy → generate_reply → quality_guard → human_review_gate` |
| **预期 context_used** | `has_order=true`, `has_logistics=false`, `order_status="待发货"`, `order_items=[{name:"多功能置物架", quantity:1}]`, `sources=["local_order", "product_knowledge"]` |
| **预期 need_human_review** | `false` |
| **预期 suggested_reply 摘要** | "亲，您的订单（多功能置物架）正在仓库加紧备货中，尚未发货。我们一般会在付款后48小时内安排发货（工作日）。发出后通常运输时效以实际物流为准。麻烦您提供一下订单号，我可以帮您查询更准确的物流信息哦～" |
| **关键约束验证** | ① 不说"已发货"；② 说明当前尚未发货；③ 只给"通常时效"，不给确定承诺。 |

---

## 场景 3：无订单号但有商品名

| 项目 | 内容 |
|---|---|
| **输入消息** | "这个书架什么时候发货？" |
| **order_id** | `""` |
| **预期 intent** | `logistics_eta` |
| **预期节点路径** | `normalize_input → detect_intent → risk_check → build_base_context → route_by_intent → match_product_from_message → match_shipping_policy → generate_reply → quality_guard → human_review_gate` |
| **预期 context_used** | `has_order=false`, `has_logistics=false`, `product_knowledge_count ≥ 0`, `sources=["product_knowledge"]` 或 `["fallback"]` |
| **预期 need_human_review** | `false` |
| **预期 suggested_reply 摘要** | "亲亲，关于书架的物流情况：我们一般会在付款后48小时内安排发货（工作日）。默认使用中通/韵达快递。发出后通常运输时效为 X-Y 天，具体以实际物流为准。麻烦您提供一下订单号，我可以帮您查询更准确的物流信息哦～" |
| **关键约束验证** | ① 匹配到商品名；② 返回对应物流政策；③ 引导客户提供订单号；④ 不编造物流单号。 |

---

## 场景 4：无订单号且无商品名

| 项目 | 内容 |
|---|---|
| **输入消息** | "我快递大概几天会到？" |
| **order_id** | `""` |
| **预期 intent** | `logistics_eta` |
| **预期节点路径** | `normalize_input → detect_intent → risk_check → build_base_context → route_by_intent → match_product_from_message → match_shipping_policy → generate_reply → quality_guard → human_review_gate` |
| **预期 context_used** | `has_order=false`, `has_logistics=false`, `product_knowledge_count=0`, `sources=["fallback"]` |
| **预期 need_human_review** | `false` |
| **预期 suggested_reply 摘要** | "亲亲，为了帮您准确查询物流信息，麻烦提供一下您的订单号哦～如果您记得购买的商品名称，也可以告诉我，我帮您查看发货时效。" |
| **关键约束验证** | ① 不调用订单 API；② 不编造物流；③ 引导客户提供订单号或商品名。 |

---

## 场景 5：高风险投诉

| 项目 | 内容 |
|---|---|
| **输入消息** | "再不处理我就去12315投诉" |
| **order_id** | `""` |
| **预期 intent** | `complaint`（或 `logistics_eta` 但被风险检测覆盖） |
| **预期节点路径** | `normalize_input → detect_intent → risk_check → build_base_context → route_by_intent → match_product_from_message → match_shipping_policy → generate_reply → quality_guard → human_review_gate` |
| **预期 context_used** | `has_order=false`, `skill_route` 中 intent 为 complaint 或 logistics_eta，`sources=["fallback"]` |
| **预期 need_human_review** | `true` |
| **预期 review_reason** | 检测到高风险关键词或强制复核关键词 |
| **预期 suggested_reply 摘要** | "非常理解您的心情，这个问题我们会高度重视。由于情况比较特殊，我需要将您的问题转交主管进一步核实处理……" |
| **关键约束验证** | ① `requires_human_review=true`；② `risk_level="high"`；③ 回复中无虚假承诺；④ 不编造赔偿/退款。 |

---

## 场景 6：JST 不可用，回退本地订单

| 项目 | 内容 |
|---|---|
| **输入消息** | "订单 202501010001 物流到哪了？" |
| **order_id** | `202501010001` |
| **预期 intent** | `logistics_eta` |
| **预期节点路径** | `normalize_input → detect_intent → risk_check → build_base_context → route_by_intent → query_jst_order → query_local_order_fallback → check_shipment_status → match_order_products → match_shipping_policy → generate_reply → quality_guard → human_review_gate` |
| **trace_steps 关键记录** | ① `query_jst_order` 记录 `"source": "jushuitan", "found": false, "reason": "聚水潭未找到...或未配置"`；② `query_local_order_fallback` 记录 `"source": "local_order", "found": true, "order_status": "已发货"` |
| **预期 context_used** | `has_order=true`, `has_logistics=true`, `data_source=""` 或 `"本地预加载"`, `sources=["local_order", "product_knowledge"]` |
| **预期 need_human_review** | `false` |
| **预期 suggested_reply 摘要** | 同场景 1（已发货），因为本地数据中有该订单。 |
| **关键约束验证** | ① JST 失败后系统不崩溃；② 自动降级到本地订单；③ 返回完整物流信息。 |

---

## 场景 7：LLM key 为空，规则模板兜底

| 项目 | 内容 |
|---|---|
| **输入消息** | "请问这款书桌的尺寸"（或任意物流问题） |
| **order_id** | `""` |
| **预期 intent** | `product_consult` 或 `logistics_eta` |
| **预期节点路径** | 根据意图走对应路径，最终在 `generate_reply` 节点 |
| **generate_reply trace 记录** | `"mode": "rule_engine"`, `"summary": "规则引擎生成"` 或 `"LLM 未配置，规则引擎生成"` |
| **预期 context_used** | 正常填充（知识库命中、商品匹配等） |
| **预期 need_human_review** | `false`（除非风险检测命中） |
| **预期 suggested_reply 摘要** | 根据场景返回规则模板或通用兜底回复，例如："亲亲，为了帮您准确查询物流信息，麻烦提供一下您的订单号哦～" |
| **关键约束验证** | ① `COPILOT_LLM_API_KEY=""` 时 `/api/analyze` 不报 500；② `suggested_reply` 非空；③ `trace_steps` 中记录 `mode="rule_engine"`；④ 不因为 LLM 未配置导致系统不可用。 |

---

## 快速对照表

| 场景 | 订单号 | 发货状态 | 商品名 | 风险 | LLM | 核心路径特点 |
|---|---|---|---|---|---|---|
| 1 有单已发 | ✓ | 已发货 | - | 低 | 任意 | 查订单 → 查物流 → 返回快递/单号 |
| 2 有单未发 | ✓ | 未发货 | - | 低 | 任意 | 查订单 → 说明未发货 → 给通常时效 |
| 3 无单有商品 | ✗ | - | ✓ | 低 | 任意 | 匹配商品 → 给商品物流政策 → 引导订单号 |
| 4 无单无商品 | ✗ | - | ✗ | 低 | 任意 | 直接引导提供订单号/商品名 |
| 5 高风险投诉 | 任意 | 任意 | 任意 | **高** | 任意 | 风险检测标记复核 → 温和回复 → 转主管 |
| 6 JST 降级 | ✓ | 已发货 | - | 低 | 任意 | JST 失败 → 本地成功 → 正常回复 |
| 7 LLM 为空 | 任意 | 任意 | 任意 | 低 | **无** | 规则引擎兜底 → 正常返回 |
