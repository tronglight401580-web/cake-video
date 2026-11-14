# Refactor step 2a: split analysis + pipeline modules (behaviour must stay bit-identical)

Context: `docs/CODEX_TASK_refactor.md` (overall plan). Done & committed: golden reference
(`tools/golden.py`, self-noise 0), core bus skeleton, 1a (io/, color/, config), 1b (render/passes).
This run: ONLY the two splits below. Do not touch `cake/ui/` or `cake/__main__.py` (step 2b), and
do not change the Recipe yet.

## 1. `cake/face.py` + `cake/seg_gpu.py` -> `cake/analysis/`
```
analysis/models.py    thread-local MediaPipe task creation (landmarker VIDEO mode, CPU segmenter),
                      registry + close_models(); model bytes via config paths
analysis/segment.py   GPU segmenter (ONNX/DirectML, from seg_gpu.py) + CPU fallback, `segment(small)`
                      -> uint8 (h, w, 2); backend choice from config (CAKE_SEG)
analysis/layers.py    landmark index tables (eyes, brows, lips, nostrils, lower lids...),
                      landmark_layers(), _under_eye(), OFFS_SCALE
analysis/frames.py    analysis_size(), to_small() (RGB and I420 paths)
analysis/analyzer.py  Raw, FaceInputs, run_models(), analyze(), _proc_task/_proc_warm,
                      Analyzer (process/thread pool, key-frame interpolation, scene-cut reset,
                      reset()/wait_ready()/finish()/result()/close())
```
`cake/face.py` and `cake/seg_gpu.py` become shims re-exporting everything tools/tests/ui use
(grep for `from cake.face import`, `F.` attribute use in tools such as `F._models`, `F._tls`,
`F._segment`, `F._gpu_segmenter`, `F.Analyzer.__init__` monkeypatching in tools/bench_speed.py,
tools/profile_*.py). Process-pool workers must still import cleanly on Windows spawn (top-level,
picklable entry points).

## 2. `cake/pipeline.py` -> `cake/pipeline/`
```
pipeline/__init__.py  re-exports (keep `cake.pipeline.X` working for every name used today,
                      including monkeypatch targets: Encoder, Decoder, yuv_capable, Renderer,
                      pick_encoder ... - tools patch them as attributes of `cake.pipeline`; make
                      sure patching still affects behaviour, e.g. export.py looks them up via the
                      package or the tools are updated consistently - document which)
pipeline/export.py    grade_video (+ CancelledError, _pump, _END)
pipeline/stills.py    _grab_frame, _to_u8, compare_still, compare_face, _renderer_with_mask,
                      _identity_style, _save_sheet
```
`grade_video` already publishes on the bus (1a); keep that.

## Verify (all must pass; report result lines)
- `python tools/golden.py check` - all 5 mean 0 / max 0
- `python tests/run_unit.py`
- `python tools/run_all_tests.py` (≈10 min, long timeout, to completion)
- `python tools/test_refcolor.py`
- `python tools/bench_speed.py samples/street_mixed_1227.mp4` and the same on the previous commit
  is NOT needed; just report fps (≈30 on this machine today)
- `python -m cake face samples/asian_hush_48036.mp4 --t 4 -o %TEMP%/face_check.jpg` runs
Report (< 30 lines): file map, how monkeypatch targets are preserved, verification lines.
