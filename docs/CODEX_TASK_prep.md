# Parallel-development prep: pluggable Recipe sections + landmark region registry

Read `docs/CODEX_PARALLEL_RULES.md` (copy is in the main repo: same text applies) and
`docs/ARCHITECTURE.md`. You own: `cake/core/recipe.py`, `cake/core/registry.py` (if needed),
`cake/analysis/*`, `cake/render/passes/maskbuild.py`, `cake/render/frame.py`,
`cake/render/renderer.py`, `cake/render/passes/demo_tint.py`, `cake/ui/param_panel.py`, `tests/*`,
`docs/ARCHITECTURE.md`, new `tools/new_worktree.ps1`.

## 1. Pluggable Recipe sections
Today every feature adds fields to the single `Recipe` class -> merge conflicts when several
streams work in parallel. Make sections pluggable, same idea as the pass registry:
`@register_section("name")` on a small dataclass (fields with the same metadata format: Chinese
label, range, step, default, ui group, preview_only, `dev_only`). `Recipe` keeps its existing
fields/behaviour exactly (golden identical, old presets/legacy dicts load), and additionally holds
`recipe.sections[name]` (or attribute access `recipe.<name>`) for every registered section,
serialised under `"sections": {...}` in to_dict/from_dict; unknown sections are kept as raw dicts
(forward compatibility), missing ones get defaults. The parameter panel builds controls for every
registered section's fields (grouped by `ui` group). Move the demo tint field into its own section
inside `cake/render/passes/demo_tint.py`, mark it `dev_only=True`; dev-only controls are hidden
unless env `CAKE_DEV=1` (read via `cake/core/config.py`).

## 2. Landmark region registry (for teeth, nasolabial folds, face reshaping...)
Today `analysis/layers.py` draws all landmark-based layers into 4 fixed mask channels, all used.
Add `@register_region("name")` for functions `(faces_landmarks: list[np.ndarray(478,2)], shape)
-> np.ndarray float32 (h, w) in 0..1`. The worker computes every registered region per frame
(analysis resolution) and ships them with `Raw`/`FaceInputs` as a uint8 stack; the renderer
uploads them into "region" textures packed 4 per RGBA texture and exposes them to passes as
FrameContext slots `region:<name>` (texture + channel index), with the same temporal EMA / reset
treatment as the existing mask. Also expose the raw smoothed landmark arrays per face to passes
(`frame_ctx.face.landmarks`) - stream A (face slimming) will need them. With NO regions registered
(default) nothing changes: golden identical, no extra textures, no speed cost.
Add one example region in tests only (e.g. "test_mouth" from the lips landmarks) proving: a test
pass can read `region:test_mouth` and the region follows the face.

## 3. Worktree helper
`tools/new_worktree.ps1 NAME` - creates `D:\cake-wt\NAME` on branch `feat/NAME` from main,
junctions `samples` and `models`, copies `luts\*.cube` and `tools\results\golden\*.npz`.
(Do not run it; the integrator will.)

## 4. Docs + tests
Update `docs/ARCHITECTURE.md` (sections registry, regions registry, parallel workflow with
worktrees). Unit tests for: section registration/serialisation/unknown-section round trip,
legacy preset still loads, dev-only hidden, region registry + packing (5 regions -> 2 textures),
region slot readable by a test pass. Verify per the rules (unit + golden).
