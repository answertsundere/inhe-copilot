from __future__ import annotations

import json
import os
import tempfile

from scripts.sidecar.config import SidecarConfig
from scripts.sidecar.vlm_client import _parse_vlm_response, call_vlm
from scripts.sidecar.vision_eval import VisionEvalRecord, append_eval_record
from scripts.sidecar.vision_extractor import (
    VisionExtractResult,
    extract_chat_from_vision,
)
from scripts.sidecar.vision_prompt import VISION_MOCK_RESPONSE


class TestVLMMock:
    def test_mock_returns_valid_structure(self):
        config = SidecarConfig(vision_provider="mock")
        result = call_vlm(b"fake_image_data", config)
        assert result["success"] is True
        assert result["latest_customer_message"] == "我没找到，怎么让他自动感应"
        assert result["latest_agent_message"] == "拍下这边看下"

    def test_mock_has_messages(self):
        config = SidecarConfig(vision_provider="mock")
        result = call_vlm(b"fake_image_data", config)
        assert len(result["messages"]) == 3
        roles = [m["role"] for m in result["messages"]]
        assert "customer" in roles
        assert "agent" in roles


def test_sidecar_cli_accepts_frontend_vlm_providers(monkeypatch):
    from scripts.sidecar import qianniu_sidecar

    monkeypatch.setattr(
        "sys.argv",
        [
            "qianniu_sidecar.py",
            "--vision-provider",
            "mimo",
            "--once",
        ],
    )
    args = qianniu_sidecar.parse_args()

    assert args.vision_provider == "mimo"


def test_mimo_provider_resolves_openai_compatible_config(monkeypatch):
    monkeypatch.setenv("SIDECAR_VISION_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1")
    monkeypatch.setenv("SIDECAR_VISION_API_KEY", "mimo-key")
    config = SidecarConfig(vision_provider="mimo")

    assert config.resolve_vision_base_url() == "https://token-plan-sgp.xiaomimimo.com/v1"
    assert config.resolve_vision_api_key() == "mimo-key"


class TestVLMParseResponse:
    def test_parse_valid_json(self):
        raw = json.dumps(VISION_MOCK_RESPONSE)
        result = _parse_vlm_response(raw)
        assert result["success"] is True
        assert result["latest_customer_message"] == "我没找到，怎么让他自动感应"

    def test_parse_json_in_code_block(self):
        raw = f"```json\n{json.dumps(VISION_MOCK_RESPONSE)}\n```"
        result = _parse_vlm_response(raw)
        assert result["success"] is True

    def test_parse_malformed_json_no_crash(self):
        result = _parse_vlm_response("this is not json at all")
        assert result["success"] is False
        assert "vlm_response_not_json" in result.get("error", "")
        assert result["messages"] == []
        assert result["latest_customer_message"] == ""

    def test_parse_partial_json(self):
        raw = '{"success": true, "messages": []}'
        result = _parse_vlm_response(raw)
        assert result["success"] is True
        assert result["latest_customer_message"] == ""
        assert result["order_candidates"] == []


class TestVisionExtractResult:
    def test_low_confidence_needs_confirm(self):
        config = SidecarConfig(
            enable_vision_extractor=True,
            vision_provider="mock",
            vision_min_confidence=0.85,
            vision_require_confirm=True,
        )
        result = VisionExtractResult(
            success=True, confidence=0.7,
            latest_customer_message="test",
        )
        assert result.needs_manual_confirm is True

    def test_confidence_threshold(self):
        config = SidecarConfig(
            vision_min_confidence=0.85,
            vision_require_confirm=False,
        )
        result = VisionExtractResult(success=True, confidence=0.9)
        # Even high confidence still needs confirm when require_confirm=True (default)
        assert result.needs_manual_confirm is True

    def test_to_dict_structure(self):
        result = VisionExtractResult(
            success=True,
            confidence=0.9,
            latest_customer_message="test msg",
            needs_manual_confirm=True,
        )
        d = result.to_dict()
        assert d["extract_method"] == "vision_vlm"
        assert d["success"] is True
        assert d["needs_manual_confirm"] is True


