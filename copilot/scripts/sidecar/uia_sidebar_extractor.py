from __future__ import annotations

import logging
import hashlib
import hmac
import secrets
import re
import unicodedata
from datetime import datetime
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


# Native accessibility metadata only. Message text never determines a speaker.
_NATIVE_TIMESTAMP = re.compile(r"\d{4}-\d{1,2}-\d{1,2} \d{1,2}:\d{2}:\d{2}")


def _subtree_end(nodes: list[dict], start: int) -> int:
    return next((i for i in range(start + 1, len(nodes))
                 if nodes[i]["depth"] <= nodes[start]["depth"]), len(nodes))


def _native_header(nodes: list[dict], index: int) -> tuple[str, str]:
    children = nodes[index + 1:_subtree_end(nodes, index)]
    texts = [n["name"].strip() for n in children if n["role"] == "Text"]
    times = [value for value in texts if _NATIVE_TIMESTAMP.fullmatch(value)]
    speakers = [value for value in texts if value not in times]
    if len(times) != 1 or len(speakers) != 1:
        raise ValueError("header_structure_invalid")
    try:
        timestamp = datetime.strptime(times[0], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        raise ValueError("header_structure_invalid") from None
    return speakers[0], timestamp.isoformat(sep=" ")


def _native_parts(nodes: list[dict]) -> list[dict]:
    parts: list[dict] = []
    i = 0
    while i < len(nodes):
        root = nodes[i]
        end = _subtree_end(nodes, i)
        children = nodes[i + 1:end]
        role, name = root["role"], root["name"].strip()
        if role == "Main":
            media = {"图片消息": "image", "视频消息": "video"}.get(name)
            if not media:
                raise ValueError("message_part_type_unknown")
            parts.append({"type": media})
        elif role == "Hyperlink":
            parts.append({"type": "link"})
        elif role == "Image":
            parts.append({"type": "image"})
        elif role == "Group":
            # Containers may repeat their leaf text. Read the subtree once,
            # but never deduplicate equal text from different messages.
            if children:
                leaves = _native_parts(children)
                parts.extend(leaves)
            elif name and not _native_icon(name):
                parts.append({"type": "text", "content": name})
        elif role == "Text" and name:
            if not _native_icon(name):
                parts.append({"type": "text", "content": name})
        elif role not in {"Text"}:
            raise ValueError("message_part_type_unknown")
        i = end
    return parts


def _native_icon(name: str) -> bool:
    return bool(name.strip()) and all(ch.isspace() or unicodedata.category(ch) == "Co" for ch in name)


def build_native_preview(before: list[dict], after: list[dict], hwnd: int, *, mode: str = "native_selection") -> dict[str, Any]:
    """Project a bounded native document into the existing local preview contract.

    The document peer is cross-checked against the native buyer list and shop
    tab, not claimed to be a new inbound-message event. The seat must confirm it.
    No input text, actor, order or product is logged or persisted here.
    """
    from .context_parser import build_uia_preview

    try:
        if mode not in ("native_selection", "manual_document_review"):
            raise ValueError("capture_mode_invalid")
        assisted = mode == "manual_document_review"
        # Diagnostic availability is not current-client ownership metadata.
        before_binding = [{k: v for k, v in n.items() if k != "selection_diagnostics"} for n in before]
        after_binding = [{k: v for k, v in n.items() if k != "selection_diagnostics"} for n in after]
        if before_binding != after_binding:
            raise ValueError("capture_binding_changed")
        nodes = before
        containers = [i for i, n in enumerate(nodes) if n.get("automation_id") == "J_msgContainer"]
        if not containers:
            raise ValueError("conversation_document_missing")
        if len(containers) != 1:
            raise ValueError("conversation_document_ambiguous")
        start = containers[0]
        end = _subtree_end(nodes, start)
        indices = [i for i in range(start + 1, end) if nodes[i]["role"] == "Heading"]
        if not indices:
            raise ValueError("message_count_invalid")
        headers = [_native_header(nodes, i) for i in indices]
        incoming = [speaker.split(" --> ") for speaker, _ in headers if " --> " in speaker]
        if not incoming or any(len(pair) != 2 for pair in incoming):
            raise ValueError("speaker_unresolved")
        buyers = {pair[0].strip() for pair in incoming}
        if len(buyers) != 1:
            raise ValueError("buyer_binding_missing")
        buyer = next(iter(buyers))
        outside = nodes[:start] + nodes[end:]
        if assisted and any(n["role"] == "TreeItem" and n.get("legacy_selected") is True
                            and n["name"].strip() != buyer for n in outside):
            raise ValueError("buyer_binding_missing")
        selected_buyers = [n for n in outside if n["role"] == "TreeItem" and n.get("selected") is True]
        if ((selected_buyers or not assisted)
                and (len(selected_buyers) != 1 or selected_buyers[0]["name"].strip() != buyer)):
            raise ValueError("buyer_binding_missing")
        shops = {pair[1].strip().partition(":")[0] for pair in incoming if ":" in pair[1]}
        if len(shops) != 1 or any(":" not in pair[1] for pair in incoming):
            raise ValueError("shop_binding_missing")
        shop = next(iter(shops))
        if assisted and any(n["role"] == "TabItem" and n.get("legacy_selected") is True
                            and ":" in n["name"] and n["name"].strip().partition(":")[0] != shop
                            for n in outside):
            raise ValueError("shop_binding_missing")
        selected_shops = [n for n in outside if n["role"] == "TabItem" and n.get("selected") is True]
        matching_shop = any(n["name"].strip().partition(":")[0] == shop and ":" in n["name"]
                            for n in selected_shops)
        conflicting_shop = any(":" in n["name"] and n["name"].strip().partition(":")[0] != shop
                               for n in selected_shops)
        if not shop or ((selected_shops or not assisted) and not matching_shop) or (assisted and conflicting_shop):
            raise ValueError("shop_binding_missing")
        key = secrets.token_bytes(32)

        def ref(value: str) -> str:
            return "native_" + hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()

        agents: set[str] = set()
        messages = []
        for position, index in enumerate(indices):
            speaker, timestamp = headers[position]
            if " --> " in speaker:
                sender, recipient = (value.strip() for value in speaker.split(" --> "))
                agent = recipient
            else:
                sender, recipient, agent = speaker.strip(), buyer, speaker.strip()
            if agent.partition(":")[0] != shop or not agent.partition(":")[2]:
                raise ValueError("speaker_unresolved")
            agents.add(ref(agent))
            stop = indices[position + 1] if position + 1 < len(indices) else end
            body = nodes[_subtree_end(nodes, index):stop]
            roots = []
            cursor = 0
            while cursor < len(body):
                subtree_end = _subtree_end(body, cursor)
                segment = body[cursor:subtree_end]
                if (body[cursor]["role"] == "Group" and any(_native_icon(c["name"]) for c in segment)
                        and all(not c["name"].strip() or _native_icon(c["name"]) for c in segment)):
                    break
                roots.extend(segment)
                cursor = subtree_end
            parts = _native_parts(roots)
            messages.append({"sender_ref": ref(sender), "recipient_ref": ref(recipient),
                             "timestamp": timestamp, "parts": parts})
        order_documents = []
        for i, n in enumerate(nodes):
            if n["role"] != "Document":
                continue
            document = nodes[i + 1:_subtree_end(nodes, i)]
            if not any(c["role"] == "Text" and c["name"].strip() == "客户订单" for c in document):
                continue
            order_documents.append(document)
        if len(order_documents) > 1:
            raise ValueError("order_document_ambiguous")
        # The current native order WebView exposes no customer-owner binding.
        # Even one stable panel may still show the previous customer's orders.
        # Do not offer those values for import until native ownership is proven.
        binding = {"window_ref": str(hwnd), "conversation_ref": ref(buyer)}
        preview = build_uia_preview({
            "mode": mode,
            "schema_version": "qianniu_uia_preview/v1", "scope": "visible_conversation_document",
            "binding_before": binding, "binding_after": binding, "truncated": False,
            "buyer_ref": ref(buyer), "agent_refs": sorted(agents), "messages": messages,
            "order_candidates": [], "product_code_candidates": [],
        })
        if preview.diagnostics["status"] != "preview_ready":
            raise ValueError(preview.diagnostics["reason_code"])
        preview.diagnostics["unbound_order_documents_omitted"] = len(order_documents)
        return {"ok": True, "status": "manual_confirmation_required" if assisted else "preview_ready",
                **({"buyer_name": buyer} if assisted else {}),
                "conversation_ref": binding["conversation_ref"],
                "shop_name": shop, "diagnostics": preview.diagnostics, "context": preview.context,
                "window": {"handle": hwnd, "label": "千牛接待窗口"}}
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "diagnostics": {
            "selected_buyer_count": sum(n.get("role") == "TreeItem" and n.get("selected") is True for n in before),
            "selected_tab_count": sum(n.get("role") == "TabItem" and n.get("selected") is True for n in before),
            "legacy_selected_buyer_count": sum(n.get("role") == "TreeItem" and n.get("legacy_selected") is True for n in before),
            "legacy_selected_tab_count": sum(n.get("role") == "TabItem" and n.get("legacy_selected") is True for n in before),
            "parent_selection": _parent_selection_summary(before),
        }}


