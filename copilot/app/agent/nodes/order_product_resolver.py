"""Resolve internal product identity from the current QianNiu order context."""

from __future__ import annotations

import re
import time
from typing import Any


_CACHE_TTL_SECONDS = 600
_RESOLUTION_CACHE: dict[str, dict[str, Any]] = {}


def _cache_get(key: str) -> dict[str, Any] | None:
    entry = _RESOLUTION_CACHE.get(key)
    if not entry:
        return None
    if time.time() - entry.get("ts", 0) > _CACHE_TTL_SECONDS:
        _RESOLUTION_CACHE.pop(key, None)
        return None
    return dict(entry.get("value") or {})


def _cache_set(key: str, value: dict[str, Any]) -> None:
    _RESOLUTION_CACHE[key] = {"ts": time.time(), "value": dict(value)}


def _candidate_value(cand: Any) -> str:
    if isinstance(cand, str):
        return cand.strip()
    if not isinstance(cand, dict):
        return ""
    for key in ("value", "product_name", "name", "title", "sku_name", "i_id", "sku_id"):
        val = str(cand.get(key) or "").strip()
        if val:
            return val
    return ""


def _candidate_type(cand: Any) -> str:
    if not isinstance(cand, dict):
        return ""
    return str(cand.get("type") or cand.get("identifier_type") or "").lower()


def _classify_product_code(value: str, cand_type: str = "") -> str:
    value = (value or "").strip()
    ctype = (cand_type or "").lower()
    if not value:
        return ""
    if "sku" in ctype or "商家编码" in ctype or "商品编码" in ctype:
        return "sku_id"
    if "i_id" in ctype or "款号" in ctype:
        return "i_id"
    if "platform" in ctype or "宝贝" in ctype:
        return ""
    if re.match(r"^YH[A-Za-z0-9_-]{4,40}$", value, re.IGNORECASE):
        return "sku_id" if re.search(r"B\d|S\d", value, re.IGNORECASE) else "i_id"
    return ""


def _pick_product_code(state: dict) -> tuple[str, str]:
    slots = state.get("slots", {}) or {}
    for key, code_type in (("sku_code", "sku_id"), ("sku_id", "sku_id"), ("i_id", "i_id")):
        value = str(slots.get(key) or "").strip()
        if value:
            return value, code_type

    ctx = state.get("copilot_context", {}) or {}
    for cand in ctx.get("product_candidates", []) or state.get("product_candidates", []) or []:
        value = _candidate_value(cand)
        code_type = _classify_product_code(value, _candidate_type(cand))
        if code_type:
            return value, code_type
    return "", ""


def _pick_product_name_candidates(state: dict) -> list[str]:
    ctx = state.get("copilot_context", {}) or {}
    names: list[str] = []
    for cand in ctx.get("product_candidates", []) or state.get("product_candidates", []) or []:
        value = _candidate_value(cand)
        if not value:
            continue
        ctype = _candidate_type(cand)
        if _classify_product_code(value, ctype):
            continue
        if "platform_product_id" in ctype or re.fullmatch(r"\d{6,}", value):
            continue
        if value not in names:
            names.append(value)
    return names


def _pick_platform_product_id(state: dict) -> str:
    ctx = state.get("copilot_context", {}) or {}
    for cand in ctx.get("product_candidates", []) or state.get("product_candidates", []) or []:
        value = _candidate_value(cand)
        ctype = _candidate_type(cand)
        if value and "platform_product_id" in ctype and re.fullmatch(r"\d{6,}", value):
            return value
    return ""


def _first_candidate(candidates: list[Any]) -> tuple[str, str]:
    for cand in candidates or []:
        value = _candidate_value(cand)
        if value:
            ctype = _candidate_type(cand)
            if "platform_trade" in ctype or "outer" in ctype:
                return value, "platform_trade_id"
            if "platform_order" in ctype or "so_id" in ctype:
                return value, "platform_order_id"
            if "internal_order" in ctype or "order_id" in ctype or "o_id" in ctype:
                return value, "internal_order_id"
            if "tracking" in ctype:
                return value, "tracking_no"
            return value, "unknown_identifier"
    return "", ""


