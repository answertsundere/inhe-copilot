"""Sidecar status API for desktop QianNiu capture."""

import threading
import time

from flask import Blueprint, jsonify, request

sidecar_bp = Blueprint("sidecar", __name__)

_lock = threading.Lock()
_status = {
    "backend_online": True,
    "sidecar_connected": False,
    "last_seen_at": "",
    "selected_window_title": "",
    "selected_hwnd": "",
    "window_matched": False,
    "uia_success": False,
    "uia_controls_count": 0,
    "order_candidates": [],
    "tracking_candidates": [],
    "product_candidates": [],
    "vision_provider": "",
    "vision_model": "",
    "vision_success": False,
    "vision_confidence": 0.0,
    "vision_duration_ms": 0,
    "source": "",
    "last_error": None,
    "latest_customer_message": "",
    "latest_messages": [],
    "latest_message_hash": "",
    "latest_analyzed_at": "",
    "latest_analysis": None,
    "analysis_status": "idle",
    "auto_analyze_enabled": False,
}


@sidecar_bp.route("/api/sidecar/status", methods=["GET"])
def get_sidecar_status():
    with _lock:
        return jsonify({
            "ok": True,
            **_status,
        })


@sidecar_bp.route("/api/sidecar/status", methods=["POST"])
def post_sidecar_status():
    global _status
    payload = request.get_json(silent=True) or {}
    with _lock:
        update_payload = {
            k: payload[k]
            for k in (
                "sidecar_connected", "last_seen_at",
                "selected_window_title", "selected_hwnd", "window_matched",
                "uia_success", "uia_controls_count",
                "order_candidates", "tracking_candidates", "product_candidates",
                "vision_provider", "vision_model", "vision_success",
                "vision_confidence", "vision_duration_ms",
                "source", "last_error",
                "latest_analyzed_at", "latest_analysis",
                "analysis_status", "auto_analyze_enabled",
            )
            if k in payload
        }

        latest_customer_message = (payload.get("latest_customer_message") or "").strip()
        latest_messages = payload.get("latest_messages")
        if latest_customer_message:
            update_payload["latest_customer_message"] = latest_customer_message
        if isinstance(latest_messages, list) and latest_messages:
            update_payload["latest_messages"] = latest_messages
        if payload.get("latest_message_hash"):
            update_payload["latest_message_hash"] = payload["latest_message_hash"]

        _status.update(update_payload)
        _status["sidecar_connected"] = True
        _status["last_seen_at"] = _status.get("last_seen_at") or time.strftime("%Y-%m-%dT%H:%M:%S")
    return jsonify({"ok": True})


@sidecar_bp.route("/api/sidecar/latest", methods=["GET"])
def get_sidecar_latest():
    with _lock:
        return jsonify({
            "ok": True,
            "sidecar_connected": _status.get("sidecar_connected", False),
            "window_matched": _status.get("window_matched", False),
            "selected_window_title": _status.get("selected_window_title", ""),
            "latest_customer_message": _status.get("latest_customer_message", ""),
            "latest_messages": _status.get("latest_messages", []),
            "latest_message_hash": _status.get("latest_message_hash", ""),
            "order_candidates": _status.get("order_candidates", []),
            "tracking_candidates": _status.get("tracking_candidates", []),
            "product_candidates": _status.get("product_candidates", []),
            "latest_analyzed_at": _status.get("latest_analyzed_at", ""),
            "latest_analysis": _status.get("latest_analysis"),
            "analysis_status": _status.get("analysis_status", "idle"),
            "auto_analyze_enabled": _status.get("auto_analyze_enabled", False),
            "last_error": _status.get("last_error"),
        })
