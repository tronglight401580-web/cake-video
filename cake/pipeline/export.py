from __future__ import annotations
import queue, threading, time
from pathlib import Path
import numpy as np
from ..core.config import CAKE_YUV
from ..core.bus import bus
from ..styles import Style, render_stamp
from ..probe import ClipInfo
from . import _deps

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
                log=print, analyzer=None, progress=None, cancel=None, skin_protect_scale=1.0) -> dict:
    # progress(n_done, n_total_or_None) every 10 frames; cancel() -> True aborts the export
    """analyzer: pass a cake.face.Analyzer to reuse its warm worker processes across videos
    (batch mode); otherwise one is created (model start-up ~3-6 s) and closed here."""
    old_log, old_progress = log, progress
    def log(message):
        bus.publish('log', message=message)
        if old_log is not None:
            old_log(message)
    def progress(done, total):
        bus.publish('progress', done=done, total=total)
        if old_progress is not None:
            old_progress(done, total)
    bus.publish('status', status='started', input=inp, output=out)
    info = _deps().probe(inp)
    own_analyzer = False
    needs_analysis = retouch > 0 or bool(style.skin_lut and style.skin_protect > 0)
    if needs_analysis and analyzer is None:
        from ..face import Analyzer
        analyzer = Analyzer(fps=float(info.fps))     # start loading models first: overlaps
        own_analyzer = True                          # with GL / encoder / decoder start-up
    elif not needs_analysis:
        analyzer = None
    if analyzer is not None:
        analyzer.reset(fps=float(info.fps))
    encoder = _deps().pick_encoder(encoder)
    w, h = _deps().target_size(info, max_short)
    high_bit = info.high_bit or bool(info.hdr)
    log(f"输入: {info.describe()}")
    log(f"输出: {w}x{h}, 风格={style.title or style.name}, 强度={strength:.2f}, "
        f"精修={retouch:.2f}, {'16bit' if high_bit else '8bit'} 处理, 编码器={encoder}")

    # GPU YUV->RGB input path: measured no gain while the GPU is the bottleneck (retouch on),
    # slower on 720p -> opt-in via CAKE_YUV=1
    yuv = _deps().source_matrix(info) if (CAKE_YUV and _deps().yuv_capable(info, high_bit)) else None
    renderer = _deps().Renderer(w, h, high_bit, yuv)
    renderer.set_style(style, strength, render_stamp(style, w, h, inp))
    renderer.skin_protect_scale = skin_protect_scale
    renderer.set_retouch(retouch, **(retouch_opts or {}))
    dec = _deps().Decoder(info, w, h, high_bit, start, duration, tonemap=tonemap, yuv=yuv is not None)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    enc = _deps().Encoder(info, out, w, h, info.fps, encoder, start, duration)

    frames = iter(dec)
    if analyzer is not None:
        t_warm = time.perf_counter()
        analyzer.wait_ready()
        if time.perf_counter() - t_warm > 0.2:
            log(f"精修模型就绪 (又等了 {time.perf_counter() - t_warm:.1f}s)")

        def _submitting(src):
            for i, f in enumerate(src):
                analyzer.submit(f, w, h, high_bit, i, yuv)
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
        # GPU converts to NV12; pipelined readback hands back the previous frame (None at first)
        done = renderer.render(frame, n, yuv=True, pipelined=True)
        if done is not None:
            out_q.put(done)
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
    last = renderer.flush()                             # the frame still in flight
    if last is not None and not cancelled:
        out_q.put(last)
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
    bus.publish('status', status='completed', **stats)
    return stats

