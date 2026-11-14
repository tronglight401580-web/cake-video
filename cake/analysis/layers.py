from __future__ import annotations
import os, threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
import cv2
import numpy as np
from ..core.config import MODEL_DIR as MODELS, ANALYSIS_SHORT, CAKE_SEG, CAKE_ANALYZER, SEG_EVERY, PROCESS_WORKERS, THREAD_WORKERS
SEG_MODEL = MODELS / "selfie_multiclass_256x256.tflite"
LMK_MODEL = MODELS / "face_landmarker.task"
LEFT_EYE = [263, 249, 390, 373, 374, 380, 381, 382, 362, 398, 384, 385, 386, 387, 388, 466]
RIGHT_EYE = [33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246]
LEFT_BROW = [276, 283, 282, 295, 285, 300, 293, 334, 296, 336]
RIGHT_BROW = [46, 53, 52, 65, 55, 70, 63, 105, 66, 107]
LIPS = [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 409, 270, 269, 267, 0, 37, 39, 40, 185]
FEATURES = [(LEFT_EYE, 1.5), (RIGHT_EYE, 1.5), (LEFT_BROW, 1.3), (RIGHT_BROW, 1.3), (LIPS, 1.15)]
# Lower eyelids, inner corner -> outer corner (for the under-eye / dark-circle region)
RIGHT_LOWER_LID = [133, 155, 154, 153, 145, 144, 163, 7, 33]
LEFT_LOWER_LID = [362, 382, 381, 380, 374, 373, 390, 249, 263]
CHIN, FOREHEAD = 152, 10
# Lower nose / nostrils: dark, spot-sized -> would be "healed" as a blemish. Excluded from R.
NOSTRILS = [64, 98, 97, 2, 326, 327, 294, 278, 344, 440, 275, 4, 45, 220, 115, 48]

OFFS_SCALE = 8.0

def landmark_layers(faces: list, shape: tuple):
    """Eyes / brows / lips cut-out (R), nostril + inner-eye-corner cut-out (G),
    dark-circle band (B), cheek-reference offset * OFFS_SCALE (A). uint8 (h, w, 4)."""
    h, w = shape
    excl = np.zeros((h, w), np.uint8)
    nose = np.zeros((h, w), np.uint8)
    under = np.zeros((h, w), np.float32)
    offs = np.zeros((h, w), np.float32)
    boxes, face_h = [], 0.0
    for p in faces:
        x0, y0 = p.min(0)
        x1, y1 = p.max(0)
        boxes.append((x0 / w, y0 / h, x1 / w, y1 / h))
        face_h = max(face_h, (y1 - y0) / h)
        for idx, grow in FEATURES:
            q = p[idx]
            c = q.mean(0)
            cv2.fillConvexPoly(excl, cv2.convexHull((c + (q - c) * grow).astype(np.int32)), 255)
        q = p[NOSTRILS]
        c = q.mean(0)
        cv2.fillConvexPoly(nose, cv2.convexHull((c + (q - c) * 1.15).astype(np.int32)), 255)
        # inner eye corners (tear duct: pink + shadowed, looks like a red spot)
        for inner, outer in ((133, 33), (362, 263)):
            ew = float(np.linalg.norm(p[inner] - p[outer]))
            cv2.circle(nose, tuple(int(v) for v in p[inner]), max(1, int(0.28 * ew)), 255, -1)
        _under_eye(p, under, offs, h)
    if faces:
        feather = max(1.0, min(h, w) / 240)
        excl = cv2.GaussianBlur(excl, (0, 0), feather)
        nose = cv2.GaussianBlur(nose, (0, 0), feather * 2)
    layers = np.dstack([excl, nose, (under * 255 + 0.5).astype(np.uint8),
                        np.clip(offs * OFFS_SCALE * 255 + 0.5, 0, 255).astype(np.uint8)])
    return layers, face_h, boxes


def _under_eye(p: np.ndarray, under: np.ndarray, offs: np.ndarray, h: int) -> None:
    """Draw the dark-circle region (a soft band under each lower lid) for one face.
    `offs` stores how far below (in uv units) the shader should look for the cheek colour."""
    down = p[CHIN] - p[FOREHEAD]
    down /= max(np.linalg.norm(down), 1e-6)
    for lid in (RIGHT_LOWER_LID, LEFT_LOWER_LID):
        q = p[lid]
        ew = float(np.linalg.norm(q[0] - q[-1]))           # eye width
        if ew < 3:
            continue
        top = q + down * 0.07 * ew                         # stay off the lashes
        bottom = (q + down * 0.42 * ew)[::-1]
        poly = np.concatenate([top, bottom]).astype(np.int32)
        H, W = under.shape
        x0, y0 = np.maximum(poly.min(0) - int(0.5 * ew) - 2, 0)
        x1, y1 = np.minimum(poly.max(0) + int(0.5 * ew) + 2, [W, H])
        if x1 - x0 < 2 or y1 - y0 < 2:                     # eye at / beyond the frame edge
            continue
        roi = under[y0:y1, x0:x1]                          # work on a small ROI, not the frame
        band = np.zeros_like(roi)
        cv2.fillPoly(band, [poly - [x0, y0]], 1.0)
        band = cv2.GaussianBlur(band, (0, 0), max(1.0, 0.12 * ew))
        np.maximum(roi, band, out=roi)
        offs[y0:y1, x0:x1][band > 0.02] = 0.55 * ew / h

