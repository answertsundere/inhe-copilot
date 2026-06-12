"""
商品知识卡生成脚本 v0.1
合并 full_items.json + full_skus.json + inventory + skumap + shops
生成: product_cards.json, product_cards.csv, sku_cards.csv, missing_info_tasks.csv, data_quality_report.md
"""

import json
import csv
import os
import sys
from collections import defaultdict
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# SCRIPT_DIR = D:\桌面文件\客服\product_knowledge
# raw_data 实际路径: D:\桌面文件\聚水潭api\客服\raw_data
RAW_DATA_DIR = r"D:\桌面文件\聚水潭api\客服\raw_data"

# ============================================================
# 工具函数
# ============================================================

def safe_str(val):
    """安全转为字符串，None/空返回空字符串"""
    if val is None:
        return ""
    if isinstance(val, str):
        return val.strip()
    return str(val).strip()


def has_value(val):
    """判断字段是否有有效值"""
    if val is None:
        return False
    if isinstance(val, str) and val.strip() == "":
        return False
    if isinstance(val, (int, float)) and val == 0:
        return True  # 0 是有效值
    return True


def load_json(path):
    """加载 JSON 文件"""
    if not os.path.exists(path):
        print(f"  [WARN] 文件不存在: {path}")
        return []
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data


def get_nested(d, *keys, default=None):
    """安全获取嵌套字典值"""
    for k in keys:
        if isinstance(d, dict):
            d = d.get(k, default)
        else:
            return default
    return d


# ============================================================
# 完整度评分
# ============================================================

def calc_completeness_score(card):
    """
    完整度评分（满分 100）
    - 商品名称: 10
    - 类目: 10
    - 商品状态: 10
    - 主图: 10
    - SKU明细: 20
    - 价格: 10
    - 库存: 10
    - 规格属性: 10
    - 客服知识字段: 20 (weight=5, h=5, l=5, w=5)
    """
    score = 0

    # 商品名称 10分
    if has_value(card.get("product_name")):
        score += 10

    # 类目 10分
    if has_value(card.get("category")):
        score += 10

    # 商品状态 10分
    if has_value(card.get("product_status")):
        score += 10

    # 主图 10分
    if has_value(card.get("main_image")):
        score += 10

    # SKU明细 20分
    sku_count = get_nested(card, "sku_summary", "sku_count", default=0)
    if sku_count and sku_count > 0:
        score += 20

    # 价格 10分 — 任一 SKU 有价格
    has_price = False
    for sku in get_nested(card, "sku_summary", "sku_list", default=[]):
        if has_value(sku.get("cost_price")) or has_value(sku.get("sale_price")):
            has_price = True
            break
    if has_price:
        score += 10

    # 库存 10分 — 任一 SKU 有库存数据
    has_stock = False
    for sku in get_nested(card, "sku_summary", "sku_list", default=[]):
        if has_value(sku.get("stock_qty")):
            has_stock = True
            break
    if has_stock:
        score += 10

    # 规格属性 10分 — 任一 SKU 有 properties_value
    has_props = False
    for sku in get_nested(card, "sku_summary", "sku_list", default=[]):
        if has_value(sku.get("properties_value")):
            has_props = True
            break
    if has_props:
        score += 10

    # 客服知识字段 20分 (weight=5, h=5, l=5, w=5) — 基于任一 SKU
    cs_facts = card.get("customer_service_facts", {})
    if has_value(cs_facts.get("weight")):
        score += 5
    # 尺寸: h/l/w 任一有值
    has_dim = False
    for sku in get_nested(card, "sku_summary", "sku_list", default=[]):
        if has_value(sku.get("h")) or has_value(sku.get("l")) or has_value(sku.get("w")):
            has_dim = True
            break
    if has_dim:
        score += 5
    # 颜色/规格从 properties_value 中提取
    if cs_facts.get("color"):
        score += 5
    # 材质/其他
    if has_value(cs_facts.get("material")):
        score += 5

    return min(score, 100)


def calc_agent_level(score, card):
    """Agent 可用等级"""
    # L0: 缺名称或SKU，score < 30
    if not has_value(card.get("product_name")) or card.get("sku_summary", {}).get("sku_count", 0) == 0:
        return "L0"
    if score < 30:
        return "L0"
    # L1: 有名称+SKU，无客服知识，score 30-50
    if score < 50:
        return "L1"
    # L2: 有规格/价格/部分知识，score 50-80
    if score <= 80:
        return "L2"
    # L3: 知识完整
    return "L3"


# ============================================================
# 异常检测
# ============================================================

