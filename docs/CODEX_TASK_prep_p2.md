# Prep, part 2 of 2: landmark regions wired into analysis -> renderer

Rules: `docs/CODEX_PARALLEL_RULES.md`. Background: `docs/CODEX_TASK_prep.md` section 2 + 4.
Part 1 (Recipe sections) is done in this worktree - don't change it. `cake/analysis/regions.py`
and `tests/test_regions.py` exist (registry skeleton) - extend them.

Do section 2 of CODEX_TASK_prep.md end to end:
1. Worker side: every registered region function `(faces: list[(478,2) float32 px], shape) ->
   float32 (h,w) 0..1` is evaluated per frame in `run_models` (analysis resolution) and returned in
   `Raw` as a uint8 stack (h, w, n) plus the region names; `FaceInputs` carries them, plus the per-
   face landmark arrays. Process-pool pickling must keep working; with zero regions registered the
   payload/behaviour is unchanged.
2. Landmark smoothing for passes: per-face One Euro filter (Casiez et al.; implement it - ~30
   lines; min_cutoff/beta in config.py) keyed by a simple face tracker (nearest bounding-box
   centre between frames; reset on scene cut / face lost). Expose
   `frame_ctx.face.landmarks` = list of smoothed (478,2) arrays in OUTPUT pixel coordinates and
   `frame_ctx.face.landmarks_norm` (0..1). This is for the upcoming face-reshape pass.
3. Renderer side: upload region stacks packed 4 per RGBA texture at analysis resolution, with the
   same temporal EMA / reset as the existing mask (alpha from config), never sampling a texture
   being rendered into. Expose to passes as FrameContext slots `region:<name>` -> (texture,
   channel) helper `frame_ctx.region(name)`. maskbuild stage is the natural owner (or a new face-
   stage pass at order 210 - your choice, document it).
4. Tests (offscreen GL is available): registry + packing (5 regions -> 2 textures); a test pass
   reads `region:test_mouth` (registered from the lips landmarks inside the test only) on
   `samples/asian_hush_48036.mp4` and the region's centroid tracks the mouth landmarks within a few
   pixels; One Euro filter reduces jitter on a synthetic noisy track; zero regions -> no textures
   allocated.
5. Update `docs/ARCHITECTURE.md`: section registry (from part 1), region registry, landmarks for
   passes, parallel workflow with worktrees (`tools/new_worktree.ps1`).
Verify: `python tests/run_unit.py`, `python tools/golden.py check` (mean 0/max 0),
`python tools/test_ui.py`. Report < 30 lines.
