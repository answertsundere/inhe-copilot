from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from .config import SidecarConfig

logger = logging.getLogger(__name__)

TRACKING_PATTERNS = [
    (r"\b(SF\d{12,15})\b", "顺丰速运"),
    (r"\b(YT\d{13,16})\b", "圆通速递"),
    (r"\b(ZTO\d{10,14})\b", "中通快递"),
    (r"\b(STO\d{10,14})\b", "申通快递"),
    (r"\b(YD\d{13,16})\b", "韵达快递"),
    (r"\b(JD\d{10,15})\b", "京东物流"),
    (r"\b(EMS[A-Za-z0-9]{9,13})\b", "EMS"),
    (r"\b([A-Za-z]{2}\d{9}[A-Za-z]{2})\b", "国际快递"),
]

ORDER_PATTERNS = [
    r"\b(\d{18,22})\b",
    r"\b(\d{15,17})\b",
]

PLATFORM_TRADE_ID_PATTERNS = [
    r"\b(\d{18,22})\b",
]

INTERNAL_PRODUCT_CODE_RE = re.compile(r"\b(YH[A-Za-z0-9_-]{4,40})\b", re.IGNORECASE)
PRODUCT_CARD_RE = re.compile(
    r"\bID\s*(\d{6,})\s+(.{4,160}?)(?:[￥¥]\s*\d|库存|销量|SKU|属性|邀请下单|优惠计算|收藏)",
    re.IGNORECASE | re.DOTALL,
)
LABEL_VALUE_RE = re.compile(
    r"(商品编码|商家编码|商品编号|产品编码|款号|SKU|sku_id|i_id|商品ID|宝贝ID|ID)\s*[:：]?\s*([A-Za-z0-9_-]{4,40})",
    re.IGNORECASE,
)


@dataclass
class CandidateItem:
    value: str
    type: str
    source: str
    confidence: float
    verified: bool = False
    carrier: str = ""


@dataclass
class UIASidebarResult:
    extract_method: str = "uia_sidebar"
    success: bool = False
    controls_count: int = 0
    text_count: int = 0
    order_candidates: list[CandidateItem] = field(default_factory=list)
    tracking_candidates: list[CandidateItem] = field(default_factory=list)
    product_candidates: list[CandidateItem] = field(default_factory=list)
    sidebar_text_redacted: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "extract_method": self.extract_method,
            "success": self.success,
            "controls_count": self.controls_count,
            "text_count": self.text_count,
            "order_candidates": [self._item_dict(c) for c in self.order_candidates],
            "tracking_candidates": [self._item_dict(c) for c in self.tracking_candidates],
            "product_candidates": [self._item_dict(c) for c in self.product_candidates],
            "sidebar_text_redacted": self.sidebar_text_redacted[:500],
            "warnings": self.warnings,
        }

    @staticmethod
    def _item_dict(item: CandidateItem) -> dict[str, Any]:
        d: dict[str, Any] = {
            "value": item.value,
            "type": item.type,
            "source": item.source,
            "confidence": item.confidence,
            "verified": item.verified,
        }
        if item.carrier:
            d["carrier"] = item.carrier
        return d


CARRIER_KEYWORDS_MAP = {
    "顺丰": "顺丰速运", "圆通": "圆通速递", "中通": "中通快递",
    "申通": "申通快递", "韵达": "韵达快递", "京东": "京东物流",
    "EMS": "EMS", "邮政": "中国邮政", "极兔": "极兔速递",
    "百世": "百世快递", "天天": "天天快递", "德邦": "德邦快递",
    "宅急送": "宅急送", "丰巢": "丰巢",
}


def _extract_carrier_from_context(text_lines: list[str], tracking_value: str) -> str:
    for line in text_lines:
        if tracking_value in line:
            for keyword, carrier in CARRIER_KEYWORDS_MAP.items():
                if keyword in line:
                    return carrier
    return ""


def _extract_tracking_candidates(text: str, all_lines: list[str]) -> list[CandidateItem]:
    candidates: list[CandidateItem] = []
    seen: set[str] = set()

    # Combined pattern: carrier,tracking_number
    combined_pattern = r"(?:顺丰速运|圆通速递|中通快递|申通快递|韵达快递|京东物流|极兔速递|百世快递|德邦快递)[,，]\s*([A-Za-z0-9]{10,20})"
    for match in re.finditer(combined_pattern, text):
        val = match.group(1)
        if val not in seen:
            carrier = _extract_carrier_from_context(all_lines, val)
            candidates.append(CandidateItem(
                value=val, type="tracking_no_candidate",
                source="uia_sidebar", confidence=0.99, carrier=carrier,
            ))
            seen.add(val)

    for pattern, default_carrier in TRACKING_PATTERNS:
        for match in re.finditer(pattern, text):
            val = match.group(1)
            if val not in seen:
                carrier = _extract_carrier_from_context(all_lines, val) or default_carrier
                candidates.append(CandidateItem(
                    value=val, type="tracking_no_candidate",
                    source="uia_sidebar", confidence=0.99, carrier=carrier,
                ))
                seen.add(val)

    return candidates


def _extract_order_candidates(text: str) -> list[CandidateItem]:
    candidates: list[CandidateItem] = []
    seen: set[str] = set()

    for pattern in PLATFORM_TRADE_ID_PATTERNS:
        for match in re.finditer(pattern, text):
            val = match.group(1)
            if val not in seen:
                candidates.append(CandidateItem(
                    value=val, type="platform_trade_id_candidate",
                    source="uia_sidebar", confidence=0.95,
                ))
                seen.add(val)
                break
        if candidates:
            break

    return candidates


