"""Face / skin analysis for video retouching.

Runs on a small copy of each frame (CPU, MediaPipe), output is a low-res 2-channel mask that the
GPU retouch shader samples at full resolution:
    R = smoothing weight (face skin, body skin at 60%, eyes / brows / lips cut out)
    G = tone weight      (skin brightening; features only half cut out)
Temporal smoothing (EMA with scene-cut reset) keeps masks from flickering between frames.
"""
from __future__ import annotations

import os
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

MODELS = Path(__file__).resolve().parent.parent / "models"
SEG_MODEL = MODELS / "selfie_multiclass_256x256.tflite"
LMK_MODEL = MODELS / "face_landmarker.task"
ANALYSIS_SHORT = 360          # analysis frame short side, px

# MediaPipe FaceMesh (478-pt) contours. (indices, hull growth factor around the centroid)
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

_tls = threading.local()
_registry: list = []            # every MediaPipe task created, so close() can release them all
_registry_lock = threading.Lock()
OFFS_SCALE = 8.0                # cheek offset (uv) is stored * 8 in a uint8 channel

# Segmentation backend: "gpu" (ONNX Runtime + DirectML, cake.seg_gpu), "cpu" (MediaPipe) or "auto".
SEG_BACKEND = os.environ.get("CAKE_SEG", "auto")
_gpu_seg = None
_gpu_seg_lock = threading.Lock()


def _gpu_segmenter():
    global _gpu_seg
    if SEG_BACKEND == "cpu":
        return None
    with _gpu_seg_lock:
        if _gpu_seg is None:
            try:
                from . import seg_gpu
                _gpu_seg = seg_gpu.GpuSegmenter() if seg_gpu.available() else False
            except Exception:
                if SEG_BACKEND == "gpu":
                    raise
                _gpu_seg = False
    return _gpu_seg or None


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


@dataclass
class Raw:
    """Worker output for one frame. All images at analysis resolution, uint8."""
    seg: np.ndarray | None  # (h, w, 2) face-skin, body-skin; None on skipped frames
    layers: np.ndarray      # (h, w, 4) eyes/brows/lips cut-out, nostril cut-out, under-eye, offset
    face_h: float
    boxes: list
    thumb: np.ndarray | None  # tiny skin map, for scene-cut detection on key frames


@dataclass
class FaceInputs:
    """What the renderer needs for one frame (mask assembly + EMA happen on the GPU)."""
    seg_a: np.ndarray       # segmentation key frame before (or at) this frame
    seg_b: np.ndarray       # next key frame (same object as seg_a on key frames / clip end)
    t: float                # interpolation weight a -> b
    layers: np.ndarray
    face_h: float
    boxes: list
    reset: bool             # scene cut / first frame: don't blend with the previous mask


def analysis_size(w: int, h: int) -> tuple[int, int]:
    k = ANALYSIS_SHORT / min(w, h)
    return max(2, round(w * k)), max(2, round(h * k))


def to_small(frame: bytes, w: int, h: int, high_bit: bool) -> np.ndarray:
    a = np.frombuffer(frame, np.uint16 if high_bit else np.uint8).reshape(h, w, 3)
    if high_bit:
        a = (a >> 8).astype(np.uint8)
    return cv2.resize(a, analysis_size(w, h), interpolation=cv2.INTER_AREA)


def _segment(small: np.ndarray, seg_task) -> np.ndarray:
    gpu = _gpu_segmenter()
    if gpu is not None:
        face, body = gpu.segment(small)
    else:
        import mediapipe as mp
        img = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(small))
        cm = seg_task.segment(img).confidence_masks
        face, body = cm[3].numpy_view().squeeze(), cm[2].numpy_view().squeeze()
    return (np.dstack([face, body]).clip(0, 1) * 255 + 0.5).astype(np.uint8)


def run_models(small: np.ndarray, do_seg: bool = True, ts_ms: int = 0) -> Raw:
    """Worker-thread part: model calls + drawing the landmark layers (all the CPU-heavy work)."""
    import mediapipe as mp
    seg_task, lmk = _models()
    seg = _segment(small, seg_task) if do_seg else None
    img = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(small))
    _tls.ts = max(ts_ms, _tls.ts + 1)                    # VIDEO mode needs increasing timestamps
    h, w = small.shape[:2]
    faces = [np.array([[q.x * w, q.y * h] for q in pts], np.float32)
             for pts in lmk.detect_for_video(img, _tls.ts).face_landmarks]
    layers, face_h, boxes = landmark_layers(faces, (h, w))
    thumb = None
    if seg is not None:
        thumb = cv2.resize(seg, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32) / 255
    return Raw(seg, layers, face_h, boxes, thumb)


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


def analyze(small: np.ndarray) -> FaceInputs:
    """Single still frame (no temporal context)."""
    raw = run_models(small, True)
    return FaceInputs(raw.seg, raw.seg, 0.0, raw.layers, raw.face_h, raw.boxes, True)


