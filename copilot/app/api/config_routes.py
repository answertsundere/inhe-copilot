"""System configuration and LLM connectivity APIs."""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

from flask import Blueprint, jsonify, request

from app.api.admin_auth import require_admin

config_bp = Blueprint("config", __name__)


_LLM_ENV_KEYS = {
    "api_key": "COPILOT_LLM_API_KEY",
    "api_base": "COPILOT_LLM_API_BASE",
    "model": "COPILOT_LLM_MODEL",
}


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) > 12:
        return value[:4] + "****" + value[-4:]
    return "****"


def _project_env_path() -> Path:
    override = os.environ.get("COPILOT_ENV_FILE")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / ".env"


def _upsert_env_values(path: Path, updates: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    pending = dict(updates)
    output: list[str] = []

    for line in lines:
        replaced = False
        for key, value in list(pending.items()):
            if re.match(rf"^\s*{re.escape(key)}\s*=", line):
                output.append(f"{key}={value}")
                pending.pop(key)
                replaced = True
                break
        if not replaced:
            output.append(line)

    if pending:
        if output and output[-1].strip():
            output.append("")
        for key, value in pending.items():
            output.append(f"{key}={value}")

    path.write_text("\n".join(output) + "\n", encoding="utf-8")


def _reload_llm_runtime(api_key: str, api_base: str, model: str) -> None:
    os.environ[_LLM_ENV_KEYS["api_key"]] = api_key
    os.environ[_LLM_ENV_KEYS["api_base"]] = api_base
    os.environ[_LLM_ENV_KEYS["model"]] = model

    import app.config as cfg

    cfg.LLM_API_KEY = api_key
    cfg.LLM_API_BASE = api_base
    cfg.LLM_MODEL = model

    try:
        import app.llm.client as llm_client

        llm_client.LLM_API_KEY = api_key
        llm_client.LLM_API_BASE = api_base
        llm_client.LLM_MODEL = model
        llm_client._client = None
    except Exception:
        pass


@config_bp.route("/api/config/llm")
@require_admin
def api_llm_config():
    """Return current LLM configuration without exposing the raw API key."""
    from app.config import LLM_API_BASE, LLM_API_KEY, LLM_MODEL

    key_set = bool(LLM_API_KEY)
    return jsonify({
        "configured": key_set,
        "api_key_masked": _mask_secret(LLM_API_KEY),
        "model": LLM_MODEL if key_set else "(未配置)",
        "api_base": LLM_API_BASE,
        "mode": "AI 模式" if key_set else "零配置模式（规则引擎）",
    })


@config_bp.route("/api/config/llm", methods=["PUT", "POST"])
@require_admin
def api_update_llm_config():
    """Save local LLM settings. The raw API key is never returned."""
    from app.config import LLM_API_BASE, LLM_API_KEY, LLM_MODEL

    data = request.get_json(silent=True) or {}
    api_base = str(data.get("api_base", LLM_API_BASE) or "").strip()
    model = str(data.get("model", LLM_MODEL) or "").strip()
    api_key = str(data.get("api_key", "") or "").strip()
    clear_api_key = bool(data.get("clear_api_key"))

    if not api_base or not re.match(r"^https?://", api_base):
        return jsonify({"error": "API Base 必须是 http:// 或 https:// 开头的地址"}), 400
    if not model:
        return jsonify({"error": "模型名称不能为空"}), 400
    if api_key and len(api_key) < 8:
        return jsonify({"error": "API Key 长度过短，请检查是否粘贴完整"}), 400
    if api_key and re.search(r"\s", api_key):
        return jsonify({"error": "API Key 不能包含空格或换行"}), 400

    next_key = "" if clear_api_key else (api_key or LLM_API_KEY)
    _upsert_env_values(_project_env_path(), {
        _LLM_ENV_KEYS["api_base"]: api_base,
        _LLM_ENV_KEYS["model"]: model,
        _LLM_ENV_KEYS["api_key"]: next_key,
    })
    _reload_llm_runtime(next_key, api_base, model)

    return jsonify({
        "ok": True,
        "configured": bool(next_key),
        "api_key_masked": _mask_secret(next_key),
        "model": model if next_key else "(未配置)",
        "api_base": api_base,
        "message": "LLM 配置已保存",
    })


@config_bp.route("/api/config/llm-test")
@require_admin
def api_llm_test():
    """Test the current LLM connection with a tiny request."""
    from app.config import LLM_API_BASE, LLM_API_KEY, LLM_MODEL
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
        response = client.create_chat_completion(
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
    except Exception as error:
        latency = int((time.time() - t0) * 1000)
        return jsonify({
            "ok": False,
            "mode": "ai_error",
            "message": "LLM 连接失败",
            "error_type": type(error).__name__,
            "latency_ms": latency,
            "model": LLM_MODEL,
            "api_base": LLM_API_BASE,
        }), 502
