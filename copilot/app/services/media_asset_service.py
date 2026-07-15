"""
图片/视频素材库查询与推荐服务。

核心原则：
- 只有 status='approved' 且 usable_for_agent=1 的素材才允许进入 Agent / 工作台推荐。
- 未审核素材绝不暴露给客户侧推荐，避免误发。
- 推荐是「AI 建议，客服人工确认后发送」，本服务不做任何自动发送。
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
import re
from typing import Optional
from urllib.parse import parse_qs, urlparse

from sqlalchemy import or_

import app.models.kb_tables  # noqa: F401  ensure models registered
from app.db import SessionLocal
from app.models.kb_tables import KBMediaAsset, KBProduct


# ─── 意图 → 偏好素材类型映射 ───
# 材质/安全/质检类问题：图片不能作为证据，最多只能辅助展示，因此默认不推荐任何素材。
_INTENT_ASSET_PRIORITY = {
    "installation": ["install_video", "install_image", "pack_guide_image"],
    "image_attachment": ["sku_image", "size_image", "pack_guide_image", "install_image"],
    "aftersales": ["aftersales_image", "pack_guide_image", "accessory_image", "install_image"],
    "product_question": ["sku_image", "size_image"],
    "size_query": ["size_image", "sku_image"],
    "material_safety": [],
    "certificate": ["certificate_image"],
}

# 客户消息关键词 → 偏好素材类型（用于无 intent 或需要更细粒度时的兜底）
_KEYWORD_PRIORITY = [
    (["安装视频", "安装教程", "怎么安装", "怎么装", "组装视频", "安装步骤", "视频"], ["install_video", "install_image", "pack_guide_image"]),
    (["可拆", "可拆卸", "拆卸", "拆开", "拆下来", "能拆", "拆装"], ["size_image", "install_image", "pack_guide_image", "sku_image"]),
    (["尺寸", "多大", "长宽高", "规格", "适配"], ["size_image", "sku_image"]),
    (["配件", "少件", "少零件", "缺件", "漏发", "零件", "错件", "多发", "装不上"], ["accessory_image", "pack_guide_image"]),
    (["外观", "颜色", "款式", "长什么样", "什么样", "效果图", "实物图"], ["sku_image", "size_image"]),
    (["图片", "图给我看", "发个图", "看看图", "照片"], ["sku_image", "size_image"]),
    (["打包", "包装", "装箱", "里面有什么"], ["pack_guide_image"]),
    (["材质", "材料", "用料"], ["material_image", "sku_image"]),
    (["证书", "质检", "合格", "检测"], ["certificate_image"]),
]

# 允许自动审核的低风险素材类型（钉钉来源可信但仍需显式开启 --auto-approve-low-risk）
_LOW_RISK_AUTO_APPROVE_TYPES = {"sku_image", "pack_guide_image", "install_video"}
_BLOCK_ASSET_TYPES = {
    "sku_image": "image",
    "size_image": "image",
    "pack_guide_image": "image",
    "install_image": "image",
    "accessory_image": "image",
    "install_video": "video",
    "certificate_image": "image",
    "material_image": "image",
    "aftersales_image": "image",
}

# 运营端「素材用途」↔ 底层 asset_type 映射（不新增 DB 字段）
_MEDIA_PURPOSE_TO_ASSET_TYPE = {
    "appearance_image": "sku_image",
    "size_image": "size_image",
    "install_image": "install_image",
    "install_video": "install_video",
    "packing_list_image": "pack_guide_image",
    "accessory_image": "accessory_image",
    "certificate_image": "certificate_image",
    "material_image": "material_image",
    "aftersales_image": "aftersales_image",
    "other": "other",
}
_ASSET_TYPE_TO_MEDIA_PURPOSE = {
    "sku_image": "appearance_image",
    "size_image": "size_image",
    "install_image": "install_image",
    "install_video": "install_video",
    "pack_guide_image": "packing_list_image",
    "accessory_image": "accessory_image",
    "certificate_image": "certificate_image",
    "material_image": "material_image",
    "aftersales_image": "aftersales_image",
    "other": "other",
}

# Media may be useful as a customer-facing attachment only when its declared
# role matches the fact being answered.  In particular, a product appearance
# photo is not a dimension or space-fit reference merely because its title
# happens to mention a size.
_DIMENSION_MEDIA_TYPES = {"size_image", "size_chart_image", "dimension_image"}
_DIMENSION_MEDIA_PURPOSES = {
    "size_image",
    "size_chart",
    "size_chart_image",
    "dimension_reference",
    "space_fit_image",
}
_IDENTITY_KEYS = ("product_id", "i_id", "sku_code")

# 旧 scene_tags → 新 answer_scenarios 兼容映射
_SCENE_TAG_TO_ANSWER_SCENARIO = {
    "dimensions": "dimensions",
    "detachable": "detachable",
    "installation": "installation",
    "accessories": "accessories",
    "packing_list": "packing_list",
    "certification_report": "certificate",
    "certificate": "certificate",
    "color": "appearance",
    "appearance": "appearance",
    "material": "material",
    "age_range": "age_range",
    "cleaning": "cleaning_care",
    "usage": "usage",
    "comparison": "comparison",
    "ask_photo": "ask_photo",
    "drilling": "drilling",
}

# 客户问题 → 偏好的 answer_scenarios（用于无明确 fact_type 时兜底）
_ANSWER_SCENARIO_PRIORITY = {
    "ask_photo": ["ask_photo", "appearance"],
    "appearance": ["appearance", "ask_photo"],
    "dimensions": ["dimensions"],
    "detachable": ["detachable", "dimensions"],
    "installation": ["installation", "drilling"],
    "drilling": ["drilling", "installation"],
    "packing_list": ["packing_list"],
    "accessories": ["accessories", "packing_list"],
    "material": ["material"],
    "certificate": ["certificate"],
    "age_range": ["age_range"],
    "cleaning_care": ["cleaning_care"],
    "usage": ["usage"],
    "comparison": ["comparison"],
}

# 意图/关键词 → 场景
_SCENARIO_INFERENCE = [
    (["图片", "照片", "图", "看看", "发图"], "ask_photo"),
    (["外观", "颜色", "款式", "长什么样", "什么样", "效果图", "实物图"], "appearance"),
    (["尺寸", "多大", "长宽高", "规格", "高度", "宽度"], "dimensions"),
    (["可拆", "可拆卸", "拆卸", "拆开", "拆下来", "能拆", "拆装"], "detachable"),
    (["安装", "组装", "怎么装", "打孔", "安装视频", "教程"], "installation"),
    (["打孔", "需要打孔", "免打孔"], "drilling"),
    (["配件", "少件", "零件", "漏发", "装不上", "缺件"], "accessories"),
    (["包装", "装箱", "打包", "里面有什么"], "packing_list"),
    (["材质", "材料", "用料", "防潮"], "material"),
    (["证书", "质检", "合格", "检测报告"], "certificate"),
    (["适合多大", "几岁", "月龄", "年龄"], "age_range"),
    (["清洗", "清洁", "怎么洗", "保养"], "cleaning_care"),
    (["怎么用", "使用", "用法"], "usage"),
    (["区别", "哪个好", "对比", "不同"], "comparison"),
]


def get_media_purpose(asset: KBMediaAsset) -> str:
    """运营端「素材用途」，优先读 source_raw.media_purpose，否则按 asset_type 反推。"""
    sr = asset.get_source_raw() or {}
    mp = sr.get("media_purpose")
    if mp and mp in _MEDIA_PURPOSE_TO_ASSET_TYPE:
        return mp
    return _ASSET_TYPE_TO_MEDIA_PURPOSE.get(asset.asset_type, asset.asset_type)


def get_applicable_style(asset: KBMediaAsset) -> dict:
    """适用款式结构化读取，兼容旧 source_raw.applicable_scope。"""
    sr = asset.get_source_raw() or {}
    style = sr.get("applicable_style")
    if isinstance(style, dict):
        return {
            "scope_type": style.get("scope_type") or "all",
            "scope_values": [str(v).strip() for v in style.get("scope_values", []) if str(v).strip()],
            "scope_note": str(style.get("scope_note") or "").strip(),
        }
    legacy = sr.get("applicable_scope")
    if legacy:
        text = str(legacy).strip()
        return {"scope_type": "custom", "scope_values": [text], "scope_note": text}
    return {"scope_type": "all", "scope_values": [], "scope_note": ""}


def get_answer_scenarios(asset: KBMediaAsset) -> list[str]:
    """可回答问题，优先读 source_raw.answer_scenarios，兼容 scene_tags。"""
    sr = asset.get_source_raw() or {}
    scenarios = sr.get("answer_scenarios")
    if isinstance(scenarios, list) and scenarios:
        return [str(s).strip() for s in scenarios if str(s).strip()]
    tags = asset.get_scene_tags() or []
    mapped = []
    for t in tags:
        m = _SCENE_TAG_TO_ANSWER_SCENARIO.get(str(t).strip().lower())
        if m and m not in mapped:
            mapped.append(m)
    return mapped


def get_auto_send_level(asset: KBMediaAsset) -> str:
    """自动发送等级：读取配置或按素材用途给默认值；过期/未审核/不可用时 disabled。"""
    if asset.status != "approved" or asset.usable_for_agent != 1 or is_url_expired(asset):
        return "disabled"
    sr = asset.get_source_raw() or {}
    level = sr.get("auto_send_level")
    if level in ("auto", "review", "disabled"):
        return level
    purpose = get_media_purpose(asset)
    if purpose in ("certificate_image", "material_image", "aftersales_image"):
        return "review"
    return "auto"


def _infer_answer_scenario(message: str, intent: str = "") -> str:
    msg = str(message or "").lower()
    intent_scenario_map = {
        "installation": "installation",
        "image_attachment": "ask_photo",
        "size_query": "dimensions",
        "product_question": "appearance",
    }
    scenario = intent_scenario_map.get(intent, "")
    if scenario:
        return scenario
    for kws, s in _SCENARIO_INFERENCE:
        if any(k in msg for k in kws):
            return s
    return "ask_photo"


def _applicable_style_score(asset: KBMediaAsset, signals: dict) -> float:
    """根据顾客消息/身份匹配适用款式，返回排序分。"""
    style = get_applicable_style(asset)
    scope_type = style.get("scope_type") or "all"
    values = [str(v).lower() for v in style.get("scope_values", []) if v]
    if scope_type == "all" or not values:
        return 0.0

    sku = str(signals.get("sku_code") or "").strip().lower()
    message = str(signals.get("customer_message") or "").lower()
    product_name = str(signals.get("product_name") or "").lower()
    i_id = str(signals.get("i_id") or "").strip().lower()
    haystack = _style_signal_text(signals)

    if scope_type == "sku":
        if sku and any(sku == v for v in values):
            return 100.0
        return 0.0

    # combo / color / size / version / custom
    if any(v in haystack for v in values):
        return 50.0
    return 0.0


def _answer_scenario_score(asset: KBMediaAsset, scenario: str) -> float:
    """可回答问题匹配分。"""
    if not scenario:
        return 0.0
    scenarios = get_answer_scenarios(asset)
    if not scenarios:
        return 0.0
    priority = _ANSWER_SCENARIO_PRIORITY.get(scenario, [])
    score = 0.0
    for idx, wanted in enumerate(priority):
        if wanted in scenarios:
            score += max(1, (len(priority) - idx) * 8)
    return score


def _style_scope_matches(asset: KBMediaAsset, signals: dict) -> bool:
    """适用款式是否命中；未命中时不应推荐给当前顾客。"""
    style = get_applicable_style(asset)
    scope_type = style.get("scope_type") or "all"
    if scope_type == "all" or not style.get("scope_values"):
        return True
    values = [str(v).lower() for v in style["scope_values"] if v]
    sku = str(signals.get("sku_code") or "").strip().lower()
    haystack = _style_signal_text(signals)
    if scope_type == "sku":
        return sku and any(sku == v for v in values)
    return any(v in haystack for v in values)


def _style_signal_text(signals: dict) -> str:
    sku = str(signals.get("sku_code") or "").strip()
    parts = [
        str(signals.get("customer_message") or ""),
        str(signals.get("product_name") or ""),
        str(signals.get("i_id") or ""),
        sku,
    ]
    parts.extend(_sku_variant_labels(sku))
    return " ".join(part for part in parts if part).lower()


def _sku_variant_labels(sku: str | None) -> list[str]:
    text = str(sku or "").strip()
    match = re.search(r"B0*(\d+)S0*(\d+)", text, flags=re.IGNORECASE)
    if not match:
        return []
    combo = int(match.group(1))
    style = int(match.group(2))
    return [
        f"b{combo:02d}",
        f"s{style:02d}",
        f"组合{combo}",
        f"{combo}号组合",
        f"组合 {combo}",
        f"款式{combo}",
    ]


def _variant_prefix(value: str | None) -> str:
    text = str(value or "").strip()
    match = re.match(r"^(.+?)B\d+S\d+$", text, flags=re.IGNORECASE)
    return match.group(1).lower() if match else ""


def _asset_identity_safe_for_signals(asset: KBMediaAsset, signals: dict) -> bool:
    """Prevent cross-variant media delivery when the current turn has an exact SKU.

    A product-name match is useful for review/admin browsing, but it is not safe enough
    for auto-send. If the customer is on B05 and the asset is B01/B07 under the same
    parent item, we must not attach that image unless the asset is explicitly marked
    as all-scope/common.
    """
    sku = str(signals.get("sku_code") or "").strip()
    i_id = str(signals.get("i_id") or "").strip()
    asset_sku = str(getattr(asset, "sku_code", "") or "").strip()
    asset_i_id = str(getattr(asset, "i_id", "") or "").strip()
    style = get_applicable_style(asset)
    scope_type = style.get("scope_type") or "all"

    if sku and asset_sku and asset_sku != sku:
        if i_id and asset_sku == i_id:
            return _style_scope_matches(asset, signals)
        if scope_type != "all":
            return False
        sku_prefix = _variant_prefix(sku)
        asset_prefix = _variant_prefix(asset_sku)
        if sku_prefix and asset_prefix and sku_prefix == asset_prefix:
            return False
        if i_id and asset_sku.startswith(i_id) and len(asset_sku) > len(i_id):
            return False

    if i_id and asset_i_id and asset_i_id != i_id:
        asset_prefix = _variant_prefix(asset_i_id)
        i_prefix = _variant_prefix(i_id)
        if asset_prefix and i_prefix and asset_prefix == i_prefix:
            return False

    return _style_scope_matches(asset, signals)


def media_asset_matches_product_identity(asset: dict, product_identity: dict | None) -> bool:
    """Require one exact common identity namespace for fact-specific media.

    Product titles are display hints, not identity namespaces.  Missing media
    identity therefore cannot be promoted into a direct reference for a known
    product.
    """
    identity = product_identity or {}
    expected = {
        key: str(identity.get(key) or "").strip()
        for key in _IDENTITY_KEYS
        if str(identity.get(key) or "").strip()
    }
    actual = {
        key: str(asset.get(key) or "").strip()
        for key in _IDENTITY_KEYS
        if str(asset.get(key) or "").strip()
    }
    common = set(expected).intersection(actual)
    if not common:
        return False
    return all(expected[key] == actual[key] for key in common)


def media_asset_matches_fact_type(asset: dict, query_fact_type: str) -> bool:
    """Return whether an asset has the declared role for a visual fact type."""
    fact_type = str(query_fact_type or "").strip().lower()
    asset_type = str(asset.get("asset_type") or "").strip().lower()
    purpose = str(asset.get("media_purpose") or asset.get("purpose") or "").strip().lower()
    if fact_type in {"dimensions", "space_fit"}:
        # A product photo cannot become a dimension reference just because a
        # title or purpose mentions size. The durable asset role is the
        # contract that downstream delivery and audit stages can trust.
        if asset_type in {"sku_image", "product_photo", "appearance_image", "packaging_image", "component_image"}:
            return False
        return asset_type in _DIMENSION_MEDIA_TYPES or purpose in _DIMENSION_MEDIA_PURPOSES
    return True


def is_delivery_media_asset_eligible(
    asset: dict,
    *,
    query_fact_type: str = "",
    product_identity: dict | None = None,
) -> bool:
    """Validate the narrow fact-specific delivery contract before attachment."""
    fact_type = str(query_fact_type or "").strip().lower()
    if fact_type not in {"dimensions", "space_fit"}:
        return True
    status = str(asset.get("status") or asset.get("review_status") or "").strip().lower()
    usable = asset.get("usable_for_agent")
    if status != "approved" or usable not in {True, 1}:
        return False
    return (
        media_asset_matches_fact_type(asset, fact_type)
        and media_asset_matches_product_identity(asset, product_identity)
    )


def parse_url_expires(url: str) -> Optional[datetime]:
    """解析 URL 中的过期时间参数（Unix 秒）。

    支持：Expires / expires / x-oss-expires。
    返回 UTC datetime；无过期信息返回 None。
    """
    if not url:
        return None
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        for key in ("Expires", "expires", "x-oss-expires"):
            vals = qs.get(key)
            if vals:
                ts = int(vals[0])
                return datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)
    except Exception:
        return None
    return None


def is_url_expired(asset: KBMediaAsset, now: Optional[datetime] = None) -> bool:
    """判断素材 URL 是否已过期或需要刷新。

    - 显式 url_expires_at 已过期
    - refresh_status == 'needs_refresh'
    """
    if asset.refresh_status == "needs_refresh":
        return True
    if not asset.url_expires_at:
        return False
    now = now or datetime.utcnow()
    return asset.url_expires_at <= now


def _mark_needs_refresh(asset: KBMediaAsset, reason: str = "url_expired") -> None:
    """标记素材需要刷新。"""
    asset.refresh_status = "needs_refresh"
    asset.updated_at = datetime.utcnow()


def _match_scope(db, query, product_id=None, i_id=None, sku_code=None, product_name=None):
    """按 product_id / i_id / sku_code / product_name 缩小范围（任一命中即可）。"""
    conds = []
    if product_id:
        conds.append(KBMediaAsset.product_id == product_id)
    if i_id:
        conds.append(KBMediaAsset.i_id == i_id)
    if sku_code:
        conds.append(KBMediaAsset.sku_code == sku_code)
    if product_name:
        conds.append(KBMediaAsset.product_name == product_name)
    if conds:
        query = query.filter(or_(*conds))
    return query


def list_media_assets(
    db,
    *,
    product_id: Optional[int] = None,
    i_id: Optional[str] = None,
    sku_code: Optional[str] = None,
    product_name: Optional[str] = None,
    asset_type: Optional[str] = None,
    status: Optional[str] = None,
    usable_for_agent: Optional[bool] = None,
    keyword: Optional[str] = None,
    category_l1: Optional[str] = None,
    category_l2: Optional[str] = None,
    category_l3: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
):
    """按条件查询素材列表（后台审核/展示用，可看未审核）。"""
    need_category = bool(category_l1 or category_l2 or category_l3)
    if need_category:
        q = db.query(KBMediaAsset).join(KBProduct, KBMediaAsset.product_id == KBProduct.id)
        if category_l1:
            q = q.filter(KBProduct.category_l1 == category_l1)
        if category_l2:
            q = q.filter(KBProduct.category_l2 == category_l2)
        if category_l3:
            q = q.filter(KBProduct.category_l3 == category_l3)
    else:
        q = db.query(KBMediaAsset)
    q = _match_scope(db, q, product_id, i_id, sku_code, product_name)
    if asset_type:
        q = q.filter(KBMediaAsset.asset_type == asset_type)
    if status:
        q = q.filter(KBMediaAsset.status == status)
    if usable_for_agent is not None:
        q = q.filter(KBMediaAsset.usable_for_agent == (1 if usable_for_agent else 0))
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(
            or_(
                KBMediaAsset.product_name.like(like),
                KBMediaAsset.asset_title.like(like),
                KBMediaAsset.i_id.like(like),
                KBMediaAsset.sku_code.like(like),
            )
        )
    total = q.count()
    rows = (
        q.order_by(KBMediaAsset.updated_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {"total": total, "items": [r.to_dict() for r in rows]}


def media_stats(db) -> dict:
    """素材库总览统计。"""
    from sqlalchemy import func
    base = db.query(KBMediaAsset)
    total = base.count()
    by_status = dict(
        db.query(KBMediaAsset.status, func.count(KBMediaAsset.id))
        .group_by(KBMediaAsset.status).all()
    )
    by_type = dict(
        db.query(KBMediaAsset.asset_type, func.count(KBMediaAsset.id))
        .group_by(KBMediaAsset.asset_type).all()
    )
    usable = base.filter(KBMediaAsset.usable_for_agent == 1).count()
    return {
        "total": total,
        "pending_review": by_status.get("pending_review", 0),
        "approved": by_status.get("approved", 0),
        "rejected": by_status.get("rejected", 0),
        "usable_for_agent": usable,
        "by_type": by_type,
    }


def get_approved_assets_for_scope(
    db,
    *,
    product_id=None,
    i_id=None,
    sku_code=None,
    product_name=None,
    asset_types=None,
    limit: int = 5,
):
    """取已审核可用的素材（供 Agent 推荐 / 工作台展示）。

    只返回 status='approved' AND usable_for_agent=1 的素材。
    """
    now = datetime.utcnow()
    q = db.query(KBMediaAsset).filter(
        KBMediaAsset.status == "approved",
        KBMediaAsset.usable_for_agent == 1,
        KBMediaAsset.refresh_status != "needs_refresh",
        KBMediaAsset.refresh_status != "error",
        or_(
            KBMediaAsset.url_expires_at.is_(None),
            KBMediaAsset.url_expires_at > now,
        ),
    )
    q = _match_scope(db, q, product_id, i_id, sku_code, product_name)
    if asset_types:
        q = q.filter(KBMediaAsset.asset_type.in_(asset_types))
    rows = q.order_by(KBMediaAsset.match_confidence.desc(), KBMediaAsset.updated_at.desc()).limit(limit).all()
    return rows


def _decide_priority_types(message: str, intent: str) -> list[str]:
    """根据消息和意图决定推荐的素材类型优先级。"""
    # 材质/安全/质检类问题不能拿图片当证据，直接不进入推荐
    if intent == "material_safety":
        return []
    msg = (message or "").lower()
    # 关键词优先（更具体）
    for kws, types in _KEYWORD_PRIORITY:
        if any(k in msg for k in kws):
            return types
    # intent 兜底
    return _INTENT_ASSET_PRIORITY.get(intent, [])


def get_recommended_assets_for_message(
    *,
    customer_message: str = "",
    product_id: Optional[int] = None,
    i_id: Optional[str] = None,
    sku_code: Optional[str] = None,
    product_name: Optional[str] = None,
    intent: str = "",
    limit: int = 5,
) -> dict:
    """根据买家消息推荐可发送素材。

    排序考虑：
      1. 适用款式（SKU/组合/颜色/尺寸/版本）精确匹配
      2. 可回答问题（answer_scenarios）匹配
      3. 素材用途（asset_type）优先级
      4. 原始 match_confidence

    返回:
      {
        "recommended_assets": [...],   # 已审核可用素材（含 auto_send_level）
        "has_unapproved": bool,         # 是否存在同范围未审核素材（仅做提示，不暴露内容）
        "priority_types": [...],
      }
    任何异常都不影响主回复流程。
    """
    result = {"recommended_assets": [], "has_unapproved": False, "priority_types": []}
    try:
        priority_types = _decide_priority_types(customer_message, intent)
        result["priority_types"] = priority_types
        if not priority_types:
            return result
        if not (product_id or i_id or sku_code or product_name):
            # 没有商品定位，不推荐（避免跨商品误推）
            return result

        db = SessionLocal()
        try:
            rows = get_approved_assets_for_scope(
                db,
                product_id=product_id,
                i_id=i_id,
                sku_code=sku_code,
                product_name=product_name,
                asset_types=priority_types,
                limit=limit * 3,
            )
            scenario = _infer_answer_scenario(customer_message, intent)
            signals = {
                "customer_message": customer_message,
                "product_name": product_name or "",
                "sku_code": sku_code or "",
                "i_id": i_id or "",
            }
            # 过滤掉适用款式不匹配的素材，避免把 A 款的图发给 B 款顾客
            rows = [r for r in rows if _asset_identity_safe_for_signals(r, signals)]
            order = {t: i for i, t in enumerate(priority_types)}

            def _score(asset):
                return (
                    -_applicable_style_score(asset, signals),
                    -_answer_scenario_score(asset, scenario),
                    order.get(asset.asset_type, 99),
                    -(asset.match_confidence or 0.0),
                )

            rows_sorted = sorted(rows, key=_score)
            result["recommended_assets"] = select_delivery_assets(
                [_asset_to_reco(r, priority_types, signals=signals, scenario=scenario) for r in rows_sorted],
                max_assets=1,
            )

            # 是否存在同范围未审核素材（提示主管去审核，不暴露链接）
            unapproved_q = db.query(KBMediaAsset).filter(
                KBMediaAsset.status != "approved",
            )
            unapproved_q = _match_scope(db, unapproved_q, product_id, i_id, sku_code, product_name)
            unapproved_q = unapproved_q.filter(KBMediaAsset.asset_type.in_(priority_types))
            result["has_unapproved"] = unapproved_q.count() > 0
        finally:
            db.close()
    except Exception as e:  # 推荐失败绝不影响主链路
        result["recommended_assets"] = []
        result["_error"] = str(e)
    return result


def recommend_for_analyze_response(
    response: dict,
    *,
    customer_message: str = "",
    product_name: Optional[str] = None,
    i_id: Optional[str] = None,
    sku_code: Optional[str] = None,
    product_id: Optional[int] = None,
) -> dict:
    """轻量接入：从 analyze 响应中抽取 intent + 商品定位，返回推荐素材。

    不修改 response，不调用 LLM，不重构主链路。失败返回空推荐。
    """
    try:
        intent = (response.get("intent") or "").strip().lower()
        # 从上下文摘要里取已确认商品名（最可靠）
        ctx = response.get("context_used") or {}
        summary = ctx.get("conversation_context_summary") or {}
        resolved_name = (
            summary.get("confirmed_product")
            or summary.get("product_name")
            or product_name
            or ""
        )
        return get_recommended_assets_for_message(
            customer_message=customer_message or summary.get("current_customer_message", ""),
            product_name=resolved_name or None,
            product_id=product_id,
            i_id=i_id,
            sku_code=sku_code,
            intent=intent,
        )
    except Exception:
        return {"recommended_assets": [], "has_unapproved": False, "priority_types": []}


def select_delivery_assets(
    recommended_assets: list[dict] | None,
    max_assets: int = 1,
    *,
    query_fact_type: str = "",
    product_identity: dict | None = None,
) -> list[dict]:
    """Return the media blocks that should actually be attached to this reply.

    只有 auto_send_level == 'auto' 的素材才进入自动发送计划。
    review 素材会保留在 recommended_assets 列表供客服参考，但不自动发送。
    """
    selected: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for asset in recommended_assets or []:
        asset_type = str(asset.get("asset_type") or "").strip()
        url = str(asset.get("asset_url") or "").strip()
        if not asset_type or not url:
            continue
        # 非 auto 素材不进入自动发送 blocks；未标注时默认按 auto 处理（兼容旧调用/测试）
        if asset.get("auto_send_level", "auto") != "auto":
            continue
        if not is_delivery_media_asset_eligible(
            asset,
            query_fact_type=query_fact_type,
            product_identity=product_identity,
        ):
            continue
        key = (asset_type, url.split("?", 1)[0].lower())
        if key in seen:
            continue
        seen.add(key)
        selected_asset = dict(asset)
        selected_asset["send_mode"] = "auto_when_platform_connected"
        selected.append(selected_asset)
        if len(selected) >= max_assets:
            break
    return selected


def build_reply_blocks(
    suggested_reply: str,
    recommended_assets: list[dict] | None,
    *,
    requires_human_review: bool = False,
    max_assets: int = 1,
    query_fact_type: str = "",
    product_identity: dict | None = None,
) -> dict:
    """Build an ordered send plan: text first, then approved media blocks.

    只有 auto_send_level == 'auto' 的素材才会真正进入 reply_blocks。
    review/disabled 素材即使出现在 recommended_assets 中也不会自动发送。
    """
    text = (suggested_reply or "").strip()
    blocks = []
    if text:
        blocks.append({
            "type": "text",
            "content": text,
            "send_mode": "auto_when_platform_connected",
        })
    added = 0
    skipped_review = 0
    for asset in recommended_assets or []:
        if added >= max_assets:
            break
        asset_type = str(asset.get("asset_type") or "")
        block_type = _BLOCK_ASSET_TYPES.get(asset_type)
        url = str(asset.get("asset_url") or "").strip()
        if not block_type or not url:
            continue
        # 非 auto 素材不进入自动发送 blocks；未标注时默认按 auto 处理（兼容旧调用/测试）
        if asset.get("auto_send_level", "auto") != "auto":
            skipped_review += 1
            continue
        if not is_delivery_media_asset_eligible(
            asset,
            query_fact_type=query_fact_type,
            product_identity=product_identity,
        ):
            skipped_review += 1
            continue
        blocks.append({
            "type": block_type,
            "url": url,
            "asset_id": asset.get("asset_id") or asset.get("id"),
            "asset_type": asset_type,
            "media_purpose": asset.get("media_purpose") or "",
            "title": asset.get("asset_title") or asset_type,
            "product_name": asset.get("product_name") or "",
            "product_id": asset.get("product_id"),
            "i_id": asset.get("i_id") or "",
            "sku_code": asset.get("sku_code") or "",
            "status": asset.get("status") or asset.get("review_status") or "",
            "usable_for_agent": asset.get("usable_for_agent"),
            "auto_send_level": asset.get("auto_send_level") or "",
            "send_mode": "auto_when_platform_connected",
        })
        added += 1

    auto_send_ready = added > 0 and bool(text) and not requires_human_review
    reason = ""
    if requires_human_review:
        reason = "requires_human_review"
    elif not added:
        if skipped_review:
            reason = "media_requires_review"
        else:
            reason = "no_media_block"
    return {
        "reply_blocks": blocks,
        "reply_delivery": {
            "mode": "blocks",
            "auto_send_ready": auto_send_ready,
            "reason": reason,
            "review_hint": "requires_human_review" if requires_human_review else ("media_requires_review" if reason == "media_requires_review" else ""),
        },
    }


def _asset_to_reco(
    asset: KBMediaAsset,
    priority_types: list[str] | None = None,
    signals: dict | None = None,
    scenario: str = "",
) -> dict:
    """转成推荐给工作台/Agent 的精简结构。"""
    type_reason_map = {
        "install_video": "安装/组装视频",
        "install_image": "安装步骤图",
        "pack_guide_image": "打包/安装指导图",
        "sku_image": "商品外观/实物图",
        "size_image": "尺寸/规格图",
        "accessory_image": "配件/零件图",
        "certificate_image": "质检/证书图",
        "material_image": "材质说明图",
        "aftersales_image": "售后说明图",
    }
    style = get_applicable_style(asset)
    scenarios = get_answer_scenarios(asset)
    auto_level = get_auto_send_level(asset)
    style_text = ""
    if style.get("scope_type") and style.get("scope_type") != "all":
        style_text = f"适用{style['scope_type']}：{', '.join(style.get('scope_values', []))}"

    match_reason_parts = [type_reason_map.get(asset.asset_type, "商品素材")]
    if style_text:
        match_reason_parts.append(style_text)
    if scenarios:
        match_reason_parts.append(f"可回答：{', '.join(scenarios[:3])}")
    if auto_level == "review":
        match_reason_parts.append("需人工确认")
    match_reason = "；".join(match_reason_parts)

    score_detail = {
        "style_score": round(_applicable_style_score(asset, signals or {}), 1) if signals else 0.0,
        "scenario_score": round(_answer_scenario_score(asset, scenario), 1) if scenario else 0.0,
        "type_order": priority_types.index(asset.asset_type) if priority_types and asset.asset_type in priority_types else 99,
        "confidence": asset.match_confidence or 0.0,
        "auto_send_level": auto_level,
    }

    return {
        "id": asset.id,
        "asset_id": asset.id,
        "asset_type": asset.asset_type,
        "media_purpose": get_media_purpose(asset),
        "asset_title": asset.asset_title,
        "asset_url": asset.asset_url,
        "source": asset.source,
        "product_id": asset.product_id,
        "i_id": asset.i_id,
        "sku_code": asset.sku_code,
        "product_name": asset.product_name,
        "confidence": asset.match_confidence or 0.0,
        "send_mode": "auto_when_platform_connected" if auto_level == "auto" else "manual",
        "match_reason": match_reason,
        "scene_tags": asset.get_scene_tags(),
        "answer_scenarios": scenarios,
        "applicable_style": style,
        "auto_send_level": auto_level,
        "match_score_detail": score_detail,
    }


# ─── 审核操作 ───

def approve_asset(db, asset_id: int, reviewer: str = "") -> Optional[KBMediaAsset]:
    asset = db.query(KBMediaAsset).get(asset_id)
    if not asset:
        return None
    asset.status = "approved"
    asset.audit_status = "reviewed"
    asset.usable_for_agent = 1
    asset.reviewed_by = reviewer or asset.reviewed_by
    asset.updated_by = reviewer or asset.updated_by
    asset.updated_at = datetime.utcnow()
    db.commit()
    return asset


def reject_asset(db, asset_id: int, reviewer: str = "") -> Optional[KBMediaAsset]:
    asset = db.query(KBMediaAsset).get(asset_id)
    if not asset:
        return None
    asset.status = "rejected"
    asset.audit_status = "reviewed"
    asset.usable_for_agent = 0
    asset.reviewed_by = reviewer or asset.reviewed_by
    asset.updated_by = reviewer or asset.updated_by
    asset.updated_at = datetime.utcnow()
    db.commit()
    return asset


def update_asset(db, asset_id: int, fields: dict, editor: str = "") -> Optional[KBMediaAsset]:
    asset = db.query(KBMediaAsset).get(asset_id)
    if not asset:
        return None
    allowed = {
        "asset_title", "asset_type", "asset_url", "status",
        "usable_for_agent", "source_doc_id", "product_name", "i_id", "sku_code",
        "url_expires_at", "refresh_status", "source_updated_at", "reviewed_by",
    }
    # 运营卡片字段通过 source_raw 兼容存储，不新增 DB 列
    card_fields = {"media_purpose", "applicable_style", "answer_scenarios", "auto_send_level", "applicable_scope"}
    sr = asset.get_source_raw() or {}
    for k, v in fields.items():
        if k in allowed:
            if k == "usable_for_agent":
                asset.usable_for_agent = 1 if v else 0
            else:
                setattr(asset, k, v)
        elif k == "scene_tags":
            asset.set_scene_tags(v if isinstance(v, list) else [])
        elif k == "source_raw" and isinstance(v, dict):
            sr = v
        elif k in card_fields:
            sr[k] = v
    # 素材用途变更时同步底层 asset_type
    if "media_purpose" in fields and fields["media_purpose"] in _MEDIA_PURPOSE_TO_ASSET_TYPE:
        asset.asset_type = _MEDIA_PURPOSE_TO_ASSET_TYPE[fields["media_purpose"]]
    # 直接修改 asset_type 时，同步 source_raw.media_purpose
    if "asset_type" in fields and fields["asset_type"] in _ASSET_TYPE_TO_MEDIA_PURPOSE:
        sr["media_purpose"] = _ASSET_TYPE_TO_MEDIA_PURPOSE[fields["asset_type"]]
    asset.set_source_raw(sr)
    if "status" in fields and fields["status"] == "approved":
        asset.audit_status = "reviewed"
        asset.usable_for_agent = 1
    elif "status" in fields and fields["status"] == "rejected":
        asset.audit_status = "reviewed"
        asset.usable_for_agent = 0
    asset.updated_by = editor or asset.updated_by
    asset.updated_at = __import__("datetime").datetime.utcnow()
    db.commit()
    return asset


def delete_asset(db, asset_id: int) -> Optional[KBMediaAsset]:
    asset = db.query(KBMediaAsset).get(asset_id)
    if not asset:
        return None
    db.delete(asset)
    db.commit()
    return asset