def _pick_order_identifier(state: dict) -> tuple[str, str]:
    slots = state.get("slots", {}) or {}
    ctx = state.get("copilot_context", {}) or {}

    for key, id_type in (
        ("platform_trade_id", "platform_trade_id"),
        ("platform_order_id", "platform_order_id"),
        ("order_id", "internal_order_id"),
        ("tracking_no", "tracking_no"),
    ):
        value = str(ctx.get(key) or "").strip()
        if value:
            return value, id_type

    value, id_type = _first_candidate(ctx.get("order_candidates", []))
    if value:
        return value, id_type
    value, id_type = _first_candidate(ctx.get("tracking_candidates", []))
    if value:
        return value, id_type

    if state.get("tracking_no"):
        return str(state["tracking_no"]).strip(), "tracking_no"
    if state.get("order_id"):
        state_order = str(state["order_id"]).strip()
        for cand in ctx.get("order_candidates", []) or []:
            if _candidate_value(cand) == state_order:
                ctype = _candidate_type(cand)
                if "platform_trade" in ctype or "outer" in ctype:
                    return state_order, "platform_trade_id"
                if "platform_order" in ctype or "so_id" in ctype:
                    return state_order, "platform_order_id"
        return state_order, "unknown_identifier"

    for key, id_type in (
        ("platform_trade_id", "platform_trade_id"),
        ("order_id", "internal_order_id"),
        ("tracking_no", "tracking_no"),
        ("possible_numeric_id", "unknown_identifier"),
    ):
        value = str(slots.get(key) or "").strip()
        if value:
            if key == "order_id" and slots.get("identifier_type"):
                return value, slots.get("identifier_type")
            return value, id_type

    conv = state.get("conversation_context", {}) or {}
    for key, id_type in (
        ("known_platform_trade_id", "platform_trade_id"),
        ("known_order_id", "internal_order_id"),
        ("known_tracking_no", "tracking_no"),
    ):
        value = str(conv.get(key) or "").strip()
        if value:
            return value, id_type
    return "", ""


def _tokens(text: str) -> set[str]:
    text = (text or "").lower()
    latin = set(re.findall(r"[a-z0-9]{2,}", text))
    chinese = {text[i:i + 2] for i in range(max(0, len(text) - 1)) if "\u4e00" <= text[i] <= "\u9fff"}
    return {t for t in latin | chinese if t.strip()}


def _score_item(item: dict, context_text: str) -> float:
    name = str(item.get("name") or item.get("sku_name") or "").strip()
    sku_id = str(item.get("sku_id") or "").strip()
    i_id = str(item.get("i_id") or "").strip()
    item_tokens = _tokens(" ".join([name, sku_id, i_id]))
    ctx_tokens = _tokens(context_text)
    if not item_tokens or not ctx_tokens:
        return 0.0
    overlap = len(item_tokens & ctx_tokens)
    return overlap / max(len(item_tokens), 1)


def _product_name_tokens(text: str) -> set[str]:
    text = (text or "").lower()
    tokens = set(re.findall(r"[a-z0-9]{2,}", text))
    chinese_chars = [ch for ch in text if "\u4e00" <= ch <= "\u9fff"]
    tokens.update(chinese_chars)
    tokens.update(
        "".join(chinese_chars[i:i + 2])
        for i in range(max(0, len(chinese_chars) - 1))
    )
    return {t for t in tokens if t.strip()}


def _chinese_text(text: str) -> str:
    return "".join(ch for ch in (text or "") if "\u4e00" <= ch <= "\u9fff")


def _longest_common_substring_len(a: str, b: str) -> int:
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    best = 0
    for ca in a:
        cur = [0] * (len(b) + 1)
        for idx, cb in enumerate(b, start=1):
            if ca == cb:
                cur[idx] = prev[idx - 1] + 1
                best = max(best, cur[idx])
        prev = cur
    return best


def _score_product_name_item(item: dict, query: str) -> float:
    name = str(item.get("name") or item.get("product_name") or item.get("sku_name") or "").strip()
    query = (query or "").strip()
    if not name or not query:
        return 0.0
    if name in query or query in name:
        return 1.0
    name_tokens = _product_name_tokens(name)
    query_tokens = _product_name_tokens(query)
    if not name_tokens or not query_tokens:
        return 0.0
    score = len(name_tokens & query_tokens) / max(len(name_tokens), 1)
    name_cn = _chinese_text(name)
    query_cn = _chinese_text(query)
    lcs = _longest_common_substring_len(name_cn, query_cn)
    if len(query_cn) >= 12:
        if len(name_cn) <= 4 and lcs < 3:
            score *= 0.65
        if lcs >= 4:
            score += 0.25
        elif lcs >= 3:
            score += 0.1
    return min(score, 1.0)


def _context_product_text(state: dict) -> str:
    ctx = state.get("copilot_context", {}) or {}
    parts = [state.get("customer_message", ""), state.get("normalized_message", "")]
    for cand in ctx.get("product_candidates", []) or []:
        parts.append(_candidate_value(cand))
    for item in ctx.get("conversation_history", []) or []:
        if isinstance(item, dict):
            from app.services.canonical_conversation_turn_service import turn_content
            parts.append(turn_content(item))
    return " ".join(p for p in parts if p)


def _pick_order_item(items: list[dict], state: dict) -> tuple[dict | None, float, str]:
    if not items:
        return None, 0.0, "no_items"
    if len(items) == 1:
        return items[0], 0.99, "single_order_item"

    primary_items = [item for item in items if not _looks_like_gift_item(item)]
    if len(primary_items) == 1:
        return primary_items[0], 0.97, "single_primary_item_with_gifts"

    context_text = _context_product_text(state)
    scored = sorted(
        [(_score_item(item, context_text), idx, item) for idx, item in enumerate(items)],
        key=lambda x: (-x[0], x[1]),
    )
    if not scored:
        return None, 0.0, "no_scored_items"
    best_score, _, best_item = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else 0.0
    if best_score >= 0.12 and best_score >= second_score + 0.05:
        return best_item, best_score, "matched_by_context"
    return None, best_score, "ambiguous_multi_item_order"


