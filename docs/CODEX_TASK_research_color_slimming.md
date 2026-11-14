# Research task: reference-photo colour transfer + automatic skin protection + automatic face slimming (video)

You are doing a **feasibility study**, not writing product code. Use live web search. Write the
report in **Chinese** to `docs/research_ref_color_slimming.md`. Do not modify anything under
`cake/`, `styles/`, `tools/`. No pip install / no downloads (you may read web pages).

## Our project (read these first, briefly)
- `README.md` - what exists. Key facts: Windows, Python 3.12, GTX 1060 5GB (Pascal, no tensor cores,
  driver 526), Xeon E5-2666 v3. Video pipeline: ffmpeg decode -> GPU shader chain (moderngl/OpenGL
  3.3) -> hardware H.264 encode. Already real-time-ish (~30 fps 1080x1920) with retouching on.
- `cake/face.py` - per-frame analysis in worker processes: MediaPipe FaceLandmarker (478 points,
  VIDEO mode, ~3 ms) + skin segmentation (MediaPipe multiclass selfie model converted to ONNX,
  DirectML on GPU, ~22 ms per call, run every 2nd frame). Produces skin masks + landmark layers.
- `cake/shaders.py` + `cake/gpu.py` - GPU passes: YUV2RGB, MASKBUILD, HEAL (blemish/dark circles),
  RETOUCH (frequency-separation smoothing), GRADE (3D LUT with strength), bloom, FINISH, TOYUV.
- `cake/looks.py` - looks are 3D LUTs (.cube) generated from numpy colour maths; skin hue protection
  is currently baked into the LUT by hue only.
- Current bottleneck: the GPU (DirectML segmentation and OpenGL compete on the GTX 1060).

## Questions to answer
1. **"像素吐司"**: what product is it (company, platform, photo or video, pricing), what exactly do
   its colour-transfer ("追色"), skin-protection and face-slimming features do, and any public
   info on how it works. Also briefly: does 像素蛋糕 / WinkStudio / 醒图 / others offer
   reference-photo colour transfer and automatic face slimming for VIDEO?
2. **Reference-photo colour transfer that outputs a 3D LUT** (so it drops into our GRADE pass and
   stays temporally stable because the LUT is fixed or changes slowly per shot). Survey open-source
   options: classical (Reinhard/Lab statistics, MKL / Monge-Kantorovich, histogram matching,
   colour-transfer with region correspondence) and learned (e.g. Image-Adaptive 3D LUT, AdaInt,
   SepLUT, Neural Preset, Deep Preset, any 2023-2026 "reference-based colour transfer / photo
   retouching" models with code). For each: repo URL, licence (commercial use OK?), model size,
   expected speed on a GTX 1060 (or CPU) for producing one LUT, quality notes, whether it handles
   "transfer the mood but keep skin natural".
3. **Automatic skin protection during transfer**: concrete method using OUR existing skin mask
   (e.g. fit the transfer on non-skin pixels only; separate constrained transfer for skin toward a
   target skin tone; blend by mask in the shader). Point to papers/code if any.
4. **Automatic face slimming / reshaping for VIDEO** driven by 478-point MediaPipe landmarks:
   survey open-source implementations (e.g. GPUPixel face reshape, other GLSL "thin face / big eye"
   filters, moving-least-squares or thin-plate-spline warps, mesh warps on the face mesh). Repo
   URLs + licences. Key concerns for video: landmark jitter (One Euro filter etc.), keeping the
   background / straight lines from bending (segmentation-limited warp, falloff), large head turns,
   multiple faces, speed on our GPU. How do commercial apps avoid the "wobbling background" artefact?
5. **Integration plan for our pipeline**: where each piece goes (new shader pass? before HEAL?),
   what data it needs from `cake/face.py`, rough effort (days), main risks, and a recommended
   minimal prototype for each of: (a) reference colour transfer -> LUT, (b) skin protection,
   (c) face slimming.

## Report format (`docs/research_ref_color_slimming.md`)
- 结论先行: for each of (a)(b)(c): 能不能做 / 推荐方案 / 预计工作量 / 主要风险 (one short block each).
- A licence table of every project you recommend (name, URL, licence, commercial OK?).
- Sources: every claim about a product or repo must have a URL. Say clearly when something could
  not be verified (don't guess product internals).
- Keep it under ~250 lines. Final message: just the 结论先行 section + the report path.
