"""Naive contour counter, used only as a comparison baseline.

It shares preprocess() with the main pipeline exactly (decode, resize, gray,
blur, Otsu, polarity, morphology, hole filling) and then simply counts external
contours with area >= min_area_px. No watershed, no median/cluster logic, so
the comparison isolates what the watershed + area logic contributes.
"""
from __future__ import annotations

import cv2
import numpy as np

from app.counter import CountParams, Preprocessed, preprocess


def baseline_from_mask(mask: np.ndarray, params: CountParams = CountParams()) -> int:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return int(sum(1 for c in contours if cv2.contourArea(c) >= params.min_area_px))


def baseline_from_preprocessed(pre: Preprocessed, params: CountParams = CountParams()) -> int:
    return baseline_from_mask(pre.mask, params)


def baseline_count(image_bytes: bytes, params: CountParams = CountParams()) -> int:
    return baseline_from_preprocessed(preprocess(image_bytes, params), params)
