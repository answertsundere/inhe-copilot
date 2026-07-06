# Embedding / RAG 本地配置说明

本项目后端由 `run_prod.py` 启动时读取项目根目录的 `.env` 文件。`start_server_5011.bat` 会启动 `run_prod.py`，所以 5011 服务要启用 embedding，必须先把配置写入本机未跟踪的 `.env`，然后重启 5011。

## 必填配置

复制 `.env.example` 为 `.env`，只在本机填写真实值：

```dotenv
COPILOT_EMBEDDING_ENABLED=true
COPILOT_EMBEDDING_API_BASE=<your_embedding_api_base>
COPILOT_EMBEDDING_API_KEY=<your_embedding_api_key>
COPILOT_EMBEDDING_MODEL=<your_embedding_model>
```

不要把真实 API Key 写入 `.env.example`、启动脚本、测试文件、日志、JSON 或 Excel。`.env`、`.env.local`、`.env.*.local` 已加入 `.gitignore`。

## 配置后验证

1. 重启 5011 后端。
2. 检查服务：

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:5011/ask/api/health"
Invoke-RestMethod -Uri "http://127.0.0.1:5011/api/eval/embedding-status" -Headers @{ "X-User-Role" = "supervisor" }
```

期望 `embedding_enabled=true`，同时 `api_base_configured=true`、`api_key_configured=true`。接口只应显示是否配置，不应返回 API Key 明文。

## 构建知识向量

配置通过后先跑预检：

```powershell
python scripts\build_knowledge_embeddings.py --preflight
```

预检成功后再构建已发布知识的 embedding：

```powershell
python scripts\build_knowledge_embeddings.py --published-only --resume
```

## 回放验证

配置和向量构建完成后，再跑诊断和小样本 replay：

```powershell
python scripts\diagnose_embedding_and_rag_readiness.py --latest --json-output outputs\embedding_status_after_config.json --excel-output "C:\Users\sshuser\Desktop\Embedding配置后诊断.xlsx"

python scripts\diagnose_evidence_chain_for_replay.py --latest --json-output outputs\evidence_chain_after_embedding_config.json --excel-output "C:\Users\sshuser\Desktop\Evidence链路诊断_after_embedding_config.xlsx"
```

如果 embedding 已启用但 `selected_evidence_count` 仍然全为 0，不要改 Agent 话术。下一步应检查：embedding index 是否为空、KB chunks 是否已有 embedding、检索是否走向量 rerank、product scope / fact_type filter 是否过严、final gate 是否过滤掉已选证据。
