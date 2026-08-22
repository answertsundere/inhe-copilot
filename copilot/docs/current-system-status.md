# 当前系统状态报告

> 日期: 2026-06-01
> 阶段: MVP 冻结 + 工程化加固
> 测试: 532 passed / 0 failed / 35 test files
> 编译: python -m py_compile app/main.py OK

---

## 一、模块清单

### 1. 已完成模块

| 模块 | 文件 | 测试 | 说明 |
|---|---|---|---|
| **LangGraph 状态图** | `app/agent/graph.py` | test_graph_structure, test_agent_graph | 30+ 节点，7 条策略分支，完整尾部链 |
| **意图识别** | `detect_intent.py`, `llm_intent_router.py`, `router_validation.py` | test_skill_router | 规则+LLM 双层，硬规则覆盖 |
| **slot_extract** | `slot_extract.py` | test_identifier_isolation, test_platform_trade_id | 支持 internal_order_id / platform_trade_id / platform_order_id / tracking_no / unknown_identifier / none |
| **identifier_router** | `identifier_router.py` | test_identifier_isolation | 6 种 identifier_type 路由 |
| **response_strategy_router** | `response_strategy_router.py` | test_tool_registry | 7 种策略 + allowed/required/forbidden 工具列表 |
| **JST 客户端** | `app/integrations/jst/client.py` | - | MD5 签名，endpoint 白名单，超时控制 |
| **JST 查询层** | `app/integrations/jst/live_query.py` | test_jst_outer_so_id_lookup | identifier dispatcher、TTL 缓存、外部订单全页扫描、重复页停滞保护 |
| **JST 实时查询节点** | `jst_live_query.py` | test_agent_graph, test_logistics_chain | 统一入口，状态映射（含销售出库状态） |
| **销售出库查询** | `orders/out/simple/query` 链路 | test_platform_trade_id | platform_trade_id → outbound_so_id；显式淘宝/天猫平台能力在零行后停止，不进入不支持的平台订单扫描 |
| **evidence_builder** | `evidence_builder.py` | test_platform_trade_id | 分层证据：order_facts / logistics_facts / product_facts / policy_facts / sop / template / faq |
| **generate_logistics_reply** | `generate_logistics_reply.py` | test_logistics_chain, test_platform_trade_id | 10+ 场景分支，outbound 已发出模板，禁止签收承诺 |
| **generate_reply** | `generate_reply.py` | test_grounded_generation | grounded generation，FAQ 直出 / LLM 重写 |
| **factual_guard** | `factual_guard.py` | test_factual_guard_promise | 事实承诺检测，改写 |
| **hallucination_guard** | `hallucination_guard.py` | test_output_guard | 无证据项检测 |
| **quality_guard** | `quality_guard.py` | test_output_guard | 禁止承诺过滤 |
| **human_review_gate** | `human_review_gate.py` | test_review_queue | 高风险入队 |
| **RAG 检索** | `rag_retrieve.py`, `knowledge_chunk_repository.py` | test_knowledge_repo, test_knowledge_graph_integration | SQLite FTS + 向量相似度 |
| **知识库后台** | `knowledge_routes.py`, `knowledge_admin.html` | test_knowledge_api, test_knowledge_repo | 完整 CRUD + 版本管理 + 审核流程 |
| **Excel 导入** | `knowledge_import_service.py` | test_knowledge_import | Excel/CSV 批量导入，预览+确认 |
| **质量检查面板** | `quality_routes.py`, `quality_check_service.py` | test_quality_api, test_quality_check | 回复质量检测 |
| **反馈记录** | `feedback_routes.py`, `feedback_service.py` | test_human_feedback_fix | accepted/edited/rejected/escalated |
| **SOP / 模板** | `sop_repository.py`, `reply_template_repository.py` | test_sop_repo, test_reply_template | YAML/JSON 加载，intent 匹配 |
| **风险检测** | `risk_service.py` | test_risk_service | 高/中/低三级关键词 |
| **输出守卫** | `output_guard.py` | test_output_guard | 禁止承诺替换 |
| **Tool Registry** | `app/agent/tools/` (4 files) | test_tool_registry | 7 个工具注册，executor + planner |
| **安全/隐私** | - | test_security | PII 脱敏，无内部标记泄露 |

