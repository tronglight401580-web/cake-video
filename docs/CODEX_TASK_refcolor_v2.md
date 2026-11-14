# Follow-up: reference colour transfer v2 - transfer the GRADE, not the scene

Read `docs/CODEX_TASK_refcolor.md` (v1 spec) and your v1 code (`cake/refcolor.py`,
`tools/test_refcolor.py`). v1 works mechanically (all regressions pass, thank you for not weakening
the asserts) but the design is wrong for what users want:

**Diagnosis (from the review image):** a night street reference applied to a daylight beach made
the beach dark and blue. Full MKL / global Lab statistics transfer moves the *scene content*
(exposure, night vs day), not the *colour grade* (teal shadows + orange highlights). Users expect
"make my video look graded like this photo", keeping their own exposure. Also the v1 recovery test
compared a night reference to a day target, so it could not measure grading accuracy.

## Algorithm v2 (default `method="grade"`; keep v1 as `method="mkl"`)
Work in Lab on the same non-skin pixel selection as v1 (source frames and reference).
1. **Tone (L)**: keep the source exposure. Partial CDF matching of L toward the reference with
   strength 0.35, then constrain: mean L shift <= 6, contrast (std) gain within [0.85, 1.25],
   monotonic curve (enforce), endpoints fixed (L=0 -> 0, L=100 -> 100). Implement as a 1D curve
   (256 samples) applied before chroma.
2. **Chroma grade by luminance band**: three soft bands over the source L (after step 1):
   shadows / mids / highlights with smooth weights (e.g. raised-cosine centred at L = 20, 50, 80,
   widths so they sum to 1). For each band compute the weighted mean (a, b) of source and of
   reference (reference bands use the reference's own L) -> offset_band = mean_ref - mean_src,
   clipped to |offset| <= 20. Also chroma scale per band = (weighted std of chroma ref / src),
   clipped to [0.6, 1.5]. Apply per pixel: (a, b) -> mean_src_band + scale_band * ((a, b) -
   mean_src_band) + offset_band, blended by the band weights. This is a split-toning / grade
   transfer, robust to different scene content.
3. Global LUT = 33^3 grid through (1) then (2), back to RGB, soft-clip, clip. Skin LUT as in v1
   but with `skin_follow` default **0.2** (L follows tone curve at 0.7 as before).
4. Style default `skin_protect` **1.0** (was 0.8).

## Tests (`tools/test_refcolor.py`, replace v1 tests 1-2, keep 3-4)
1. **Same-scene recovery (grading accuracy)**: reference = `samples/beach_daylight_1221.mp4`
   frame at t=8 s graded with `teal_orange`; target = the same clip at t=4 s.
   A = v2 ref style, B = real `teal_orange`, C = ungraded. Assert dE76(A,B) < 0.6 * dE76(C,B)
   on non-skin pixels. Also run the same with `film_warm` and report (assert same ratio).
2. **Cross-scene sanity**: reference = `samples/street_mixed_1227.mp4` t=3 graded `teal_orange`
   (night); target beach t=4. Assert non-skin mean L changes by <= 8 (day stays day), and the
   sign of the shadow-band and highlight-band (a, b) shifts applied to the target matches the sign
   of the reference's own shadow/highlight (a, b) offsets relative to neutral (report the numbers).
   Report the same numbers for `method="mkl"` (no assert) to show the difference.
3. **Skin protection**: as v1 (neon reference -> hush), now expect >= 50% reduction of face-skin
   chroma shift with protection, non-skin shift unchanged within 10%.
4. `python tools/run_all_tests.py` all PASS.
5. Update `tools/results/refcolor_review.jpg`: row per test, columns reference | original |
   v2 no protection | v2 protection | (rows 1-2) real target style | (row 2) mkl for comparison.

## Rules
Do not weaken thresholds; if missed, report the real numbers and your diagnosis. Keep the public
API (`build_reference_style`, CLI, UI) unchanged except the new `method` parameter (CLI
`--method grade|mkl`). Final message < 40 lines: changes, test numbers, review image path.
