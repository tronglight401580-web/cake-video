# Stream B: shine (oily skin) removal + teeth whitening

Rules: `docs/CODEX_PARALLEL_RULES.md` (work only in `D:\cake-wt\b`, no commits, feature OFF =>
golden bit-identical, don't run run_all_tests/bench). Read `docs/ARCHITECTURE.md` - in particular
the NEW mechanisms you must use: Recipe sections (`@register_section`), landmark regions
(`@register_region`, `frame_ctx.region(name)`), pass registry (`@register_pass`).
You own ONLY new files: `cake/render/passes/shine.py`, `cake/render/passes/teeth.py`,
`cake/analysis/regions_teeth.py` (or put the region in teeth.py if imports allow - processes must
still register it in workers: check how regions are discovered in worker processes), their tests in
`tests/`, `tools/test_b.py`. Do not edit core/renderer/analyzer/ui files; if discovery needs an
import line in a package `__init__`, that single line is allowed - report it.

## 1. Shine removal (去油光) - pass order 350 (after heal 300, before retouch 400)
Section `shine` with `amount` (0..1, default 0, label 去油光, ui group 人像精修).
Within the skin (use the existing "skin" or smoothing mask slot): find specular highlights =
luminance clearly above the local skin base (half-res blur of skin-only pixels, like heal's
SKINDOWN/BLUR4 approach - your own textures) AND low saturation (shine is whitish). Reduce them:
pull the colour toward the local skin base, keeping some highlight (never flatten fully: max 70%
at amount 1) with soft thresholds (smoothstep) so there are no edges. Enabled only when amount > 0
and a face mask exists.

## 2. Teeth whitening (牙齿美白) - region "teeth" + pass order 450 (after retouch, before grade)
Section `teeth` with `amount` (0..1, default 0, label 牙齿美白).
Region: polygon of the INNER lip contour (MediaPipe FaceMesh inner-lip indices
78,191,80,81,82,13,312,311,310,415,308,324,318,402,317,14,87,178,88,95), filled, lightly feathered.
Pass: inside the region, only pixels that look like teeth (fairly bright, low-to-moderate
saturation, not red like tongue/gums: e.g. L above a threshold relative to the mouth region's
median, hue not in the red band) -> reduce yellow (shift b* toward 0 in a gamma-safe way) and lift
lightness slightly; soft weights; amount scales it. Must not touch lips/skin outside the region.

## Tests (`tools/test_b.py` + unit tests)
- Golden identical with defaults (both 0).
- Shine: `samples/asian_hush_48036.mp4` t=4 and `samples/asian_indoor_48688.mp4` t=3: with amount
  0.8 the 99.5th-percentile luminance inside the face skin drops and the count of "specular"
  pixels (L > skin median + X and low saturation) drops by >= 40%; non-skin pixels change < 0.5
  levels mean.
- Teeth: `samples/asian_mother_child_48689.mp4` t=3 (mother smiling, teeth visible): with amount
  0.8 mean b* (yellow) of detected teeth pixels decreases by >= 3 and L increases; pixels outside
  the teeth region change < 0.5 levels mean (excluding a 3 px feather band).
- Timing: GPU time per pass at 1080x1920 measured with glFinish around run() over 50 frames
  (report ms; target <= 1.5 ms each).
- Review image `tools/results/b_review.jpg`: 2x crops before/after for shine (forehead/nose) and
  teeth.
Verify: `python tests/run_unit.py`, `python tools/golden.py check`, `python tools/test_b.py`,
`python tools/test_ui.py` (controls appear). Report < 35 lines.