def _looks_like_gift_item(item: dict) -> bool:
    name = str(item.get("name") or item.get("sku_name") or "").strip()
    sku_id = str(item.get("sku_id") or item.get("i_id") or "").strip()
    try:
        price = float(item.get("price") or item.get("amount") or item.get("sale_price") or 0)
    except (TypeError, ValueError):
        price = 0.0
    gift_by_name = any(word in name for word in ("\u8d60\u54c1", "\u8d60\u9001", "\u793c\u54c1"))
    gift_by_code = sku_id.startswith("GIFT") or sku_id.endswith("-GIFT")
    return gift_by_name or gift_by_code or price <= 0


def _identity_from_item(item: dict, confidence: float, reason: str, order_data: dict, identifier: str, identifier_type: str) -> dict:
    name = str(item.get("name") or item.get("sku_name") or "").strip()
    sku_id = str(item.get("sku_id") or "").strip()
    i_id = str(item.get("i_id") or "").strip()
    candidates = []
    for val in (name, sku_id, i_id):
        if val and val not in candidates:
            candidates.append(val)
    return {
        "status": "resolved",
        "source": "jst_order_items",
        "identifier": identifier,
        "identifier_type": identifier_type,
        "internal_product_name": name,
        "matched_product_name": name,
        "sku_id": sku_id,
        "i_id": i_id,
        "confidence": round(float(confidence), 3),
        "reason": reason,
        "order_id": str(order_data.get("o_id") or ""),
        "so_id": str(order_data.get("so_id") or ""),
        "outer_so_id": str(order_data.get("outer_so_id") or ""),
        "item_count": len(order_data.get("items", []) or []),
        "candidates": candidates,
    }


def _identity_from_product_card(card: dict, code: str, code_type: str) -> dict:
    name = str(card.get("product_name") or card.get("name") or "").strip()
    i_id = str(card.get("i_id") or "").strip()
    sku_id = code if code_type == "sku_id" else ""
    sku_list = card.get("sku_summary", {}).get("sku_list", []) if isinstance(card.get("sku_summary"), dict) else []
    if code_type == "sku_id":
        for sku in sku_list:
            if str(sku.get("sku_id") or "").strip() == code:
                sku_id = code
                break
    candidates = []
    for val in (name, sku_id, i_id, code):
        if val and val not in candidates:
            candidates.append(val)
    return {
        "status": "resolved",
        "source": "sidecar_product_code",
        "identifier": code,
        "identifier_type": code_type,
        "internal_product_name": name,
        "matched_product_name": name or code,
        "sku_id": sku_id,
        "i_id": i_id or (code if code_type == "i_id" else ""),
        "confidence": 0.98,
        "reason": "matched_by_sidecar_product_code",
        "item_count": 0,
        "candidates": candidates,
    }


def _identity_from_jst_sku(sku_data: dict, code: str, code_type: str) -> dict:
    name = str(sku_data.get("name") or sku_data.get("sku_name") or "").strip()
    sku_id = str(sku_data.get("sku_id") or code).strip()
    i_id = str(sku_data.get("i_id") or "").strip()
    candidates = []
    for val in (name, sku_id, i_id):
        if val and val not in candidates:
            candidates.append(val)
    return {
        "status": "resolved",
        "source": "jst_sku_query",
        "identifier": code,
        "identifier_type": code_type,
        "internal_product_name": name,
        "matched_product_name": name or sku_id or code,
        "sku_id": sku_id,
        "i_id": i_id,
        "confidence": 0.9,
        "reason": "matched_by_jst_sku",
        "item_count": 0,
        "candidates": candidates,
    }


def _identity_from_jst_product_lookup(product_data: dict, identifier: str, identifier_type: str, lookup: dict) -> dict:
    name = str(
        product_data.get("name")
        or product_data.get("title")
        or product_data.get("item_name")
        or product_data.get("shop_i_name")
        or product_data.get("sku_name")
        or ""
    ).strip()
    sku_id = str(
        product_data.get("sku_id")
        or product_data.get("jst_sku_id")
        or product_data.get("src_sku_id")
        or product_data.get("outer_sku_id")
        or ""
    ).strip()
    i_id = str(
        product_data.get("i_id")
        or product_data.get("jst_i_id")
        or product_data.get("item_id")
        or ""
    ).strip()
    candidates = []
    for val in (name, sku_id, i_id, identifier):
        if val and val not in candidates:
            candidates.append(val)
    return {
        "status": "resolved",
        "source": "jst_product_name_query" if identifier_type == "product_name" else "jst_product_query",
        "identifier": identifier,
        "identifier_type": identifier_type,
        "internal_product_name": name,
        "matched_product_name": name or sku_id or i_id or identifier,
        "sku_id": sku_id,
        "i_id": i_id,
        "confidence": float(lookup.get("confidence") or (0.88 if (sku_id or i_id) else 0.72)),
        "reason": f"matched_by_{identifier_type}",
        "item_count": 0,
        "candidates": candidates,
        "lookup_endpoint": lookup.get("endpoint", ""),
        "lookup_duration_ms": lookup.get("duration_ms", 0),
        "attempted_paths": lookup.get("attempted_paths", []),
    }


