# Refactor step 1b: split the renderer into registered passes (output must stay bit-identical)

Context: `docs/CODEX_TASK_refactor.md` (overall plan, "Pass registry" + "Target layout" sections).
Done and committed: golden reference (`tools/golden.py`, self-noise exactly 0), core skeleton
(`cake/core/registry.py` etc.), and step 1a (io/ and color/ moved, config centralised).
This run: ONLY split `cake/gpu.py` + `cake/shaders.py` into `cake/render/`. No Phase 2 work.

## Target
```
cake/render/context.py     GL context creation, fullscreen quad + VAO factory, program cache,
                           render-target helpers (rt(size) -> (tex, fbo)), PBO double-buffered
                           readback helper
cake/render/frame.py       FrameContext: recipe/settings view, frame index, size, face inputs,
                           dict of named texture slots, plus per-frame uniforms the passes need
cake/render/renderer.py    Renderer: same public API as today's cake.gpu.Renderer (constructor
                           (w, h, high_bit, yuv=None), set_style, set_retouch, set_face, render(...,
                           yuv=, pipelined=), flush, release, and attributes used elsewhere: mask,
                           skin, face_boxes, face_h, strength, retouch, skin_protect_scale, scale,
                           mask_alpha, debug ...). It imports cake.render.passes (self-registering),
                           instantiates the registered passes in order, calls setup() once, and per
                           frame runs the enabled() ones in order.
cake/render/passes/        input.py (100: RGB upload / YUV2RGB), maskbuild.py (200; invoked from
                           set_face, not per render - model that cleanly, e.g. a pass whose run is
                           triggered by set_face, or a separate "per-face-update" stage in the
                           registry), heal.py (300), retouch.py (400), grade.py (500), bloom.py (600),
                           finish.py (700), output.py (800: TOYUV + readback for yuv path; RGB path
                           reads finish target). Each pass owns its GLSL (inline string in the module)
                           and its textures/framebuffers.
cake/gpu.py, cake/shaders.py   become thin shims re-exporting Renderer and the GLSL constants
                           (tools may import shader strings by name - keep the names).
```
Rules for passes: declare `reads` / `writes` slot names; communicate only through FrameContext
slots (e.g. "rgb", "mask", "skin", "healed", "retouched", "graded", "bloom", "out16", "out8");
no pass reaches into another pass's attributes. Keep exact numerical behaviour: same uniforms,
same texture formats (f1 / nu2 / f2 / f4), same filtering, same pass order, same skip conditions
(e.g. heal only when spots/under > 0 and mask has 4 channels; bloom only when bloom_amount > 0;
skin protection when a skin LUT exists), same dither seeds (`frame % 4096`).

A tiny registry check: add a unit test that a DEMO pass registered in a test module at order 650
is picked up and run between bloom and finish without editing renderer.py (then unregister it).

## Verify (all must pass; report result lines)
- `python tools/golden.py check` - all 5 must be mean 0 / max 0 (bit-identical). If not, find the
  difference (format, filtering, order, uniform) and fix it; do not relax the tolerance.
- `python tests/run_unit.py`
- `python tools/run_all_tests.py` (≈10 min; long timeout; run to completion)
- `python tools/test_refcolor.py`
- `python tools/bench_speed.py samples/street_mixed_1227.mp4` - report loop fps (baseline 32-35);
  must not drop more than 5%.
Report (< 40 lines): file map, how maskbuild is modelled, verification lines, fps, open issues.
