from __future__ import annotations

import io

import pytest
from PIL import Image

from app.services.product_media_preprocessing_service import ImagePreprocessingError, preprocess_product_media_image


def _image_bytes(size=(2400, 1600), mode="RGB"):
    image = Image.new(mode, size, (255, 0, 0, 128) if mode == "RGBA" else (255, 0, 0))
    out = io.BytesIO(); image.save(out, format="PNG"); return out.getvalue()


def test_preprocessing_is_deterministic_preserves_aspect_and_records_hashes():
    data = _image_bytes()
    first = preprocess_product_media_image(data, profile={"max_pixels": 500_000})
    second = preprocess_product_media_image(data, profile={"max_pixels": 500_000})
    assert first.data == second.data
    assert first.provenance["original_media_sha256"] != first.provenance["derived_input_sha256"]
    assert first.provenance["derived_width"] * first.provenance["derived_height"] <= 500_000
    assert abs(first.provenance["scale_x"] - first.provenance["scale_y"]) < 0.001


def test_preprocessing_keeps_alpha_as_png_and_rejects_invalid_image():
    result = preprocess_product_media_image(_image_bytes(mode="RGBA"))
    assert result.extension == ".png"
    with pytest.raises(ImagePreprocessingError, match="image_decode_failed"):
        preprocess_product_media_image(b"not-image")
