from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

from .config import SidecarConfig

logger = logging.getLogger(__name__)


def post_copilot_context(
    payload: dict[str, Any],
    config: SidecarConfig | None = None,
) -> dict[str, Any]:
    config = config or SidecarConfig()
    url = config.backend_url.rstrip("/") + "/api/copilot/context"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=config.request_timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        logger.error("backend returned %s: %s", exc.code, raw[:500])
        return {"ok": False, "status": exc.code, "raw": raw}
    except Exception as exc:
        logger.error("post context failed: %s", exc)
        return {"ok": False, "error": str(exc)}


def post_copilot_feedback(
    feedback_data: dict[str, Any],
    config: SidecarConfig | None = None,
) -> dict[str, Any]:
    config = config or SidecarConfig()
    url = config.backend_url.rstrip("/") + "/api/copilot/feedback"
    body = json.dumps(feedback_data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=config.request_timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw)
    except Exception as exc:
        logger.error("post feedback failed: %s", exc)
        return {"ok": False, "error": str(exc)}


def post_sidecar_status(
    status_data: dict[str, Any],
    config: SidecarConfig | None = None,
) -> dict[str, Any]:
    config = config or SidecarConfig()
    url = config.backend_url.rstrip("/") + "/api/sidecar/status"
    body = json.dumps(status_data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=config.request_timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw)
    except Exception as exc:
        logger.error("post sidecar status failed: %s", exc)
        return {"ok": False, "error": str(exc)}


def build_panel_url(config: SidecarConfig | None = None, source: str = "sidecar_mixed") -> str:
    config = config or SidecarConfig()
    base = config.panel_url
    separator = "&" if "?" in base else "?"
    return f"{base}{separator}source={source}"
