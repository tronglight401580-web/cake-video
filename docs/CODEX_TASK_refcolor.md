# Implement: reference-photo colour transfer ("参考图追色") + automatic skin protection

Background research: `docs/research_ref_color_slimming.md` (sections (a) and (b)). Read `README.md`,
`cake/face.py`, `cake/gpu.py`, `cake/shaders.py`, `cake/looks.py`, `cake/styles.py`,
`cake/pipeline.py`, `cake/ui/engine.py`, `cake/ui/app.py` before starting. No network, no pip
install (numpy, opencv, mediapipe, onnxruntime-directml, PySide6, Pillow are installed).
MediaPipe needs `model_asset_buffer` (non-ASCII paths). Keep all existing behaviour unchanged when
the new features are not used.

## Goal
User picks ONE reference photo -> we produce a style that makes the video's colour/mood match the
reference, while faces/necks/arms keep a natural skin tone (protection strength adjustable).

## 1. Full-skin mask channel (cake/shaders.py MASKBUILD, cake/gpu.py set_face)
The existing mask RGBA (R smooth weight, G tone, B under-eye, A cheek offset) has eyes/lips cut out
and body skin down-weighted - NOT suitable for colour protection. Add a second output:
- MASKBUILD writes a 2nd colour attachment (`layout(location = 1) out vec4 o2;`) with
  `o2.r = clamp(face + body, 0, 1)` (full skin probability, no feature cut-outs), same temporal
  EMA / reset logic as the first target (needs its own ping-pong pair of RGBA16F (or R16F) textures,
  never sample the texture being written).
- Expose it as `Renderer.skin` (texture, analysis resolution) next to `Renderer.mask`.

## 2. cake/refcolor.py (new) - fit the transfer, write two LUTs + a style
```python
def build_reference_style(ref_image: str, clips: list[str], name: str | None = None,
                          skin_follow: float = 0.3, samples_per_clip: int = 8) -> Style
```
- Sample `samples_per_clip` frames evenly from each clip (reuse `cake.media.Decoder` / ffmpeg at
  analysis size, short side 360). Get skin masks with `cake.face.run_models(small, True, ts)` or the
  segmentation part only (face-skin + body-skin = skin). Same for the reference image (resize to short
  side 360; RGB uint8).
- Colour space: sRGB-ish display RGB -> linear -> CIE Lab (D65). Write the conversions in numpy.
- Pixel selection for statistics: NON-skin pixels (skin prob < 0.3) with 3 < L < 97 (drop clipped).
  If fewer than 2% usable pixels, fall back to all pixels with 3 < L < 97.
- Global transfer = MKL (Monge-Kantorovich linear) in Lab:
  `T = Cs^-1/2 (Cs^1/2 Cr Cs^1/2)^1/2 Cs^-1/2`, `f(x) = T (x - mu_s) + mu_r`
  (eigen-decomposition; clamp eigenvalues >= 1e-4 * trace). Safety limits: blend T toward identity
  so that the L-axis gain stays within [0.6, 1.6] and the a/b gains within [0.4, 2.0]; limit
  |mu shift| to 25 L units and 30 a/b units. Document every constant.
- Global LUT: 33^3 identity grid (`cake.cube.identity`) -> Lab -> f -> RGB, soft-clip highlights
  like `looks.soft_clip`, clip to [0,1]. Write `luts/ref_<name>.cube`.
- Skin LUT (protection target): starts from the global result but keeps skin natural:
  in Lab, `skin(x) = x + [dL * 0.7, da * skin_follow, db * skin_follow]` where (dL, da, db) is
  `global(x) - x` (i.e. skin follows the brightness/mood, only part of the colour cast).
  If the reference has >= 1.5% skin pixels, additionally pull the skin mean toward the reference skin
  mean by `skin_follow`, limited to |dL| <= 6, |da|, |db| <= 4. Then apply the existing
  hue-guard idea from `looks.protect_skin` (keep skin hue within 12-30 deg HSV) to the skin LUT only.
  Write `luts/ref_<name>_skin.cube`.
