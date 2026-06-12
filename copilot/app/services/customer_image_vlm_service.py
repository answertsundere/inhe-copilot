from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any

from openai import OpenAI

from app import config

logger = logging.getLogger(__name__)

CUSTOMER_IMAGE_SYSTEM_PROMPT = """你是 INHE 母婴儿童电商客服图片识别助手。
你只负责识别客户发来的图片内容，不生成客服回复，不承诺售后结果。
图片可能是：破损照片、少件/配件照片、安装照片、活动/价保截图、商品页面截图、物流截图、聊天截图或其他。

安全边界：
- 不能仅凭图片确认赔付、补发、退款、质量责任或安全结论。
- 看不清就说不确定，不要猜。
- 不识别身份证、手机号、详细地址等隐私；如看见隐私，只标记 privacy_risk=true。
- 涉及宝宝安全、材质、3C、食品级、受伤、误食等，必须 requires_human_review=true。

只输出严格 JSON：
{
  "success": true,
  "image_type": "damage_photo|missing_parts|installation_photo|promotion_screenshot|order_screenshot|product_page|logistics_screenshot|chat_screenshot|unknown",
  "issue_type": "damage|missing_parts|installation|promotion|price_protection|invoice|logistics|product_question|safety|unknown",
  "summary": "用中文简短描述图片可见内容",
  "visible_text": "图片中可见关键文字，若无则空",
  "detected_objects": ["可见物品/部件"],
  "evidence_points": ["图片中可作为客服核实依据的点"],
  "missing_info": ["还需要客户补充的信息"],
  "privacy_risk": false,
  "requires_human_review": true,
  "reason_for_review": "为什么需要人工复核",
  "confidence": 0.0,
  "warnings": []
}"""

CUSTOMER_IMAGE_USER_PROMPT = "请识别这张客户发来的图片，并按 JSON schema 输出。"


def analyze_customer_images(attachments: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Analyze image attachments with VLM when configured.

    Raw images are not persisted. Returned dicts intentionally contain only
    structured observations and short text summaries.
    """
    if not attachments:
        return []
    results: list[dict[str, Any]] = []
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        image_payload = _extract_image_payload(attachment)
        if not image_payload:
            results.append(_metadata_only_result(attachment, "no_image_payload"))
            continue
        if not _vlm_ready():
            results.append(_metadata_only_result(attachment, "vlm_not_configured"))
            continue
        results.append(_call_customer_image_vlm(image_payload, attachment))
    return results


def _vlm_ready() -> bool:
    return bool(
        config.COPILOT_VLM_ENABLED
        and config.COPILOT_VLM_API_BASE
        and config.COPILOT_VLM_API_KEY
        and config.COPILOT_VLM_MODEL
    )


def _extract_image_payload(attachment: dict[str, Any]) -> str:
    value = (
        attachment.get("data_url")
        or attachment.get("image_url")
        or attachment.get("url")
        or attachment.get("base64")
        or attachment.get("image_b64")
        or ""
    )
    if not value:
        return ""
    value = str(value).strip()
    if value.startswith("data:image/"):
        return value
    if re.match(r"^https?://", value):
        return value
    mime = attachment.get("mime_type") or attachment.get("mime") or "image/png"
    return f"data:{mime};base64,{value}"


def _call_customer_image_vlm(image_url: str, attachment: dict[str, Any]) -> dict[str, Any]:
    try:
        client = OpenAI(
            api_key=config.COPILOT_VLM_API_KEY,
            base_url=config.COPILOT_VLM_API_BASE,
        )
        response = client.chat.completions.create(
            model=config.COPILOT_VLM_MODEL,
            messages=[
                {"role": "system", "content": CUSTOMER_IMAGE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": CUSTOMER_IMAGE_USER_PROMPT},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                },
            ],
            temperature=0,
            max_tokens=1200,
            timeout=config.COPILOT_VLM_TIMEOUT_SECONDS,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or ""
        parsed = _parse_json(raw)
        return _normalize_vlm_result(parsed, attachment)
    except Exception as exc:
        logger.warning("customer image VLM failed: %s", exc)
        result = _metadata_only_result(attachment, "vlm_call_failed")
        result["error"] = str(exc)
        return result


def _parse_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start:end + 1]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {
            "success": False,
            "image_type": "unknown",
            "issue_type": "unknown",
            "summary": "",
            "visible_text": "",
            "warnings": ["vlm_response_parse_failed"],
            "error": "vlm_response_not_json",
        }


def _normalize_vlm_result(parsed: dict[str, Any], attachment: dict[str, Any]) -> dict[str, Any]:
    allowed_image_types = {
        "damage_photo", "missing_parts", "installation_photo", "promotion_screenshot",
        "order_screenshot", "product_page", "logistics_screenshot", "chat_screenshot",
        "unknown",
    }
    allowed_issue_types = {
        "damage", "missing_parts", "installation", "promotion", "price_protection",
        "invoice", "logistics", "product_question", "safety", "unknown",
    }
    image_type = str(parsed.get("image_type") or attachment.get("kind") or "unknown")
    issue_type = str(parsed.get("issue_type") or "unknown")
    if image_type not in allowed_image_types:
        image_type = "unknown"
    if issue_type not in allowed_issue_types:
        issue_type = "unknown"

    confidence = parsed.get("confidence", 0.0)
    try:
        confidence = max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        confidence = 0.0

    safety_review = issue_type == "safety" or bool(parsed.get("privacy_risk"))
    requires_review = bool(parsed.get("requires_human_review", True)) or safety_review

    return {
        "success": bool(parsed.get("success", True)),
        "source": "customer_image_vlm",
        "image_type": image_type,
        "issue_type": issue_type,
        "summary": str(parsed.get("summary") or ""),
        "visible_text": str(parsed.get("visible_text") or ""),
        "detected_objects": _string_list(parsed.get("detected_objects")),
        "evidence_points": _string_list(parsed.get("evidence_points")),
        "missing_info": _string_list(parsed.get("missing_info")),
        "privacy_risk": bool(parsed.get("privacy_risk", False)),
        "requires_human_review": requires_review,
        "reason_for_review": str(parsed.get("reason_for_review") or "客户图片需要结合订单/商品信息人工核实"),
        "confidence": confidence,
        "warnings": _string_list(parsed.get("warnings")),
    }


def _metadata_only_result(attachment: dict[str, Any], warning: str) -> dict[str, Any]:
    return {
        "success": False,
        "source": "customer_image_metadata",
        "image_type": str(attachment.get("kind") or attachment.get("type") or "unknown"),
        "issue_type": "unknown",
        "summary": str(
            attachment.get("description")
            or attachment.get("ocr_text")
            or attachment.get("note")
            or ""
        ),
        "visible_text": str(attachment.get("ocr_text") or ""),
        "detected_objects": [],
        "evidence_points": [],
        "missing_info": ["订单号", "商品/问题补充说明"],
        "privacy_risk": False,
        "requires_human_review": True,
        "reason_for_review": "客户图片未经过 VLM 或人工确认",
        "confidence": 0.0,
        "warnings": [warning],
    }


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]
