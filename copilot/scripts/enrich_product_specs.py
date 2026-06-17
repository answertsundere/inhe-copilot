"""用 VLM 从规格图自动提取商品规格草稿。

用法：
    set OPENAI_API_KEY=your_api_key_here
    set OPENAI_BASE_URL=https://apihub.agnes-ai.com/v1
    python scripts/enrich_product_specs.py --limit 5 --dry-run

可选参数：
    --limit N       最多处理 N 个商品
    --dry-run       只打印 VLM 输出，不写入数据库
    --model MODEL   模型名，默认 gpt-4o
    --apply         把结果写回 specs_json（默认不写，需配合 --dry-run=false）

安全说明：
- API Key 请通过环境变量 OPENAI_API_KEY 传入，不要写进脚本或命令历史。
- 提取结果会作为「草稿」写入 specs_json，并保留来源备注，建议人工复核后再发布。
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import app.models.kb_tables  # noqa: F401
import requests
from app.db import SessionLocal
from app.models.kb_tables import KBMediaAsset, KBProduct
from app.repositories.kb_product_repository import _compute_completeness
from sqlalchemy import case

DEFAULT_MODEL = "gpt-4o"
DEFAULT_TEMPERATURE = 0.2

# 要提取的字段说明（与完整度计算保持一致）
FIELD_PROMPT = """
请根据这张商品规格/详情图，提取以下字段。如果图片里确实没有某一项，请填 ""。
输出必须是纯 JSON，不要加 markdown 代码块，不要解释。