def _identity_from_product_name_match(item: dict, query: str, confidence: float, reason: str) -> dict:
    name = str(item.get("name") or item.get("product_name") or item.get("sku_name") or "").strip()
    sku_id = str(item.get("sku_id") or "").strip()
    i_id = str(item.get("i_id") or "").strip()
    candidates = []
    for val in (name, sku_id, i_id, query):
        if val and val not in candidates:
            candidates.append(val)
    return {
        "status": "resolved",
        "source": "sidecar_product_name",
        "identifier": query,
        "identifier_type": "product_name",
        "internal_product_name": name,
        "matched_product_name": name or query,
        "sku_id": sku_id,
        "i_id": i_id,
        "confidence": round(float(confidence), 3),
        "reason": reason,
        "item_count": 0,
        "candidates": candidates,
    }


def _local_product_items(pk_repo: Any, product_repo: Any) -> list[dict]:
    items: list[dict] = []
    seen: set[tuple[str, str, str]] = set()

    for card in getattr(pk_repo, "_cards", []) or []:
        name = str(card.get("product_name") or card.get("name") or "").strip()
        i_id = str(card.get("i_id") or "").strip()
        sku_list = card.get("sku_summary", {}).get("sku_list", []) if isinstance(card.get("sku_summary"), dict) else []
        if sku_list:
            for sku in sku_list:
                item = {
                    "name": name or str(sku.get("sku_name") or "").strip(),
                    "sku_id": str(sku.get("sku_id") or "").strip(),
                    "i_id": i_id,
                }
                key = (item["name"], item["sku_id"], item["i_id"])
                if item["name"] and key not in seen:
                    items.append(item)
                    seen.add(key)
        elif name:
            item = {"name": name, "sku_id": "", "i_id": i_id}
            key = (item["name"], item["sku_id"], item["i_id"])
            if key not in seen:
                items.append(item)
                seen.add(key)

    for sku in getattr(product_repo, "skus", {}).values() if product_repo else []:
        item = {
            "name": str(sku.get("name") or sku.get("sku_name") or "").strip(),
            "sku_id": str(sku.get("sku_id") or "").strip(),
            "i_id": str(sku.get("i_id") or "").strip(),
        }
        key = (item["name"], item["sku_id"], item["i_id"])
        if item["name"] and key not in seen:
            items.append(item)
            seen.add(key)

    try:
        from app.db import SessionLocal
        from app.models.kb_tables import KBProduct

        db = SessionLocal()
        try:
            products = db.query(KBProduct).filter(KBProduct.status == "published").all()
            for product in products:
                name = str(product.product_name or "").strip()
                i_id = str(product.i_id or "").strip()
                sku_list = product.get_sku_list()
                if sku_list:
                    for sku in sku_list:
                        if isinstance(sku, dict):
                            sku_id = str(
                                sku.get("sku_code")
                                or sku.get("sku_id")
                                or sku.get("value")
                                or ""
                            ).strip()
                        else:
                            sku_id = str(sku or "").strip()
                        item = {"name": name, "sku_id": sku_id, "i_id": i_id}
                        key = (item["name"], item["sku_id"], item["i_id"])
                        if item["name"] and key not in seen:
                            items.append(item)
                            seen.add(key)
                elif name:
                    item = {"name": name, "sku_id": "", "i_id": i_id}
                    key = (item["name"], item["sku_id"], item["i_id"])
                    if key not in seen:
                        items.append(item)
                        seen.add(key)
        finally:
            db.close()
    except Exception:
        pass

    return items


