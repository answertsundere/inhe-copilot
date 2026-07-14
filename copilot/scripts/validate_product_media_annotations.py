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
    ANNOTATION_SCHEMA_VERSION,
    ATTRIBUTE_KEYS,
    DIMENSION_SCOPES,
    EVIDENCE_STATUSES,
    IMAGE_SCOPES,
    LABEL_STUDIO_RELATION_TYPES,
    OBJECT_LABELS,
    VISUAL_DESCRIPTION_SCHEMA_VERSION,
    canonical_annotation_label,
    canonical_dimension_attribute,
    canonical_dimension_scope,
    canonical_evidence_status,
    canonical_image_scope,
    canonical_object_representation,
    canonical_annotation_relation,
    task_authoring_labels,
)


_OBJECT_SCOPES = {"product_overall", "packaging", "component", "accessory", "included_item", "display_prop"}
_TEXT_SCOPES = {"label_text_region", "dimension_label_region", "high_risk_text_region"}
_DOCUMENT_SCOPES = {"compliance_document_region"}
_PANEL_SCOPES = {"product_panel", "mode_panel"}
_CONTROL_RESULT_TYPES = {"choices", "textarea"}
_HIGH_RISK_TERMS = (
    "承重", "无毒", "有毒", "食品级", "认证", "检测", "适用年龄", "年龄", "安全", "防倾倒", "固定墙", "墙面固定", "甲醛",
    "load capacity", "non-toxic", "toxic", "food grade", "certification", "age", "child safety", "anti-tip", "wall mounting", "formaldehyde",
)
_UNSUPPORTED_DESCRIPTION_TERMS = (
    "适合", "推荐", "安全可靠", "性能优良", "结实耐用", "不会夹", "售后", "包退", "保修", "赔付", "补发",
    "suitable for", "recommended", "safe and reliable", "warranty", "refund", "replacement", "compensation",
)


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
    if relation == "object_part_of_product":
        return source in {"component", "accessory", "included_item"} and target == "product_overall"
    if relation == "dimension_measures_object":
        return source == "dimension_label_region" and target in {"product_overall", "component", "packaging"}
    if relation == "panel_contains_object":
        return source in _OBJECT_SCOPES | _TEXT_SCOPES and target in _PANEL_SCOPES
    if relation == "object_active_in_mode":
        return source in {"product_overall", "component"} and target == "mode_panel"
    if relation == "label_describes_object":
        return source in {"label_text_region", "high_risk_text_region"} and target in _OBJECT_SCOPES | _DOCUMENT_SCOPES
    return False


def _control_values(result: dict[str, Any]) -> list[str]:
    value = result.get("value") if isinstance(result.get("value"), dict) else {}
    if isinstance(value.get("choices"), list):
        return [_text(item) for item in value["choices"] if _text(item)]
    if isinstance(value.get("text"), list):
        return [_text(item) for item in value["text"] if _text(item)]
    if _text(value.get("text")):
        return [_text(value.get("text"))]
    return []


def _control_region_id(result: dict[str, Any]) -> str:
    return _text(result.get("parentID") or result.get("parent_id") or result.get("id"))


def _single_control(
    controls: dict[str, list[str]],
    name: str,
    errors: list[str],
    *,
    required: bool = False,
) -> str:
    values = controls.get(name) or []
    if required and not values:
        errors.append(f"{name}_missing")
        return ""
    if len(values) > 1:
        errors.append(f"{name}_multiple")
    return values[0] if values else ""


def _contains_high_risk_text(value: str) -> bool:
    normalized = _text(value).lower()
    return any(term in normalized for term in _HIGH_RISK_TERMS)


def _contains_unsupported_description(value: str) -> bool:
    normalized = _text(value).lower()
    return _contains_high_risk_text(normalized) or any(term in normalized for term in _UNSUPPORTED_DESCRIPTION_TERMS)


def _product_context(expected_task: dict[str, Any]) -> dict[str, Any]:
    meta = _meta(expected_task)
    return {
        "product_identity": dict(meta.get("product_identity") or {}),
        "product_title_reference": _text(meta.get("product_title_reference") or meta.get("product_title_for_human_aid")),
        "variant_or_color_reference": _text(meta.get("variant_or_color_reference")),
        "source_of_product_context": _text(meta.get("source_of_product_context")),
    }


