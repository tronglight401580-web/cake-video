# Stream A follow-up: fix the rippled contour (warp field must be smooth)

Rules unchanged. Your v1 passes geometry/alignment/golden/speed, but the review image
(`tools/results/a_review.jpg`) shows a BLOCKING artefact: wavy ripples along the face contour and
hair edge (hush: left cheek/hair; mother_child: mother's left hair + cheek - very visible). The
temporal shimmer failure (2.26 / 1.49) is most likely the same ripples moving with the face.

**Diagnosis (product owner):** the field is a SUM of compact per-control-point bumps
`w=(1-(r/R)^2)^2` whose radius R is small relative to the spacing between the 21 contour points,
so the displacement oscillates between neighbouring points -> ripples. It is a design problem,
not a tuning problem.

## Fix
1. Normalised weights (partition of unity / Shepard-style): displacement(x) =
   sum_i w_i(x) d_i / max(sum_i w_i(x), eps) multiplied by a smooth envelope that goes to 0 away
   from the face; or a moving-least-squares / thin-plate formulation with the contour points as
   handles AND a ring of fixed anchor points (zero displacement) around the face at ~1.4x the face
   radius. Pick one, document why.
2. Radius / smoothness: influence must be broad relative to point spacing (R >= 3x spacing) so
   the field is smooth along the contour; low-pass the half-res field (separable gaussian) before
   use.
3. Jacobian guard: keep the local area scale (det J of the mapping) within [0.8, 1.25] everywhere
   (scale the field down locally/globally if needed). Keep the existing fold guard.
4. Keep everything else (eyes, 2 faces, yaw fade, appear/disappear fade, mask/region warping).

## New / updated tests (do not weaken existing ones)
- Ripple metric: on the OUTPUT frame, sample the warped jaw contour (landmarker on output, or the
  image gradient maximum along normals of the input contour) and compute the mean absolute second
  difference along the contour; it must not exceed the input contour's value by more than 15%.
  Also a field-smoothness unit test: max |second derivative| of the displacement field along the
  contour direction below a documented bound.
- Re-run the temporal check (shimmer/breathing p95 <= 1.0) and the landmark-jitter check - choose
  a frame range where the face is detected in >= 90% of frames (report which).
- Geometry (jaw -3..-6%), alignment (IoU >= 0.9), far-pixel identity, golden, unit, UI test: keep.
- Review image: add 3x crops of the contour regions that rippled (hush left cheek/hair, mother
  left cheek/hair), before vs after.
Report < 35 lines with all numbers.
