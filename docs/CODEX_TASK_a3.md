# Stream A follow-up 3: honest strength curve + real temporal stability

Rules unchanged (`docs/CODEX_PARALLEL_RULES.md`). Product-owner review of A2:
- ACCEPTED: the ripple fix. 3x contour crops are clean, roughness ratios ~1.00, Jacobian 0.86-1.14,
  IoU >= 0.987, far pixels identical, golden identical, 0.26 ms. Keep all of that.
- REJECTED: `slim = slim**5; eyes = eyes**5` in `warp.py`. The temporal test runs at slim 0.7 /
  eyes 0.5, so this made it measure ~17% / ~3% strength - the shimmer/breathing pass is not real,
  and users would see almost nothing below slider value 0.8. Also eye growth on hush is only 0.23%.

## Fix
1. Strength response: linear (or at most a mild curve such as `s**1.5`; document it). Slider 0.5
   must give a visible effect.
2. Reduce breathing at the source instead: stabilise the warp's own geometry over time. Ideas
   (pick, document why): derive the push vectors in a face-normalised frame from temporally
   smoothed scalars (face width, axis, centre) with a stronger One-Euro/EMA than the landmarks;
   smooth the half-res field over time (EMA in face-aligned coordinates, reset on cut / track
   loss); quantise nothing. Keep ripple fix, Jacobian guard, fade logic.
3. Eyes: check why hush eye width grew only 0.23% at eyes 1.0 (yaw fade? radius? landmark choice?)
   and make eyes 1.0 give >= 3% on both hush and indoor unless the face is genuinely turned (report).

## Tests (do not weaken; add)
- Temporal check at slim 0.7 / eyes 0.5 (as specified) AND at slim 1.0 / eyes 1.0: added shimmer /
  breathing p95 <= 1.0 for both. Use >= 120 frames where the face is detected in >= 90% (report the
  range and count); 48 frames is too short.
- Add a test that geometry scales sensibly with the slider: jaw reduction at slim 0.5 is between
  35% and 65% of the reduction at slim 1.0.
- Keep: jaw -3..-6% at 1.0, eyes grow, ripple ratio <= 1.15, IoU >= 0.9, far pixels identical,
  golden, unit, UI, GPU time.
- Review image: as A2, plus a row of hush face crops at slim 0.5 and 1.0.
Report < 35 lines with all numbers.
