"""Read-only inventory for product-media annotation and detector feasibility."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.extract_product_media_observations import (  # noqa: E402
    ReadOnlyDatabaseGuard,
    _formal_kb_state_fingerprint,
    load_project_dotenv,
)

load_project_dotenv()
import app.models.kb_tables  # noqa: E402,F401
from app.db import SessionLocal  # noqa: E402
from app.models.kb_tables import KBMediaAsset  # noqa: E402
from app.services.product_media_annotation_schema_service import annotation_priority, image_reference, is_annotation_image_asset  # noqa: E402


def _scene_tags(asset: Any) -> set[str]:
    values = asset.get_scene_tags() if hasattr(asset, "get_scene_tags") else getattr(asset, "scene_tags", [])
    return {str(value).strip().lower() for value in values} if isinstance(values, list) else set()


def build_report(assets: list[Any]) -> dict[str, Any]:
    roles = Counter(str(getattr(asset, "asset_type", "other") or "other") for asset in assets)
    image_assets = [asset for asset in assets if is_annotation_image_asset(asset)]
    tag_sets = [_scene_tags(asset) for asset in image_assets]
    reference_ready = sum(1 for asset in image_assets if image_reference(asset)[0])
    stored_ocr = sum(1 for asset in image_assets if isinstance((asset.get_source_raw() or {}).get("ocr_items"), list))
    stored_candidates = sum(1 for asset in image_assets if isinstance((asset.get_source_raw() or {}).get("model_candidates"), list))
    priorities = Counter(reason for _priority, reason in (annotation_priority(asset) for asset in image_assets))
    eligible = reference_ready
    pilot_count = min(eligible, 120)
    return {
        "schema_version": "product_media_annotation_feasibility_v1",
        "shadow_only": True,
        "total_media_count": len(assets),
        "annotatable_image_media_count": len(image_assets),
        "media_with_annotation_image_reference_count": reference_ready,
        "media_role_counts": dict(sorted(roles.items())),
        "dimension_image_count": roles["size_image"],
        "packaging_image_count": sum(1 for tags in tag_sets if "packaging" in tags),
        "mode_image_count": sum(1 for tags in tag_sets if "mode" in tags),
        "multi_panel_image_count": sum(1 for tags in tag_sets if "multi_panel" in tags),
        "current_ocr_available_count": stored_ocr,
        "current_object_provider_success_count": stored_candidates,
        "current_shadow_metadata_note": "OCR and object qualifications are not persisted as product facts or observations.",
        "suggested_min_annotation_count": pilot_count,
        "recommended_labeling_priority": [
            {"priority": 1, "task_type": "尺寸标注与对象范围", "selection_basis": "size_image 媒体角色"},
            {"priority": 2, "task_type": "包装、模式和多面板范围", "selection_basis": "结构化 scene_tags"},
            {"priority": 3, "task_type": "配件、随附物和展示道具范围", "selection_basis": "accessory_image 与其他已标记媒体角色"},
        ],
        "priority_reason_counts": dict(sorted(priorities.items())),
        "training_candidate_model_options": [
            "YOLO 系列：先训练视觉范围类别，不训练尺寸关系或商品事实。",
            "MMDetection 或 Detectron2：当需要 COCO 格式评测和更细的实例检测实验时评估。",
            "Layout/OCR 组合：保留 OCR 文字框，由后续人工审核关系标注，不直接从文字生成事实。",
        ],
        "estimated_risks": [
            "少量样本只能验证标注一致性与过拟合风险，不能证明跨商品泛化。",
            "包装、部件、模式图和商品整体必须分别标注，否则会污染尺寸关系训练。",
            "高风险文字只能作为拒绝或人工复核信号，不得作为检测模型的可回答标签。",
        ],
        "formal_kb_write_attempt_count": 0,
        "can_change_can_send_count": 0,
    }


def run() -> dict[str, Any]:
    db = SessionLocal()
    guard = ReadOnlyDatabaseGuard(db)
    try:
        guard.enable()
        before = _formal_kb_state_fingerprint(db)
        assets = db.query(KBMediaAsset).order_by(KBMediaAsset.id.asc()).all()
        report = build_report(assets)
        after = _formal_kb_state_fingerprint(db)
        report.update({
            "database_query_only": guard.enabled,
            "formal_kb_state_unchanged": before == after,
            "formal_kb_write_attempt_count": guard.write_attempt_count,
        })
        return report
    finally:
        guard.close()
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-output", default="outputs/product_media_annotation_feasibility.json")
    args = parser.parse_args(argv)
    report = run()
    output = PROJECT_ROOT / args.json_output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