- Style JSON `styles/ref_<name>.json`: `{"title": "追色·<name>", "lut": "ref_<name>.cube",
  "skin_lut": "ref_<name>_skin.cube", "skin_protect": 0.8, "comment": "...", "reference": "<path>"}`,
  no other effects. `name` default = reference file stem sanitised to ASCII/pinyin-free
  `[a-z0-9_]` (fallback `ref_<timestamp>`).
- Return the loaded Style.

## 3. Style + renderer + GRADE (cake/styles.py, cake/gpu.py, cake/shaders.py)
- `Style` gets optional `skin_lut: str = ""`, `skin_protect: float = 0.0`, `reference: str = ""`
  (keep `load_style` rejecting unknown keys). `Style.load_skin_lut()` like `load_lut` (cached).
- Renderer: second 3D LUT texture for the skin LUT (identity 2^3 LUT when the style has none).
- GRADE shader: `g = mix(lut(c), skin_lut(c), clamp(skin_mask(uv) * skin_protect * k, 0, 1))`
  then `mix(c, g, strength)` as today. `k` = 1 normally; a new `Renderer.skin_protect_scale`
  (default 1) lets the UI scale it. When no skin texture exists, behave as if mask = 0.
- Skin protection must work even when retouch = 0: the analysis must run if
  `retouch > 0 or (style.skin_lut and style.skin_protect > 0)`. Update `pipeline.grade_video`
  (analyzer creation condition) and `ui/engine.py` (`_retouch_on` / analyzer creation, and the
  retouch passes themselves must still be skipped when retouch == 0).

## 4. CLI + UI
- CLI: `python -m cake refstyle REF.jpg CLIP [CLIP...] [--name NAME] [--skin-follow 0.3]`
  -> prints the new style name. Also `python -m cake grade CLIP --ref REF.jpg` = build style from
  that clip then grade with it.
- UI (`cake/ui/app.py`): in the 风格 group add a "参考图追色…" button: pick an image, build the style
  in a background QThread from the CURRENT clip (status text while working), then add it to the
  style combo and select it; show a small thumbnail of the reference under the combo. Add a
  "肤色保护" slider (0-100, default 80) that maps to `skin_protect_scale` for styles that have a skin
  LUT (disabled otherwise). Settings dicts / presets / per-clip settings must include it.

## 5. Quality checks (write these as scripts; run them; report numbers)
`tools/test_refcolor.py` (prints a summary, exit code != 0 on failure):
1. **Recovery test**: reference = a frame (t=3 s) of `samples/street_mixed_1227.mp4` graded with
   the existing `teal_orange` style (render it with `cake.pipeline` stills machinery or a 1-frame
   grade). Build a reference style for `samples/beach_daylight_1221.mp4`. Grade beach at t=4 s with
   (A) the ref style, (B) the real `teal_orange`, (C) no style. Report mean CIEDE2000 (or CIE76 if
   simpler, say which) on NON-skin pixels: dE(A,B) must be clearly smaller than dE(C,B)
   (assert dE(A,B) < 0.6 * dE(C,B)).
2. **Skin protection test**: reference = a strongly tinted image (e.g. frame of
   `samples/neon_night_1230.mp4` at t=3). Apply to `samples/asian_hush_48036.mp4` t=4 with
   skin_protect 0 vs 0.8. On face-skin pixels report mean HSV hue and Lab a/b shift vs the original;
   assert protection reduces the skin colour shift by >= 50% while non-skin shift is unchanged
   (within 10%).
3. **No regression**: `python tools/run_all_tests.py` still all PASS.
4. Save ONE review image `tools/results/refcolor_review.jpg`: rows = the two tests; columns =
   reference | original | transfer without protection | transfer with protection | (row 1 only)
   real teal_orange. Label each tile.

## Report (final message, < 40 lines)
Files changed, the two tests' numbers (PASS/FAIL), run_all_tests summary line, path of the review
image, and anything you could not do. Do not weaken asserts to make tests pass — if a target is
missed, report the real number and what you think limits it.
