"""Read-only validation for a Label Studio product-media annotation export.

Human rectangles and relations remain external review data.  This tool never
creates ProductMediaObservation records, knowledge entries, review candidates,
or delivery changes.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.product_media_annotation_schema_service import (  # noqa: E402
    LABEL_STUDIO_RELATION_TYPES,
    OBJECT_LABELS,
    canonical_annotation_label,
)


_OBJECT_SCOPES = {"product_overall", "packaging", "component", "accessory", "included_item", "display_prop"}
_TEXT_SCOPES = {"label_text_region", "dimension_label_region", "high_risk_text_region"}
_PANEL_SCOPES = {"product_panel", "mode_panel"}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _tasks(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict) and isinstance(value.get("tasks"), list):
        return [item for item in value["tasks"] if isinstance(item, dict)]
    return []


def _meta(task: dict[str, Any]) -> dict[str, Any]:
    return task.get("meta") if isinstance(task.get("meta"), dict) else {}


def _annotation_results(task: dict[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    annotations = task.get("annotations") if isinstance(task.get("annotations"), list) else []
    for annotation in annotations:
        if not isinstance(annotation, dict) or annotation.get("was_cancelled"):
            continue
        results = annotation.get("result")
        if isinstance(results, list):
            return annotation, [item for item in results if isinstance(item, dict)]
    return None, []


def _bbox(result: dict[str, Any]) -> tuple[float, float, float, float] | None:
    value = result.get("value") if isinstance(result.get("value"), dict) else {}
    try:
        bbox = tuple(float(value[key]) for key in ("x", "y", "width", "height"))
    except (KeyError, TypeError, ValueError):
        return None
    x, y, width, height = bbox
    if width <= 0 or height <= 0 or x < 0 or y < 0 or x + width > 100 or y + height > 100:
        return None
    return bbox


def _labels(result: dict[str, Any]) -> list[str]:
    value = result.get("value") if isinstance(result.get("value"), dict) else {}
    raw = value.get("rectanglelabels") if isinstance(value.get("rectanglelabels"), list) else []
    return [canonical_annotation_label(label) for label in raw]


def _manifest_index(manifest: Any) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for task in _tasks(manifest):
        uid = _text(_meta(task).get("task_uid"))
        if uid:
            index[uid] = task
    return index


def _relation_legal(relation: str, source: str, target: str) -> bool:
    if relation == "part_of":
        return source in {"component", "accessory", "included_item"} and target == "product_overall"
    if relation == "labelled_by":
        return source in _OBJECT_SCOPES and target in {"label_text_region", "dimension_label_region"}
    if relation == "visible_in":
        return source in _OBJECT_SCOPES | _TEXT_SCOPES and target in _PANEL_SCOPES
    if relation == "active_in_mode":
        return source in {"product_overall", "component"} and target == "mode_panel"
    return False


def validate_annotation_tasks(exported: Any, manifest: Any) -> dict[str, Any]:
    """Validate official Label Studio export shape and external-review boundaries."""
    expected = _manifest_index(manifest)
    seen_uids: set[str] = set()
    task_results: list[dict[str, Any]] = []
    error_counts: Counter[str] = Counter()
    manual_annotation_count = 0

    for task in _tasks(exported):
        errors: list[str] = []
        meta = _meta(task)
        uid = _text(meta.get("task_uid"))
        if not uid:
            errors.append("task_uid_missing")
        elif uid in seen_uids:
            errors.append("duplicate_task_uid")
        else:
            seen_uids.add(uid)
        expected_task = expected.get(uid)
        if not expected_task:
            errors.append("task_uid_not_in_manifest")
        else:
            expected_meta = _meta(expected_task)
            for field in ("media_asset_id", "source_image_sha256"):
                if _text(meta.get(field)) != _text(expected_meta.get(field)):
                    errors.append(f"{field}_mismatch")
        if not _text(meta.get("media_asset_id")):
            errors.append("media_asset_id_missing")
        if not _text(meta.get("schema_version")):
            errors.append("annotation_schema_version_missing")

        annotation, results = _annotation_results(task)
        if annotation is None:
            errors.append("manual_annotation_missing")
        else:
            manual_annotation_count += 1
            if annotation.get("completed_by") in (None, ""):
                errors.append("annotator_missing")
            if not _text(annotation.get("updated_at") or annotation.get("created_at")):
                errors.append("review_time_missing")

        regions: dict[str, str] = {}
        relation_rows: list[dict[str, Any]] = []
        region_keys: set[tuple[str, tuple[float, float, float, float]]] = set()
        for result in results:
            result_type = _text(result.get("type"))
            if result_type == "relation":
                relation_rows.append(result)
                continue
            if result_type != "rectanglelabels":
                errors.append("annotation_result_type_invalid")
                continue
            labels = _labels(result)
            bbox = _bbox(result)
            region_id = _text(result.get("id"))
            if not region_id:
                errors.append("region_id_missing")
            if len(labels) != 1:
                errors.append("region_label_count_invalid")
                continue
            label = labels[0]
            if label not in OBJECT_LABELS:
                errors.append("unknown_label")
                continue
            if bbox is None:
                errors.append("bbox_invalid_or_out_of_bounds")
                continue
            key = (label, tuple(round(value, 4) for value in bbox))
            if key in region_keys:
                errors.append("duplicate_region")
            region_keys.add(key)
            regions[region_id] = label

        dimension_relation_ids: set[str] = set()
        for relation_row in relation_rows:
            source_id = _text(relation_row.get("from_id"))
            target_id = _text(relation_row.get("to_id"))
            labels = relation_row.get("labels") if isinstance(relation_row.get("labels"), list) else []
            if len(labels) != 1 or _text(labels[0]) not in LABEL_STUDIO_RELATION_TYPES:
                errors.append("relation_label_invalid")
                continue
            relation = _text(labels[0])
            source = regions.get(source_id)
            target = regions.get(target_id)
            if not source or not target:
                errors.append("relation_endpoint_missing")
                continue
            if not _relation_legal(relation, source, target):
                errors.append("relation_scope_invalid")
            if relation == "labelled_by" and target == "dimension_label_region":
                dimension_relation_ids.add(target_id)

        for region_id, label in regions.items():
            if label == "dimension_label_region" and region_id not in dimension_relation_ids:
                errors.append("dimension_relation_missing")
            if label == "high_risk_text_region":
                continue
        for error in set(errors):
            error_counts[error] += 1
        task_results.append({
            "task_uid": uid,
            "media_asset_id": _text(meta.get("media_asset_id")),
            "manual_annotation_present": annotation is not None,
            "region_count": len(regions),
            "relation_count": len(relation_rows),
            "errors": sorted(set(errors)),
            "passed": not errors,
        })

    passed_count = sum(1 for result in task_results if result["passed"])
    return {
        "schema_version": "product_media_annotation_validation_v1",
        "shadow_only": True,
        "total_task_count": len(task_results),
        "manual_annotation_count": manual_annotation_count,
        "passed_task_count": passed_count,
        "failed_task_count": len(task_results) - passed_count,
        "all_tasks_have_manual_annotations": bool(task_results) and manual_annotation_count == len(task_results),
        "error_counts": dict(sorted(error_counts.items())),
        "tasks": task_results,
        "formal_kb_write_attempt_count": 0,
        "product_media_observation_write_attempt_count": 0,
        "pending_review_created_count": 0,
        "can_change_can_send_count": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Label Studio JSON export")
    parser.add_argument("--task-manifest", required=True, help="Original task manifest")
    parser.add_argument("--json-output", default="outputs/product_media_annotation_validation.json")
    args = parser.parse_args(argv)
    report = validate_annotation_tasks(_load_json(Path(args.input)), _load_json(Path(args.task_manifest)))
    output = PROJECT_ROOT / args.json_output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8-sig")
    print(json.dumps({key: value for key, value in report.items() if key != "tasks"}, ensure_ascii=False))
    return 0 if not report["error_counts"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