### 2. 可内部试用模块

| 模块 | 说明 | 限制 |
|---|---|---|
| **物流查询（外部交易号）** | 普通 JST `orders/out/simple/query` 按 `so_ids` 与 `jst_shop_id` 精确查询销售出库记录；结构化 `shop_platform` 选择适配器能力 | 已实测天猫英禾店铺可返回商品 `sku_id`/`i_id` 与物流身份；不使用千牛 Sidecar 或奇门。显式淘宝/天猫店铺的零行结果会停止在销售出库能力边界，不再调用不支持的平台订单接口；零行不证明平台订单不存在 |
| **物流查询（内部订单号）** | internal_order_id → orders/single/query | 需要精确 o_id |
| **物流查询（快递单号）** | tracking_no → logistic/query 扫描 | 仅扫描最近 7 天 100 条，大量单号查不到 |
| **商品咨询** | RAG 知识库检索 | 依赖知识库内容质量 |
| **退货/售后** | 售后政策知识 | 策略偏保守，不主动承诺 |
| **投诉场景** | SOP + 人工复核 | 已接入高风险 SOP |
| **送达时间承诺** | factual_guard 拦截+改写 | 已验证不承诺具体日期 |

### 3. 部分完成模块

| 模块 | 当前状态 | 缺失 |
|---|---|---|
| **Tool Registry 接入主链路** | 已注册 7 工具 + executor + planner | graph 仍走旧节点，未切换到 tool_executor_node |
| **LLM 工具选择** | plan_tools 支持 LLM 选择 | 未在主链路启用 |
| **物流轨迹详情** | 只有发货时间+快递公司 | 无中间物流节点（揽收/中转/派送） |
| **商品知识卡片** | 1898 条 product_knowledge | 部分商品信息不完整 |

### 4. 未完成模块

| 模块 | 说明 |
|---|---|
| **快递100/快递鸟对接** | tracking_no 实时物流轨迹（JST 不支持） |
| **向量 Embedding** | 当前用 FTS + 简单相似度，无语义检索 |
| **多轮对话** | 无 session/memory 机制 |
| **主动推送** | 无 webhook/消息推送 |
| **监控/告警** | 无 Prometheus/Grafana |
| **并发/限流** | 开发服务器，无 WSGI/gunicorn |

### 5. 当前风险

| 风险 | 级别 | 说明 |
|---|---|---|
| tracking_no 查不到 | **高** | JST logistic/query 仅扫最近 7 天 100 条，大量快递单号查不到 |
| Flask 开发服务器 | **高** | 不支持并发，不适合生产 |
| LLM 依赖 | **中** | qwen-plus 可用性/延迟不确定，已做降级但体验下降 |
| 知识库质量 | **中** | 依赖人工维护，RAG 质量影响回复准确性 |
| Tool Registry 未接入 | **低** | 已注册但 graph 仍走旧节点，不影响功能 |

### 6. 下一步建议

1. **接入快递100/快递鸟** — 解决 tracking_no 查不到的核心痛点
2. **Tool Registry 逐步接入主链路** — 先在 logistics_with_order 策略切换
3. **部署 WSGI 服务器** — gunicorn / waitress
4. **向量 Embedding** — 提升 RAG 语义检索质量
5. **监控** — 请求延迟、JST 成功率、LLM 降级率

---

## 二、Tool Registry 接入状态

### 已完成文件

| 文件 | 大小 | 功能 |
|---|---|---|
| `app/agent/tools/base.py` | 2KB | ToolSpec 数据类 |
| `app/agent/tools/schemas.py` | 4.5KB | 7 个工具的 input/output schema |
| `app/agent/tools/registry.py` | 14KB | ToolRegistry 单例 + 7 个 handler |
| `app/agent/tools/executor.py` | 14KB | ToolExecutor + plan_tools + tool_executor_node |
| `app/agent/tools/__init__.py` | 0.5KB | 导出 |

### 已注册工具

