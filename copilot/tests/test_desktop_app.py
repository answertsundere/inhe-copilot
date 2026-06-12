"""
Desktop App Tests — 验证桌面客户端模块和 Sidecar API

覆盖需求:
1. config_store 读写配置
2. config_store 脱敏 API Key
3. api_client 基础调用
4. sidecar_manager 初始状态
5. api_bridge 方法存在
6. sidecar API GET/POST
7. sidecar 状态持久
8. 页面渲染包含 4 Tab
9. 页面包含安全提示
10. 不泄露隐私字段
"""

import sys
import os
import json
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


# ---- Config Store Tests ----

class TestConfigStore:
    def test_default_config_loads(self):
        from desktop.config_store import DEFAULT_CONFIG, load_config
        cfg = load_config()
        assert cfg["server_base_url"] == "http://127.0.0.1:5000"
        assert cfg["forbid_auto_send"] is True
        assert "vlm_provider" in cfg

    def test_save_and_reload(self):
        from desktop import config_store

        original_file = config_store.CONFIG_FILE
        with tempfile.TemporaryDirectory() as tmpdir:
            config_store.CONFIG_FILE = os.path.join(tmpdir, "config.json")
            try:
                original = config_store.load_config()
                modified = dict(original)
                modified["always_on_top"] = False
                modified["vlm_provider"] = "dashscope"
                config_store.save_config(modified)
                reloaded = config_store.load_config()
                assert reloaded["always_on_top"] is False
                assert reloaded["vlm_provider"] == "dashscope"
            finally:
                config_store.CONFIG_FILE = original_file

    def test_safe_config_masks_api_key(self):
        import os
        from desktop import config_store

        original_file = config_store.CONFIG_FILE
        with tempfile.TemporaryDirectory() as tmpdir:
            config_store.CONFIG_FILE = os.path.join(tmpdir, "config.json")
            try:
                config_store.save_config({
                    "vlm_api_key": "sk-test-secret-key-123",
                    "server_base_url": "http://127.0.0.1:5000",
                })
                safe = config_store.get_safe_config()
                assert safe.get("vlm_api_key_masked") == "sk-t****"
                # Original should not be in safe output
                assert safe.get("vlm_api_key", "") != "sk-test-secret-key-123"
            finally:
                config_store.CONFIG_FILE = original_file

    def test_config_dir_exists(self):
        from desktop.config_store import get_config_dir
        d = get_config_dir()
        assert ".inhe-copilot" in d


# ---- API Client Tests ----

class TestApiClient:
    def test_test_backend_returns_dict(self):
        from desktop.api_client import test_backend
        result = test_backend()
        assert isinstance(result, dict)
        # Backend may or may not be running, but should return dict

    def test_get_sidecar_status_returns_dict(self):
        from desktop.api_client import get_sidecar_status
        result = get_sidecar_status()
        assert isinstance(result, dict)


# ---- Sidecar Manager Tests ----

class TestSidecarManager:
    def test_initial_not_running(self):
        from desktop.sidecar_manager import SidecarManager
        mgr = SidecarManager()
        assert mgr.is_running() is False
        assert mgr.get_pid() == 0

    def test_stop_when_not_running(self):
        from desktop.sidecar_manager import SidecarManager
        mgr = SidecarManager()
        result = mgr.stop()
        assert result["ok"] is True

    def test_sidecar_env_includes_vlm_config(self):
        from desktop.sidecar_manager import _sidecar_env_from_config

        env = _sidecar_env_from_config({
            "server_base_url": "http://127.0.0.1:5000",
            "poll_interval": 3,
            "request_timeout": 20,
            "enable_vision": True,
            "vlm_provider": "mimo",
            "vlm_base_url": "https://vision.example.com/v1",
            "vlm_api_key": "sk-test",
            "vlm_model": "mimo-v2.5",
            "vlm_timeout_seconds": 15,
            "vlm_min_confidence": 0.8,
            "vlm_require_confirm": True,
        })

        assert env["SIDECAR_ENABLE_VISION"] == "true"
        assert env["SIDECAR_VISION_PROVIDER"] == "mimo"
        assert env["SIDECAR_VISION_BASE_URL"] == "https://vision.example.com/v1"
        assert env["SIDECAR_VISION_API_KEY"] == "sk-test"
        assert env["SIDECAR_VISION_MODEL"] == "mimo-v2.5"
        assert env["SIDECAR_VISION_TIMEOUT_SECONDS"] == "15"
        assert env["SIDECAR_VISION_MIN_CONFIDENCE"] == "0.8"