def _resolve_product_name_from_local(state: dict) -> dict | None:
    names = _pick_product_name_candidates(state)
    if not names:
        return None

    try:
        from app.main import get_product_knowledge_repo, get_product_repo

        pk_repo = get_product_knowledge_repo()
        product_repo = get_product_repo()
        items = _local_product_items(pk_repo, product_repo)
    except Exception as exc:
        return {
            "status": "lookup_error",
            "source": "sidecar_product_name",
            "identifier": names[0],
            "identifier_type": "product_name",
            "reason": str(exc),
            "confidence": 0.0,
            "candidates": [],
        }

    if not items:
        return None

    context_text = _context_product_text(state)
    scored: list[tuple[float, int, dict, str]] = []
    for query in names:
        for idx, item in enumerate(items):
            score = max(
                _score_product_name_item(item, query),
                _score_item(item, " ".join([context_text, query])),
            )
            if score > 0:
                scored.append((score, idx, item, query))

    if not scored:
        return None

    scored.sort(key=lambda x: (-x[0], x[1]))
    best_score, _, best_item, best_query = scored[0]
    best_identity_key = (
        str(best_item.get("i_id") or "").strip(),
        str(best_item.get("name") or "").strip(),
    )
    second_score = 0.0
    for score, _, item, _query in scored[1:]:
        item_identity_key = (
            str(item.get("i_id") or "").strip(),
            str(item.get("name") or "").strip(),
        )
        if item_identity_key != best_identity_key:
            second_score = score
            break
    best_name = str(best_item.get("name") or "").strip()
    long_platform_title = len(best_query) >= 12
    exact_containment = bool(best_name and (best_name in best_query or best_query in best_name))
    confident_match = (
        (best_score >= 0.35 and best_score >= second_score + 0.08)
        if not long_platform_title
        else ((best_score >= 0.55 and best_score >= second_score + 0.12) or exact_containment)
    )
    if confident_match:
        return _identity_from_product_name_match(best_item, best_query, best_score, "matched_by_sidecar_product_name")

    candidates = []
    for score, _, item, _query in scored[:5]:
        if score < 0.25:
            continue
        name = str(item.get("name") or "").strip()
        if name and not any(c.get("name") == name for c in candidates):
            candidates.append({
                "name": name,
                "sku_id": str(item.get("sku_id") or "").strip(),
                "i_id": str(item.get("i_id") or "").strip(),
            })
    if candidates:
        # Distinguish single-candidate-low-confidence from multi-candidate-ambiguous
        distinct_ids = set(c.get("i_id") or c.get("name") for c in candidates if c.get("i_id") or c.get("name"))
        if len(distinct_ids) <= 1:
            # Only one product matched — resolve with low confidence instead of ambiguous
            best = candidates[0]
            return {
                "status": "resolved",
                "source": "sidecar_product_name",
                "identifier": names[0],
                "identifier_type": "product_name",
                "internal_product_name": best.get("name", ""),
                "matched_product_name": best.get("name", "") or names[0],
                "sku_id": best.get("sku_id", ""),
                "i_id": best.get("i_id", ""),
                "confidence": round(float(best_score), 3),
                "reason": "low_confidence_single_match",
                "item_count": 1,
                "candidates": [best],
                "low_confidence": True,
            }
        if len(names) == 1 and len(best_query) >= 12 and best_score >= 0.25:
            identity = _identity_from_product_name_match(
                best_item,
                best_query,
                best_score,
                "low_confidence_best_sidecar_match",
            )
            identity["candidates"] = candidates
            identity["low_confidence"] = True
            return identity
        identity = _unresolved("ambiguous", names[0], "product_name", "ambiguous_sidecar_product_name", candidates)
        identity["source"] = "sidecar_product_name"
        identity["item_count"] = len(candidates)
        return identity
    return None


def _resolve_direct_product_code(state: dict) -> dict | None:
    code, code_type = _pick_product_code(state)
    if not code:
        return None

    try:
        from app.main import get_product_knowledge_repo, get_product_repo

        pk_repo = get_product_knowledge_repo()
        product_repo = get_product_repo()
        card = None
        if pk_repo:
            card = pk_repo.get_by_sku_id(code) if code_type == "sku_id" else pk_repo.get_by_i_id(code)
        if card:
            return _identity_from_product_card(card, code, code_type)

        local_product = None
        if product_repo:
            local_product = product_repo.get_sku(code) if code_type == "sku_id" else product_repo.get_product(code)
        if local_product:
            return _identity_from_jst_sku(local_product, code, code_type)

        try:
            from app.db import SessionLocal
            from app.models.kb_tables import KBProduct

            db = SessionLocal()
            try:
                kb_product = None
                if code_type == "i_id":
                    kb_product = db.query(KBProduct).filter(KBProduct.i_id == code).first()
                else:
                    products = db.query(KBProduct).filter(KBProduct.status == "published").all()
                    for product in products:
                        for sku in product.get_sku_list():
                            if isinstance(sku, dict):
                                sku_id = str(
                                    sku.get("sku_code")
                                    or sku.get("sku_id")
                                    or sku.get("value")
                                    or ""
                                ).strip()
                            else:
                                sku_id = str(sku or "").strip()
                            if sku_id == code:
                                kb_product = product
                                break
                        if kb_product:
                            break
                if kb_product and kb_product.status == "published":
                    sku_list = []
                    for sku in kb_product.get_sku_list():
                        if isinstance(sku, dict):
                            sku_id = str(
                                sku.get("sku_code")
                                or sku.get("sku_id")
                                or sku.get("value")
                                or ""
                            ).strip()
                        else:
                            sku_id = str(sku or "").strip()
                        if sku_id:
                            sku_list.append({"sku_id": sku_id})
                    card = {
                        "product_name": kb_product.product_name,
                        "i_id": kb_product.i_id,
                        "sku_summary": {"sku_list": sku_list},
                    }
                    return _identity_from_product_card(card, code, code_type)
            finally:
                db.close()
        except Exception:
            pass

        if code_type == "sku_id":
            from app.integrations.jst.live_query import lookup_product_by_sku

            sku_lookup = lookup_product_by_sku(code)
            if sku_lookup.get("found") and isinstance(sku_lookup.get("data"), dict):
                identity = _identity_from_jst_sku(sku_lookup["data"], code, code_type)
                identity["lookup_endpoint"] = sku_lookup.get("endpoint", "")
                identity["lookup_duration_ms"] = sku_lookup.get("duration_ms", 0)
                return identity

        if code_type == "i_id":
            from app.integrations.jst.live_query import lookup_product_by_i_id

            product_lookup = lookup_product_by_i_id(code)
            if product_lookup.get("found") and isinstance(product_lookup.get("data"), dict):
                return _identity_from_jst_product_lookup(product_lookup["data"], code, code_type, product_lookup)
    except Exception as exc:
        return {
            "status": "lookup_error",
            "source": "sidecar_product_code",
            "identifier": code,
            "identifier_type": code_type,
            "reason": str(exc),
            "confidence": 0.0,
            "candidates": [],
        }

    return {
        "status": "not_found",
        "source": "sidecar_product_code",
        "identifier": code,
        "identifier_type": code_type,
        "reason": "product_code_not_found",
        "confidence": 0.0,
        "candidates": [],
    }


