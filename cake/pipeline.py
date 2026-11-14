"""High-level operations: grade a whole video, or render before/after stills."""
from __future__ import annotations

import queue
import threading
import time
from pathlib import Path

import numpy as np

from .gpu import Renderer
from .media import Decoder, Encoder, pick_encoder, target_size
from .probe import ClipInfo, probe
from .styles import Style, render_stamp

_END = object()


class CancelledError(RuntimeError):
    pass


def _pump(src_iter, q: queue.Queue, errors: list):
    try:
        for item in src_iter:
            q.put(item)
    except Exception as e:  # pragma: no cover - surfaced in main thread
        errors.append(e)
    finally:
        q.put(_END)


def grade_video(inp: str, out: str, style: Style, strength: float = 1.0,
                max_short: int | None = 1080, start: float | None = None,
                duration: float | None = None, encoder: str = "auto",
                tonemap: str = "mobius", retouch: float = 0.5, retouch_opts: dict | None = None,
                log=print, analyzer=None, progress=None, cancel=None) -> dict:
    # progress(n_done, n_total_or_None) every 10 frames; cancel() -> True aborts the export
    """analyzer: pass a cake.face.Analyzer to reuse its warm worker processes across videos
    (batch mode); otherwise one is created (model start-up ~3-6 s) and closed here."""
    info = probe(inp)
    own_analyzer = False
    if retouch > 0 and analyzer is None:
        from .face import Analyzer
        analyzer = Analyzer(fps=float(info.fps))     # start loading models first: overlaps
        own_analyzer = True                          # with GL / encoder / decoder start-up
    elif retouch <= 0:
        analyzer = None
    if analyzer is not None:
        analyzer.reset(fps=float(info.fps))
    encoder = pick_encoder(encoder)
    w, h = target_size(info, max_short)
    high_bit = info.high_bit or bool(info.hdr)
    log(f"输入: {info.describe()}")
    log(f"输出: {w}x{h}, 风格={style.title or style.name}, 强度={strength:.2f}, "
        f"精修={retouch:.2f}, {'16bit' if high_bit else '8bit'} 处理, 编码器={encoder}")

    renderer = Renderer(w, h, high_bit)
    renderer.set_style(style, strength, render_stamp(style, w, h, inp))
    renderer.set_retouch(retouch, **(retouch_opts or {}))
    dec = Decoder(info, w, h, high_bit, start, duration, tonemap=tonemap)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    enc = Encoder(info, out, w, h, info.fps, encoder, start, duration)

    frames = iter(dec)
    if analyzer is not None:
        t_warm = time.perf_counter()
        analyzer.wait_ready()
        if time.perf_counter() - t_warm > 0.2:
            log(f"精修模型就绪 (又等了 {time.perf_counter() - t_warm:.1f}s)")

        def _submitting(src):
            for i, f in enumerate(src):
                analyzer.submit(f, w, h, high_bit, i)
                yield f, i
            analyzer.finish()
        frames = _submitting(frames)

    in_q: queue.Queue = queue.Queue(maxsize=12)   # look-ahead = frames analysed in parallel
    out_q: queue.Queue = queue.Queue(maxsize=6)
    errors: list = []
    reader = threading.Thread(target=_pump, args=(frames, in_q, errors), daemon=True)

    def _writer():
        try:
            while (buf := out_q.get()) is not _END:
                enc.write(buf)
        except Exception as e:
            errors.append(e)
            while out_q.get() is not _END:   # drain so the producer never blocks
                pass

    writer = threading.Thread(target=_writer, daemon=True)
    reader.start()
    writer.start()

    total = int((duration or max(0.0, info.duration - (start or 0))) * float(info.fps)) or None
    t0 = time.perf_counter()
    n = 0
    cancelled = False
    while (item := in_q.get()) is not _END:
        if analyzer:
            frame, idx = item
            renderer.set_face(analyzer.result(idx))
        else:
            frame = item
        out_q.put(renderer.render(frame, n, yuv=True))   # GPU does RGB -> I420 (Encoder default)
        n += 1
        if progress is not None and n % 10 == 0:
            progress(n, total)
        if cancel is not None and cancel():
            cancelled = True
            dec.kill()                                  # unblocks the reader thread
            while in_q.get() is not _END:               # drain so it can finish
                pass
            break
        if n % 60 == 0:
            fps = n / (time.perf_counter() - t0)
            pct = f"{100 * n / total:5.1f}%" if total else ""
            log(f"  {n}{'/' + str(total) if total else ''} 帧 {pct}  {fps:.1f} fps")
    out_q.put(_END)
    writer.join()
    reader.join()
    if analyzer is not None and own_analyzer:
        analyzer.close()
    dec_err = "" if cancelled else dec.close()
    code, enc_err = enc.close()
    renderer.release()
    elapsed = time.perf_counter() - t0
    if cancelled:
        Path(out).unlink(missing_ok=True)
        raise CancelledError("已取消")
    if errors or code != 0 or n == 0:
        raise RuntimeError(f"处理失败 (frames={n}, encoder exit={code})\n"
                           f"errors={errors}\ndecoder: {dec_err}\nencoder: {enc_err}")
    stats = {"frames": n, "seconds": elapsed, "fps": n / elapsed, "out": out}
    log(f"完成: {n} 帧, {elapsed:.1f}s, 平均 {n / elapsed:.1f} fps -> {out}")
    return stats


