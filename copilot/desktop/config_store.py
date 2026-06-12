"""
Config store — JSON 配置读写
存储路径: ~/.inhe-copilot/config.json
"""

import json
import os
import base64

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".inhe-copilot")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

DEFAULT_CONFIG = {
    "server_base_url": "http://127.0.0.1:5000",
    "api_token": "",
    "request_timeout": 30,
    "auto_start_sidecar": True,
    "monitor_qianniu": True,
    "always_on_top": True,
    "poll_interval": 10,
    "stable_reads": 1,
    "window_keywords": ["千牛", "qianniu", "卖家中心"],
    "enable_uia": True,
    "enable_vision": False,
    "enable_clipboard": True,
    "vlm_provider": "mock",
    "vlm_base_url": "",
    "vlm_api_key": "",
    "vlm_model": "",
    "vlm_timeout_seconds": 10,
    "vlm_min_confidence": 0.5,
    "vlm_require_confirm": True,
    "vlm_save_screenshot_debug": False,
    "forbid_auto_send": True,
    "high_risk_force_human_review": True,
    "unverified_knowledge_blocked": True,
    "log_level": "INFO",
    "save_screenshot_debug": False,
}


def _encode_key(key: str) -> str:
    if not key:
        return ""
    return base64.b64encode(key.encode()).decode()


def _decode_key(encoded: str) -> str:
    if not encoded:
        return ""
    try:
        return base64.b64decode(encoded.encode()).decode()
    except Exception:
        return ""


def load_config() -> dict:
    """加载配置，缺失字段用默认值补全"""
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8-sig") as f:
                saved = json.load(f)
            cfg.update(saved)
        except Exception:
            pass
    return cfg


def save_config(cfg: dict) -> dict:
    """保存配置，缺失字段补默认值，敏感字段未提交时保留旧值。"""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    current = load_config()
    merged = dict(DEFAULT_CONFIG)
    merged.update(current)
    for key, value in (cfg or {}).items():
        if key in ("vlm_api_key", "api_token") and value in (None, "", "undefined"):
            continue
        merged[key] = value
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    return {"ok": True}


def get_safe_config() -> dict:
    """返回配置副本，API Key 脱敏，原始密钥移除"""
    cfg = load_config()
    if cfg.get("vlm_api_key"):
        cfg["vlm_api_key_masked"] = cfg["vlm_api_key"][:4] + "****"
    else:
        cfg["vlm_api_key_masked"] = ""
    cfg.pop("vlm_api_key", None)
    if cfg.get("api_token"):
        cfg["api_token_masked"] = cfg["api_token"][:4] + "****"
    else:
        cfg["api_token_masked"] = ""
    cfg.pop("api_token", None)
    return cfg


def get_config_dir() -> str:
    return CONFIG_DIR
