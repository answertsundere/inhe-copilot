"""
聚水潭实时数据查询仓库 - 直接调用聚水潭 OpenAPI 获取最新数据
带 TTL 缓存，避免短时间重复请求
"""

import hashlib
import json
import time
import requests
from typing import Optional
from app.repositories.base import BaseRepository

# 凭证必须通过环境变量设置，不硬编码
# JUSHUITAN_APP_KEY / JUSHUITAN_APP_SECRET / JUSHUITAN_ACCESS_TOKEN / JUSHUITAN_BASE_URL

_CACHE_TTL = 300  # 5 分钟缓存


class _SimpleCache:
    """简单的 TTL 缓存"""

    def __init__(self, ttl=300):
        self._store = {}
        self._ttl = ttl

    def get(self, key):
        entry = self._store.get(key)
        if entry and time.time() - entry["ts"] < self._ttl:
            return entry["val"]
        return None

    def set(self, key, val):
        self._store[key] = {"val": val, "ts": time.time()}


class LiveJSTRepository(BaseRepository):
    """聚水潭实时查询仓库"""

    def __init__(self):
        import os
        self._app_key = os.environ.get("JUSHUITAN_APP_KEY", "")
        self._app_secret = os.environ.get("JUSHUITAN_APP_SECRET", "")
        self._access_token = os.environ.get("JUSHUITAN_ACCESS_TOKEN", "")
        self._base_url = os.environ.get("JUSHUITAN_BASE_URL", "https://openapi.jushuitan.com/open")
        self._cache = _SimpleCache(_CACHE_TTL)

    def _check_config(self):
        """检查凭证是否已配置，未配置时抛出异常"""
        missing = []
        if not self._app_key:
            missing.append("JUSHUITAN_APP_KEY")
        if not self._app_secret:
            missing.append("JUSHUITAN_APP_SECRET")
        if not self._access_token:
            missing.append("JUSHUITAN_ACCESS_TOKEN")
        if missing:
            raise RuntimeError(
                f"缺少聚水潭 API 必需环境变量: {', '.join(missing)}\n"
                f"请在 .env 文件或环境变量中设置。"
            )

    def load(self):
        """兼容 BaseRepository 接口，无需预加载"""
        pass

    # ---- 底层 API 调用 ----

    def _sign(self, params: dict) -> str:
        sorted_params = sorted(params.items())
        sign_str = self._app_secret + "".join(f"{k}{v}" for k, v in sorted_params)
        return hashlib.md5(sign_str.encode("utf-8")).hexdigest()

    def _call(self, endpoint: str, biz: dict = None, timeout: float = 5.0) -> dict:
        self._check_config()
        ts = str(int(time.time()))
        biz_str = json.dumps(biz or {}, separators=(",", ":"), ensure_ascii=False)
        params = {
            "access_token": self._access_token,
            "app_key": self._app_key,
            "biz": biz_str,
            "charset": "utf-8",
            "timestamp": ts,
            "version": "2",
        }
        params["sign"] = self._sign(params)
        resp = requests.post(
            f"{self._base_url}/{endpoint}",
            data=params,
            timeout=timeout,
        )
        return resp.json()

    # ---- 公开方法 ----

    def query_sku(self, sku_id: str) -> Optional[dict]:
        """查询单个 SKU 实时信息（扫最近7天匹配 sku_id）"""
        cache_key = f"sku:{sku_id}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        from datetime import datetime, timedelta
        now = datetime.now()
        week_ago = now - timedelta(days=6)
        result = self._call("sku/query", {
            "page_index": 1,
            "page_size": 100,
            "modified_begin": week_ago.strftime("%Y-%m-%d 00:00:00"),
            "modified_end": now.strftime("%Y-%m-%d 23:59:59"),
        })
        if result.get("code") == 0:
            datas = result.get("data", {}).get("datas", [])
            # 匹配 sku_id（大小写不敏感）
            sku_lower = sku_id.lower()
            for s in datas:
                if (s.get("sku_id") or "").lower() == sku_lower:
                    self._cache.set(cache_key, s)
                    return s
        self._cache.set(cache_key, None)
        return None

    def query_product(self, i_id: str) -> Optional[dict]:
        """按款号查询商品（扫最近7天匹配 i_id）"""
        cache_key = f"product:{i_id}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        from datetime import datetime, timedelta
        now = datetime.now()
        week_ago = now - timedelta(days=6)
        result = self._call("mall/item/query", {
            "page_index": 1,
            "page_size": 100,
            "modified_begin": week_ago.strftime("%Y-%m-%d 00:00:00"),
            "modified_end": now.strftime("%Y-%m-%d 23:59:59"),
        })
        if result.get("code") == 0:
            datas = result.get("data", {}).get("datas", [])
            for item in datas:
                if item.get("i_id") == i_id:
                    self._cache.set(cache_key, item)
                    return item
        self._cache.set(cache_key, None)
        return None

    def query_inventory(self, sku_id: str) -> Optional[dict]:
        """查询单个 SKU 库存"""
        cache_key = f"inv:{sku_id}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        # 库存接口需要时间范围，用最近7天
        from datetime import datetime, timedelta
        now = datetime.now()
        week_ago = now - timedelta(days=7)
        result = self._call("inventory/query", {
            "page_index": 1,
            "page_size": 100,
            "modified_begin": week_ago.strftime("%Y-%m-%d 00:00:00"),
            "modified_end": now.strftime("%Y-%m-%d 23:59:59"),
        })
        if result.get("code") != 0:
            return None
        datas = result.get("data", {}).get("datas", [])
        sku_lower = sku_id.lower()
        for inv in datas:
            if (inv.get("sku_id") or "").lower() == sku_lower:
                self._cache.set(cache_key, inv)
                return inv
        self._cache.set(cache_key, None)
        return None

    def query_order(self, order_id: str, timeout: float = 5.0, max_total_seconds: float = 15.0) -> Optional[dict]:
        """查询订单（从最近7天开始回溯，最多6个月）"""
        cache_key = f"order:{order_id}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        order = self._find_order(order_id, months_back=6, timeout=timeout, max_total_seconds=max_total_seconds)
        self._cache.set(cache_key, order)
        return order

    def query_logistics(self, order_id: str) -> list:
        """查询物流信息 — 通过 order_ids 查 logistic/query，返回带物流字段的订单记录"""
        cache_key = f"logistics:{order_id}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        from datetime import datetime, timedelta
        now = datetime.now()
        week_ago = now - timedelta(days=6)
        result = self._call("logistic/query", {
            "order_ids": [order_id],
            "page_size": 10,
            "modified_begin": week_ago.strftime("%Y-%m-%d 00:00:00"),
            "modified_end": now.strftime("%Y-%m-%d 23:59:59"),
        })
        # 聚水潭 logistic/query 返回 data.orders（不是 datas）
        orders = result.get("data", {}).get("orders", []) if result.get("code") == 0 else []
        self._cache.set(cache_key, orders)
        return orders

    def query_refunds(self, order_id: str) -> list:
        """查询退款/售后"""
        cache_key = f"refund:{order_id}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        from datetime import datetime, timedelta
        now = datetime.now()
        week_ago = now - timedelta(days=7)
        # 退款接口需要时间范围，且没有 order_ids 过滤，需要遍历匹配
        result = self._call("refund/single/query", {
            "page_size": 50,
            "modified_begin": week_ago.strftime("%Y-%m-%d 00:00:00"),
            "modified_end": now.strftime("%Y-%m-%d 23:59:59"),
        })
        datas = result.get("data", {}).get("datas", []) if result.get("code") == 0 else []
        # 过滤匹配该订单的退款
        matched = [r for r in datas if r.get("o_id") == order_id]
        self._cache.set(cache_key, matched)
        return matched

    def search_skus(self, keyword: str, limit: int = 10) -> list:
        """按关键词搜索 SKU（扫最近7天）"""
        from datetime import datetime, timedelta
        now = datetime.now()
        week_ago = now - timedelta(days=6)
        result = self._call("sku/query", {
            "page_index": 1,
            "page_size": 100,
            "modified_begin": week_ago.strftime("%Y-%m-%d 00:00:00"),
            "modified_end": now.strftime("%Y-%m-%d 23:59:59"),
        })
        if result.get("code") != 0:
            return []
        datas = result.get("data", {}).get("datas", [])
        kw = keyword.lower()
        matched = [s for s in datas if kw in (s.get("name") or "").lower() or kw in (s.get("sku_id") or "").lower()]
        return matched[:limit]

    # ---- 内部辅助 ----

    def _find_order(self, order_id: str, months_back: int = 6, timeout: float = 5.0, max_total_seconds: float = 15.0) -> Optional[dict]:
        """统一查找订单 — 不管传入的是订单号、店铺单号、平台订单号还是快递单号，
        都依次尝试以下路径：
        1. o_ids + 时间范围直查
        2. so_ids + 时间范围直查
        3. 快递单号反查（扫最近物流记录匹配 l_id）
        4. 时间窗口扫描（匹配 outer_so_id 等平台订单号）

        max_total_seconds: _find_order 整体最大耗时（秒），超时立即返回 None
        """
        from datetime import datetime, timedelta
        _find_start = time.time()
        now = datetime.now()
        order_id_str = str(order_id).strip()
        if not order_id_str:
            return None

        def _elapsed():
            return time.time() - _find_start

        # 路径 1 & 2 扫描最近 4 周（每次 7 天），逐周尝试
        for week_offset in range(4):
            if _elapsed() > max_total_seconds:
                return None
            batch_end = now - timedelta(weeks=week_offset)
            batch_start = batch_end - timedelta(days=6)
            time_range = {
                "modified_begin": batch_start.strftime("%Y-%m-%d 00:00:00"),
                "modified_end": batch_end.strftime("%Y-%m-%d 23:59:59"),
            }

            # 路径 1：o_ids + 时间范围直查
            result = self._call("orders/single/query", {
                "page_index": 1,
                "page_size": 10,
                "o_ids": [order_id_str],
                **time_range,
            })
            if result.get("code") == 0:
                orders = result.get("data", {}).get("orders", [])
                if orders:
                    return orders[0]

            # 路径 2：so_ids + 时间范围直查（店铺订单号）
            result = self._call("orders/single/query", {
                "page_index": 1,
                "page_size": 10,
                "so_ids": [order_id_str],
                **time_range,
            })
            if result.get("code") == 0:
                orders = result.get("data", {}).get("orders", [])
                if orders:
                    return orders[0]

        # 路径 3：快递单号反查（扫最近物流记录匹配 l_id）
        # 限制扫描范围以控制响应时间
        for week_offset in range(4):  # 缩小到最近 4 周
            if _elapsed() > max_total_seconds:
                return None
            batch_end = now - timedelta(weeks=week_offset)
            batch_start = batch_end - timedelta(days=6)
            for page in range(1, 4):  # 每周最多翻 3 页（300 条）
                if _elapsed() > max_total_seconds:
                    return None
                log_result = self._call("logistic/query", {
                    "page_index": page,
                    "page_size": 100,
                    "modified_begin": batch_start.strftime("%Y-%m-%d 00:00:00"),
                    "modified_end": batch_end.strftime("%Y-%m-%d 23:59:59"),
                })
                if log_result.get("code") == 0:
                    log_orders = log_result.get("data", {}).get("orders", [])
                    if not log_orders:
                        break  # 没有更多数据
                    for log in log_orders:
                        log_lid = str(log.get("l_id") or "").upper().strip()
                        if log_lid and log_lid == order_id_str.upper():
                            o_id = log.get("o_id")
                            if o_id:
                                # 用 o_id 查完整订单，尝试多个时间窗口
                                # 订单 modified 时间可能与物流记录不同，需要多扫几周
                                found_order = None
                                for sub_week in range(8):
                                    sub_end = batch_end - timedelta(weeks=sub_week)
                                    sub_start = sub_end - timedelta(days=6)
                                    sub_result = self._call("orders/single/query", {
                                        "page_index": 1,
                                        "page_size": 10,
                                        "o_ids": [str(o_id)],
                                        "modified_begin": sub_start.strftime("%Y-%m-%d 00:00:00"),
                                        "modified_end": sub_end.strftime("%Y-%m-%d 23:59:59"),
                                    })
                                    if sub_result.get("code") == 0:
                                        sub_orders = sub_result.get("data", {}).get("orders", [])
                                        if sub_orders:
                                            found_order = sub_orders[0]
                                            break
                                    time.sleep(0.05)
                                if found_order:
                                    return found_order
                else:
                    break  # API 出错，跳到下一周
                time.sleep(0.05)  # 频率控制
            time.sleep(0.1)

        # 路径 4：时间窗口扫描（匹配 outer_so_id 等平台订单号）
        if _elapsed() > max_total_seconds:
            return None
        batch_end = now
        for _ in range(min(months_back * 4, 8)):
            batch_start = batch_end - timedelta(days=6)
            result = self._call("orders/single/query", {
                "page_index": 1,
                "page_size": 100,
                "modified_begin": batch_start.strftime("%Y-%m-%d 00:00:00"),
                "modified_end": batch_end.strftime("%Y-%m-%d 23:59:59"),
            })
            if result.get("code") == 0:
                orders = result.get("data", {}).get("orders", [])
                for o in orders:
                    if str(o.get("o_id")) == order_id_str:
                        return o
                for o in orders:
                    outer_so_id = str(o.get("outer_so_id") or "")
                    if outer_so_id and order_id_str in outer_so_id:
                        return o
            batch_end = batch_start
            if batch_end.year < 2024 or _elapsed() > max_total_seconds:
                break
            time.sleep(0.1)
        return None
