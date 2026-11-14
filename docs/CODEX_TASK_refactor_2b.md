# Refactor step 2b: split the UI + the Recipe end to end + Qt bus adapter

Context: `docs/CODEX_TASK_refactor.md`. Done & committed: golden (self-noise 0), core bus skeleton,
1a, 1b (render passes), 2a (analysis/, pipeline/). This is the widest step: the goal is that ONE
parameter object (`cake.core.recipe.Recipe`) flows UI -> presets -> per-clip settings -> preview
engine -> export -> renderer, so preview and export can never disagree, and a future feature only
adds Recipe fields + a pass.

## 1. Recipe end to end
- Recipe covers everything the user can set today: style, strength, retouch level, spots (None =
  follow level), eyes (None = follow level), keep_moles, debug overlay (preview only - never
  exported), skin_protect_scale. Field metadata: Chinese label, min/max/step/default, `ui` group
  ("风格" / "人像精修"), `preview_only` flag. Version number; `from_dict` accepts older versions.
- `Recipe.from_legacy(d)` migrates today's settings dicts (`{"style","strength","retouch",
  "opts":{"spots","under","keep_moles","debug"}, ...}`) - used when loading old presets.json and
  old per-clip data.
- Renderer: `Renderer.apply_recipe(recipe, stamp_rgba=None)` sets style/strength/retouch/skin
  scale (old setters stay as wrappers). `FrameContext.recipe` becomes the Recipe; passes that need
  the Style read `fc.style`. Golden must stay bit-identical.
- `grade_video(inp, out, recipe=None, *, ...)`: when `recipe` is given use it; the old positional /
  keyword parameters keep working (build a Recipe from them). Same for `compare_still/compare_face`.
- Preview engine: `PreviewEngine.set_recipe(recipe)`; `set_params(**kw)` stays as a wrapper.
- CLI: move argument parsing to `cake/cli.py`, build a Recipe from args, `cake/__main__.py` stays a
  thin entry. All current commands/flags unchanged (`grade` incl. batch and `--ref`, `still`,
  `face`, `refstyle`, `ui`, `styles`, `probe`, `build-luts`).

## 2. UI split (`cake/ui/app.py` 848 lines ->)
```
ui/main_window.py   MainWindow: layout, wiring, shortcuts, drag & drop
ui/preview_view.py  PreviewView (split compare widget)
ui/queue_panel.py   queue list, thumbnails, per-clip Recipe storage
ui/param_panel.py   style combo + reference-colour button/thumbnail + presets section, and the
                    numeric sliders/checkboxes GENERATED from Recipe field metadata (so adding a
                    Recipe field with metadata makes a control appear). Keep current behaviour:
                    spots/eyes follow retouch until touched, value labels, debounce.
ui/presets.py       load/save presets (Recipe dicts, legacy migration), PRESETS_FILE
ui/export_worker.py ExportWorker (jobs carry a Recipe)
ui/bus_qt.py        QtBusBridge(QObject): subscribes to cake.core.bus topics and re-emits Qt
                    signals on the GUI thread (status, progress, error); main window + export use it
ui/automation.py    the --screenshot / --play / --export-test driver
ui/app.py           shim: re-export MainWindow, main, load_presets, save_presets, PRESETS_FILE ...
```
`tools/test_ui.py` monkeypatches `cake.ui.app.PRESETS_FILE` and calls `win._export`,
`win.settings()`, `win.apply_settings()`, `win._apply_preset()`, `win._apply_to_all()`,
`win.style_box`, `win.strength`, `win.retouch`, `win.queue`, ... Keep these names working
(compat properties/wrappers on MainWindow are fine), so the existing UI test runs unmodified.
`settings()` may now return a Recipe-backed dict; `apply_settings()` must accept both.

## 3. New tests
- `tests/test_recipe_flow.py`: legacy preset dict -> Recipe -> dict round trip; preview and export
  configure an identical renderer state for the same Recipe (compare style name, strength,
  retouch/spots/under/mole_keep/debug, skin_protect_scale on two Renderers set up via the engine's
  and the export's code paths); `debug` never reaches export.
- A unit test that a Recipe field with metadata produces a control in ParamPanel (offscreen Qt).

## Verify (all must pass, report result lines)
`python tools/golden.py check` (mean 0/max 0) · `python tests/run_unit.py` ·
`python tools/test_ui.py` (unmodified) · `python tools/run_all_tests.py` (≈10 min, to completion) ·
`python tools/test_refcolor.py` · offscreen screenshot
`python -m cake ui samples/asian_hush_48036.mp4 --t 4 --screenshot tools/results/ui_after_2b.png`
(set QT_QPA_PLATFORM=offscreen and QT_QPA_FONTDIR=C:/Windows/Fonts for that command).
Report (< 40 lines): file map, Recipe fields, verification lines, screenshot path, open issues.
Never weaken a test.
