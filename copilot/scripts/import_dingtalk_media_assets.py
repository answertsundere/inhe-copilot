#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把钉钉媒体报告导入正式素材表 kb_media_asset。

设计要点：
- 默认 dry-run；必须加 --apply 才真正写库。
- content_hash 基于「稳定 URL 路径 + i_id + sku_code + asset_type」生成，
  去掉签名 query 参数（Expires/Signature/OSSAccessKeyId），避免重签被当成新素材。
- 同 content_hash 已存在：更新 last_seen_at / source_updated_at / url_expires_at / refresh_status，
  不重复插入，且不重置已审核状态（已 approved 素材不会被改回 pending_review）。
- URL 真正变化时可选重置为待审核（--reset-urls-on-change）。
- 支持按 type / product_id / i_id / sku_code / limit 小批量导入。
- 支持 --auto-approve-low-risk：对 install_video / pack_guide_image / sku_image 自动审核通过。

用法:
    python scripts/import_dingtalk_media_assets.py --dry-run
    python scripts/import_dingtalk_media_assets.py --apply --limit 5 --type sku_image
    python scripts/import_dingtalk_media_assets.py --apply --refresh
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))


# 允许自动审核的低风险素材类型（需显式开启 --auto-approve-low-risk）
_LOW_RISK_AUTO_APPROVE_TYPES = {"install_video", "pack_guide_image", "sku_image"}


def _stable_url_key(url: str) -> str:
    """去掉签名 query 参数，只保留 scheme+host+path 作为稳定 key。

    alidocs / OSS 图片 URL 形如：
    https://alidocs2.oss.../img/xxxx.png?Expires=...&OSSAccessKeyId=...&Signature=...
    每次同步签名都会变，但 path 是稳定的。
    """
    if not url:
        return ""
    parsed = urlparse(url.strip())
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def parse_url_expires(url: str) -> Optional[datetime]:
    """解析 URL 中的过期时间参数（Unix 秒）。"""
    if not url:
        return None
    try:
        from urllib.parse import parse_qs

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


def compute_content_hash(i_id: str, sku_code: str, asset_type: str, asset_url: str) -> str:
    raw = "|".join([
        (i_id or "").strip(),
        (sku_code or "").strip(),
        (asset_type or "").strip(),
        _stable_url_key(asset_url),
    ])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _build_assets_from_detail(detail: dict):
    """把一个 detail 拆成若干待入库的 asset 行（dict）。"""
    i_id = str(detail.get("i_id", "") or "").strip()
    product_id = detail.get("product_id")
    product_name = str(detail.get("product_name", "") or "").strip()
    matched_dt_skus = detail.get("matched_dt_skus") or []
    match_reasons = detail.get("match_reasons") or []
    match_reason_text = "; ".join(match_reasons) if match_reasons else ""

    # sku_code 取 matched_dt_skus 第一个或 i_id（i_id 本身通常也是款号）
    primary_sku = matched_dt_skus[0] if matched_dt_skus else i_id

    rows = []

    # 1) 安装视频 install_videos: {platform: {url, title}}
    install_videos = detail.get("install_videos") or {}
    if isinstance(install_videos, dict):
        for platform, info in install_videos.items():
            if not isinstance(info, dict):
                continue
            url = str(info.get("url", "") or "").strip()
            if not url:
                continue
            title = str(info.get("title", "") or "").strip() or f"{product_name} 安装视频"
            rows.append({
                "product_id": product_id,
                "i_id": i_id,
                "sku_code": str(primary_sku or ""),
                "product_name": product_name,
                "asset_type": "install_video",
                "asset_title": title,
                "asset_url": url,
                "source": "dingtalk",
                "source_doc_id": f"dt_sku_db:{platform}",
                "match_confidence": 0.9,
                "match_reason": match_reason_text,
                "source_raw": {"platform": platform, **info},
                "scene_tags": ["安装咨询"],
            })

    # 2) 包装/安装指导图 pack_guide_images: [url, ...]
    pack_guide_images = detail.get("pack_guide_images") or []
    if isinstance(pack_guide_images, list):
        for url in pack_guide_images:
            url = str(url or "").strip()
            if not url:
                continue
            rows.append({
                "product_id": product_id,
                "i_id": i_id,
                "sku_code": str(primary_sku or ""),
                "product_name": product_name,
                "asset_type": "pack_guide_image",
                "asset_title": f"{product_name} 打包/安装指导图".strip(),
                "asset_url": url,
                "source": "dingtalk",
                "source_doc_id": "dt_sku_db:pack_guide",
                "match_confidence": 0.85,
                "match_reason": match_reason_text,
                "source_raw": {"bucket": "pack_guide"},
                "scene_tags": ["安装咨询", "配件缺失"],
            })

    # 3) SKU 图 sku_images: [url, ...]
    sku_images = detail.get("sku_images") or []
    if isinstance(sku_images, list):
        for url in sku_images:
            url = str(url or "").strip()
            if not url:
                continue
            rows.append({
                "product_id": product_id,
                "i_id": i_id,
                "sku_code": str(primary_sku or ""),
                "product_name": product_name,
                "asset_type": "sku_image",
                "asset_title": f"{product_name} 商品图".strip(),
                "asset_url": url,
                "source": "dingtalk",
                "source_doc_id": "dt_sku_db:sku_image",
                "match_confidence": 0.8,
                "match_reason": match_reason_text,
                "source_raw": {"bucket": "sku_image"},
                "scene_tags": ["商品咨询", "尺寸咨询"],
            })

    return rows


