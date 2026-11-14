"""Measure what each style does to a frame: brightness, contrast, saturation, black point,
vignette, and (most important for Douyin) skin brightness / hue / saturation.

    python tools/eval_looks.py clip.mp4 [clip2.mp4 ...] --t 3
"""
import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cake import looks                          # noqa: E402
from cake.gpu import Renderer                   # noqa: E402
from cake.media import target_size              # noqa: E402
from cake.pipeline import _grab_frame, _to_u8   # noqa: E402
from cake.probe import probe                    # noqa: E402
from cake.styles import list_styles, render_stamp  # noqa: E402


def stats(rgb: np.ndarray, skin: np.ndarray) -> dict:
    c = rgb.astype(np.float64) / 255.0
    y = looks.luma(c)
    hsv = looks.rgb_to_hsv(c)
    h, w = y.shape
    cy, cx = slice(h * 3 // 8, h * 5 // 8), slice(w * 3 // 8, w * 5 // 8)
    corners = np.concatenate([y[:h // 8, :w // 8].ravel(), y[:h // 8, -w // 8:].ravel(),
                              y[-h // 8:, :w // 8].ravel(), y[-h // 8:, -w // 8:].ravel()])
    m = skin > 0.5
    out = {
        "亮度": y.mean() * 100,
        "对比(std)": y.std() * 100,
        "饱和": hsv[..., 1].mean() * 100,
        "黑位p1": np.percentile(y, 1) * 100,
        "白位p99": np.percentile(y, 99) * 100,
        "四角/中心": corners.mean() / max(y[cy, cx].mean(), 1e-4),
    }
    if m.sum() > 500:
        sh = hsv[..., 0][m]
        out.update({"肤亮": y[m].mean() * 100,
                    "肤色相": float(np.degrees(np.angle(np.exp(1j * np.radians(sh)).mean())) % 360),
                    "肤饱和": hsv[..., 1][m].mean() * 100})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clips", nargs="+")
    ap.add_argument("--t", type=float, default=3.0)
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    styles = list_styles()
    for clip in a.clips:
        info = probe(clip)
        w, h = target_size(info, 1080)
        hb = info.high_bit or bool(info.hdr)
        frame = _grab_frame(info, a.t, w, h, hb, "mobius")
        orig = _to_u8(frame, w, h, hb)
        skin = looks.skin_weight(orig.astype(np.float64) / 255.0)
        rows = [("原片", stats(orig, skin))]
        r = Renderer(w, h, hb)
        for st in styles:
            r.set_style(st, 1.0, None)          # no stamp: don't let it skew numbers
            g = np.frombuffer(r.render(frame, 0), np.uint8).reshape(h, w, 3)
            rows.append((st.title, stats(g, skin)))
        r.release()
        keys = list(rows[0][1].keys())
        print(f"\n== {Path(clip).stem} @ {a.t}s  (肤色像素 {int((skin > 0.5).sum())})")
        print(f"{'':10s}" + "".join(f"{k:>10s}" for k in keys))
        for name, s in rows:
            print(f"{name:10s}" + "".join(f"{s.get(k, float('nan')):10.2f}" for k in keys))


if __name__ == "__main__":
    main()
