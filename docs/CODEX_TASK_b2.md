# Stream B follow-up (small): finish the open items

Rules unchanged (`docs/CODEX_PARALLEL_RULES.md`). Product-owner review of `tools/results/b_review.jpg`:
shine removal visibly works on the hush clip (nose/forehead). The indoor clip is evenly lit and has
almost no real specular shine - its broad soft forehead highlight is correctly left alone, so the
"specular pixels -40%" criterion is the wrong test for that clip. Decisions:

1. `tools/test_b.py` shine: keep ">= 40% fewer specular pixels" for `asian_hush_48036` only. For
   `asian_indoor_48688` replace it with a no-damage check: mean |change| on face skin <= 1.5 levels
   and p99.5 luminance change <= 3 levels. Add a comment with this rationale (review 2026-11-14).
2. Teeth: use the mouth-region-relative brightness threshold the spec asked for (relative to the
   median L of the teeth region pixels) instead of the absolute one; re-check the teeth numbers
   (b* decrease >= 3, L increase, outside-region change < 0.5).
3. Measure GPU time per pass at 1080x1920 over 50 frames with glFinish (report ms each).
4. Fix `tools/results/b_review.jpg` layout: row 1 hush shine before/after (2x crop forehead+nose),
   row 2 indoor before/after (same), row 3 mother_child MOTHER's mouth before/after (2x crop showing
   teeth), each tile labelled.
5. Add an explicit check to `tools/test_b.py` (or a unit test) that the 去油光 / 牙齿美白 controls
   exist in the parameter panel.
Verify: unit, golden, `tools/test_b.py`, `tools/test_ui.py`. Report < 25 lines.
