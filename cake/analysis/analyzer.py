from __future__ import annotations
import os, threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
import cv2
import numpy as np
from ..core.config import MODEL_DIR as MODELS, ANALYSIS_SHORT, CAKE_SEG, CAKE_ANALYZER, SEG_EVERY, PROCESS_WORKERS, THREAD_WORKERS
SEG_MODEL = MODELS / "selfie_multiclass_256x256.tflite"
LMK_MODEL = MODELS / "face_landmarker.task"
from .models import _models, _tls, close_models
from .segment import _gpu_segmenter, _segment
from .frames import to_small
from .layers import landmark_layers

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

    def __init__(self, workers: int | None = None, seg_every: int = SEG_EVERY, fps: float = 30.0,
                 cut_threshold: float = 0.12, mode: str | None = None):
        self.mode = mode or CAKE_ANALYZER
        if self.mode == "process":
            from concurrent.futures import ProcessPoolExecutor
            n = workers or PROCESS_WORKERS
            self.pool = ProcessPoolExecutor(max_workers=n)
            # load models in every worker up front (~2-4 s) instead of during the first frames
            self.warm = [self.pool.submit(_proc_warm, i) for i in range(n)]
        else:
            self.pool = ThreadPoolExecutor(max_workers=workers or THREAD_WORKERS, thread_name_prefix="face")
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

    def submit(self, frame: bytes, w: int, h: int, high_bit: bool, index: int,
               yuv: tuple | None = None) -> Future:
        do_seg = index % self.seg_every == 0
        ts = getattr(self, "_ts_base", 0) + int(index * self.frame_ms)
        if self.mode == "process":
            fut = self.pool.submit(_proc_task, to_small(frame, w, h, high_bit, yuv), do_seg, ts)
        else:
            fut = self.pool.submit(lambda: run_models(to_small(frame, w, h, high_bit, yuv), do_seg, ts))
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

