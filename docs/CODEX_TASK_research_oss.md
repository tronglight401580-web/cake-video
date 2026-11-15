# Research: open-source projects similar to this one - comparison and reuse plan

Research only. Do NOT edit code. Write the report to `docs/research_oss_comparison.md` (Chinese,
tables welcome). Use web search; cite every project with its URL, licence, stars, and last commit /
release date as you found them (say "unverified" when you could not confirm a number).

## Our project (read `docs/ARCHITECTURE.md` for detail)
A Windows desktop tool ("video PixelCake") for short vertical videos (Douyin / WeChat Channels):
stylised colour grading + portrait retouching, near real time. Stack: Python, ffmpeg decode/encode
(Media Foundation H.264 hardware), moderngl OpenGL 3.3 shader chain, MediaPipe FaceLandmarker
(478 points) + selfie multiclass segmentation (ONNX on DirectML), PySide6 UI. Modules:
1. Colour: procedural 3D LUTs (.cube) per style, skin-hue protection, bloom/vignette/finish.
2. Reference-photo colour transfer with automatic skin protection (separate skin LUT).
3. Retouch: frequency-separation skin smoothing, blemish (acne) removal, dark-circle correction,
   shine removal, teeth whitening, temporal stabilisation (One-Euro landmarks, mask EMA).
4. Face reshape: face slimming + eye enlarging (GPU inverse-mapping warp).
5. Pipeline / UI: batch queue, before/after preview, presets, real-time playback.

## What to find and compare
A. Whole-product analogues (open source): real-time beauty / retouch engines and video colour
   tools. Must check at least: GPUPixel, any OpenCV/MediaPipe "beauty camera" projects with face
   slimming, FaceBeauty-type repos, OBS beauty/LUT filters, Olive / Shotcut / Kdenlive colour
   features, ffmpeg lut3d/haldclut, OpenColorIO, VapourSynth/AviSynth retouch plugins.
B. Per-module alternatives:
   - colour LUT generation / film-look libraries; reference-based colour transfer (classic
     Reinhard/MKL/ histogram, learned: e.g. Neural Preset, Deep Preset, colour-transfer repos);
   - AI skin retouching (e.g. ABPN, RetouchFormer, other skin-retouch / blemish-removal models),
     face restoration is out of scope unless useful for retouch;
   - face reshape / liquify (MLS, GPUPixel reshape filters, other real-time face-slim shaders);
   - face landmarks / face parsing / skin segmentation alternatives to MediaPipe (e.g. BiSeNet
     face parsing, InsightFace) with speed on Windows GPU;
   - temporal stabilisation / video consistency (e.g. deflicker, blind video temporal
     consistency methods).
C. Commercial reference points (brief, no deep dive): PixelCake (像素蛋糕) and its video features,
   Meitu Wink, CapCut/剪映 beauty, 醒图, FaceUnity / SenseTime beauty SDKs - only what they offer
   for video retouch/reshape/colour, to position the open-source options.

## For each candidate report
licence (commercial use OK?), maturity, platform/language, GPU/real-time capability on Windows,
quality evidence (paper/demo), integration cost into our Python + OpenGL pipeline, and overlap with
our module (replace / reuse a part / ignore).

## Conclusions the report must end with
1. A table per module: our current implementation vs best open-source option, recommendation
   (keep / replace / borrow technique) and why.
2. Specifically: can GPUPixel or another engine replace our warp pass (ours currently costs ~400 ms
   CPU per frame - a known bug) and/or our retouch passes? Licence and integration path.
3. What is genuinely not available open source (our likely differentiation).
4. Top 3 reuse actions ranked by value / effort.
Keep the report under ~400 lines. Report back a < 25-line summary.
