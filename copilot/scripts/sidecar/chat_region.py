from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import SidecarConfig


@dataclass
class ChatRegion:
    left_ratio: float
    top_ratio: float
    right_ratio: float
    bottom_ratio: float

    def to_pixels(self, window_width: int, window_height: int) -> tuple[int, int, int, int]:
        left = int(window_width * self.left_ratio)
        top = int(window_height * self.top_ratio)
        right = int(window_width * self.right_ratio)
        bottom = int(window_height * self.bottom_ratio)
        return left, top, right, bottom


def load_chat_region(config: SidecarConfig | None = None) -> ChatRegion:
    config = config or SidecarConfig()
    region = config.chat_region
    return ChatRegion(
        left_ratio=region.get("left_ratio", 0.18),
        top_ratio=region.get("top_ratio", 0.08),
        right_ratio=region.get("right_ratio", 0.72),
        bottom_ratio=region.get("bottom_ratio", 0.88),
    )
