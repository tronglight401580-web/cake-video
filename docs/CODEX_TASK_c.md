# Stream C: per-shot reference colour transfer

Rules: `docs/CODEX_PARALLEL_RULES.md` in the main repo applies (you work only in `D:\cake-wt\c`;
no commits; golden must stay identical with the feature off; don't run run_all_tests/bench).
You own: `cake/color/refcolor.py`, `cake/render/passes/grade.py`, `cake/pipeline/export.py`
(minimal changes), `cake/cli.py` (one flag), `tools/test_refcolor.py`, new `tools/test_pershot.py`.
Do NOT edit `cake/core/recipe.py` (another stream is changing it) - per-shot data lives in the
reference style JSON, not in the Recipe.

## Problem
`build_reference_style` fits ONE transfer for the whole clip. A clip with several shots (indoor ->
outdoor) gets a compromise LUT. Fit one LUT per shot instead.

## Do
1. Shot detection on analysis-size frames (reuse the frames already sampled, but sample densely
   enough to find cuts: e.g. every 2nd frame at 180p): colour-histogram distance (e.g. chi-square on
   HSV 3D histograms) + threshold + min shot length 0.5 s; return frame ranges. Expose
   `detect_shots(clip) -> list[(start_frame, end_frame)]`.
2. `build_reference_style(..., per_shot: bool = False)`: when True fit the v2 "grade" transfer
   (and skin LUT) per shot (statistics from frames of that shot only; if a shot has too few
   usable pixels fall back to the clip-wide fit). Write `luts/ref_<name>_s<k>.cube` /
   `_s<k>_skin.cube`; the style JSON gets `"shots": [{"start": f0, "end": f1, "lut": ..., "skin_lut":
   ...}, ...]` (extend the Style dataclass in `cake/color/styles.py` with an optional `shots` list -
   that small edit is allowed). Default False = today's behaviour.
3. Grade pass: if the style has shots, pick the LUT pair for the current frame index; cross-fade
   linearly over 8 frames after each cut start (mix of previous and next LUT outputs) to avoid a
   hard colour jump if the detected cut is a frame off. Frame index must be the absolute clip frame
   (account for `start` offset in grade_video and the preview engine - read how frame indices flow
   and report what you changed). Preview engine (`cake/ui/engine.py`) only if needed for correct
   indices - minimal.
4. CLI: `refstyle ... --per-shot` and `grade ... --ref X --per-shot`.

## Tests (`tools/test_pershot.py`)
- Build a test clip: first 3 s of `samples/asian_indoor_48688.mp4` + first 3 s of
  `samples/beach_daylight_1221.mp4` (scale/pad both to 720x1280 portrait, concat with ffmpeg into a
  temp file). Detect shots: exactly 2, cut within ±2 frames of the true boundary.
- Reference = frame of `samples/street_mixed_1227.mp4` graded with `teal_orange`. Compare per-shot
  vs single-LUT on each shot: per-shot must be at least as close to "that shot graded with
  teal_orange directly" as single-LUT for BOTH shots (CIE76 on non-skin pixels), report numbers.
- No flicker inside a shot: frame-to-frame mean abs difference of the graded output inside a shot
  must equal (±0.2 levels) that of the ungraded source.
- `tools/test_refcolor.py` still passes; golden identical; unit tests pass.