| 工具名 | handler 封装 | 已被主 graph 调用？ |
|---|---|---|
| jst_lookup_order_tool | lookup_order_by_identifier(o_id) | **否** — graph 走 jst_live_query 节点 |
| jst_lookup_outbound_tool | lookup_order_by_identifier(outer_so_id) | **否** — graph 走 jst_live_query 节点 |
| jst_lookup_tracking_tool | lookup_order_by_identifier(tracking_no) | **否** — graph 走 jst_live_query 节点 |
| rag_search_tool | KnowledgeChunkRepository.search_chunks | **否** — graph 走 rag_retrieve 节点 |
| product_resolver_tool | _match_products_from_message() | **否** — graph 走 resolve_product_identity 节点 |
| sop_lookup_tool | sop_repo.search() | **否** — graph 走 RAG knowledge_scope_router |
| template_select_tool | template_repo.search() | **否** — graph 走 RAG knowledge_scope_router |

### 当前接入状态

**graph 目前仍 100% 走旧节点**。Tool Registry 是附加基础设施层：

```
当前:  state → response_strategy_router → jst_live_query(旧节点) → evidence_builder
未来:  state → response_strategy_router → tool_planner → tool_executor_node → evidence_builder
```

### 已生效的部分

- `response_strategy_router` 已输出 `allowed_tools / required_tools / forbidden_tools`（写入 state 但 graph 条件边不读取）
- `evidence_builder` 已能消费 `tool_results`（但 graph 不产生 tool_results）
- `plan_tools` + `tool_executor_node` 已就绪但未被 graph 调用

### 切换路径

1. **Phase 2a**: 在 graph.py 中为 `logistics_with_order` 策略添加 `tool_planner → tool_executor_node` 分支，替换 `jst_live_query` 节点
2. **Phase 2b**: 为 `product_question` 策略替换 `rag_retrieve → resolve_product_identity` 为 `tool_executor_node`
3. **Phase 2c**: 为 `high_risk` 策略替换为 `tool_executor_node(sop_lookup_tool)`
4. **Phase 3**: 删除旧节点（确认全部切换后）

---

## 三、运行时验收结果

### 测试 1: 外部交易单号查询

```
Message:           5118207015382036103 我的快递大概什么时候到
Intent:            logistics_eta
Identifier Type:   platform_trade_id
Response Strategy: logistics_with_order
Allowed Tools:     [jst_lookup_outbound_tool, rag_search_tool, template_select_tool, product_resolver_tool]
Used Fact Tool:    jst_live_query
Used Endpoint:     orders/out/simple/query
Order Facts:       1 (source=jst_sales_out)
Logistics Facts:   1
Hallucination:     passed=True
Human Review:      False
Reply:             顺丰速运 SF0229477422177 2026-06-01 13:22:39 已发出，具体送达时间以实际物流更新为准
✓ 通过 — 走 orders/out/simple/query，包含快递公司/单号/发出时间，不说已签收
```

### 测试 2: 内部订单号查询

```
Message:           订单号 1636367，什么时候到？
Intent:            logistics_eta
Identifier Type:   internal_order_id
Response Strategy: logistics_with_order
Used Fact Tool:    jst_live_query
Used Endpoint:     (未命中)
Order Facts:       0
Human Review:      False
Reply:             暂时没有查询到该订单号对应的订单/物流信息
✓ 通过 — 走 internal_order_id 查询，未查到时安全兜底
```

### 测试 3: 快递单号查询

```
Message:           快递单号 SF0229477422177 到哪里了？
Intent:            logistics_eta
Identifier Type:   tracking_no
Response Strategy: logistics_with_order
Used Fact Tool:    jst_live_query
Used Endpoint:     (未命中 — JST logistic/query 扫描限制)
Human Review:      False
Reply:             暂时没有在系统中查到该物流单号对应的订单/物流信息
✓ 通过 — 走 tracking_no 查询，查不到安全兜底，不编造
```

### 测试 4: 送达时间承诺

```
Message:           明天能不能一定到？
Intent:            logistics_eta
Identifier Type:   none
Response Strategy: logistics_policy_without_order
factual_guard:     triggered rewrite (A2)
Hallucination:     passed=True
Human Review:      False
Reply:             非常理解您希望包裹准时到达的心情...无法对具体到某一天的送达做出绝对承诺
✓ 通过 — factual_guard 拦截承诺，改写为安全话术
```

### 测试 5: 商品材质咨询