def _resolve_product_name_via_jst(state: dict) -> dict | None:
    names = _pick_product_name_candidates(state)
    if not names:
        return None
    product_name = names[0]
    try:
        from app.integrations.jst.live_query import lookup_product_by_name

        lookup = lookup_product_by_name(product_name)
        if lookup.get("found") and isinstance(lookup.get("data"), dict):
            return _identity_from_jst_product_lookup(lookup["data"], product_name, "product_name", lookup)
        identity = _unresolved(
            "not_found",
            product_name,
            "product_name",
            lookup.get("safe_fallback_reason") or lookup.get("error_code") or "product_name_not_found",
        )
        identity["source"] = "jst_product_name_query"
        identity["lookup_endpoint"] = lookup.get("endpoint", "")
        identity["lookup_duration_ms"] = lookup.get("duration_ms", 0)
        identity["attempted_paths"] = lookup.get("attempted_paths", [])
        return identity
    except Exception as exc:
        identity = _unresolved("lookup_error", product_name, "product_name", str(exc))
        identity["source"] = "jst_product_name_query"
        return identity


def _resolve_sidecar_product_name(state: dict) -> dict | None:
    """Resolve the sidecar product title without relying on an order lookup."""
    name_candidates = _pick_product_name_candidates(state)
    if not name_candidates:
        return None

    jst_name_identity = _resolve_product_name_via_jst(state)
    if jst_name_identity and jst_name_identity.get("status") == "resolved":
        return jst_name_identity

    local_identity = _resolve_product_name_from_local(state)
    if local_identity:
        return local_identity

    return jst_name_identity


def _lookup_local_order(identifier: str, identifier_type: str) -> dict | None:
    """Fallback: try to find order in local JSON repository."""
    if not identifier:
        return None
    try:
        from app.main import get_order_repo
        order_repo = get_order_repo()
    except Exception:
        try:
            from app.repositories.json_order_repository import JsonOrderRepository
            order_repo = JsonOrderRepository()
            order_repo.load()
        except Exception:
            return None

    if identifier_type in ("internal_order_id", "order_id", "platform_order_id"):
        order = order_repo.get_order(identifier)
        if order:
            return order
    if identifier_type == "tracking_no":
        order = order_repo.get_order_by_tracking_no(identifier)
        if order:
            return order
    # Try all lookup paths as fallback
    order = order_repo.get_order(identifier)
    if order:
        return order
    order = order_repo.get_order_by_tracking_no(identifier)
    if order:
        return order
    return None


def _unresolved(status: str, identifier: str = "", identifier_type: str = "", reason: str = "", items: list[dict] | None = None) -> dict:
    candidates = []
    for item in items or []:
        name = str(item.get("name") or "").strip()
        sku_id = str(item.get("sku_id") or "").strip()
        i_id = str(item.get("i_id") or "").strip()
        if name:
            candidates.append({"name": name, "sku_id": sku_id, "i_id": i_id})
    return {
        "status": status,
        "source": "jst_order_items",
        "identifier": identifier,
        "identifier_type": identifier_type,
        "reason": reason,
        "confidence": 0.0,
        "candidates": candidates[:5],
    }