def _extract_product_candidates(text: str) -> list[CandidateItem]:
    candidates: list[CandidateItem] = []
    seen: set[tuple[str, str]] = set()
    lines = text.splitlines()

    compact_text = re.sub(r"\s+", " ", text or "").strip()
    for product_id, title in PRODUCT_CARD_RE.findall(compact_text):
        clean_title = _clean_product_title(title)
        for cand_type, value, confidence in (
            ("platform_product_id_candidate", product_id, 0.7),
            ("product_candidate", clean_title, 0.92),
        ):
            if not value:
                continue
            key = (cand_type, value)
            if key not in seen:
                candidates.append(CandidateItem(
                    value=value,
                    type=cand_type,
                    source="uia_sidebar",
                    confidence=confidence,
                    verified=False,
                ))
                seen.add(key)

    for line in lines:
        stripped = line.strip()
        for label, value in LABEL_VALUE_RE.findall(stripped):
            label_lower = label.lower()
            cand_type = "platform_product_id_candidate"
            confidence = 0.7
            if label_lower in ("sku", "sku_id", "商家编码", "商品编码", "商品编号", "产品编码"):
                cand_type = "sku_id_candidate"
                confidence = 0.96
            elif label_lower in ("i_id", "款号"):
                cand_type = "i_id_candidate"
                confidence = 0.95
            key = (cand_type, value)
            if key not in seen:
                candidates.append(CandidateItem(
                    value=value,
                    type=cand_type,
                    source="uia_sidebar",
                    confidence=confidence,
                    verified=cand_type in ("sku_id_candidate", "i_id_candidate"),
                ))
                seen.add(key)

        for match in INTERNAL_PRODUCT_CODE_RE.finditer(stripped):
            value = match.group(1)
            cand_type = "sku_id_candidate" if re.search(r"B\d|S\d", value, re.IGNORECASE) else "i_id_candidate"
            key = (cand_type, value)
            if key not in seen:
                candidates.append(CandidateItem(
                    value=value,
                    type=cand_type,
                    source="uia_sidebar",
                    confidence=0.94,
                    verified=True,
                ))
                seen.add(key)

        if any(kw in stripped for kw in ("咨询宝贝", "发送宝贝")):
            product_text = stripped
            for kw in ("咨询宝贝", "发送宝贝"):
                product_text = product_text.replace(kw, "").strip()
            key = ("product_candidate", product_text)
            if product_text and not _is_bad_product_candidate(product_text) and key not in seen:
                candidates.append(CandidateItem(
                    value=product_text, type="product_candidate",
                    source="uia_sidebar", confidence=0.6,
                ))
                seen.add(key)
            break

    return candidates


def _clean_product_title(title: str) -> str:
    title = re.sub(r"\s+", " ", title or "").strip(" -:：|")
    title = re.sub(r"^(咨询宝贝|发送宝贝|宝贝|商品)\s*", "", title).strip()
    return title[:120].strip()


def _is_bad_product_candidate(value: str) -> bool:
    value = (value or "").strip()
    if not value:
        return True
    if re.fullmatch(r"\(?\d+\)?", value):
        return True
    if len(value) < 3:
        return True
    return False


def read_uia_controls(window: Any, config: SidecarConfig | None = None) -> list[str]:
    config = config or SidecarConfig()
    texts: list[str] = []

    try:
        controls = window.descendants(control_type="Text")
    except Exception as exc:
        logger.warning("read text descendants failed: %s", exc)
        controls = []

    for control in controls[:config.uia_max_items]:
        for getter in (lambda c: (c.window_text() or "").strip(),
                       lambda c: (c.element_info.name or "").strip()):
            try:
                text = getter(control)
            except Exception:
                continue
            if text and len(text) <= config.uia_max_text_length and text not in texts:
                texts.append(text)

    if not texts:
        try:
            controls = window.descendants()
        except Exception as exc:
            logger.warning("read all descendants failed: %s", exc)
            controls = []
        for control in controls[:config.uia_max_items]:
            try:
                text = (control.window_text() or "").strip()
            except Exception:
                continue
            if text and len(text) <= config.uia_max_text_length and text not in texts:
                texts.append(text)

    return texts


def extract_sidebar(window: Any, config: SidecarConfig | None = None) -> UIASidebarResult:
    config = config or SidecarConfig()
    result = UIASidebarResult()

    if window is None:
        result.warnings.append("window is None")
        return result

    try:
        text_lines = read_uia_controls(window, config)
        result.controls_count = len(text_lines)
        result.text_count = len(text_lines)
    except Exception as exc:
        logger.warning("UIA extraction failed: %s", exc)
        result.warnings.append(f"uia_error: {exc}")
        return result

    full_text = "\n".join(text_lines)

    result.tracking_candidates = _extract_tracking_candidates(full_text, text_lines)
    result.order_candidates = _extract_order_candidates(full_text)
    result.product_candidates = _extract_product_candidates(full_text)
    result.sidebar_text_redacted = full_text[:500]
    result.success = True

    logger.info(
        "uia_sidebar extracted: controls=%d tracking=%d orders=%d products=%d",
        result.controls_count,
        len(result.tracking_candidates),
        len(result.order_candidates),
        len(result.product_candidates),
    )

    return result
