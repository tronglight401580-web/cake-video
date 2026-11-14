# Refactor: modular architecture with a unified management bus (behaviour must NOT change)

Goal from the product owner: split the project into clear modules that are easy to change, with a
**unified management bus** so several people (or several Codex runs) can later develop features in
parallel without touching each other's files. **Functionality, image output and performance must
stay the same.** Read `README.md` and all of `cake/` first.

The work is split in two phases. Do **Phase 0 + Phase 1** in this run, then STOP and report.
Phase 2 will be a separate run (same spec). Never weaken a test to make it pass.

## Target layout
```
cake/
  core/
    config.py     # ONE place for env flags (CAKE_SEG, CAKE_ANALYZER, CAKE_YUV), paths (ROOT, models,
                  # luts, styles, presets file), and tunables (ANALYSIS_SHORT, seg_every, workers,
                  # PREVIEW_SHORT, LOOKAHEAD, encoder settings). Other modules import from here.
    recipe.py     # Recipe: the single parameter object (see below)
    registry.py   # effect/pass registry (see below)
    bus.py        # event bus (see below)
  io/             probe.py, media.py               (moved from cake/)
  color/          cube.py, looks.py, styles.py, refcolor.py
  analysis/       models.py (MediaPipe/ONNX loading, close), segment.py (seg_gpu + CPU fallback),
                  layers.py (landmark layers / under-eye), analyzer.py (process pool, interpolation,
                  FaceInputs)                       (split of face.py + seg_gpu.py)
  render/
    context.py    # GL context, fullscreen quad, program cache, render-target helpers, PBO readback
    renderer.py   # orchestrator: builds the ordered pass list from the registry + recipe, runs it,
                  # owns readback (RGB / NV12, pipelined)
    passes/       # one module per pass, GLSL next to its pass (inline string or .glsl file):
                  # input (RGB upload / YUV2RGB), maskbuild, heal (skindown+blur4+heal), retouch,
                  # grade (LUT + skin LUT), bloom, finish, output (TOYUV)
  pipeline/       export.py (grade_video), stills.py (compare_still, compare_face)   (Phase 2)
  ui/             main_window.py, preview_view.py, param_panel.py, queue_panel.py,
                  export_worker.py, engine.py, automation.py                         (Phase 2)
  cli.py          argument parsing (Phase 2); cake/__main__.py stays a thin entry
```
**Compatibility shims are mandatory**: old import paths keep working as thin re-exports
(`cake.gpu.Renderer`, `cake.pipeline.grade_video/compare_still/compare_face/_grab_frame/...`,
`cake.face.*`, `cake.media.*`, `cake.styles.*`, `cake.looks.*`, `cake.cube.*`, `cake.refcolor.*`,
`cake.seg_gpu.*`, `cake.probe.*`). All `tools/*.py` must run unchanged.

## The management bus (4 parts)
1. **Recipe** (`core/recipe.py`): dataclass tree, the ONLY representation of processing parameters:
   `Recipe(style: str, strength: float, retouch: RetouchCfg(level, spots|None, eyes|None,
   keep_moles, debug), skin_protect_scale: float, version: int)`; room for future sections
   (e.g. `slimming`). Each field carries metadata (label in Chinese, range, default, step) so a UI
   panel can be generated from it later. `to_dict()/from_dict()` (JSON), `from_legacy(dict)` for
   the current UI settings/preset dict format, `validate()`. Phase 1: add it + tests; Phase 2: make
   UI, presets, per-clip settings, engine, export and CLI all use it.
2. **Pass registry** (`core/registry.py`): `@register_pass(name, order)` on a `Pass` base class:
   ```python
   class Pass:
       name: str; order: int
       reads: tuple[str, ...]; writes: tuple[str, ...]        # named texture slots in FrameContext
       def enabled(self, recipe, frame_ctx) -> bool
       def setup(self, gl, width, height) -> None             # allocate textures / programs once
       def run(self, frame_ctx) -> None
       def release(self) -> None
   ```
   `FrameContext` carries the recipe, frame index, size, face data (FaceInputs) and a dict of named
   textures (e.g. "rgb", "mask", "skin", "healed", "retouched", "graded", "bloom", "out16").
   Passes are discovered by importing `cake.render.passes` (each pass module self-registers);
   a new feature = a new module in `passes/` with its own order number - no edit to renderer.py.
   Orders: input 100, maskbuild 200, (future warp 250), heal 300, retouch 400, grade 500,
   bloom 600, finish 700, output 800 (leave gaps).