def order_product_resolver(state: dict) -> dict:
    t0 = time.time()
    conversation_id = state.get("conversation_id") or "default"
    ctx = state.get("conversation_context", {}) or {}
    code, code_type = _pick_product_code(state)
    direct_key = f"product_code:{code_type}:{code}" if code and code_type else ""
    if direct_key:
        cached_ctx = ctx.get("order_product_identity") if ctx.get("order_product_identity_key") == direct_key else None
        cached_global = _cache_get(f"{conversation_id}|{direct_key}") if not cached_ctx else None
        cached = cached_ctx or cached_global
        if cached:
            return _build_updates_from_identity(state, cached, t0, cache_hit=True)

    direct_identity = _resolve_direct_product_code(state)
    if direct_identity and direct_identity.get("status") == "resolved":
        direct_key = f"product_code:{direct_identity.get('identifier_type', '')}:{direct_identity.get('identifier', '')}"
        if direct_key:
            _cache_set(f"{conversation_id}|{direct_key}", direct_identity)
        return _build_updates_from_identity(state, direct_identity, t0, cache_hit=False)

    identifier, identifier_type = _pick_order_identifier(state)
    current_key = f"{identifier_type}:{identifier}" if identifier else ""

    # 纯物流/订单查询意图：不需要商品身份解析，交给 identifier tool router 处理
    if identifier and state.get("intent") in (
        "logistics_eta", "logistics_trace", "shipping", "logistics", "delivery_not_received"
    ):
        trace = {
            "node": "order_product_resolver",
            "status": "skipped",
            "duration_ms": int((time.time() - t0) * 1000),
            "cache_hit": False,
            "summary": "deferred to identifier tool router (logistics/order lookup intent)",
        }
        return {"trace_steps": state.get("trace_steps", []) + [trace]}

    if not identifier:
        name_candidates = _pick_product_name_candidates(state)
        jst_name_identity = None
        if name_candidates:
            name_key = f"product_name:{name_candidates[0]}"
            cached_ctx = ctx.get("order_product_identity") if ctx.get("order_product_identity_key") == name_key else None
            cached_global = _cache_get(f"{conversation_id}|{name_key}") if not cached_ctx else None
            cached = cached_ctx or cached_global
            if cached:
                return _build_updates_from_identity(state, cached, t0, cache_hit=True)

        # 本地商品库优先（无外部依赖、更快）：
        # - 高置信命中（status=resolved 且无 low_confidence）：直接采用，跳过 JST。
        # - 低置信命中（low_confidence=True）：本地模糊匹配不可靠，继续调用 JST 名称查询做二次确认。
        # - 未命中/歧义：按既有兜底走 JST 名称查询。
        name_identity = _resolve_product_name_from_local(state)
        local_resolved = bool(name_identity and name_identity.get("status") == "resolved")
        local_confident = local_resolved and not name_identity.get("low_confidence")
        if local_confident:
            name_key = f"product_name:{name_identity.get('identifier', '')}"
            _cache_set(f"{conversation_id}|{name_key}", name_identity)
            return _build_updates_from_identity(state, name_identity, t0, cache_hit=False)

        jst_name_identity = _resolve_product_name_via_jst(state)
        if jst_name_identity and jst_name_identity.get("status") == "resolved":
            # JST 高置信结果覆盖本地低置信结果；保留本地候选用于调试/澄清。
            chosen = jst_name_identity
            if local_resolved:
                chosen = dict(jst_name_identity)
                chosen["local_low_confidence_candidates"] = name_identity.get("candidates", [])
            name_key = f"product_name:{chosen.get('identifier', '')}"
            _cache_set(f"{conversation_id}|{name_key}", chosen)
            return _build_updates_from_identity(state, chosen, t0, cache_hit=False)

        # JST 未命中：回退到本地结果（低置信 resolved 或歧义），保留既有兜底语义。
        fallback = name_identity or jst_name_identity
        if fallback:
            name_key = f"product_name:{fallback.get('identifier', '')}"
            _cache_set(f"{conversation_id}|{name_key}", fallback)
            return _build_updates_from_identity(state, fallback, t0, cache_hit=False)
        trace = {
            "node": "order_product_resolver",
            "status": "skipped",
            "duration_ms": 0,
            "cache_hit": False,
            "summary": "no order identifier for product identity",
        }
        updates = {"trace_steps": state.get("trace_steps", []) + [trace]}
        if direct_identity:
            updates["order_product_identity"] = direct_identity
        elif jst_name_identity:
            updates["order_product_identity"] = jst_name_identity
        return updates

    cached_ctx = ctx.get("order_product_identity") if ctx.get("order_product_identity_key") == current_key else None
    cached_global = _cache_get(f"{conversation_id}|{current_key}") if not cached_ctx else None
    cached = cached_ctx or cached_global
    if cached:
        return _build_updates_from_identity(state, cached, t0, cache_hit=True)

    try:
        from app.integrations.jst.live_query import lookup_order_by_identifier

        lookup = lookup_order_by_identifier(identifier, identifier_type, exhaustive=False)
        if not lookup.get("found") and identifier_type != "unknown_identifier":
            fallback_lookup = lookup_order_by_identifier(
                identifier,
                "unknown_identifier",
                exhaustive=False,
            )
            if fallback_lookup.get("found"):
                fallback_lookup["primary_lookup"] = {
                    "identifier_type": identifier_type,
                    "endpoint": lookup.get("endpoint", ""),
                    "duration_ms": lookup.get("duration_ms", 0),
                    "safe_fallback_reason": lookup.get("safe_fallback_reason", ""),
                }
                lookup = fallback_lookup
                identifier_type = "unknown_identifier"
    except Exception as exc:
        identity = _unresolved("lookup_error", identifier, identifier_type, str(exc))
        return _build_updates_from_identity(state, identity, t0, cache_hit=False)

    if not lookup.get("found"):
        # Fallback: try local order repository before giving up
        # Only when the identifier came from current-turn slots (not stale conversation context)
        local_order = _lookup_local_order(identifier, identifier_type)
        # Check if identifier came from current-turn slot extraction vs conversation context
        slots = state.get("slots", {}) or {}
        identifier_in_current_slots = bool(
            identifier and (
                identifier == slots.get("order_id") or identifier == slots.get("platform_trade_id")
                or identifier == slots.get("tracking_no") or identifier == slots.get("possible_numeric_id")
                or identifier == state.get("order_id", "") or identifier == state.get("tracking_no", "")
            )
        )
        if local_order:
            lookup = {"found": True, "data": local_order, "source": "local_order", "query_type": identifier_type}
            # Tag whether this came from current-turn slots (affects order_found propagation)
            lookup["_from_current_slots"] = identifier_in_current_slots
            identifier_type = identifier_type or "internal_order_id"
        else:
            # Do not let a failed order lookup erase a sidecar product title.
            # In real QianNiu use, customers often ask "where is my package +
            # is this material safe" in one message; the order may miss while
            # the sidebar product is still the best product identity.
            sidecar_identity = _resolve_sidecar_product_name(state)
            if sidecar_identity and sidecar_identity.get("status") == "resolved":
                sidecar_identity["order_lookup_status"] = "not_found"
                sidecar_identity["order_identifier"] = identifier
                sidecar_identity["order_identifier_type"] = identifier_type
                sidecar_identity["order_lookup_reason"] = (
                    lookup.get("safe_fallback_reason") or lookup.get("error_code") or "order_not_found"
                )
                key = f"product_name:{sidecar_identity.get('identifier', '')}"
                if sidecar_identity.get("identifier"):
                    _cache_set(f"{conversation_id}|{key}", sidecar_identity)
                return _build_updates_from_identity(state, sidecar_identity, t0, cache_hit=False)

            identity = _unresolved(
                "not_found",
                identifier,
                identifier_type,
                lookup.get("safe_fallback_reason") or lookup.get("error_code") or "order_not_found",
            )
            identity["lookup_endpoint"] = lookup.get("endpoint", "")
            identity["lookup_duration_ms"] = lookup.get("duration_ms", 0)
            _cache_set(f"{conversation_id}|{current_key}", identity)
            return _build_updates_from_identity(state, identity, t0, cache_hit=False)

    order_data = lookup.get("data") or {}
    from_current_slots = lookup.get("_from_current_slots", True)
    items = order_data.get("items", []) or []
    item, confidence, reason = _pick_order_item(items, state)
    if item:
        identity = _identity_from_item(item, confidence, reason, order_data, identifier, identifier_type)
        identity["_order_data"] = order_data  # propagate full order for downstream nodes
        identity["_from_current_slots"] = from_current_slots  # track identifier provenance
    else:
        identity = _unresolved("ambiguous", identifier, identifier_type, reason, items)
        identity["item_count"] = len(items)
    identity["lookup_endpoint"] = lookup.get("endpoint", "")
    identity["lookup_duration_ms"] = lookup.get("duration_ms", 0)
    _cache_set(f"{conversation_id}|{current_key}", identity)
    return _build_updates_from_identity(state, identity, t0, cache_hit=False)


