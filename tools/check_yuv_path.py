"""YUV input path (GPU conversion) must match the RGB path (ffmpeg conversion).

    python tools/check_yuv_path.py [CLIP]
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def frames(p, w, h, n=30):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", p, "-frames:v", str(n), "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(n, h, w, 3).astype(np.float32)


def main():
    import cake.pipeline as P
    from cake.styles import load_style
    clip = sys.argv[1] if len(sys.argv) > 1 else "samples/street_mixed_1227.mp4"
    outs, real = {}, P.yuv_capable
    for mode in ("yuv", "rgb"):
        P.yuv_capable = real if mode == "yuv" else (lambda info, hb: False)
        out = os.path.join(tempfile.gettempdir(), f"cake_{mode}.mp4")
        s = P.grade_video(clip, out, load_style("film_warm"), retouch=0.5, log=lambda *a: None)
        print(f"{mode} path: {s['fps']:.1f} fps")
        outs[mode] = out
    from cake.probe import probe
    from cake.media import target_size
    w, h = target_size(probe(clip), 1080)
    d = np.abs(frames(outs["yuv"], w, h) - frames(outs["rgb"], w, h))
    print(f"YUV vs RGB path: mean |diff| {d.mean():.3f}, p99 {np.percentile(d, 99):.1f}, "
          f"max {d.max():.0f} (0-255)")


if __name__ == "__main__":
    main()
