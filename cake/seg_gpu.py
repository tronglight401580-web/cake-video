"""MediaPipe compatible selfie skin segmentation through ONNX Runtime."""
from __future__ import annotations

import threading
from .core.config import SEGMENTATION_MODEL

import cv2
import numpy as np

MODEL = SEGMENTATION_MODEL


def available() -> bool:
    return MODEL.is_file() and __import__("importlib").util.find_spec("onnxruntime") is not None


class GpuSegmenter:
    def __init__(self, providers=("DmlExecutionProvider", "CPUExecutionProvider")):
        import onnxruntime as ort

        self._lock = threading.Lock()
        self._session = ort.InferenceSession(MODEL.read_bytes(), providers=list(providers))
        self.provider = self._session.get_providers()[0]
        self._input = self._session.get_inputs()[0]
        self._output = self._session.get_outputs()[0].name

    def segment(self, small_rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Return face-skin and body-skin confidence masks at the input resolution."""
        if small_rgb.ndim != 3 or small_rgb.shape[2] != 3 or small_rgb.dtype != np.uint8:
            raise ValueError("small_rgb must be an HxWx3 uint8 RGB array")
        # MediaPipe's ImageToTensor path scales RGB bytes to [-1, 1].
        ih, iw = int(self._input.shape[-3]), int(self._input.shape[-2])
        resized = cv2.resize(small_rgb, (iw, ih), interpolation=cv2.INTER_LINEAR)
        x = np.ascontiguousarray(resized[None], dtype=np.float32) / 127.5 - 1.0
        if len(self._input.shape) == 4 and self._input.shape[1] == 3:
            x = x.transpose(0, 3, 1, 2)
        with self._lock:
            out = self._session.run([self._output], {self._input.name: x})[0]
        if out.ndim != 4:
            raise RuntimeError(f"Unexpected segmentation output shape: {out.shape}")
        if out.shape[1] == 6:
            out = out.transpose(0, 2, 3, 1)
        conf = out[0]
        # tf2onnx exposes the model's pre-softmax logits.
        conf = conf - conf.max(axis=-1, keepdims=True)
        conf = np.exp(conf)
        conf /= conf.sum(axis=-1, keepdims=True)
        h, w = small_rgb.shape[:2]
        if conf.shape[:2] != (h, w):
            conf = cv2.resize(conf, (w, h), interpolation=cv2.INTER_LINEAR)
        return np.ascontiguousarray(conf[..., 3], dtype=np.float32), np.ascontiguousarray(conf[..., 2], dtype=np.float32)
