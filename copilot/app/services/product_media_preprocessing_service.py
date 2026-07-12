"""Deterministic, offline-only image preparation for product-media VLM work."""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError


PREPROCESSING_VERSION = "product_media_bounded_pixels_v1"
DEFAULT_PROFILE = {
    "max_pixels": 1024 * 1024,
    "max_width": 2048,
    "max_height": 2048,
    "output_format": "JPEG",
    "quality": 92,
    "tile_enabled": False,
    "tile_size": 0,
    "tile_overlap": 0,
}


class ImagePreprocessingError(ValueError):
    pass


@dataclass(frozen=True)
class PreprocessedImage:
    data: bytes
    extension: str
    provenance: dict


def _bounded_size(width: int, height: int, profile: dict) -> tuple[int, int]:
    max_pixels = int(profile["max_pixels"])
    scale = min(1.0, (max_pixels / max(width * height, 1)) ** 0.5,
                int(profile["max_width"]) / max(width, 1), int(profile["max_height"]) / max(height, 1))
    return max(1, round(width * scale)), max(1, round(height * scale))


def preprocess_product_media_image(data: bytes, *, profile: dict | None = None) -> PreprocessedImage:
    options = {**DEFAULT_PROFILE, **(profile or {})}
    if options["tile_enabled"]:
        raise ImagePreprocessingError("tiling_not_enabled_for_current_shadow_profile")
    original_hash = hashlib.sha256(data).hexdigest()
    try:
        with Image.open(io.BytesIO(data)) as source:
            source.verify()
        with Image.open(io.BytesIO(data)) as source:
            original_width, original_height = source.size
            if original_width * original_height > 40_000_000:
                raise ImagePreprocessingError("image_pixel_limit_exceeded")
            oriented = ImageOps.exif_transpose(source)
            width, height = oriented.size
            target_width, target_height = _bounded_size(width, height, options)
            transformed = oriented.resize((target_width, target_height), Image.Resampling.LANCZOS) if (width, height) != (target_width, target_height) else oriented.copy()
            had_alpha = "A" in transformed.getbands()
            if had_alpha:
                transformed = transformed.convert("RGBA")
                image_format, extension = "PNG", ".png"
            else:
                transformed = transformed.convert("RGB")
                image_format, extension = "JPEG", ".jpg"
            output = io.BytesIO()
            save_options = {"format": image_format}
            if image_format == "JPEG": save_options.update({"quality": int(options["quality"]), "optimize": False})
            transformed.save(output, **save_options)
    except (UnidentifiedImageError, OSError) as exc:
        raise ImagePreprocessingError("image_decode_failed") from exc
    derived = output.getvalue()
    return PreprocessedImage(
        data=derived,
        extension=extension,
        provenance={
            "preprocessing_version": PREPROCESSING_VERSION,
            "original_media_sha256": original_hash,
            "derived_input_sha256": hashlib.sha256(derived).hexdigest(),
            "original_width": original_width, "original_height": original_height,
            "derived_width": target_width, "derived_height": target_height,
            "scale_x": target_width / width, "scale_y": target_height / height,
            "exif_transposed": (width, height) != (original_width, original_height),
            "alpha_preserved": had_alpha,
            "output_format": image_format,
            "tile_enabled": False,
        },
    )
