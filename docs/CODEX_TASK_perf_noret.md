# Perf regression: retouch-off export got 33-46% slower (find and fix)

Rules: `docs/CODEX_PARALLEL_RULES.md`, but your worktree is `D:\cake-wt\prep` (now at main 2bbe985).
No commits. Feature output must stay bit-identical (golden).

**Rule override for this task only (product owner, 2026-11-14):** you MAY and MUST run
`tools/bench_speed.py`, `tools/bench_matrix.py` and `tools/run_all_tests.py`. The parallel rule
against them exists to avoid GPU contention between streams; nothing else runs during this task.
Usage: `python tools/bench_speed.py samples/<clip>.mp4 --retouch 0` (the clip argument is required).
Side note from your previous attempt: the UI test reported a missing `luts/black_gold.cube` in this
worktree - check whether LUTs of the newer styles are generated on demand, and report.

## Evidence (`tools/bench_matrix.py`, config `noret` = `tools/bench_speed.py <clip> --retouch 0`,
style film_warm)
| clip | 07:35 (commit 7ffccf5) | 18:44 (main 2bbe985) |
| street_mixed_1227 | 71.6 fps | 38.7 fps |
| asian_hush_48036 | 128.5 fps | 86.6 fps |
Retouch-ON configs did NOT regress (they got faster), so the cost is in the retouch-off path.

## Steps
1. Re-measure noret on main 3x per clip (median) to confirm it is real, not noise.
2. Bisect over these commits (oldest first): 7ffccf5, ba6a58a, b9d5553, b552b4e, b70d9bc, 82233a8,
   f79d09f, d5e3847, eec757e, f9fd0fc, d77dbea, 6f7823a, dafad09. To get each tree without touching
   git state: `git archive <hash> | tar -x -C _bisect/<hash>` inside this worktree (delete `_bisect`
   afterwards), point it at the shared `samples/` and `models/`, run noret 3x, take the median.
   Report the first commit where noret drops > 10%.
3. Profile that path on main (per-pass GPU time with glFinish, decode/encode/readback, whether
   the analyzer or any face/region/mask work runs when nothing needs it, per-frame allocations,
   sync points). Likely suspects: a pass that is "off" but still runs or allocates, region/mask
   building with retouch 0, the One-Euro/landmark path, YUV or readback changes from the refactor.
4. Fix so that disabled features cost ~0 again. Target: noret within 10% of the 07:35 numbers.
Verify: unit, golden, `tools/run_all_tests.py`, `tools/test_ui.py`, `tools/bench_matrix.py`
(report the full table). Report < 30 lines: culprit commit, root cause, fix, before/after fps.