{
  "product_name": "商品名（如果图上有更准确的名称）",
  "brand": "品牌",
  "specs": {
    "material": "材质",
    "size": "尺寸/规格",
    "load_capacity": "承重/容量",
    "age_range": "适用年龄",
    "accessories": "配件清单",
    "install_method": "安装方式",
    "detachable": "是否可拆卸",
    "drill_required": "是否需打孔",
    "installation_time": "安装耗时",
    "installation_difficulty": "安装难度",
    "rental_friendly": "租房/墙面友好说明",
    "pinch_safety": "防夹/安全设计",
    "stability_note": "稳定性说明",
    "moisture": "防潮说明",
    "cleaning": "清洁保养",
    "odor_note": "气味说明",
    "certification_report": "合格证/质检资料",
    "size_image_note": "尺寸图补充说明"
  },
  "warranty": {
    "period": "质保期"
  },
  "logistics": {
    "attribute": "物流属性"
  }
}
"""


def image_to_base64(data: bytes, ext: str) -> str:
    ext = ext.lower().lstrip(".")
    if ext == "jpg":
        ext = "jpeg"
    mime = f"image/{ext}" if ext in ("png", "jpeg", "webp") else "image/png"
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def resolve_image_bytes(asset: KBMediaAsset) -> Optional[tuple[bytes, str]]:
    """返回图片二进制数据和扩展名。支持本地文件和 http(s) URL。"""
    url = asset.asset_url or ""

    # 1. 本地相对路径（从上传目录读取）
    if url.startswith("/ask/api/media-assets/uploads/"):
        rel = url.replace("/ask/api/media-assets/uploads/", "")
        local = PROJECT_ROOT / "app" / "media_uploads" / rel
        if local.exists():
            return local.read_bytes(), local.suffix

    # 2. 本地 UNC/绝对路径
    sr = asset.get_source_raw() or {}
    original = sr.get("original_path")
    if original and Path(original).exists():
        p = Path(original)
        return p.read_bytes(), p.suffix

    # 3. 远程 URL（钉钉/OSS 等）
    if url.startswith(("http://", "https://")):
        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            ext = Path(url.split("?", 1)[0]).suffix or ".png"
            return r.content, ext
        except Exception:
            return None

    return None


def call_vlm(api_key: str, base_url: str, model: str, image_b64: str, context: dict) -> dict:
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    system_msg = "你是一位商品信息录入助手，擅长从商品规格图/详情图里提取结构化参数。只输出 JSON，不输出其他内容。"
    user_text = f"商品代码: {context.get('i_id', '')}\n商品名称: {context.get('product_name', '')}\n类目: {context.get('category', '')}\n\n{FIELD_PROMPT}"

    payload = {
        "model": model,
        "temperature": DEFAULT_TEMPERATURE,
        "messages": [
            {"role": "system", "content": system_msg},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {"url": image_b64}},
                ],
            },
        ],
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    raw = data["choices"][0]["message"]["content"]

    # 清理 markdown 代码块
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"VLM 返回不是有效 JSON: {raw}") from e


def merge_specs(existing: dict, extracted: dict) -> dict:
    """用提取值填充现有空字段，已有值保留。"""
    result = dict(existing)
    for section in ("specs", "warranty", "logistics"):
        if section not in extracted:
            continue
        result.setdefault(section, {})
        for k, v in extracted.get(section, {}).items():
            if not v:
                continue
            current = result[section].get(k)
            if current in (None, "", "-", "--", "无", "暂无", "详见商品详情页", "见详情页"):
                result[section][k] = v
    # product_name/brand 只在空时覆盖
    for top in ("product_name", "brand"):
        if extracted.get(top) and not result.get(top):
            result[top] = extracted[top]
    return result


def enrich_products(limit: Optional[int], dry_run: bool, apply: bool, model: str) -> None:
    api_key = os.environ.get("OPENAI_API_KEY")
    base_url = os.environ.get("OPENAI_BASE_URL", "https://apihub.agnes-ai.com/v1")
    if not api_key:
        print("请先设置环境变量 OPENAI_API_KEY", file=sys.stderr)
        sys.exit(1)

    db = SessionLocal()
    try:
        # 优先处理完整度低、且有关联规格图的商品
        products = (
            db.query(KBProduct)
            .filter(KBProduct.status.in_(["draft", "published"]))
            .order_by(KBProduct.completeness_score.asc())
            .limit(limit or 10000)
            .all()
        )

        processed = 0
        enriched = 0

        for product in products:
            if limit and processed >= limit:
                break

            # 优先找 size_image，没有再找 pack_guide_image / sku_image / install_image
            asset = (
                db.query(KBMediaAsset)
                .filter(KBMediaAsset.i_id == product.i_id)
                .filter(KBMediaAsset.asset_type.in_([
                    "size_image", "pack_guide_image", "sku_image", "install_image"
                ]))
                .filter(KBMediaAsset.status == "approved")
                .order_by(
                    case(
                        (KBMediaAsset.asset_type == "size_image", 1),
                        (KBMediaAsset.asset_type == "pack_guide_image", 2),
                        (KBMediaAsset.asset_type == "sku_image", 3),
                        (KBMediaAsset.asset_type == "install_image", 4),
                        else_=5,
                    ),
                    KBMediaAsset.updated_at.desc(),
                )
                .first()
            )
            if not asset:
                continue

            resolved = resolve_image_bytes(asset)
            if not resolved:
                print(f"[{product.i_id}] 无法读取图片: {asset.asset_url}")
                continue

            processed += 1
            context = {
                "i_id": product.i_id,
                "product_name": product.product_name,
                "category": f"{product.category_l1 or ''}/{product.category_l2 or ''}/{product.category_l3 or ''}",
            }

            print(f"\n[{processed}/{limit or len(products)}] 处理 {product.i_id} - {product.product_name}")

            try:
                image_data, ext = resolved
                image_b64 = image_to_base64(image_data, ext)
                extracted = call_vlm(api_key, base_url, model, image_b64, context)
            except Exception as e:
                print(f"  VLM 调用失败: {e}")
                continue

            print(f"  提取结果: {json.dumps(extracted, ensure_ascii=False, indent=2)[:400]}...")

            if dry_run:
                continue

            if not apply:
                print("  未加 --apply，跳过写入")
                continue

            # 合并 specs/warranty/logistics
            current_specs = product.get_specs() or {}
            merged = merge_specs(current_specs, extracted)

            # 标记自动提取来源
            auto_note = {
                "_auto_enriched_at": datetime.utcnow().isoformat(),
                "_auto_enriched_from": str(asset.asset_url),
                "_auto_enriched_model": model,
            }
            merged.setdefault("_meta", {}).update(auto_note)

            product.set_specs(merged)
            if extracted.get("product_name") and not product.product_name:
                product.product_name = extracted["product_name"]
            if extracted.get("brand") and not product.brand:
                product.brand = extracted["brand"]

            # 重算完整度
            score, missing = _compute_completeness(product)
            product.completeness_score = round(score * 100, 1)
            product.set_missing_fields(missing)
            enriched += 1

        db.commit()
        print(f"\n处理商品数: {processed}")
        print(f"成功 enrichment: {enriched}")
        if dry_run:
            print("本次为演习，未写入数据库。")
        elif not apply:
            print("未加 --apply，未写入数据库。")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="用 VLM 从规格图提取商品规格草稿")
    parser.add_argument("--limit", type=int, default=None, help="最多处理 N 个商品")
    parser.add_argument("--dry-run", action="store_true", help="只打印 VLM 输出，不写入数据库")
    parser.add_argument("--apply", action="store_true", help="确认把结果写回数据库")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="模型名，默认 gpt-4o")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        print("提示：未加 --apply，结果不会写入数据库。如需写入请加上 --apply。", file=sys.stderr)

    enrich_products(args.limit, args.dry_run, args.apply, args.model)


if __name__ == "__main__":
    main()
