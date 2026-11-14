# Task: find and fix the parity gap between `cake/seg_gpu.py` (ONNX/DirectML) and MediaPipe

Previous attempt (read `cake/seg_gpu.py`, `tools/test_seg_gpu.py`, `tools/convert_seg_onnx.py`):
the ONNX model converts and runs (DirectML 23.5 ms vs MediaPipe CPU 143 ms), and on most frames it
is close (mean abs diff 0.002-0.005), but:
- `asian_closeup_v_101040.mp4` @2s (purple / red neon light, face mostly hidden) is way off:
  face mean diff 0.177, IoU 0.05; body IoU 0.00.
- body-skin IoU at >0.5 is only 0.91-0.96 on the other clips.

This smells like a preprocessing / postprocessing mismatch that only shows on extreme colours,
not a broken model. Find the ROOT CAUSE — don't tune thresholds to make numbers pass.

## Hypotheses to test (verify each with evidence, report what you found)
1. Double softmax: `seg_gpu.py` applies softmax to the ONNX output assuming it is pre-softmax, but
   the TFLite graph contains 6 SOFTMAX ops. Inspect the ONNX graph's final nodes (onnx package is in
   `.cv\Scripts\python.exe`; `onnx` may also be importable in the main env) and check whether the
   output already sums to 1 over the class axis.
2. Input normalisation: [0,1] vs [-1,1] vs 0..255; check the TFLite model metadata
   (NormalizationOptions in the model's metadata flatbuffer; `tflite` package is installed in the main
   env) and MediaPipe's image segmenter defaults.
3. Channel order (RGB vs BGR) and how MediaPipe maps a non-square input to 256x256 (stretch vs keep
   aspect with padding) and the output back (bilinear? with/without align-corners?).
4. Whether MediaPipe applies any activation / smoothing on confidence masks after the model.
A fast way to test: build a tiny probe — feed MediaPipe and ONNX the same 256x256 image (no resize
involved) and compare raw outputs; then vary one preprocessing choice at a time.

## Files you may change
`cake/seg_gpu.py`, `tools/test_seg_gpu.py`, `tools/convert_seg_onnx.py`, new files under `tools/`.
Do NOT touch `cake/face.py`, `cake/gpu.py`, `cake/shaders.py`, `cake/pipeline.py`, `models/*.tflite`.
No network, no pip install. MediaPipe needs `BaseOptions(model_asset_buffer=...)` (non-ASCII path).
Keep the public interface of `cake/seg_gpu.py` unchanged (GpuSegmenter.segment, .provider, available()).

## Acceptance (updated — IoU at a hard 0.5 threshold is too boundary-sensitive for soft masks)
For each clip/class: mean abs diff < 0.01, and soft IoU = sum(min(a,b)) / sum(max(a,b)) > 0.95
whenever sum(max(a,b)) > 1% of pixels (skip IoU for near-empty masks, but still enforce mean diff).
Same 4 clips/timestamps as `tools/test_seg_gpu.py`; also add `samples/asian_indoor_48688.mp4` @3s
and `samples/neon_night_1230.mp4` @3s. Keep the benchmark; DirectML must stay well under 40 ms/call.

## Report
Root cause(s) with the evidence, the fix, the final parity table and benchmark. Run
`python tools/test_seg_gpu.py` and make it pass. Don't leave processes running.