def detect_data_quality_warnings(card, item_data, sku_datas):
    """检测数据质量问题"""
    warnings = []

    # 商品名称为空
    if not has_value(card.get("product_name")):
        warnings.append("商品名称为空")

    # 无 SKU
    if card.get("sku_summary", {}).get("sku_count", 0) == 0:
        warnings.append("商品存在但没有 SKU")

    # 主图缺失
    if not has_value(card.get("main_image")):
        warnings.append("主图缺失")

    # 类目缺失
    if not has_value(card.get("category")):
        warnings.append("类目缺失")

    # 价格缺失 — 所有 SKU 都没价格
    has_any_price = False
    for sku in card.get("sku_summary", {}).get("sku_list", []):
        if has_value(sku.get("cost_price")) or has_value(sku.get("sale_price")):
            has_any_price = True
            break
    if not has_any_price and len(card.get("sku_summary", {}).get("sku_list", [])) > 0:
        warnings.append("价格缺失")

    # 库存缺失 — 所有 SKU 都没库存数据
    has_any_stock = False
    for sku in card.get("sku_summary", {}).get("sku_list", []):
        if has_value(sku.get("stock_qty")):
            has_any_stock = True
            break
    if not has_any_stock and len(card.get("sku_summary", {}).get("sku_list", [])) > 0:
        warnings.append("库存缺失")

    # SKU 命名混乱 — 同一 i_id 下 SKU name 不一致（排除空值）
    sku_names = set()
    for sku in card.get("sku_summary", {}).get("sku_list", []):
        name = safe_str(sku.get("sku_name"))
        if name:
            sku_names.add(name)
    if len(sku_names) > 1:
        warnings.append(f"SKU命名不一致({len(sku_names)}种): " + ", ".join(list(sku_names)[:3]))

    # 商品状态未知
    status = card.get("product_status")
    if not has_value(status) or status == "未知":
        warnings.append("商品状态未知")

    # 图片缺失（所有SKU都无图）
    all_no_pic = True
    for sku in card.get("sku_summary", {}).get("sku_list", []):
        if has_value(sku.get("pic")):
            all_no_pic = False
            break
    if all_no_pic and len(card.get("sku_summary", {}).get("sku_list", [])) > 0:
        warnings.append("所有SKU图片缺失")

    return warnings


def detect_missing_fields(card):
    """检测缺失字段，返回缺失字段列表"""
    missing = []

    if not has_value(card.get("product_name")):
        missing.append("product_name")
    if not has_value(card.get("category")):
        missing.append("category")
    if not has_value(card.get("main_image")):
        missing.append("main_image")
    if card.get("sku_summary", {}).get("sku_count", 0) == 0:
        missing.append("sku_list")

    # 价格
    has_price = any(
        has_value(s.get("cost_price")) or has_value(s.get("sale_price"))
        for s in card.get("sku_summary", {}).get("sku_list", [])
    )
    if not has_price:
        missing.append("price")

    # 库存
    has_stock = any(has_value(s.get("stock_qty")) for s in card.get("sku_summary", {}).get("sku_list", []))
    if not has_stock:
        missing.append("stock")

    # 规格属性
    has_props = any(has_value(s.get("properties_value")) for s in card.get("sku_summary", {}).get("sku_list", []))
    if not has_props:
        missing.append("properties_value")

    # 客服知识字段
    cs = card.get("customer_service_facts", {})
    if not has_value(cs.get("material")):
        missing.append("material")
    if not has_value(cs.get("weight")):
        missing.append("weight")
    if not cs.get("color"):
        missing.append("color")

    # 商品状态
    if not has_value(card.get("product_status")):
        missing.append("product_status")

    return missing


# ============================================================
# 主处理逻辑
# ============================================================