def _proc_task(small: np.ndarray, do_seg: bool, ts: int) -> Raw:
    """Process-pool entry point (must be top level to be picklable)."""
    return run_models(small, do_seg, ts)


def _proc_warm(_i: int) -> int:
    """Load the models in a worker (and hold it briefly so each worker gets one warm task)."""
    import time
    _models()
    _gpu_segmenter()
    time.sleep(0.4)
    return os.getpid()


class Analyzer:
    """Frames are analysed ahead of the renderer. Segmentation runs every `seg_every` frames
    (skipped frames are interpolated between key frames on the GPU); landmarks run on every
    frame so eye / lip cut-outs never lag behind the face.

    mode="process" (default): worker PROCESSES. With threads, the workers' Python parts, the
    render thread and the reader/writer threads all fight over the GIL - measured: the main loop
    spent most of its time waiting for it. Each process has its own GIL (and its own DirectML
    session); only the small analysis frame (~0.7 MB) and the result (~1.4 MB) cross over."""

    def __init__(self, workers: int | None = None, seg_every: int = 2, fps: float = 30.0,
                 cut_threshold: float = 0.12, mode: str | None = None):
        self.mode = mode or os.environ.get("CAKE_ANALYZER", "process")
        if self.mode == "process":
            from concurrent.futures import ProcessPoolExecutor
            n = workers or 3
            self.pool = ProcessPoolExecutor(max_workers=n)
            # load models in every worker up front (~2-4 s) instead of during the first frames
            self.warm = [self.pool.submit(_proc_warm, i) for i in range(n)]
        else:
            self.pool = ThreadPoolExecutor(max_workers=workers or 4, thread_name_prefix="face")
        self.seg_every = max(1, seg_every)
        self.frame_ms = 1000.0 / max(fps, 1.0)
        self.cut = cut_threshold
        self.futs: dict[int, Future] = {}
        self.last_seg = None
        self.last_thumb = None
        self.last_seg_index = -1
        self.face_h = 0.0
        self.eof = False
        self._cv = threading.Condition()

    def submit(self, frame: bytes, w: int, h: int, high_bit: bool, index: int) -> Future:
        do_seg = index % self.seg_every == 0
        ts = getattr(self, "_ts_base", 0) + int(index * self.frame_ms)
        if self.mode == "process":
            fut = self.pool.submit(_proc_task, to_small(frame, w, h, high_bit), do_seg, ts)
        else:
            fut = self.pool.submit(lambda: run_models(to_small(frame, w, h, high_bit), do_seg, ts))
        with self._cv:
            self.futs[index] = fut
            self._cv.notify_all()
        return fut

    def reset(self, fps: float | None = None):
        """Start a new video with the same (warm) workers."""
        with self._cv:
            self.futs = {}
            self.eof = False
        if fps:
            self.frame_ms = 1000.0 / max(fps, 1.0)
        self.last_seg = self.last_thumb = None
        self.last_seg_index = -1
        self.face_h = 0.0
        self._ts_base = getattr(self, "_ts_base", 0) + 10_000_000   # keep VIDEO-mode ts rising

    def wait_ready(self):
        for f in getattr(self, "warm", []):
            f.result()

    def finish(self):
        """Called by the producer after the last frame was submitted."""
        with self._cv:
            self.eof = True
            self._cv.notify_all()

    def _next_seg(self, index: int):
        """Segmentation of the next key frame after `index`, or None at the end of the clip."""
        k = (index // self.seg_every + 1) * self.seg_every
        with self._cv:
            while k not in self.futs and not self.eof:
                self._cv.wait(0.05)
            fut = self.futs.get(k)
        return (k, fut.result().seg) if fut else (None, None)

    def result(self, index: int) -> FaceInputs:
        """Call in frame order from the render thread. Cheap: no image maths here."""
        raw = self.futs[index].result()
        reset = False
        if raw.seg is not None:
            if self.last_thumb is None or float(np.abs(raw.thumb - self.last_thumb).mean()) > self.cut:
                reset = True
            self.last_seg, self.last_thumb, self.last_seg_index = raw.seg, raw.thumb, index
            seg_a = seg_b = raw.seg
            t = 0.0
        else:
            k, nxt = self._next_seg(index)
            seg_a = self.last_seg
            seg_b = nxt if nxt is not None else self.last_seg
            t = 0.0 if nxt is None else (index - self.last_seg_index) / (k - self.last_seg_index)
        for old in [i for i in self.futs if i < self.last_seg_index]:
            del self.futs[old]
        if raw.face_h > 0:
            self.face_h = raw.face_h if self.face_h == 0 or reset else \
                self.face_h + (raw.face_h - self.face_h) * 0.2
        return FaceInputs(seg_a, seg_b, t, raw.layers, self.face_h, raw.boxes, reset)

    def close(self):
        self.pool.shutdown(wait=True, cancel_futures=True)
        if self.mode != "process":
            close_models()
