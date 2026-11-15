# Stream A: automatic face slimming + eye enlarging for video (warp pass, order 250)

Rules: `docs/CODEX_PARALLEL_RULES.md` (work only in `D:\cake-wt\a`, no commits, feature OFF =>
golden bit-identical, don't run run_all_tests/bench). Read `docs/ARCHITECTURE.md` (Recipe
sections, regions, `frame_ctx.face.landmarks` = One-Euro-smoothed, tracked landmarks in output
pixels) and `docs/research_ref_color_slimming.md` section (c).
You own new files: `cake/render/passes/warp.py` (+ helpers), its section, `tests/test_warp*.py`,
`tools/test_a.py`. A one-line import in a package `__init__` is allowed (report it). Do not edit
core/renderer/analyzer/ui files unless unavoidable (then minimal, reported).

## Recipe section `reshape`
`slim` (瘦脸, 0..1, default 0), `eyes` (大眼, 0..1, default 0). ui group 人像精修.

## Warp design (GPU, inverse mapping - every output pixel samples a source position)
1. Displacement field pass: per frame compute a half-res RG16F field D(uv) (source = uv + D).
   - Slim: control points on the lower face contour (MediaPipe face-oval indices from ear to chin,
     e.g. 234,93,132,58,172,136,150,149,176,148,152,377,400,378,379,365,397,288,361,323,454),
     each pushed toward the face centre line (nose bridge 168 -> chin 152 axis) by
     `slim * 0.045 * face_width` (chin moves less: scale by distance from the axis). Liquify-style
     push with smooth radial falloff `w = (1 - (r/R)^2)^2`, R about 0.22 * face width; inverse
     mapping: source = x - sum_i w_i(x) * d_i, with a Jacobian/fold guard (cap total displacement
     so the mapping stays monotonic; never fold).
   - Eyes: radial magnification around each eye centre (mean of the eye contour landmarks),
     radius ~ 0.9 * eye width, source = c + (x - c) * (1 - eyes * 0.12 * (1 - (r/R)^2)^2).
   - Up to the 2 largest faces. Strength fades automatically: by head yaw (estimate from landmark
     asymmetry, e.g. nose tip vs cheek extremes; full at |yaw| < 20 deg, zero at > 45 deg); fade
     in/out over ~8 frames when a face appears / is lost (track id from the smoother).
2. Apply pass: warp the "rgb" slot (full res, bilinear) AND every mask-like slot (mask, skin, all
   region textures) with the SAME field so retouch/heal/protection stay aligned with the moved
   face. Write new textures and replace the slots (ping-pong; never sample what you write).
3. Background safety: the field is zero beyond each control point's radius; report how far from
   the face contour pixels can move. No inpainting in this version (small displacements only).

## Tests (`tools/test_a.py` + unit tests)
- Golden identical with defaults (slim=eyes=0) -> nothing allocated / zero cost when off.
- Geometry (asian_hush_48036 t=4, asian_indoor_48688 t=3): with slim 1.0, run the landmarker on
  the OUTPUT: jaw width (dist 234-454 or 132-361) shrinks by 3-6%; eye width grows with eyes 1.0;
  pixels farther than 1.3*R from every control point are bit-identical to slim 0.
- Alignment: skin mask re-segmented on the output vs the warped skin slot: soft IoU >= 0.9.
- Temporal: grade the hush clip with slim 0.7, eyes 0.5 (style none, retouch 0.5); use
  `tools/flicker.py` vs the same settings with slim=eyes=0: added face shimmer/breathing p95 <= 1.0
  level; landmark jitter in the output (frame-to-frame, after removing global motion) not more than
  the input's +20%.
- Fold guard: random extreme landmark sets never produce a folded mapping (unit test on the field
  maths on CPU).
- GPU time for field + apply at 1080x1920: report (target <= 2 ms total).
- Review image `tools/results/a_review.jpg`: before/after full frames + face crops for hush,
  indoor, mother_child (2 faces).
Verify: unit, golden, `tools/test_a.py`, `tools/test_ui.py`. Report < 40 lines; never weaken tests.
