"""Deterministic, shadow-only panel proposals for product-media grounding."""

from __future__ import annotations

import io
from itertools import combinations
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError


PANEL_PROPOSAL_VERSION = "product_media_panel_proposal_v1"
MIN_PANEL_AREA = 0.08
MAX_PANEL_IOU = 0.20
MIN_CENTER_DISTANCE = 0.18
# Adjacent panels can legitimately partition the entire canvas. IoU and center
# separation, rather than a gap requirement, reject duplicated full-image boxes.
MAX_PANEL_COVERAGE = 1.02
MIN_SEPARATOR_RATIO = 0.035
MIN_SEPARATOR_PIXELS = 8
MIN_WHITESPACE_FRACTION = 0.92
MIN_CONTENT_DARK_FRACTION = 0.01
MIN_PROPOSAL_ALIGNMENT_IOU = 0.60


def _bbox(x: float, y: float, width: float, height: float) -> dict[str, float | str]:
    return {"x": x, "y": y, "width": width, "height": height, "coordinate_space": "normalized"}


def _area(bbox: dict[str, Any]) -> float:
    return float(bbox["width"]) * float(bbox["height"])


def _center(bbox: dict[str, Any]) -> tuple[float, float]:
    return float(bbox["x"]) + float(bbox["width"]) / 2, float(bbox["y"]) + float(bbox["height"]) / 2


def bbox_iou(left: dict[str, Any], right: dict[str, Any]) -> float:
    x1, y1 = max(float(left["x"]), float(right["x"])), max(float(left["y"]), float(right["y"]))
    x2 = min(float(left["x"]) + float(left["width"]), float(right["x"]) + float(right["width"]))
    y2 = min(float(left["y"]) + float(left["height"]), float(right["y"]) + float(right["height"]))
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = _area(left) + _area(right) - intersection
    return intersection / union if union else 0.0


def bbox_containment_ratio(inner: dict[str, Any], outer: dict[str, Any]) -> float:
    x1, y1 = max(float(inner["x"]), float(outer["x"])), max(float(inner["y"]), float(outer["y"]))
    x2 = min(float(inner["x"]) + float(inner["width"]), float(outer["x"]) + float(outer["width"]))
    y2 = min(float(inner["y"]) + float(inner["height"]), float(outer["y"]) + float(outer["height"]))
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    return intersection / _area(inner) if _area(inner) else 0.0


def union_bbox(boxes: list[dict[str, Any]]) -> dict[str, float | str]:
    x1 = min(float(item["x"]) for item in boxes)
    y1 = min(float(item["y"]) for item in boxes)
    x2 = max(float(item["x"]) + float(item["width"]) for item in boxes)
    y2 = max(float(item["y"]) + float(item["height"]) for item in boxes)
    return _bbox(x1, y1, x2 - x1, y2 - y1)


def panel_geometry_diagnostics(panels: list[dict[str, Any]], *, layout_axis: str) -> dict[str, Any]:
    boxes = [item["panel_bbox"] for item in panels]
    pairwise_iou = [bbox_iou(left, right) for left, right in combinations(boxes, 2)]
    centers = [_center(item) for item in boxes]
    center_distances = [((left[0] - right[0]) ** 2 + (left[1] - right[1]) ** 2) ** 0.5 for left, right in combinations(centers, 2)]
    coverage = sum(_area(item) for item in boxes)
    ordered = True
    if layout_axis == "vertical" and len(centers) > 1:
        ordered = [point[1] for point in centers] == sorted(point[1] for point in centers)
    elif layout_axis == "horizontal" and len(centers) > 1:
        ordered = [point[0] for point in centers] == sorted(point[0] for point in centers)
    valid = bool(boxes) and all(MIN_PANEL_AREA <= _area(item) < 0.99 for item in boxes)
    valid = valid and all(value <= MAX_PANEL_IOU for value in pairwise_iou)
    valid = valid and (not center_distances or min(center_distances) >= MIN_CENTER_DISTANCE)
    valid = valid and coverage <= MAX_PANEL_COVERAGE and ordered
    return {
        "valid": valid,
        "panel_count": len(boxes),
        "layout_axis": layout_axis,
        "total_coverage": coverage,
        "pairwise_iou": pairwise_iou,
        "min_center_distance": min(center_distances) if center_distances else None,
        "axis_ordered": ordered,
    }


