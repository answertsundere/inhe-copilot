"""
API Bridge — 暴露给 JS 的 Python API
pywebview 自动将此类方法映射为 window.pywebview.api.xxx()
"""

import json
import os
import subprocess
import sys

import desktop.api_client as api_client
from desktop.config_store import load_config, save_config, get_safe_config, get_config_dir
from desktop.sidecar_manager import SidecarManager


class ApiBridge:
    def __init__(self, window=None):
        self._window = window
        self._sidecar = SidecarManager()

    # ---- Backend ----

    def test_backend(self):
        return api_client.test_backend()

    def analyze(self, payload_json):
        payload = json.loads(payload_json) if isinstance(payload_json, str) else payload_json
        return api_client.analyze(payload)

    def submit_feedback(self, payload_json):
        payload = json.loads(payload_json) if isinstance(payload_json, str) else payload_json
        return api_client.submit_feedback(payload)

    def get_metrics(self):
        return api_client.get_metrics()

    def get_sidecar_status(self):
        result = api_client.get_sidecar_status()
        result["sidecar_process_running"] = self._sidecar.is_running()
        result["sidecar_pid"] = self._sidecar.get_pid()
        return result

    def get_sidecar_latest(self):
        return api_client.get_sidecar_latest()

    # ---- Config ----

    def get_config(self):
        return get_safe_config()

    def save_config(self, config_json):
        cfg = json.loads(config_json) if isinstance(config_json, str) else config_json
        return save_config(cfg)

    # ---- Sidecar ----

    def start_sidecar(self):
        return self._sidecar.start()

    def stop_sidecar(self):
        return self._sidecar.stop()

    def capture_qianniu_once(self):
        return self._sidecar.capture_once()

    # ---- Window ----

    def set_always_on_top(self, flag_json):
        flag = json.loads(flag_json) if isinstance(flag_json, str) else flag_json
        if self._window:
            self._window.on_top = bool(flag)
        return {"ok": True}

    def copy_to_clipboard(self, text):
        if self._window:
            self._window.evaluate_js(f"navigator.clipboard.writeText({json.dumps(text)})")
        return {"ok": True}

    def open_logs_folder(self):
        log_dir = get_config_dir()
        os.makedirs(log_dir, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(log_dir)
        return {"ok": True, "path": log_dir}

    def get_diagnostic_info(self):
        cfg = load_config()
        backend = api_client.test_backend()
        sidecar_running = self._sidecar.is_running()
        sidecar_pid = self._sidecar.get_pid()
        return {
            "backend_online": backend.get("ok", False) if isinstance(backend, dict) else False,
            "backend_response": backend,
            "sidecar_process_running": sidecar_running,
            "sidecar_pid": sidecar_pid,
            "server_base_url": cfg.get("server_base_url", ""),
            "vlm_provider": cfg.get("vlm_provider", "mock"),
            "vlm_model": cfg.get("vlm_model", ""),
            "python_version": sys.version,
        }
