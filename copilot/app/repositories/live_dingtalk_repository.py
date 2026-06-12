"""
钉钉多维表实时查询仓库 - 直接调钉钉 Notable API 获取最新产品详情
支持按 SKU 编码精确查询和按关键词搜索
"""

import os
import time
import requests
from typing import Optional, List
from app.repositories.base import BaseRepository

# 凭证必须通过环境变量设置，不硬编码
# COPILOT_DT_CLIENT_ID / COPILOT_DT_CLIENT_SECRET / COPILOT_DT_OPERATOR_ID / COPILOT_DT_BASE_ID

# Sheet IDs
_SHEET_SKU_DB = "m6ZKv2m"       # SKU数据库-自产贴牌
_SHEET_KNOWLEDGE = "JamZf9c"    # 商品知识库

_CACHE_TTL = 300  # 5 分钟缓存


class _TokenHolder:
    """钉钉 accessToken 自动刷新"""

    def __init__(self, client_id: str, client_secret: str):
        self._client_id = client_id
        self._client_secret = client_secret
        self._token = None
        self._expire_at = 0

    def get(self) -> str:
        if self._token and time.time() < self._expire_at - 60:
            return self._token
        resp = requests.post(
            "https://api.dingtalk.com/v1.0/oauth2/accessToken",
            json={"appKey": self._client_id, "appSecret": self._client_secret},
            timeout=30,
        )
        data = resp.json()
        if "accessToken" not in data:
            raise RuntimeError(f"钉钉 accessToken 获取失败: {data}")
        self._token = data["accessToken"]
        self._expire_at = time.time() + data.get("expireIn", 7200)
        return self._token


class _SimpleCache:
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


