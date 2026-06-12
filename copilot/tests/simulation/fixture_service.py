"""
Fixture service — provides fixture data for offline simulation mode.

Loads pre-built fixture files and injects context so the analysis pipeline
can run without real JST / order database lookups.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"

# Module-level caches (loaded once)
_jst_fixtures: dict | None = None
_product_fixtures: dict | None = None


# ---------------------------------------------------------------------------
# Fixture loading
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> dict:
    """Load a JSON fixture file, returning empty dict on failure."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning("Fixture file not found: %s", path)
        return {}
    except json.JSONDecodeError as e:
        logger.error("Fixture JSON parse error in %s: %s", path, e)
        return {}


def _get_jst_fixtures() -> dict:
    global _jst_fixtures
    if _jst_fixtures is None:
        _jst_fixtures = _load_json(_FIXTURES_DIR / "simulated_jst_cases.json")
    return _jst_fixtures


def _get_product_fixtures() -> dict:
    global _product_fixtures
    if _product_fixtures is None:
        _product_fixtures = _load_json(_FIXTURES_DIR / "simulated_product_context.json")
    return _product_fixtures


def reload_fixtures() -> None:
    """Force reload fixture data from disk (useful during development)."""
    global _jst_fixtures, _product_fixtures
    _jst_fixtures = None
    _product_fixtures = None
    _get_jst_fixtures()
    _get_product_fixtures()


# ---------------------------------------------------------------------------
# ID classification
# ---------------------------------------------------------------------------

# Known non-SIM order IDs that are in fixtures
_KNOWN_FIXTURE_ORDER_IDS: set[str] | None = None


def _get_known_fixture_order_ids() -> set[str]:
    global _KNOWN_FIXTURE_ORDER_IDS
    if _KNOWN_FIXTURE_ORDER_IDS is None:
        jst = _get_jst_fixtures()
        _KNOWN_FIXTURE_ORDER_IDS = {
            oid for oid, data in jst.get("orders", {}).items()
            if data.get("found", False)
        }
    return _KNOWN_FIXTURE_ORDER_IDS


def is_fixture_id(id_str: str) -> bool:
    """Check whether an ID refers to fixture data.

    Returns True for:
      - IDs starting with SIM_ prefix
      - Known order/tracking IDs that exist in fixture data
    """
    if not id_str:
        return False
    if id_str.startswith("SIM_"):
        return True
    # Also check if this is a known fixture order ID (e.g. 20260530001)
    return id_str in _get_known_fixture_order_ids()


# ---------------------------------------------------------------------------
# Fixture data retrieval
# ---------------------------------------------------------------------------

def get_fixture_order(order_id: str) -> Optional[dict]:
    """Return fixture order data for the given order ID, or None."""
    if not order_id:
        return None
    jst = _get_jst_fixtures()
    order_data = jst.get("orders", {}).get(order_id)
    if order_data and order_data.get("found", False):
        return order_data
    return None


def get_fixture_logistics(tracking_no: str) -> Optional[dict]:
    """Return fixture logistics data for the given tracking number, or None."""
    if not tracking_no:
        return None
    jst = _get_jst_fixtures()
    logistics_data = jst.get("logistics", {}).get(tracking_no)
    if logistics_data and logistics_data.get("found", False):
        return logistics_data
    return None


def get_fixture_refund(order_id: str) -> Optional[dict]:
    """Return fixture refund data for the given order ID, or None."""
    if not order_id:
        return None
    jst = _get_jst_fixtures()
    refund_data = jst.get("refunds", {}).get(order_id)
    if refund_data and refund_data.get("found", False):
        return refund_data
    return None


def get_fixture_product(product_name: str) -> Optional[dict]:
    """Return fixture product context matching the given name (fuzzy).

    Tries exact key match first, then searches keys and category fields
    for a substring match.
    """
    if not product_name:
        return None
    products = _get_product_fixtures().get("products", {})

    # Exact key match
    if product_name in products:
        return products[product_name]

    # Substring match against keys and names
    name_lower = product_name.lower()
    for key, data in products.items():
        if name_lower in key.lower() or name_lower in data.get("name", "").lower():
            return data
        if name_lower in data.get("category", "").lower():
            return data

    # Keyword-based match for common references
    keyword_map = {
        "垫": "爬行垫",
        "围栏": "游戏围栏",
        "收纳": "收纳柜",
        "套装": "爬行垫+围栏套装",
    }
    for keyword, product_key in keyword_map.items():
        if keyword in name_lower and product_key in products:
            return products[product_key]

    return None


def get_fixture_policy(policy_type: str) -> Optional[dict]:
    """Return fixture policy data for the given type (shipping/returns/refund/installation/promotions)."""
    policies = _get_product_fixtures().get("policies", {})
    return policies.get(policy_type)


# ---------------------------------------------------------------------------
# Context injection
# ---------------------------------------------------------------------------