def _parent_selection_summary(nodes: list[dict]) -> dict:
    summary = {}
    for role in ("Tree", "Tab", "List"):
        controls = [n.get("selection_diagnostics", {}) for n in nodes if n.get("role") == role]
        if not controls:
            continue
        summary[role] = {}
        for channel in ("uia", "msaa"):
            readings = [control.get(channel, {}) for control in controls]
            summary[role][channel] = {
                "read_controls": sum(r.get("status") == "read" for r in readings),
                "unsupported_controls": sum(r.get("status") == "unsupported" for r in readings),
                "error_controls": sum(r.get("status") not in {"read", "unsupported"} for r in readings),
                "selected_items": sum(r["count"] for r in readings if r.get("status") == "read"),
            }
    return summary


def _native_parent_selection(element: Any) -> dict:
    """Read only collection lengths, never dereference selected customer data."""
    from pywinauto.uia_defines import NoPatternInterfaceError, get_elem_interface

    result = {}
    for channel, pattern in (("uia", "Selection"), ("msaa", "LegacyIAccessible")):
        try:
            selection = get_elem_interface(element, pattern).GetCurrentSelection()
            count = selection.Length
            if type(count) is not int or not 0 <= count <= 1800:
                raise ValueError("selection_count_invalid")
            result[channel] = {"status": "read", "count": count}
        except NoPatternInterfaceError:
            result[channel] = {"status": "unsupported", "count": None}
        except Exception:
            # UIA errors may contain account data. Unknown is not an empty read.
            result[channel] = {"status": "error", "count": None}
    return result


