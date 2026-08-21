"""
客服 Copilot 配置 - 所有敏感配置从环境变量读取
"""

import os

# ============ 项目根目录 ============
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ============ LLM 配置 (从环境变量读取) ============
LLM_API_BASE = os.environ.get(
    "COPILOT_LLM_API_BASE",
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
)
LLM_API_KEY = os.environ.get("COPILOT_LLM_API_KEY", "")
LLM_MODEL = os.environ.get("COPILOT_LLM_MODEL", "qwen-plus")
COPILOT_LLM_TRANSPORT_THINKING = os.environ.get(
    "COPILOT_LLM_TRANSPORT_THINKING",
    "",
).strip().lower()
COPILOT_LLM_MIN_OUTPUT_TOKENS = int(
    os.environ.get("COPILOT_LLM_MIN_OUTPUT_TOKENS", "0")
)

# The post-graph decision shadow intentionally has independent credentials and
# transport capability.  It must never silently reuse the formal reply model.
COPILOT_DECISION_LLM_PROVIDER = os.environ.get("COPILOT_DECISION_LLM_PROVIDER", "")
COPILOT_DECISION_LLM_API_BASE = os.environ.get("COPILOT_DECISION_LLM_API_BASE", "")
COPILOT_DECISION_LLM_API_KEY = os.environ.get("COPILOT_DECISION_LLM_API_KEY", "")
COPILOT_DECISION_LLM_MODEL = os.environ.get("COPILOT_DECISION_LLM_MODEL", "")
COPILOT_DECISION_LLM_CAPABILITY = os.environ.get("COPILOT_DECISION_LLM_CAPABILITY", "unsupported")
COPILOT_DECISION_LLM_TIMEOUT_SECONDS = int(
    os.environ.get("COPILOT_DECISION_LLM_TIMEOUT_SECONDS", "20")
)
COPILOT_DECISION_LLM_QUALIFIED = os.environ.get(
    "COPILOT_DECISION_LLM_QUALIFIED", "false"
).lower() in ("1", "true", "yes", "on")
COPILOT_DECISION_LLM_DISABLE_THINKING = os.environ.get(
    "COPILOT_DECISION_LLM_DISABLE_THINKING", "false"
).lower() in ("1", "true", "yes", "on")

# Unified Textual Audit has an independent, explicit strict-output role. It
# must never silently inherit the Composer/formal reply model or the decision
# shadow credentials.
COPILOT_UNIFIED_AUDIT_STRICT_ENABLED = os.environ.get(
    "COPILOT_UNIFIED_AUDIT_STRICT_ENABLED", "false"
).lower() in ("1", "true", "yes", "on")
COPILOT_UNIFIED_AUDIT_PROVIDER = os.environ.get(
    "COPILOT_UNIFIED_AUDIT_PROVIDER", ""
)
COPILOT_UNIFIED_AUDIT_API_BASE = os.environ.get(
    "COPILOT_UNIFIED_AUDIT_API_BASE", ""
)
COPILOT_UNIFIED_AUDIT_API_KEY = os.environ.get(
    "COPILOT_UNIFIED_AUDIT_API_KEY", ""
)
COPILOT_UNIFIED_AUDIT_MODEL = os.environ.get(
    "COPILOT_UNIFIED_AUDIT_MODEL", ""
)
COPILOT_UNIFIED_AUDIT_CAPABILITY = os.environ.get(
    "COPILOT_UNIFIED_AUDIT_CAPABILITY", "unsupported"
)
COPILOT_UNIFIED_AUDIT_TIMEOUT_SECONDS = int(
    os.environ.get("COPILOT_UNIFIED_AUDIT_TIMEOUT_SECONDS", "20")
)
COPILOT_UNIFIED_AUDIT_QUALIFIED = os.environ.get(
    "COPILOT_UNIFIED_AUDIT_QUALIFIED", "false"
).lower() in ("1", "true", "yes", "on")
COPILOT_UNIFIED_AUDIT_QUALIFICATION_FINGERPRINT = os.environ.get(
    "COPILOT_UNIFIED_AUDIT_QUALIFICATION_FINGERPRINT", ""
)
COPILOT_UNIFIED_AUDIT_DISABLE_THINKING = os.environ.get(
    "COPILOT_UNIFIED_AUDIT_DISABLE_THINKING", "false"
).lower() in ("1", "true", "yes", "on")