def _build_updates_from_identity(state: dict, identity: dict, t0: float, cache_hit: bool) -> dict:
    status = identity.get("status", "")
    trace = {
        "node": "order_product_resolver",
        "status": "success" if status == "resolved" else ("skipped" if status == "not_found" else "partial"),
        "duration_ms": int((time.time() - t0) * 1000),
        "cache_hit": cache_hit,
        "identifier_type": identity.get("identifier_type", ""),
        "identifier": identity.get("identifier", ""),
        "summary": f"order product identity {status}: {identity.get('matched_product_name') or identity.get('reason', '')}",
    }
    updates: dict[str, Any] = {
        "order_product_identity": identity,
        "trace_steps": state.get("trace_steps", []) + [trace],
    }
    if status == "resolved":
        product_name = identity.get("matched_product_name", "")
        slots = dict(state.get("slots", {}) or {})
        if product_name:
            slots["product_name"] = product_name
            slots["sku_name"] = product_name
        if identity.get("sku_id"):
            slots["sku_code"] = identity["sku_id"]
        updates.update({
            "matched_product_name": product_name,
            "product_candidates": identity.get("candidates", []),
            "slots": slots,
            "product_identity_source": identity.get("source", ""),
        })
        # Propagate order data to top-level state for downstream nodes
        # Only set order_found when the identifier came from current-turn slots,
        # not from stale conversation context (avoids test isolation issues)
        order_data = identity.get("_order_data")
        from_current_slots = identity.get("_from_current_slots", True)
        if order_data and not state.get("order") and not state.get("live_order") and from_current_slots:
            updates["order"] = order_data
            updates["order_found"] = True
            updates["order_source"] = identity.get("source", "local_order")
    elif identity.get("candidates") and status != "resolved":
        # Only set need_clarification for truly ambiguous (not resolved with low confidence)
        updates["need_clarification"] = True
        if identity.get("source") == "sidecar_product_name":
            updates["product_candidates"] = []
            updates["should_query_knowledge"] = False
            updates["answer_mode"] = "no_evidence_clarification"
            updates["clarification_question"] = (
                "亲亲，当前会话里的商品名称可能对应多个内部商品，"
                "麻烦您确认一下具体 SKU、商品编码、商品链接或订单号，我帮您核实准确参数～"
            )
        else:
            updates["product_candidates"] = identity.get("candidates", [])
    return updates
