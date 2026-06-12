"""
系统配置与 LLM 连接检测 API
"""

import time
from flask import Blueprint, jsonify

config_bp = Blueprint("config", __name__)


@config_bp.route("/api/config/llm")
def api_llm_config():
    """获取当前 LLM 配置（脱敏）"""
    from app.config import LLM_API_KEY, LLM_MODEL, LLM_API_BASE

    key_set = bool(LLM_API_KEY)
    masked_key = ""
    if key_set:
        # 脱敏：只显示前4位和后4位
        if len(LLM_API_KEY) > 12:
            masked_key = LLM_API_KEY[:4] + "****" + LLM_API_KEY[-4:]
        else:
            masked_key = "****"

    return jsonify({
        "configured": key_set,
        "api_key_masked": masked_key,
        "model": LLM_MODEL if key_set else "(未配置)",
        "api_base": LLM_API_BASE,
        "mode": "AI 模式" if key_set else "零配置模式（规则引擎）",
    })


@config_bp.route("/api/config/llm-test")
def api_llm_test():
    """实际测试 LLM 连接（发送一个简单请求验证 Key 是否有效）"""
    from app.config import LLM_API_KEY, LLM_MODEL, LLM_API_BASE
    from app.llm.client import LLMClient

    if not LLM_API_KEY:
        return jsonify({
            "ok": False,
            "mode": "zero_config",
            "message": "未配置 COPILOT_LLM_API_KEY，当前运行零配置模式（规则引擎）",
            "latency_ms": 0,
            "model": "(未配置)",
        })

    t0 = time.time()
    try:
        client = LLMClient()
        response = client.client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Hi, just testing connectivity. Reply with 'OK' only."},
            ],
            temperature=0,
            max_tokens=10,
        )
        raw = response.choices[0].message.content.strip()
        latency = int((time.time() - t0) * 1000)
        return jsonify({
            "ok": True,
            "mode": "ai",
            "message": "LLM 连接正常",
            "latency_ms": latency,
            "model": LLM_MODEL,
            "api_base": LLM_API_BASE,
            "test_response": raw,
        })
    except Exception as e:
        latency = int((time.time() - t0) * 1000)
        return jsonify({
            "ok": False,
            "mode": "ai_error",
            "message": f"LLM 连接失败: {str(e)}",
            "latency_ms": latency,
            "model": LLM_MODEL,
            "api_base": LLM_API_BASE,
        }), 502
