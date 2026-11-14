# Stream D: competitor comparison tools + 4 new styles

Rules: `docs/CODEX_PARALLEL_RULES.md` in the main repo applies (work only in `D:\cake-wt\d`; no
commits; golden identical; don't run run_all_tests/bench). You own: new files in `tools/`,
`styles/*.json` (new ones only), `cake/color/looks.py` (ADD new look functions + LOOKS entries
only; do not change existing looks). Generate LUTs with `python -m cake build-luts`.

## 1. Comparison tools (for comparing with PixCake / WinkStudio results)
- `tools/export_frames.py CLIP --times 1,3,5 --out DIR` -> lossless PNG frames at source
  resolution (these get retouched in other apps).
- `tools/compare_reference.py ORIGINAL.png OURS.png THEIRS.png [--out sheet.jpg]`:
  metrics on face-skin pixels (skin mask via `cake.analysis` on ORIGINAL; same mask for all three):
  mean L change vs original, mean hue / a,b change, skin smoothness = high-frequency energy
  (luma minus gaussian sigma 2) relative to original, "spot count" proxy = number of small dark
  blobs (DoG blob detection) in skin; and on non-skin pixels mean CIE76 vs original. Print a table
  OURS vs THEIRS, and save a side-by-side sheet (3 full images + 3 face crops at 2x).
- A short `docs/COMPARE_GUIDE.md` (Chinese): how to export frames, retouch them in the other app,
  and run the comparison.
Test: run it with THEIRS = our own output re-graded with a different style (no real competitor
image available here) just to prove it works end to end.

## 2. Four new styles (follow the Douyin rules in README "抖音适配规则")
Use the existing primitives in looks.py (white_balance, exposure, contrast, hue_adjust,
split_tone, saturation, soft_clip, levels, protect_skin). Starting points (tune within about ±30%
only if the checks below fail):
| name / title | look recipe | effects JSON |
|---|---|---|
| `japanese_fresh` 日系清新 | exposure +0.15; WB (0.97,1,1.03); contrast 0.92 (pivot 0.5); greens: shift +10°, sat 0.85; blues sat 0.9; saturation 0.88; shadows tint (0,0.02,0.03), highlights (0.01,0.01,0); levels black 0.03 white 0.995; protect_skin 0.6 | bloom 0.10 thr 0.80; vignette 0; grain 0.015 size 1.8 |
| `hk_retro` 港风 | WB (1.06,1,0.90); contrast 1.25 (pivot 0.45); greens shift -15° sat 0.8; reds (352°) sat 1.15; split shadows (-0.01,0.04,0), highlights (0.06,0.03,-0.04); saturation 1.05; black 0.03 tint (0,0.01,0); protect_skin 0.6 | bloom 0.18 tint (1,0.45,0.25) radius 28; grain 0.035 size 2.2; vignette 0.08 |
| `creamy` 奶油肌 | exposure +0.12; WB (1.02,1,0.97); contrast 0.95; saturation 0.9; highlights (0.03,0.02,-0.01); soft_clip(0.85,1.06); black 0.02; protect_skin 0.8 target 16 max_sat 0.42 | bloom 0.12 thr 0.75; soften 0.10; vignette 0 |
| `black_gold` 黑金 | hue bands: blue/cyan/green/purple sat 0.1; orange/yellow (30-60°) sat 1.2 shift toward 40°; contrast 1.3; black 0.0; protect_skin 0.7 | bloom 0.20 tint (1,0.8,0.5) thr 0.7; vignette 0.12 |
Checks with `python tools/eval_looks.py` on samples beach_daylight_1221, street_mixed_1227,
asian_hush_48036, neon_night_1230 (t=3): for each new style: overall brightness >= original - 1;
white p99 >= 95 (if the original's p99 >= 95); corner/centre ratio drop <= 0.06; mean skin hue
within 12-26°. Report the table. Make one review sheet:
`python -m cake still samples/asian_hush_48036.mp4 --t 4 -s japanese_fresh -s hk_retro -s creamy
-s black_gold -o tools/results/new_styles.jpg` (and the same for beach_daylight at t=4).
Golden identical; unit tests pass.