# Turn Understanding may use an independently qualified strict-output role.
# It never inherits formal Agent, decision-shadow, Composer, or Audit settings.
COPILOT_TURN_UNDERSTANDING_STRICT_ENABLED = os.environ.get(
    "COPILOT_TURN_UNDERSTANDING_STRICT_ENABLED", "false"
).lower() in ("1", "true", "yes", "on")
COPILOT_TURN_UNDERSTANDING_PROVIDER = os.environ.get(
    "COPILOT_TURN_UNDERSTANDING_PROVIDER", ""
)
COPILOT_TURN_UNDERSTANDING_API_BASE = os.environ.get(
    "COPILOT_TURN_UNDERSTANDING_API_BASE", ""
)
COPILOT_TURN_UNDERSTANDING_API_KEY = os.environ.get(
    "COPILOT_TURN_UNDERSTANDING_API_KEY", ""
)
COPILOT_TURN_UNDERSTANDING_MODEL = os.environ.get(
    "COPILOT_TURN_UNDERSTANDING_MODEL", ""
)
COPILOT_TURN_UNDERSTANDING_CAPABILITY = os.environ.get(
    "COPILOT_TURN_UNDERSTANDING_CAPABILITY", "unsupported"
)
COPILOT_TURN_UNDERSTANDING_TIMEOUT_SECONDS = int(
    os.environ.get("COPILOT_TURN_UNDERSTANDING_TIMEOUT_SECONDS", "20")
)
COPILOT_TURN_UNDERSTANDING_QUALIFIED = os.environ.get(
    "COPILOT_TURN_UNDERSTANDING_QUALIFIED", "false"
).lower() in ("1", "true", "yes", "on")
COPILOT_TURN_UNDERSTANDING_QUALIFICATION_FINGERPRINT = os.environ.get(
    "COPILOT_TURN_UNDERSTANDING_QUALIFICATION_FINGERPRINT", ""
)
COPILOT_TURN_UNDERSTANDING_DISABLE_THINKING = os.environ.get(
    "COPILOT_TURN_UNDERSTANDING_DISABLE_THINKING", "false"
).lower() in ("1", "true", "yes", "on")

# ============ 客户图片 VLM 配置 ============
COPILOT_VLM_ENABLED = os.environ.get("COPILOT_VLM_ENABLED", "false").lower() in ("1", "true", "yes", "on")
COPILOT_VLM_API_BASE = os.environ.get(
    "COPILOT_VLM_API_BASE",
    os.environ.get("SIDECAR_VISION_BASE_URL", ""),
)
COPILOT_VLM_API_KEY = os.environ.get(
    "COPILOT_VLM_API_KEY",
    os.environ.get("SIDECAR_VISION_API_KEY", ""),
)
COPILOT_VLM_MODEL = os.environ.get(
    "COPILOT_VLM_MODEL",
    os.environ.get("SIDECAR_VISION_MODEL", ""),
)
COPILOT_VLM_TIMEOUT_SECONDS = int(os.environ.get(
    "COPILOT_VLM_TIMEOUT_SECONDS",
    os.environ.get("SIDECAR_VISION_TIMEOUT_SECONDS", "30"),
))

# ============ 数据路径 ============
# 外部真实数据目录（聚水潭导出等），可选
EXTERNAL_DATA_DIR = os.environ.get("COPILOT_EXTERNAL_DATA_DIR", "")
# 内部样例数据目录
SAMPLE_DATA_DIR = os.environ.get(
    "COPILOT_SAMPLE_DATA_DIR",
    os.path.join(BASE_DIR, "data"),
)
# 规则目录
RULES_DIR = os.environ.get(
    "COPILOT_RULES_DIR",
    os.path.join(BASE_DIR, "rules"),
)
# 知识库目录
KNOWLEDGE_DIR = os.environ.get(
    "COPILOT_KNOWLEDGE_DIR",
    os.path.join(BASE_DIR, "knowledge"),
)
# 反馈记录文件
FEEDBACK_FILE = os.environ.get(
    "COPILOT_FEEDBACK_FILE",
    os.path.join(BASE_DIR, "data", "feedback.jsonl"),
)
# 复核队列文件
REVIEW_QUEUE_FILE = os.environ.get(
    "COPILOT_REVIEW_QUEUE_FILE",
    os.path.join(BASE_DIR, "data", "review_queue.jsonl"),
)

# 知识库数据库（SQLite）
KNOWLEDGE_DB_PATH = os.environ.get(
    "COPILOT_KNOWLEDGE_DB_PATH",
    os.path.join(BASE_DIR, "data", "knowledge_base.db"),
)

