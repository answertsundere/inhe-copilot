from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from .config import SidecarConfig

logger = logging.getLogger(__name__)


@dataclass
class WindowCandidate:
    hwnd: int
    title: str
    class_name: str
    visible: bool
    minimized: bool
    score: int
    match_reason: str


@dataclass
class WindowSelection:
    selected_hwnd: int
    selected_title: str
    selected_reason: str
    candidate_windows: list[WindowCandidate]


def _score_window(title: str, visible: bool, minimized: bool, priority_keywords: list[str]) -> tuple[int, str]:
    score = 0
    reason = ""

    if not visible:
        return 0, "not_visible"

    # Score by keyword specificity: earlier keywords get much higher scores
    base_scores = {
        "接待中心": 200,
        "旺旺": 180,
        "接待台": 170,
        "聊天": 160,
    }

    for keyword in priority_keywords:
        if keyword in title:
            score = base_scores.get(keyword, 80)
            reason = f"title_contains_{keyword}"
            break

    # Extra penalty for generic "千牛" or "千牛工作台" when title is clearly not a Qianniu app window
    if score <= 80:
        # Check if title looks like a real Qianniu window (shop:staff-pattern)
        has_shop_pattern = (":" in title and "-" in title) or "阿里旺旺" in title
        if not has_shop_pattern:
            score = max(score - 60, 0)  # Likely a terminal/editor window mentioning 千牛

    if "工作台" in title and "接待中心" not in title and "接待台" not in title:
        score -= 30

    if minimized and score > 0:
        score -= 40

    return max(score, 0), reason or "keyword_match"


def find_all_candidates(config: SidecarConfig | None = None) -> list[WindowCandidate]:
    if config is None:
        config = SidecarConfig()

    try:
        import win32gui
    except Exception as exc:
        logger.warning("win32gui unavailable: %s", exc)
        return []

    candidates: list[WindowCandidate] = []

    def enum_handler(hwnd: int, _) -> None:
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return
            title = (win32gui.GetWindowText(hwnd) or "").strip()
            if not title:
                return
            class_name: str = ""
            try:
                class_name = win32gui.GetClassName(hwnd) or ""
            except Exception:
                pass

            if not any(kw in title for kw in config.window_find_keywords):
                return

            is_minimized = bool(win32gui.IsIconic(hwnd))
            score, reason = _score_window(title, True, is_minimized, config.window_title_priority)

            candidates.append(WindowCandidate(
                hwnd=hwnd,
                title=title,
                class_name=class_name,
                visible=True,
                minimized=is_minimized,
                score=score,
                match_reason=reason,
            ))
        except Exception:
            return

    try:
        win32gui.EnumWindows(enum_handler, None)
    except Exception as exc:
        logger.warning("EnumWindows failed: %s", exc)

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates


def select_window(config: SidecarConfig | None = None) -> WindowSelection | None:
    config = config or SidecarConfig()
    candidates = find_all_candidates(config)

    if not candidates:
        logger.info("no qianniu windows found")
        return None

    best = candidates[0]
    if best.score == 0:
        logger.info("all candidate windows have score 0, none suitable")
        return None

    logger.info(
        "selected window hwnd=%s title=%s reason=%s score=%s",
        best.hwnd, best.title, best.match_reason, best.score,
    )

    return WindowSelection(
        selected_hwnd=best.hwnd,
        selected_title=best.title,
        selected_reason=best.match_reason,
        candidate_windows=candidates,
    )


def attach_uia_window(hwnd: int) -> Any | None:
    try:
        from pywinauto import Desktop
    except Exception as exc:
        logger.warning("pywinauto unavailable: %s", exc)
        return None

    try:
        return Desktop(backend="uia").window(handle=hwnd)
    except Exception as exc:
        logger.warning("attach window hwnd=%s failed: %s", hwnd, exc)
        return None
