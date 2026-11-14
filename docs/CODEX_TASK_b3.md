# Stream B follow-up 3: tune shine removal (teeth / timing are done)

Rules unchanged. State after the interrupted follow-up 2 (`docs/CODEX_TASK_b2.md`):
- teeth now uses the mouth-relative threshold: b* -4.62, L* +1.65, outside 0.018 -> PASS. Keep.
- timing: shine 0.54 ms, teeth 0.91 ms -> OK.
- shine on hush: specular-pixel ratio 0.879 (target <= 0.60) -> too weak.
- shine on indoor (no real shine, broad soft highlight): p99.5 luminance changed 7 levels
  (target <= 3) -> it wrongly treats the broad soft highlight as shine.

Both say the same thing: the detector must target SMALL, VERY BRIGHT, LOW-SATURATION specular
spots, and act more strongly on them, while leaving broad soft highlights alone. Suggested approach
(you may improve): band-pass detection (fine-scale blur minus coarse local skin base, like heal's
med/base pair) so only spot-sized bright structure counts; saturation gate; then reduce toward the
local base with up to ~70% at amount 1. Do not touch the specular-pixel definition in the test.

Then finish the open items of `docs/CODEX_TASK_b2.md`: items 1 (test criteria - already partly
done, check), 4 (review image layout) and 5 (controls exist check), if not done yet.
Verify: unit, golden, `tools/test_b.py`, `tools/test_ui.py`. Report < 25 lines with the numbers.
