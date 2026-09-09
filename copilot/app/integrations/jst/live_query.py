"""
聚水潭实时查询层 — 只读、精确身份验证和受控范围查询。

API 能力说明（基于 2026-05-31 实测）：
- o_ids 参数（orders/single/query）：实测可用精确查询，~400ms，无需时间范围。
  注意：此参数未在官方手册明确列出，属于实测发现能力。如果 API 未来变更导致失效，
  会返回 code!=0 或 found=0，此时直接安全 fallback，不做慢扫。
- so_ids 参数（orders/single/query）：实测可用精确查询，~450ms，需搭配最近7天时间范围。
  同上，属于实测能力。
- orders/out/simple/query：销售出库查询的 so_ids 过滤只可作为查询提示；
  调用方必须逐字段验证返回订单或明细标识，不能把请求参数当作精确命中证明。
  当已有精确店铺范围时，才允许在该店铺的最近修改时间窗口内受控分页。
- sku_ids 参数（sku/query）：实测可用精确查询。
- l_id 参数（logistic/query）：实测 API 忽略此参数，不支持精确查询。
- tracking_no：聚水潭无任何 API 支持按 tracking_no 精确查询。

查询策略：
1. internal_order_id (o_id)  → orders/single/query + o_ids（单次调用）
2. platform_order_id (so_id) → orders/single/query + so_ids + 最近7天（单次调用）
3. platform_trade_id (outer_so_id) → orders/out/simple/query 有界时间扫描 + 精确字段验证
   fallback → orders/single/query outer_so_id scan
4. tracking_no → logistic/query 单页扫描（l_id 匹配）
5. unknown_identifier → outbound_so_id → o_ids → so_ids → outer_so_id scan → logistic/query scan
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Optional

from app.integrations.jst.client import JSTClient
from app.integrations.jst.errors import JSTConfigError, JSTTimeoutError, JSTAPIError

logger = logging.getLogger(__name__)


def _log_api_error(e: JSTAPIError) -> None:
    """Log JST API errors with classification for diagnostics."""
    classification = e.classify()
    if e.is_ip_allowlist_error:
        logger.error(
            "JST network access blocked (code=%s); endpoint=%s; classify=%s",
            e.code,
            e.endpoint,
            classification,
        )
    elif e.is_auth_error:
        logger.error(
            "JST 认证错误 (code=%s): %s. endpoint=%s. 请检查环境变量 JUSHUITAN_APP_KEY, "
            "JUSHUITAN_APP_SECRET, JUSHUITAN_ACCESS_TOKEN 是否正确配置。",
            e.code, e.api_message, e.endpoint,
        )
    else:
        logger.warning("JST API 错误 (code=%s): %s, endpoint=%s", e.code, e.api_message, e.endpoint)


def _safe_api_error_code(error: JSTAPIError) -> str:
    """Return a stable, non-sensitive code for a read-only JST API failure."""
    if error.is_ip_allowlist_error:
        return "jst_ip_allowlist_blocked"
    return str(error.code)

# TTL 缓存
_CACHE_TTL_FOUND = 60   # 成功结果缓存 60s
_CACHE_TTL_MISS = 15     # 失败结果缓存 15s
_cache: dict = {}
_OUTBOUND_SCAN_PAGE_SIZE = 100
_OUTBOUND_SCAN_MAX_PAGES = 20


def _cache_get(key: str):
    entry = _cache.get(key)
    if entry and time.time() - entry["ts"] < entry["ttl"]:
        return entry["val"]
    if entry:
        del _cache[key]
    return None


def _cache_set(key: str, val: dict, found: bool):
    _cache[key] = {"val": val, "ts": time.time(), "ttl": _CACHE_TTL_FOUND if found else _CACHE_TTL_MISS}


def _normalize_shop_label(value: str) -> str:
    return " ".join(str(value or "").split()).casefold()


def _resolve_exact_shop_scope(
    client: JSTClient,
    *,
    shop_id: str = "",
    shop_name: str = "",
) -> dict:
    """Resolve a UI display label to one exact JST shop id for query routing only.

    Shop context never identifies an order or a SKU.  It can only narrow a
    lookup that already has an explicit order identifier.  An empty or
    ambiguous display label therefore fails closed instead of choosing a row.
    """
    explicit_shop_id = str(shop_id or "").strip()
    if explicit_shop_id:
        return {"status": "resolved", "shop_id": explicit_shop_id}

    normalized_name = _normalize_shop_label(shop_name)
    if not normalized_name:
        return {"status": "unscoped", "shop_id": ""}

    cache_key = f"shop_scope:{normalized_name}"
    cached = _cache_get(cache_key)
    if isinstance(cached, dict):
        return dict(cached)

    result = client.call("shops/query", {"page_index": 1, "page_size": 100})
    data = result.get("data") if isinstance(result, dict) else {}
    rows = (data.get("datas") or data.get("shops") or []) if isinstance(data, dict) else []
    matching_ids: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or row.get("enabled") is False:
            continue
        labels = {
            _normalize_shop_label(row.get(field, ""))
            for field in ("shop_name", "name", "shop_nick", "seller_nick", "nick")
        }
        resolved_shop_id = str(row.get("shop_id") or "").strip()
        if resolved_shop_id and normalized_name in labels:
            matching_ids.add(resolved_shop_id)

    if len(matching_ids) == 1:
        scope = {"status": "resolved", "shop_id": next(iter(matching_ids))}
        _cache_set(cache_key, scope, True)
        return dict(scope)

    scope = {
        "status": "ambiguous" if matching_ids else "not_found",
        "shop_id": "",
    }
    _cache_set(cache_key, scope, False)
    return dict(scope)


def _make_result(*, found: bool, data=None, source="jst_live", endpoint="",
                 query_type="", duration_ms=0, error_code=None, error_message=None,
                 safe_fallback_reason=None) -> dict:
    return {
        "found": found,
        "data": data,
        "source": source,
        "endpoint": endpoint,
        "query_type": query_type,
        "duration_ms": duration_ms,
        "error_code": error_code,
        "error_message": error_message,
        "safe_fallback_reason": safe_fallback_reason,
    }


def _resolve_dispatch_shop_scope(*, shop_id: str = "", shop_name: str = "") -> dict:
    """Resolve an optional selected-shop boundary once for a multi-path lookup."""
    explicit_shop_id = str(shop_id or "").strip()
    if explicit_shop_id:
        return {"status": "resolved", "shop_id": explicit_shop_id}
    if not _normalize_shop_label(shop_name):
        return {"status": "unscoped", "shop_id": ""}
    try:
        return _resolve_exact_shop_scope(JSTClient(), shop_name=shop_name)
    except (JSTConfigError, JSTTimeoutError, JSTAPIError) as exc:
        return {"status": "unavailable", "shop_id": "", "error_code": type(exc).__name__}


def _enforce_result_shop_scope(result: dict, *, expected_shop_id: str) -> dict:
    """Reject a successful direct lookup unless its returned order matches scope."""
    if not expected_shop_id or not isinstance(result, dict) or not result.get("found"):
        return result
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    actual_shop_id = str(data.get("shop_id") or "").strip()
    if actual_shop_id == expected_shop_id:
        return result

    rejected = _make_result(
        found=False,
        source=result.get("source", "jst_live"),
        endpoint=result.get("endpoint", ""),
        query_type=result.get("query_type", ""),
        duration_ms=result.get("duration_ms", 0),
        error_code="shop_scope_mismatch",
        safe_fallback_reason="shop_scope_mismatch",
    )
    if isinstance(result.get("attempted_paths"), list):
        rejected["attempted_paths"] = result["attempted_paths"]
    return rejected


def _recent_modified_range(days: int = 6) -> tuple[str, str]:
    """Return a JST-compatible recent modified time range within the 7-day limit."""
    now = datetime.now()
    begin = now - timedelta(days=days)
    return begin.strftime("%Y-%m-%d 00:00:00"), now.strftime("%Y-%m-%d 23:59:59")


def _historical_modified_windows(*, days: int = 75, window_days: int = 6) -> list[tuple[str, str]]:
    """Return backward JST-compatible windows without exceeding the 7-day API range."""
    now = datetime.now()
    windows = []
    cursor_end = now
    remaining = days
    while remaining > 0:
        span = min(window_days, remaining)
        cursor_begin = cursor_end - timedelta(days=span)
        windows.append((
            cursor_begin.strftime("%Y-%m-%d 00:00:00"),
            cursor_end.strftime("%Y-%m-%d 23:59:59"),
        ))
        cursor_end = cursor_begin - timedelta(seconds=1)
        remaining -= span
    return windows


def _safe_order_item(item: dict) -> dict:
    return {
        "sku_id": item.get("sku_id", ""),
        "i_id": item.get("i_id", ""),
        "name": item.get("name", ""),
        "qty": item.get("qty", 0),
        "price": item.get("sale_price", item.get("price", item.get("seller_income_amount", 0))),
    }


def _extract_order_info(order: dict, *, matched_item: dict | None = None) -> dict:
    """从聚水潭订单数据中提取客服所需字段（脱敏）"""
    items = []
    for item in order.get("items", []):
        if isinstance(item, dict):
            items.append(_safe_order_item(item))
    raw_items = order.get("items", [])
    first_raw_item = raw_items[0] if raw_items else {}

    result = {
        "o_id": str(order.get("o_id", "")),
        "io_id": str(order.get("io_id", "")),
        "so_id": str(order.get("so_id", "")),
        "outer_so_id": str(order.get("outer_so_id") or first_raw_item.get("outer_oi_id") or ""),
        "shop_id": order.get("shop_id", ""),
        "shop_name": order.get("shop_name", ""),
        "status": order.get("status", ""),
        "shop_status": order.get("shop_status", ""),
        "amount": order.get("amount", order.get("seller_income_amount", 0)),
        "pay_amount": order.get("pay_amount", order.get("buyer_paid_amount", 0)),
        "freight": order.get("freight", 0),
        "created": order.get("created", ""),
        "pay_date": order.get("pay_date", ""),
        "send_date": order.get("send_date") or order.get("io_date") or "",
        "sign_time": order.get("sign_time", ""),
        "logistics_company": order.get("logistics_company", ""),
        "l_id": order.get("l_id", ""),
        "items": items,
        "remark": order.get("remark", ""),
        "buyer_message": order.get("buyer_message", ""),
    }
    if isinstance(matched_item, dict):
        result["matched_item"] = _safe_order_item(matched_item)
        result["matched_item_reason"] = "exact_jst_order_item"
    return result


def _outbound_identifier_match(
    rows: list[dict],
    identifier: str,
    *,
    expected_shop_id: str = "",
) -> tuple[dict, dict | None] | None:
    """Return one exact order or item match from an outbound query response."""
    target = str(identifier or "").strip()
    if not target:
        return None

    item_matches: list[tuple[dict, dict]] = []
    order_matches: list[tuple[dict, None]] = []
    for order in rows:
        if not isinstance(order, dict):
            continue
        if expected_shop_id and str(order.get("shop_id") or "").strip() != expected_shop_id:
            continue
        if any(
            str(order.get(field) or "").strip() == target
            for field in ("so_id", "o_id", "outer_so_id")
        ):
            order_matches.append((order, None))
        for item in order.get("items") or []:
            if not isinstance(item, dict):
                continue
            if any(
                str(item.get(field) or "").strip() == target
                for field in ("outer_oi_id", "oi_id", "raw_so_id")
            ):
                item_matches.append((order, item))

    if len(item_matches) == 1:
        return item_matches[0]
    if item_matches:
        return None
    if len(order_matches) == 1:
        return order_matches[0]
    return None


def lookup_order_by_order_id(o_id: str) -> dict:
    """按聚水潭订单号 o_id 精确查询 — 单次 API 调用，~400ms"""
    if not o_id:
        return _make_result(found=False, query_type="order_id", safe_fallback_reason="empty_id")
    if not str(o_id).strip().isdigit():
        return _make_result(found=False, query_type="order_id", safe_fallback_reason="non_numeric_o_id")

    cache_key = f"oid:{o_id}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    client = JSTClient()
    t0 = time.time()
    try:
        result = client.call("orders/single/query", {
            "page_index": 1,
            "page_size": 10,
            "o_ids": [str(o_id)],
        })
        orders = result.get("data", {}).get("orders", [])
        duration_ms = int((time.time() - t0) * 1000)

        matched = [
            order for order in orders
            if str(order.get("o_id") or "").strip() == str(o_id).strip()
        ]
        if len(matched) == 1:
            data = _extract_order_info(matched[0])
            r = _make_result(found=True, data=data, endpoint="orders/single/query",
                             query_type="order_id", duration_ms=duration_ms)
        else:
            r = _make_result(found=False, endpoint="orders/single/query",
                             query_type="order_id", duration_ms=duration_ms,
                             safe_fallback_reason=(
                                 "not_found" if not orders else "o_id_not_matched"
                             ))

    except JSTConfigError:
        duration_ms = int((time.time() - t0) * 1000)
        r = _make_result(found=False, query_type="order_id", duration_ms=duration_ms,
                         error_code="config_missing", safe_fallback_reason="jst_not_configured")
    except JSTTimeoutError as e:
        duration_ms = int((time.time() - t0) * 1000)
        r = _make_result(found=False, query_type="order_id", duration_ms=duration_ms,
                         error_code="timeout", error_message=str(e), safe_fallback_reason="jst_timeout")
    except JSTAPIError as e:
        duration_ms = int((time.time() - t0) * 1000)
        _log_api_error(e)
        code = _safe_api_error_code(e)
        r = _make_result(found=False, query_type="order_id", duration_ms=duration_ms,
                         error_code=code, error_message=e.api_message, safe_fallback_reason=code)

    _cache_set(cache_key, r, r["found"])
    return r


def lookup_order_by_platform_order_id(so_id: str) -> dict:
    """按平台/店铺订单号 so_id 精确查询 — 单次 API 调用，~450ms"""
    if not so_id:
        return _make_result(found=False, query_type="platform_order_id", safe_fallback_reason="empty_id")

    cache_key = f"soid:{so_id}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    client = JSTClient()
    t0 = time.time()
    now = datetime.now()
    week_ago = now - timedelta(days=6)

    try:
        result = client.call("orders/single/query", {
            "page_index": 1,
            "page_size": 10,
            "so_ids": [str(so_id)],
            "modified_begin": week_ago.strftime("%Y-%m-%d 00:00:00"),
            "modified_end": now.strftime("%Y-%m-%d 23:59:59"),
        })
        orders = result.get("data", {}).get("orders", [])
        duration_ms = int((time.time() - t0) * 1000)

        matched = [
            order for order in orders
            if str(order.get("so_id") or "").strip() == str(so_id).strip()
        ]
        if len(matched) == 1:
            data = _extract_order_info(matched[0])
            r = _make_result(found=True, data=data, endpoint="orders/single/query",
                             query_type="platform_order_id", duration_ms=duration_ms)
        else:
            r = _make_result(found=False, endpoint="orders/single/query",
                             query_type="platform_order_id", duration_ms=duration_ms,
                             safe_fallback_reason=(
                                 "not_found" if not orders else "so_id_not_matched"
                             ))

    except (JSTConfigError, JSTTimeoutError, JSTAPIError) as e:
        duration_ms = int((time.time() - t0) * 1000)
        if isinstance(e, JSTAPIError):
            _log_api_error(e)
        code = "config_missing" if isinstance(e, JSTConfigError) else "timeout" if isinstance(e, JSTTimeoutError) else _safe_api_error_code(e)
        r = _make_result(found=False, query_type="platform_order_id", duration_ms=duration_ms,
                         error_code=code, error_message=str(e),
                         safe_fallback_reason=code)

    _cache_set(cache_key, r, r["found"])
    return r


def lookup_order_by_platform_order_id_history(so_id: str, *, days: int = 75) -> dict:
    """Search an older platform order id with exact so_ids over bounded history."""
    if not so_id:
        return _make_result(found=False, query_type="platform_order_id_history", safe_fallback_reason="empty_id")

    cache_key = f"soid_hist:{days}:{so_id}"
    cached = _cache_get(cache_key)
    if cached is not None:
        cached_copy = dict(cached)
        cached_copy["attempted_paths"] = list(cached.get("attempted_paths", []))
        return cached_copy

    client = JSTClient()
    t0 = time.time()
    attempted_paths = []
    last_error_code = None
    last_error_message = None

    try:
        for modified_begin, modified_end in _historical_modified_windows(days=days):
            start = time.time()
            result = client.call("orders/single/query", {
                "page_index": 1,
                "page_size": 10,
                "so_ids": [str(so_id)],
                "modified_begin": modified_begin,
                "modified_end": modified_end,
            })
            orders = result.get("data", {}).get("orders", [])
            duration_ms = int((time.time() - start) * 1000)
            matched = [o for o in orders if str(o.get("so_id") or "").strip() == str(so_id).strip()]
            order = matched[0] if len(matched) == 1 else None
            attempted_paths.append({
                "query_type": "platform_order_id_history",
                "endpoint": "orders/single/query",
                "found": bool(order),
                "duration_ms": duration_ms,
                "modified_begin": modified_begin,
                "modified_end": modified_end,
                "error_code": None,
                "safe_fallback_reason": None if order else "not_found_in_window",
            })
            if order:
                r = _make_result(
                    found=True,
                    data=_extract_order_info(order),
                    endpoint="orders/single/query",
                    query_type="platform_order_id_history",
                    duration_ms=int((time.time() - t0) * 1000),
                )
                r["attempted_paths"] = attempted_paths
                _cache_set(cache_key, r, True)
                r_copy = dict(r)
                r_copy["attempted_paths"] = list(r.get("attempted_paths", []))
                return r_copy

    except (JSTConfigError, JSTTimeoutError, JSTAPIError) as e:
        duration_ms = int((time.time() - t0) * 1000)
        if isinstance(e, JSTAPIError):
            _log_api_error(e)
        last_error_code = "config_missing" if isinstance(e, JSTConfigError) else "timeout" if isinstance(e, JSTTimeoutError) else _safe_api_error_code(e)
        last_error_message = str(e)
        attempted_paths.append({
            "query_type": "platform_order_id_history",
            "endpoint": "orders/single/query",
            "found": False,
            "duration_ms": duration_ms,
            "error_code": last_error_code,
            "safe_fallback_reason": last_error_code,
        })

    r = _make_result(
        found=False,
        endpoint="orders/single/query",
        query_type="platform_order_id_history",
        duration_ms=int((time.time() - t0) * 1000),
        error_code=last_error_code,
        error_message=last_error_message,
        safe_fallback_reason=last_error_code or "not_found_in_75d_history",
    )
    r["attempted_paths"] = attempted_paths
    _cache_set(cache_key, r, False)
    r_copy = dict(r)
    r_copy["attempted_paths"] = list(r.get("attempted_paths", []))
    return r_copy


def lookup_order_by_outer_so_id(outer_so_id: str, *, max_pages: int = 5) -> dict:
    """Find an order by JST outer_so_id via a bounded recent order scan.

    The JST UI exposes "external transaction no" separately from so_id. The
    public order endpoint does not appear to support an exact outer_so_id
    parameter, so this scans recent orders and requires an exact returned
    field match.  Substring similarity is not an identity proof.
    """
    if not outer_so_id:
        return _make_result(found=False, query_type="outer_so_id", safe_fallback_reason="empty_id")

    cache_key = f"outer:{outer_so_id}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    client = JSTClient()
    t0 = time.time()
    now = datetime.now()
    week_ago = now - timedelta(days=6)
    target = str(outer_so_id).strip()

    try:
        for page_index in range(1, max_pages + 1):
            result = client.call("orders/single/query", {
                "page_index": page_index,
                "page_size": 100,
                "modified_begin": week_ago.strftime("%Y-%m-%d 00:00:00"),
                "modified_end": now.strftime("%Y-%m-%d 23:59:59"),
            })
            orders = result.get("data", {}).get("orders", [])
            for order in orders:
                candidate = str(order.get("outer_so_id") or "").strip()
                if candidate == target:
                    duration_ms = int((time.time() - t0) * 1000)
                    r = _make_result(
                        found=True,
                        data=_extract_order_info(order),
                        endpoint="orders/single/query",
                        query_type="outer_so_id_scan",
                        duration_ms=duration_ms,
                    )
                    _cache_set(cache_key, r, True)
                    return r

            if len(orders) < 100:
                break

        duration_ms = int((time.time() - t0) * 1000)
        r = _make_result(
            found=False,
            endpoint="orders/single/query",
            query_type="outer_so_id_scan",
            duration_ms=duration_ms,
            safe_fallback_reason="outer_so_id_not_found_in_recent_orders",
        )

    except (JSTConfigError, JSTTimeoutError, JSTAPIError) as e:
        duration_ms = int((time.time() - t0) * 1000)
        if isinstance(e, JSTAPIError):
            _log_api_error(e)
        code = "config_missing" if isinstance(e, JSTConfigError) else "timeout" if isinstance(e, JSTTimeoutError) else _safe_api_error_code(e)
        r = _make_result(
            found=False,
            endpoint="orders/single/query",
            query_type="outer_so_id_scan",
            duration_ms=duration_ms,
            error_code=code,
            error_message=str(e),
            safe_fallback_reason=code,
        )

    _cache_set(cache_key, r, r["found"])
    return r


def lookup_outbound_by_so_id(
    so_id: str,
    *,
    shop_id: str = "",
    shop_name: str = "",
) -> dict:
    """Resolve an outbound order using an exact identifier and an optional shop scope.

    ``so_ids`` narrows the first provider request but cannot prove identity by
    itself.  Every accepted result must still have exactly one matching
    order-level or line-level identifier.  If an explicit shop scope is known,
    a bounded recent-window pagination follows a direct miss; an unscoped
    request never expands into a company-wide list scan.
    """
    target = str(so_id or "").strip()
    if not target:
        return _make_result(found=False, query_type="outbound_so_id", safe_fallback_reason="empty_id")

    client = JSTClient()
    t0 = time.time()
    active_endpoint = "orders/out/simple/query"
    attempts: list[dict] = []
    try:
        active_endpoint = "shops/query"
        scope = _resolve_exact_shop_scope(
            client,
            shop_id=shop_id,
            shop_name=shop_name,
        )
        scope_status = scope.get("status")
        resolved_shop_id = str(scope.get("shop_id") or "").strip()
        if scope_status in {"ambiguous", "not_found"}:
            r = _make_result(
                found=False,
                endpoint="shops/query",
                query_type="outbound_so_id",
                duration_ms=int((time.time() - t0) * 1000),
                safe_fallback_reason=f"shop_scope_{scope_status}",
            )
            _cache_set(f"outso:{target}|shop_name:{_normalize_shop_label(shop_name)}", r, False)
            return r

        cache_key = f"outso:{target}|shop:{resolved_shop_id or 'unscoped'}"
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

        active_endpoint = "orders/out/simple/query"
        direct_params = {
            "page_index": 1,
            "page_size": _OUTBOUND_SCAN_PAGE_SIZE,
            "so_ids": [target],
        }
        if resolved_shop_id:
            direct_params["shop_id"] = resolved_shop_id
        direct_result = client.call("orders/out/simple/query", direct_params)
        direct_rows = direct_result.get("data", {}).get("datas", [])
        attempts.append({
            "endpoint": "orders/out/simple/query",
            "stage": "direct_identifier_hint",
            "page_index": 1,
            "found": False,
        })
        matched = _outbound_identifier_match(
            direct_rows,
            target,
            expected_shop_id=resolved_shop_id,
        )
        if matched:
            row, matched_item = matched
            data = _extract_order_info(row, matched_item=matched_item)
            r = _make_result(
                found=True,
                data=data,
                endpoint="orders/out/simple/query",
                query_type="outbound_so_id",
                duration_ms=int((time.time() - t0) * 1000),
            )
            attempts[-1]["found"] = True
            r["attempted_paths"] = attempts
            _cache_set(cache_key, r, True)
            return r

        # Do not broaden an unscoped lookup.  The selected shop only narrows
        # an already explicit order identifier; it is never an identity source.
        if not resolved_shop_id:
            r = _make_result(
                found=False,
                endpoint="orders/out/simple/query",
                query_type="outbound_so_id",
                duration_ms=int((time.time() - t0) * 1000),
                safe_fallback_reason=(
                    "outbound_identifier_not_matched" if direct_rows else "not_found"
                ),
            )
            r["attempted_paths"] = attempts
            _cache_set(cache_key, r, False)
            return r

        modified_begin, modified_end = _recent_modified_range()
        for page_index in range(1, _OUTBOUND_SCAN_MAX_PAGES + 1):
            scan_result = client.call("orders/out/simple/query", {
                "shop_id": resolved_shop_id,
                "page_index": page_index,
                "page_size": _OUTBOUND_SCAN_PAGE_SIZE,
                "modified_begin": modified_begin,
                "modified_end": modified_end,
            })
            rows = scan_result.get("data", {}).get("datas", [])
            attempts.append({
                "endpoint": "orders/out/simple/query",
                "stage": "scoped_recent_scan",
                "page_index": page_index,
                "found": False,
            })
            matched = _outbound_identifier_match(
                rows,
                target,
                expected_shop_id=resolved_shop_id,
            )
            if matched:
                row, matched_item = matched
                data = _extract_order_info(row, matched_item=matched_item)
                r = _make_result(
                    found=True,
                    data=data,
                    endpoint="orders/out/simple/query",
                    query_type="outbound_so_id",
                    duration_ms=int((time.time() - t0) * 1000),
                )
                attempts[-1]["found"] = True
                r["attempted_paths"] = attempts
                _cache_set(cache_key, r, True)
                return r
            if len(rows) < _OUTBOUND_SCAN_PAGE_SIZE:
                r = _make_result(
                    found=False,
                    endpoint="orders/out/simple/query",
                    query_type="outbound_so_id",
                    duration_ms=int((time.time() - t0) * 1000),
                    safe_fallback_reason=(
                        "outbound_identifier_not_matched" if rows or direct_rows else "not_found"
                    ),
                )
                r["attempted_paths"] = attempts
                _cache_set(cache_key, r, False)
                return r

        r = _make_result(
            found=False,
            endpoint="orders/out/simple/query",
            query_type="outbound_so_id",
            duration_ms=int((time.time() - t0) * 1000),
            safe_fallback_reason="outbound_scoped_scan_incomplete",
        )
        r["attempted_paths"] = attempts

    except (JSTConfigError, JSTTimeoutError, JSTAPIError) as e:
        duration_ms = int((time.time() - t0) * 1000)
        if isinstance(e, JSTAPIError):
            _log_api_error(e)
        code = "config_missing" if isinstance(e, JSTConfigError) else "timeout" if isinstance(e, JSTTimeoutError) else _safe_api_error_code(e)
        r = _make_result(
            found=False,
            endpoint=active_endpoint,
            query_type="outbound_so_id",
            duration_ms=duration_ms,
            error_code=code,
            error_message=str(e),
            safe_fallback_reason=code,
        )
        if attempts:
            r["attempted_paths"] = attempts

    _cache_set(cache_key if "cache_key" in locals() else f"outso:{target}", r, r["found"])
    return r


def lookup_logistics_by_tracking_no(tracking_no: str) -> dict:
    """按快递单号查询 — 单页扫描最近7天物流记录匹配 l_id，然后回查完整订单。

    聚水潭 logistic/query 不支持按 l_id 精确过滤（参数被 API 忽略），
    所以用单页扫描（1 次 API 调用，~700ms）匹配 tracking_no。
    匹配到后用 o_id 回查完整订单。
    只扫最近 7 天第 1 页（100 条），不做多周多页扫描。
    """
    if not tracking_no:
        return _make_result(found=False, query_type="tracking_no", safe_fallback_reason="empty_id")

    cache_key = f"tn:{tracking_no}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    client = JSTClient()
    t0 = time.time()
    now = datetime.now()
    week_ago = now - timedelta(days=6)

    try:
        result = client.call("logistic/query", {
            "page_index": 1,
            "page_size": 100,
            "modified_begin": week_ago.strftime("%Y-%m-%d 00:00:00"),
            "modified_end": now.strftime("%Y-%m-%d 23:59:59"),
        })
        orders = result.get("data", {}).get("orders", [])
        scan_ms = int((time.time() - t0) * 1000)

        # 在返回的物流记录中精确匹配 l_id
        target_upper = tracking_no.strip().upper()
        matched = None
        for o in orders:
            lid = str(o.get("l_id", "")).strip().upper()
            if lid and lid == target_upper:
                matched = o
                break

        if not matched:
            r = _make_result(
                found=False,
                endpoint="logistic/query",
                query_type="tracking_no",
                duration_ms=scan_ms,
                safe_fallback_reason="tracking_no_not_found_in_recent_7d",
            )
            _cache_set(cache_key, r, False)
            return r

        # 匹配到 → 用 o_id 回查完整订单
        o_id = str(matched.get("o_id", ""))
        if o_id:
            order_result = lookup_order_by_order_id(o_id)
            total_ms = int((time.time() - t0) * 1000)
            if order_result["found"]:
                order_result["query_type"] = "tracking_no→order_id"
                order_result["duration_ms"] = total_ms
                _cache_set(cache_key, order_result, True)
                return order_result

        # 匹配到 l_id 但回查订单失败 → 返回物流记录中的基本信息
        duration_ms = int((time.time() - t0) * 1000)
        data = {
            "o_id": o_id,
            "status": matched.get("status", ""),
            "logistics_company": matched.get("logistics_company", ""),
            "l_id": matched.get("l_id", ""),
            "send_date": matched.get("send_date", ""),
            "items": [],
        }
        r = _make_result(
            found=True, data=data, endpoint="logistic/query",
            query_type="tracking_no_scan", duration_ms=duration_ms,
        )
        _cache_set(cache_key, r, True)
        return r

    except (JSTConfigError, JSTTimeoutError, JSTAPIError) as e:
        duration_ms = int((time.time() - t0) * 1000)
        if isinstance(e, JSTAPIError):
            _log_api_error(e)
        r = _make_result(found=False, query_type="tracking_no", duration_ms=duration_ms,
                         error_code=type(e).__name__, safe_fallback_reason=type(e).__name__)
        _cache_set(cache_key, r, False)
        return r


def lookup_order_by_identifier(identifier: str, identifier_type: str, *, exhaustive: bool = True) -> dict:
    """根据 identifier_type 分发到对应查询函数。
    order_id 类型查不到时自动尝试 so_ids（用户给的平台订单号可能被识别为 order_id）。
    """
    if not identifier:
        return _make_result(found=False, query_type=identifier_type, safe_fallback_reason="empty_id")

    if identifier_type == "order_id":
        # 先按 o_ids 查，查不到自动按 so_ids 再查
        r1 = lookup_order_by_order_id(identifier)
        if r1["found"]:
            return r1
        r2 = lookup_order_by_platform_order_id(identifier)
        if r2["found"]:
            r2["query_type"] = "order_id→so_id_fallback"
            return r2
        total_ms = r1.get("duration_ms", 0) + r2.get("duration_ms", 0)
        return _make_result(
            found=False, query_type="order_id", duration_ms=total_ms,
            safe_fallback_reason="not_found",
        )

    if identifier_type == "platform_order_id":
        r1 = lookup_order_by_platform_order_id(identifier)
        if r1["found"]:
            return r1
        r2 = lookup_order_by_order_id(identifier)
        if r2["found"]:
            r2["query_type"] = "platform_order_id→o_id_fallback"
            return r2
        total_ms = r1.get("duration_ms", 0) + r2.get("duration_ms", 0)
        return _make_result(
            found=False, query_type="platform_order_id", duration_ms=total_ms,
            safe_fallback_reason="not_found",
        )

    if identifier_type == "tracking_no":
        return lookup_logistics_by_tracking_no(identifier)

    # unknown_identifier: 依次尝试 o_id → so_id（最多 2 次调用，~1s）
    r1 = lookup_order_by_order_id(identifier)
    if r1["found"]:
        r1["query_type"] = "unknown→order_id"
        return r1

    r2 = lookup_order_by_platform_order_id(identifier)
    if r2["found"]:
        r2["query_type"] = "unknown→platform_order_id"
        return r2

    # 最后尝试 tracking_no 单页扫描
    r3 = lookup_logistics_by_tracking_no(identifier)
    if r3["found"]:
        r3["query_type"] = "unknown→tracking_no_scan"
        return r3

    total_ms = r1.get("duration_ms", 0) + r2.get("duration_ms", 0) + r3.get("duration_ms", 0)
    return _make_result(
        found=False,
        query_type="unknown_identifier",
        duration_ms=total_ms,
        safe_fallback_reason="not_found_by_any_path",
    )


def lookup_product_by_sku(sku_id: str) -> dict:
    """按商家 SKU 编码查询商品。

    Some JST tenants reject alphanumeric merchant SKU values in the undocumented
    ``sku_ids`` exact parameter. When that happens, fall back to the documented
    7-day modified window and match ``sku_id`` locally.
    """
    if not sku_id:
        return _make_result(found=False, query_type="sku", safe_fallback_reason="empty_id")

    client = JSTClient()
    t0 = time.time()
    target = str(sku_id).strip()

    try:
        # sku_ids 精确查询（实测能力，非手册明确参数）
        result = client.call("sku/query", {
            "page_index": 1,
            "page_size": 10,
            "sku_ids": [target],
        })
        datas = result.get("data", {}).get("datas", [])
        duration_ms = int((time.time() - t0) * 1000)

        if datas:
            matched = [row for row in datas if str(row.get("sku_id") or "").strip() == target]
            return _make_result(found=True, data=matched[0] if matched else datas[0], endpoint="sku/query",
                                query_type="sku", duration_ms=duration_ms)

        return _make_result(found=False, endpoint="sku/query", query_type="sku",
                            duration_ms=duration_ms, safe_fallback_reason="not_found")

    except (JSTConfigError, JSTTimeoutError, JSTAPIError) as e:
        if isinstance(e, JSTConfigError):
            duration_ms = int((time.time() - t0) * 1000)
            return _make_result(found=False, query_type="sku", duration_ms=duration_ms,
                                error_code="config_missing", error_message=str(e),
                                safe_fallback_reason="config_missing")

        first_error_code = "timeout" if isinstance(e, JSTTimeoutError) else _safe_api_error_code(e)
        first_error_message = str(e)

    modified_begin, modified_end = _recent_modified_range()
    try:
        result = client.call("sku/query", {
            "page_index": 1,
            "page_size": 100,
            "modified_begin": modified_begin,
            "modified_end": modified_end,
        })
        rows = _extract_datas(result)
        duration_ms = int((time.time() - t0) * 1000)
        for row in rows:
            if str(row.get("sku_id") or "").strip() == target:
                r = _make_result(found=True, data=row, endpoint="sku/query",
                                 query_type="sku_recent_modified_scan",
                                 duration_ms=duration_ms)
                r["attempted_paths"] = [
                    {
                        "query_type": "sku:sku_ids",
                        "endpoint": "sku/query",
                        "found": False,
                        "error_code": first_error_code,
                        "safe_fallback_reason": first_error_code,
                    },
                    {
                        "query_type": "sku:recent_modified_scan",
                        "endpoint": "sku/query",
                        "found": True,
                        "rows": len(rows),
                    },
                ]
                return r

        r = _make_result(found=False, endpoint="sku/query",
                         query_type="sku_recent_modified_scan",
                         duration_ms=duration_ms,
                         error_code=first_error_code,
                         error_message=first_error_message,
                         safe_fallback_reason="not_found_in_recent_skus")
        r["attempted_paths"] = [
            {
                "query_type": "sku:sku_ids",
                "endpoint": "sku/query",
                "found": False,
                "error_code": first_error_code,
                "safe_fallback_reason": first_error_code,
            },
            {
                "query_type": "sku:recent_modified_scan",
                "endpoint": "sku/query",
                "found": False,
                "rows": len(rows),
                "safe_fallback_reason": "not_found_in_recent_skus",
            },
        ]
        return r
    except (JSTTimeoutError, JSTAPIError) as e:
        duration_ms = int((time.time() - t0) * 1000)
        if isinstance(e, JSTAPIError):
            _log_api_error(e)
        code = "timeout" if isinstance(e, JSTTimeoutError) else _safe_api_error_code(e)
        return _make_result(found=False, endpoint="sku/query", query_type="sku",
                            duration_ms=duration_ms, error_code=code,
                            error_message=str(e),
                            safe_fallback_reason=code)


def lookup_product_by_i_id(i_id: str) -> dict:
    """按聚水潭款号 i_id 精确查询商品。"""
    if not i_id:
        return _make_result(found=False, query_type="i_id", safe_fallback_reason="empty_id")

    cache_key = f"iid:{i_id}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    client = JSTClient()
    t0 = time.time()

    try:
        result = client.call("mall/item/query", {
            "page_index": 1,
            "page_size": 10,
            "i_ids": [str(i_id)],
        })
        rows = _extract_datas(result)
        duration_ms = int((time.time() - t0) * 1000)

        if rows:
            matched = [row for row in rows if str(row.get("i_id") or "").strip() == str(i_id)]
            row = matched[0] if matched else rows[0]
            r = _make_result(found=True, data=row, endpoint="mall/item/query",
                             query_type="i_id", duration_ms=duration_ms)
        else:
            r = _make_result(found=False, endpoint="mall/item/query", query_type="i_id",
                             duration_ms=duration_ms, safe_fallback_reason="not_found")

    except (JSTConfigError, JSTTimeoutError, JSTAPIError) as e:
        duration_ms = int((time.time() - t0) * 1000)
        if isinstance(e, JSTAPIError):
            _log_api_error(e)
        code = "config_missing" if isinstance(e, JSTConfigError) else "timeout" if isinstance(e, JSTTimeoutError) else _safe_api_error_code(e)
        r = _make_result(found=False, endpoint="mall/item/query", query_type="i_id",
                         duration_ms=duration_ms, error_code=code,
                         error_message=str(e), safe_fallback_reason=code)

    _cache_set(cache_key, r, r["found"])
    return r


def _extract_datas(result: dict) -> list[dict]:
    data = result.get("data", {}) if isinstance(result, dict) else {}
    for key in ("datas", "items", "skus", "sku_maps", "rows"):
        rows = data.get(key)
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, dict)]
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    return []


def _product_name_match_score(row: dict, query: str) -> float:
    query = str(query or "").strip().lower()
    name = str(
        row.get("name")
        or row.get("title")
        or row.get("item_name")
        or row.get("shop_i_name")
        or row.get("sku_name")
        or ""
    ).strip().lower()
    if not query or not name:
        return 0.0
    if name in query or query in name:
        return 1.0
    q_chars = {ch for ch in query if "\u4e00" <= ch <= "\u9fff"}
    n_chars = {ch for ch in name if "\u4e00" <= ch <= "\u9fff"}
    if not n_chars or not q_chars:
        return 0.0
    return len(q_chars & n_chars) / max(len(n_chars), 1)


def lookup_product_by_name(product_name: str) -> dict:
    """Resolve a visible product title/name to JST internal product fields.

    QianNiu platform item ids are not used here because they are platform-local
    and cannot be trusted as JST lookup keys. The API query is bounded and the
    returned rows are accepted only when the product name/title matches.
    """
    product_name = str(product_name or "").strip()
    if not product_name:
        return _make_result(found=False, query_type="product_name", safe_fallback_reason="empty_name")

    cache_key = f"product_name:{product_name}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    modified_begin, modified_end = _recent_modified_range()
    attempts = [
        ("skumap/query", {
            "page_index": 1,
            "page_size": 100,
            "modified_begin": modified_begin,
            "modified_end": modified_end,
        }),
        ("mall/item/query", {
            "page_index": 1,
            "page_size": 100,
            "modified_begin": modified_begin,
            "modified_end": modified_end,
        }),
        ("sku/query", {
            "page_index": 1,
            "page_size": 100,
            "modified_begin": modified_begin,
            "modified_end": modified_end,
        }),
    ]
    attempted_paths = []
    client = JSTClient()
    t0 = time.time()
    last_error_code = None
    last_error_message = None

    for endpoint, biz in attempts:
        start = time.time()
        try:
            result = client.call(endpoint, biz)
            rows = _extract_datas(result)
            scored = sorted(
                [(_product_name_match_score(row, product_name), idx, row) for idx, row in enumerate(rows)],
                key=lambda x: (-x[0], x[1]),
            )
            best_score = scored[0][0] if scored else 0.0
            best_row = scored[0][2] if scored and best_score >= 0.55 else None
            duration_ms = int((time.time() - start) * 1000)
            attempted_paths.append({
                "query_type": "product_name:recent_modified_scan",
                "endpoint": endpoint,
                "found": bool(best_row),
                "duration_ms": duration_ms,
                "score": round(best_score, 3),
                "rows": len(rows),
                "error_code": None,
                "safe_fallback_reason": None if best_row else "not_found_or_low_score",
            })
            if best_row:
                total_ms = int((time.time() - t0) * 1000)
                r = _make_result(
                    found=True,
                    data=best_row,
                    endpoint=endpoint,
                    query_type=f"product_name->{endpoint}:recent_modified_scan",
                    duration_ms=total_ms,
                )
                r["confidence"] = round(best_score, 3)
                r["attempted_paths"] = attempted_paths
                _cache_set(cache_key, r, True)
                return r
        except (JSTConfigError, JSTTimeoutError, JSTAPIError) as e:
            duration_ms = int((time.time() - start) * 1000)
            if isinstance(e, JSTAPIError):
                _log_api_error(e)
            last_error_code = "config_missing" if isinstance(e, JSTConfigError) else "timeout" if isinstance(e, JSTTimeoutError) else _safe_api_error_code(e)
            last_error_message = str(e)
            attempted_paths.append({
                "query_type": "product_name:recent_modified_scan",
                "endpoint": endpoint,
                "found": False,
                "duration_ms": duration_ms,
                "error_code": last_error_code,
                "safe_fallback_reason": last_error_code,
            })
            if isinstance(e, JSTConfigError):
                break

    total_ms = int((time.time() - t0) * 1000)
    r = _make_result(
        found=False,
        endpoint="mall/item/query|sku/query",
        query_type="product_name",
        duration_ms=total_ms,
        error_code=last_error_code,
        error_message=last_error_message,
        safe_fallback_reason=last_error_code or "not_found",
    )
    r["attempted_paths"] = attempted_paths
    _cache_set(cache_key, r, False)
    return r


def _attempt_debug(*results: dict) -> list:
    return [
        {
            "query_type": r.get("query_type", ""),
            "endpoint": r.get("endpoint", ""),
            "found": bool(r.get("found")),
            "duration_ms": r.get("duration_ms", 0),
            "error_code": r.get("error_code"),
            "safe_fallback_reason": r.get("safe_fallback_reason"),
        }
        for r in results
        if r
    ]


def _aggregate_lookup_miss(
    identifier_type: str,
    *results: dict,
    fallback_reason: str,
) -> dict:
    """Return not-found only when every bounded lookup path completed cleanly."""
    attempts = _attempt_debug(*results)
    duration_ms = sum(int(result.get("duration_ms") or 0) for result in results if result)
    provider_failure = next(
        (result for result in results if result and result.get("error_code")),
        None,
    )
    if provider_failure:
        merged = _make_result(
            found=False,
            endpoint=provider_failure.get("endpoint", ""),
            query_type=identifier_type,
            duration_ms=duration_ms,
            error_code=provider_failure.get("error_code"),
            error_message=provider_failure.get("error_message"),
            safe_fallback_reason=(
                provider_failure.get("safe_fallback_reason")
                or provider_failure.get("error_code")
            ),
        )
    else:
        merged = _make_result(
            found=False,
            query_type=identifier_type,
            duration_ms=duration_ms,
            safe_fallback_reason=fallback_reason,
        )
    merged["attempted_paths"] = attempts
    return merged


# Keep this definition after the legacy dispatcher above so imports use the
# full identifier surface, including JST outer_so_id ("external transaction no").
def _lookup_outbound_for_identifier(
    identifier: str,
    *,
    shop_id: str = "",
    shop_name: str = "",
) -> dict:
    kwargs = {}
    if str(shop_id or "").strip():
        kwargs["shop_id"] = str(shop_id).strip()
    if str(shop_name or "").strip():
        kwargs["shop_name"] = str(shop_name).strip()
    return lookup_outbound_by_so_id(identifier, **kwargs)


def lookup_order_by_identifier(
    identifier: str,
    identifier_type: str,
    *,
    exhaustive: bool = True,
    shop_id: str = "",
    shop_name: str = "",
) -> dict:
    """Dispatch identifier lookup across all known JST order id surfaces.

    Routing:
      internal_order_id  → o_ids → so_ids fallback → outbound → outer scan
      platform_order_id  → o_ids first（当前千牛/聚水潭同号）→ so_ids fallback → outbound → outer scan
      platform_trade_id  → outbound_so_id → o_ids/so_ids fallback → outer_so_id scan
      tracking_no        → logistic/query scan
      unknown_identifier → outbound → o_ids → so_ids → outer scan → logistic scan
    """
    if not identifier:
        return _make_result(found=False, query_type=identifier_type, safe_fallback_reason="empty_id")

    scope = _resolve_dispatch_shop_scope(shop_id=shop_id, shop_name=shop_name)
    scope_status = str(scope.get("status") or "")
    resolved_shop_id = str(scope.get("shop_id") or "").strip()
    scope_limits_expansion = scope_status in {"ambiguous", "not_found", "unavailable"}
    scope_limit_reason = f"shop_scope_{scope_status}" if scope_limits_expansion else ""

    def scoped(result: dict) -> dict:
        return _enforce_result_shop_scope(result, expected_shop_id=resolved_shop_id)

    outbound_scope = {"shop_id": resolved_shop_id} if resolved_shop_id else {}

    if identifier_type == "internal_order_id":
        r1 = scoped(lookup_order_by_order_id(identifier))
        if r1["found"]:
            return r1

        r2 = scoped(lookup_order_by_platform_order_id(identifier))
        if r2["found"]:
            r2["query_type"] = "internal_order_id->so_id_fallback"
            r2["attempted_paths"] = _attempt_debug(r1, r2)
            return r2

        r_out = scoped(_lookup_outbound_for_identifier(identifier, **outbound_scope))
        if r_out["found"]:
            r_out["query_type"] = "internal_order_id->outbound_so_id_fallback"
            r_out["attempted_paths"] = _attempt_debug(r1, r2, r_out)
            return r_out

        r3 = scoped(lookup_order_by_outer_so_id(identifier))
        if r3["found"]:
            r3["query_type"] = "internal_order_id->outer_so_id_fallback"
            r3["attempted_paths"] = _attempt_debug(r1, r2, r_out, r3)
            return r3

        return _aggregate_lookup_miss(
            "internal_order_id",
            r1,
            r2,
            r_out,
            r3,
            fallback_reason="not_found",
        )

    if identifier_type == "platform_order_id":
        r1 = scoped(lookup_order_by_order_id(identifier))
        if r1["found"]:
            r1["query_type"] = "platform_order_id->same_order_id"
            return r1

        r2 = scoped(lookup_order_by_platform_order_id(identifier))
        if r2["found"]:
            r2["query_type"] = "platform_order_id->so_id_fallback"
            r2["attempted_paths"] = _attempt_debug(r1, r2)
            return r2

        r_hist = scoped(lookup_order_by_platform_order_id_history(identifier))
        if r_hist["found"]:
            r_hist["query_type"] = "platform_order_id->so_id_history_fallback"
            r_hist["attempted_paths"] = _attempt_debug(r1, r2) + r_hist.get("attempted_paths", [])
            return r_hist

        r_out = scoped(_lookup_outbound_for_identifier(identifier, **outbound_scope))
        if r_out["found"]:
            r_out["query_type"] = "platform_order_id->outbound_so_id_fallback"
            r_out["attempted_paths"] = _attempt_debug(r1, r2, r_hist, r_out)
            return r_out

        r3 = scoped(lookup_order_by_outer_so_id(identifier))
        if r3["found"]:
            r3["query_type"] = "platform_order_id->outer_so_id_fallback"
            r3["attempted_paths"] = _attempt_debug(r1, r2, r_hist, r_out, r3)
            return r3

        return _aggregate_lookup_miss(
            "platform_order_id",
            r1,
            r2,
            r_hist,
            r_out,
            r3,
            fallback_reason="not_found",
        )

    if identifier_type == "platform_trade_id":
        # Primary: orders/out/simple/query (销售出库查询)
        r_out = scoped(_lookup_outbound_for_identifier(identifier, **outbound_scope))
        if r_out["found"]:
            r_out["query_type"] = "platform_trade_id->outbound_so_id"
            r_out["attempted_paths"] = _attempt_debug(r_out)
            return r_out

        r_oid = scoped(lookup_order_by_order_id(identifier))
        if r_oid["found"]:
            r_oid["query_type"] = "platform_trade_id->same_order_id"
            r_oid["attempted_paths"] = _attempt_debug(r_out, r_oid)
            return r_oid

        if not exhaustive:
            r_so = scoped(lookup_order_by_platform_order_id(identifier))
            if r_so["found"]:
                r_so["query_type"] = "platform_trade_id->so_id_fallback"
                r_so["attempted_paths"] = _attempt_debug(r_out, r_oid, r_so)
                return r_so
            return _aggregate_lookup_miss(
                "platform_trade_id",
                r_out,
                r_oid,
                r_so,
                fallback_reason="not_found_fast_path",
            )

        r_so = scoped(lookup_order_by_platform_order_id(identifier))
        if r_so["found"]:
            r_so["query_type"] = "platform_trade_id->so_id_fallback"
            r_so["attempted_paths"] = _attempt_debug(r_out, r_oid, r_so)
            return r_so

        r_hist = scoped(lookup_order_by_platform_order_id_history(identifier))
        if r_hist["found"]:
            r_hist["query_type"] = "platform_trade_id->so_id_history_fallback"
            r_hist["attempted_paths"] = _attempt_debug(r_out, r_oid, r_so) + r_hist.get("attempted_paths", [])
            return r_hist

        # Fallback: outer_so_id scan (orders/single/query 扫描)
        r_outer = scoped(lookup_order_by_outer_so_id(identifier))
        if r_outer["found"]:
            r_outer["query_type"] = "platform_trade_id->outer_so_id_scan"
            r_outer["attempted_paths"] = _attempt_debug(r_out, r_oid, r_so, r_hist, r_outer)
            return r_outer

        return _aggregate_lookup_miss(
            "platform_trade_id",
            r_out,
            r_oid,
            r_so,
            r_hist,
            r_outer,
            fallback_reason="not_found",
        )

    if identifier_type == "tracking_no":
        return scoped(lookup_logistics_by_tracking_no(identifier))

    # unknown_identifier: outbound → o_id → so_id → outer_so_id scan → tracking scan
    r_out = scoped(_lookup_outbound_for_identifier(identifier, **outbound_scope))
    if r_out["found"]:
        r_out["query_type"] = "unknown->outbound_so_id"
        r_out["attempted_paths"] = _attempt_debug(r_out)
        return r_out

    r1 = scoped(lookup_order_by_order_id(identifier))
    if r1["found"]:
        r1["query_type"] = "unknown->order_id"
        r1["attempted_paths"] = _attempt_debug(r_out, r1)
        return r1

    r2 = scoped(lookup_order_by_platform_order_id(identifier))
    if r2["found"]:
        r2["query_type"] = "unknown->platform_order_id"
        r2["attempted_paths"] = _attempt_debug(r_out, r1, r2)
        return r2

    if scope_limits_expansion:
        # A selected UI label is routing context, not an order identity.  When
        # it cannot be mapped to exactly one JST shop, exact identifier queries
        # remain safe, but unscoped row-list scans must stay disabled.
        r_hist = scoped(lookup_order_by_platform_order_id_history(identifier))
        if r_hist["found"]:
            r_hist["query_type"] = "unknown->platform_order_id_history"
            r_hist["attempted_paths"] = _attempt_debug(r_out, r1, r2) + r_hist.get("attempted_paths", [])
            return r_hist
        return _aggregate_lookup_miss(
            "unknown_identifier",
            r_out,
            r1,
            r2,
            r_hist,
            fallback_reason=scope_limit_reason,
        )

    # A chat request with an untyped identifier must remain bounded. Historical
    # scans are available to callers that explicitly request exhaustive lookup,
    # but are too expensive for the interactive product-resolution path.
    if not exhaustive:
        return _aggregate_lookup_miss(
            "unknown_identifier",
            r_out,
            r1,
            r2,
            fallback_reason="not_found_fast_path",
        )

    r_hist = scoped(lookup_order_by_platform_order_id_history(identifier))
    if r_hist["found"]:
        r_hist["query_type"] = "unknown->platform_order_id_history"
        r_hist["attempted_paths"] = _attempt_debug(r_out, r1, r2) + r_hist.get("attempted_paths", [])
        return r_hist

    r_outer = scoped(lookup_order_by_outer_so_id(identifier))
    if r_outer["found"]:
        r_outer["query_type"] = "unknown->outer_so_id_scan"
        r_outer["attempted_paths"] = _attempt_debug(r_out, r1, r2, r_hist, r_outer)
        return r_outer

    r3 = scoped(lookup_logistics_by_tracking_no(identifier))
    if r3["found"]:
        r3["query_type"] = "unknown->tracking_no_scan"
        r3["attempted_paths"] = _attempt_debug(r_out, r1, r2, r_hist, r_outer, r3)
        return r3

    return _aggregate_lookup_miss(
        "unknown_identifier",
        r_out,
        r1,
        r2,
        r_hist,
        r_outer,
        r3,
        fallback_reason="not_found_by_any_path",
    )
