"""Real-video parity and short latency comparison for the ONNX selfie segmenter."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from cake.face import analysis_size  # noqa: E402
from cake.seg_gpu import GpuSegmenter  # noqa: E402

CLIPS = [
    ("asian_hush_48036.mp4", 4),
    ("asian_mother_child_48689.mp4", 3),
    ("asian_closeup_v_101040.mp4", 2),
    ("street_mixed_1227.mp4", 3),
    ("asian_indoor_48688.mp4", 3),
    ("neon_night_1230.mp4", 3),
]


def frame_at(path: Path, seconds: int) -> np.ndarray:
    probe = subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
        "stream=width,height", "-of", "json", str(path),
    ])
    stream = json.loads(probe)["streams"][0]
    w, h = int(stream["width"]), int(stream["height"])
    raw = subprocess.check_output([
        "ffmpeg", "-v", "error", "-nostdin", "-ss", str(seconds), "-i", str(path),
        "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ])
    rgb = np.frombuffer(raw, np.uint8).reshape(h, w, 3)
    sw, sh = analysis_size(w, h)
    return cv2.resize(rgb, (sw, sh), interpolation=cv2.INTER_AREA)


def mediapipe_segment(small: np.ndarray, task):
    import mediapipe as mp
    image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(small))
    masks = task.segment(image).confidence_masks
    return masks[3].numpy_view().squeeze().astype(np.float32), masks[2].numpy_view().squeeze().astype(np.float32)


def main() -> None:
    from mediapipe.tasks.python import BaseOptions, vision
    model = ROOT / "models" / "selfie_multiclass_256x256.tflite"
    task = vision.ImageSegmenter.create_from_options(vision.ImageSegmenterOptions(
        base_options=BaseOptions(model_asset_buffer=model.read_bytes()),
        running_mode=vision.RunningMode.IMAGE, output_confidence_masks=True,
        output_category_mask=False,
    ))
    providers = ["CPUExecutionProvider"]
    import onnxruntime as ort
    if "DmlExecutionProvider" in ort.get_available_providers():
        providers.insert(0, "DmlExecutionProvider")
    segmenters = {ep: GpuSegmenter((ep,)) for ep in providers}
    print("Parity (max abs / mean abs / soft IoU)")
    print("clip                         provider  class      max       mean      soft IoU")
    frames = []
    failures = []
    for filename, sec in CLIPS:
        small = frame_at(ROOT / "samples" / filename, sec)
        ref = mediapipe_segment(small, task)
        frames.append(small)
        for ep, seg in segmenters.items():
            got = seg.segment(small)
            for name, a, b in zip(("face", "body"), ref, got):
                diff = np.abs(a - b)
                union = np.maximum(a, b).sum()
                iou = np.minimum(a, b).sum() / union if union else 1.0
                print(f"{filename:28} {ep:18} {name:8} {diff.max():.6f} {diff.mean():.6f} {iou:.6f}")
                if not (diff.mean() < .01 and (union <= .01 * a.size or iou > .95)):
                    failures.append(f"{filename} {ep} {name}")

    print("\nBenchmark (ms/call; 50 calls after warm-up; 360x640)")
    bench = cv2.resize(frames[0], (640, 360), interpolation=cv2.INTER_AREA)
    # Face module's public worker path includes the same MediaPipe segmentation task.
    mp_image = __import__("mediapipe").Image(image_format=__import__("mediapipe").ImageFormat.SRGB, data=bench)
    seg_task = task
    funcs = [("MediaPipe CPU", lambda: seg_task.segment(mp_image))]
    funcs += [(f"ORT {ep}", lambda s=s: s.segment(bench)) for ep, s in segmenters.items()]
    for label, fn in funcs:
        fn()
        start = time.perf_counter()
        for _ in range(50):
            fn()
        print(f"{label:24} {(time.perf_counter() - start) * 1000 / 50:9.3f}")
    task.close()
    assert not failures, "Parity failed: " + ", ".join(failures)


if __name__ == "__main__":
    main()
