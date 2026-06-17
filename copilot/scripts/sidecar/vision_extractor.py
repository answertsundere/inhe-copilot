from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from typing import Any

from .chat_region import ChatRegion, load_chat_region
from .config import SidecarConfig
from .screen_capture import ScreenCaptureResult, capture_chat_region
from .vlm_client import call_vlm

MAX_IMAGE_DIMENSION = 800

logger = logging.getLogger(__name__)


@dataclass
class VisionCandidateItem:
    value: str
    source: str
    confidence: float
    verified: bool = False
    type: str = ""


@dataclass
class VisionMessage:
    role: str
    text: str
    time: str
    confidence: float


@dataclass
class VisionExtractResult:
    success: bool
    extract_method: str = "vision_vlm"
    confidence: float = 0.0
    messages: list[VisionMessage] = field(default_factory=list)
    latest_customer_message: str = ""
    latest_agent_message: str = ""
    order_candidates: list[VisionCandidateItem] = field(default_factory=list)
    tracking_candidates: list[VisionCandidateItem] = field(default_factory=list)
    product_candidates: list[VisionCandidateItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    needs_manual_confirm: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "extract_method": self.extract_method,
            "confidence": self.confidence,
            "messages": [
                {"role": m.role, "text": m.text, "time": m.time, "confidence": m.confidence}
                for m in self.messages
            ],
            "latest_customer_message": self.latest_customer_message,
            "latest_agent_message": self.latest_agent_message,
            "order_candidates": [self._cand_dict(c) for c in self.order_candidates],
            "tracking_candidates": [self._cand_dict(c) for c in self.tracking_candidates],
            "product_candidates": [self._cand_dict(c) for c in self.product_candidates],
            "warnings": self.warnings,
            "needs_manual_confirm": self.needs_manual_confirm,
        }

    @staticmethod
    def _cand_dict(item: VisionCandidateItem) -> dict[str, Any]:
        d = {
            "value": item.value,
            "source": item.source,
            "confidence": item.confidence,
            "verified": item.verified,
        }
        if item.type:
            d["type"] = item.type
        return d


def extract_chat_from_vision(
    hwnd: int,
    config: SidecarConfig | None = None,
) -> VisionExtractResult:
    config = config or SidecarConfig()
    result = VisionExtractResult(success=False)

    if not config.enable_vision_extractor:
        result.warnings.append("vision_extractor_disabled")
        return result

    chat_region = load_chat_region(config)
    capture = capture_chat_region(hwnd, chat_region, config)

    if not capture.success:
        result.warnings.append(f"capture_failed: {capture.error_code}")
        result.warnings.append(capture.message)
        logger.info("vision capture failed: %s", capture.error_code)
        return result

    if capture.image_data is None:
        result.warnings.append("no_image_data")
        return result

    # Resize large images to reduce VLM token cost and latency
    image_data = _compress_image(capture.image_data)

    vlm_response = call_vlm(image_data, config)

    if not vlm_response.get("success"):
        result.warnings.extend(vlm_response.get("warnings", []))
        error = vlm_response.get("error", "unknown")
        result.warnings.append(f"vlm_error: {error}")
        logger.info("VLM call failed: %s", error)
        return result

    result.success = True
    result.confidence = vlm_response.get("overall_confidence", 0.0)

    for msg_data in vlm_response.get("messages", []):
        result.messages.append(VisionMessage(
            role=msg_data.get("role", "unknown"),
            text=msg_data.get("text", ""),
            time=msg_data.get("time", ""),
            confidence=msg_data.get("confidence", 0.0),
        ))

    result.latest_customer_message = vlm_response.get("latest_customer_message", "")
    result.latest_agent_message = vlm_response.get("latest_agent_message", "")
    _repair_message_roles_and_latest(result)

    for cand in vlm_response.get("order_candidates", []):
        result.order_candidates.append(VisionCandidateItem(
            value=cand.get("value", ""),
            source="vision",
            confidence=cand.get("confidence", 0.0),
            verified=False,
            type=cand.get("type", ""),
        ))

    for cand in vlm_response.get("tracking_candidates", []):
        result.tracking_candidates.append(VisionCandidateItem(
            value=cand.get("value", ""),
            source="vision",
            confidence=cand.get("confidence", 0.0),
            verified=False,
            type=cand.get("type", ""),
        ))

    for cand in vlm_response.get("product_candidates", []):
        result.product_candidates.append(VisionCandidateItem(
            value=cand.get("value", ""),
            source="vision",
            confidence=cand.get("confidence", 0.0),
            type=cand.get("type", ""),
        ))

    result.warnings.extend(vlm_response.get("warnings", []))

    if result.confidence < config.vision_min_confidence:
        result.needs_manual_confirm = True
        result.warnings.append(f"low_confidence: {result.confidence:.2f} < {config.vision_min_confidence}")

    if config.vision_require_confirm:
        result.needs_manual_confirm = True

    logger.info(
        "vision extracted: messages=%d customer=%r confidence=%.2f confirm=%s",
        len(result.messages), result.latest_customer_message[:50],
        result.confidence, result.needs_manual_confirm,
    )

    return result


def _repair_message_roles_and_latest(result: VisionExtractResult) -> None:
    """Keep the sidecar useful when the VLM confuses left buyer bubbles with agent."""
    chat_messages = [
        msg for msg in result.messages
        if msg.text.strip() and msg.role in {"customer", "agent", "unknown"}
    ]
    if not chat_messages:
        return

    customer_messages = [msg for msg in chat_messages if msg.role == "customer"]
    if customer_messages and not result.latest_customer_message.strip():
        result.latest_customer_message = customer_messages[-1].text.strip()

    agent_messages = [msg for msg in chat_messages if msg.role == "agent"]
    if agent_messages and not result.latest_agent_message.strip():
        result.latest_agent_message = agent_messages[-1].text.strip()

    if result.latest_customer_message.strip():
        return

    # 千牛接待区截图经常只有左侧买家连续追问；部分 VLM 会把这些全部标成 agent。
    # 这种情况下把所有非 system 可见气泡降级为 customer，保证后端拿到完整上下文。
    if not customer_messages and chat_messages:
        for msg in chat_messages:
            msg.role = "customer"
        result.latest_customer_message = chat_messages[-1].text.strip()
        result.latest_agent_message = ""
        result.warnings.append("vision_role_repaired_all_chat_as_customer")


def _compress_image(image_data: bytes, max_dim: int = MAX_IMAGE_DIMENSION) -> bytes:
    try:
        from PIL import Image
    except ImportError:
        return image_data

    try:
        img = Image.open(io.BytesIO(image_data))
        w, h = img.size
        if max(w, h) <= max_dim:
            return image_data

        ratio = max_dim / max(w, h)
        new_w = int(w * ratio)
        new_h = int(h * ratio)
        img = img.resize((new_w, new_h), Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        compressed = buf.getvalue()
        logger.info("image compressed: %dx%d -> %dx%d, %dKB -> %dKB",
                     w, h, new_w, new_h, len(image_data) // 1024, len(compressed) // 1024)
        return compressed
    except Exception as exc:
        logger.warning("image compression failed: %s", exc)
        return image_data