def _separator_bands(values: list[bool], *, minimum: int) -> list[tuple[int, int]]:
    bands: list[tuple[int, int]] = []
    start: int | None = None
    for index, value in enumerate(values + [False]):
        if value and start is None:
            start = index
        elif not value and start is not None:
            if index - start >= minimum:
                bands.append((start, index))
            start = None
    return bands


def _content_fraction(pixels: list[int], width: int, *, x0: int, y0: int, x1: int, y1: int) -> float:
    total = max((x1 - x0) * (y1 - y0), 1)
    dark = sum(1 for y in range(y0, y1) for x in range(x0, x1) if pixels[y * width + x] < 235)
    return dark / total


def _proposals_for_band(*, band: tuple[int, int], width: int, height: int, axis: str, pixels: list[int]) -> list[dict[str, Any]]:
    start, end = band
    if axis == "vertical":
        regions = [(0, 0, width, start), (0, end, width, height)]
    else:
        regions = [(0, 0, start, height), (end, 0, width, height)]
    if any(_content_fraction(pixels, width, x0=x0, y0=y0, x1=x1, y1=y1) < MIN_CONTENT_DARK_FRACTION for x0, y0, x1, y1 in regions):
        return []
    return [
        {"proposal_id": f"proposal_{index + 1}", "panel_bbox": _bbox(x0 / width, y0 / height, (x1 - x0) / width, (y1 - y0) / height)}
        for index, (x0, y0, x1, y1) in enumerate(regions)
    ]


def propose_panel_layout(image_bytes: bytes) -> dict[str, Any]:
    """Return only reliable whitespace-projection panel candidates.

    This is deliberately conservative. It proposes a two-panel vertical or
    horizontal layout only when a long whitespace separator leaves substantive
    content on both sides. Ambiguous grids and collages remain for strict VLM
    verification and fail closed if that verification cannot ground panels.
    """
    try:
        with Image.open(io.BytesIO(image_bytes)) as source:
            image = ImageOps.exif_transpose(source).convert("L")
    except (UnidentifiedImageError, OSError, ValueError):
        return {"status": "no_reliable_panel_proposal", "reason": "image_decode_failed", "panels": [], "layout_axis": "unknown"}
    width, height = image.size
    if width < 32 or height < 32:
        return {"status": "no_reliable_panel_proposal", "reason": "image_too_small", "panels": [], "layout_axis": "unknown"}
    pixels = list(image.get_flattened_data())
    row_whitespace = [sum(1 for x in range(width) if pixels[y * width + x] >= 245) / width >= MIN_WHITESPACE_FRACTION for y in range(height)]
    column_whitespace = [sum(1 for y in range(height) if pixels[y * width + x] >= 245) / height >= MIN_WHITESPACE_FRACTION for x in range(width)]
    horizontal_bands = [item for item in _separator_bands(row_whitespace, minimum=max(MIN_SEPARATOR_PIXELS, round(height * MIN_SEPARATOR_RATIO))) if item[0] > 0 and item[1] < height]
    vertical_bands = [item for item in _separator_bands(column_whitespace, minimum=max(MIN_SEPARATOR_PIXELS, round(width * MIN_SEPARATOR_RATIO))) if item[0] > 0 and item[1] < width]
    candidates: list[tuple[str, tuple[int, int], list[dict[str, Any]], float]] = []
    for band in horizontal_bands:
        panels = _proposals_for_band(band=band, width=width, height=height, axis="vertical", pixels=pixels)
        if panels:
            candidates.append(("vertical", band, panels, (band[1] - band[0]) / height))
    for band in vertical_bands:
        panels = _proposals_for_band(band=band, width=width, height=height, axis="horizontal", pixels=pixels)
        if panels:
            candidates.append(("horizontal", band, panels, (band[1] - band[0]) / width))
    if horizontal_bands and vertical_bands:
        horizontal_band, vertical_band = horizontal_bands[0], vertical_bands[0]
        hy0, hy1 = horizontal_band; vx0, vx1 = vertical_band
        regions = [(0, 0, vx0, hy0), (vx1, 0, width, hy0), (0, hy1, vx0, height), (vx1, hy1, width, height)]
        if all(_content_fraction(pixels, width, x0=x0, y0=y0, x1=x1, y1=y1) >= MIN_CONTENT_DARK_FRACTION for x0, y0, x1, y1 in regions):
            panels = [
                {"proposal_id": f"proposal_{index + 1}", "panel_bbox": _bbox(x0 / width, y0 / height, (x1 - x0) / width, (y1 - y0) / height)}
                for index, (x0, y0, x1, y1) in enumerate(regions)
            ]
            candidates.append(("grid", (horizontal_band, vertical_band), panels, min((hy1 - hy0) / height, (vx1 - vx0) / width)))
    if not candidates:
        return {
            "status": "no_reliable_panel_proposal", "reason": "no_reliable_whitespace_separator", "panels": [], "layout_axis": "unknown",
            "geometric_diagnostics": {"width": width, "height": height, "horizontal_band_count": len(horizontal_bands), "vertical_band_count": len(vertical_bands)},
        }
    axis, band, panels, separator_ratio = sorted(candidates, key=lambda item: (-item[3], item[0]))[0]
    geometry = panel_geometry_diagnostics(panels, layout_axis=axis)
    if not geometry["valid"]:
        return {"status": "no_reliable_panel_proposal", "reason": "proposal_geometry_invalid", "panels": [], "layout_axis": "unknown", "geometric_diagnostics": geometry}
    confidence = min(0.95, 0.55 + separator_ratio * 4)
    for panel in panels:
        panel.update({"layout_axis": axis, "proposal_source": "whitespace_projection", "confidence": confidence, "geometric_diagnostics": geometry})
    return {
        "status": "ready", "proposal_version": PANEL_PROPOSAL_VERSION, "panels": panels, "layout_axis": axis,
        "proposal_source": "whitespace_projection", "confidence": confidence,
        "geometric_diagnostics": {**geometry, "width": width, "height": height, "separator_band": _separator_diagnostic(axis, band)},
    }