class LiveDingTalkRepository(BaseRepository):
    """钉钉多维表实时查询仓库"""

    def __init__(self):
        self._client_id = os.environ.get("COPILOT_DT_CLIENT_ID", "")
        self._client_secret = os.environ.get("COPILOT_DT_CLIENT_SECRET", "")
        self._operator_id = os.environ.get("COPILOT_DT_OPERATOR_ID", "")
        self._base_id = os.environ.get("COPILOT_DT_BASE_ID", "")
        self._token_holder = _TokenHolder(self._client_id, self._client_secret)
        self._cache = _SimpleCache(_CACHE_TTL)

    def load(self):
        """兼容 BaseRepository 接口"""
        pass

    def _check_config(self):
        """检查凭证是否已配置"""
        missing = []
        if not self._client_id:
            missing.append("COPILOT_DT_CLIENT_ID")
        if not self._client_secret:
            missing.append("COPILOT_DT_CLIENT_SECRET")
        if not self._operator_id:
            missing.append("COPILOT_DT_OPERATOR_ID")
        if not self._base_id:
            missing.append("COPILOT_DT_BASE_ID")
        if missing:
            raise RuntimeError(
                f"缺少钉钉 API 必需环境变量: {', '.join(missing)}\n"
                f"请在 .env 文件或环境变量中设置。"
            )

    # ---- 底层 API ----

    def _list_records(self, sheet_id: str, filter_condition: dict = None,
                      max_results: int = 100) -> list:
        """列出记录，支持过滤条件"""
        self._check_config()
        token = self._token_holder.get()
        url = (f"https://api.dingtalk.com/v1.0/notable/bases/"
               f"{self._base_id}/sheets/{sheet_id}/records/list")
        headers = {
            "x-acs-dingtalk-access-token": token,
            "Content-Type": "application/json",
        }
        params = {"operatorId": self._operator_id}

        all_records = []
        next_token = None

        while len(all_records) < max_results:
            body = {"maxResults": min(100, max_results - len(all_records))}
            if next_token:
                body["nextToken"] = next_token
            if filter_condition:
                body["filter"] = filter_condition

            resp = requests.post(url, headers=headers, params=params,
                                 json=body, timeout=60)
            if resp.status_code == 503:
                time.sleep(2)
                resp = requests.post(url, headers=headers, params=params,
                                     json=body, timeout=60)

            if resp.status_code != 200:
                break

            data = resp.json()
            records = data.get("records", [])
            all_records.extend(records)

            if not data.get("hasMore") or not data.get("nextToken"):
                break
            next_token = data["nextToken"]

        return all_records

    # ---- 字段提取辅助 ----

    @staticmethod
    def _extract_text(field_val) -> str:
        """提取文本/选项字段"""
        if isinstance(field_val, dict):
            return field_val.get("name", field_val.get("text", ""))
        if isinstance(field_val, str):
            return field_val
        return ""

    @staticmethod
    def _extract_images(field_val) -> list:
        """提取图片 URL 列表"""
        if not isinstance(field_val, list):
            return []
        return [img["url"] for img in field_val
                if isinstance(img, dict) and img.get("url")]

    @staticmethod
    def _extract_link(field_val) -> dict:
        """提取链接字段"""
        if isinstance(field_val, dict) and field_val.get("link"):
            return {"url": field_val["link"], "title": field_val.get("text", "")}
        return {}

    @staticmethod
    def _extract_tag(field_val) -> str:
        """提取标签/选项字段（列表形式）"""
        if isinstance(field_val, list) and field_val:
            return field_val[0].get("name", "")
        if isinstance(field_val, dict):
            return field_val.get("name", "")
        return ""

    # ---- 公开方法 ----

    def query_sku(self, sku_id: str) -> Optional[dict]:
        """从 SKU数据库 查颜色/视频/打包指南等"""
        cache_key = f"dt_sku:{sku_id}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        # 钉钉 Notable API 的 filter 语法
        filter_cond = {
            "operator": "and",
            "conditions": [
                {
                    "operator": "is",
                    "field": "商品编码-公式",
                    "value": sku_id,
                }
            ],
        }
        records = self._list_records(_SHEET_SKU_DB,
                                     filter_condition=filter_cond,
                                     max_results=5)
        if not records:
            # filter 不生效时，回退到全量扫描
            result = self._scan_sku_db(sku_id)
            self._cache.set(cache_key, result)
            return result

        fields = records[0].get("fields", {})
        result = self._parse_sku_db_fields(fields)
        self._cache.set(cache_key, result)
        return result

    def query_knowledge(self, sku_id: str) -> list:
        """从商品知识库查平台信息（可能有多个平台SKU）"""
        cache_key = f"dt_know:{sku_id}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        filter_cond = {
            "operator": "and",
            "conditions": [
                {
                    "operator": "is",
                    "field": "商家编码",
                    "value": sku_id,
                }
            ],
        }
        records = self._list_records(_SHEET_KNOWLEDGE,
                                     filter_condition=filter_cond,
                                     max_results=50)
        if not records:
            result = self._scan_knowledge(sku_id)
            self._cache.set(cache_key, result)
            return result

        result = [self._parse_knowledge_fields(r.get("fields", {}))
                  for r in records]
        self._cache.set(cache_key, result)
        return result

    def search_products(self, keyword: str, limit: int = 20) -> list:
        """按产品名称搜索"""
        cache_key = f"dt_search:{keyword}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        # 先从 SKU数据库 搜索（产品名称绑定字段）
        all_records = self._list_records(_SHEET_SKU_DB, max_results=500)
        kw = keyword.lower()
        matched = []
        for r in all_records:
            fields = r.get("fields", {})
            name = self._extract_text(fields.get("产品名称绑定", ""))
            code = str(fields.get("商品编码-公式", ""))
            if kw in name.lower() or kw in code.lower():
                matched.append(self._parse_sku_db_fields(fields))
                if len(matched) >= limit:
                    break

        self._cache.set(cache_key, matched)
        return matched

    # ---- 扫描回退（filter 不生效时） ----

    def _scan_sku_db(self, sku_id: str) -> Optional[dict]:
        """全量扫描 SKU 数据库（回退方案）"""
        all_records = self._list_records(_SHEET_SKU_DB, max_results=3000)
        for r in all_records:
            fields = r.get("fields", {})
            code = str(fields.get("商品编码-公式", ""))
            if code == sku_id:
                return self._parse_sku_db_fields(fields)
        return None

    def _scan_knowledge(self, sku_id: str) -> list:
        """全量扫描商品知识库（回退方案）"""
        all_records = self._list_records(_SHEET_KNOWLEDGE, max_results=5000)
        results = []
        for r in all_records:
            fields = r.get("fields", {})
            code = str(fields.get("商家编码", ""))
            if code == sku_id:
                results.append(self._parse_knowledge_fields(fields))
        return results

    # ---- 字段解析 ----

    def _parse_sku_db_fields(self, fields: dict) -> dict:
        """解析 SKU数据库 记录"""
        # 安装视频
        install_videos = {}
        for vkey, vlabel in [("安装视频(抖音)", "douyin"), ("安装视频(B站)", "bilibili")]:
            link = self._extract_link(fields.get(vkey))
            if link:
                install_videos[vlabel] = link

        return {
            "sku_id": self._extract_text(fields.get("商品编码-公式", "")),
            "product_name": self._extract_text(fields.get("产品名称绑定", "")),
            "color": self._extract_text(fields.get("颜色", "")),
            "spec": self._extract_text(fields.get("规格", "")),
            "sku_images": self._extract_images(fields.get("SKU图")),
            "install_videos": install_videos,
            "pack_guide_images": self._extract_images(fields.get("打包指南")),
            "box_length_cm": fields.get("纸箱长cm"),
            "box_width_cm": fields.get("纸箱宽cm"),
            "box_height_cm": fields.get("纸箱高cm"),
            "gross_weight_kg": fields.get("毛重(kg)"),
            "net_weight_kg": fields.get("净重(kg)"),
            "volume_m3": fields.get("体积 (m³)"),
            "production_type": self._extract_tag(fields.get("自产/贴牌")),
            "stock_status": self._extract_tag(fields.get("产品备货公告")),
            "price_retail": fields.get("⭐平销价-阶2"),
            "price_promo": fields.get("大促价-阶段4"),
            "price_cost_high": fields.get("♣高级出厂价"),
            "price_cost_mid": fields.get("中级出厂价"),
            "price_cost_low": fields.get("初级出厂价"),
            "price_dist_high": fields.get("高级分销价"),
            "price_dist_low": fields.get("初级分销价"),
            "freight_avg": fields.get("运费均价"),
            "source": "dingtalk_sku_db",
        }

    @staticmethod
    def _parse_knowledge_fields(fields: dict) -> dict:
        """解析商品知识库记录"""
        return {
            "sku_id": str(fields.get("商家编码", "")),
            "platform_sku_id": str(fields.get("skuId", "")),
            "product_name": str(fields.get("产品名称", "")),
            "item_title": str(fields.get("商品名称", "")),
            "spec": str(fields.get("规格属性", "")),
            "price": fields.get("价格(元)"),
            "fixed_price": fields.get("一口价"),
            "category": str(fields.get("类目名称", "")),
            "images": LiveDingTalkRepository._extract_images(fields.get("商品图片")),
            "stock": fields.get("库存"),
            "delivery_days": fields.get("最长发货时效"),
            "shop": str(fields.get("关联店铺", "")),
            "source": "dingtalk_knowledge",
        }