# 客服训练样本附件上传目录
TRAINING_SAMPLE_UPLOAD_DIR = os.environ.get(
    "COPILOT_TRAINING_SAMPLE_UPLOAD_DIR",
    os.path.join(BASE_DIR, "data", "training_sample_uploads"),
)

# ============ 聚水潭 OpenAPI 配置 (必须通过环境变量设置) ============
# 兼容历史 JUSHUITAN_* 与生产 COPILOT_JST_* 环境变量名
JST_APP_KEY = os.environ.get("JUSHUITAN_APP_KEY") or os.environ.get("COPILOT_JST_APP_KEY", "")
JST_APP_SECRET = os.environ.get("JUSHUITAN_APP_SECRET") or os.environ.get("COPILOT_JST_APP_SECRET", "")
JST_ACCESS_TOKEN = os.environ.get("JUSHUITAN_ACCESS_TOKEN") or os.environ.get("COPILOT_JST_ACCESS_TOKEN", "")
JST_BASE_URL = os.environ.get("JUSHUITAN_BASE_URL") or os.environ.get("COPILOT_JST_BASE_URL", "https://openapi.jushuitan.com/open")

# ============ 钉钉多维表配置 (必须通过环境变量设置) ============
DT_CLIENT_ID = os.environ.get("COPILOT_DT_CLIENT_ID", "")
DT_CLIENT_SECRET = os.environ.get("COPILOT_DT_CLIENT_SECRET", "")
DT_OPERATOR_ID = os.environ.get("COPILOT_DT_OPERATOR_ID", "")
DT_BASE_ID = os.environ.get("COPILOT_DT_BASE_ID", "")

