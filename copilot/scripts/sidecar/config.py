from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

VALID_VISION_PROVIDERS = (
    "mock",
    "external_openai_compatible",
    "local_openai_compatible",
    "dashscope",
    "mimo",
    "custom",
)


@dataclass
class SidecarConfig:
    # Window watcher
    window_title_priority: list[str] = field(default_factory=lambda: [
        "接待中心", "旺旺", "接待台", "聊天", "千牛工作台", "千牛",
    ])
    window_find_keywords: list[str] = field(default_factory=lambda: [
        "千牛", "旺旺", "阿里旺旺", "接待台", "接待中心",
    ])

    # UIA sidebar
    uia_max_items: int = 600
    uia_max_text_length: int = 500

    # Chat region ratios (relative to window client area)
    chat_region: dict[str, float] = field(default_factory=lambda: {
        "left_ratio": 0.18,
        "top_ratio": 0.08,
        "right_ratio": 0.72,
        "bottom_ratio": 0.88,
    })

    # Vision / VLM
    enable_vision_extractor: bool = True
    vision_provider: str = "external_openai_compatible"
    vision_base_url: str = ""
    vision_api_key: str = ""
    vision_model: str = "mimo-v2.5"
    vision_timeout_seconds: int = 30
    vision_min_confidence: float = 0.85
    vision_auto_submit: bool = False
    vision_require_confirm: bool = True
    save_screenshot_debug: bool = False

    # Eval logging
    vision_eval_log: str = ""

    # Copilot backend
    backend_url: str = "http://127.0.0.1:5011"
    panel_url: str = "http://127.0.0.1:5011/copilot-panel"
    request_timeout: float = 10.0

    # Polling
    poll_interval: float = 2.0

    # Safety
    auto_send: bool = False
    auto_click: bool = False
    auto_type: bool = False

    # Logging
    log_file: str = ""

    def resolve_vision_base_url(self) -> str:
        if self.vision_base_url:
            return self.vision_base_url
        if self.vision_provider == "external_openai_compatible":
            return os.getenv("SIDECAR_VISION_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1")
        if self.vision_provider == "local_openai_compatible":
            return os.getenv("SIDECAR_LOCAL_VISION_BASE_URL", "http://127.0.0.1:8000/v1")
        if self.vision_provider == "mimo":
            return os.getenv("SIDECAR_VISION_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1")
        if self.vision_provider in ("dashscope", "custom"):
            return os.getenv("SIDECAR_VISION_BASE_URL", self.vision_base_url)
        return ""

    def resolve_vision_api_key(self) -> str:
        if self.vision_api_key:
            return self.vision_api_key
        if self.vision_provider == "external_openai_compatible":
            return os.getenv("SIDECAR_VISION_API_KEY", "")
        if self.vision_provider == "local_openai_compatible":
            return os.getenv("SIDECAR_LOCAL_VISION_API_KEY", "local")
        if self.vision_provider in ("dashscope", "mimo", "custom"):
            return os.getenv("SIDECAR_VISION_API_KEY", self.vision_api_key)
        return ""


def load_config_from_env() -> SidecarConfig:
    cfg = SidecarConfig()
    cfg.backend_url = os.getenv("COPILOT_BACKEND", cfg.backend_url)
    cfg.panel_url = os.getenv("COPILOT_PANEL_URL", cfg.panel_url)
    cfg.log_file = os.getenv(
        "QIANNIU_SIDECAR_LOG",
        os.path.join(os.path.dirname(__file__), "..", "..", "data", "sidecar", "qianniu_sidecar.log"),
    )
    cfg.poll_interval = float(os.getenv("QIANNIU_SIDECAR_INTERVAL", str(cfg.poll_interval)))
    cfg.request_timeout = float(os.getenv("QIANNIU_SIDECAR_TIMEOUT", str(cfg.request_timeout)))
    cfg.enable_vision_extractor = os.getenv("SIDECAR_ENABLE_VISION", "true").lower() in ("true", "1", "yes")
    cfg.vision_provider = os.getenv("SIDECAR_VISION_PROVIDER", cfg.vision_provider)
    cfg.vision_base_url = os.getenv("SIDECAR_VISION_BASE_URL", cfg.vision_base_url)
    cfg.vision_api_key = os.getenv("SIDECAR_VISION_API_KEY", cfg.vision_api_key)
    cfg.vision_model = os.getenv("SIDECAR_VISION_MODEL", cfg.vision_model)
    cfg.vision_timeout_seconds = int(os.getenv("SIDECAR_VISION_TIMEOUT_SECONDS", str(cfg.vision_timeout_seconds)))
    cfg.vision_min_confidence = float(os.getenv("SIDECAR_VISION_MIN_CONFIDENCE", str(cfg.vision_min_confidence)))
    cfg.vision_require_confirm = os.getenv("SIDECAR_VISION_REQUIRE_CONFIRM", "true").lower() in ("true", "1", "yes")
    cfg.save_screenshot_debug = os.getenv("SIDECAR_SAVE_SCREENSHOT_DEBUG", "false").lower() in ("true", "1", "yes")
    cfg.vision_eval_log = os.getenv(
        "SIDECAR_VISION_EVAL_LOG",
        os.path.join(os.path.dirname(__file__), "..", "..", "data", "sidecar", "vision_eval.jsonl"),
    )
    return cfg
