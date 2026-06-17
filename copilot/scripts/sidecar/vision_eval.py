from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .privacy_filter import redact_all

logger = logging.getLogger(__name__)


@dataclass
class VisionEvalRecord:
    model_name: str
    provider: str
    image_size_bytes: int = 0
    image_width: int = 0
    image_height: int = 0
    duration_ms: int = 0
    confidence: float = 0.0
    latest_customer_message: str = ""
    latest_agent_message: str = ""
    messages_count: int = 0
    role_parse_success: bool = False
    json_parse_success: bool = False
    needs_manual_confirm: bool = True
    order_candidates_count: int = 0
    tracking_candidates_count: int = 0
    product_candidates_count: int = 0
    warnings: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_name": self.model_name,
            "provider": self.provider,
            "image_size_bytes": self.image_size_bytes,
            "image_width": self.image_width,
            "image_height": self.image_height,
            "duration_ms": self.duration_ms,
            "confidence": self.confidence,
            "latest_customer_message": redact_all(self.latest_customer_message),
            "latest_agent_message": redact_all(self.latest_agent_message),
            "messages_count": self.messages_count,
            "role_parse_success": self.role_parse_success,
            "json_parse_success": self.json_parse_success,
            "needs_manual_confirm": self.needs_manual_confirm,
            "order_candidates_count": self.order_candidates_count,
            "tracking_candidates_count": self.tracking_candidates_count,
            "product_candidates_count": self.product_candidates_count,
            "warnings": self.warnings,
            "error": self.error,
        }


def append_eval_record(record: VisionEvalRecord, log_path: str) -> None:
    if not log_path:
        return
    try:
        path = Path(log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record.to_dict(), ensure_ascii=False)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        logger.info("vision eval record appended to %s", log_path)
    except Exception as exc:
        logger.warning("failed to append vision eval record: %s", exc)


class VisionEvalTimer:
    def __init__(self) -> None:
        self._start = 0.0

    def start(self) -> None:
        self._start = time.monotonic()

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self._start) * 1000)
