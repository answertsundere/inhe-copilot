"""Shared semantic patterns for short, colloquial after-sales requests."""

from __future__ import annotations

import re


_MISSING_OBJECT = re.compile(
    r"(?:少(?:了|发)?|缺(?:了)?|没(?:有|收到)?|未收到|漏发)"
    r".{0,8}(?:这个|一个|配件|零件|螺丝|板子|板|工具|赠品)"
    r"|(?:配件|零件|螺丝|板子|板|工具|赠品).{0,6}(?:没有|没收到|少了|缺了)"
)
_REPLENISHMENT_REQUEST = re.compile(
    r"(?:能|可以|还能|可不可以)?.{0,4}"
    r"(?:补发|补一个|补一件|配一个|配(?:吗|不|嘛)|单独.{0,4}(?:给我|来|发)|重新发)"
)
_DAMAGED_EXCHANGE = re.compile(
    r"(?:坏了|破了|裂了|断了|损坏|变形).{0,10}(?:换|补|重新发|怎么办|咋办)?"
)
_WRONG_ITEM = re.compile(r"(?:发错|错发|发的不是|不是我拍的).{0,10}(?:换|重新发|补发|怎么办|咋办)?")


def classify_colloquial_aftersales(text: str) -> dict:
    """Return a narrow after-sales subtype without treating generic product talk as after-sales."""
    normalized = re.sub(r"\s+", "", str(text or ""))
    if not normalized:
        return {}
    if _WRONG_ITEM.search(normalized):
        return {"matched": True, "subtype": "wrong_item", "reason": "wrong_item_semantic_pattern"}
    if _DAMAGED_EXCHANGE.search(normalized):
        return {"matched": True, "subtype": "damaged_item", "reason": "damage_exchange_semantic_pattern"}
    if _MISSING_OBJECT.search(normalized):
        return {"matched": True, "subtype": "missing_item", "reason": "missing_object_semantic_pattern"}
    if _REPLENISHMENT_REQUEST.search(normalized):
        return {"matched": True, "subtype": "replacement_request", "reason": "replenishment_semantic_pattern"}
    return {}
