# Continue preview_speed2 (previous run hit the usage limit mid-way)

Your previous run already implemented most of `docs/CODEX_TASK_preview_speed2.md` in this worktree
(see `git diff`: `cake/render/passes/warp.py` guard rewrite, `PREVIEW_PLAY_SHORT = 540`,
`tools/bench_speed.py --slim/--eyes`, probe scripts `tools/_speed2_*.py`). The last measurement seen
was hush export with the new bench: "loop 44.4 fps". Do NOT start over. Finish:
1. Confirm the warp pass cost (CPU + GPU) per frame at 1080x1920 and the output diff vs the saved
   baselines `tools/results/speed2_base_*.npy` (max / mean levels; must be <= 1 level).
2. Run the full acceptance from preview_speed2: playback table (hush + vertical; retouch off / 0.5 /
   0.5+slim+eyes) at >= 540 short side with fps, speed and dropped %; export fps with and without
   slim (`tools/bench_speed.py samples/asian_hush_48036.mp4 --retouch 0.5 [--slim 1 --eyes 1]`).
3. Verify: unit, golden, `tools/test_a.py`, `tools/test_ui.py`, `tools/run_all_tests.py`.
4. Delete the temporary `tools/_speed2_*.py` and `tools/results/speed2_base_*.npy` at the end
   unless a test needs them (then move them under `tools/proto/` and say so).
Report < 30 lines with all numbers.