3. **Event bus** (`core/bus.py`): small thread-safe pub/sub: `bus.publish(topic, **payload)`,
   `bus.subscribe(topic, fn) -> unsubscribe`; topics: `status`, `progress`, `log`, `error`,
   `frame_stats`. `grade_video` publishes progress/status/log (keep its existing `log=` /
   `progress=` / `cancel=` parameters working by bridging them). Phase 2: UI gets a Qt adapter that
   re-emits bus events on the GUI thread.
4. **Config** (`core/config.py`) as above. No module reads `os.environ` directly any more.

## Phase 0 - golden reference (do FIRST, before moving any code)
Write `tools/golden.py` with `record` and `check` sub-commands. It runs the CURRENT renderer
through `cake.pipeline.grade_video` with a capturing encoder (monkeypatch `cake.pipeline.Encoder`
with a class that stores the raw NV12 frames it receives) for these configs, first 24 frames each:
| id | clip | style | retouch | extra |
|---|---|---|---|---|
| g1 | samples/asian_hush_48036.mp4 | film_warm | 0.5 | |
| g2 | samples/street_mixed_1227.mp4 | teal_orange_portrait | 1.0 | |
| g3 | samples/neon_night_1230.mp4 | ccd | 0 | |
| g4 | samples/asian_mother_child_48689.mp4 | none | 0.5 | spots 1.0, eyes 0.8, remove moles |
| g5 | samples/beach_daylight_1221.mp4 | a reference style built from a frame of street_mixed (use cake.refcolor, fixed name `golden_ref`) | 0 | skin_protect 1.0 |
`record` saves frames to `tools/results/golden/<id>.npz` (compressed) + a JSON manifest.
`check` re-runs and compares per config: max abs diff and mean abs diff over all frames; PASS if
mean <= 0.05 and max <= 2 (8-bit levels; analysis/DirectML may be very slightly non-deterministic -
first run `check` right after `record` on the unchanged code and report the self-noise; if self-noise
exceeds that, report it and use 2x the observed self-noise as the tolerance, documented).
Run `record` now, then `check` once to measure self-noise.

## Phase 1 - core bus + render pass split
1. Create `core/config.py`, `core/recipe.py`, `core/registry.py`, `core/bus.py` (as above).
2. Move `probe.py, media.py` -> `io/`, `cube.py, looks.py, styles.py, refcolor.py` -> `color/`
   with shims at the old paths. Point all env/paths/constants at `core/config.py`.
3. Split `gpu.py` + `shaders.py` into `render/context.py`, `render/renderer.py`,
   `render/passes/*.py`. `Renderer`'s public API stays identical (constructor args, `set_style`,
   `set_retouch`, `set_face`, `render(frame, index, yuv=, pipelined=)`, `flush`, `release`,
   attributes used by tools/UI such as `mask`, `skin`, `face_boxes`, `strength`,
   `skin_protect_scale`). Internally it builds the pass list from the registry each time
   relevant settings change and runs `enabled()` passes in order.
4. `grade_video` publishes on the bus (bridging the old callbacks).
5. Unit tests with **pytest** in `tests/` (pytest is NOT installed and you cannot install it - write
   them pytest-style AND add `tests/run_unit.py` that discovers and runs `test_*` functions without
   pytest): cube read/write round trip, `looks.soft_clip`/`s_curve` monotonic, refcolor Lab<->RGB
   round trip, Recipe to/from dict + from_legacy, registry ordering and duplicate-name error, bus
   subscribe/unsubscribe/thread-safety.
6. Verification, all must pass: `python tools/golden.py check` (all PASS),
   `python tests/run_unit.py`, `python tools/run_all_tests.py`, `python tools/test_refcolor.py`,
   and `python tools/bench_speed.py samples/street_mixed_1227.mp4` (report fps; must be within
   -5% of the 32-33 fps baseline - if slower, find out why).

## Phase 2 (NOT in this run - for reference so Phase 1 leaves room for it)
analysis/ split; pipeline/ export + stills; UI split into the files listed; Recipe used end to end
(UI settings, presets with legacy migration, per-clip settings, engine params, export jobs, CLI);
Qt adapter for the bus; `docs/ARCHITECTURE.md` (module map, the bus, "how to add a new effect pass"
with a worked example of a tiny demo pass added purely as a new file); `pyproject.toml` +
`requirements.txt`.

## Report (final message, < 50 lines)
Phase 0 self-noise numbers; Phase 1 file map (old -> new); every verification command with its
result line; bench fps; anything left undone or any behaviour difference you could not eliminate.
