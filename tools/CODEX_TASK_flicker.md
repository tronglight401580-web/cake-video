# Task: tools/flicker.py — measure temporal flicker that processing ADDS, focused on faces

Context: we retouch faces in video (skin smoothing / brightening driven by per-frame ML masks).
Per-frame processing can "shimmer" or "breathe" frame to frame. We need a tool that says how much
flicker our processing added compared with the original, especially on the face.

Write ONE file: `tools/flicker.py` (+ `tools/test_flicker.py`). Do NOT touch `cake/`, `styles/`,
`luts/`, `models/`, `samples/`. No network access; do not pip install.

## Allowed dependencies
Python 3.12 stdlib, numpy, Pillow, opencv (`cv2`, already installed), mediapipe 1.2.3 (installed).
ffmpeg/ffprobe on PATH. Windows; paths may contain Chinese characters — use subprocess arg lists.
Face model: `models/face_landmarker.task` (MediaPipe Tasks FaceLandmarker, 478 points). Use
`mediapipe.tasks.python.vision.FaceLandmarker` with `RunningMode.IMAGE` and `BaseOptions(model_asset_path=...)`.

## CLI
```
python tools/flicker.py ORIGINAL.mp4 PROCESSED.mp4 [--max-frames 240] [--out OUT_DIR]
```
Both videos have the same frame count / fps / orientation (processed may have different resolution:
scale processed to original size, or both to the original's size capped at 1080 short side).

## Metric
Decode both as rgb24 frame streams (ffmpeg pipe). For each t ≥ 1, with luma Y (Rec.709):
- `dO = Y_o[t] - Y_o[t-1]`, `dP = Y_p[t] - Y_p[t-1]`
- added flicker map `A = |dP - dO|` (motion in the original cancels out; what remains is change the
  processing introduced). Also compute a low-pass version (gaussian sigma 4 px) of `dP - dO` to
  catch "breathing" (large-area brightness pumping) separately from fine shimmer.
- Face region: run FaceLandmarker on the ORIGINAL frame every frame; face mask = convex hull of the
  478 points (all faces), filled. Report metrics inside face mask and in the whole frame.
Per frame record: `face_shimmer` (mean A in face), `face_breathing` (mean |lowpass| in face),
`frame_shimmer`, `frame_breathing`. Values in 8-bit levels (0-255 scale).

## Outputs
- `OUT/<stem>_flicker.json`: per-frame arrays + summary (mean, p95, max for each metric, number of
  frames with a face).
- `OUT/<stem>_flicker.png`: line plot of the four metrics over frames (draw with Pillow; no matplotlib
  needed) plus a heatmap thumbnail of the mean added-flicker map over the clip.
- Print a short summary table. Default OUT = `<processed dir>/flicker/`.

## Test
`tools/test_flicker.py`: build a synthetic 2 s clip with ffmpeg (e.g. `testsrc2` 540x960), make a
"processed" copy that is identical (expect ~0 flicker) and one with per-frame random brightness
jitter (`eq=brightness=...` driven by an expression with `random(0)`, or numpy-generated) — assert
the jittered one has much higher frame_breathing than the identical one. Faces will be absent in
synthetic clips; the tool must handle 0 faces gracefully. Run the test and make it pass.

Print a short summary of what you built and the test output when done.
