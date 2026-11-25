"""Realistic optical & physical capture degradation pipeline.

Transforms crisp CAD outputs into realistic scanned or photographed blueprints
while strictly preserving topological answers (semantic-preserving transforms).
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

from schemforge.netlist import DegradationProfile

def apply_degradation(
    image_path: str, profile: DegradationProfile, seed: int
) -> None:
    """Apply deterministic optical/sensor degradation in-place to PNG image."""
    if profile == DegradationProfile.CLEAN:
        return

    rng = np.random.default_rng(seed)
    with Image.open(image_path) as raw:
        img = raw.convert("RGB")

    w, h = img.size

    if profile == DegradationProfile.OFFICE_SCAN:
        angle = float(rng.uniform(-1.6, 1.6))
        bg_sample = tuple(int(v) for v in np.array(img)[5, 5])
        img = img.rotate(angle, resample=Image.Resampling.BICUBIC, fillcolor=bg_sample)
        img = ImageEnhance.Color(img).enhance(0.25)
        img = ImageEnhance.Contrast(img).enhance(1.12)
        arr = np.array(img, dtype=np.float32)
        speck_mask = rng.random((h, w)) < 0.0018
        arr[speck_mask] = rng.uniform(30, 120, size=(speck_mask.sum(), 3))
        img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))

    elif profile == DegradationProfile.MOBILE_PHOTO:
        angle = float(rng.uniform(-2.8, 2.8))
        bg_sample = tuple(int(v) for v in np.array(img)[5, 5])
        img = img.rotate(angle, resample=Image.Resampling.BICUBIC, fillcolor=bg_sample)
        img = img.filter(ImageFilter.GaussianBlur(radius=0.55))
        arr = np.array(img, dtype=np.float32)

        yy, xx = np.mgrid[0:h, 0:w]
        cx = w * float(rng.uniform(0.35, 0.65))
        cy = h * float(rng.uniform(0.35, 0.65))
        dist = np.sqrt(((xx - cx) / w) ** 2 + ((yy - cy) / h) ** 2)
        vignette = np.clip(1.04 - 0.30 * dist, 0.72, 1.04)[..., None]
        noise = rng.normal(0.0, 4.5, size=arr.shape)
        arr = arr * vignette + noise
        img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))

    elif profile == DegradationProfile.LOW_CONTRAST_FAX:
        img = ImageEnhance.Contrast(img).enhance(0.68)
        img = img.filter(ImageFilter.GaussianBlur(radius=0.45))
        arr = np.array(img, dtype=np.float32)
        fold_x = int(rng.uniform(w * 0.3, w * 0.7))
        for dx in range(-4, 5):
            if 0 <= fold_x + dx < w:
                shade = 1.0 - 0.14 * (1.0 - abs(dx) / 5.0)
                arr[:, fold_x + dx, :] *= shade
        arr += rng.normal(0.0, 3.0, size=arr.shape)
        img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))

    img.save(image_path, format="PNG", optimize=True, compress_level=9)
