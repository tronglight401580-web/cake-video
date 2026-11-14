# Task: tools/platform_sim.py — short-video platform compression simulator

Context: this repo is a video color-grading tool for Douyin / WeChat Channels vertical short videos.
Platforms re-encode uploads at low bitrate, which destroys fine film grain and causes banding.
We need a tool that simulates that re-encode and shows how much of our grain/texture survives.

Write ONE file: `tools/platform_sim.py` (plus `tools/test_platform_sim.py`). Do NOT touch anything
under `cake/`, `styles/`, `luts/`. No network access is available; do not try to pip install.

## Allowed dependencies
Python 3.12 stdlib, numpy, Pillow (already installed). `ffmpeg` and `ffprobe` are on PATH
(ffmpeg 8.1, has libx264). Windows 10; paths may contain Chinese characters — always pass
args to subprocess as a list, never via a shell string, and read/write files with explicit utf-8.

## CLI
```
python tools/platform_sim.py GRADED.mp4 [--orig ORIGINAL.mp4] [--times 1.0,3.5]
                             [--bitrates 3M,1.5M] [--out OUT_DIR]
```
- `--times`: seconds to sample; default = 3 evenly spaced points inside the video (10%,50%,90%).
- `--bitrates`: list of target video bitrates; default `3M,1.5M` (rough Douyin / Channels playback).
- `--out`: default `<GRADED dir>/sim/`.
- `--orig` optional: if given, include the ungraded original as the first column for reference.

## Steps
1. For each bitrate, re-encode GRADED with libx264: scale down to fit within 1080x1920 keeping
   aspect (never upscale), `-preset veryfast -b:v B -maxrate 1.5*B -bufsize 2*B -profile:v high
   -pix_fmt yuv420p -an`. Save `OUT/<stem>_<bitrate>.mp4`. Skip if it already exists and is newer
   than GRADED.
2. Extract frames at each time from GRADED, each re-encode (and ORIG): use ffprobe for size,
   `ffmpeg -ss T -i FILE -frames:v 1 -f rawvideo -pix_fmt rgb24 -` and read into numpy.
   All compared frames must be the same size (scale the larger ones down to the re-encode size).
3. Metrics per time, per version (luma, Rec.709 weights, float):
   - `hf`: mean |Y - gaussian_blur(Y, sigma=1.5)| (separable numpy conv) → high-frequency energy.
   - `hf_flat`: same but only over "flat" pixels — pixels where local std of the blurred image
     (7x7 window) is in the lowest 30% — this isolates grain from real detail.
   - `grain_retention = hf_flat(version) / hf_flat(graded)`.
   - `banding`: on flat pixels, fraction of 2nd-derivative == 0 runs ≥ 6 px horizontally
     (simple heuristic, document it in a comment).
   Write `OUT/<stem>_sim.json` and print a readable table.
4. Contact sheet `OUT/<stem>_sim.png`: one row per time. Columns: (orig), graded, each bitrate.
   Each cell = a 360-px-wide full-frame thumbnail on top + a 1:1 (unscaled) 320x320 crop from the
   flattest 320x320 region below it, with a label "graded" / "3M" etc and the grain_retention
   value. Use `C:/Windows/Fonts/msyh.ttc` if it exists else Pillow default font.

## Tests
`tools/test_platform_sim.py` (plain asserts, runnable with `python tools/test_platform_sim.py`):
generate a 4 s 1080x1920 test clip into a temp dir with ffmpeg (`testsrc2` + `noise=alls=20:allf=t`),
run the tool's main() on it, assert the mp4s, json and png exist and grain_retention values are in
(0, 1.5]. Run the test yourself and make sure it passes.

When done, print a short summary of what you built and the test output.