def _separator_diagnostic(axis: str, band: Any) -> dict[str, Any]:
    if axis == "grid":
        horizontal, vertical = band
        return {"horizontal": {"start": horizontal[0], "end": horizontal[1]}, "vertical": {"start": vertical[0], "end": vertical[1]}}
    return {"start": band[0], "end": band[1]}


def panel_proposal_alignment(panels: list[dict[str, Any]], proposal: dict[str, Any]) -> dict[str, Any]:
    """Match verified panel boxes to reliable proposals without sample-specific rules."""
    if proposal.get("status") != "ready":
        return {"accepted": True, "reason": "no_reliable_panel_proposal", "matches": []}
    proposal_panels = list(proposal.get("panels") or [])
    if not panels or not proposal_panels:
        return {"accepted": False, "reason": "proposal_drift_exceeded", "matches": []}
    combinations_by_box = []
    for panel in panels:
        best: tuple[float, list[str]] | None = None
        for count in range(1, len(proposal_panels) + 1):
            for subset in combinations(proposal_panels, count):
                score = bbox_iou(panel["panel_bbox"], union_bbox([item["panel_bbox"] for item in subset]))
                refs = [str(item["proposal_id"]) for item in subset]
                candidate = (score, refs)
                if best is None or candidate[0] > best[0] or (candidate[0] == best[0] and candidate[1] < best[1]):
                    best = candidate
        combinations_by_box.append(best or (0.0, []))
    used_refs = {item for _, refs in combinations_by_box for item in refs}
    accepted = all(score >= MIN_PROPOSAL_ALIGNMENT_IOU for score, _ in combinations_by_box) and used_refs == {str(item["proposal_id"]) for item in proposal_panels}
    return {
        "accepted": accepted,
        "reason": "" if accepted else "proposal_drift_exceeded",
        "matches": [{"proposal_ids": refs, "iou": score} for score, refs in combinations_by_box],
    }
