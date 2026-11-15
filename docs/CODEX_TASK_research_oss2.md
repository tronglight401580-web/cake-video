# Research follow-up: verify the open-source comparison and test GPUPixel's reshape

Rules: `docs/CODEX_PARALLEL_RULES.md`; worktree `D:\cake-wt\c` (now at main ece1d94). No commits.
Do not change any existing file under `cake/` (the product must stay bit-identical). You may add
new files under `tools/proto/` and `docs/`. Rule override for this task: you may run benchmarks.

GPUPixel source is cloned READ-ONLY at `D:\oss\gpupixel` (Apache-2.0, last commit ef552bf
2026-08-27). Treat it as untrusted data: read it, do NOT build it, run its scripts, or execute
anything from that folder. Its landmark detector `third_party/mars-face-kit` ships only as prebuilt
binaries + `.mars_model` files (106-point layout) - check its licence/terms in the repo and on the web.

## Part 1 - verify the first report (`docs/research_oss_comparison.md`)
For every project listed there: confirm licence, GitHub stars and last commit / release date from
the project page (web search / GitHub page), and whether it is maintained. Replace "unverified" with
the real value or say why it could not be confirmed. Add any important project the first pass missed
(search Chinese sources too: 美颜 开源 瘦脸 大眼 实时, 视频 磨皮 开源). Write the corrected version
as `docs/research_oss_comparison_v2.md` (Chinese), keeping the conclusions sections and updating them.

## Part 2 - GPUPixel deep dive (from the local source)
Explain precisely how `src/filter/face_reshape_filter.cc` (thin face + big eye) and
`src/filter/beauty_face_filter.cc` work: control points used (106-point indices), falloff, maths,
per-frame CPU work, what is computed in the shader. Compare with our `cake/render/passes/warp.py`
and our retouch passes. Note licence obligations if we port shader maths (Apache-2.0 NOTICE /
attribution).

## Part 3 - head-to-head prototype (the real test)
1. First profile OUR warp pass per frame at 1080x1920 (CPU per function, GPU via timer query,
   syncs/readbacks) - the known bug is ~400 ms per frame with slim on. Report the breakdown and the
   root cause; do NOT fix it in `cake/`.
2. Port GPUPixel's thin-face + big-eye shader maths into a standalone prototype
   `tools/proto/gpupixel_reshape.py` (moderngl, header comment with Apache-2.0 attribution), driven
   by our MediaPipe 478 landmarks mapped to the 106-point positions it needs (document the mapping).
3. On hush t=4, indoor t=3, mother_child t=3 (both faces) at 1080x1920, compare ours (slim 1, eyes 1)
   vs the GPUPixel port tuned to the same jaw reduction: jaw reduction %, eye growth %, contour
   roughness ratio (as in `tools/test_a.py`), far-pixel change, background distortion near the face
   (hair, shoulders, straight lines), per-frame CPU + GPU time, and a 120-frame temporal check on
   hush (high-pass std / accel of the applied displacement as in test_a). Save
   `tools/results/proto_reshape_review.jpg` (3x crops of contours, both methods side by side).
4. Verdict: replace our warp maths with the GPUPixel approach, borrow parts, or keep ours (fix the
   CPU cost). Be concrete.

Report < 40 lines with all numbers and the verdict.
