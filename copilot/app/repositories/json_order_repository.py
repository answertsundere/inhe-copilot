"""
JSON 文件订单仓库 - 优先读取外部真实数据，无则回退样例数据
"""

import hashlib
import hmac
import json
import logging
import os
from typing import Optional

from .base import OrderRepositoryBase
from app.config import EXTERNAL_DATA_DIR, SAMPLE_DATA_DIR, _read_jst_environment_value

logger = logging.getLogger(__name__)

_SNAPSHOT_MANIFEST_FILENAME = "snapshot_order_projection.manifest.json"
_SNAPSHOT_SCHEMA_VERSION_V1 = "jst_snapshot_order_projection/v1"
_SNAPSHOT_SCHEMA_VERSION_V2 = "jst_snapshot_order_projection/v2"
_SNAPSHOT_ORDER_REFERENCE_HMAC_ALGORITHM = "hmac-sha256"


def _file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_lower_sha256(value: object) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


def _snapshot_order_reference_hmac(order_reference: str, secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        str(order_reference or "").strip().encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


class JsonOrderRepository(OrderRepositoryBase):
    """从 JSON 文件加载的订单仓库"""

    def __init__(self):
        self.orders = {}
        self.logistics = {}
        self.refunds = {}
        self.aftersale = {}
        self._snapshot_external_item_orders = {}
        self._snapshot_order_reference_orders = {}
        self._loaded = False

    def load(self):
        """加载订单相关数据，优先外部真实数据"""
        self._snapshot_external_item_orders = {}
        self._snapshot_order_reference_orders = {}
        data_dir = EXTERNAL_DATA_DIR or SAMPLE_DATA_DIR
        using_external = bool(EXTERNAL_DATA_DIR) and os.path.isdir(EXTERNAL_DATA_DIR)
        source = "外部数据" if using_external else "样例数据"
        logger.info("订单仓库数据来源: %s (%s)", source, data_dir)

        # 加载订单
        orders = self._load_json(data_dir, "orders.json")
        if not orders:
            orders = self._load_json(SAMPLE_DATA_DIR, "sample_orders.json")
        snapshot_lookup_ready = (
            self._snapshot_order_lookup_enabled()
            and self._snapshot_projection_is_valid(data_dir, orders)
        )
        snapshot_schema_version = (
            self._snapshot_projection_schema_version(data_dir)
            if snapshot_lookup_ready
            else ""
        )
        for o in orders:
            oid = str(o.get("o_id", ""))
            if oid:
                self.orders[oid] = o
            if snapshot_lookup_ready and o.get("snapshot_identity_only") is True:
                if snapshot_schema_version == _SNAPSHOT_SCHEMA_VERSION_V2:
                    reference_hmac = str(o.get("order_reference_hmac") or "").strip()
                    if reference_hmac:
                        self._snapshot_order_reference_orders.setdefault(reference_hmac, []).append(o)
                for item in o.get("items") or []:
                    if not isinstance(item, dict):
                        continue
                    external_item_id = str(item.get("outer_oi_id") or "").strip()
                    if external_item_id:
                        self._snapshot_external_item_orders.setdefault(external_item_id, []).append((o, item))
        logger.info("  订单: %d 条", len(self.orders))

        # 加载物流
        logistics = self._load_json(data_dir, "logistics.json")
        if not logistics and not snapshot_lookup_ready:
            logistics = self._load_json(SAMPLE_DATA_DIR, "sample_logistics.json")
        for l in logistics:
            oid = str(l.get("o_id", ""))
            if oid:
                self.logistics.setdefault(oid, []).append(l)
        logger.info("  物流: %d 条", sum(len(v) for v in self.logistics.values()))

        # 加载退款
        refunds = self._load_json(data_dir, "refunds.json")
        if not refunds and not snapshot_lookup_ready:
            refunds = self._load_json(SAMPLE_DATA_DIR, "sample_refunds.json")
        for r in refunds:
            oid = str(r.get("o_id", ""))
            if oid:
                self.refunds.setdefault(oid, []).append(r)
        logger.info("  退款: %d 条", sum(len(v) for v in self.refunds.values()))

        # 加载售后
        aftersale = self._load_json(data_dir, "aftersale_received.json")
        if aftersale:
            for a in aftersale:
                oid = str(a.get("o_id", ""))
                if oid:
                    self.aftersale.setdefault(oid, []).append(a)
            logger.info("  售后: %d 条", sum(len(v) for v in self.aftersale.values()))

        self._loaded = True

    def _load_json(self, directory: str, filename: str) -> list:
        """加载 JSON 文件"""
        path = os.path.join(directory, filename)
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("读取 %s 失败: %s", path, e)
            return []

    def get_order(self, order_id: str) -> Optional[dict]:
        """查询订单"""
        return self.orders.get(str(order_id))

    def get_order_by_tracking_no(self, tracking_no: str) -> Optional[dict]:
        """通过快递单号反查订单"""
        tn = str(tracking_no).upper().strip()
        for order in self.orders.values():
            if str(order.get("l_id", "")).upper().strip() == tn:
                return order
        return None

    def get_order_by_external_item_id(self, external_item_id: str) -> Optional[dict]:
        """Return one exact JST snapshot item match, or fail closed on ambiguity."""
        matches = self._snapshot_external_item_orders.get(str(external_item_id or "").strip(), [])
        if len(matches) != 1:
            return None
        order, item = matches[0]
        result = dict(order)
        result["items"] = [dict(value) if isinstance(value, dict) else value for value in order.get("items") or []]
        matched_item = dict(item)
        result.update({
            "snapshot_identity_only": True,
            "identity_source": "jst_snapshot_order_items",
            "matched_item_reason": "exact_jst_snapshot_order_item",
            "matched_item": matched_item,
        })
        return result

    def get_order_by_snapshot_order_reference(self, order_reference: str) -> Optional[dict]:
        """Resolve an exact sidebar order reference without storing it in the snapshot."""
        secret = _read_jst_environment_value("COPILOT_JST_SNAPSHOT_ORDER_LOOKUP_SECRET")
        if not secret or not str(order_reference or "").strip():
            return None
        reference_hmac = _snapshot_order_reference_hmac(order_reference, secret)
        matches = self._snapshot_order_reference_orders.get(reference_hmac, [])
        if len(matches) != 1:
            return None
        order = matches[0]
        result = dict(order)
        items = [dict(value) if isinstance(value, dict) else value for value in order.get("items") or []]
        result["items"] = items
        result.update({
            "snapshot_identity_only": True,
            "identity_source": "jst_snapshot_order_reference",
            "matched_item_reason": "exact_jst_snapshot_order_reference",
        })
        if len(items) == 1 and isinstance(items[0], dict):
            result["matched_item"] = dict(items[0])
        return result

    @staticmethod
    def _snapshot_order_lookup_enabled() -> bool:
        return os.environ.get("COPILOT_JST_SNAPSHOT_ORDER_LOOKUP_ENABLED", "").strip().lower() in {
            "1", "true", "yes", "on",
        }

    @staticmethod
    def _snapshot_projection_is_valid(data_dir: str, orders: list) -> bool:
        """Fail closed unless the identity-only projection matches its manifest."""
        orders_path = os.path.join(data_dir, "orders.json")
        manifest_path = os.path.join(data_dir, _SNAPSHOT_MANIFEST_FILENAME)
        try:
            with open(manifest_path, "r", encoding="utf-8") as handle:
                manifest = json.load(handle)
            if not isinstance(manifest, dict):
                return False
            schema_version = str(manifest.get("schema_version") or "")
            if (
                manifest.get("dataset_id") != "jst_snapshot_order_projection"
                or schema_version not in {
                    _SNAPSHOT_SCHEMA_VERSION_V1,
                    _SNAPSHOT_SCHEMA_VERSION_V2,
                }
                or not str(manifest.get("source_basename") or "").strip()
                or not _is_lower_sha256(manifest.get("source_sha256"))
                or not _is_lower_sha256(manifest.get("projection_sha256"))
                or not str(manifest.get("generated_at") or "").strip()
                or not isinstance(manifest.get("privacy_projection"), dict)
                or manifest["privacy_projection"].get("identity_only") is not True
                or manifest.get("projection_sha256") != _file_sha256(orders_path)
                or not isinstance(manifest.get("order_count"), int)
                or manifest["order_count"] != len(orders)
            ):
                return False
            if (
                schema_version == _SNAPSHOT_SCHEMA_VERSION_V2
                and manifest.get("order_reference_hmac_algorithm")
                != _SNAPSHOT_ORDER_REFERENCE_HMAC_ALGORITHM
            ):
                return False
        except (OSError, json.JSONDecodeError):
            return False

        for order in orders:
            expected_keys = {
                "snapshot_record_uid", "snapshot_identity_only", "items",
            }
            if schema_version == _SNAPSHOT_SCHEMA_VERSION_V2:
                expected_keys.add("order_reference_hmac")
            if not isinstance(order, dict) or set(order) != expected_keys:
                return False
            if order.get("snapshot_identity_only") is not True:
                return False
            record_uid = str(order.get("snapshot_record_uid") or "")
            if len(record_uid) != 32 or any(char not in "0123456789abcdef" for char in record_uid):
                return False
            if (
                schema_version == _SNAPSHOT_SCHEMA_VERSION_V2
                and not _is_lower_sha256(order.get("order_reference_hmac"))
            ):
                return False
            items = order.get("items")
            if not isinstance(items, list) or not items:
                return False
            for item in items:
                if not isinstance(item, dict) or set(item) != {"outer_oi_id", "sku_id", "i_id"}:
                    return False
                if not str(item.get("outer_oi_id") or "").strip() or not str(item.get("sku_id") or "").strip():
                    return False
                if not isinstance(item.get("i_id"), str):
                    return False
        return True

    @staticmethod
    def _snapshot_projection_schema_version(data_dir: str) -> str:
        manifest_path = os.path.join(data_dir, _SNAPSHOT_MANIFEST_FILENAME)
        try:
            with open(manifest_path, "r", encoding="utf-8") as handle:
                manifest = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return ""
        if not isinstance(manifest, dict):
            return ""
        return str(manifest.get("schema_version") or "")

    def get_logistics(self, order_id: str) -> list:
        """查询物流"""
        return self.logistics.get(str(order_id), [])

    def get_refunds(self, order_id: str) -> list:
        """查询退款"""
        return self.refunds.get(str(order_id), [])

    def get_aftersale(self, order_id: str) -> list:
        """查询售后"""
        return self.aftersale.get(str(order_id), [])

    def search_orders_by_status(self, status: str, limit: int = 20) -> list:
        """按状态搜索订单"""
        results = []
        for oid, order in self.orders.items():
            if order.get("status") == status or order.get("shop_status") == status:
                results.append(order)
                if len(results) >= limit:
                    break
        return results

    def count_orders(self) -> int:
        return len(self.orders)

    def count_logistics(self) -> int:
        return sum(len(v) for v in self.logistics.values())

    def count_refunds(self) -> int:
        return sum(len(v) for v in self.refunds.values())

    def count_aftersale(self) -> int:
        return sum(len(v) for v in self.aftersale.values())