def main():
    print("=" * 60)
    print("商品知识卡生成 v0.1")
    print("=" * 60)

    # ---- 1. 加载数据 ----
    print("\n[1] 加载数据源 ...")

    items = load_json(os.path.join(SCRIPT_DIR, "full_items.json"))
    skus = load_json(os.path.join(SCRIPT_DIR, "full_skus.json"))
    inventory = load_json(os.path.join(RAW_DATA_DIR, "inventory.json"))
    skumap = load_json(os.path.join(RAW_DATA_DIR, "skumap.json"))
    shops = load_json(os.path.join(RAW_DATA_DIR, "shops_all.json"))
    combine = load_json(os.path.join(SCRIPT_DIR, "full_combine.json"))
    suppliers = load_json(os.path.join(RAW_DATA_DIR, "suppliers.json"))

    print(f"  items:    {len(items)} 条")
    print(f"  skus:     {len(skus)} 条")
    print(f"  inventory: {len(inventory)} 条")
    print(f"  skumap:   {len(skumap)} 条")
    print(f"  shops:    {len(shops)} 条")
    print(f"  combine:  {len(combine)} 条")
    print(f"  suppliers: {len(suppliers)} 条")

    # ---- 2. 构建索引 ----
    print("\n[2] 构建索引 ...")

    # items: i_id -> item data
    items_by_iid = {}
    for item in items:
        iid = item.get("i_id")
        if iid:
            items_by_iid[iid] = item

    # skus: i_id -> [sku data]
    skus_by_iid = defaultdict(list)
    for sku in skus:
        iid = sku.get("i_id")
        if iid:
            skus_by_iid[iid].append(sku)

    # inventory: sku_id -> inventory data
    inv_by_sku = {}
    for inv in inventory:
        sid = str(inv.get("sku_id", ""))
        if sid:
            inv_by_sku[sid] = inv

    # skumap: i_id -> [skumap data]
    skumap_by_iid = defaultdict(list)
    for sm in skumap:
        iid = sm.get("i_id")
        if iid:
            skumap_by_iid[iid].append(sm)

    # shops: shop_id -> shop_name
    shops_map = {}
    for shop in shops:
        sid = str(shop.get("shop_id", ""))
        name = shop.get("shop_name", "")
        if sid:
            shops_map[sid] = name

    # combine: i_id -> [combine data]
    combine_by_iid = defaultdict(list)
    for c in combine:
        iid = c.get("i_id")
        if iid:
            combine_by_iid[iid].append(c)
    # also index by sku_id
    combine_by_sku = {}
    for c in combine:
        sid = c.get("sku_id")
        if sid:
            combine_by_sku[sid] = c

    # suppliers: supplier_name -> supplier details
    supplier_by_name = {}
    for sup in suppliers:
        name = safe_str(sup.get("name"))
        if name:
            supplier_by_name[name] = sup
    # also by supplier_id if present in SKU data
    supplier_by_id = {}
    for sup in suppliers:
        sid = sup.get("supplier_id")
        if sid:
            supplier_by_id[str(sid)] = sup

    print(f"  items 索引: {len(items_by_iid)} 个 i_id")
    print(f"  skus 索引:  {len(skus_by_iid)} 个 i_id")
    print(f"  inventory 索引: {len(inv_by_sku)} 个 sku_id")
    print(f"  skumap 索引: {len(skumap_by_iid)} 个 i_id")
    print(f"  shops 索引: {len(shops_map)} 个 shop_id")
    print(f"  combine 索引: {len(combine_by_iid)} 个 i_id, {len(combine_by_sku)} 个 sku_id")
    print(f"  suppliers 索引: {len(supplier_by_name)} 家(按名称), {len(supplier_by_id)} 家(按ID)")

    # ---- 3. 合并数据 & 生成知识卡 ----
    print("\n[3] 合并数据 & 生成知识卡 ...")

    # 收集所有 i_id（items 为主，skus 补充）
    all_iids = set(items_by_iid.keys()) | set(skus_by_iid.keys())

    # 异常追踪
    orphan_skus = []  # SKU 有 i_id 但 items 无
    no_sku_items = []  # 商品有 i_id 但无 SKU
    sku_only_iids = set(skus_by_iid.keys()) - set(items_by_iid.keys())
    item_only_iids = set(items_by_iid.keys()) - set(skus_by_iid.keys())

    product_cards = []
    sku_cards_rows = []

    for iid in sorted(all_iids):
        item_data = items_by_iid.get(iid)
        sku_datas = skus_by_iid.get(iid, [])
        skumap_datas = skumap_by_iid.get(iid, [])

        # 判断数据来源
        from_item = item_data is not None
        from_sku = len(sku_datas) > 0

        # 如果 items 无数据但有 SKU，标记为异常
        if not from_item and from_sku:
            orphan_skus.append(iid)

        # 如果有 items 但无 SKU，标记
        if from_item and not from_sku:
            no_sku_items.append(iid)

        # ----- 构建商品卡 -----

        # 主档信息（优先 items，补充 skus）
        if from_item:
            product_name = safe_str(item_data.get("name"))
            category = safe_str(item_data.get("c_name")) or safe_str(item_data.get("category"))
            brand = safe_str(item_data.get("brand"))
            main_pic = safe_str(item_data.get("pic"))
            enabled_status = item_data.get("enabled")
            created = safe_str(item_data.get("created"))
            modified = safe_str(item_data.get("modified"))
        else:
            # 从 SKU 数据推断
            if sku_datas:
                product_name = safe_str(sku_datas[0].get("name"))
                category = safe_str(sku_datas[0].get("category"))
                brand = safe_str(sku_datas[0].get("brand"))
                main_pic = safe_str(sku_datas[0].get("pic"))
                enabled_status = sku_datas[0].get("enabled")
                created = safe_str(sku_datas[0].get("created"))
                modified = safe_str(sku_datas[0].get("modified"))
            else:
                product_name = ""
                category = ""
                brand = None
                main_pic = ""
                enabled_status = None
                created = ""
                modified = ""

        # 状态映射
        if enabled_status is None:
            product_status = "未知"
        elif enabled_status == 1 or enabled_status is True:
            product_status = "启用"
        elif enabled_status == 0 or enabled_status is False:
            product_status = "停用"
        else:
            product_status = str(enabled_status)

        # 店铺名称
        shop_names = []
        for sm in skumap_datas:
            sid = str(sm.get("shop_id", ""))
            sname = shops_map.get(sid)
            if sname and sname not in shop_names:
                shop_names.append(sname)

        # 组合装信息
        combine_datas = combine_by_iid.get(iid, [])

        # SKU 明细列表
        sku_list = []
        colors = set()

        for sku in sku_datas:
            sku_id = safe_str(sku.get("sku_id"))
            sku_name = safe_str(sku.get("name"))
            props = safe_str(sku.get("properties_value"))
            cost_price = sku.get("cost_price")
            sale_price = sku.get("sale_price")
            weight = sku.get("weight")
            h = sku.get("h")
            l = sku.get("l")
            w = sku.get("w")
            sku_pic = safe_str(sku.get("pic"))
            sku_enabled = sku.get("enabled")

            # 库存
            stock_qty = None
            inv_data = inv_by_sku.get(sku_id)
            if inv_data:
                stock_qty = inv_data.get("qty")

            # 状态
            if sku_enabled is None:
                sku_status = "未知"
            elif sku_enabled == 1 or sku_enabled is True:
                sku_status = "启用"
            elif sku_enabled == 0 or sku_enabled is False:
                sku_status = "停用"
            else:
                sku_status = str(sku_enabled)

            # 从 properties_value 提取颜色
            if props:
                parts = props.split(";")
                for part in parts:
                    part = part.strip()
                    if len(parts) >= 2:
                        colors.add(parts[-1].strip())

            # 组合装子SKU信息
            combine_info = None
            c_data = combine_by_sku.get(sku_id)
            if c_data:
                child_items = c_data.get("items", [])
                combine_info = {
                    "is_combine": True,
                    "combine_cost_price": c_data.get("cost_price"),
                    "combine_sale_price": c_data.get("sale_price"),
                    "child_skus": [
                        {"sku_id": ci.get("src_sku_id"), "qty": ci.get("qty")}
                        for ci in child_items
                    ]
                }

            # 供应商详情
            supplier_detail = None
            sup_name = safe_str(sku.get("supplier_name"))
            if sup_name and sup_name in supplier_by_name:
                sup = supplier_by_name[sup_name]
                supplier_detail = {
                    "name": sup.get("name"),
                    "contacts": sup.get("contacts"),
                    "phone": sup.get("phone"),
                    "address": sup.get("address"),
                    "enabled": sup.get("enabled"),
                }

            sku_entry = {
                "sku_id": sku_id,
                "sku_name": sku_name,
                "properties_value": props,
                "barcode": sku.get("sku_code"),
                "cost_price": cost_price,
                "sale_price": sale_price,
                "stock_qty": stock_qty,
                "weight": weight,
                "h": h,
                "l": l,
                "w": w,
                "pic": sku_pic,
                "status": sku_status,
                "sku_type": sku.get("sku_type"),
                "labels": sku.get("labels"),
                "brand": sku.get("brand"),
                "supplier_name": sku.get("supplier_name"),
                "supplier_detail": supplier_detail,
                "category": sku.get("category"),
                "combine_info": combine_info,
                "source": "sku_query"
            }
            sku_list.append(sku_entry)

            # SKU cards CSV 行
            sku_cards_rows.append({
                "i_id": iid,
                "product_name": product_name,
                "sku_id": sku_id,
                "sku_name": sku_name,
                "properties_value": props,
                "barcode": safe_str(sku.get("sku_code")),
                "cost_price": cost_price,
                "sale_price": sale_price,
                "weight": weight,
                "stock_qty": stock_qty,
                "status": sku_status,
                "source": "sku_query"
            })

        # 也从 items 的嵌套 SKU 中提取（如果没有 sku/query 的数据）
        if not sku_datas and item_data and item_data.get("skus"):
            for sku in item_data["skus"]:
                sku_id = safe_str(sku.get("sku_id"))
                # 去重
                if any(s["sku_id"] == sku_id for s in sku_list):
                    continue

                sku_name = safe_str(sku.get("name"))
                props = safe_str(sku.get("properties_value"))
                cost_price = sku.get("cost_price")
                sale_price = sku.get("sale_price")
                weight = sku.get("weight")
                h = sku.get("h")
                l = sku.get("l")
                w = sku.get("w")
                sku_pic = safe_str(sku.get("pic"))
                sku_enabled = sku.get("enabled")

                stock_qty = None
                inv_data = inv_by_sku.get(sku_id)
                if inv_data:
                    stock_qty = inv_data.get("qty")

                if sku_enabled is None:
                    sku_status = "未知"
                elif sku_enabled == 1 or sku_enabled is True:
                    sku_status = "启用"
                else:
                    sku_status = "停用"

                if props:
                    parts = props.split(";")
                    for part in parts:
                        colors.add(part.strip())

                sku_entry = {
                    "sku_id": sku_id,
                    "sku_name": sku_name,
                    "properties_value": props,
                    "barcode": sku.get("sku_code"),
                    "cost_price": cost_price,
                    "sale_price": sale_price,
                    "stock_qty": stock_qty,
                    "weight": weight,
                    "h": h,
                    "l": l,
                    "w": w,
                    "pic": sku_pic,
                    "status": sku_status,
                    "sku_type": sku.get("sku_type"),
                    "labels": sku.get("labels"),
                    "brand": sku.get("brand"),
                    "supplier_name": sku.get("supplier_name"),
                    "category": sku.get("category"),
                    "source": "mall_item_query"
                }
                sku_list.append(sku_entry)

                sku_cards_rows.append({
                    "i_id": iid,
                    "product_name": product_name,
                    "sku_id": sku_id,
                    "sku_name": sku_name,
                    "properties_value": props,
                    "barcode": safe_str(sku.get("sku_code")),
                    "cost_price": cost_price,
                    "sale_price": sale_price,
                    "weight": weight,
                    "stock_qty": stock_qty,
                    "status": sku_status,
                    "source": "mall_item_query"
                })

        # 客服知识字段（从 SKU 数据提取）
        # material: API 无此字段
        material = None
        # size: 从 h/l/w 推导（仅标注 inferred）
        size_str = None
        has_hlw = False
        for s in sku_list:
            if has_value(s.get("h")) or has_value(s.get("l")) or has_value(s.get("w")):
                has_hlw = True
                break
        # weight
        weight_val = None
        for s in sku_list:
            if has_value(s.get("weight")):
                weight_val = s["weight"]
                break

        card = {
            "product_card_id": f"ITEM_{iid}",
            "i_id": iid,
            "product_name": product_name or None,
            "product_status": product_status,
            "category": category or None,
            "brand": brand,
            "main_image": main_pic or None,
            "shop_names": shop_names,
            "sku_summary": {
                "sku_count": len(sku_list),
                "sku_list": sku_list
            },
            "customer_service_facts": {
                "material": None,  # 待补充
                "size": None,  # 待补充
                "color": sorted(list(colors)) if colors else [],
                "weight": weight_val,
                "package_list": None,  # 待补充
                "installation_method": None,  # 待补充
                "cleaning_method": None,  # 待补充
                "applicable_scene": None,  # 待补充
                "applicable_people_or_pet": None,  # 待补充
                "selling_points": [],  # 待补充
                "after_sales_notes": []  # 待补充
            },
            "faq_draft": [],  # 待补充
            "forbidden_claims": [],  # 待补充
            "missing_fields": [],
            "completeness_score": 0,
            "review_status": "待运营补全",
            "agent_usable_level": "L0",
            "source_fields": {
                "from_item_query": ["product_name", "category", "main_image", "brand", "product_status"] if from_item else [],
                "from_sku_query": ["sku_list", "cost_price", "weight", "properties_value"] if from_sku else []
            },
            "data_quality_warnings": [],
            "last_updated": modified or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        # 计算缺失字段
        card["missing_fields"] = detect_missing_fields(card)

        # 计算完整度评分
        score = calc_completeness_score(card)
        card["completeness_score"] = score

        # 计算 Agent 可用等级
        card["agent_usable_level"] = calc_agent_level(score, card)

        # 审核状态
        if score >= 80:
            card["review_status"] = "高可用待确认"
        elif score >= 50:
            card["review_status"] = "部分可用待补全"
        else:
            card["review_status"] = "待运营补全"

        # 数据质量警告
        card["data_quality_warnings"] = detect_data_quality_warnings(card, item_data, sku_datas)

        product_cards.append(card)

    print(f"  生成商品知识卡: {len(product_cards)} 张")
    print(f"  SKU 明细行: {len(sku_cards_rows)} 行")

    # ---- 4. 输出文件 ----
    print("\n[4] 输出文件 ...")

    # 4.1 product_cards.json
    json_path = os.path.join(SCRIPT_DIR, "product_cards.json")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(product_cards, f, ensure_ascii=False, indent=2)
    print(f"  [OK] product_cards.json ({len(product_cards)} 条)")

    # 4.2 product_cards.csv — 展平所有实际数据值
    csv_path = os.path.join(SCRIPT_DIR, "product_cards.csv")
    with open(csv_path, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            "i_id", "商品名称", "类目", "品牌", "商品状态",
            "SKU数", "主图URL",
            "成本价(最低)", "成本价(最高)", "售价",
            "库存总量",
            "规格属性(首个SKU)", "颜色(从规格提取)",
            "重量(kg)", "长(cm)", "宽(cm)", "高(cm)", "体积",
            "供应商", "标签",
            "关联店铺",
            "缺失字段", "缺失字段数", "完整度评分",
            "Agent可用等级", "审核状态", "质量警告",
            "最后更新时间"
        ])
        for card in product_cards:
            sku_list = card.get("sku_summary", {}).get("sku_list", [])

            # 从所有 SKU 中提取实际价格/尺寸/重量
            cost_prices = [s["cost_price"] for s in sku_list if s.get("cost_price") is not None and s.get("cost_price") != 0]
            sale_prices = [s["sale_price"] for s in sku_list if s.get("sale_price") is not None and s.get("sale_price") != 0]
            weights = [s["weight"] for s in sku_list if s.get("weight") is not None and s.get("weight") != 0]
            stock_qtys = [s["stock_qty"] for s in sku_list if s.get("stock_qty") is not None]
            hs = [s["h"] for s in sku_list if s.get("h") is not None and s.get("h") != 0]
            ls = [s["l"] for s in sku_list if s.get("l") is not None and s.get("l") != 0]
            ws = [s["w"] for s in sku_list if s.get("w") is not None and s.get("w") != 0]

            # 供应商（去重合并）
            suppliers = sorted(set(
                s.get("supplier_name") for s in sku_list
                if s.get("supplier_name") and safe_str(s.get("supplier_name"))
            ))

            # 标签（去重合并）
            all_labels = sorted(set(
                tag.strip()
                for s in sku_list
                if s.get("labels")
                for tag in s.get("labels", "").split(",")
                if tag.strip()
            ))

            # 规格属性（取第一个有值的）
            first_props = ""
            for s in sku_list:
                if safe_str(s.get("properties_value")):
                    first_props = s["properties_value"]
                    break

            # 颜色
            colors = card.get("customer_service_facts", {}).get("color", [])

            writer.writerow([
                card["i_id"],
                card.get("product_name", ""),
                card.get("category", ""),
                card.get("brand", ""),
                card.get("product_status", ""),
                card.get("sku_summary", {}).get("sku_count", 0),
                card.get("main_image", ""),
                min(cost_prices) if cost_prices else "",
                max(cost_prices) if cost_prices else "",
                ", ".join(str(p) for p in sale_prices) if sale_prices else "",
                sum(stock_qtys) if stock_qtys else "",
                first_props,
                ", ".join(colors) if colors else "",
                ", ".join(str(w) for w in weights) if weights else "",
                ", ".join(str(v) for v in ls) if ls else "",
                ", ".join(str(v) for v in ws) if ws else "",
                ", ".join(str(v) for v in hs) if hs else "",
                "",  # 体积暂无汇总
                ", ".join(suppliers) if suppliers else "",
                ", ".join(all_labels) if all_labels else "",
                ", ".join(card.get("shop_names", [])),
                ", ".join(card.get("missing_fields", [])),
                len(card.get("missing_fields", [])),
                card.get("completeness_score", 0),
                card.get("agent_usable_level", ""),
                card.get("review_status", ""),
                " | ".join(card.get("data_quality_warnings", [])),
                card.get("last_updated", ""),
            ])
    print(f"  [OK] product_cards.csv")

    # 4.3 sku_cards.csv — 补全所有字段
    sku_csv_path = os.path.join(SCRIPT_DIR, "sku_cards.csv")
    with open(sku_csv_path, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            "i_id", "商品名称", "sku_id", "sku名称", "规格属性",
            "条码", "成本价", "售价", "重量(kg)",
            "长(cm)", "宽(cm)", "高(cm)",
            "库存数量",
            "品牌", "供应商", "标签", "类目",
            "图片URL", "状态", "来源接口"
        ])
        # 重新从 sku_list 展平，确保所有字段都有
        for card in product_cards:
            for sku in card.get("sku_summary", {}).get("sku_list", []):
                writer.writerow([
                    card["i_id"],
                    card.get("product_name", ""),
                    sku.get("sku_id", ""),
                    sku.get("sku_name", ""),
                    sku.get("properties_value", ""),
                    sku.get("barcode", ""),
                    sku.get("cost_price", ""),
                    sku.get("sale_price", ""),
                    sku.get("weight", ""),
                    sku.get("l", ""),
                    sku.get("w", ""),
                    sku.get("h", ""),
                    sku.get("stock_qty", ""),
                    card.get("brand", "") or sku.get("brand", ""),
                    sku.get("supplier_name", ""),
                    sku.get("labels", ""),
                    sku.get("category", "") or card.get("category", ""),
                    sku.get("pic", ""),
                    sku.get("status", ""),
                    sku.get("source", ""),
                ])
    print(f"  [OK] sku_cards.csv")

    # 4.4 missing_info_tasks.csv
    missing_csv_path = os.path.join(SCRIPT_DIR, "missing_info_tasks.csv")
    missing_rows = []
    for card in product_cards:
        for field in card.get("missing_fields", []):
            # 建议补充问题
            questions = {
                "product_name": "请提供商品名称",
                "category": "请确认商品类目",
                "main_image": "请上传商品主图",
                "sku_list": "请确认该商品是否有SKU，或标记为已下架",
                "price": "请补充成本价或售价",
                "stock": "请确认库存数据是否需要同步",
                "properties_value": "请补充SKU规格属性（颜色、尺寸等）",
                "material": "请补充商品材质信息",
                "weight": "请补充商品重量",
                "color": "请补充商品颜色信息",
                "product_status": "请确认商品当前状态",
            }
            # 优先级
            priority_map = {
                "product_name": "H",
                "sku_list": "H",
                "category": "M",
                "main_image": "M",
                "price": "M",
                "stock": "M",
                "properties_value": "M",
                "material": "L",
                "weight": "L",
                "color": "L",
                "product_status": "L",
            }

            missing_rows.append({
                "i_id": card["i_id"],
                "product_name": card.get("product_name", ""),
                "missing_field": field,
                "reason": "API数据中该字段为空",
                "suggestion": questions.get(field, "请补充该字段"),
                "priority": priority_map.get(field, "L"),
            })

    with open(missing_csv_path, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["i_id", "商品名称", "缺失字段", "缺失原因", "建议补充问题", "优先级"])
        for row in missing_rows:
            writer.writerow([
                row["i_id"],
                row["product_name"],
                row["missing_field"],
                row["reason"],
                row["suggestion"],
                row["priority"],
            ])
    print(f"  [OK] missing_info_tasks.csv ({len(missing_rows)} 条任务)")

    # ---- 5. 数据质量报告 ----
    print("\n[5] 生成数据质量报告 ...")

    # 统计
    total_items = len(product_cards)
    total_skus = len(sku_cards_rows)
    total_iids = len(all_iids)

    # 完整度分布
    score_buckets = {"0-30": 0, "30-50": 0, "50-80": 0, "80-100": 0}
    level_counts = {"L0": 0, "L1": 0, "L2": 0, "L3": 0}
    for card in product_cards:
        s = card["completeness_score"]
        if s < 30:
            score_buckets["0-30"] += 1
        elif s < 50:
            score_buckets["30-50"] += 1
        elif s <= 80:
            score_buckets["50-80"] += 1
        else:
            score_buckets["80-100"] += 1
        level_counts[card["agent_usable_level"]] += 1

    # 缺失字段统计
    field_missing_counts = defaultdict(int)
    for card in product_cards:
        for field in card.get("missing_fields", []):
            field_missing_counts[field] += 1

    # 质量警告统计
    warning_counts = defaultdict(int)
    for card in product_cards:
        for w in card.get("data_quality_warnings", []):
            # 简化警告类型
            wtype = w.split("(")[0]
            warning_counts[wtype] += 1

    # Top 需要补全的商品（按缺失字段数排序，取前20）
    top_missing = sorted(product_cards, key=lambda c: len(c.get("missing_fields", [])), reverse=True)[:20]

    # 生成报告
    report = f"""# 数据质量报告 — 商品知识卡 v0.1

> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---

## 1. 商品总数

| 维度 | 数量 |
|------|------|
| 商品（款号）总数 | **{total_items}** |
| SKU 总数 | **{total_skus}** |
| 平均每商品 SKU 数 | **{total_skus / total_items:.2f}** |

---

## 2. 商品 / SKU 匹配情况

| 类型 | 数量 |
|------|------|
| items 和 skus 都有（完全匹配） | {len(set(items_by_iid.keys()) & set(skus_by_iid.keys()))} |
| 仅 items 有，无 SKU 数据 | **{len(item_only_iids)}** |
| 仅 skus 有，无 items 主档 | **{len(sku_only_iids)}** |

### 仅 SKU 有、商品主档缺失的 i_id（{len(orphan_skus)} 个）
> 这些 SKU 在 sku/query 中存在但 mall/item/query 中没有对应主档

{(chr(10).join(f"- `{iid}`" for iid in sorted(orphan_skus)[:20])) if orphan_skus else "- 无"}

{(f"... 还有 {len(orphan_skus) - 20} 个" if len(orphan_skus) > 20 else "")}

### 有商品主档但无 SKU 的 i_id（{len(no_sku_items)} 个）
> 这些商品在 mall/item/query 中有记录但 sku/query 中没有匹配的 SKU

{(chr(10).join(f"- `{iid}`" for iid in sorted(no_sku_items)[:20])) if no_sku_items else "- 无"}

{(f"... 还有 {len(no_sku_items) - 20} 个" if len(no_sku_items) > 20 else "")}

---

## 3. 缺失字段统计

| 字段 | 缺失商品数 | 占比 |
|------|-----------|------|
"""

    for field, count in sorted(field_missing_counts.items(), key=lambda x: -x[1]):
        pct = count / total_items * 100
        report += f"| {field} | {count} | {pct:.1f}% |\n"

    report += f"""
---

## 4. 数据质量警告统计

| 警告类型 | 涉及商品数 |
|----------|-----------|
"""

    for wtype, count in sorted(warning_counts.items(), key=lambda x: -x[1]):
        report += f"| {wtype} | {count} |\n"

    report += f"""
---

## 5. 完整度评分分布

| 分数段 | 商品数 | 占比 |
|--------|--------|------|
| 0-30 分（L0 未覆盖） | {score_buckets['0-30']} | {score_buckets['0-30'] / total_items * 100:.1f}% |
| 30-50 分（L1 可识别） | {score_buckets['30-50']} | {score_buckets['30-50'] / total_items * 100:.1f}% |
| 50-80 分（L2 可建议） | {score_buckets['50-80']} | {score_buckets['50-80'] / total_items * 100:.1f}% |
| 80-100 分（L3 高可用） | {score_buckets['80-100']} | {score_buckets['80-100'] / total_items * 100:.1f}% |

---

## 6. Agent 可用等级分布

| 等级 | 商品数 | 占比 | 说明 |
|------|--------|------|------|
| L0 未覆盖 | {level_counts['L0']} | {level_counts['L0'] / total_items * 100:.1f}% | 不允许 Agent 使用 |
| L1 可识别 | {level_counts['L1']} | {level_counts['L1'] / total_items * 100:.1f}% | 只能识别，不建议直接回复 |
| L2 可建议 | {level_counts['L2']} | {level_counts['L2'] / total_items * 100:.1f}% | 可生成建议，需人工复验 |
| L3 高可用 | {level_counts['L3']} | {level_counts['L3'] / total_items * 100:.1f}% | 可作为客服主要依据 |

---

## 7. Top 20 需要补全的商品

| i_id | 商品名称 | SKU数 | 缺失字段数 | 评分 | 等级 |
|------|----------|-------|-----------|------|------|
"""

    for card in top_missing:
        name = (card.get("product_name") or "")[:20]
        report += f"| {card['i_id']} | {name} | {card['sku_summary']['sku_count']} | {len(card.get('missing_fields', []))} | {card['completeness_score']} | {card['agent_usable_level']} |\n"

    report += f"""
---

## 8. 补全任务统计

| 优先级 | 任务数 |
|--------|--------|
| H（高） | {sum(1 for r in missing_rows if r['priority'] == 'H')} |
| M（中） | {sum(1 for r in missing_rows if r['priority'] == 'M')} |
| L（低） | {sum(1 for r in missing_rows if r['priority'] == 'L')} |
| **总计** | **{len(missing_rows)}** |

---

## 9. 下一步建议

1. **优先处理 H 级任务**: 补充缺失商品名称和 SKU 信息的商品
2. **库存数据同步**: 当前库存数据仅覆盖最近 6 个月（{len(inventory)} 条），建议定期全量同步
3. **客服知识字段补全**: material、size、package_list 等字段需要运营手动补充
4. **图片补全**: 为无图商品补充主图和 SKU 图
5. **FAQ 和禁止承诺**: 在基础数据完善后，为 L2/L3 商品生成 FAQ 草稿
6. **定期更新**: 建议每周增量拉取新商品数据，更新知识卡

---

*报告由 generate_product_cards.py 自动生成*
"""

    report_path = os.path.join(SCRIPT_DIR, "data_quality_report.md")
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report)
    print(f"  [OK] data_quality_report.md")

    # ---- 6. 最终统计 ----
    print("\n" + "=" * 60)
    print("生成完成！最终统计:")
    print(f"  商品知识卡: {len(product_cards)} 张")
    print(f"  SKU 明细: {len(sku_cards_rows)} 行")
    print(f"  补全任务: {len(missing_rows)} 条")
    print(f"  Agent 可用等级分布: L0={level_counts['L0']}, L1={level_counts['L1']}, L2={level_counts['L2']}, L3={level_counts['L3']}")
    print(f"  平均完整度评分: {sum(c['completeness_score'] for c in product_cards) / len(product_cards):.1f}")
    print("=" * 60)


if __name__ == "__main__":
    main()