def _grab_frame(info: ClipInfo, t: float, w: int, h: int, high_bit: bool, tonemap: str) -> bytes:
    dec = Decoder(info, w, h, high_bit, start=t, frames=1, tonemap=tonemap)
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
                  thumb_w: int = 540, tonemap: str = "mobius", retouch: float = 0.5) -> str:
    """Side-by-side contact sheet: original | style1 | style2 ... with labels."""
    info = probe(inp)
    w, h = target_size(info, max_short)
    high_bit = info.high_bit or bool(info.hdr)
    frame = _grab_frame(info, t, w, h, high_bit, tonemap)
    tiles = [("原片", _to_u8(frame, w, h, high_bit))]
    renderer = _renderer_with_mask(frame, w, h, high_bit, retouch)
    for st in styles:
        renderer.set_style(st, strength, render_stamp(st, w, h, inp))
        rgb = np.frombuffer(renderer.render(frame, int(t * 30)), np.uint8).reshape(h, w, 3)
        tiles.append((st.title or st.name, rgb))
    renderer.release()
    return _save_sheet(tiles, out_png, thumb_w)


def _renderer_with_mask(frame, w, h, high_bit, retouch, opts=None) -> Renderer:
    r = Renderer(w, h, high_bit)
    r.set_retouch(retouch, **(opts or {}))
    if retouch > 0:
        from .face import analyze, to_small
        r.set_face(analyze(to_small(frame, w, h, high_bit)))
    else:
        r.face_boxes = []
    return r


def compare_face(inp: str, out_png: str, style: Style | None, t: float = 1.0,
                 levels=(0.0, 0.5, 1.0), max_short: int | None = 1080, opts: dict | None = None,
                 tonemap: str = "mobius") -> str:
    """Retouch check sheet. Row 1: full frames at each retouch level; row 2: 1:1 face crops."""
    from .styles import Style as _S
    info = probe(inp)
    w, h = target_size(info, max_short)
    high_bit = info.high_bit or bool(info.hdr)
    frame = _grab_frame(info, t, w, h, high_bit, tonemap)
    st = style or _S(name="none", title="无风格", lut="", lut_strength=0.0)
    full, crops = [], []
    box = None
    for lv in levels:
        r = _renderer_with_mask(frame, w, h, high_bit, lv, opts)
        if style is None:
            r.set_style(_identity_style(), 0.0)
        else:
            r.set_style(st, 1.0)
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
    from .cube import identity
    from .styles import Style as _S
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

