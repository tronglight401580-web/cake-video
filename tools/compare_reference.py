"""Compare two grades against an original using one shared face-skin mask."""
import argparse
from pathlib import Path
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def read_rgb(path):
    a = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if a is None:
        raise FileNotFoundError(path)
    return cv2.cvtColor(a, cv2.COLOR_BGR2RGB)


def hue(rgb):
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV).astype(np.float32)[..., 0] * 2


def blob_count(gray, mask):
    # Dark, compact DoG responses approximate visible spots; use same facial region for all.
    g = gray.astype(np.float32)
    response = cv2.GaussianBlur(g, (0, 0), 1.0) - cv2.GaussianBlur(g, (0, 0), 3.0)
    candidates = (response > 4.0) & mask
    n, labels, stats, _ = cv2.connectedComponentsWithStats(candidates.astype(np.uint8), 8)
    return int(sum(1 for x, y, w, h, area in stats[1:] if 2 <= area <= 80 and max(w, h) <= 14))


def metrics(rgb, orig, mask, nonmask):
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    olab = cv2.cvtColor(orig, cv2.COLOR_RGB2LAB).astype(np.float32)
    y = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    oy = cv2.cvtColor(orig, cv2.COLOR_RGB2GRAY).astype(np.float32)
    h, oh = hue(rgb), hue(orig)
    def mean(x, m):
        vals = x[m]
        return float(vals.mean()) if vals.size else float("nan")
    dh = (h - oh + 180) % 360 - 180
    smooth = cv2.GaussianBlur(y, (0, 0), 2.0)
    osmooth = cv2.GaussianBlur(oy, (0, 0), 2.0)
    hf = y - smooth
    ohf = oy - osmooth
    return {
        "LΔ": mean(lab[..., 0] - olab[..., 0], mask),
        "hueΔ": mean(dh, mask),
        "aΔ": mean(lab[..., 1] - olab[..., 1], mask),
        "bΔ": mean(lab[..., 2] - olab[..., 2], mask),
        "smooth%": mean(hf * hf, mask) / max(mean(ohf * ohf, mask), 1e-8) * 100,
        "spots": float(blob_count(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), mask)),
        "non-skin ΔE76": mean(np.linalg.norm(lab - olab, axis=-1), nonmask),
    }


def sheet(images, mask, out):
    h, w = mask.shape
    yy, xx = np.where(mask)
    if len(xx):
        pad = max(12, int(max(xx.max()-xx.min(), yy.max()-yy.min()) * .12))
        x0, x1 = max(0, xx.min()-pad), min(w, xx.max()+pad+1)
        y0, y1 = max(0, yy.min()-pad), min(h, yy.max()+pad+1)
    else:
        x0, x1, y0, y1 = w//4, 3*w//4, h//4, 3*h//4
    thumb_w = 480
    full_h = round(h * thumb_w / w)
    crop_side = max(x1-x0, y1-y0)
    cx, cy = (x0+x1)//2, (y0+y1)//2
    x0c, y0c = max(0, min(w-crop_side, cx-crop_side//2)), max(0, min(h-crop_side, cy-crop_side//2))
    tiles = []
    for label, a in zip(("Original", "Ours", "Theirs"), images):
        im = Image.fromarray(a)
        full = im.resize((thumb_w, full_h), Image.Resampling.LANCZOS)
        crop = im.crop((x0c, y0c, x0c+crop_side, y0c+crop_side)).resize((thumb_w, thumb_w), Image.Resampling.LANCZOS)
        tiles.append((label, full, crop))
    pad, lh = 12, 38
    canvas = Image.new("RGB", (pad*4 + thumb_w*3, lh*2 + full_h + thumb_w + pad*3), (24,24,24))
    d = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    for i, (label, full, crop) in enumerate(tiles):
        x = pad + i*(thumb_w+pad)
        d.text((x, 8), label, fill="white", font=font)
        canvas.paste(full, (x, lh))
        d.text((x, lh+full_h+pad), label + " face crop ×2", fill="white", font=font)
        canvas.paste(crop, (x, lh+full_h+lh))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, quality=94)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("original", type=Path)
    ap.add_argument("ours", type=Path)
    ap.add_argument("theirs", type=Path)
    ap.add_argument("--out", type=Path, default=Path("sheet.jpg"))
    a = ap.parse_args()
    images = [read_rgb(p) for p in (a.original, a.ours, a.theirs)]
    if any(im.shape != images[0].shape for im in images):
        ap.error("all three images must have identical dimensions")
    from cake.analysis.frames import analysis_size
    from cake.analysis.segment import segment
    small = cv2.resize(images[0], analysis_size(images[0].shape[1], images[0].shape[0]), interpolation=cv2.INTER_AREA)
    face_skin = segment(small)[..., 0].astype(np.float32) / 255
    mask = cv2.resize(face_skin, (images[0].shape[1], images[0].shape[0]), interpolation=cv2.INTER_LINEAR) > 0.5
    if mask.sum() < 20:
        raise RuntimeError("face-skin segmentation returned too few pixels")
    vals = [metrics(im, images[0], mask, ~mask) for im in images]
    print(f"{'Metric':<18} {'Ours':>12} {'Theirs':>12}")
    for key in vals[1]:
        print(f"{key:<18} {vals[1][key]:>12.3f} {vals[2][key]:>12.3f}")
    sheet(images, mask, a.out)
    print(f"Sheet: {a.out}")


if __name__ == "__main__":
    main()
