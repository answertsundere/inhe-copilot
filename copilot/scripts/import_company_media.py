"""从公司共享盘导入「规格图」和「资质/证书图」到素材库。

用法（在已能访问共享盘的电脑上执行）：
    python scripts/import_company_media.py "\\\\192.168.110.110\\货品部资料 宁波同步温州"

可选参数：
    --dry-run     只打印会导入哪些文件，不写入数据库
    --skip-copy   不复制文件到本地，只记录原始 UNC/本地路径
    --limit N     最多导入 N 张，用于小批量验证

规则：
- 排除以下目录（及其子目录）：
  AAA_XXXX（成品图存档） - 副本、AAA_XXXX（成品图存档）、A 各类资质证书、
  3D模型（优化分数）、0通用类、00Eagle、（临时）产品尺寸标注检查、#recycle
- 只处理扩展名：png, jpg, jpeg, webp
- 产品身份证取第二级目录名的第一段，例如：
  ...\LSJ 沥水架类\LSJW002 2号洞洞板沥水架\... -> i_id=LSJW002
- 扫描范围：每个商品目录下的
  "08 详情\新版详情页"
  如果该目录下还有子文件夹（如"翻新"、"翻新 - 副本"），按文件夹修改时间倒序，
  优先从最新的文件夹里找；找不到再降级到"新版详情页"外层。
- 只导入文件名包含以下关键字的图片：
  * 「规格」「产品」→ 产品规格图（size_image）
  * 「资质」「证书」→ 证书图（certificate_image）
- 导入后状态：approved + usable_for_agent=1，并关联到对应 i_id 的商品，
  以便在「商品资料 → 商品素材」中直接看到。
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# 把项目根目录加入 path，确保能 import app
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import app.models.kb_tables  # noqa: F401
from app.db import SessionLocal
from app.models.kb_tables import KBMediaAsset, KBProduct
from app.services.media_asset_service import get_auto_send_level

# ─── 配置 ───
EXCLUDED_TOP_DIRS = {
    "AAA_XXXX（成品图存档） - 副本",
    "AAA_XXXX（成品图存档）",
    "A 各类资质证书",
    "3D模型（优化分数）",
    "0通用类",
    "00Eagle",
    "（临时）产品尺寸标注检查",
    "#recycle",
}

ALLOWED_EXTS = {".png", ".jpg", ".jpeg", ".webp"}

# 详情页文件夹名称（商品目录下任意层级出现都扫描）
DETAIL_FOLDER_NAMES = {"新版详情页", "08 详情"}

# 目标本地目录（与 media_routes 上传目录保持一致）
UPLOAD_BASE = PROJECT_ROOT / "app" / "media_uploads"

# 运营端素材用途 -> 底层 asset_type
MEDIA_PURPOSE_TO_ASSET_TYPE = {
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

SPEC_KEYWORDS = ["规格", "产品"]
CERT_KEYWORDS = ["资质", "证书"]


def classify_media_purpose(filename: str) -> Optional[tuple[str, list[str]]]:
    """只接受规格图和证书/资质图，其余返回 None（跳过）。"""
    name_lower = filename.lower()
    if any(k in name_lower for k in SPEC_KEYWORDS):
        return "size_image", ["dimensions"]
    if any(k in name_lower for k in CERT_KEYWORDS):
        return "certificate_image", ["certificate"]
    return None


def parse_product_identity(dir_name: str) -> tuple[str, str]:
    """从 'LSJW002 2号洞洞板沥水架' 解析出 i_id 和 product_name。"""
    parts = dir_name.strip().split(None, 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return parts[0], parts[0]


def file_md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_upload_dir() -> Path:
    today = datetime.now().strftime("%Y-%m-%d")
    target = UPLOAD_BASE / today
    target.mkdir(parents=True, exist_ok=True)
    return target


def should_skip_dir(rel_path: Path) -> bool:
    """相对路径的第一级如果在排除列表里，就跳过整棵子树。"""
    parts = rel_path.parts
    if not parts:
        return False
    return parts[0] in EXCLUDED_TOP_DIRS


def dir_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def find_best_detail_files(detail_dir: Path) -> list[Path]:
    """
    对「新版详情页」目录做版本降级选择：
    1. 把外层 detail_dir 本身和它的直接子文件夹一起按修改时间倒序。
    2. 依次只扫描每个候选文件夹的直接文件。
    3. 第一个找到匹配文件的候选，返回该候选里的所有匹配文件；都没有返回空。
    """
    if not detail_dir.exists() or not detail_dir.is_dir():
        return []

    candidates = [detail_dir]
    try:
        for child in detail_dir.iterdir():
            if child.is_dir():
                candidates.append(child)
    except PermissionError:
        pass

    candidates.sort(key=dir_mtime, reverse=True)

    for candidate in candidates:
        try:
            files = [f for f in candidate.iterdir() if f.is_file()]
        except PermissionError:
            continue
        matching = [
            f for f in files
            if f.suffix.lower() in ALLOWED_EXTS and classify_media_purpose(f.name) is not None
        ]
        if matching:
            # 同一个候选文件夹内，按修改时间最新的排在前面
            matching.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            return matching

    return []


def import_media(root: Path, dry_run: bool, skip_copy: bool, limit: Optional[int] = None) -> None:
    db = SessionLocal()
    try:
        total = 0
        imported = 0
        dup = 0
        reached_limit = False

        # 预加载 i_id -> KBProduct 映射，方便关联 product_id
        product_map = {p.i_id: p for p in db.query(KBProduct).filter(KBProduct.i_id != "").all()}

        target_dir = ensure_upload_dir() if not skip_copy else None
        today_str = datetime.now().strftime("%Y-%m-%d")

        for dirpath, dirnames, filenames in os.walk(root):
            if reached_limit:
                break

            current = Path(dirpath)
            try:
                rel = current.relative_to(root)
            except ValueError:
                rel = Path()

            # 排除顶层垃圾目录
            if should_skip_dir(rel):
                dirnames[:] = []
                continue

            # 只处理名为「新版详情页」或「08 详情」的文件夹
            if current.name not in DETAIL_FOLDER_NAMES:
                continue

            # 必须有足够深的层级才能拿到产品身份证
            parts = rel.parts
            if len(parts) < 2:
                continue

            i_id, product_name = parse_product_identity(parts[1])
            kb_product = product_map.get(i_id)

            files = find_best_detail_files(current)
            if not files:
                # 即使当前 detail_dir 没有匹配文件，也不再继续向下递归（子文件夹已在 find_best_detail_files 中处理）
                dirnames[:] = []
                continue

            for src in files:
                if limit is not None and imported >= limit:
                    reached_limit = True
                    break

                total += 1
                classified = classify_media_purpose(src.name)
                if classified is None:
                    continue
                purpose, scenarios = classified
                asset_type = MEDIA_PURPOSE_TO_ASSET_TYPE.get(purpose, purpose)

                # 复制到本地可访问目录，或保留原路径
                if skip_copy:
                    asset_url = str(src)
                    content_hash = file_md5(src)
                else:
                    content_hash = file_md5(src)
                    stored_name = f"{content_hash[:16]}{src.suffix.lower()}"
                    dest = target_dir / stored_name
                    if not dest.exists():
                        shutil.copy2(src, dest)
                    asset_url = f"/ask/api/media-assets/uploads/{today_str}/{stored_name}"

                # 去重：同一产品同一类型同一文件内容
                existing = (
                    db.query(KBMediaAsset)
                    .filter(KBMediaAsset.i_id == i_id)
                    .filter(KBMediaAsset.asset_type == asset_type)
                    .filter(KBMediaAsset.content_hash == content_hash)
                    .first()
                )
                if existing:
                    dup += 1
                    if not dry_run:
                        existing.last_seen_at = datetime.utcnow()
                        existing.updated_at = datetime.utcnow()
                    continue

                imported += 1

                if dry_run:
                    print(f"[DRY-RUN] {i_id} | {purpose} | {src}")
                    continue

                asset = KBMediaAsset(
                    product_id=kb_product.id if kb_product else None,
                    i_id=i_id,
                    sku_code="",
                    product_name=kb_product.product_name if kb_product else product_name,
                    asset_type=asset_type,
                    asset_title=src.name,
                    asset_url=asset_url,
                    source="company_share",
                    source_doc_id="",
                    content_hash=content_hash,
                    match_confidence=1.0,
                    match_reason="公司共享盘导入",
                    status="approved",
                    audit_status="reviewed",
                    usable_for_agent=1,
                    reviewed_by="import_script",
                    created_by="import_script",
                    updated_by="import_script",
                    last_seen_at=datetime.utcnow(),
                )
                asset.set_scene_tags([])
                asset.set_source_raw({
                    "media_purpose": purpose,
                    "applicable_style": {"scope_type": "all", "scope_values": [], "scope_note": ""},
                    "answer_scenarios": scenarios,
                    "auto_send_level": get_auto_send_level(asset),
                    "original_path": str(src),
                })
                db.add(asset)

            # 已经处理完当前 detail 文件夹，不再继续向下递归
            dirnames[:] = []

        if not dry_run:
            db.commit()

        print(f"\n扫描文件: {total}")
        print(f"新导入: {imported}")
        print(f"重复跳过: {dup}")
        if dry_run:
            print("本次为演习，未写入数据库。")
    except Exception as e:
        db.rollback()
        print(f"导入失败: {e}", file=sys.stderr)
        raise
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="从公司共享盘导入规格图和证书图到素材库")
    parser.add_argument("root", help="共享盘根目录，例如 '\\\\192.168.110.110\\货品部资料 宁波同步温州'")
    parser.add_argument("--dry-run", action="store_true", help="只打印，不写入数据库")
    parser.add_argument("--skip-copy", action="store_true", help="不复制文件到本地，只记录原始路径")
    parser.add_argument("--limit", type=int, default=None, help="最多导入 N 张，用于小批量验证")
    args = parser.parse_args()

    root = Path(args.root)
    if not root.exists():
        print(f"路径不存在或无法访问: {root}", file=sys.stderr)
        sys.exit(1)

    import_media(root, args.dry_run, args.skip_copy, args.limit)


if __name__ == "__main__":
    main()
