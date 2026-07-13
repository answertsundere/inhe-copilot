from __future__ import annotations

import io

from PIL import Image, ImageDraw

from app.services.product_media_panel_proposal_service import (
    bbox_iou,
    panel_geometry_diagnostics,
    panel_proposal_alignment,
    propose_panel_layout,
)


def _image_with_regions(regions, *, size=(240, 240)):
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    for region in regions:
        draw.rectangle(region, fill="black")
    buffer = io.BytesIO(); image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_whitespace_projection_proposes_vertical_panels():
    report = propose_panel_layout(_image_with_regions([(20, 20, 220, 90), (20, 150, 220, 220)]))

    assert report["status"] == "ready"
    assert report["layout_axis"] == "vertical"
    assert len(report["panels"]) == 2
    assert report["geometric_diagnostics"]["valid"] is True


def test_whitespace_projection_proposes_horizontal_panels():
    report = propose_panel_layout(_image_with_regions([(20, 20, 90, 220), (150, 20, 220, 220)]))

    assert report["status"] == "ready"
    assert report["layout_axis"] == "horizontal"
    assert len(report["panels"]) == 2


def test_whitespace_projection_proposes_regular_grid():
    report = propose_panel_layout(_image_with_regions([(20, 20, 90, 90), (150, 20, 220, 90), (20, 150, 90, 220), (150, 150, 220, 220)]))

    assert report["status"] == "ready"
    assert report["layout_axis"] == "grid"
    assert len(report["panels"]) == 4


def test_single_panel_or_ambiguous_image_has_no_reliable_proposal():
    report = propose_panel_layout(_image_with_regions([(20, 20, 220, 220)]))

    assert report["status"] == "no_reliable_panel_proposal"
    assert report["panels"] == []


def test_geometry_rejects_near_full_overlap_and_alignment_rejects_large_drift():
    overlapping = [
        {"panel_bbox": {"x": 0.0, "y": 0.0, "width": 0.98, "height": 0.98}},
        {"panel_bbox": {"x": 0.01, "y": 0.01, "width": 0.98, "height": 0.98}},
    ]
    geometry = panel_geometry_diagnostics(overlapping, layout_axis="vertical")
    assert geometry["valid"] is False
    assert bbox_iou(overlapping[0]["panel_bbox"], overlapping[1]["panel_bbox"]) > 0.9

    adjacent = [
        {"panel_bbox": {"x": 0.0, "y": 0.0, "width": 1.0, "height": 0.5}},
        {"panel_bbox": {"x": 0.0, "y": 0.5, "width": 1.0, "height": 0.5}},
    ]
    assert panel_geometry_diagnostics(adjacent, layout_axis="vertical")["valid"] is True

    proposal = {"status": "ready", "panels": [
        {"proposal_id": "left", "panel_bbox": {"x": 0.0, "y": 0.0, "width": 0.45, "height": 1.0}},
        {"proposal_id": "right", "panel_bbox": {"x": 0.55, "y": 0.0, "width": 0.45, "height": 1.0}},
    ]}
    drift = panel_proposal_alignment([
        {"panel_bbox": {"x": 0.0, "y": 0.0, "width": 1.0, "height": 0.45}},
        {"panel_bbox": {"x": 0.0, "y": 0.55, "width": 1.0, "height": 0.45}},
    ], proposal)
    assert drift["accepted"] is False
    assert drift["reason"] == "proposal_drift_exceeded"