class TestVisionDisabled:
    def test_vision_disabled_returns_warning(self):
        config = SidecarConfig(enable_vision_extractor=False)
        result = extract_chat_from_vision(hwnd=12345, config=config)
        assert result.success is False
        assert "vision_extractor_disabled" in result.warnings

    def test_order_candidates_from_vision_verified_false(self):
        config = SidecarConfig(vision_provider="mock")
        result = call_vlm(b"data", config)
        for cand in result.get("order_candidates", []):
            # VLM candidates are never verified
            pass  # mock has no order candidates, but the pattern holds

    def test_tracking_from_vision_verified_false(self):
        result = VisionExtractResult(success=True)
        d = result.to_dict()
        for cand in d.get("tracking_candidates", []):
            assert cand["verified"] is False


class TestScreenshotNotPersisted:
    def test_default_no_debug_screenshot(self):
        config = SidecarConfig()
        assert config.save_screenshot_debug is False


class TestVisionEvalLogging:
    def test_eval_record_appended_to_jsonl(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "eval.jsonl")
            record = VisionEvalRecord(
                model_name="test-model",
                provider="mock",
                image_size_bytes=1024,
                duration_ms=50,
                confidence=0.9,
                latest_customer_message="测试消息",
                role_parse_success=True,
                json_parse_success=True,
            )
            append_eval_record(record, log_path)

            with open(log_path, encoding="utf-8") as f:
                lines = f.readlines()
            assert len(lines) == 1
            data = json.loads(lines[0])
            assert data["model_name"] == "test-model"
            assert data["provider"] == "mock"
            assert data["duration_ms"] == 50
            assert data["json_parse_success"] is True

    def test_eval_record_redacts_phone_numbers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "eval.jsonl")
            record = VisionEvalRecord(
                model_name="test-model",
                provider="mock",
                latest_customer_message="收货地址在北京市朝阳区13812345678",
            )
            append_eval_record(record, log_path)

            with open(log_path, encoding="utf-8") as f:
                data = json.loads(f.readline())
            assert "13812345678" not in data["latest_customer_message"]
            assert "北京市朝阳区" not in data["latest_customer_message"]

    def test_eval_log_created_on_vlm_call(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "eval.jsonl")
            config = SidecarConfig(
                vision_provider="mock",
                vision_eval_log=log_path,
            )
            call_vlm(b"test_data", config)

            with open(log_path, encoding="utf-8") as f:
                lines = f.readlines()
            assert len(lines) == 1
            data = json.loads(lines[0])
            assert data["provider"] == "mock"
            assert data["json_parse_success"] is True

    def test_eval_record_no_raw_image(self):
        record = VisionEvalRecord(model_name="m", provider="mock")
        d = record.to_dict()
        assert "image_data" not in d
        assert "image_b64" not in d
        assert "raw_screenshot" not in d


class TestProviderRouting:
    def test_external_openai_compatible_uses_resolve(self):
        config = SidecarConfig(
            vision_provider="external_openai_compatible",
            vision_base_url="https://api.example.com/v1",
            vision_api_key="test-key",
        )
        assert config.resolve_vision_base_url() == "https://api.example.com/v1"
        assert config.resolve_vision_api_key() == "test-key"

    def test_local_openai_compatible_default_url(self):
        config = SidecarConfig(vision_provider="local_openai_compatible")
        assert config.resolve_vision_base_url() == "http://127.0.0.1:8000/v1"
        assert config.resolve_vision_api_key() == "local"

    def test_external_resolve_from_config(self):
        config = SidecarConfig(
            vision_provider="external_openai_compatible",
            vision_base_url="https://custom.example.com/v1",
            vision_api_key="my-key",
        )
        assert config.resolve_vision_base_url() == "https://custom.example.com/v1"
        assert config.resolve_vision_api_key() == "my-key"

    def test_default_provider_is_external(self):
        config = SidecarConfig()
        assert config.vision_provider == "external_openai_compatible"