# ============ Web 配置 ============
WEB_HOST = os.environ.get("COPILOT_WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.environ.get("COPILOT_WEB_PORT", "5011"))
WEB_DEBUG = os.environ.get("COPILOT_WEB_DEBUG", "false").lower() == "true"


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


# ============ 货品资料规范库（只读身份参考） ============
COPILOT_PRODUCT_DATA_HUB_ENABLED = _env_bool("COPILOT_PRODUCT_DATA_HUB_ENABLED", False)
COPILOT_PRODUCT_DATA_HUB_BASE_URL = os.environ.get(
    "COPILOT_PRODUCT_DATA_HUB_BASE_URL",
    "http://127.0.0.1:8795",
).strip()
COPILOT_PRODUCT_DATA_HUB_TIMEOUT_SECONDS = float(
    os.environ.get("COPILOT_PRODUCT_DATA_HUB_TIMEOUT_SECONDS", "2")
)


# ============ Grounded Generation 配置 ============
USE_LLM_FOR_EXACT_FAQ = _env_bool("COPILOT_USE_LLM_FOR_EXACT_FAQ", False)
USE_LLM_FOR_PRODUCT_FACTS = _env_bool("COPILOT_USE_LLM_FOR_PRODUCT_FACTS", False)
USE_LLM_FOR_POLICY_REWRITE = _env_bool("COPILOT_USE_LLM_FOR_POLICY_REWRITE", True)
USE_LLM_FOR_SOP_REWRITE = _env_bool("COPILOT_USE_LLM_FOR_SOP_REWRITE", True)
FAQ_EXACT_SCORE_THRESHOLD = float(os.environ.get("COPILOT_FAQ_EXACT_SCORE_THRESHOLD", "0.45"))

# ============ RAG Embedding 配置 ============
EMBEDDING_ENABLED = _env_bool("COPILOT_EMBEDDING_ENABLED", False)
EMBEDDING_SHADOW_MODE = _env_bool("COPILOT_EMBEDDING_SHADOW_MODE", True)
EMBEDDING_MODEL = os.environ.get("COPILOT_EMBEDDING_MODEL", "text-embedding-v3")
EMBEDDING_API_BASE = os.environ.get("COPILOT_EMBEDDING_API_BASE", "")
EMBEDDING_API_KEY = os.environ.get("COPILOT_EMBEDDING_API_KEY", "")
RAG_VECTOR_WEIGHT = float(os.environ.get("COPILOT_RAG_VECTOR_WEIGHT", "0.55"))
RAG_TEXT_WEIGHT = float(os.environ.get("COPILOT_RAG_TEXT_WEIGHT", "0.30"))
RAG_SCOPE_WEIGHT = float(os.environ.get("COPILOT_RAG_SCOPE_WEIGHT", "0.15"))

# ============ Parallel Understanding Phase 2 switches ============
ENABLE_PARALLEL_FUSION_ROUTING = _env_bool("COPILOT_ENABLE_PARALLEL_FUSION_ROUTING", False)
ENABLE_PARALLEL_SAFETY_CONTRACT = _env_bool("COPILOT_ENABLE_PARALLEL_SAFETY_CONTRACT", True)
ENABLE_PARALLEL_IDENTIFIER_ROUTING = _env_bool("COPILOT_ENABLE_PARALLEL_IDENTIFIER_ROUTING", False)
ENABLE_PARALLEL_HIGH_RISK_GATE = _env_bool("COPILOT_ENABLE_PARALLEL_HIGH_RISK_GATE", True)

# ============ Version Constants (环境变量可覆盖) ============
GRAPH_VERSION = os.environ.get("COPILOT_GRAPH_VERSION", "parallel-phase2-v1")
PROMPT_VERSION = os.environ.get("COPILOT_PROMPT_VERSION", "grounded-generation-v1")
ROUTING_CONFIG_VERSION = os.environ.get("COPILOT_ROUTING_VERSION", "routing-v1")
TOOL_REGISTRY_VERSION = os.environ.get("COPILOT_TOOL_REGISTRY_VERSION", "tool-registry-v1")
APP_VERSION = os.environ.get("COPILOT_APP_VERSION", "1.0.0")

# ============ 脱敏配置 ============
MASK_ORDER_IDS = _env_bool("COPILOT_MASK_ORDER_IDS", False)
MASK_TRACKING_NOS = _env_bool("COPILOT_MASK_TRACKING_NOS", False)

# ============ 检索配置 ============
COPILOT_RETRIEVER_BACKEND = os.environ.get("COPILOT_RETRIEVER_BACKEND", "current_sqlite")

# ============ RAG Judge 配置 ============
COPILOT_RAG_LLM_JUDGE_ENABLED = _env_bool("COPILOT_RAG_LLM_JUDGE_ENABLED", False)
COPILOT_FINAL_AUDIT_LLM_ENABLED = _env_bool("COPILOT_FINAL_AUDIT_LLM_ENABLED", True)
COPILOT_FINAL_POLISH_LLM_ENABLED = _env_bool("COPILOT_FINAL_POLISH_LLM_ENABLED", False)
COPILOT_MODEL_FIRST_ANSWER_COMPOSER_ENABLED = _env_bool(
    "COPILOT_MODEL_FIRST_ANSWER_COMPOSER_ENABLED",
    False,
)
COPILOT_COMPOSER_LLM_API_BASE = os.environ.get(
    "COPILOT_COMPOSER_LLM_API_BASE", ""
)
COPILOT_COMPOSER_LLM_API_KEY = os.environ.get(
    "COPILOT_COMPOSER_LLM_API_KEY", ""
)
COPILOT_COMPOSER_LLM_MODEL = os.environ.get(
    "COPILOT_COMPOSER_LLM_MODEL", ""
)
COPILOT_COMPOSER_LLM_TIMEOUT_SECONDS = int(
    os.environ.get("COPILOT_COMPOSER_LLM_TIMEOUT_SECONDS", "30")
)
COPILOT_COMPOSER_LLM_TRANSPORT_THINKING = os.environ.get(
    "COPILOT_COMPOSER_LLM_TRANSPORT_THINKING", ""
).strip().lower()
COPILOT_COMPOSER_LLM_MIN_OUTPUT_TOKENS = int(
    os.environ.get("COPILOT_COMPOSER_LLM_MIN_OUTPUT_TOKENS", "0")
)
COPILOT_COMPOSER_LLM_QUALIFIED = _env_bool(
    "COPILOT_COMPOSER_LLM_QUALIFIED",
    False,
)
COPILOT_COMPOSER_LLM_QUALIFICATION_FINGERPRINT = os.environ.get(
    "COPILOT_COMPOSER_LLM_QUALIFICATION_FINGERPRINT",
    "",
)

# ============ Fact Type 语义分类 ============
COPILOT_FACT_TYPE_LLM_ENABLED = _env_bool("COPILOT_FACT_TYPE_LLM_ENABLED", True)

# ============ Logistics fast path ============
COPILOT_EXPLICIT_LOGISTICS_FAST_PATH_ENABLED = _env_bool(
    "COPILOT_EXPLICIT_LOGISTICS_FAST_PATH_ENABLED",
    True,
)
