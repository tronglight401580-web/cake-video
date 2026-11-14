from __future__ import annotations
import os, threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
import cv2
import numpy as np
from ..core.config import MODEL_DIR as MODELS, ANALYSIS_SHORT, CAKE_SEG, CAKE_ANALYZER, SEG_EVERY, PROCESS_WORKERS, THREAD_WORKERS
SEG_MODEL = MODELS / "selfie_multiclass_256x256.tflite"
LMK_MODEL = MODELS / "face_landmarker.task"
from .segment import _gpu_segmenter
_tls = threading.local()
_registry = []
_registry_lock = threading.Lock()

def _models():
    if not hasattr(_tls, "lmk"):
        from mediapipe.tasks.python import BaseOptions, vision
        # model_asset_buffer, not _path: MediaPipe's C layer can't open non-ASCII (Chinese) paths.
        # VIDEO mode tracks landmarks between calls instead of re-detecting faces every frame.
        _tls.lmk = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_buffer=LMK_MODEL.read_bytes()),
            running_mode=vision.RunningMode.VIDEO, num_faces=4,
            min_face_detection_confidence=0.5, min_face_presence_confidence=0.5,
            min_tracking_confidence=0.5))
        _tls.ts = -1
        _tls.seg = None
        with _registry_lock:
            _registry.append(_tls.lmk)
    if _tls.seg is None and _gpu_segmenter() is None:
        from mediapipe.tasks.python import BaseOptions, vision
        _tls.seg = vision.ImageSegmenter.create_from_options(vision.ImageSegmenterOptions(
            base_options=BaseOptions(model_asset_buffer=SEG_MODEL.read_bytes()),
            running_mode=vision.RunningMode.IMAGE,
            output_confidence_masks=True, output_category_mask=False))
        with _registry_lock:
            _registry.append(_tls.seg)
    return _tls.seg, _tls.lmk


def close_models():
    with _registry_lock:
        for task in _registry:
            try:
                task.close()
            except Exception:
                pass
        _registry.clear()