def _matches_filters(row: dict, *, asset_type: Optional[str], product_id: Optional[int],
                     i_id: Optional[str], sku_code: Optional[str]) -> bool:
    if asset_type and row["asset_type"] != asset_type:
        return False
    if product_id is not None and row.get("product_id") != product_id:
        return False
    if i_id and row.get("i_id") != i_id:
        return False
    if sku_code and row.get("sku_code") != sku_code:
        return False
    return True


def _is_low_risk_auto_approvable(asset_type: str) -> bool:
    return asset_type in _LOW_RISK_AUTO_APPROVE_TYPES


def import_report(
    report_path: str,
    *,
    reset_urls_on_change: bool = False,
    dry_run: bool = False,
    limit: Optional[int] = None,
    asset_type: Optional[str] = None,
    product_id: Optional[int] = None,
    i_id: Optional[str] = None,
    sku_code: Optional[str] = None,
    auto_approve_low_risk: bool = False,
    source_updated_at: Optional[datetime] = None,
):
    """执行导入。返回统计 dict。"""
    import app.models.kb_tables  # noqa: F401  register models
    from app.db import SessionLocal, init_db
    from app.models.kb_tables import KBMediaAsset

    init_db()

    with open(report_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    summary = data.get("summary", {}) if isinstance(data, dict) else {}
    details = data.get("details", []) if isinstance(data, dict) else []

    stats = {
        "total_products_read": len(details),
        "new_assets": 0,
        "updated_assets": 0,
        "approved_assets": 0,
        "install_video": 0,
        "pack_guide_image": 0,
        "sku_image": 0,
        "unmatched_products": int(summary.get("local_unmatched_products_count", 0)),
        "failures": [],
        "url_reset_to_pending": 0,
        "skipped_by_filter": 0,
    }

    now = datetime.utcnow()
    source_updated_at = source_updated_at or now

    # 预构建待处理行
    all_rows = []
    for detail in details:
        try:
            rows = _build_assets_from_detail(detail)
        except Exception as e:
            stats["failures"].append({"i_id": detail.get("i_id"), "error": str(e)})
            continue
        for r in rows:
            if _matches_filters(r, asset_type=asset_type, product_id=product_id,
                                i_id=i_id, sku_code=sku_code):
                all_rows.append(r)
            else:
                stats["skipped_by_filter"] += 1

    if limit:
        all_rows = all_rows[:limit]

    stats["filtered_assets"] = len(all_rows)

    if dry_run:
        for r in all_rows:
            stats[r["asset_type"]] = stats.get(r["asset_type"], 0) + 1
        return stats

    db = SessionLocal()
    try:
        for r in all_rows:
            chash = compute_content_hash(r["i_id"], r["sku_code"], r["asset_type"], r["asset_url"])
            url_expires_at = parse_url_expires(r["asset_url"])
            refresh_status = "ok" if (not url_expires_at or url_expires_at > now) else "needs_refresh"

            existing = db.query(KBMediaAsset).filter(KBMediaAsset.content_hash == chash).first()
            if existing:
                # 更新 last_seen_at / source_updated_at / url_expires_at / refresh_status
                existing.last_seen_at = now
                existing.source_updated_at = source_updated_at
                existing.set_source_raw({**existing.get_source_raw(), **r.get("source_raw", {})})

                if existing.asset_url != r["asset_url"]:
                    existing.asset_url = r["asset_url"]
                    existing.url_expires_at = url_expires_at
                    existing.refresh_status = refresh_status
                    if reset_urls_on_change and existing.status == "approved":
                        existing.status = "pending_review"
                        existing.audit_status = "unreviewed"
                        existing.usable_for_agent = 0
                        stats["url_reset_to_pending"] += 1
                else:
                    # URL 未变也刷新过期时间（签名可能已续期但 path 不变，expires 参数会更新）
                    existing.url_expires_at = url_expires_at
                    existing.refresh_status = refresh_status

                # 对刷新后仍处于 pending_review 的低风险素材，按策略自动审核
                if (
                    auto_approve_low_risk
                    and existing.status == "pending_review"
                    and _is_low_risk_auto_approvable(r["asset_type"])
                    and refresh_status == "ok"
                ):
                    existing.status = "approved"
                    existing.audit_status = "reviewed"
                    existing.usable_for_agent = 1
                    existing.reviewed_by = "dingtalk_auto_approve"
                    stats["approved_assets"] += 1

                existing.updated_at = now
                stats["updated_assets"] += 1
                continue

            # 新素材：默认 pending_review / usable_for_agent=0
            asset = KBMediaAsset(
                product_id=r["product_id"],
                i_id=r["i_id"],
                sku_code=r["sku_code"],
                product_name=r["product_name"],
                asset_type=r["asset_type"],
                asset_title=r["asset_title"],
                asset_url=r["asset_url"],
                source=r["source"],
                source_doc_id=r["source_doc_id"],
                match_confidence=r["match_confidence"],
                match_reason=r["match_reason"],
                status="pending_review",
                audit_status="unreviewed",
                usable_for_agent=0,
                content_hash=chash,
                created_by="import_dingtalk_media",
                last_seen_at=now,
                source_updated_at=source_updated_at,
                url_expires_at=url_expires_at,
                refresh_status=refresh_status,
            )
            asset.set_source_raw(r.get("source_raw", {}))
            asset.set_scene_tags(r.get("scene_tags", []))

            # 自动审核低风险类型（仅当链接未过期且显式开启）
            if auto_approve_low_risk and _is_low_risk_auto_approvable(r["asset_type"]) and refresh_status == "ok":
                asset.status = "approved"
                asset.audit_status = "reviewed"
                asset.usable_for_agent = 1
                asset.reviewed_by = "dingtalk_auto_approve"
                stats["approved_assets"] += 1

            db.add(asset)
            stats["new_assets"] += 1
            stats[r["asset_type"]] = stats.get(r["asset_type"], 0) + 1

        db.commit()

        # 去重刷新：同一张图/视频被多个商品引用时，旧关联可能因签名过期变成 needs_refresh；
        # 这里用同稳定路径下最新的有效 URL 回填所有重复项，避免一个商品正常、另一个商品显示过期。
        if not dry_run:
            _refresh_duplicate_urls(db, now)
            db.commit()
    finally:
        db.close()

    return stats


def _refresh_duplicate_urls(db, now: datetime) -> int:
    """把同稳定路径下的过期/旧 URL 刷新为组内最新 URL。"""
    from collections import defaultdict
    from app.models.kb_tables import KBMediaAsset
    assets = db.query(KBMediaAsset).all()
    groups = defaultdict(list)
    for a in assets:
        path = ""
        try:
            path = urlparse(a.asset_url or "").path
        except Exception:
            path = a.asset_url or ""
        if path:
            groups[path].append(a)

    refreshed = 0
    for path, group in groups.items():
        if len(group) <= 1:
            continue
        best = max(group, key=lambda a: a.url_expires_at or datetime.min.replace(tzinfo=None))
        if not best.url_expires_at:
            continue
        for a in group:
            if a.id == best.id:
                continue
            if a.asset_url != best.asset_url or a.url_expires_at != best.url_expires_at or a.refresh_status != best.refresh_status:
                a.asset_url = best.asset_url
                a.url_expires_at = best.url_expires_at
                a.refresh_status = best.refresh_status
                a.updated_at = now
                refreshed += 1
    return refreshed


def main():
    parser = argparse.ArgumentParser(description="导入钉钉素材报告到 kb_media_asset")
    parser.add_argument(
        "--report",
        default=str(_PROJECT_ROOT / "data" / "dingtalk_media_report_v2.json"),
        help="钉钉素材报告 JSON 路径",
    )
    parser.add_argument("--apply", action="store_true", help="真正写库（默认 dry-run）")
    parser.add_argument("--dry-run", action="store_true", help=argparse.SUPPRESS)  # 兼容旧参数
    parser.add_argument("--limit", type=int, default=None, help="限制处理的素材行数")
    parser.add_argument(
        "--type", dest="asset_type",
        choices=["install_video", "pack_guide_image", "sku_image"],
        default=None,
        help="只导入指定素材类型",
    )
    parser.add_argument("--product-id", type=int, default=None, help="按 product_id 过滤")
    parser.add_argument("--i-id", default=None, help="按 i_id 过滤")
    parser.add_argument("--sku-code", default=None, help="按 sku_code 过滤")
    parser.add_argument(
        "--reset-urls-on-change", action="store_true",
        help="URL 变化时把已审核素材重置为 pending_review（默认关闭，保持稳定 key 不触发）",
    )
    parser.add_argument(
        "--auto-approve-low-risk", action="store_true", dest="auto_approve_low_risk",
        help="自动审核 install_video / pack_guide_image / sku_image（默认不自动审核）",
    )
    args = parser.parse_args()

    if not os.path.exists(args.report):
        print(f"错误: 报告文件不存在: {args.report}")
        sys.exit(1)

    # dry-run 为默认；--apply 显式放行；--dry-run 保持兼容
    dry_run = not args.apply

    print("=" * 60)
    print("导入钉钉素材到 kb_media_asset")
    print(f"  报告: {args.report}")
    print(f"  模式: {'APPLY' if args.apply else 'DRY-RUN'}")
    print("=" * 60)

    stats = import_report(
        args.report,
        reset_urls_on_change=args.reset_urls_on_change,
        dry_run=dry_run,
        limit=args.limit,
        asset_type=args.asset_type,
        product_id=args.product_id,
        i_id=args.i_id,
        sku_code=args.sku_code,
        auto_approve_low_risk=args.auto_approve_low_risk,
    )

    print(f"\n总读取商品数        : {stats['total_products_read']}")
    print(f"通过过滤素材数      : {stats.get('filtered_assets', stats.get('new_assets', 0) + stats.get('updated_assets', 0))}")
    print(f"跳过（过滤条件）    : {stats['skipped_by_filter']}")
    print(f"新增素材数          : {stats['new_assets']}")
    print(f"更新素材数          : {stats['updated_assets']}")
    print(f"自动审核通过数      : {stats['approved_assets']}")
    print(f"安装视频数量        : {stats['install_video']}")
    print(f"安装/包装指导图数量 : {stats['pack_guide_image']}")
    print(f"SKU 图片数量        : {stats['sku_image']}")
    print(f"未匹配商品数量      : {stats['unmatched_products']}")
    if stats["url_reset_to_pending"]:
        print(f"URL 变化重置为待审核: {stats['url_reset_to_pending']}")
    if stats["failures"]:
        print(f"\n失败记录样例 ({len(stats['failures'])} 条):")
        for f in stats["failures"][:5]:
            print(f"  i_id={f.get('i_id')}: {f.get('error')}")
    if dry_run:
        print("\n(dry-run 模式，未写库)")
    print("\n导入完成。")


if __name__ == "__main__":
    main()
