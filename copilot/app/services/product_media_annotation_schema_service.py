"""Read-only annotation schema for product-media detector feasibility work.

The schema deliberately describes visual regions and their relationships.  It
does not turn OCR, model predictions, or annotations into product facts.
"""

from __future__ import annotations

import hashlib
from typing import Any


ANNOTATION_SCHEMA_VERSION = "product_media_annotation_v5"
VISUAL_DESCRIPTION_SCHEMA_VERSION = "product_media_visual_description_v1"
LABEL_STUDIO_MODEL_VERSION = "copilot_shadow_candidates_v1"

OBJECT_LABELS = (
    "product_overall",
    "packaging",
    "component",
    "accessory",
    "included_item",
    "display_prop",
    "label_text_region",
    "dimension_label_region",
    "mode_panel",
    "product_panel",
    "compliance_document_region",
    "high_risk_text_region",
)
PROHIBITED_FACT_LABELS = {
    "load_capacity",
    "non_toxic",
    "food_grade",
    "certification",
    "child_safety",
    "anti_tip",
    "wall_mounting",
}
RELATION_TYPES = {
    "panel_contains_object",
    "label_describes_object",
    "dimension_measures_object",
    "object_part_of_product",
    "object_active_in_mode",
}
_LABEL_STUDIO_RELATION_DISPLAY_NAMES_ZH = {
    "object_part_of_product": "属于",
    "dimension_measures_object": "测量对象",
    "panel_contains_object": "可见于面板",
    "object_active_in_mode": "当前模式有效",
    "label_describes_object": "说明对象",
}
LABEL_STUDIO_RELATION_TYPES = set(_LABEL_STUDIO_RELATION_DISPLAY_NAMES_ZH.values())
_DISPLAY_RELATION_TO_CANONICAL = {
    display: relation for relation, display in _LABEL_STUDIO_RELATION_DISPLAY_NAMES_ZH.items()
}
ATTRIBUTE_KEYS = {
    "width",
    "height",
    "depth",
    "length",
    "diameter",
    "thickness",
    "layer_count",
    "compartment_count",
}
IMAGE_SCOPES = {"packaging", "product", "mixed", "document", "unknown"}
DIMENSION_SCOPES = {"packaging", "product_overall", "component", "mode_specific"}
EVIDENCE_STATUSES = {"visible_only", "pending_review", "rejected"}

