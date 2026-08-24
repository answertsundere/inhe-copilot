"""
聚水潭实时查询层 — 精确读取优先，必要时在官方允许的时间窗口内完整分页扫描。

API 能力说明（基于 2026-05-31 实测）：
- o_ids 参数（orders/single/query）：实测可用精确查询，~400ms，无需时间范围。
  注意：此参数未在官方手册明确列出，属于实测发现能力。如果 API 未来变更导致失效，
  会返回 code!=0 或 found=0，此时直接安全 fallback，不做慢扫。
- so_ids 参数（orders/single/query）：实测可用精确查询，~450ms，需搭配最近7天时间范围。
  同上，属于实测能力。
- so_ids 参数（orders/out/simple/query）：销售出库查询的精确读取尝试。
  该参数不是公开稳定的外部交易号过滤合同，因此精确未命中后必须在
  官方要求的最近 7 天 modified 窗口中按页精确匹配返回字段。
- sku_ids 参数（sku/query）：实测可用精确查询。
- l_id 参数（logistic/query）：实测 API 忽略此参数，不支持精确查询。
- tracking_no：聚水潭无任何 API 支持按 tracking_no 精确查询。

查询策略：
1. internal_order_id (o_id)  → orders/single/query + o_ids（单次调用）
2. platform_order_id (so_id) → orders/single/query + so_ids + 最近7天（单次调用）
3. 天猫/淘宝的 platform_order_id / platform_trade_id → sales-outbound exact
   attempt → sales-outbound recent-window complete scan；不调用不支持的平台
   ordinary-order surface。
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
    if e.is_auth_error:
        logger.error(
            "JST 认证错误 (code=%s): %s. endpoint=%s. 请检查环境变量 JUSHUITAN_APP_KEY, "
            "JUSHUITAN_APP_SECRET, JUSHUITAN_ACCESS_TOKEN 是否正确配置。",
            e.code, e.api_message, e.endpoint,
        )
    else:
        logger.warning("JST API 错误 (code=%s): %s, endpoint=%s", e.code, e.api_message, e.endpoint)

# TTL 缓存
_CACHE_TTL_FOUND = 60   # 成功结果缓存 60s
_CACHE_TTL_MISS = 15     # 失败结果缓存 15s
_cache: dict = {}


def _cache_get(key: str):
    entry = _cache.get(key)
    if entry and time.time() - entry["ts"] < entry["ttl"]:
        return entry["val"]
    if entry:
        del _cache[key]
    return None


def _cache_set(key: str, val: dict, found: bool):
    _cache[key] = {"val": val, "ts": time.time(), "ttl": _CACHE_TTL_FOUND if found else _CACHE_TTL_MISS}


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


def _extract_order_info(order: dict) -> dict:
    """从聚水潭订单数据中提取客服所需字段（脱敏）"""
    items = []
    for item in order.get("items", []):
        items.append({
            "sku_id": item.get("sku_id", ""),
            "i_id": item.get("i_id", ""),
            "name": item.get("name", ""),
            "qty": item.get("qty", 0),
            "price": item.get("sale_price", item.get("price", item.get("seller_income_amount", 0))),
        })
    raw_items = order.get("items", [])
    first_raw_item = raw_items[0] if raw_items else {}

    return {
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

        if orders:
            data = _extract_order_info(orders[0])
            r = _make_result(found=True, data=data, endpoint="orders/single/query",
                             query_type="order_id", duration_ms=duration_ms)
        else:
            r = _make_result(found=False, endpoint="orders/single/query",
                             query_type="order_id", duration_ms=duration_ms,
                             safe_fallback_reason="not_found")

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
        r = _make_result(found=False, query_type="order_id", duration_ms=duration_ms,
                         error_code=str(e.code), error_message=e.api_message, safe_fallback_reason="jst_api_error")

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

        if orders:
            # 精确匹配 so_id（API 可能返回多条）
            matched = [o for o in orders if str(o.get("so_id")) == str(so_id)]
            order = matched[0] if matched else orders[0]
            data = _extract_order_info(order)
            r = _make_result(found=True, data=data, endpoint="orders/single/query",
                             query_type="platform_order_id", duration_ms=duration_ms)
        else:
            r = _make_result(found=False, endpoint="orders/single/query",
                             query_type="platform_order_id", duration_ms=duration_ms,
                             safe_fallback_reason="not_found")

    except (JSTConfigError, JSTTimeoutError, JSTAPIError) as e:
        duration_ms = int((time.time() - t0) * 1000)
        if isinstance(e, JSTAPIError):
            _log_api_error(e)
        code = "config_missing" if isinstance(e, JSTConfigError) else "timeout" if isinstance(e, JSTTimeoutError) else str(e.code)
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
            matched = [o for o in orders if str(o.get("so_id")) == str(so_id)]
            order = matched[0] if matched else (orders[0] if orders else None)
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
        last_error_code = "config_missing" if isinstance(e, JSTConfigError) else "timeout" if isinstance(e, JSTTimeoutError) else str(e.code)
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


def lookup_order_by_outer_so_id(
    outer_so_id: str,
    *,
    max_pages: Optional[int] = None,
    shop_id: str = "",
) -> dict:
    """Find an order by JST outer_so_id by scanning every returned page.

    The JST UI exposes "external transaction no" separately from so_id. The
    public order endpoint does not appear to support an exact outer_so_id
    parameter, so this scans recent orders and matches the returned field. By
    default the scan stops only at the provider's real last page or when the
    target is found. ``max_pages`` remains an explicit caller-side diagnostic
    limit; it is not the interactive default.
    """
    if not outer_so_id:
        return _make_result(found=False, query_type="outer_so_id", safe_fallback_reason="empty_id")

    normalized_shop_id = str(shop_id or "").strip()
    cache_key = f"outer:{normalized_shop_id}:{outer_so_id}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    client = JSTClient()
    t0 = time.time()
    now = datetime.now()
    week_ago = now - timedelta(days=6)
    target = str(outer_so_id).strip()
    page_index = 1
    scanned_pages = 0
    page_fingerprints: set[tuple[tuple[str, str, str], ...]] = set()
    terminal_result: Optional[dict] = None

    try:
        while True:
            if max_pages is not None and page_index > max_pages:
                duration_ms = int((time.time() - t0) * 1000)
                terminal_result = _make_result(
                    found=False,
                    endpoint="orders/single/query",
                    query_type="outer_so_id_scan",
                    duration_ms=duration_ms,
                    error_code="scan_page_limit_reached",
                    safe_fallback_reason="scan_page_limit_reached",
                )
                terminal_result["scanned_pages"] = scanned_pages
                break

            params = {
                "page_index": page_index,
                "page_size": 100,
                "modified_begin": week_ago.strftime("%Y-%m-%d 00:00:00"),
                "modified_end": now.strftime("%Y-%m-%d 23:59:59"),
            }
            if normalized_shop_id:
                params["shop_id"] = normalized_shop_id
            result = client.call("orders/single/query", params)
            data = result.get("data", {}) or {}
            orders = data.get("orders", []) or []
            scanned_pages += 1

            page_fingerprint = tuple(
                (
                    str(order.get("o_id") or ""),
                    str(order.get("so_id") or ""),
                    str(order.get("outer_so_id") or ""),
                )
                for order in orders
                if isinstance(order, dict)
            )
            if orders and page_fingerprint in page_fingerprints:
                duration_ms = int((time.time() - t0) * 1000)
                terminal_result = _make_result(
                    found=False,
                    endpoint="orders/single/query",
                    query_type="outer_so_id_scan",
                    duration_ms=duration_ms,
                    error_code="pagination_stalled",
                    safe_fallback_reason="pagination_stalled",
                )
                terminal_result["scanned_pages"] = scanned_pages
                break
            page_fingerprints.add(page_fingerprint)

            for order in orders:
                if normalized_shop_id and str(order.get("shop_id") or "").strip() != normalized_shop_id:
                    continue
                if target in _outbound_identifiers(order):
                    duration_ms = int((time.time() - t0) * 1000)
                    r = _make_result(
                        found=True,
                        data=_extract_order_info(order),
                        endpoint="orders/single/query",
                        query_type="outer_so_id_scan",
                        duration_ms=duration_ms,
                    )
                    r["scanned_pages"] = scanned_pages
                    _cache_set(cache_key, r, True)
                    return r

            page_count = data.get("page_count") or data.get("page_total")
            try:
                reached_reported_end = bool(page_count) and page_index >= int(page_count)
            except (TypeError, ValueError):
                reached_reported_end = False
            if reached_reported_end or len(orders) < 100:
                break
            page_index += 1

        if terminal_result is None:
            duration_ms = int((time.time() - t0) * 1000)
            terminal_result = _make_result(
                found=False,
                endpoint="orders/single/query",
                query_type="outer_so_id_scan",
                duration_ms=duration_ms,
                safe_fallback_reason="outer_so_id_not_found_in_complete_recent_scan",
            )
            terminal_result["scanned_pages"] = scanned_pages
        r = terminal_result

    except (JSTConfigError, JSTTimeoutError, JSTAPIError) as e:
        duration_ms = int((time.time() - t0) * 1000)
        if isinstance(e, JSTAPIError):
            _log_api_error(e)
        code = "config_missing" if isinstance(e, JSTConfigError) else "timeout" if isinstance(e, JSTTimeoutError) else str(e.code)
        r = _make_result(
            found=False,
            endpoint="orders/single/query",
            query_type="outer_so_id_scan",
            duration_ms=duration_ms,
            error_code=code,
            error_message=str(e),
            safe_fallback_reason=code,
        )
        r["scanned_pages"] = scanned_pages

    _cache_set(cache_key, r, r["found"])
    return r


def _outbound_identifiers(row: dict) -> set[str]:
    identifiers = {
        str(row.get(key) or "").strip()
        for key in ("so_id", "outer_so_id")
        if str(row.get(key) or "").strip()
    }
    for item in row.get("items", []) or []:
        if not isinstance(item, dict):
            continue
        for key in ("so_id", "outer_so_id", "outer_oi_id", "raw_so_id"):
            value = str(item.get(key) or "").strip()
            if value:
                identifiers.add(value)
    return identifiers


def lookup_outbound_by_so_id(so_id: str, *, shop_id: str = "") -> dict:
    """Query JST sales outbound records by platform/external transaction id."""
    if not so_id:
        return _make_result(found=False, query_type="outbound_so_id", safe_fallback_reason="empty_id")

    normalized_shop_id = str(shop_id or "").strip()
    cache_key = f"outso:{normalized_shop_id}:{so_id}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    client = JSTClient()
    t0 = time.time()
    now = datetime.now()
    week_ago = now - timedelta(days=6)
    try:
        query = {
            "page_index": 1,
            "page_size": 20,
            "so_ids": [str(so_id)],
            "modified_begin": week_ago.strftime("%Y-%m-%d 00:00:00"),
            "modified_end": now.strftime("%Y-%m-%d 23:59:59"),
        }
        if normalized_shop_id:
            query["shop_id"] = normalized_shop_id
        result = client.call("orders/out/simple/query", query)
        rows = result.get("data", {}).get("datas", [])
        duration_ms = int((time.time() - t0) * 1000)

        target = str(so_id).strip()
        matched = [
            row for row in rows
            if isinstance(row, dict)
            and target in _outbound_identifiers(row)
            and (
                not normalized_shop_id
                or str(row.get("shop_id") or "").strip() == normalized_shop_id
            )
        ]
        if matched:
            row = matched[0]
            data = _extract_order_info(row)
            r = _make_result(
                found=True,
                data=data,
                endpoint="orders/out/simple/query",
                query_type="outbound_so_id",
                duration_ms=duration_ms,
            )
        else:
            r = _make_result(
                found=False,
                endpoint="orders/out/simple/query",
                query_type="outbound_so_id",
                duration_ms=duration_ms,
                safe_fallback_reason="not_found",
            )

    except (JSTConfigError, JSTTimeoutError, JSTAPIError) as e:
        duration_ms = int((time.time() - t0) * 1000)
        if isinstance(e, JSTAPIError):
            _log_api_error(e)
        code = "config_missing" if isinstance(e, JSTConfigError) else "timeout" if isinstance(e, JSTTimeoutError) else str(e.code)
        r = _make_result(
            found=False,
            endpoint="orders/out/simple/query",
            query_type="outbound_so_id",
            duration_ms=duration_ms,
            error_code=code,
            error_message=str(e),
            safe_fallback_reason=code,
        )

    _cache_set(cache_key, r, r["found"])
    return r


def lookup_outbound_by_so_id_history(
    so_id: str,
    *,
    shop_id: str = "",
    days: int = 75,
) -> dict:
    """Search bounded sales-outbound history using only an exact identifier.

    The sales-outbound API requires a short modified-time range even when a
    platform order identifier is supplied.  This retries the *same exact*
    query over provider-compatible historical windows; it never replaces the
    identifier with product text or performs an unbounded table scan.
    """
    if not so_id:
        return _make_result(
            found=False,
            query_type="outbound_so_id_history",
            safe_fallback_reason="empty_id",
        )

    normalized_shop_id = str(shop_id or "").strip()
    target = str(so_id).strip()
    cache_key = f"outso_hist:{normalized_shop_id}:{days}:{target}"
    cached = _cache_get(cache_key)
    if cached is not None:
        cached_copy = dict(cached)
        cached_copy["attempted_paths"] = list(cached.get("attempted_paths", []))
        return cached_copy

    client = JSTClient()
    started_at = time.time()
    attempted_paths: list[dict] = []
    last_error_code = None
    last_error_message = None

    try:
        for modified_begin, modified_end in _historical_modified_windows(days=days):
            attempt_started_at = time.time()
            params = {
                "page_index": 1,
                "page_size": 20,
                "so_ids": [target],
                "modified_begin": modified_begin,
                "modified_end": modified_end,
            }
            if normalized_shop_id:
                params["shop_id"] = normalized_shop_id
            result = client.call("orders/out/simple/query", params)
            rows = (result.get("data", {}) or {}).get("datas", []) or []
            duration_ms = int((time.time() - attempt_started_at) * 1000)
            match = next(
                (
                    row
                    for row in rows
                    if isinstance(row, dict)
                    and target in _outbound_identifiers(row)
                    and (
                        not normalized_shop_id
                        or str(row.get("shop_id") or "").strip() == normalized_shop_id
                    )
                ),
                None,
            )
            attempted_paths.append({
                "query_type": "outbound_so_id_history",
                "endpoint": "orders/out/simple/query",
                "found": bool(match),
                "duration_ms": duration_ms,
                "modified_begin": modified_begin,
                "modified_end": modified_end,
                "error_code": None,
                "safe_fallback_reason": None if match else "not_found_in_window",
            })
            if match is not None:
                response = _make_result(
                    found=True,
                    data=_extract_order_info(match),
                    endpoint="orders/out/simple/query",
                    query_type="outbound_so_id_history",
                    duration_ms=int((time.time() - started_at) * 1000),
                )
                response["attempted_paths"] = attempted_paths
                _cache_set(cache_key, response, True)
                response_copy = dict(response)
                response_copy["attempted_paths"] = list(attempted_paths)
                return response_copy
    except (JSTConfigError, JSTTimeoutError, JSTAPIError) as exc:
        if isinstance(exc, JSTAPIError):
            _log_api_error(exc)
        last_error_code = (
            "config_missing"
            if isinstance(exc, JSTConfigError)
            else "timeout"
            if isinstance(exc, JSTTimeoutError)
            else str(exc.code)
        )
        last_error_message = str(exc)
        attempted_paths.append({
            "query_type": "outbound_so_id_history",
            "endpoint": "orders/out/simple/query",
            "found": False,
            "duration_ms": int((time.time() - started_at) * 1000),
            "error_code": last_error_code,
            "safe_fallback_reason": last_error_code,
        })

    response = _make_result(
        found=False,
        endpoint="orders/out/simple/query",
        query_type="outbound_so_id_history",
        duration_ms=int((time.time() - started_at) * 1000),
        error_code=last_error_code,
        error_message=last_error_message,
        safe_fallback_reason=last_error_code or f"not_found_in_{days}d_history",
    )
    response["attempted_paths"] = attempted_paths
    _cache_set(cache_key, response, False)
    response_copy = dict(response)
    response_copy["attempted_paths"] = list(attempted_paths)
    return response_copy


def lookup_outbound_by_identifier_scan(identifier: str, *, shop_id: str = "") -> dict:
    """Find a sales-outbound record by scanning its provider-bounded time window.

    ``orders/out/simple/query`` requires a recent ``modified`` window.  Its
    documented surface does not guarantee support for an exact external-order
    filter, so an exact miss is followed by a read-only, shop-scoped page scan.
    The scan stops at the provider's final page, a short page, a repeated page,
    or an API error.  It never guesses from product names or customer text.
    """
    if not identifier:
        return _make_result(
            found=False,
            query_type="outbound_recent_scan",
            safe_fallback_reason="empty_id",
        )

    normalized_shop_id = str(shop_id or "").strip()
    target = str(identifier).strip()
    cache_key = f"outscan:{normalized_shop_id}:{target}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    client = JSTClient()
    t0 = time.time()
    now = datetime.now()
    week_ago = now - timedelta(days=6)
    page_index = 1
    scanned_pages = 0
    page_fingerprints: set[tuple[tuple[str, str, str], ...]] = set()
    terminal_result: Optional[dict] = None

    try:
        while True:
            params = {
                "page_index": page_index,
                "page_size": 100,
                "modified_begin": week_ago.strftime("%Y-%m-%d 00:00:00"),
                "modified_end": now.strftime("%Y-%m-%d 23:59:59"),
            }
            if normalized_shop_id:
                params["shop_id"] = normalized_shop_id

            result = client.call("orders/out/simple/query", params)
            data = result.get("data", {}) or {}
            rows = data.get("datas", []) or []
            scanned_pages += 1

            page_fingerprint = tuple(
                (
                    str(row.get("o_id") or ""),
                    str(row.get("so_id") or ""),
                    str(row.get("outer_so_id") or ""),
                )
                for row in rows
                if isinstance(row, dict)
            )
            if rows and page_fingerprint in page_fingerprints:
                terminal_result = _make_result(
                    found=False,
                    endpoint="orders/out/simple/query",
                    query_type="outbound_recent_scan",
                    duration_ms=int((time.time() - t0) * 1000),
                    error_code="pagination_stalled",
                    safe_fallback_reason="pagination_stalled",
                )
                terminal_result["scanned_pages"] = scanned_pages
                break
            page_fingerprints.add(page_fingerprint)

            for row in rows:
                if not isinstance(row, dict):
                    continue
                if normalized_shop_id and str(row.get("shop_id") or "").strip() != normalized_shop_id:
                    continue
                if target not in _outbound_identifiers(row):
                    continue
                r = _make_result(
                    found=True,
                    data=_extract_order_info(row),
                    endpoint="orders/out/simple/query",
                    query_type="outbound_recent_scan",
                    duration_ms=int((time.time() - t0) * 1000),
                )
                r["scanned_pages"] = scanned_pages
                _cache_set(cache_key, r, True)
                return r

            page_count = data.get("page_count") or data.get("page_total")
            try:
                reached_reported_end = bool(page_count) and page_index >= int(page_count)
            except (TypeError, ValueError):
                reached_reported_end = False
            if reached_reported_end or len(rows) < 100:
                break
            page_index += 1

        if terminal_result is None:
            terminal_result = _make_result(
                found=False,
                endpoint="orders/out/simple/query",
                query_type="outbound_recent_scan",
                duration_ms=int((time.time() - t0) * 1000),
                safe_fallback_reason="outbound_identifier_not_found_in_complete_recent_scan",
            )
            terminal_result["scanned_pages"] = scanned_pages
        r = terminal_result

    except (JSTConfigError, JSTTimeoutError, JSTAPIError) as e:
        if isinstance(e, JSTAPIError):
            _log_api_error(e)
        code = "config_missing" if isinstance(e, JSTConfigError) else "timeout" if isinstance(e, JSTTimeoutError) else str(e.code)
        r = _make_result(
            found=False,
            endpoint="orders/out/simple/query",
            query_type="outbound_recent_scan",
            duration_ms=int((time.time() - t0) * 1000),
            error_code=code,
            error_message=str(e),
            safe_fallback_reason=code,
        )
        r["scanned_pages"] = scanned_pages

    _cache_set(cache_key, r, r["found"])
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


def lookup_order_by_identifier(
    identifier: str,
    identifier_type: str,
    *,
    exhaustive: bool = True,
    shop_id: str = "",
    shop_platform: str = "",
) -> dict:
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

        first_error_code = "timeout" if isinstance(e, JSTTimeoutError) else str(e.code)
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
        code = "timeout" if isinstance(e, JSTTimeoutError) else str(e.code)
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
        code = "config_missing" if isinstance(e, JSTConfigError) else "timeout" if isinstance(e, JSTTimeoutError) else str(e.code)
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
            last_error_code = "config_missing" if isinstance(e, JSTConfigError) else "timeout" if isinstance(e, JSTTimeoutError) else str(e.code)
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


def _aggregate_lookup_failure(
    *,
    query_type: str,
    results: tuple[dict, ...],
    duration_ms: int,
    not_found_reason: str,
) -> dict:
    """Keep infrastructure failures distinct from completed lookup misses."""
    reasons = {
        str(result.get("safe_fallback_reason") or "").strip().lower()
        for result in results
        if isinstance(result, dict)
    }
    error_codes = {
        str(result.get("error_code") or "").strip().lower()
        for result in results
        if isinstance(result, dict)
    }

    if reasons & {"jst_not_configured", "config_missing"} or "config_missing" in error_codes:
        fallback_reason = "jst_not_configured"
        error_code = "config_missing"
    elif reasons & {"jst_timeout", "timeout", "tool_timeout"} or "timeout" in error_codes:
        fallback_reason = "jst_timeout"
        error_code = "timeout"
    elif reasons & {"jst_api_error", "api_failed"} or any(
        code and code not in {"not_found", "not_found_fast_path"}
        for code in error_codes
    ):
        fallback_reason = "jst_api_error"
        error_code = next((code for code in error_codes if code), "api_error")
    else:
        fallback_reason = not_found_reason
        error_code = None

    return _make_result(
        found=False,
        query_type=query_type,
        duration_ms=duration_ms,
        error_code=error_code,
        safe_fallback_reason=fallback_reason,
    )


# Keep this definition after the legacy dispatcher above so imports use the
# full identifier surface, including JST outer_so_id ("external transaction no").
def lookup_order_by_identifier(
    identifier: str,
    identifier_type: str,
    *,
    exhaustive: bool = True,
    shop_id: str = "",
    shop_platform: str = "",
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

    if identifier_type == "internal_order_id":
        r1 = lookup_order_by_order_id(identifier)
        if r1["found"]:
            return r1

        r2 = lookup_order_by_platform_order_id(identifier)
        if r2["found"]:
            r2["query_type"] = "internal_order_id->so_id_fallback"
            r2["attempted_paths"] = _attempt_debug(r1, r2)
            return r2

        r_out = lookup_outbound_by_so_id(identifier, shop_id=shop_id) if shop_id else lookup_outbound_by_so_id(identifier)
        if r_out["found"]:
            r_out["query_type"] = "internal_order_id->outbound_so_id_fallback"
            r_out["attempted_paths"] = _attempt_debug(r1, r2, r_out)
            return r_out

        r3 = lookup_order_by_outer_so_id(identifier, shop_id=shop_id)
        if r3["found"]:
            r3["query_type"] = "internal_order_id->outer_so_id_fallback"
            r3["attempted_paths"] = _attempt_debug(r1, r2, r_out, r3)
            return r3

        total_ms = r1.get("duration_ms", 0) + r2.get("duration_ms", 0) + r_out.get("duration_ms", 0) + r3.get("duration_ms", 0)
        r = _aggregate_lookup_failure(
            query_type="internal_order_id",
            results=(r1, r2, r_out, r3),
            duration_ms=total_ms,
            not_found_reason="not_found",
        )
        r["attempted_paths"] = _attempt_debug(r1, r2, r_out, r3)
        return r

    if identifier_type == "platform_order_id":
        normalized_platform = str(shop_platform or "").strip().lower()
        if normalized_platform in {"taobao", "tmall", "taobao_tmall"}:
            # The selected store determines the readable identifier surface.
            # Keep Tmall side-panel order ids on sales outbound data rather
            # than trying the ordinary-order endpoint with a different schema.
            r_out = lookup_outbound_by_so_id(identifier, shop_id=shop_id)
            if r_out["found"]:
                r_out["query_type"] = "platform_order_id->outbound_so_id"
                r_out["attempted_paths"] = _attempt_debug(r_out)
                r_out["source_capability"] = "sales_outbound_only"
                return r_out

            r_out_history = lookup_outbound_by_so_id_history(identifier, shop_id=shop_id)
            if r_out_history["found"]:
                r_out_history["query_type"] = "platform_order_id->outbound_so_id_history"
                r_out_history["attempted_paths"] = _attempt_debug(r_out) + r_out_history.get("attempted_paths", [])
                r_out_history["source_capability"] = "sales_outbound_only"
                return r_out_history

            r_out_scan = lookup_outbound_by_identifier_scan(identifier, shop_id=shop_id)
            if r_out_scan["found"]:
                r_out_scan["query_type"] = "platform_order_id->outbound_recent_scan"
                r_out_scan["attempted_paths"] = _attempt_debug(r_out) + r_out_history.get("attempted_paths", []) + _attempt_debug(r_out_scan)
                r_out_scan["source_capability"] = "sales_outbound_only"
                return r_out_scan

            r = _aggregate_lookup_failure(
                query_type="platform_order_id",
                results=(r_out, r_out_history, r_out_scan),
                duration_ms=(
                    r_out.get("duration_ms", 0)
                    + r_out_history.get("duration_ms", 0)
                    + r_out_scan.get("duration_ms", 0)
                ),
                not_found_reason="sales_outbound_record_not_visible",
            )
            r["attempted_paths"] = _attempt_debug(r_out) + r_out_history.get("attempted_paths", []) + _attempt_debug(r_out_scan)
            r["source_capability"] = "sales_outbound_only"
            r["lookup_complete"] = not bool(r.get("error_code"))
            return r

        r1 = lookup_order_by_order_id(identifier)
        if r1["found"]:
            r1["query_type"] = "platform_order_id->same_order_id"
            return r1

        r2 = lookup_order_by_platform_order_id(identifier)
        if r2["found"]:
            r2["query_type"] = "platform_order_id->so_id_fallback"
            r2["attempted_paths"] = _attempt_debug(r1, r2)
            return r2

        r_hist = lookup_order_by_platform_order_id_history(identifier)
        if r_hist["found"]:
            r_hist["query_type"] = "platform_order_id->so_id_history_fallback"
            r_hist["attempted_paths"] = _attempt_debug(r1, r2) + r_hist.get("attempted_paths", [])
            return r_hist

        r_out = lookup_outbound_by_so_id(identifier, shop_id=shop_id) if shop_id else lookup_outbound_by_so_id(identifier)
        if r_out["found"]:
            r_out["query_type"] = "platform_order_id->outbound_so_id_fallback"
            r_out["attempted_paths"] = _attempt_debug(r1, r2, r_hist, r_out)
            return r_out

        r_out_scan = lookup_outbound_by_identifier_scan(identifier, shop_id=shop_id)
        if r_out_scan["found"]:
            r_out_scan["query_type"] = "platform_order_id->outbound_recent_scan"
            r_out_scan["attempted_paths"] = _attempt_debug(r1, r2, r_hist, r_out, r_out_scan)
            return r_out_scan

        r3 = lookup_order_by_outer_so_id(identifier, shop_id=shop_id)
        if r3["found"]:
            r3["query_type"] = "platform_order_id->outer_so_id_fallback"
            r3["attempted_paths"] = _attempt_debug(r1, r2, r_hist, r_out, r_out_scan, r3)
            return r3

        total_ms = (
            r1.get("duration_ms", 0)
            + r2.get("duration_ms", 0)
            + r_hist.get("duration_ms", 0)
            + r_out.get("duration_ms", 0)
            + r_out_scan.get("duration_ms", 0)
            + r3.get("duration_ms", 0)
        )
        r = _aggregate_lookup_failure(
            query_type="platform_order_id",
            results=(r1, r2, r_hist, r_out, r_out_scan, r3),
            duration_ms=total_ms,
            not_found_reason="not_found",
        )
        r["attempted_paths"] = _attempt_debug(r1, r2, r_hist, r_out, r_out_scan, r3)
        return r

    if identifier_type == "platform_trade_id":
        # Primary: orders/out/simple/query (销售出库查询)
        r_out = lookup_outbound_by_so_id(identifier, shop_id=shop_id) if shop_id else lookup_outbound_by_so_id(identifier)
        if r_out["found"]:
            r_out["query_type"] = "platform_trade_id->outbound_so_id"
            r_out["attempted_paths"] = _attempt_debug(r_out)
            if str(shop_platform or "").strip().lower() in {"taobao", "tmall", "taobao_tmall"}:
                r_out["source_capability"] = "sales_outbound_only"
            return r_out

        normalized_platform = str(shop_platform or "").strip().lower()
        if normalized_platform in {"taobao", "tmall", "taobao_tmall"}:
            # JST's ordinary order query does not expose Taobao/Tmall orders.
            # Keep the lookup on the read-only sales-outbound surface.  The
            # exact filter is not documented as reliable, so scan its required
            # recent modified window before concluding that the record is not
            # visible.  Do not fall through to unsupported ordinary orders.
            r_out_scan = lookup_outbound_by_identifier_scan(identifier, shop_id=shop_id)
            if r_out_scan["found"]:
                r_out_scan["query_type"] = "platform_trade_id->outbound_recent_scan"
                r_out_scan["attempted_paths"] = _attempt_debug(r_out, r_out_scan)
                r_out_scan["source_capability"] = "sales_outbound_only"
                return r_out_scan
            r = _aggregate_lookup_failure(
                query_type="platform_trade_id",
                results=(r_out, r_out_scan),
                duration_ms=r_out.get("duration_ms", 0) + r_out_scan.get("duration_ms", 0),
                not_found_reason="sales_outbound_record_not_visible",
            )
            r["attempted_paths"] = _attempt_debug(r_out, r_out_scan)
            r["source_capability"] = "sales_outbound_only"
            r["lookup_complete"] = not bool(r.get("error_code"))
            return r

        r_oid = lookup_order_by_order_id(identifier)
        if r_oid["found"]:
            r_oid["query_type"] = "platform_trade_id->same_order_id"
            r_oid["attempted_paths"] = _attempt_debug(r_out, r_oid)
            return r_oid

        if not exhaustive:
            r_so = lookup_order_by_platform_order_id(identifier)
            if r_so["found"]:
                r_so["query_type"] = "platform_trade_id->so_id_fallback"
                r_so["attempted_paths"] = _attempt_debug(r_out, r_oid, r_so)
                return r_so
            r = _aggregate_lookup_failure(
                query_type="platform_trade_id",
                results=(r_out, r_oid, r_so),
                duration_ms=r_out.get("duration_ms", 0) + r_oid.get("duration_ms", 0) + r_so.get("duration_ms", 0),
                not_found_reason="not_found_fast_path",
            )
            r["attempted_paths"] = _attempt_debug(r_out, r_oid, r_so)
            return r

        if not exhaustive:
            r_so = lookup_order_by_platform_order_id(identifier)
            if r_so["found"]:
                r_so["query_type"] = "platform_trade_id->so_id_fallback"
                r_so["attempted_paths"] = _attempt_debug(r_out, r_oid, r_so)
                return r_so
            r = _aggregate_lookup_failure(
                query_type="platform_trade_id",
                results=(r_out, r_oid, r_so),
                duration_ms=r_out.get("duration_ms", 0) + r_oid.get("duration_ms", 0) + r_so.get("duration_ms", 0),
                not_found_reason="not_found_fast_path",
            )
            r["attempted_paths"] = _attempt_debug(r_out, r_oid, r_so)
            return r

        r_so = lookup_order_by_platform_order_id(identifier)
        if r_so["found"]:
            r_so["query_type"] = "platform_trade_id->so_id_fallback"
            r_so["attempted_paths"] = _attempt_debug(r_out, r_oid, r_so)
            return r_so

        r_hist = lookup_order_by_platform_order_id_history(identifier)
        if r_hist["found"]:
            r_hist["query_type"] = "platform_trade_id->so_id_history_fallback"
            r_hist["attempted_paths"] = _attempt_debug(r_out, r_oid, r_so) + r_hist.get("attempted_paths", [])
            return r_hist

        # Fallback: outer_so_id scan (orders/single/query 扫描)
        r_outer = lookup_order_by_outer_so_id(identifier, shop_id=shop_id)
        if r_outer["found"]:
            r_outer["query_type"] = "platform_trade_id->outer_so_id_scan"
            r_outer["attempted_paths"] = _attempt_debug(r_out, r_oid, r_so, r_hist, r_outer)
            return r_outer

        total_ms = (
            r_out.get("duration_ms", 0)
            + r_oid.get("duration_ms", 0)
            + r_so.get("duration_ms", 0)
            + r_hist.get("duration_ms", 0)
            + r_outer.get("duration_ms", 0)
        )
        r = _aggregate_lookup_failure(
            query_type="platform_trade_id",
            results=(r_out, r_oid, r_so, r_hist, r_outer),
            duration_ms=total_ms,
            not_found_reason="not_found",
        )
        r["attempted_paths"] = _attempt_debug(r_out, r_oid, r_so, r_hist, r_outer)
        return r

    if identifier_type == "tracking_no":
        return lookup_logistics_by_tracking_no(identifier)

    # unknown_identifier: outbound → o_id → so_id → outer_so_id scan → tracking scan
    r_out = lookup_outbound_by_so_id(identifier, shop_id=shop_id) if shop_id else lookup_outbound_by_so_id(identifier)
    if r_out["found"]:
        r_out["query_type"] = "unknown->outbound_so_id"
        r_out["attempted_paths"] = _attempt_debug(r_out)
        return r_out

    r1 = lookup_order_by_order_id(identifier)
    if r1["found"]:
        r1["query_type"] = "unknown->order_id"
        r1["attempted_paths"] = _attempt_debug(r_out, r1)
        return r1

    r2 = lookup_order_by_platform_order_id(identifier)
    if r2["found"]:
        r2["query_type"] = "unknown->platform_order_id"
        r2["attempted_paths"] = _attempt_debug(r_out, r1, r2)
        return r2

    # A chat request with an untyped identifier must remain bounded. Historical
    # scans are available to callers that explicitly request exhaustive lookup,
    # but are too expensive for the interactive product-resolution path.
    if not exhaustive:
        r = _aggregate_lookup_failure(
            query_type="unknown_identifier",
            results=(r_out, r1, r2),
            duration_ms=(
                r_out.get("duration_ms", 0)
                + r1.get("duration_ms", 0)
                + r2.get("duration_ms", 0)
            ),
            not_found_reason="not_found_fast_path",
        )
        r["attempted_paths"] = _attempt_debug(r_out, r1, r2)
        return r

    r_hist = lookup_order_by_platform_order_id_history(identifier)
    if r_hist["found"]:
        r_hist["query_type"] = "unknown->platform_order_id_history"
        r_hist["attempted_paths"] = _attempt_debug(r_out, r1, r2) + r_hist.get("attempted_paths", [])
        return r_hist

    r_outer = lookup_order_by_outer_so_id(identifier, shop_id=shop_id)
    if r_outer["found"]:
        r_outer["query_type"] = "unknown->outer_so_id_scan"
        r_outer["attempted_paths"] = _attempt_debug(r_out, r1, r2, r_hist, r_outer)
        return r_outer

    r3 = lookup_logistics_by_tracking_no(identifier)
    if r3["found"]:
        r3["query_type"] = "unknown->tracking_no_scan"
        r3["attempted_paths"] = _attempt_debug(r_out, r1, r2, r_hist, r_outer, r3)
        return r3

    total_ms = (
        r_out.get("duration_ms", 0)
        + r1.get("duration_ms", 0)
        + r2.get("duration_ms", 0)
        + r_hist.get("duration_ms", 0)
        + r_outer.get("duration_ms", 0)
        + r3.get("duration_ms", 0)
    )
    r = _aggregate_lookup_failure(
        query_type="unknown_identifier",
        results=(r_out, r1, r2, r_hist, r_outer, r3),
        duration_ms=total_ms,
        not_found_reason="not_found_by_any_path",
    )
    r["attempted_paths"] = _attempt_debug(r_out, r1, r2, r_hist, r_outer, r3)
    return r
