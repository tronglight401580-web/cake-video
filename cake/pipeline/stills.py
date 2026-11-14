from __future__ import annotations
import queue, threading, time
from pathlib import Path
import numpy as np
from ..core.config import CAKE_YUV
from ..core.bus import bus
from ..core.recipe import Recipe, RetouchCfg
from ..styles import Style, render_stamp
from ..probe import ClipInfo
from . import _deps

def _grab_frame(info: ClipInfo, t: float, w: int, h: int, high_bit: bool, tonemap: str) -> bytes:
    dec = _deps().Decoder(info, w, h, high_bit, start=t, frames=1, tonemap=tonemap)
    frame = next(iter(dec), None)
    err = dec.close()
    if frame is None:
        raise RuntimeError(f"无法在 {t}s 截帧: {err}")
    return frame


def _to_u8(frame: bytes, w: int, h: int, high_bit: bool) -> np.ndarray:
    a = np.frombuffer(frame, np.uint16 if high_bit else np.uint8).reshape(h, w, 3)
    return (a >> 8).astype(np.uint8) if high_bit else a.copy()


def compare_still(inp: str, out_png: str, styles: list[Style], t: float = 1.0,
                  strength: float = 1.0, max_short: int | None = 1080,
                  thumb_w: int = 540, tonemap: str = "mobius", retouch: float = 0.5,
                  *, recipe: Recipe | None = None) -> str:
    """Side-by-side contact sheet: original | style1 | style2 ... with labels."""
    base = recipe or Recipe(style=styles[0].name if styles else 'none', strength=strength,
                            retouch=RetouchCfg(retouch))
    base.validate()
    info = _deps().probe(inp)
    w, h = _deps().target_size(info, max_short)
    high_bit = info.high_bit or bool(info.hdr)
    frame = _grab_frame(info, t, w, h, high_bit, tonemap)
    tiles = [("原片", _to_u8(frame, w, h, high_bit))]
    renderer = _renderer_with_mask(frame, w, h, high_bit, base.retouch.level)
    if renderer.mask is None and any(st.skin_lut and st.skin_protect > 0 for st in styles):
        from ..face import analyze, to_small
        renderer.set_face(analyze(to_small(frame, w, h, high_bit)))
    for st in styles:
        r = Recipe.from_dict(base.to_dict())
        r.style = st.name
        renderer.apply_recipe(r, render_stamp(st, w, h, inp))
        rgb = np.frombuffer(renderer.render(frame, int(t * 30)), np.uint8).reshape(h, w, 3)
        tiles.append((st.title or st.name, rgb))
    renderer.release()
    return _save_sheet(tiles, out_png, thumb_w)


def _renderer_with_mask(frame, w, h, high_bit, retouch, opts=None) -> Renderer:
    r = _deps().Renderer(w, h, high_bit)
    r.set_retouch(retouch, **(opts or {}))
    if retouch > 0:
        from ..face import analyze, to_small
        r.set_face(analyze(to_small(frame, w, h, high_bit)))
    else:
        r.face_boxes = []
    return r


def compare_face(inp: str, out_png: str, style: Style | None, t: float = 1.0,
                 levels=(0.0, 0.5, 1.0), max_short: int | None = 1080, opts: dict | None = None,
                 tonemap: str = "mobius", *, recipe: Recipe | None = None) -> str:
    """Retouch check sheet. Row 1: full frames at each retouch level; row 2: 1:1 face crops."""
    from ..styles import Style as _S
    info = _deps().probe(inp)
    w, h = _deps().target_size(info, max_short)
    high_bit = info.high_bit or bool(info.hdr)
    frame = _grab_frame(info, t, w, h, high_bit, tonemap)
    st = style or _S(name="none", title="无风格", lut="", lut_strength=0.0)
    full, crops = [], []
    box = None
    base = recipe or Recipe(style=style.name if style else 'none',
                            retouch=RetouchCfg(spots=(opts or {}).get('spots'),
                                               eyes=(opts or {}).get('under'),
                                               keep_moles=(opts or {}).get('keep_moles', True),
                                               debug=(opts or {}).get('debug', False)))
    for lv in levels:
        r = _renderer_with_mask(frame, w, h, high_bit, lv, opts)
        variant = Recipe.from_dict(base.to_dict())
        variant.retouch.level = lv
        if style is None:
            r.set_style(_identity_style(), 0.0)
            r.set_retouch(lv, variant.retouch.spots, variant.retouch.eyes,
                          variant.retouch.keep_moles, variant.retouch.debug)
        else:
            variant.style = st.name
            r.apply_recipe(variant)
        rgb = np.frombuffer(r.render(frame, 0), np.uint8).reshape(h, w, 3)
        if box is None and r.face_boxes:
            box = max(r.face_boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
        r.release()
        label = "原片" if lv == 0 and style is None else f"精修 {lv:g}"
        full.append((label, rgb))
    if box is None:
        box = (0.3, 0.2, 0.7, 0.5)
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2 * w, (y0 + y1) / 2 * h
    side = int(max((x1 - x0) * w, (y1 - y0) * h) * 0.75)       # cheek-to-cheek, 1:1 pixels
    side = max(160, min(side, 720))
    cx0 = int(np.clip(cx - side / 2, 0, w - side))
    cy0 = int(np.clip(cy - side / 2, 0, h - side))
    zoom = 540 / side
    for label, rgb in full:
        crops.append((label + f" · 脸部放大 {zoom:.1f}×", rgb[cy0:cy0 + side, cx0:cx0 + side]))
    return _save_sheet(full, out_png, 540, extra_rows=[crops])


def _identity_style() -> Style:
    """A no-op style (identity LUT, no effects) for retouch-only renders."""
    from ..cube import identity
    from ..styles import Style as _S
    s = _S(name="identity", title="无风格", lut="")
    lut = identity(17).astype("f4")
    s.load_lut = lambda: lut          # type: ignore[method-assign]
    return s


def _save_sheet(tiles, out_png, thumb_w, extra_rows=()) -> str:
    from PIL import Image, ImageDraw, ImageFont
    h0, w0 = tiles[0][1].shape[:2]
    th = round(h0 * thumb_w / w0)
    rows = [[(lbl, Image.fromarray(a).resize((thumb_w, th), Image.LANCZOS)) for lbl, a in tiles]]
    for row in extra_rows:
        rows.append([(lbl, Image.fromarray(np.ascontiguousarray(a)).resize((thumb_w, thumb_w), Image.LANCZOS)
                      if a.shape[1] != thumb_w else Image.fromarray(np.ascontiguousarray(a)))
                     for lbl, a in row])
    pad, label_h = 12, 54
    width = pad + max(len(r) for r in rows) * (thumb_w + pad)
    height = sum(label_h + r[0][1].height + pad for r in rows)
    sheet = Image.new("RGB", (width, height), (24, 24, 24))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 30)
    except OSError:
        font = ImageFont.load_default()
    y = 0
    for row in rows:
        for i, (label, im) in enumerate(row):
            x = pad + i * (thumb_w + pad)
            sheet.paste(im, (x, y + label_h))
            draw.text((x + 4, y + 10), label, fill=(235, 235, 235), font=font)
        y += label_h + row[0][1].height + pad
    Path(out_png).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_png, quality=92)
    return out_png