_CACHE_FIELDS = ("original_path", "cache_path", "local_cache_path", "cached_path", "download_path", "file_path")
_ROLE_PRIORITY = {
    "size_image": 0,
    "pack_guide_image": 1,
    "accessory_image": 2,
    "sku_image": 3,
}
_HIGH_RISK_TERMS = (
    "承重", "无毒", "有毒", "食品级", "认证", "检测", "适用年龄", "年龄", "安全", "防倾倒", "固定墙", "墙面固定", "甲醛",
    "load capacity", "non-toxic", "toxic", "food grade", "certification", "age", "child safety", "anti-tip", "wall mounting", "formaldehyde",
)
_LABEL_DISPLAY_NAMES_ZH = {
    "product_overall": "商品实例（当前面板）",
    "packaging": "包装/纸箱",
    "component": "商品部件",
    "accessory": "配件",
    "included_item": "随附物",
    "display_prop": "展示道具",
    "label_text_region": "图片说明文字",
    "dimension_label_region": "尺寸标注（数值和线）",
    "mode_panel": "模式面板",
    "product_panel": "商品展示面板",
    "compliance_document_region": "认证/检测文件（仅审核）",
    "high_risk_text_region": "高风险文字",
}
_DISPLAY_NAME_TO_LABEL = {display: label for label, display in _LABEL_DISPLAY_NAMES_ZH.items()}
_AUTHORING_PROFILE_LABELS = {
    "packaging_dimension": (
        "packaging",
        "label_text_region",
        "dimension_label_region",
        "high_risk_text_region",
    ),
    "mode_dimension": (
        "mode_panel",
        "product_panel",
        "product_overall",
        "component",
        "label_text_region",
        "dimension_label_region",
        "high_risk_text_region",
    ),
    "product_specification": (
        "product_panel",
        "product_overall",
        "component",
        "label_text_region",
        "dimension_label_region",
        "high_risk_text_region",
    ),
    # Kept only so previously exported manifests remain reviewable. New tasks
    # never fall back to this broad palette.
    "visual_layout": (
        "product_panel",
        "mode_panel",
        "product_overall",
        "packaging",
        "component",
        "accessory",
        "included_item",
        "display_prop",
        "label_text_region",
        "dimension_label_region",
        "high_risk_text_region",
    ),
    "compliance_document": (
        "compliance_document_region",
        "label_text_region",
        "high_risk_text_region",
    ),
}
_PROFILE_DISPLAY_NAMES_ZH = {
    "packaging_dimension": "包装尺寸图",
    "mode_dimension": "模式尺寸图",
    "product_specification": "商品规格参数图",
    "compliance_document": "认证/检测文件",
    "visual_layout": "历史通用视觉布局",
}
_MEDIA_ROLE_DISPLAY_NAMES_ZH = {
    "size_image": "尺寸/规格图",
    "packaging_dimension": "包装尺寸图",
    "packaging_dimension_image": "包装尺寸图",
    "package_dimension_image": "包装尺寸图",
    "mode_dimension": "模式尺寸图",
    "mode_dimension_image": "模式尺寸图",
    "certificate_image": "认证/检测资料图",
    "compliance_document_image": "认证/检测资料图",
    "pack_guide_image": "安装/包装指引图",
    "accessory_image": "配件图",
    "sku_image": "商品展示图",
}
_IMAGE_SCOPE_DISPLAY_NAMES_ZH = {
    "packaging": "包装/纸箱",
    "product": "商品",
    "mixed": "商品与其他对象混合",
    "document": "文件/证书",
    "unknown": "无法确认",
}
_DIMENSION_ATTRIBUTE_DISPLAY_NAMES_ZH = {
    "width": "宽度",
    "height": "高度",
    "depth": "深度",
    "length": "长度",
    "diameter": "直径",
    "thickness": "厚度",
    "layer_count": "层数",
    "compartment_count": "格数",
    "unknown": "图中未明确",
}
_DIMENSION_SCOPE_DISPLAY_NAMES_ZH = {
    "product_overall": "商品整体",
    "component": "商品部件",
    "packaging": "包装/纸箱",
    "mode_specific": "当前模式专属",
}
_EVIDENCE_STATUS_DISPLAY_NAMES_ZH = {
    "visible_only": "仅图片可见",
    "pending_review": "待进一步审核",
    "rejected": "拒绝采用",
}
_OBJECT_REPRESENTATION_DISPLAY_NAMES_ZH = {
    "actual": "实际可见对象",
    "printed": "印刷或屏幕中的图像",
    "unknown": "无法确认",
}
_MODEL_CANDIDATE_FIELDS = (
    "provider_name",
    "model_name",
    "object_type",
    "object_label",
    "subject_scope",
    "panel_id",
    "bbox",
    "confidence",
    "rejection_reason",
    "observation_eligible",
    "used_for_generation",
    "can_change_can_send",
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _raw(asset: Any) -> dict[str, Any]:
    if isinstance(asset, dict):
        value = asset.get("source_raw")
    elif hasattr(asset, "get_source_raw"):
        value = asset.get_source_raw()
    else:
        value = getattr(asset, "source_raw", None)
    return value if isinstance(value, dict) else {}


def _value(asset: Any, key: str) -> Any:
    return asset.get(key) if isinstance(asset, dict) else getattr(asset, key, None)


def _scene_tags(asset: Any) -> list[str]:
    if isinstance(asset, dict):
        value = asset.get("scene_tags")
    elif hasattr(asset, "get_scene_tags"):
        value = asset.get_scene_tags()
    else:
        value = getattr(asset, "scene_tags", None)
    return [str(item).strip().lower() for item in value] if isinstance(value, list) else []


def image_reference(asset: Any) -> tuple[str, str]:
    """Return the existing source reference without downloading or rewriting it."""
    url = _text(_value(asset, "asset_url"))
    if url:
        return url, "asset_url"
    raw = _raw(asset)
    for field in _CACHE_FIELDS:
        value = _text(raw.get(field))
        if value:
            return value, field
    return "", "missing"


def product_identity(asset: Any) -> dict[str, str]:
    return {
        "product_id": _text(_value(asset, "product_id")),
        "i_id": _text(_value(asset, "i_id")),
        "sku_code": _text(_value(asset, "sku_code")),
    }


def label_studio_display_label(label: str) -> str:
    """Return the Chinese authoring label while retaining a canonical schema key."""
    return _LABEL_DISPLAY_NAMES_ZH.get(_text(label), _text(label))


def canonical_annotation_label(label: Any) -> str:
    value = _text(label)
    return _DISPLAY_NAME_TO_LABEL.get(value, value)


def canonical_annotation_relation(relation: Any) -> str:
    """Return the canonical relation key from the Chinese authoring value."""
    value = _text(relation)
    return _DISPLAY_RELATION_TO_CANONICAL.get(value, value)


def _canonical_display_value(value: Any, display_names: dict[str, str]) -> str:
    normalized = _text(value)
    for key, display in display_names.items():
        if normalized in {key, display}:
            return key
    return normalized


def canonical_image_scope(value: Any) -> str:
    return _canonical_display_value(value, _IMAGE_SCOPE_DISPLAY_NAMES_ZH)


def canonical_dimension_attribute(value: Any) -> str:
    return _canonical_display_value(value, _DIMENSION_ATTRIBUTE_DISPLAY_NAMES_ZH)


def canonical_dimension_scope(value: Any) -> str:
    return _canonical_display_value(value, _DIMENSION_SCOPE_DISPLAY_NAMES_ZH)


def canonical_evidence_status(value: Any) -> str:
    return _canonical_display_value(value, _EVIDENCE_STATUS_DISPLAY_NAMES_ZH)


def canonical_object_representation(value: Any) -> str:
    return _canonical_display_value(value, _OBJECT_REPRESENTATION_DISPLAY_NAMES_ZH)


def _task_uid(asset_id: str, image_sha256: str, reference: str) -> str:
    seed = "|".join((asset_id, image_sha256 or reference))
    return "pma_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def annotation_profile(asset: Any) -> str:
    """Choose a reviewer palette from durable task/media metadata only."""
    raw = _raw(asset)
    explicit_values = (
        _value(asset, "annotation_task_type"),
        _value(asset, "task_type"),
        raw.get("annotation_task_type"),
        raw.get("task_type"),
        raw.get("annotation_profile"),
    )
    for value in explicit_values:
        profile = _text(value).lower()
        if profile in _AUTHORING_PROFILE_LABELS and profile != "visual_layout":
            return profile

    role = _text(
        _value(asset, "media_role")
        or raw.get("media_role")
        or raw.get("media_purpose")
        or _value(asset, "asset_type")
    ).lower()
    tags = set(_scene_tags(asset))
    if role in {"compliance_document", "certificate_image", "compliance_document_image"}:
        return "compliance_document"
    if role in {"packaging_dimension", "packaging_dimension_image", "package_dimension_image"} or (
        role == "size_image" and tags.intersection({"packaging", "packaging_dimension", "package_dimension"})
    ):
        return "packaging_dimension"
    if role in {"mode_dimension", "mode_dimension_image"} or (
        role == "size_image" and tags.intersection({"mode", "mode_dimension", "multi_mode"})
    ):
        return "mode_dimension"
    return "product_specification"


def authoring_labels(profile: str) -> list[dict[str, str]]:
    """Return Label Studio dynamic labels for one stable authoring profile."""
    labels = _AUTHORING_PROFILE_LABELS.get(_text(profile), ())
    return [{"value": label_studio_display_label(label)} for label in labels]


def task_authoring_labels(task: dict[str, Any]) -> set[str]:
    """Return canonical labels permitted by an exported task's dynamic palette."""
    data = task.get("data") if isinstance(task, dict) else None
    values = data.get("authoring_labels") if isinstance(data, dict) else None
    if not isinstance(values, list):
        return set()
    return {
        canonical_annotation_label(item.get("value") if isinstance(item, dict) else item)
        for item in values
        if canonical_annotation_label(item.get("value") if isinstance(item, dict) else item) in OBJECT_LABELS
    }


def label_studio_config_xml() -> str:
    """Return an importable Chinese Label Studio config for the shared schema."""
    relations = "\n".join(f'      <Relation value="{relation}" />' for relation in sorted(LABEL_STUDIO_RELATION_TYPES))
    dimension_label = label_studio_display_label("dimension_label_region")
    product_label = label_studio_display_label("product_overall")
    product_panel_label = label_studio_display_label("product_panel")
    mode_panel_label = label_studio_display_label("mode_panel")
    label_text = label_studio_display_label("label_text_region")
    high_risk_text = label_studio_display_label("high_risk_text_region")
    image_scope_choices = "\n".join(
        f'      <Choice value="{display}" />' for display in _IMAGE_SCOPE_DISPLAY_NAMES_ZH.values()
    )
    dimension_attribute_choices = "\n".join(
        f'      <Choice value="{display}" />' for display in _DIMENSION_ATTRIBUTE_DISPLAY_NAMES_ZH.values()
    )
    dimension_scope_choices = "\n".join(
        f'      <Choice value="{display}" />' for display in _DIMENSION_SCOPE_DISPLAY_NAMES_ZH.values()
    )
    evidence_status_choices = "\n".join(
        f'      <Choice value="{display}" />' for display in _EVIDENCE_STATUS_DISPLAY_NAMES_ZH.values()
    )
    object_representation_choices = "\n".join(
        f'      <Choice value="{display}" />' for display in _OBJECT_REPRESENTATION_DISPLAY_NAMES_ZH.values()
    )
    object_description_controls = "\n".join(
        f'  <TextArea name="{label}_visual_description" toName="image" perRegion="true" visibleWhen="region-selected" whenTagName="region_label" whenLabelValue="{label_studio_display_label(label)}" placeholder="只描述该框内实际可见的对象" />'
        for label in ("product_overall", "packaging", "component", "accessory", "included_item", "display_prop")
    )
    return f"""<View>
  <Header value="商品媒体人工标注（仅审核用，不生成商品事实）" />
  <Header value="$annotation_profile_instruction" />
  <Text name="annotation_context" value="$annotation_context" valueType="text" />
  <Image name="image" value="$image" />
  <RectangleLabels name="region_label" toName="image" value="$authoring_labels" />
  <Choices name="image_scope" toName="image" choice="single-radio" required="true">
{image_scope_choices}
  </Choices>
  <TextArea name="reviewed_visual_summary" toName="image" required="true" rows="2" placeholder="只写图片中看见了什么，不写安全、性能、适用或售后结论" />
  <TextArea name="variant_or_color_reference" toName="image" rows="1" placeholder="仅在图片明确展示规格或颜色时填写" />
  <TextArea name="label_visible_text" toName="image" perRegion="true" visibleWhen="region-selected" whenTagName="region_label" whenLabelValue="{label_text}" placeholder="抄录图片中可见文字" />
  <TextArea name="high_risk_visible_text" toName="image" perRegion="true" visibleWhen="region-selected" whenTagName="region_label" whenLabelValue="{high_risk_text}" placeholder="抄录图片中的高风险文字；不会成为商品事实" />
  <TextArea name="product_panel_summary" toName="image" perRegion="true" visibleWhen="region-selected" whenTagName="region_label" whenLabelValue="{product_panel_label}" placeholder="简述该面板展示的可见内容" />
  <TextArea name="mode_panel_summary" toName="image" perRegion="true" visibleWhen="region-selected" whenTagName="region_label" whenLabelValue="{mode_panel_label}" placeholder="简述该模式面板展示的可见内容" />
  <TextArea name="mode_or_state" toName="image" perRegion="true" visibleWhen="region-selected" whenTagName="region_label" whenLabelValue="{mode_panel_label}" placeholder="填写图片明确写出的模式或状态" />
{object_description_controls}
  <Choices name="object_representation" toName="image" perRegion="true" choice="single-radio" visibleWhen="region-selected" whenTagName="region_label" whenLabelValue="{product_label}">
{object_representation_choices}
  </Choices>
  <Choices name="dimension_attribute" toName="image" perRegion="true" choice="single-radio" visibleWhen="region-selected" whenTagName="region_label" whenLabelValue="{dimension_label}">
{dimension_attribute_choices}
  </Choices>
  <Choices name="dimension_scope" toName="image" perRegion="true" choice="single-radio" visibleWhen="region-selected" whenTagName="region_label" whenLabelValue="{dimension_label}">
{dimension_scope_choices}
  </Choices>
  <TextArea name="dimension_visible_value" toName="image" perRegion="true" visibleWhen="region-selected" whenTagName="region_label" whenLabelValue="{dimension_label}" placeholder="仅填写图中可见的数值和单位，例如 38cm" />
  <TextArea name="dimension_unit" toName="image" perRegion="true" visibleWhen="region-selected" whenTagName="region_label" whenLabelValue="{dimension_label}" placeholder="填写图片明确显示的单位，例如 cm" />
  <Choices name="dimension_evidence_status" toName="image" perRegion="true" choice="single-radio" visibleWhen="region-selected" whenTagName="region_label" whenLabelValue="{dimension_label}">
{evidence_status_choices}
  </Choices>
  <Relations>
{relations}
  </Relations>
</View>"""


def suggested_task_type(asset: Any) -> str:
    """Use durable media metadata only; filenames and product text are excluded."""
    return _PROFILE_DISPLAY_NAMES_ZH[annotation_profile(asset)]


def media_role_display_name(asset: Any) -> str:
    role = _text(_value(asset, "asset_type")).lower()
    return _MEDIA_ROLE_DISPLAY_NAMES_ZH.get(role, "其他商品图片")


def annotation_priority(asset: Any) -> tuple[int, str]:
    role = _text(_value(asset, "asset_type")).lower()
    tags = set(_scene_tags(asset))
    if role in _ROLE_PRIORITY:
        return _ROLE_PRIORITY[role], role
    if {"packaging", "mode", "multi_panel"}.intersection(tags):
        return 4, "scene_tagged_visual_layout"
    return 9, "other_media_role"


def is_annotation_image_asset(asset: Any) -> bool:
    """Accept explicit image roles only; videos are not Label Studio image tasks."""
    return _text(_value(asset, "asset_type")).lower().endswith("_image")


def annotation_instructions(profile: str = "visual_layout") -> list[str]:
    if profile == "packaging_dimension":
        return [
            "只标包装/纸箱、图片说明文字、尺寸标注和高风险文字；箱体上的商品印刷图不是商品实例。",
            "每条包装尺寸都必须用“测量对象”连接到包装/纸箱，作用范围只能选择包装/纸箱。",
            "图片中的商品宣传图、性能词和适用结论不得标为实际商品对象或商品事实。",
        ]
    if profile == "mode_dimension":
        return [
            "先框模式面板或商品展示面板，再框当前面板内实际可见的商品实例和部件。",
            "模式专属尺寸必须连接到当前面板内的对象，并标为当前模式专属或商品部件，不能升级为商品整体尺寸。",
            "本任务不标包装、随附物或展示道具；无法确认对象归属时留待返工。",
        ]
    if profile == "product_specification":
        return [
            "只标商品展示面板、当前面板中的商品实例、商品部件、图片说明文字、尺寸标注和高风险文字。",
            "材质、颜色、层数等图片文字先作为图片说明文字；人工标注本身不会把它们变成正式商品事实。",
            "适用年龄、儿童安全、无毒、食品级、承重、认证、防倾倒和墙面固定只能标为高风险文字。",
        ]
    if profile == "compliance_document":
        return [
            "先框认证/检测文件本体；它仅表示图片中出现文件，不表示认证或检测结论已经成立。",
            "认证、检测、无毒、食品级、儿童安全、承重等主张均框为高风险文字区域，不能标为商品事实。",
            "只框图片中可见的文件、文字和标志；不要标注包装、商品尺寸或商品部件。",
        ]
    return [
        "这是历史通用标签盘，仅用于校验已有标注；新任务不得使用。",
        "先框模式面板或商品展示面板；每个面板中的完整商品都标为一个商品实例，无法确认时不标为商品实例。",
        "每条尺寸标注都框住数值、单位和标注线，并用“测量对象”从尺寸标注连到商品实例、商品部件或包装/纸箱。",
        "多面板图片中，被测对象再用“可见于面板”连到所属面板；模式专属的对象再用“当前模式有效”连到模式面板。",
        "尺寸区域填写图中可见数值和单位，并选择属性与作用范围；包装尺寸、部件尺寸和模式尺寸不得标为商品实例整体尺寸。",
        "承重、无毒、食品级、认证、儿童安全、防倾倒和墙面固定仅可标为高风险文字区域，不标为可回答事实。",
    ]


def _variant_or_color_reference(asset: Any) -> str:
    raw = _raw(asset)
    for value in (
        _value(asset, "variant_or_color_reference"),
        raw.get("variant_or_color_reference"),
        raw.get("variant_name"),
        raw.get("color_name"),
        raw.get("color"),
    ):
        if _text(value):
            return _text(value)
    return ""


def _source_of_product_context(asset: Any) -> str:
    return "media_asset_product_identity" if any(product_identity(asset).values()) else "unscoped_media_asset"


def visual_description_schema() -> dict[str, Any]:
    """Return the controlled external-review description contract."""
    return {
        "schema_version": VISUAL_DESCRIPTION_SCHEMA_VERSION,
        "product_context_fields": [
            "product_identity",
            "product_title_reference",
            "variant_or_color_reference",
            "source_of_product_context",
        ],
        "image_fields": [
            "media_role",
            "reviewed_visual_summary",
            "visible_claims",
            "high_risk_text_regions",
            "image_scope",
        ],
        "panel_fields": ["panel_id", "panel_type", "mode_or_state", "panel_summary"],
        "object_fields": [
            "object_id",
            "object_scope",
            "parent_panel_id",
            "parent_object_id",
            "visual_description",
            "is_printed_representation",
            "is_actual_product_object",
        ],
        "dimension_fields": [
            "dimension_label_id",
            "raw_value",
            "unit",
            "attribute_key",
            "measured_object_id",
            "scope",
            "evidence_status",
        ],
        "image_scopes": sorted(IMAGE_SCOPES),
        "dimension_scopes": sorted(DIMENSION_SCOPES),
        "evidence_statuses": sorted(EVIDENCE_STATUSES),
        "shadow_only": True,
        "used_for_generation": False,
        "can_change_can_send": False,
    }


def _normalized_bbox(value: Any) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    try:
        bbox = {key: float(value[key]) for key in ("x", "y", "width", "height")}
    except (KeyError, TypeError, ValueError):
        return None
    if bbox["width"] <= 0 or bbox["height"] <= 0:
        return None
    if any(number < 0 or number > 1 for number in bbox.values()):
        return None
    if bbox["x"] + bbox["width"] > 1 or bbox["y"] + bbox["height"] > 1:
        return None
    return bbox


def _is_high_risk_text(text: str, classification: dict[str, Any] | None = None) -> bool:
    if isinstance(classification, dict) and classification.get("high_risk_text"):
        return True
    normalized = _text(text).lower()
    return any(term in normalized for term in _HIGH_RISK_TERMS)


def _ocr_prediction(asset_id: str, item: dict[str, Any], index: int) -> dict[str, Any] | None:
    bbox = _normalized_bbox(item.get("bbox"))
    text = _text(item.get("text"))
    if not bbox or not text:
        return None
    classification = item.get("classification") if isinstance(item.get("classification"), dict) else {}
    label = "high_risk_text_region" if _is_high_risk_text(text, classification) else (
        "dimension_label_region" if classification.get("dimension_text") else "label_text_region"
    )
    original_size = item.get("source_image_size") if isinstance(item.get("source_image_size"), dict) else {}
    width = int(original_size.get("width") or 1)
    height = int(original_size.get("height") or 1)
    result_id = hashlib.sha256(f"{asset_id}|ocr|{index}|{text}|{bbox}".encode("utf-8")).hexdigest()[:20]
    return {
        "id": f"ocr_{result_id}",
        "type": "rectanglelabels",
        "from_name": "region_label",
        "to_name": "image",
        "original_width": width,
        "original_height": height,
        "image_rotation": 0,
        "score": float(item.get("confidence") or 0.0),
        "value": {
            "x": round(bbox["x"] * 100, 4),
            "y": round(bbox["y"] * 100, 4),
            "width": round(bbox["width"] * 100, 4),
            "height": round(bbox["height"] * 100, 4),
            "rotation": 0,
            "rectanglelabels": [label_studio_display_label(label)],
        },
        "meta": {"text": text, "source": _text(item.get("source") or item.get("provider_name") or "ocr")},
    }


def _safe_model_candidates(candidates: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Keep review-relevant geometry/provenance, never provider raw payloads."""
    safe: list[dict[str, Any]] = []
    for candidate in candidates or []:
        if not isinstance(candidate, dict):
            continue
        item = {field: candidate[field] for field in _MODEL_CANDIDATE_FIELDS if field in candidate}
        bbox = _normalized_bbox(item.get("bbox"))
        if "bbox" in item:
            item["bbox"] = bbox
        safe.append(item)
    return safe


def build_label_studio_task(
    asset: Any,
    *,
    ocr_items: list[dict[str, Any]] | None = None,
    model_candidates: list[dict[str, Any]] | None = None,
    image_details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an importable Label Studio task with shadow suggestions only."""
    asset_id = _text(_value(asset, "id") or _value(asset, "asset_id"))
    reference, reference_kind = image_reference(asset)
    details = image_details if isinstance(image_details, dict) else {}
    image_sha256 = _text(details.get("observed_media_sha256"))
    source_size = details.get("source_image_size") if isinstance(details.get("source_image_size"), dict) else {}
    task_uid = _task_uid(asset_id, image_sha256, reference)
    priority, priority_reason = annotation_priority(asset)
    profile = annotation_profile(asset)
    allowed_labels = set(_AUTHORING_PROFILE_LABELS[profile])
    predictions = [
        prediction
        for index, item in enumerate(ocr_items or [])
        if isinstance(item, dict)
        for prediction in [_ocr_prediction(asset_id, item, index)]
        if prediction is not None
        and canonical_annotation_label(prediction["value"]["rectanglelabels"][0]) in allowed_labels
    ]
    title = _text(_value(asset, "product_name"))
    variant_reference = _variant_or_color_reference(asset)
    product_context_source = _source_of_product_context(asset)
    instructions = annotation_instructions(profile)
    context = "\n".join(filter(None, (
        f"任务编号：{task_uid}",
        f"商品标题（仅辅助识别）：{title}" if title else "",
        f"规格/颜色参考（仅辅助识别）：{variant_reference}" if variant_reference else "",
        f"媒体角色：{media_role_display_name(asset)}",
        f"标注范围：{instructions[0]}",
        "请只标注图片中可见区域；不要依据商品标题推断对象或尺寸。",
    )))
    return {
        "data": {
            "image": reference,
            "annotation_context": context,
            "annotation_profile": profile,
            "annotation_profile_name_zh": _PROFILE_DISPLAY_NAMES_ZH[profile],
            "annotation_profile_instruction": "；".join(instructions),
            "authoring_labels": authoring_labels(profile),
        },
        "meta": {
            "schema_version": ANNOTATION_SCHEMA_VERSION,
            "task_uid": task_uid,
            "media_asset_id": asset_id,
            "image_reference_kind": reference_kind,
            "original_image_source": reference,
            "product_identity": product_identity(asset),
            "product_title_for_human_aid": title,
            "product_title_reference": title,
            "variant_or_color_reference": variant_reference,
            "source_of_product_context": product_context_source,
            "source_type": _text(_value(asset, "source")),
            "source_image_sha256": image_sha256,
            "source_image_size": source_size,
            "source_image_source_kind": _text(details.get("source_kind")),
            "media_role": _text(_value(asset, "asset_type")),
            "suggested_task_type": suggested_task_type(asset),
            "priority": priority,
            "priority_reason": priority_reason,
            "annotation_profile": profile,
            "annotation_instructions_zh": instructions,
            "visual_description_schema": visual_description_schema(),
            "prohibited_fact_labels": sorted(PROHIBITED_FACT_LABELS),
            "label_display_names_zh": _LABEL_DISPLAY_NAMES_ZH,
            "prediction_source_version": LABEL_STUDIO_MODEL_VERSION,
            "current_model_candidates": _safe_model_candidates(model_candidates),
            "shadow_only": True,
            "used_for_generation": False,
            "can_change_can_send": False,
        },
        "predictions": [{"model_version": LABEL_STUDIO_MODEL_VERSION, "result": predictions}] if predictions else [],
    }


def validate_label_studio_task(task: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(task, dict) or not isinstance(task.get("data"), dict) or not _text(task["data"].get("image")):
        errors.append("image_reference_required")
    meta = task.get("meta") if isinstance(task, dict) else None
    if not isinstance(meta, dict) or meta.get("schema_version") != ANNOTATION_SCHEMA_VERSION:
        errors.append("annotation_schema_version_invalid")
    elif set(meta.get("prohibited_fact_labels") or ()) != PROHIBITED_FACT_LABELS:
        errors.append("prohibited_fact_labels_invalid")
    allowed_labels = task_authoring_labels(task)
    if not allowed_labels:
        errors.append("task_authoring_labels_missing")
    for prediction in task.get("predictions") or []:
        for result in prediction.get("result") or []:
            labels = ((result.get("value") or {}).get("rectanglelabels") or [])
            if len(labels) != 1 or canonical_annotation_label(labels[0]) not in allowed_labels:
                errors.append("annotation_label_invalid")
    return errors


def annotation_schema() -> dict[str, Any]:
    return {
        "schema_version": ANNOTATION_SCHEMA_VERSION,
        "object_labels": list(OBJECT_LABELS),
        "relation_types": sorted(RELATION_TYPES),
        "label_studio_relation_types": sorted(LABEL_STUDIO_RELATION_TYPES),
        "label_display_names_zh": _LABEL_DISPLAY_NAMES_ZH,
        "authoring_profiles": {
            profile: list(labels) for profile, labels in _AUTHORING_PROFILE_LABELS.items()
        },
        "profile_display_names_zh": _PROFILE_DISPLAY_NAMES_ZH,
        "visual_description_schema": visual_description_schema(),
        "attribute_keys": sorted(ATTRIBUTE_KEYS),
        "prohibited_fact_labels": sorted(PROHIBITED_FACT_LABELS),
        "shadow_only": True,
        "used_for_generation": False,
        "can_change_can_send": False,
    }
