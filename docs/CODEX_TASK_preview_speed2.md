# Preview speed follow-up: fix the real cost (warp pass), restore preview resolution

Rules and overrides as in `docs/CODEX_TASK_preview_speed.md`. Product-owner review of your result:

- ACCEPTED: background decoder queue, wall-clock scheduler with frame dropping that still advances
  analysis/tracking, status fps/dropped readout, paused frame byte-identical. Keep all of it.
- REJECTED: `PREVIEW_PLAY_SHORT = 180` / `PREVIEW_PLAY_PORTRAIT_SHORT = 128`. A 128-180 px preview is
  unusable for judging retouch/slimming; it only hides the real problem. Playback short side must be
  >= 540 (720 preferred); a drop to 540 during playback is the most allowed.
- The real problem is in your own profile: GPU render 483.5 ms per frame with slim+eyes on, vs
  ~5 ms without. `tools/test_a.py` also prints "warp GPU 0.18 ms, render 370.75 ms": the warp
  shader is cheap, so ~400 ms per frame is spent elsewhere in the warp pass - most likely CPU work
  (the CPU field counterpart used for the area / smoothness guards evaluated on a grid every frame,
  numpy per-frame allocations, GPU->CPU readback of the field, glFinish/sync, texture re-creation).
  This also makes EXPORT with slimming ~2-3 fps, which is a release blocker.

**Root cause already found (research v2, `docs/research_oss_comparison_v2.md` on main):** cProfile
of hush at 1080x1920 = 1185 ms per frame end to end; two `guard_controls` calls = 1171 ms
(`displacement` itself 1038 ms, `area_range` 98 ms); upload/readback ~4/4 ms; warp GPU 0.34 ms.
So step 1 is only a quick confirmation; spend the effort on step 2. A GPUPixel-style approach was
compared and rejected (more background distortion, weaker eyes, worse two-face results) - keep our
warp maths and behaviour, make the guard cheap.

## Do
1. Profile `cake/render/passes/warp.py` per frame at 1080x1920 and at 720p (CPU time per function,
   GPU time, any readback/sync). Report the breakdown.
2. Make the whole warp pass <= 3 ms per frame (CPU + GPU) at 1080x1920. Ideas: evaluate the guards
   on a coarse grid (e.g. 32x32 around the face only) or only when the controls change by more than a
   threshold; vectorise; cache allocations; never read the field back; no glFinish. The warp output
   must stay the same within 1 level (report max/mean diff vs the current output on hush t=4, indoor
   t=3, mother_child t=3 at slim 1 / eyes 1), and all `tools/test_a.py` checks must still pass.
3. Set playback resolution back to >= 540 short side (720 if real time holds) and re-measure the
   playback table from your report (hush + vertical; retouch off / 0.5 / 0.5+slim+eyes), plus export
   fps with `tools/bench_speed.py samples/asian_hush_48036.mp4` with retouch 0.5 and slim 1 / eyes 1
   (add a CLI/bench flag for reshape if needed).
Acceptance: playback 1.00x +- 2%; dropped <= 15% for retouch+slim+eyes on the vertical clip at
>= 540 short side; export with slim within 15% of export without slim.
Verify: unit, golden, `tools/test_a.py`, `tools/test_ui.py`, `tools/run_all_tests.py`.
Report < 30 lines with the profile, diffs and the before/after tables.
