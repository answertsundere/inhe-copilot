"""Sidecar status API for desktop QianNiu capture."""

import threading
import time
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

from flask import Blueprint, jsonify, request
from app.api.admin_auth import current_principal, require_authenticated

sidecar_bp = Blueprint("sidecar", __name__)

_lock = threading.Lock()
_manual_capture_lock = threading.Lock()
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


def _native_preview(payload):
    root = Path(__file__).resolve().parents[2]
    env = {key: value for key, value in os.environ.items()
           if key.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH", "USERPROFILE", "APPDATA", "LOCALAPPDATA"}}
    env.update(PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1",
               COPILOT_KNOWLEDGE_DB_PATH=":memory:", COPILOT_QIANNIU_PREVIEW_PIPE="1")
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "qianniu_sidecar.py"), "--manual-native-stdin"],
        input=json.dumps(payload), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, encoding="utf-8", timeout=20, cwd=root, env=env,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    if len(result.stdout) > 2_000_000:
        return {"ok": False, "error": "capture_size_limit"}
    return json.loads(result.stdout)


@sidecar_bp.after_request
def _private_preview_headers(response):
    if request.endpoint == "sidecar.preview_qianniu_conversation":
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["Pragma"] = "no-cache"
    return response


@sidecar_bp.route("/api/sidecar/qianniu/preview", methods=["POST"])
@require_authenticated
def preview_qianniu_conversation():
    """One local human-requested observation, never an automatic Agent input."""
    if os.environ.get("COPILOT_QIANNIU_MANUAL_READ_ENABLED", "").lower() != "true":
        return jsonify(ok=False, error="manual_read_disabled"), 404
    principal = current_principal()
    try:
        host = urlsplit("//" + request.host).hostname
        origin = urlsplit(request.headers.get("Origin", ""))
        local = {"127.0.0.1", "localhost", "::1"}
        valid_origin = (origin.scheme in {"http", "https"} and origin.hostname in local
                        and not origin.username and not origin.password
                        and not origin.path and not origin.query and not origin.fragment)
        forwarded = any(k.lower().startswith(("x-forwarded-", "cf-")) or k.lower() == "forwarded"
                        for k in request.headers.keys())
        permitted = (request.remote_addr in {"127.0.0.1", "::1"} and host in local
                     and valid_origin and not forwarded and not principal.is_service
                     and principal.auth_type in {"development", "cloudflare_access", "test"})
    except ValueError:
        permitted = False
    if not permitted:
        return jsonify(ok=False, error="local_human_capture_required"), 403
    if request.content_length is None or request.content_length > 1024:
        return jsonify(ok=False, error="capture_request_invalid"), 422
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or set(payload) - {"window_handle", "mode"}:
        return jsonify(ok=False, error="capture_request_invalid"), 422
    if payload.get("mode", "native_selection") not in ("native_selection", "manual_document_review"):
        return jsonify(ok=False, error="capture_mode_invalid"), 422
    if "window_handle" in payload and (type(payload["window_handle"]) is not int or payload["window_handle"] <= 0):
        return jsonify(ok=False, error="window_selection_invalid"), 422
    if not _manual_capture_lock.acquire(blocking=False):
        return jsonify(ok=False, error="capture_busy"), 503
    try:
        result = _native_preview(payload)
        return jsonify(result), 200 if result.get("ok") else 422
    except subprocess.TimeoutExpired:
        return jsonify(ok=False, error="native_capture_timeout"), 503
    except Exception:
        return jsonify(ok=False, error="native_capture_unavailable"), 503
    finally:
        _manual_capture_lock.release()


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