def _structured_description(
    *,
    expected_task: dict[str, Any],
    profile: str,
    regions: dict[str, dict[str, Any]],
    relations: list[dict[str, str]],
    global_controls: dict[str, list[str]],
    region_controls: dict[str, dict[str, list[str]]],
    errors: list[str],
) -> dict[str, Any]:
    product_context = _product_context(expected_task)
    if not any(product_context["product_identity"].values()):
        errors.append("product_identity_missing")
    if not _text(_meta(expected_task).get("source_image_sha256")):
        errors.append("source_image_sha256_missing")
    image_scope = canonical_image_scope(
        _single_control(global_controls, "image_scope", errors, required=True)
    )
    if image_scope not in IMAGE_SCOPES:
        errors.append("image_scope_invalid")
    summary = _single_control(global_controls, "reviewed_visual_summary", errors, required=True)
    if _contains_unsupported_description(summary):
        errors.append("reviewed_visual_summary_contains_unsupported_claim")
    if profile == "packaging_dimension" and image_scope != "packaging":
        errors.append("packaging_image_scope_invalid")
    if profile == "compliance_document" and image_scope != "document":
        errors.append("compliance_document_image_scope_invalid")
    if profile in {"mode_dimension", "product_specification"} and image_scope not in {"product", "mixed", "unknown"}:
        errors.append("product_image_scope_invalid")
    variant_reference = _single_control(global_controls, "variant_or_color_reference", errors)
    if not variant_reference:
        variant_reference = _text(_meta(expected_task).get("variant_or_color_reference"))

    panel_by_object: dict[str, str] = {}
    parent_by_object: dict[str, str] = {}
    measured_object_by_dimension: dict[str, str] = {}
    active_mode_by_object: dict[str, str] = {}
    for relation in relations:
        if relation["relation"] == "panel_contains_object":
            panel_by_object[relation["source_id"]] = relation["target_id"]
        elif relation["relation"] == "object_part_of_product":
            parent_by_object[relation["source_id"]] = relation["target_id"]
        elif relation["relation"] == "dimension_measures_object":
            measured_object_by_dimension[relation["source_id"]] = relation["target_id"]
        elif relation["relation"] == "object_active_in_mode":
            active_mode_by_object[relation["source_id"]] = relation["target_id"]

    panels: list[dict[str, Any]] = []
    objects: list[dict[str, Any]] = []
    visible_claims: list[dict[str, Any]] = []
    high_risk_regions: list[dict[str, Any]] = []
    dimensions: list[dict[str, Any]] = []
    for region_id, region in regions.items():
        label = region["label"]
        controls = region_controls.get(region_id, {})
        provenance = {
            "task_uid": _text(_meta(expected_task).get("task_uid")),
            "media_asset_id": _text(_meta(expected_task).get("media_asset_id")),
            "source_image_sha256": _text(_meta(expected_task).get("source_image_sha256")),
            "region_id": region_id,
            "bbox": region["bbox"],
        }
        if label in _PANEL_SCOPES:
            summary_name = "mode_panel_summary" if label == "mode_panel" else "product_panel_summary"
            panel_summary = _single_control(controls, summary_name, errors)
            mode_or_state = _single_control(controls, "mode_or_state", errors, required=label == "mode_panel")
            panels.append({
                "panel_id": region_id,
                "panel_type": label,
                "mode_or_state": mode_or_state,
                "panel_summary": panel_summary,
                "provenance": provenance,
            })
            continue
        if label in _OBJECT_SCOPES:
            representation = canonical_object_representation(
                _single_control(controls, "object_representation", errors, required=label == "product_overall")
            )
            if label == "product_overall" and representation != "actual":
                errors.append("product_instance_not_confirmed_actual")
            visual_description = _single_control(controls, f"{label}_visual_description", errors)
            if _contains_unsupported_description(visual_description):
                errors.append("object_visual_description_contains_unsupported_claim")
            objects.append({
                "object_id": region_id,
                "object_scope": label,
                "parent_panel_id": panel_by_object.get(region_id, ""),
                "parent_object_id": parent_by_object.get(region_id, ""),
                "visual_description": visual_description,
                "is_printed_representation": representation == "printed",
                "is_actual_product_object": representation == "actual",
                "active_in_mode": active_mode_by_object.get(region_id, ""),
                "provenance": provenance,
            })
            continue
        if label in {"label_text_region", "high_risk_text_region"}:
            field = "high_risk_visible_text" if label == "high_risk_text_region" else "label_visible_text"
            visible_text = _single_control(controls, field, errors, required=True)
            claim = {
                "region_id": region_id,
                "text": visible_text,
                "evidence_status": "rejected" if label == "high_risk_text_region" else "visible_only",
                "provenance": provenance,
            }
            if label == "high_risk_text_region":
                high_risk_regions.append(claim)
            else:
                if _contains_high_risk_text(visible_text):
                    errors.append("high_risk_text_must_use_high_risk_region")
                visible_claims.append(claim)
            continue
        if label == "dimension_label_region":
            raw_value = _single_control(controls, "dimension_visible_value", errors, required=True)
            unit = _single_control(controls, "dimension_unit", errors, required=True)
            attribute_key = canonical_dimension_attribute(
                _single_control(controls, "dimension_attribute", errors, required=True)
            )
            scope = canonical_dimension_scope(
                _single_control(controls, "dimension_scope", errors, required=True)
            )
            evidence_status = canonical_evidence_status(
                _single_control(controls, "dimension_evidence_status", errors, required=True)
            )
            measured_object_id = measured_object_by_dimension.get(region_id, "")
            if attribute_key not in ATTRIBUTE_KEYS | {"unknown"}:
                errors.append("dimension_attribute_invalid")
            if scope not in DIMENSION_SCOPES:
                errors.append("dimension_scope_invalid")
            if evidence_status not in EVIDENCE_STATUSES:
                errors.append("dimension_evidence_status_invalid")
            target_label = regions.get(measured_object_id, {}).get("label", "")
            expected_scope = {
                "packaging": "packaging",
                "component": "component",
                "product_overall": "mode_specific" if measured_object_id in active_mode_by_object or profile == "mode_dimension" else "product_overall",
            }.get(target_label, "")
            if expected_scope and scope != expected_scope:
                errors.append("dimension_scope_object_mismatch")
            if profile == "packaging_dimension" and scope != "packaging":
                errors.append("packaging_dimension_scope_invalid")
            if profile == "mode_dimension" and scope not in {"component", "mode_specific"}:
                errors.append("mode_dimension_scope_invalid")
            if scope == "mode_specific" and measured_object_id not in active_mode_by_object:
                errors.append("mode_specific_relation_missing")
            dimensions.append({
                "dimension_label_id": region_id,
                "raw_value": raw_value,
                "unit": unit,
                "attribute_key": attribute_key,
                "measured_object_id": measured_object_id,
                "scope": scope,
                "evidence_status": evidence_status,
                "provenance": provenance,
            })

    meta = _meta(expected_task)
    return {
        "schema_version": VISUAL_DESCRIPTION_SCHEMA_VERSION,
        "shadow_only": True,
        "used_for_generation": False,
        "can_change_can_send": False,
        "product_context": product_context,
        "image": {
            "media_role": _text(meta.get("media_role")),
            "image_scope": image_scope,
            "reviewed_visual_summary": summary,
            "variant_or_color_reference": variant_reference,
            "visible_claims": visible_claims,
            "high_risk_text_regions": high_risk_regions,
            "provenance": {
                "task_uid": _text(meta.get("task_uid")),
                "media_asset_id": _text(meta.get("media_asset_id")),
                "source_image_sha256": _text(meta.get("source_image_sha256")),
            },
        },
        "panels": panels,
        "objects": objects,
        "dimensions": dimensions,
    }


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
        allowed_labels = task_authoring_labels(expected_task) if expected_task else set()
        profile = ""
        if not expected_task:
            errors.append("task_uid_not_in_manifest")
        else:
            expected_meta = _meta(expected_task)
            profile = _text(expected_meta.get("annotation_profile"))
            for field in ("media_asset_id", "source_image_sha256"):
                if _text(meta.get(field)) != _text(expected_meta.get(field)):
                    errors.append(f"{field}_mismatch")
            if _text(meta.get("annotation_profile")) != profile:
                errors.append("annotation_profile_mismatch")
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

        regions: dict[str, dict[str, Any]] = {}
        relation_rows: list[dict[str, Any]] = []
        control_rows: list[dict[str, Any]] = []
        global_controls: dict[str, list[str]] = {}
        region_controls: dict[str, dict[str, list[str]]] = {}
        region_keys: set[tuple[str, tuple[float, float, float, float]]] = set()
        for result in results:
            result_type = _text(result.get("type"))
            if result_type == "relation":
                relation_rows.append(result)
                continue
            if result_type in _CONTROL_RESULT_TYPES:
                control_rows.append(result)
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
            if not allowed_labels or label not in allowed_labels:
                errors.append("task_profile_label_not_allowed")
                continue
            if bbox is None:
                errors.append("bbox_invalid_or_out_of_bounds")
                continue
            key = (label, tuple(round(value, 4) for value in bbox))
            if key in region_keys:
                errors.append("duplicate_region")
            region_keys.add(key)
            regions[region_id] = {"label": label, "bbox": bbox}

        for control_row in control_rows:
            control_name = _text(control_row.get("from_name"))
            values = _control_values(control_row)
            region_id = _control_region_id(control_row)
            if region_id in regions or control_row.get("parentID"):
                region_controls.setdefault(region_id, {}).setdefault(control_name, []).extend(values)
            else:
                global_controls.setdefault(control_name, []).extend(values)

        dimension_subject_ids: dict[str, str] = {}
        panel_relation_sources: set[str] = set()
        relations: list[dict[str, str]] = []
        for relation_row in relation_rows:
            source_id = _text(relation_row.get("from_id"))
            target_id = _text(relation_row.get("to_id"))
            labels = relation_row.get("labels") if isinstance(relation_row.get("labels"), list) else []
            if len(labels) != 1 or _text(labels[0]) not in LABEL_STUDIO_RELATION_TYPES:
                errors.append("relation_label_invalid")
                continue
            relation = canonical_annotation_relation(labels[0])
            source = regions.get(source_id, {}).get("label")
            target = regions.get(target_id, {}).get("label")
            if not source or not target:
                errors.append("relation_endpoint_missing")
                continue
            if not _relation_legal(relation, source, target):
                errors.append("relation_scope_invalid")
            relations.append({"relation": relation, "source_id": source_id, "target_id": target_id})
            if relation == "dimension_measures_object":
                dimension_subject_ids[source_id] = target_id
            if relation == "panel_contains_object":
                panel_relation_sources.add(source_id)

        has_panels = any(region["label"] in _PANEL_SCOPES for region in regions.values())
        for region_id, region in regions.items():
            label = region["label"]
            if label == "dimension_label_region":
                subject_id = dimension_subject_ids.get(region_id)
                if not subject_id:
                    errors.append("dimension_subject_missing")
                elif has_panels and subject_id not in panel_relation_sources:
                    errors.append("dimension_panel_scope_missing")
            if label == "high_risk_text_region":
                continue
        structured_description = None
        if annotation is not None and expected_task and _text(_meta(expected_task).get("schema_version")) == ANNOTATION_SCHEMA_VERSION:
            structured_description = _structured_description(
                expected_task=expected_task,
                profile=profile,
                regions=regions,
                relations=relations,
                global_controls=global_controls,
                region_controls=region_controls,
                errors=errors,
            )
        for error in set(errors):
            error_counts[error] += 1
        task_results.append({
            "task_uid": uid,
            "media_asset_id": _text(meta.get("media_asset_id")),
            "manual_annotation_present": annotation is not None,
            "region_count": len(regions),
            "relation_count": len(relation_rows),
            "annotation_profile": profile,
            "structured_visual_description": structured_description,
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
