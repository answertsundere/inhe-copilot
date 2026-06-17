from __future__ import annotations

import base64
import json
import logging
from typing import Any

from .config import SidecarConfig
from .text_repair import repair_mojibake_obj
from .vision_eval import VisionEvalRecord, VisionEvalTimer, append_eval_record
from .vision_prompt import VISION_MOCK_RESPONSE, VISION_SYSTEM_PROMPT, VISION_USER_PROMPT_TEMPLATE

logger = logging.getLogger(__name__)


def call_vlm(
    image_data: bytes,
    config: SidecarConfig | None = None,
) -> dict[str, Any]:
    config = config or SidecarConfig()
    timer = VisionEvalTimer()
    timer.start()

    eval_record = VisionEvalRecord(
        model_name=config.vision_model,
        provider=config.vision_provider,
        image_size_bytes=len(image_data) if image_data else 0,
    )

    if config.vision_provider == "mock":
        logger.info("VLM provider=mock, returning mock response")
        eval_record.duration_ms = timer.elapsed_ms()
        eval_record.json_parse_success = True
        eval_record.role_parse_success = True
        eval_record.confidence = VISION_MOCK_RESPONSE.get("overall_confidence", 0.9)
        eval_record.latest_customer_message = VISION_MOCK_RESPONSE.get("latest_customer_message", "")
        eval_record.latest_agent_message = VISION_MOCK_RESPONSE.get("latest_agent_message", "")
        eval_record.messages_count = len(VISION_MOCK_RESPONSE.get("messages", []))
        append_eval_record(eval_record, config.vision_eval_log)
        return VISION_MOCK_RESPONSE

    image_b64 = base64.b64encode(image_data).decode("ascii")

    if config.vision_provider in ("external_openai_compatible", "local_openai_compatible", "dashscope", "mimo", "custom"):
        result = _call_openai_compatible(image_b64, config)
    else:
        logger.warning("unknown vision_provider=%s, falling back to mock", config.vision_provider)
        eval_record.duration_ms = timer.elapsed_ms()
        eval_record.error = f"unknown_provider_{config.vision_provider}"
        append_eval_record(eval_record, config.vision_eval_log)
        return VISION_MOCK_RESPONSE

    eval_record.duration_ms = timer.elapsed_ms()
    eval_record.confidence = result.get("overall_confidence", 0.0)
    eval_record.latest_customer_message = result.get("latest_customer_message", "")
    eval_record.latest_agent_message = result.get("latest_agent_message", "")
    eval_record.messages_count = len(result.get("messages", []))
    eval_record.json_parse_success = result.get("success", False)
    eval_record.role_parse_success = bool(result.get("latest_customer_message"))
    eval_record.order_candidates_count = len(result.get("order_candidates", []))
    eval_record.tracking_candidates_count = len(result.get("tracking_candidates", []))
    eval_record.product_candidates_count = len(result.get("product_candidates", []))
    eval_record.warnings = result.get("warnings", [])
    if not result.get("success"):
        eval_record.error = result.get("error", "unknown")

    append_eval_record(eval_record, config.vision_eval_log)
    return result


def _call_openai_compatible(image_b64: str, config: SidecarConfig) -> dict[str, Any]:
    try:
        from openai import OpenAI
    except ImportError:
        logger.warning("openai package not available")
        return _make_error_response("openai package not installed")

    base_url = config.resolve_vision_base_url()
    api_key = config.resolve_vision_api_key()

    if not base_url:
        return _make_error_response(f"vision_base_url not configured for provider={config.vision_provider}")
    if not api_key:
        return _make_error_response(f"vision_api_key not configured for provider={config.vision_provider}")

    try:
        client = OpenAI(base_url=base_url, api_key=api_key)
        response = client.chat.completions.create(
            model=config.vision_model,
            messages=[
                {"role": "system", "content": VISION_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": VISION_USER_PROMPT_TEMPLATE},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                        },
                    ],
                },
            ],
            max_tokens=4096,
            timeout=config.vision_timeout_seconds,
        )
        raw_text = response.choices[0].message.content or ""
        return _parse_vlm_response(raw_text)
    except Exception as exc:
        logger.warning("VLM call failed (provider=%s): %s", config.vision_provider, exc)
        return _make_error_response(str(exc))


def _make_error_response(error: str) -> dict[str, Any]:
    return {
        "success": False,
        "error": error,
        "messages": [],
        "latest_customer_message": "",
        "latest_agent_message": "",
        "order_candidates": [],
        "tracking_candidates": [],
        "product_candidates": [],
        "warnings": [],
        "overall_confidence": 0.0,
    }


def _parse_vlm_response(raw_text: str) -> dict[str, Any]:
    text = raw_text.strip()

    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("VLM returned non-JSON: %s", text[:200])
        return {
            "success": False,
            "error": "vlm_response_not_json",
            "raw_text": text[:500],
            "messages": [],
            "latest_customer_message": "",
            "latest_agent_message": "",
            "order_candidates": [],
            "tracking_candidates": [],
            "product_candidates": [],
            "warnings": ["vlm_response_parse_failed"],
            "overall_confidence": 0.0,
        }

    parsed.setdefault("success", True)
    parsed.setdefault("messages", [])
    parsed.setdefault("latest_customer_message", "")
    parsed.setdefault("latest_agent_message", "")
    parsed.setdefault("order_candidates", [])
    parsed.setdefault("tracking_candidates", [])
    parsed.setdefault("product_candidates", [])
    parsed.setdefault("warnings", [])
    parsed.setdefault("overall_confidence", 0.0)

    return repair_mojibake_obj(parsed)