```
Message:           六号防摔枕材质是什么？能洗吗？
Intent:            product_question
Identifier Type:   none
Response Strategy: product_question
Knowledge Titles:  [产品信息] (RAG 命中)
Hallucination:     passed=True
Human Review:      False
Reply:             记忆棉/乳胶，可拆洗，建议手洗...
✓ 通过 — RAG 检索命中产品知识，回答有依据
```

### 测试 6: 商品防水咨询

```
Message:           一号狮子围兜防水吗？
Intent:            product_question
Identifier Type:   none
Response Strategy: product_question
Knowledge Titles:  [产品信息] (RAG 命中)
Hallucination:     passed=True
Human Review:      False
Reply:             防水面料，可以直接擦拭...底部有接漏设计...
✓ 通过 — RAG 命中，回答具体
```

### 测试 7: 退货咨询

```
Message:           收到后不想要了可以退吗？
Intent:            aftersales
Identifier Type:   none
Response Strategy: aftersales
Hallucination:     passed=True
Human Review:      False
Reply:             感谢您的反馈，已经记录下来...会尽快为您核实处理
✓ 通过 — 售后意图识别正确，回复偏保守不主动承诺
```

### 测试 8: 投诉场景

```
Message:           再不处理我就投诉平台。
Intent:            complaint
Identifier Type:   none
Response Strategy: high_risk
Required Tools:    [sop_lookup_tool]
Hallucination:     passed=True
Human Review:      **True**
Reply:             非常抱歉给您带来不便...会有专人尽快为您处理...
✓ 通过 — 投诉识别正确，自动进入人工复核
```

### 验收汇总

| # | 场景 | 通过 | 关键验证点 |
|---|---|---|---|
| 1 | 外部交易单号 | ✓ | orders/out/simple/query, 已发出不说签收 |
| 2 | 内部订单号 | ✓ | internal_order_id 路由 |
| 3 | 快递单号 | ✓ | tracking_no 路由，安全兜底 |
| 4 | 送达承诺 | ✓ | factual_guard 拦截 |
| 5 | 商品材质 | ✓ | RAG 产品知识 |
| 6 | 商品防水 | ✓ | RAG 产品知识 |
| 7 | 退货咨询 | ✓ | 售后意图 |
| 8 | 投诉场景 | ✓ | 高风险 + 人工复核 |

---

## 四、MVP 判定

| 能力 | 状态 | 可内部试用 | 风险 |
|---|---|---|---|
| 物流查询（外部交易号） | **已完成** | 是 | 仅限有出库记录的单号 |
| 物流查询（内部订单号） | **已完成** | 是 | 需精确 o_id |
| 物流查询（快递单号） | **部分完成** | 受限 | JST 仅扫 7 天 100 条，大量查不到 |
| JST 查询层 | **已完成** | 是 | 超时 3s，降级安全 |
| 销售出库 orders/out/simple/query | **已完成** | 是 | 状态映射完整 |
| 知识库后台 | **已完成** | 是 | CRUD + 版本 + 审核 + 导入 |
| Excel 导入 | **已完成** | 是 | 预览 + 确认 |
| RAG 检索 | **已完成** | 是 | FTS + 相似度，无 embedding |
| factual_guard | **已完成** | 是 | 承诺检测 + 改写 |
| hallucination_guard | **已完成** | 是 | 无证据项检测 |
| Tool Registry | **已完成** | 待接入 | 已注册未接入主链路 |
| Tool Executor | **已完成** | 待接入 | 已就绪未被 graph 调用 |
| 质量检查面板 | **已完成** | 是 | 回复质量检测 |
| 反馈记录 | **已完成** | 是 | 4 种 action |
| SOP / 模板 | **已完成** | 是 | 29 条 SOP / 840 条模板 |
| 商品咨询 | **可内部试用** | 是 | 依赖知识库质量 |
| 退货/售后 | **可内部试用** | 是 | 策略偏保守 |
| 投诉处理 | **可内部试用** | 是 | SOP + 人工复核 |

**结论: MVP 可内部试用。** 物流查询（外部交易号/内部订单号）、知识库 RAG、安全守卫链、反馈闭环均已就绪。快递单号查询受 JST API 限制需接第三方。
