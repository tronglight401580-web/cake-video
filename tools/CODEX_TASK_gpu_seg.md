# Task: run the skin segmenter on the GPU (ONNX Runtime + DirectML)

## Why
`cake/face.py` runs MediaPipe's multiclass selfie segmenter on CPU: ~140 ms/frame on this machine
(Xeon E5-2666 v3, GTX 1060 5GB). It is the main reason video retouching runs at ~12 fps instead of
real time. Goal: same masks, on the GPU, a few ms per frame.

## Files you may create / change
- `tools/convert_seg_onnx.py` (exists; rewrite freely) -> produces `models/selfie_multiclass_256x256.onnx`
- `cake/seg_gpu.py` (new)
- `tools/test_seg_gpu.py` (new)
Do NOT edit `cake/face.py`, `cake/gpu.py`, `cake/shaders.py`, `cake/pipeline.py` — another engineer
is changing them right now. No network access; do not pip install.

## Environment (already installed)
- Main interpreter `python` (3.12): numpy, opencv (`cv2`), mediapipe 1.2.3, onnxruntime-directml 1.24
  (`DmlExecutionProvider` available), Pillow.
- Conversion venv `.cv\Scripts\python.exe`: tensorflow-cpu + tf2onnx. Use it ONLY for conversion, e.g.
  `.cv\Scripts\python.exe -m tf2onnx.convert --tflite models\selfie_multiclass_256x256.tflite --output models\selfie_multiclass_256x256.onnx --opset 17`
  (`tflite2onnx` was tried and fails on SUM and on RESIZE with computed sizes; don't use it.)
- Paths contain Chinese characters: MediaPipe needs `BaseOptions(model_asset_buffer=path.read_bytes())`;
  for ORT also pass model bytes (`InferenceSession(path.read_bytes(), ...)`).

Model facts: input `[1,256,256,3]` float, output `[1,256,256,6]` softmax confidences, classes
`background, hair, body-skin, face-skin, clothes, others`. Ops: CONV_2D, DEPTHWISE_CONV_2D, ADD, MUL,
RESHAPE, TRANSPOSE, SOFTMAX, SUM, RESIZE_BILINEAR, RESIZE_NEAREST_NEIGHBOR, TRANSPOSE_CONV.

## `cake/seg_gpu.py` interface (must match exactly)
```python
class GpuSegmenter:
    def __init__(self, providers=("DmlExecutionProvider", "CPUExecutionProvider")): ...
    def segment(self, small_rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """small_rgb: (h, w, 3) uint8 RGB of any size (we pass ~360x640 / 640x360).
        Returns (face_skin, body_skin): float32 (h, w) in 0..1 at the INPUT size —
        i.e. drop-in for MediaPipe's confidence_masks[3] / [2] at the same resolution."""
    provider: str   # which EP is actually active
def available() -> bool   # model file exists and onnxruntime imports
```
Must be safe to call from several threads (serialise internally with a lock if DirectML needs it).

## Parity (the important part)
Reproduce MediaPipe's preprocessing/postprocessing exactly: figure out input normalisation
([0,1] vs [-1,1]), how a non-square frame is mapped to 256x256 (stretch vs letterbox/crop), and how
the 256x256 output is resized back. Verify on REAL frames from these clips (decode with ffmpeg pipe,
scale to short side 360 like `cake.face.to_small` does):
`samples/asian_hush_48036.mp4` (t=4), `samples/asian_mother_child_48689.mp4` (t=3),
`samples/asian_closeup_v_101040.mp4` (t=2, vertical), `samples/street_mixed_1227.mp4` (t=3, vertical).
Report per clip, for face-skin and body-skin: max abs diff, mean abs diff, and IoU of (>0.5) masks
vs MediaPipe. Target: mean abs diff < 0.01 and IoU > 0.97. Compare both DML and CPU EPs.

## Speed
`tools/test_seg_gpu.py` also benchmarks: MediaPipe CPU vs ORT CPU vs ORT DirectML, ms per call
(after warm-up, 50 calls), at 360x640 input. Print a table.

## Done =
`python tools/test_seg_gpu.py` runs the parity checks (asserting the targets) + the benchmark and
passes. Print the parity table and benchmark table in your final message. Keep your test runs short
(another process will benchmark later; don't leave anything running).
