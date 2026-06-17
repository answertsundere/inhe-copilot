#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从钉钉多维表 SKU数据库 拉取安装视频和打包指南，
匹配并同步到本地商品知识库 (kb_product)。

用法:
    python sync_dingtalk_media.py              # 仅生成报告
    python sync_dingtalk_media.py --update-db  # 生成报告并写入数据库
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

# ─── 加载 .env ───
_project_root = Path(__file__).parent.parent
_env_path = _project_root / ".env"
if _env_path.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=_env_path)
    except Exception:
        pass

# ─── 配置 ───
CLIENT_ID = os.environ.get("COPILOT_DT_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("COPILOT_DT_CLIENT_SECRET", "")
OPERATOR_ID = os.environ.get("COPILOT_DT_OPERATOR_ID", "")
BASE_ID = os.environ.get("COPILOT_DT_BASE_ID", "")
SHEET_ID = os.environ.get("COPILOT_DT_SKU_DB_SHEET_ID", "m6ZKv2m")

# ─── 工具函数 ───

def _get_access_token() -> str:
    url = "https://api.dingtalk.com/v1.0/oauth2/accessToken"
    resp = requests.post(url, json={"appKey": CLIENT_ID, "appSecret": CLIENT_SECRET}, timeout=30)
    data = resp.json()
    if resp.status_code != 200 or "accessToken" not in data:
        raise RuntimeError(f"获取钉钉 token 失败: {data}")
    return data["accessToken"]


def _fetch_all_records(base_id: str, sheet_id: str) -> list:
    token = _get_access_token()
    url = f"https://api.dingtalk.com/v1.0/notable/bases/{base_id}/sheets/{sheet_id}/records/list"
    headers = {
        "x-acs-dingtalk-access-token": token,
        "Content-Type": "application/json",
    }
    params = {"operatorId": OPERATOR_ID}

    all_records = []
    next_token = None
    page = 1

    while True:
        body = {"maxResults": 100}
        if next_token:
            body["nextToken"] = next_token

        resp = requests.post(url, headers=headers, params=params, json=body, timeout=60)
        if resp.status_code != 200:
            print(f"  第 {page} 页请求失败: {resp.status_code} {resp.text}")
            break

        data = resp.json()
        records = data.get("records", [])
        all_records.extend(records)
        print(f"  第 {page} 页获取 {len(records)} 条，累计 {len(all_records)}")

        next_token = data.get("nextToken")
        if not next_token:
            break
        page += 1
        time.sleep(0.2)

    return all_records


def _extract_media(record: dict) -> dict:
    fields = record.get("fields", {})

    # 安装视频（支持抖音、B站）
    videos = {}
    for key, label in [("安装视频(抖音)", "douyin"), ("安装视频(B站)", "bilibili")]:
        val = fields.get(key)
        if isinstance(val, dict) and val.get("link"):
            videos[label] = {"url": val["link"], "title": val.get("text", "")}

    # 打包指南图片
    pack_images = []
    val = fields.get("打包指南")
    if isinstance(val, list):
        for item in val:
            if isinstance(item, dict) and item.get("url"):
                pack_images.append(item["url"])

    # SKU 图
    sku_images = []
    val = fields.get("SKU图")
    if isinstance(val, list):
        for item in val:
            if isinstance(item, dict) and item.get("url"):
                sku_images.append(item["url"])

    return {
        "sku_code": str(fields.get("商品编码-公式", "")).strip(),
        "product_name": str(fields.get("产品名称绑定", "")).strip(),
        "videos": videos,
        "pack_guide_images": pack_images,
        "sku_images": sku_images,
    }


# ─── 主流程 ───

def main():
    parser = argparse.ArgumentParser(description="同步钉钉多维表媒体数据到商品库")
    parser.add_argument("--update-db", action="store_true", help="是否将匹配结果写入 kb_product.specs_json")
    parser.add_argument("--output", default="dingtalk_media_report.json", help="JSON 报告输出路径")
    args = parser.parse_args()

    # 0. 校验配置
    missing = []
    if not CLIENT_ID:
        missing.append("COPILOT_DT_CLIENT_ID")
    if not CLIENT_SECRET:
        missing.append("COPILOT_DT_CLIENT_SECRET")
    if not OPERATOR_ID:
        missing.append("COPILOT_DT_OPERATOR_ID")
    if not BASE_ID:
        missing.append("COPILOT_DT_BASE_ID")
    if missing:
        print(f"错误: 缺少环境变量: {', '.join(missing)}")
        print("请在 copilot/.env 中配置钉钉多维表凭据。")
        sys.exit(1)

    # 1. 拉取钉钉数据
    print("=" * 60)
    print("步骤 1: 从钉钉多维表拉取 SKU数据库")
    print(f"  Base ID : {BASE_ID}")
    print(f"  Sheet ID: {SHEET_ID}")
    records = _fetch_all_records(BASE_ID, SHEET_ID)
    print(f"  共拉取 {len(records)} 条记录")

    # 2. 解析媒体字段
    print("\n步骤 2: 解析安装视频 / 打包指南 / SKU图")
    sku_media_map = {}
    for rec in records:
        media = _extract_media(rec)
        if media["sku_code"]:
            sku_media_map[media["sku_code"]] = media

    total_skus = len(sku_media_map)
    with_video = sum(1 for m in sku_media_map.values() if m["videos"])
    with_pack = sum(1 for m in sku_media_map.values() if m["pack_guide_images"])
    with_sku_img = sum(1 for m in sku_media_map.values() if m["sku_images"])
    print(f"  有安装视频的 SKU : {with_video} / {total_skus}")
    print(f"  有打包指南的 SKU : {with_pack} / {total_skus}")
    print(f"  有 SKU 图的 SKU  : {with_sku_img} / {total_skus}")

    # 3. 连接本地数据库
    print("\n步骤 3: 连接本地商品库")
    sys.path.insert(0, str(_project_root))
    from app.db import SessionLocal
    from app.models.kb_tables import KBProduct

    db = SessionLocal()
    try:
        products = db.query(KBProduct).all()
        print(f"  本地商品总数: {len(products)}")

        # 4. 匹配（精确匹配 + i_id 前缀匹配）
        print("\n步骤 4: 按 SKU 编码匹配（精确 + i_id 前缀）")

        # 预先构建前缀索引，加速前缀查找
        prefix_map = {}  # prefix -> [sku_code, ...]
        for dt_sku_code in sku_media_map:
            # 提取可能的款号前缀：YH01K01B04S05 -> YH01K01
            # 规则：去掉最后一段 BxxSxx 或 Sxx 后缀
            parts = dt_sku_code.split("B")
            if len(parts) >= 3:
                # YH01K01B04S05 -> 分割为 [YH01K01, 04S05]，prefix = YH01K01
                prefix = "B".join(parts[:-2])  # 取除最后两段外的所有
                if not prefix:
                    prefix = parts[0]
            elif len(parts) == 2:
                prefix = parts[0]
            else:
                prefix = dt_sku_code

            if prefix not in prefix_map:
                prefix_map[prefix] = []
            prefix_map[prefix].append(dt_sku_code)

        matched_video = 0
        matched_pack = 0
        matched_sku_img = 0
        unmatched_products = []
        product_updates = []
        report = []

        for product in products:
            skus = product.get_sku_list()
            product_videos = {}
            product_packs = []
            product_sku_imgs = []
            matched_dt_skus = set()
            match_reasons = []

            # 策略 A: i_id 精确匹配
            if product.i_id in sku_media_map:
                media = sku_media_map[product.i_id]
                matched_dt_skus.add(product.i_id)
                if media["videos"]:
                    product_videos.update(media["videos"])
                if media["pack_guide_images"]:
                    product_packs.extend(media["pack_guide_images"])
                if media["sku_images"]:
                    product_sku_imgs.extend(media["sku_images"])
                match_reasons.append(f"i_id_exact:{product.i_id}")

            # 策略 B: i_id 前缀匹配（款号匹配多个 SKU）
            if product.i_id in prefix_map:
                for dt_sku_code in prefix_map[product.i_id]:
                    if dt_sku_code in matched_dt_skus:
                        continue
                    media = sku_media_map[dt_sku_code]
                    matched_dt_skus.add(dt_sku_code)
                    if media["videos"]:
                        product_videos.update(media["videos"])
                    if media["pack_guide_images"]:
                        product_packs.extend(media["pack_guide_images"])
                    if media["sku_images"]:
                        product_sku_imgs.extend(media["sku_images"])
                if product.i_id not in [r.split(":")[1] for r in match_reasons if r.startswith("i_id_exact:")]:
                    match_reasons.append(f"i_id_prefix:{product.i_id}")

            # 策略 C: sku_list 精确匹配
            for sku_entry in skus:
                sku_code = (
                    sku_entry.get("sku_code", "")
                    if isinstance(sku_entry, dict)
                    else str(sku_entry)
                )
                if not sku_code:
                    continue
                if sku_code in sku_media_map and sku_code not in matched_dt_skus:
                    media = sku_media_map[sku_code]
                    matched_dt_skus.add(sku_code)
                    if media["videos"]:
                        product_videos.update(media["videos"])
                    if media["pack_guide_images"]:
                        product_packs.extend(media["pack_guide_images"])
                    if media["sku_images"]:
                        product_sku_imgs.extend(media["sku_images"])
                    match_reasons.append(f"sku_exact:{sku_code}")

            # 去重并保持顺序
            product_packs = list(dict.fromkeys(product_packs))
            product_sku_imgs = list(dict.fromkeys(product_sku_imgs))

            has_video = len(product_videos) > 0
            has_pack = len(product_packs) > 0
            has_sku_img = len(product_sku_imgs) > 0

            if has_video:
                matched_video += 1
            if has_pack:
                matched_pack += 1
            if has_sku_img:
                matched_sku_img += 1

            report.append({
                "product_id": product.id,
                "i_id": product.i_id,
                "product_name": product.product_name,
                "match_reasons": match_reasons,
                "matched_dt_skus": sorted(matched_dt_skus),
                "has_install_video": has_video,
                "has_pack_guide": has_pack,
                "has_sku_images": has_sku_img,
                "install_videos": product_videos,
                "pack_guide_images": product_packs[:5],
                "sku_images": product_sku_imgs[:5],
            })

            if not matched_dt_skus:
                unmatched_products.append(product.i_id)

            # 准备数据库更新
            if args.update_db and (has_video or has_pack or has_sku_img):
                specs = product.get_specs()
                updated = False

                if has_video:
                    specs["install_videos"] = product_videos
                    updated = True
                if has_pack:
                    specs["pack_guide_images"] = product_packs
                    updated = True
                if has_sku_img:
                    specs["sku_images"] = product_sku_imgs
                    updated = True

                if updated:
                    product.set_specs(specs)
                    product_updates.append(product)

        # 5. 保存报告
        output_path = Path(args.output)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump({
                "summary": {
                    "dingtalk_total_skus": total_skus,
                    "dingtalk_with_video": with_video,
                    "dingtalk_with_pack_guide": with_pack,
                    "dingtalk_with_sku_images": with_sku_img,
                    "local_total_products": len(products),
                    "local_matched_video": matched_video,
                    "local_matched_pack_guide": matched_pack,
                    "local_matched_sku_images": matched_sku_img,
                    "local_unmatched_products_count": len(unmatched_products),
                    "local_unmatched_products_sample": sorted(unmatched_products)[:50],
                },
                "details": report,
            }, f, ensure_ascii=False, indent=2)
        print(f"\n报告已保存: {output_path.resolve()}")

        # 6. 写入数据库
        if args.update_db:
            print(f"\n步骤 5: 写入数据库")
            if product_updates:
                for p in product_updates:
                    db.add(p)
                db.commit()
                print(f"  已更新 {len(product_updates)} 条商品记录")
            else:
                print("  无数据需要更新")

        # 7. 汇总
        print("\n" + "=" * 60)
        print("同步完成")
        print(f"  钉钉 SKU 总数              : {total_skus}")
        print(f"  钉钉有安装视频             : {with_video}")
        print(f"  钉钉有打包指南             : {with_pack}")
        print(f"  本地商品总数               : {len(products)}")
        print(f"  本地商品匹配到视频         : {matched_video}")
        print(f"  本地商品匹配到打包指南     : {matched_pack}")
        print(f"  本地商品匹配到 SKU 图      : {matched_sku_img}")
        print(f"  完全未匹配的商品数         : {len(unmatched_products)}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
