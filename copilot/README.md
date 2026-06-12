# INHE 客服 Copilot

客服工作台 AI 助手 — 分析客户消息意图、判断风险等级、查询业务上下文、生成建议回复。

> **定位**: 这是客服 Copilot，不是自动回复机器人。AI 生成建议，人工决定是否采纳。

## 快速开始

```bash
cd copilot

# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置环境变量（二选一）
cp .env.example .env
# 编辑 .env，填入 COPILOT_LLM_API_KEY
# 或直接: set COPILOT_LLM_API_KEY=sk-xxx

# 3. 启动 Web 服务（开发）
python run_web.py
# 打开 http://127.0.0.1:5000

# 3b. 启动 Web 服务（生产/内测）
python run_prod.py

# 4. 或启动命令行
python run_cli.py

# 5. 运行测试
python -m pytest tests/ -v
```

## 项目结构

```
copilot/
  app/
    config.py              配置（环境变量读取）
    main.py                Flask 应用工厂 + 服务初始化
    logging_config.py      日志配置
    api/                   API 路由
      analyze_routes.py    POST /api/analyze
      order_routes.py      GET /api/order|sku|product|stats
      feedback_routes.py   POST/GET /api/feedback
      health_routes.py     GET /api/health
      metrics_routes.py   GET /api/metrics
    agent/                 LangGraph Agent 链路
      graph.py             主状态图（策略路由 + Tool Registry）
      state.py             AgentState 定义
      tools/               工具注册中心
        registry.py        ToolRegistry 单例 + 7 个工具注册
        executor.py        tool_planner + tool_executor_node
        schemas.py         工具输入/输出 schema
        base.py            ToolSpec 定义
      nodes/               图节点
        response_strategy_router.py  策略路由 + 工具权限
        evidence_builder.py         分层证据构建
        generate_reply.py           Grounded Generation
        hallucination_guard.py      幻觉守卫
        factual_guard.py            事实守卫
        ...
    services/              业务服务
      reply_service.py     主编排器
      risk_service.py      风险检测
      context_builder.py   上下文组装
      output_guard.py      禁止承诺拦截
      feedback_service.py  反馈记录
      metrics_service.py   请求指标统计
      embedding_service.py Embedding 服务
    llm/                   LLM 调用层
      client.py            OpenAI 兼容客户端
      prompts.py           Prompt 模板
      schemas.py           Pydantic 输出模型
    repositories/          数据仓库
      base.py              仓库接口
      knowledge_chunk_repository.py  知识分片 + 混合检索
      json_order_repository.py
      json_product_repository.py
      file_knowledge_repository.py
      file_policy_repository.py
    models/                数据模型
      knowledge_base.py    知识库 ORM 模型
      reply.py, order.py, product.py, knowledge.py
    integrations/
      jst/                 聚水潭集成
        live_query.py      实时查询
  rules/                   规则文件 (YAML)
    forbidden_claims.yaml  禁止承诺
    risk_keywords.yaml     风险关键词
    reply_policies.yaml    回复策略
  knowledge/               知识库 (Markdown)
    shipping.md, refund.md, product_common.md, complaint.md
  data/                    样例数据 (JSON)
  scripts/                 脚本
    build_knowledge_embeddings.py  构建知识库 embedding
  web/
    templates/index.html   前端页面
  tests/                   测试
  run_web.py               Web 开发入口
  run_prod.py              生产入口 (Waitress)
  run_cli.py               CLI 入口
```

## 架构

```
客户消息
  → normalize → detect_intent → risk_check → slot_extract
  → response_strategy_router（策略路由 + 工具权限）
  → tool_planner → tool_executor_node（Tool Registry 链路）
  → evidence_builder（分层证据）
  → response_strategy_planner
  → generate_reply / generate_logistics_reply（Grounded Generation）
  → hallucination_guard → factual_guard（守卫）
  → build_response → human_review_gate → 输出
```

### Tool Registry 工具列表

| 工具 | 说明 | 适用意图 |
|------|------|----------|
| jst_lookup_order_tool | 聚水潭订单查询 | 物流 |
| jst_lookup_outbound_tool | 聚水潭出库查询 | 物流 |
| jst_lookup_tracking_tool | 聚水潭快递查询 | 物流 |
| rag_search_tool | 知识库检索 | 全部 |
| product_resolver_tool | 商品识别 | 商品咨询 |
| sop_lookup_tool | SOP 查询 | 投诉/高风险 |
| template_select_tool | 话术模板 | 全部 |

### Grounded Generation 策略

| answer_mode | LLM 使用 | 说明 |
|-------------|----------|------|
| exact_faq_answer | 否 | FAQ 精确匹配 |
| product_fact_answer | 否 | 商品事实直接输出 |
| no_evidence_clarification | 否 | 无证据追问 |
| policy_grounded_answer | 是（受限） | 政策润色 |
| sop_human_review_answer | 是（受限） | SOP 回复 |

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/` | Web 工作台 |
| GET  | `/api/health` | 健康检查 |
| GET  | `/api/metrics` | 请求指标 |
| POST | `/api/analyze` | 分析客户消息 |
| GET  | `/api/order/<id>` | 查询订单 |
| GET  | `/api/sku/<id>` | 查询 SKU |
| GET  | `/api/product/<id>` | 查询商品 |
| POST | `/api/feedback` | 提交反馈 |
| GET  | `/api/feedback` | 反馈列表 |
| GET  | `/api/feedback/stats` | 反馈统计 |
| GET  | `/api/stats` | 全局统计 |

## 环境变量

| 变量 | 必需 | 说明 |
|------|------|------|
| `COPILOT_LLM_API_KEY` | 是 | LLM API Key |
| `COPILOT_LLM_API_BASE` | 否 | API 地址（默认通义千问） |
| `COPILOT_LLM_MODEL` | 否 | 模型名（默认 qwen-plus） |
| `JUSHUITAN_APP_KEY` | 否 | 聚水潭 App Key |
| `JUSHUITAN_APP_SECRET` | 否 | 聚水潭 App Secret |
| `JUSHUITAN_ACCESS_TOKEN` | 否 | 聚水潭 Access Token |
| `COPILOT_EXTERNAL_DATA_DIR` | 否 | 外部数据目录（聚水潭导出） |
| `COPILOT_WEB_PORT` | 否 | Web 端口（默认 5000） |
| `COPILOT_LOG_LEVEL` | 否 | 日志级别（默认 INFO） |
| `COPILOT_EMBEDDING_ENABLED` | 否 | 启用 embedding 检索（默认 false） |
| `COPILOT_EMBEDDING_API_BASE` | 否 | Embedding API 地址 |
| `COPILOT_EMBEDDING_API_KEY` | 否 | Embedding API Key |
| `COPILOT_EMBEDDING_MODEL` | 否 | Embedding 模型名（默认 text-embedding-v3） |

## 技术栈

- Python 3.10+, Flask, LangGraph
- OpenAI 兼容接口（通义千问 / DeepSeek / Moonshot）
- SQLAlchemy + SQLite（知识库）
- YAML 规则, Markdown 知识库, JSON 数据
- pytest 测试（555+ tests）

## ⚠️ 安全注意

- **不要把 LLM Key、聚水潭 Key、Access Token 写入代码。** 所有密钥通过环境变量或 `.env` 文件管理。
- **如果密钥曾经进入代码或对话，应立即到对应平台轮换。**
- **`.env` 文件已被 `.gitignore` 排除。** 不要把 `.env` 提交到版本库。
- **不要提交真实业务导出数据。**
- **日志中不输出密钥、手机号、地址等隐私信息。**
- **聚水潭接口只使用只读白名单。**