# ---- API Bridge Tests ----

class TestApiBridge:
    def test_has_required_methods(self):
        from desktop.api_bridge import ApiBridge
        bridge = ApiBridge()
        assert hasattr(bridge, "test_backend")
        assert hasattr(bridge, "analyze")
        assert hasattr(bridge, "submit_feedback")
        assert hasattr(bridge, "get_metrics")
        assert hasattr(bridge, "get_sidecar_status")
        assert hasattr(bridge, "get_config")
        assert hasattr(bridge, "save_config")
        assert hasattr(bridge, "start_sidecar")
        assert hasattr(bridge, "stop_sidecar")
        assert hasattr(bridge, "capture_qianniu_once")
        assert hasattr(bridge, "get_diagnostic_info")

    def test_get_config_returns_dict(self):
        from desktop.api_bridge import ApiBridge
        bridge = ApiBridge()
        cfg = bridge.get_config()
        assert isinstance(cfg, dict)
        assert "server_base_url" in cfg

    def test_diagnostic_info_returns_dict(self):
        from desktop.api_bridge import ApiBridge
        bridge = ApiBridge()
        info = bridge.get_diagnostic_info()
        assert isinstance(info, dict)
        assert "sidecar_process_running" in info


# ---- Sidecar API Endpoint Tests ----

@pytest.fixture
def app():
    from app.main import create_app
    app = create_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


class TestSidecarAPI:
    def test_get_status(self, client):
        resp = client.get("/api/sidecar/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert "sidecar_connected" in data
        assert "window_matched" in data
        assert "vision_provider" in data

    def test_post_status_updates(self, client):
        resp = client.post("/api/sidecar/status",
                          json={
                              "sidecar_connected": True,
                              "window_matched": True,
                              "selected_window_title": "千牛卖家中心",
                              "vision_provider": "mock",
                              "uia_controls_count": 235,
                          },
                          content_type="application/json")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True

        # Verify GET reflects update
        resp2 = client.get("/api/sidecar/status")
        data2 = resp2.get_json()
        assert data2["window_matched"] is True
        assert data2["selected_window_title"] == "千牛卖家中心"
        assert data2["uia_controls_count"] == 235

    def test_post_partial_update(self, client):
        resp = client.post("/api/sidecar/status",
                          json={"vision_confidence": 0.91},
                          content_type="application/json")
        assert resp.status_code == 200


# ---- Renderer HTML Tests ----

class TestRendererHTML:
    def test_index_html_has_4_tabs(self):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "desktop", "pages", "index.html")
        with open(path, "r", encoding="utf-8") as f:
            html = f.read()
        assert "主页" in html
        assert "设置" in html
        assert "诊断" in html
        assert "指标" in html

    def test_has_safety_notice(self):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "desktop", "pages", "index.html")
        with open(path, "r", encoding="utf-8") as f:
            html = f.read()
        assert "不会自动发送到千牛" in html
        assert "forbid_auto_send" in html or "禁止自动发送" in html

    def test_has_no_private_fields(self):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "desktop", "pages", "index.html")
        with open(path, "r", encoding="utf-8") as f:
            html = f.read()
        assert "buyer_id" not in html
        assert "receiver_phone" not in html
        assert "receiver_address" not in html
        assert "receiver_name" not in html

    def test_has_reject_reasons(self):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "desktop", "pages", "index.html")
        with open(path, "r", encoding="utf-8") as f:
            html = f.read()
        assert "事实错误" in html
        assert "AI 回复太保守" in html
        assert "AI 回复太冒进" in html

    def test_has_escalate_button(self):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "desktop", "pages", "index.html")
        with open(path, "r", encoding="utf-8") as f:
            html = f.read()
        assert "转人工/主管" in html

    def test_has_keyboard_shortcuts(self):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "desktop", "pages", "index.html")
        with open(path, "r", encoding="utf-8") as f:
            html = f.read()
        assert "ctrlKey" in html
        assert "shiftKey" in html

    def test_has_vision_banner(self):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "desktop", "pages", "index.html")
        with open(path, "r", encoding="utf-8") as f:
            html = f.read()
        assert "视觉识别" in html

    def test_has_metrics_cards(self):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "desktop", "pages", "index.html")
        with open(path, "r", encoding="utf-8") as f:
            html = f.read()
        assert "今日建议" in html
        assert "采纳数" in html
        assert "高风险" in html
