# Prep, part 1 of 2: pluggable Recipe sections (+ UI + dev-only demo)

Rules: `docs/CODEX_PARALLEL_RULES.md`. Full background: `docs/CODEX_TASK_prep.md` section 1.
The region registry skeleton (`cake/analysis/regions.py`, `tests/test_regions.py`) and
`tools/new_worktree.ps1` already exist from the previous run - leave them alone (part 2 continues
them). This run does ONLY section 1 of CODEX_TASK_prep.md:

1. `@register_section("name")` registry for small dataclasses whose fields use the same metadata
   format as Recipe fields (+ `dev_only`). `Recipe` keeps all existing fields/behaviour; registered
   sections are available as `recipe.sections[name]` and as attributes (`recipe.<name>`);
   to_dict/from_dict serialise them under `"sections"`; unknown sections preserved as raw dicts;
   missing ones get defaults; legacy dicts and old presets still load; version handled.
2. Param panel builds controls for every registered section's fields (grouped by `ui` group);
   fields with `dev_only=True` are hidden unless `cake.core.config` says dev mode (env `CAKE_DEV=1`,
   read in config.py only).
3. Move `demo_tint` into its own section defined in `cake/render/passes/demo_tint.py`
   (`dev_only=True`); the pass reads `recipe.demo_tint.amount` (or similar). Remove the old
   top-level field from Recipe but keep `from_dict` accepting it (migrate into the section).
4. Tests: section registration/serialisation/unknown-section round trip; legacy preset with the old
   top-level demo_tint still loads; dev-only control hidden by default and shown with CAKE_DEV=1;
   `python tools/test_ui.py` still passes (it's allowed to run it once - it's the UI test, not the
   full regression).
Verify: `python tests/run_unit.py`, `python tools/golden.py check` (mean 0/max 0),
`python tools/test_ui.py`. Report < 25 lines.
