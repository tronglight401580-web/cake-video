# Stream A follow-up 6: fast onset + a working stability criterion

Rules unchanged (`docs/CODEX_PARALLEL_RULES.md`). This worktree is now at main (2bbe985), which
includes stream A (warp, order 250) and stream B (shine 350, teeth 450). A is accepted; two issues
remain, from `tools/results/*_warp_metrics.csv` (A5):

## 1. Slow onset (must fix)
At clip start the applied jaw displacement ramps slowly: hush reaches steady strength after ~30
frames, indoor after ~70 (0.02 -> 1.89 px). The appear fade is only 8 frames, so something else is
slow (field EMA alpha 0.12, the face-local geometry EMA, the yaw weight, or their product).
- Log per frame: appear fade, yaw weight, smoothed geometry state, field EMA alpha, applied jaw px.
  Report which term causes the ramp.
- Fix: on a new track / reset / cut, initialise the geometry smoothing and the field history from
  the current frame (no ramp from zero), and let the field EMA follow faster while the appear fade
  is < 1 (the fade already hides the onset). Keep the heavy smoothing for steady tracking.
- Target: applied strength reaches >= 90% of its frame-30..119 median within 10 frames of the face
  appearing, on hush and indoor - unless the yaw weight itself is < 0.9 then (report the yaw values;
  a genuinely turned face may stay weaker, that is correct behaviour).
- Do not lose the A5 steady-state stability (jaw step p95 <= 0.8%, eye <= 1.1% after onset).

## 2. Stability criterion in `tools/test_a.py` (replace the A5 one that had no eligible frames)
The "fade-free frames" rule excluded every frame because yaw weight < 1 counted as fade. New rule:
exclude only frames where the APPEAR fade < 1 (and the 2 frames after); yaw weight stays in - it is
what the viewer sees. On the applied jaw px and eye magnification (detector-free, per face):
- step p95 |m_t - m_{t-1}| / median(m) <= 2%
- high-pass breathing: std(m - centred 15-frame moving average) / median(m) <= 2%
  (a slow change over seconds, e.g. a head turn, is not breathing; document this in a comment)
- the onset target from item 1.
Keep the detector-based checks with the noise-floor limits from A5, and every other check.
`tools/test_a.py` must exit 0 at the end.

Also regenerate `tools/results/a_compare.mp4` (same layout as A5) and verify it with ffprobe.
Verify: unit, golden, `tools/test_a.py`, `tools/test_b.py`, `tools/test_ui.py`. Report < 30 lines.
