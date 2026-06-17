from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import time
import unicodedata
import webbrowser
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.sidecar.config import SidecarConfig, load_config_from_env
from scripts.sidecar.context_parser import build_extract_status
from scripts.sidecar.copilot_client import build_panel_url, post_copilot_context, post_sidecar_status
from scripts.sidecar.privacy_filter import is_safe_for_log
from scripts.sidecar.uia_sidebar_extractor import extract_sidebar
from scripts.sidecar.vision_extractor import extract_chat_from_vision
from scripts.sidecar.window_watcher import attach_uia_window, select_window


logger = logging.getLogger(__name__)


def configure_logging(log_file: str) -> None:
    path = Path(log_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.FileHandler(path, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def run_single_capture(config: SidecarConfig, debug: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {
        "candidate_windows": [],
        "selected_window_title": "",
        "selected_hwnd": None,
        "selected_reason": "",

        "uia_success": False,
        "uia_controls_count": 0,
        "uia_text_count": 0,
        "order_candidates": [],
        "tracking_candidates": [],
        "product_candidates": [],

        "vision_enabled": config.enable_vision_extractor,
        "vision_region": config.chat_region,
        "vision_success": False,
        "vision_confidence": 0.0,
        "messages": [],
        "latest_customer_message": "",
        "latest_agent_message": "",
        "vision_messages_count": 0,

        "needs_manual_confirm": True,
        "panel_url": build_panel_url(config, "sidecar_mixed"),
        "api_status": "not_called",

        "customer_message_source": "",
        "extract_status": "",
        "warnings": [],
    }

    # Step 1: Find window
    selection = select_window(config)
    if selection is None:
        result["warnings"].append("no_qianniu_window_found")
        return result

    result["selected_hwnd"] = selection.selected_hwnd
    result["selected_window_title"] = selection.selected_title
    result["selected_reason"] = selection.selected_reason
    result["candidate_windows"] = [
        {
            "hwnd": c.hwnd,
            "title": c.title,
            "class_name": c.class_name,
            "visible": c.visible,
            "minimized": c.minimized,
            "score": c.score,
        }
        for c in selection.candidate_windows
    ]

    # Step 2: UIA sidebar extraction
    window = attach_uia_window(selection.selected_hwnd)
    uia_result = extract_sidebar(window, config)
    result["uia_success"] = uia_result.success
    result["uia_controls_count"] = uia_result.controls_count
    result["uia_text_count"] = uia_result.text_count
    result["order_candidates"] = [c.__dict__ for c in uia_result.order_candidates]
    result["tracking_candidates"] = [
        {"value": c.value, "carrier": c.carrier, "source": c.source, "confidence": c.confidence, "verified": c.verified}
        for c in uia_result.tracking_candidates
    ]
    result["product_candidates"] = [c.__dict__ for c in uia_result.product_candidates]
    result["warnings"].extend(uia_result.warnings)

    # Step 3: Vision extraction
    if config.enable_vision_extractor:
        vision_result = extract_chat_from_vision(selection.selected_hwnd, config)
        result["vision_success"] = vision_result.success
        result["vision_confidence"] = vision_result.confidence
        result["messages"] = [
            {"role": m.role, "text": m.text, "time": m.time, "confidence": m.confidence}
            for m in vision_result.messages
        ]
        result["latest_customer_message"] = vision_result.latest_customer_message
        result["latest_agent_message"] = vision_result.latest_agent_message
        result["vision_messages_count"] = len(vision_result.messages)
        result["warnings"].extend(vision_result.warnings)

        # Merge vision candidates (UIA takes priority for tracking/orders)
        vision_order_values = {c.value for c in uia_result.order_candidates}
        for cand in vision_result.order_candidates:
            if cand.value not in vision_order_values:
                result["order_candidates"].append({
                    "value": cand.value, "source": "vision",
                    "confidence": cand.confidence, "verified": False,
                })

        tracking_values = {c.value for c in uia_result.tracking_candidates}
        for cand in vision_result.tracking_candidates:
            if cand.value not in tracking_values:
                result["tracking_candidates"].append({
                    "value": cand.value, "source": "vision",
                    "confidence": cand.confidence, "verified": False,
                })

        product_values = {c.value for c in uia_result.product_candidates}
        for cand in vision_result.product_candidates:
            if cand.value not in product_values:
                result["product_candidates"].append({
                    "value": cand.value, "source": "vision",
                    "confidence": cand.confidence,
                })

        result["customer_message_source"] = "vision"
    else:
        result["warnings"].append("vision_disabled")
        result["customer_message_source"] = "none"

    # Step 4: Determine extract status
    extract_status = build_extract_status(
        customer_message=result["latest_customer_message"],
        has_uia_sidebar=uia_result.success,
        has_vision=result["vision_success"],
    )
    result["extract_status"] = extract_status["extract_status"]
    result["needs_manual_confirm"] = extract_status["needs_manual_confirm"]
    result["should_call_copilot_context"] = extract_status["should_call_copilot_context"]

    return result


def build_mixed_payload(capture_result: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": "sidecar_mixed",
        "customer_message": capture_result.get("latest_customer_message", ""),
        "conversation_history": capture_result.get("messages", []),
        "customer_message_source": capture_result.get("customer_message_source", ""),
        "window_title": capture_result.get("selected_window_title", ""),
        "conversation_id": "",
        "order_candidates": capture_result.get("order_candidates", []),
        "tracking_candidates": capture_result.get("tracking_candidates", []),
        "product_candidates": capture_result.get("product_candidates", []),
        "needs_manual_confirm": capture_result.get("needs_manual_confirm", True),
        "extract_status": capture_result.get("extract_status", ""),
    }


def build_status_payload(capture_result: dict[str, Any], config: SidecarConfig) -> dict[str, Any]:
    return {
        "sidecar_connected": True,
        "last_seen_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "selected_window_title": capture_result.get("selected_window_title", ""),
        "selected_hwnd": str(capture_result.get("selected_hwnd") or ""),
        "window_matched": bool(capture_result.get("selected_hwnd")),
        "uia_success": bool(capture_result.get("uia_success")),
        "uia_controls_count": int(capture_result.get("uia_controls_count") or 0),
        "order_candidates": capture_result.get("order_candidates", []),
        "tracking_candidates": capture_result.get("tracking_candidates", []),
        "product_candidates": capture_result.get("product_candidates", []),
        "vision_provider": config.vision_provider,
        "vision_model": config.vision_model,
        "vision_success": bool(capture_result.get("vision_success")),
        "vision_confidence": float(capture_result.get("vision_confidence") or 0.0),
        "vision_duration_ms": int(capture_result.get("vision_duration_ms") or 0),
        "source": "sidecar_mixed",
        "last_error": ";".join(capture_result.get("warnings", [])[:5]) or None,
        "latest_customer_message": capture_result.get("latest_customer_message", ""),
        "latest_messages": capture_result.get("messages", []),
        "latest_message_hash": capture_result.get("latest_message_hash", ""),
        "analysis_status": capture_result.get("analysis_status", "captured"),
        "auto_analyze_enabled": bool(capture_result.get("auto_analyze_enabled", False)),
    }


def run_loop(args: argparse.Namespace, config: SidecarConfig) -> None:
    if args.open_panel:
        webbrowser.open(build_panel_url(config, "sidecar_mixed"))

    processed_key = ""
    candidate_key = ""
    stable_count = 0
    while True:
        capture = run_single_capture(config, debug=args.debug)
        capture["auto_analyze_enabled"] = bool(args.auto_analyze)
        customer_message = capture.get("latest_customer_message", "")
        key = _message_key(capture)
        capture["latest_message_hash"] = key
        post_sidecar_status(build_status_payload(capture, config), config)

        if not capture.get("selected_hwnd"):
            logger.info("qianniu window not found")
        else:
            logger.info(
                "capture: title=%s uia=%s vision=%s customer=%r",
                capture["selected_window_title"],
                capture["uia_success"],
                capture["vision_success"],
                capture["latest_customer_message"][:50],
            )

            if key and key == candidate_key:
                stable_count += 1
            else:
                candidate_key = key
                stable_count = 1 if key else 0

            if customer_message and key != processed_key and stable_count >= args.stable_reads:
                if args.auto_analyze:
                    payload = build_mixed_payload(capture)
                    capture["analysis_status"] = "analyzing"
                    post_sidecar_status(build_status_payload(capture, config), config)
                    resp = post_copilot_context(payload, config)
                    capture["api_status"] = "called" if resp.get("ok") else "error"
                    capture["analysis_status"] = "analyzed" if resp.get("ok") else "analysis_error"
                    capture["latest_analysis"] = resp
                    status_payload = build_status_payload(capture, config)
                    status_payload["latest_analysis"] = resp
                    status_payload["latest_analyzed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                    post_sidecar_status(status_payload, config)
                    logger.info("copilot result ok=%s", resp.get("ok"))
                    processed_key = key
                else:
                    logger.info(
                        "auto analyze disabled, panel_url=%s",
                        capture.get("panel_url"),
                    )
            elif not customer_message:
                logger.info("no customer message extracted")

        if args.once:
            if args.debug:
                safe = is_safe_for_log(capture)
                output = json.dumps(safe, ensure_ascii=False, indent=2)
                sys.stdout.buffer.write(output.encode("utf-8", errors="replace"))
                sys.stdout.buffer.write(b"\n")
            break

        time.sleep(config.poll_interval)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="QianNiu Copilot Sidecar (mixed architecture)")
    parser.add_argument("--backend", default=os.getenv("COPILOT_BACKEND", "http://127.0.0.1:5011"))
    parser.add_argument("--panel-url", default=os.getenv("COPILOT_PANEL_URL", "http://127.0.0.1:5011/copilot-panel"))
    parser.add_argument("--log-file", default=os.getenv("QIANNIU_SIDECAR_LOG", ""))
    parser.add_argument("--interval", type=float, default=float(os.getenv("QIANNIU_SIDECAR_INTERVAL", "2.0")))
    parser.add_argument("--timeout", type=float, default=float(os.getenv("QIANNIU_SIDECAR_TIMEOUT", "10.0")))
    parser.add_argument("--open-panel", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--no-auto-post", action="store_true", default=True)
    parser.add_argument("--auto-analyze", action="store_true", default=True)
    parser.add_argument("--stable-reads", type=int, default=int(os.getenv("QIANNIU_STABLE_READS", "2")))
    parser.add_argument("--vision-provider",
                        choices=["mock", "external_openai_compatible", "local_openai_compatible", "dashscope", "mimo", "custom"],
                        default=os.getenv("SIDECAR_VISION_PROVIDER", "external_openai_compatible"))
    return parser.parse_args()


def _message_key(capture: dict[str, Any]) -> str:
    message = _normalize_message_for_key(capture.get("latest_customer_message") or "")
    if not message:
        return ""
    raw = f"{capture.get('selected_hwnd') or ''}|{message}"
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()


def _normalize_message_for_key(message: str) -> str:
    chars: list[str] = []
    for ch in (message or "").strip():
        category = unicodedata.category(ch)
        if category in ("So", "Sk", "Cs"):
            continue
        if ch.isspace():
            continue
        chars.append(ch)
    return "".join(chars)


def main() -> None:
    # Load .env before reading config
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        # sidecar-specific config overrides
        sidecar_env = ROOT / "sidecar.env"
        if sidecar_env.exists():
            load_dotenv(sidecar_env, override=True)
    except Exception:
        pass

    args = parse_args()
    config = load_config_from_env()
    if args.backend:
        config.backend_url = args.backend
    if args.panel_url:
        config.panel_url = args.panel_url
    if args.log_file:
        config.log_file = args.log_file
    if not config.log_file:
        config.log_file = str(ROOT / "data" / "sidecar" / "qianniu_sidecar.log")
    config.poll_interval = args.interval
    config.request_timeout = args.timeout
    config.vision_provider = args.vision_provider

    configure_logging(config.log_file)
    logger.info(
        "starting qianniu sidecar (mixed architecture) backend=%s interval=%s vision=%s",
        config.backend_url, config.poll_interval, config.vision_provider,
    )
    run_loop(args, config)


if __name__ == "__main__":
    main()
