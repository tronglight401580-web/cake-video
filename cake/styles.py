"""Style presets: styles/<name>.json = LUT + shader effect parameters."""
from __future__ import annotations

import datetime as _dt
import json
import os
from dataclasses import dataclass, field, fields
from functools import lru_cache
from pathlib import Path

import numpy as np

from .cube import read_cube

ROOT = Path(__file__).resolve().parent.parent
STYLE_DIR = ROOT / "styles"
LUT_DIR = ROOT / "luts"


@dataclass
class Style:
    name: str
    title: str = ""
    lut: str = ""                 # file in luts/ or absolute path to any .cube
    skin_lut: str = ""
    skin_protect: float = 0.0
    reference: str = ""
    lut_strength: float = 1.0
    bloom_amount: float = 0.0
    bloom_threshold: float = 0.7
    bloom_knee: float = 0.2
    bloom_radius: float = 40.0    # px at 1080p
    bloom_tint: list = field(default_factory=lambda: [1.0, 1.0, 1.0])
    ca: float = 0.0
    soften: float = 0.0
    vignette: float = 0.0
    vignette_soft: float = 0.6
    grain: float = 0.0
    grain_size: float = 1.6       # px at 1080p
    grain_chroma: float = 0.15
    stamp: dict | None = None     # {"text": "auto" | str, "color": [r,g,b], "size": px@1080}

    def load_lut(self) -> np.ndarray:
        p = Path(self.lut)
        if not p.is_absolute():
            p = LUT_DIR / p
        if not p.exists():
            raise FileNotFoundError(f"LUT not found: {p}  (run: python -m cake build-luts)")
        return _read_cube_cached(str(p), p.stat().st_mtime_ns)

    def load_skin_lut(self) -> np.ndarray:
        p = Path(self.skin_lut)
        if not p.is_absolute():
            p = LUT_DIR / p
        return _read_cube_cached(str(p), p.stat().st_mtime_ns)


@lru_cache(maxsize=32)
def _read_cube_cached(path: str, _mtime: int) -> np.ndarray:
    """Parsing a 33^3 .cube text file takes ~150 ms; the UI switches styles interactively."""
    return read_cube(path)


def list_styles() -> list[Style]:
    return [load_style(p.stem) for p in sorted(STYLE_DIR.glob("*.json"))]


def load_style(name_or_path: str) -> Style:
    p = Path(name_or_path)
    if p.suffix.lower() == ".cube":
        # bare third-party LUT, no effects
        return Style(name=p.stem, title=p.stem, lut=str(p.resolve()))
    if p.suffix.lower() != ".json":
        p = STYLE_DIR / f"{name_or_path}.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    known = {f.name for f in fields(Style)}
    unknown = set(data) - known - {"comment"}
    if unknown:
        raise ValueError(f"{p}: unknown keys {sorted(unknown)}")
    data = {k: v for k, v in data.items() if k in known}
    data.setdefault("name", p.stem)
    return Style(**data)


def _stamp_text(spec: dict, video_path: str | None) -> str:
    text = spec.get("text", "auto")
    if text != "auto":
        return text
    ts = os.path.getmtime(video_path) if video_path and os.path.exists(video_path) else None
    d = _dt.date.fromtimestamp(ts) if ts else _dt.date.today()
    return d.strftime("'%y %m %d")


def render_stamp(style: Style, w: int, h: int, video_path: str | None = None) -> np.ndarray | None:
    """Orange LCD-style date stamp (CCD look), drawn once into an RGBA overlay."""
    if not style.stamp:
        return None
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    spec = style.stamp
    scale = min(w, h) / 1080.0
    size = int(spec.get("size", 46) * scale)
    color = tuple(int(c * 255) for c in spec.get("color", [1.0, 0.55, 0.15]))
    font = None
    for f in spec.get("fonts", []) + ["C:/Windows/Fonts/consolab.ttf", "C:/Windows/Fonts/consola.ttf",
                                      "C:/Windows/Fonts/arialbd.ttf"]:
        if os.path.exists(f):
            font = ImageFont.truetype(f, size)
            break
    font = font or ImageFont.load_default()
    text = _stamp_text(spec, video_path)

    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    tw, th = draw.textbbox((0, 0), text, font=font)[2:]
    # Portrait: keep the stamp inside the Douyin / Channels safe area (~840x1280 centred-high on
    # 1080x1920), clear of the right-hand button column and the bottom caption block.
    # Landscape (shown letterboxed, no UI over the picture): classic bottom-right corner.
    if h >= w:
        mx = int(spec.get("margin_x", 0.17) * w)
        my = int(spec.get("margin_y", 0.25) * h)
    else:
        mx = int(spec.get("margin_x_landscape", 0.05) * w)
        my = int(spec.get("margin_y_landscape", 0.08) * h)
    pos = (w - mx - tw, h - my - th)
    draw.text(pos, text, font=font, fill=color + (235,))
    glow = img.filter(ImageFilter.GaussianBlur(max(2, size // 6)))
    glow_arr = np.array(glow).astype(np.float32)
    glow_arr[..., 3] *= 0.85
    base = np.array(img).astype(np.float32)
    a = base[..., 3:4] / 255.0
    ga = glow_arr[..., 3:4] / 255.0
    out_a = a + ga * (1 - a)
    out_rgb = (base[..., :3] * a + glow_arr[..., :3] * ga * (1 - a)) / np.maximum(out_a, 1e-6)
    out = np.concatenate([out_rgb, out_a * 255], -1)
    return np.clip(out, 0, 255).astype(np.uint8)