def read_native_tree(window: Any) -> list[dict]:
    """Bounded read-only UIA traversal. Call from a timeout-limited process."""
    nodes = []

    def visit(control: Any, depth: int) -> None:
        if depth > 28 or len(nodes) >= 1800:
            raise ValueError("capture_size_limit")
        info = control.element_info
        name = info.name or ""
        if len(name) > 8000:
            raise ValueError("capture_size_limit")
        role = info.control_type
        aria = info.element.GetCurrentPropertyValue(30101)
        heading = info.element.GetCurrentPropertyValue(30173)
        if aria == "heading" or (isinstance(heading, int) and 80051 <= heading <= 80059):
            role = "Heading"
        elif aria == "main":
            role = "Main"
        state = info.element.GetCurrentPropertyValue(30096) if role in {"TreeItem", "TabItem"} else 0
        nodes.append({"depth": depth, "role": role, "name": name,
                      "automation_id": info.automation_id or "",
                      "legacy_selected": isinstance(state, int) and bool(state & 2),
                      "selected": info.element.GetCurrentPropertyValue(30079) is True
                      if role in {"TreeItem", "TabItem"} else False})
        if role in {"Tree", "Tab", "List"}:
            nodes[-1]["selection_diagnostics"] = _native_parent_selection(info.element)
        for child in control.children():
            visit(child, depth + 1)

    visit(window, 0)
    return nodes
