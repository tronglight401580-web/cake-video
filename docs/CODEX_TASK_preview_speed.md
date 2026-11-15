# Preview playback is slow-motion: make it play at real time

Rules: `docs/CODEX_PARALLEL_RULES.md`, worktree `D:\cake-wt\prep` (at main). No commits. Export
output must stay bit-identical (golden). Rule override for this task: you MAY run
`tools/test_ui.py`, `tools/run_all_tests.py` and benchmarks; nothing else runs meanwhile.

**This is an implementation task. A previous attempt stopped after inspection with no code
changes - that is not acceptable. Implement steps 1-7, measure, iterate. Stop only for a concrete
blocker you cannot solve, and then name it exactly.** Notes from that attempt, already handled:
- `luts/black_gold.cube` etc. were missing in this worktree; they are now generated (`python -m cake
  build-luts`), so `tools/test_ui.py` can run.
- Skipped frames must still advance the analyzer and the renderer's temporal state (One-Euro
  landmarks, warp field history, segmentation keyframes). Suggested: a cheap "advance" path that
  feeds the analysis result / landmarks to the stateful parts without the full-res render, or render
  skipped frames at a tiny size - pick and document.
- Pipelined readback exists only for the NV12 export path; step 4 is optional - an async RGB PBO
  path for the preview is welcome if cheap, otherwise skip it and rely on steps 2, 3, 5, 6.

## Problem (user report: "播放速度慢")
`cake/ui/engine.py` `_play_step` is fully serial and by design "if rendering is slower we simply
play slower": decode (`next(dec_iter)`) -> wait for the analyzer result -> synchronous render with
readback -> two QImage conversions (output + original) -> emit, one frame at a time, at 720p
(`PREVIEW_SHORT`), `LOOKAHEAD = 6`. Export reaches 40-50 fps at 720p with retouch because it uses a
decoder thread, analyzer pool look-ahead and `renderer.render(..., pipelined=True)`; the preview
uses none of that, so any frame that takes > 1/fps plays in slow motion.

User's exact case: retouch ON + slim ON, source at the default upload resolution of a phone video
(treat as 1080x1920 vertical; also check 4K). This case is the primary acceptance target.

## Goal
Playback runs at the clip's real frame rate (wall clock) in every configuration; when the machine
cannot keep up, frames are DROPPED (display skips) instead of slowing down. Paused / single-step /
seek still show the exact full-quality frame.

## Required changes (minimal, inside `cake/ui/` and `cake/core/config.py`; report anything else)
1. Measure first: per-frame time split (decode wait, analyzer wait, render, readback, QImage/emit)
   for retouch 0, retouch 0.5, retouch 0.5 + slim 1 + eyes 1, on `samples/asian_hush_48036.mp4`
   and one 1080x1920 vertical sample (and a 4K source if one exists). Report the table.
2. Decode on a background thread with a bounded queue (bigger look-ahead, e.g. 2x fps frames) so
   the analyzer pool always has frames submitted ahead of display.
3. Real-time scheduler: frame due time from the wall clock; if a frame is already late, skip it
   (still submitted to the analyzer so tracking/smoothing stays continuous - check what the
   analyzer and the One-Euro / warp temporal smoothing need when renders are skipped, and keep
   them correct). Never render a frame that will be late anyway.
4. Use the pipelined readback path for playback (as export does) where it helps.
5. Avoid per-frame waste: convert the original-side QImage only when the compare view needs it,
   reuse buffers.
6. If still below real time with retouch on: lower the PREVIEW resolution during playback only
   (e.g. short side 540), full 720 when paused. Make it a config constant.
7. Show the achieved display fps and dropped-frame count in the existing status/ms readout.

## Acceptance
- Playback wall-clock speed = 1.00x +- 2% over 10 s for all configurations in step 1 (frames may
  drop; report dropped %). Target dropped frames: 0% with retouch off, <= 15% with retouch +
  slim on hush.
- Paused frame identical to before the change (compare a still at t=4 s via the engine).
- `tools/test_ui.py`, unit, golden, `tools/run_all_tests.py` pass.
Report < 30 lines: before/after table (fps achieved, dropped %, time split).
