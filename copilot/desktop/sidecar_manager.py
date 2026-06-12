"""
Sidecar Manager — Sidecar 子进程管理
"""

import os
import json
import subprocess
import sys

from desktop.config_store import load_config


class SidecarManager:
    def __init__(self):
        self._process = None
        self._log_lines = []

    def start(self) -> dict:
        if self.is_running():
            return {"ok": True, "status": "already_running"}

        cfg = load_config()
        script = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "scripts", "sidecar", "qianniu_sidecar.py"
        )

        if not os.path.exists(script):
            return {"ok": False, "error": f"sidecar script not found: {script}"}

        cmd = [
            sys.executable,
            script,
            "--backend", cfg.get("server_base_url", "http://127.0.0.1:5000"),
            "--panel-url", cfg.get("server_base_url", "http://127.0.0.1:5000").rstrip("/") + "/copilot-panel",
            "--interval", str(cfg.get("poll_interval", 5)),
            "--timeout", str(cfg.get("request_timeout", 30)),
            "--vision-provider", cfg.get("vlm_provider", "mock"),
            "--stable-reads", str(cfg.get("stable_reads", 1)),
            "--auto-analyze",
        ]
        env = os.environ.copy()
        env.update(_sidecar_env_from_config(cfg))
        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            return {"ok": True, "pid": self._process.pid}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def stop(self) -> dict:
        if not self.is_running():
            return {"ok": True, "status": "not_running"}
        try:
            self._process.terminate()
            self._process.wait(timeout=5)
        except Exception:
            try:
                self._process.kill()
            except Exception:
                pass
        self._process = None
        return {"ok": True}

    def is_running(self) -> bool:
        if self._process is None:
            return False
        return self._process.poll() is None

    def get_pid(self) -> int:
        return self._process.pid if self.is_running() else 0

    def capture_once(self) -> dict:
        cfg = load_config()
        script = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "scripts", "sidecar", "qianniu_sidecar.py"
        )
        if not os.path.exists(script):
            return {"ok": False, "error": f"sidecar script not found: {script}"}

        cmd = [
            sys.executable,
            script,
            "--once",
            "--debug",
            "--backend", cfg.get("server_base_url", "http://127.0.0.1:5000"),
            "--panel-url", cfg.get("server_base_url", "http://127.0.0.1:5000").rstrip("/") + "/copilot-panel",
            "--interval", str(cfg.get("poll_interval", 5)),
            "--timeout", str(cfg.get("request_timeout", 30)),
            "--vision-provider", cfg.get("vlm_provider", "mock"),
        ]
        try:
            completed = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env={**os.environ.copy(), **_sidecar_env_from_config(cfg)},
                timeout=max(float(cfg.get("request_timeout", 30)) + 10, 20),
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            data = _parse_json_from_stdout(completed.stdout)
            if data is None:
                return {
                    "ok": False,
                    "error": "capture_output_not_json",
                    "stdout": completed.stdout[-1000:],
                    "stderr": completed.stderr[-1000:],
                    "returncode": completed.returncode,
                }
            data["ok"] = completed.returncode == 0
            if completed.returncode != 0:
                data["error"] = data.get("error") or completed.stderr[-500:]
            return data
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "capture_timeout"}
        except Exception as e:
            return {"ok": False, "error": str(e)}


def _sidecar_env_from_config(cfg: dict) -> dict[str, str]:
    """Map desktop config keys to the sidecar's environment contract."""
    env = {
        "COPILOT_BACKEND": cfg.get("server_base_url", "http://127.0.0.1:5000"),
        "COPILOT_PANEL_URL": cfg.get("server_base_url", "http://127.0.0.1:5000").rstrip("/") + "/copilot-panel",
        "QIANNIU_SIDECAR_INTERVAL": str(cfg.get("poll_interval", 5)),
        "QIANNIU_STABLE_READS": str(cfg.get("stable_reads", 1)),
        "QIANNIU_SIDECAR_TIMEOUT": str(cfg.get("request_timeout", 30)),
        "SIDECAR_ENABLE_VISION": "true" if cfg.get("enable_vision") else "false",
        "SIDECAR_VISION_PROVIDER": cfg.get("vlm_provider", "mock"),
        "SIDECAR_VISION_BASE_URL": cfg.get("vlm_base_url", ""),
        "SIDECAR_VISION_API_KEY": cfg.get("vlm_api_key", ""),
        "SIDECAR_VISION_MODEL": cfg.get("vlm_model", ""),
        "SIDECAR_VISION_TIMEOUT_SECONDS": str(cfg.get("vlm_timeout_seconds", 10)),
        "SIDECAR_VISION_MIN_CONFIDENCE": str(cfg.get("vlm_min_confidence", 0.5)),
        "SIDECAR_VISION_REQUIRE_CONFIRM": "true" if cfg.get("vlm_require_confirm", True) else "false",
        "SIDECAR_SAVE_SCREENSHOT_DEBUG": "true" if cfg.get("vlm_save_screenshot_debug") or cfg.get("save_screenshot_debug") else "false",
        "PYTHONIOENCODING": "utf-8",
    }
    return {k: v for k, v in env.items() if v is not None}


def _parse_json_from_stdout(stdout: str) -> dict | None:
    text = (stdout or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            return None
    return None
