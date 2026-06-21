"""Renderer for validated answer blocks.

The renderer is deliberately narrow: it accepts customer-safe answer blocks and
formats them into one reply. It must not inspect raw evidence fields or invent
additional product facts.
"""

from __future__ import annotations

from typing import Any

from app.services.answer_blocks_service import validate_customer_text


def render_customer_answer(
    answer_blocks: list[dict[str, Any]],
    *,
    customer_message: str = "",
) -> dict[str, Any]:
    rendered_parts: list[str] = []
    skipped: list[dict[str, Any]] = []
    for block in answer_blocks or []:
        if not isinstance(block, dict) or not block.get("can_send_to_customer", True):
            skipped.append({"reason": "cannot_send_to_customer", "block": block})
            continue
        text = str(block.get("customer_text") or "").strip()
        issues = validate_customer_text(text)
        if issues:
            skipped.append({"reason": "invalid_customer_text", "issues": issues, "block": block})
            continue
        rendered_parts.append(text)

    if not rendered_parts:
        return {
            "passed": False,
            "renderer_used": False,
            "rendered_text": "",
            "skipped_blocks": skipped,
            "reason": "no_valid_answer_blocks",
        }

    body = _join_parts(rendered_parts)
    reply = body if body.startswith(("亲", "您好")) else f"亲亲，{body}"
    return {
        "passed": True,
        "renderer_used": True,
        "rendered_text": reply,
        "skipped_blocks": skipped,
        "block_count": len(rendered_parts),
    }


def controlled_fallback_reply(*, reason: str = "") -> str:
    if reason:
        return f"亲亲，这个点我需要再按页面和对应资料核对一下，避免说错影响您使用；我确认清楚后再给您准确答复。"
    return "亲亲，这个点我需要再按页面和对应资料核对一下，避免说错影响您使用。"


def _join_parts(parts: list[str]) -> str:
    cleaned = [part.strip() for part in parts if part and part.strip()]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return " ".join(cleaned)
    return "您这边问到的点我分开说明：\n" + "\n".join(
        f"{index}. {text}" for index, text in enumerate(cleaned, start=1)
    )