def inject_fixture_context(
    customer_message: str,
    scenario: str,
    fixtures: dict | None = None,
) -> dict:
    """Build a copilot_context dict from fixture data for offline mode.

    This provides the analysis pipeline with order, logistics, product,
    and policy information without requiring real database or API calls.

    Args:
        customer_message: The customer's message text.
        scenario: The test scenario type (e.g. 'logistics', 'after_sales_return').
        fixtures: Optional override fixtures dict (for testing). If None,
                  loads from default fixture files.

    Returns:
        A copilot_context dict suitable for passing to ReplyService.analyze().
    """
    if fixtures is not None:
        _use_jst = fixtures
        _use_products = fixtures
    else:
        _use_jst = _get_jst_fixtures()
        _use_products = _get_product_fixtures()

    context: dict[str, Any] = {
        "provider": "fixture",
        "scenario": scenario,
    }

    # --- Extract identifiers from message ---
    order_id = _extract_order_id(customer_message, _use_jst)
    tracking_no = _extract_tracking_no(customer_message, _use_jst)
    product_name = _extract_product_name(customer_message)

    # --- Order context ---
    if order_id:
        order_data = _use_jst.get("orders", {}).get(order_id)
        if order_data and order_data.get("found"):
            context["order"] = _sanitize_order(order_data)
            # If order has logistics, inject that too
            lid = order_data.get("l_id", "")
            if lid:
                logistics_data = _use_jst.get("logistics", {}).get(lid)
                if logistics_data and logistics_data.get("found"):
                    context["logistics"] = [_sanitize_logistics(logistics_data)]
            # Refund data
            refund_data = _use_jst.get("refunds", {}).get(order_id)
            if refund_data and refund_data.get("found"):
                context["refund"] = [refund_data]

    # --- Logistics context (if tracking no provided directly) ---
    if tracking_no and "logistics" not in context:
        logistics_data = _use_jst.get("logistics", {}).get(tracking_no)
        if logistics_data and logistics_data.get("found"):
            context["logistics"] = [_sanitize_logistics(logistics_data)]

    # --- Product context ---
    if product_name:
        product_data = _use_products.get("products", {}).get(product_name)
        if product_data:
            context["product_knowledge"] = [product_data]
        else:
            # Try fuzzy match
            matched = get_fixture_product(product_name)
            if matched:
                context["product_knowledge"] = [matched]

    # --- Scenario-specific policy hints ---
    policies = _use_products.get("policies", {})
    if scenario in ("logistics",):
        context["shipping_policy"] = policies.get("shipping", {})
    elif scenario in ("after_sales_return",):
        context["return_policy"] = policies.get("returns", {})
        context["refund_policy"] = policies.get("refund", {})
    elif scenario in ("installation",):
        context["installation_policy"] = policies.get("installation", {})
    elif scenario in ("pre_sale_product",):
        context["product_policy"] = policies.get("promotions", {})

    return context


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

# Order IDs referenced in the simulated customer dialogues
_DIALOGUE_ORDER_IDS = {
    "20260530001", "20260528003", "20260601005",
    "20260602008", "20269999000",
}


def _extract_order_id(message: str, jst_fixtures: dict) -> str:
    """Try to extract an order ID from the customer message."""
    import re

    # Check for explicit order number patterns
    patterns = [
        r"订单[号]?[:：\s]*(\d{10,20})",
        r"订单[号]?[:：\s]*(SIM_\w+)",
        r"订单\s*(\d{10,20})",
    ]
    for pat in patterns:
        m = re.search(pat, message)
        if m:
            return m.group(1)

    # Check if any known fixture order ID appears in the message
    orders = jst_fixtures.get("orders", {})
    for oid in orders:
        if oid in message:
            return oid

    return ""


def _extract_tracking_no(message: str, jst_fixtures: dict) -> str:
    """Try to extract a tracking number from the customer message."""
    import re

    patterns = [
        r"单号[:：\s]*(\d[\w\d]{5,})",
        r"物流单号[:：\s]*(\d[\w\d]{5,})",
        r"运单号[:：\s]*(\d[\w\d]{5,})",
        r"(SF\d{10,})",
        r"(ZT\d{10,})",
        r"(DB\d{10,})",
        r"(SIM_TRACK_\w+)",
    ]
    for pat in patterns:
        m = re.search(pat, message)
        if m:
            return m.group(1)

    # Check if any known fixture tracking ID appears in the message
    logistics = jst_fixtures.get("logistics", {})
    for lid in logistics:
        if lid in message:
            return lid

    return ""


def _extract_product_name(message: str) -> str:
    """Try to extract a product name from the customer message."""
    # Keyword to product name mapping
    keyword_product = {
        "爬行垫": "爬行垫",
        "垫子": "爬行垫",
        "游戏围栏": "游戏围栏",
        "围栏": "游戏围栏",
        "收纳柜": "收纳柜",
        "收纳": "收纳柜",
        "套装": "爬行垫+围栏套装",
    }
    for keyword, product_name in keyword_product.items():
        if keyword in message:
            return product_name
    return ""


def _sanitize_order(order: dict) -> dict:
    """Remove PII fields from order data for fixture context."""
    safe_fields = {
        "o_id", "shop_name", "status", "shop_status", "amount",
        "pay_amount", "freight", "buyer_message", "remark",
        "created", "pay_date", "send_date", "sign_time",
        "logistics_company", "l_id", "items", "refund",
        "partial_shipments", "provider",
    }
    return {k: v for k, v in order.items() if k in safe_fields}


def _sanitize_logistics(logistics: dict) -> dict:
    """Remove unnecessary fields from logistics data for fixture context."""
    safe_fields = {
        "l_id", "logistics_company", "courier_name", "send_date",
        "state_text", "data", "provider",
    }
    return {k: v for k, v in logistics.items() if k in safe_fields}
