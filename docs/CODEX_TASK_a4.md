# Stream A follow-up 4: replace the temporal test with a geometry-aware one (no algorithm change)

Rules unchanged (`docs/CODEX_PARALLEL_RULES.md`). Product-owner review of A3: ACCEPTED as the
algorithm (linear strength, jaw -3.05/-3.85%, eyes +3.66/+5.54%, slider 0.5 = 44-63% of 1.0,
ripple ratios ~0.99, IoU >= 0.986, far pixels identical, golden identical, 0.33 ms, 25/25 unit,
review image looks clean). Do NOT change `warp.py` behaviour in this task.

## Why the temporal check changes
`tools/flicker.py` compares pixel-aligned frame differences of processed vs original. That is right
for colour/retouch flicker, but a geometric warp moves edges, so whenever the face moves the
difference is non-zero even for a perfectly stable warp - your diagnostic proved it (fixed field ->
shimmer p95 5.58, higher than the real run). The "<= 1.0 face shimmer" criterion from A/A2/A3 is
therefore invalid for the warp pass and is retired for warp only (product-owner decision,
2026-11-14). Keep `flicker.py` unchanged; keep using it for colour/retouch passes.

## New temporal criteria (in `tools/test_a.py`, hush frames 0-119, and indoor 0-119)
Render slim 0.7/eyes 0.5 and slim 1.0/eyes 1.0 vs slim=eyes=0 with otherwise identical settings.
Run the landmarker on BOTH outputs every frame.
1. Warp-strength stability ("breathing"): per frame r_t = jaw width(warped) / jaw width(unwarped)
   (234-454, also 132-361) and e_t = eye width ratio. Report mean, std and p95 of |r_t - r_{t-1}|.
   Pass: p95 |r_t - r_{t-1}| <= 0.004 and std(r_t after removing a linear trend) <= 0.006, same for
   e_t with 0.006 / 0.010. Also compute the same statistic for two runs of the UNWARPED render
   against each other's landmarks (detector noise floor) and report it next to the numbers.
2. Shape jitter not added: landmark jitter of the warped output (frame-to-frame, global motion
   removed) <= unwarped output's +20% (you already have this - keep).
3. Outside-face flicker: flicker.py-style delta restricted to pixels farther than 1.3*R from every
   control point must be exactly 0 (warp touches nothing there).
4. Write a side-by-side review video `tools/results/a_compare.mp4` (left unwarped, right slim 1.0 /
   eyes 1.0, hush 0-119 then indoor 0-119, labelled, h264, <= 1280 px wide) so the owner can watch
   for breathing by eye; also save its 3 worst frames (largest |r_t - r_{t-1}|) as
   `tools/results/a_worst.jpg`.
Keep every other existing check. Verify: unit, golden, `tools/test_a.py`, `tools/test_ui.py`.
Report < 30 lines with all numbers incl. the noise floor.
