"""Generate a 1080x1920 test chart video for judging looks objectively.

Rows: ColorChecker 24 (sRGB) | skin tones light->dark | grey ramp (banding) |
      sky gradient | hue x saturation sweep.
    python tools/make_chart.py OUT.mp4
"""
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw

W, H = 1080, 1920
# X-Rite ColorChecker Classic, sRGB D65 (8-bit)
CHECKER = [
    (115, 82, 68), (194, 150, 130), (98, 122, 157), (87, 108, 67), (133, 128, 177), (103, 189, 170),
    (214, 126, 44), (80, 91, 166), (193, 90, 99), (94, 60, 108), (157, 188, 64), (224, 163, 46),
    (56, 61, 150), (70, 148, 73), (175, 54, 60), (231, 199, 31), (187, 86, 149), (8, 133, 161),
    (243, 243, 242), (200, 200, 200), (160, 160, 160), (122, 122, 121), (85, 85, 85), (52, 52, 52),
]
SKIN = [(255, 224, 205), (241, 200, 175), (226, 180, 152), (210, 160, 130),
        (188, 136, 106), (160, 110, 84), (125, 84, 62), (90, 60, 45)]


def chart() -> np.ndarray:
    img = Image.new("RGB", (W, H), (40, 40, 40))
    d = ImageDraw.Draw(img)
    pw, ph, gap = 170, 150, 6
    x0, y0 = (W - (6 * pw + 5 * gap)) // 2, 30
    for i, c in enumerate(CHECKER):
        x, y = x0 + (i % 6) * (pw + gap), y0 + (i // 6) * (ph + gap)
        d.rectangle([x, y, x + pw, y + ph], fill=c)
    y = y0 + 4 * (ph + gap) + 24
    sw = (W - 2 * x0 - 7 * gap) // 8
    for i, c in enumerate(SKIN):
        x = x0 + i * (sw + gap)
        d.rectangle([x, y, x + sw, y + 180], fill=c)
    a = np.array(img).astype(np.float32)
    y = y + 180 + 30
    ramp = np.linspace(0, 1, W)[None, :, None]
    a[y:y + 180] = ramp * 255
    y += 200
    t = np.linspace(0, 1, 260)[:, None, None]
    top, bottom = np.array([70, 130, 210]), np.array([200, 225, 245])
    a[y:y + 260] = top + (bottom - top) * t
    y += 280
    hh = H - y - 20
    hue = np.linspace(0, 1, W)[None, :]
    sat = np.linspace(1, 0, hh)[:, None]
    hsv = np.stack([np.broadcast_to(hue, (hh, W)) * 255, np.broadcast_to(sat, (hh, W)) * 255,
                    np.full((hh, W), 230.0)], -1).astype(np.uint8)
    a[y:y + hh] = np.array(Image.fromarray(hsv, "HSV").convert("RGB"))
    return np.clip(a, 0, 255).astype(np.uint8)


if __name__ == "__main__":
    out = sys.argv[1]
    png = out.rsplit(".", 1)[0] + ".png"
    Image.fromarray(chart()).save(png)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-i", png, "-t", "2", "-r", "30",
                    "-vf", "format=yuv444p", "-c:v", "libx264", "-crf", "4", "-pix_fmt", "yuv444p",
                    "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", out],
                   check=True)
    print(out)
