"""
[已废弃] 旧配置文件 - 仅为兼容旧脚本保留。

请勿在此文件中硬编码任何密钥。
请使用以下方式配置：
  1. 环境变量: COPILOT_LLM_API_KEY, COPILOT_LLM_API_BASE, COPILOT_LLM_MODEL
  2. .env 文件: 复制 .env.example 为 .env 并填入真实值
  3. 新架构配置: app/config.py

推荐入口：
  - Web 服务: python run_web.py
  - 命令行:   python run_cli.py
"""

import os
import warnings

warnings.warn(
    "config.py (旧) 已废弃，请使用 app/config.py。"
    "推荐入口: run_web.py / run_cli.py",
    DeprecationWarning,
    stacklevel=2,
)

# ============ LLM 配置 (从环境变量读取) ============
LLM_API_BASE = os.environ.get("COPILOT_LLM_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1")
LLM_API_KEY = os.environ.get("COPILOT_LLM_API_KEY", "")
LLM_MODEL = os.environ.get("COPILOT_LLM_MODEL", "qwen-plus")

# ============ 数据路径 (从环境变量读取) ============
DATA_DIR = os.environ.get("COPILOT_EXTERNAL_DATA_DIR", "")

# ============ 客服规则 (已迁移至 rules/*.yaml) ============
# 以下保留仅为旧脚本兼容，新架构请使用 FilePolicyRepository
FORBIDDEN_CLAIMS = [
    "今天一定发", "明天一定到", "一定免费补发", "一定可以退",
    "绝对没有味道", "百分百安全", "不会坏", "不会塌",
    "保证没问题", "肯定能到", "马上就好", "立刻就发",
]

RISK_KEYWORDS = {
    "high": ["投诉", "差评", "退款", "赔偿", "315", "12315", "工商", "媒体", "曝光", "律师", "起诉"],
    "medium": ["催发货", "催快递", "没收到", "发错了", "少发", "漏发", "破损", "质量问题"],
    "low": ["什么时候发", "几天到", "怎么用", "尺寸", "材质", "颜色", "安装"],
}
