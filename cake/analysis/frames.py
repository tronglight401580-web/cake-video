from __future__ import annotations
import os, threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
import cv2
import numpy as np
from ..core.config import MODEL_DIR as MODELS, ANALYSIS_SHORT, CAKE_SEG, CAKE_ANALYZER, SEG_EVERY, PROCESS_WORKERS, THREAD_WORKERS
SEG_MODEL = MODELS / "selfie_multiclass_256x256.tflite"
LMK_MODEL = MODELS / "face_landmarker.task"

def analysis_size(w: int, h: int) -> tuple[int, int]:
    k = ANALYSIS_SHORT / min(w, h)
    return max(2, round(w * k)), max(2, round(h * k))


def to_small(frame: bytes, w: int, h: int, high_bit: bool, yuv: tuple | None = None) -> np.ndarray:
    """Analysis-size RGB uint8 from an RGB24/48 frame, or from an I420 frame (yuv=(matrix, range)):
    the planes are downscaled first and converted at small size (~1 ms instead of a full-res
    conversion), with the source's real matrix/range."""
    size = analysis_size(w, h)
    if yuv is None:
        a = np.frombuffer(frame, np.uint16 if high_bit else np.uint8).reshape(h, w, 3)
        if high_bit:
            a = (a >> 8).astype(np.uint8)
        return cv2.resize(a, size, interpolation=cv2.INTER_AREA)
    buf = np.frombuffer(frame, np.uint8)
    ny, nc = w * h, (w // 2) * (h // 2)
    y = cv2.resize(buf[:ny].reshape(h, w), size, interpolation=cv2.INTER_AREA).astype(np.float32)
    u = cv2.resize(buf[ny:ny + nc].reshape(h // 2, w // 2), size, interpolation=cv2.INTER_LINEAR)
    v = cv2.resize(buf[ny + nc:ny + 2 * nc].reshape(h // 2, w // 2), size,
                   interpolation=cv2.INTER_LINEAR)
    if yuv[1] == "pc":
        yy, cb, cr = y, u.astype(np.float32) - 128, v.astype(np.float32) - 128
    else:
        yy = (y - 16) * (255 / 219)
        cb = (u.astype(np.float32) - 128) * (255 / 224)
        cr = (v.astype(np.float32) - 128) * (255 / 224)
    kr, kb = (0.299, 0.114) if yuv[0] == "bt601" else (0.2126, 0.0722)
    r = yy + 2 * (1 - kr) * cr
    b = yy + 2 * (1 - kb) * cb
    g = (yy - kr * r - kb * b) / (1 - kr - kb)
    return np.clip(np.dstack([r, g, b]) + 0.5, 0, 255).astype(np.uint8)

