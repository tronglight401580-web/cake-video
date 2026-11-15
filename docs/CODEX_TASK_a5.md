# Stream A follow-up 5: finish A4 (it was cut off by the usage limit)

Rules unchanged (`docs/CODEX_PARALLEL_RULES.md`). Read `docs/CODEX_TASK_a4.md` first; its new
temporal checks already run (`tools/results/a4_test.log`). Do NOT change `warp.py` behaviour.
Product-owner review of the A4 numbers: background identical and landmark jitter OK, but the
detector-based ratio steps (hush jaw p95 ~1.3%, eyes ~2%) exceed the guessed limits, and the
reported "noise floor" is 0 because it compared identical renders - useless. Open items:

1. Primary breathing metric, detector-free: log from the warp pass itself, per frame and per face,
   the mean displacement magnitude (px) at the jaw control points and the eye magnification actually
   applied (after fades / guards / smoothing). Report step p95 of |m_t - m_{t-1}| / mean(m) and
   detrended std / mean(m). Pass: step p95 <= 2% and detrended std <= 4% of the mean (yaw/appear
   fades excluded: report how many frames were in a fade).
2. Real detector noise floor: compute the same r_t statistics between the unwarped render and that
   render resampled by a tiny known transform (bilinear, 0.37 px shift + 1.002 scale about the face
   centre). Report it next to the warped numbers. The detector-based checks then pass if they are
   <= max(A4 limit, 1.5 x noise floor); document this in a comment.
3. `tools/results/a_compare.mp4` was left unfinished (no moov atom): write it with ffmpeg (pipe raw
   frames, `-movflags +faststart`), side by side unwarped | slim 1.0 eyes 1.0, hush 0-119 then indoor
   0-119, labelled, <= 1280 px wide, and verify it with ffprobe. Also `tools/results/a_worst.jpg`
   (3 frames with the largest step of metric 1).
Verify: unit, golden, `tools/test_a.py`, `tools/test_ui.py`. Report < 30 lines with all numbers.
