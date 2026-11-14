# Refactor step 2c: architecture doc, dependency manifest, final regression

Context: `docs/CODEX_TASK_refactor.md`; steps 0-2b are done (read the current code, not the plan,
when they differ). Do not change behaviour in `cake/` except what is listed here.

## 1. `docs/ARCHITECTURE.md` (Chinese, ~200-300 lines, accurate to the CURRENT code)
- 模块地图: every package (core, io, color, analysis, render, render/passes, pipeline, ui, cli) -
  responsibility, key classes/functions, who depends on whom (dependency direction rules: ui ->
  pipeline -> render/analysis -> color/io -> core; core depends on nothing).
- 管理总线: Recipe (fields, metadata, versioning/legacy migration, where it flows), pass registry
  (Pass interface, stage face/frame, order numbers table incl. reserved 250 for warp, texture slot
  names and who reads/writes them), event bus (topics, payloads, Qt bridge), config centre (every
  env var and tunable with default).
- 数据流: one frame through export (decoder -> analyzer -> set_face/maskbuild -> passes ->
  pipelined NV12 readback -> encoder) and through preview.
- 并行开发约定: which files a new feature owns, which shared files it may touch (only Recipe +
  its own pass + optional ui metadata), how to add tests, how to run golden/regression, how to
  record a new golden after an intentional output change (`tools/golden.py record` + note why).
- **Worked example "如何新增一个效果"**: actually implement a tiny demo pass
  `cake/render/passes/demo_tint.py` (order 650, adds a configurable colour tint, disabled unless a
  new Recipe field `demo_tint` (default 0) > 0, field has metadata so the UI shows a slider) and
  walk through it in the doc. Golden must stay identical (default 0 = disabled). Add a unit test
  that enabling it changes the output and disabling it restores bit-identical output.
## 2. Dependency manifest
`requirements.txt` (pinned to the versions installed now: `python -m pip freeze` filtered to what
`cake/` and `tools/` import) and `pyproject.toml` (project metadata, Python >=3.12, console script
`cake = cake.__main__:main`, optional extras `[ui]`, `[convert]` for tensorflow-cpu/tf2onnx).
Mention model downloads (README already lists URLs).
## 3. README
Replace outdated module paths in README with the new layout (short section pointing to
ARCHITECTURE.md). Keep user-facing usage text.
## 4. Final regression (report result lines)
golden check · tests/run_unit.py · tools/test_ui.py · tools/run_all_tests.py (to completion) ·
tools/test_refcolor.py · tools/bench_speed.py samples/street_mixed_1227.mp4 (fps).
Final message < 30 lines.
