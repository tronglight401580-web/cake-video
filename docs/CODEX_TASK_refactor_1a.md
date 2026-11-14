# Refactor step 1a: move io/ and color/ modules + centralise configuration

Context: `docs/CODEX_TASK_refactor.md` (overall plan). Phase 0 (golden reference) and the core
skeleton (`cake/core/{config,recipe,registry,bus}.py`) are done and committed. This run does ONLY
the mechanical part below. Do NOT touch `cake/gpu.py`, `cake/shaders.py` (another run splits them
next) and do NOT start Phase 2.

## Do
1. Move (git mv is fine, or copy + delete) with **thin re-export shims at the old paths**:
   - `cake/probe.py`, `cake/media.py` -> `cake/io/probe.py`, `cake/io/media.py`
   - `cake/cube.py`, `cake/looks.py`, `cake/styles.py`, `cake/refcolor.py` -> `cake/color/...`
   A shim is e.g. `from .io.media import *  # noqa` plus explicit re-export of private names that
   other code/tools import (grep `tools/`, `tests/`, `cake/` for `from cake.media import _x` etc.).
   Monkeypatching used by tools (e.g. `cake.pipeline.Encoder = ...`, `P.yuv_capable = ...`) must
   keep working - check `tools/golden.py`, `tools/bench_speed.py`, `tools/check_yuv_path.py`,
   `tools/profile_*.py` still behave.
2. Centralise configuration in `cake/core/config.py`: every `os.environ` read (CAKE_SEG,
   CAKE_ANALYZER, CAKE_YUV, QT vars excluded), every path constant (ROOT, models, luts, styles,
   presets file) and every tunable (ANALYSIS_SHORT, seg_every default, worker count default,
   PREVIEW_SHORT, LOOKAHEAD, encoder argument tables) is defined there and imported by the modules
   that use it. Values must stay identical. `grep -rn "os.environ" cake/` must only hit config.py
   (and ui code setting QT_* for offscreen tests if any).
3. Inside moved modules, use the new package-relative imports.

## Verify (all must pass; report the result lines)
- `python tools/golden.py check` - all 5 PASS (self-noise is 0, so expect mean 0 / max 0)
- `python tests/run_unit.py`
- `python tools/run_all_tests.py` (≈10 min; long timeout; run it to completion)
- `python tools/test_refcolor.py`
Report (< 30 lines): moved files, config constants moved, the verification result lines, anything
you could not do. Never weaken a test.
