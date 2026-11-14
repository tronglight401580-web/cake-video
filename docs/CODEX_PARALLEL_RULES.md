# Rules for every parallel Codex stream (read first)

- You work ONLY inside your own git worktree directory (your cwd, e.g. `D:\cake-wt\c`). Never
  read/write `D:\像素蛋糕视频版` or another worktree. `samples/` and `models/` are shared junctions:
  read-only for you.
- Do not commit (the .git of a worktree is outside your sandbox); just leave your changes in the
  working tree. The integrator reviews and commits.
- Touch only the files your task says you own. If you truly must change a shared file, keep the
  change minimal and list it explicitly in your report.
- With your feature OFF (default), output must stay bit-identical:
  `python tools/golden.py check` -> all 5 configs mean 0 / max 0.
- Always run: `python tests/run_unit.py`, `python tools/golden.py check`, plus your own feature
  tests. Do NOT run `tools/run_all_tests.py` or `tools/bench_speed.py` (several streams share one GPU;
  the integrator runs the full regression and benchmarks at merge time).
- Read `docs/ARCHITECTURE.md` for the module map, the Recipe, the pass registry and the bus.
- Never weaken a test to make it pass; report real numbers. Final message < 35 lines.
