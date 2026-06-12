"""
API Client — Flask 后端 HTTP 客户端
"""

import json
import urllib.request
import urllib.error

from desktop.config_store import load_config


def _base_url() -> str:
    return load_config().get("server_base_url", "http://127.0.0.1:5000")


def _timeout() -> int:
    return load_config().get("request_timeout", 30)


def _request(method: str, path: str, body: dict = None) -> dict:
    url = _base_url().rstrip("/") + path
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=_timeout()) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"ok": False, "error": f"HTTP {e.code}"}
    except urllib.error.URLError:
        return {"ok": False, "error": "connection_failed"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def test_backend() -> dict:
    return _request("GET", "/api/health")


def analyze(payload: dict) -> dict:
    return _request("POST", "/api/copilot/context", payload)


def submit_feedback(payload: dict) -> dict:
    return _request("POST", "/api/copilot/feedback", payload)


def get_metrics() -> dict:
    return _request("GET", "/api/copilot/metrics")


def get_sidecar_status() -> dict:
    return _request("GET", "/api/sidecar/status")


def get_sidecar_latest() -> dict:
    return _request("GET", "/api/sidecar/latest")
