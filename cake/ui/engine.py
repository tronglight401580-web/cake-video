"""Preview engine: one QThread owns the decoder, the GL renderer and the analysis processes.

The UI never touches those objects; it sends commands (queue) and receives frames (signal).
While paused, parameter changes re-render the current frame immediately.
"""
from __future__ import annotations

import queue
import threading
import time
from copy import deepcopy
from collections import deque
from dataclasses import dataclass, field, replace

import numpy as np
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from ..gpu import Renderer
from ..media import Decoder, target_size
from ..probe import probe
from ..styles import load_style, render_stamp

from ..core.config import PREVIEW_SHORT, PREVIEW_PLAY_SHORT, PREVIEW_PLAY_PORTRAIT_SHORT, LOOKAHEAD
from ..core.recipe import Recipe, RetouchCfg


@dataclass
class Params:
    style: str = "film_warm"
    strength: float = 1.0
    retouch: float = 0.5
    skin_protect_scale: float = 1.0
    spots: float | None = None
    eyes: float | None = None
    keep_moles: bool = True
    debug: bool = False
    demo_tint: float = 0.0
    extra: dict = field(default_factory=dict)


def _qimage(rgb: bytes | np.ndarray, w: int, h: int) -> QImage:
    a = np.ascontiguousarray(rgb if isinstance(rgb, np.ndarray) else
                             np.frombuffer(rgb, np.uint8).reshape(h, w, 3))
    return QImage(a.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


class PreviewEngine(QThread):
    frame_ready = Signal(QImage, QImage, float, float)   # graded, original, t (s), render ms
    clip_loaded = Signal(dict)
    playing_changed = Signal(bool)
    status = Signal(str)
    error = Signal(str)
    playback_stats = Signal(float, int)

    def __init__(self):
        super().__init__()
        self.cmds: queue.Queue = queue.Queue()
        self.params = Params()
        self.recipe = Recipe(style='film_warm')

    # ---------------------------------------------------------------- UI-side API (any thread)
    def load(self, path: str, t: float = 0.0):
        self.cmds.put(("load", path, t))

    def play(self):
        self.cmds.put(("play", time.perf_counter()))

    def pause(self):
        self.cmds.put(("pause",))

    def seek(self, t: float):
        self.cmds.put(("seek", t))

    def set_params(self, **kw):
        data = self.recipe.to_dict()
        for key, value in kw.items():
            if key in ('retouch', 'spots', 'eyes', 'keep_moles', 'debug'):
                data['retouch'][{'retouch': 'level'}.get(key, key)] = value
            elif key == 'demo_tint':
                data['sections']['demo_tint']['amount'] = value
            elif key in data:
                data[key] = value
        self.set_recipe(Recipe.from_dict(data))

    def set_recipe(self, recipe: Recipe):
        recipe.validate()
        self.recipe = Recipe.from_dict(recipe.to_dict())
        self.cmds.put(('recipe', self.recipe))

    def step(self, delta: int):
        """Paused: show the next (+1) or previous (-1) frame."""
        self.cmds.put(("step", delta))

    def stop(self):
        self.cmds.put(("stop",))
        self.wait(5000)

    # ---------------------------------------------------------------- engine thread
    def run(self):
        self.info = None
        self.renderer = None
        self.analyzer = None
        self.dec = None
        self.dec_iter = None
        self.buf: deque = deque()
        self.dec_queue = None
        self.dec_thread = None
        self.dec_stop = None
        self.compare = True
        self.displayed = self.dropped = 0
        self.render_seconds = 1 / 30
        self.skipped_since_render = 0
        self.playing = False
        self.last = None                     # (frame bytes, index) currently shown
        self.base_t = 0.0                    # clip time of internal index 0
        self.next_idx = 0
        self.eof = False
        self.t_play0 = 0.0
        self.idx_play0 = 0
        running = True
        try:
            # start the retouch worker processes right away (~3-6 s) - while the user is still
            # picking files - instead of on the first clip
            if self.params.retouch > 0:
                from ..face import Analyzer
                self.status.emit("正在后台加载精修模型…")
                self.analyzer = Analyzer()
                self.analyzer.wait_ready()
                self.status.emit("精修模型就绪")
            while running:
                try:
                    cmd = self.cmds.get(timeout=0 if self.playing else 0.05)
                except queue.Empty:
                    cmd = None
                if cmd:
                    running = self._handle(cmd)
                    continue                 # drain all pending commands before rendering
                if self.playing:
                    self._play_step()
        except Exception as e:               # surface to the UI instead of dying silently
            import traceback
            self.error.emit(f"{e}\n{traceback.format_exc()}")
        finally:
            self._close_decoder()
            if self.analyzer is not None:
                self.analyzer.close()
            if self.renderer is not None:
                self.renderer.release()

    def _handle(self, cmd) -> bool:
        kind = cmd[0]
        if kind == "stop":
            return False
        if kind == "load":
            self._load(cmd[1], cmd[2])
        elif kind == "play" and self.info:
            reshape = getattr(self.params, 'sections', {}).get('reshape', {})
            slim = reshape.get('slim', 0) if isinstance(reshape, dict) else reshape.slim
            eyes = reshape.get('eyes', 0) if isinstance(reshape, dict) else reshape.eyes
            short = (PREVIEW_PLAY_PORTRAIT_SHORT if self.info.height > self.info.width
                     else PREVIEW_PLAY_SHORT) if (slim or eyes) else PREVIEW_SHORT
            self._set_preview_size(short)
            if self.eof and not self.buf:
                self._open_at(0.0)
            self.playing = True
            # Resizing restarts the decoder and renderer. Start the playback
            # clock after that work so setup does not count as late video.
            self.t_play0, self.idx_play0 = time.perf_counter(), self.next_display_idx()
            self.displayed = self.dropped = 0
            self.skipped_since_render = 0
            self.playing_changed.emit(True)
        elif kind == "pause":
            self.playing = False
            if self._set_preview_size(PREVIEW_SHORT):
                self._show_next()
            self.playing_changed.emit(False)
        elif kind == "compare":
            self.compare = cmd[1]
            if self.compare and not self.playing and self.last is not None:
                self._render_and_emit(*self.last, reanalyze=False)
        elif kind == "seek" and self.info:
            self._open_at(cmd[1])
            if not self.playing:
                self._show_next()
            else:
                self.t_play0, self.idx_play0 = time.perf_counter(), 0
        elif kind == "step" and self.info and not self.playing and self.last is not None:
            if cmd[1] > 0:
                self._show_next()
            else:
                t = self.base_t + (self.last[1] - 1) / float(self.info.fps)
                self._open_at(max(0.0, t))
                self._show_next()
        elif kind == "params":
            self._apply_params(cmd[1])
            if not self.playing and self.last is not None:
                self._render_and_emit(*self.last, reanalyze=False)
        elif kind == 'recipe':
            r = cmd[1]
            self._apply_params(dict(style=r.style, strength=r.strength, retouch=r.retouch.level,
                                    spots=r.retouch.spots, eyes=r.retouch.eyes,
                                    keep_moles=r.retouch.keep_moles, debug=r.retouch.debug,
                                    skin_protect_scale=r.skin_protect_scale, demo_tint=r.demo_tint.amount, sections=r.to_dict()['sections']))
            if not self.playing and self.last is not None:
                self._render_and_emit(*self.last, reanalyze=False)
        return True

    # ---------------------------------------------------------------- clip / decoder
    def _load(self, path: str, t: float):
        self.playing = False
        self.playing_changed.emit(False)
        self.info = probe(path)
        w, h = target_size(self.info, PREVIEW_SHORT)
        self.w, self.h = w, h
        self.high_bit = self.info.high_bit or bool(self.info.hdr)
        if self.renderer is not None:
            self.renderer.release()
        self.renderer = Renderer(w, h, self.high_bit)
        self._apply_params({}, force_style=True)
        self.clip_loaded.emit({"path": path, "duration": self.info.duration,
                               "fps": float(self.info.fps), "width": self.info.width,
                               "height": self.info.height, "desc": self.info.describe()})
        self._open_at(t)
        self._show_next()

    def set_compare(self, enabled: bool):
        self.cmds.put(("compare", enabled))

    def _set_preview_size(self, short: int):
        w, h = target_size(self.info, short)
        if (w, h) == (self.w, self.h):
            return False
        t = self.base_t + (self.last[1] if self.last else self.next_display_idx()) / float(self.info.fps)
        self._close_decoder()
        self.renderer.release()
        self.w, self.h = w, h
        self.renderer = Renderer(w, h, self.high_bit)
        self._apply_params({}, force_style=True)
        self._open_at(t)
        self.last = None
        return True

    def _close_decoder(self):
        if self.dec is not None:
            self.dec.kill()
        if self.dec_stop is not None:
            self.dec_stop.set()
        if self.dec_thread is not None:
            self.dec_thread.join(timeout=2)
        self.dec = self.dec_iter = None
        self.dec_queue = self.dec_thread = self.dec_stop = None
        self.buf.clear()

    def _open_at(self, t: float):
        self._close_decoder()
        t = max(0.0, min(t, max(0.0, self.info.duration - 0.05)))
        self.base_t = t
        self.dec = Decoder(self.info, self.w, self.h, self.high_bit, start=t or None)
        self.dec_iter = iter(self.dec)
        self.dec_queue = queue.Queue(maxsize=max(LOOKAHEAD, round(2 * float(self.info.fps))))
        self.dec_stop = threading.Event()
        dec_iter, dec_queue, dec_stop = self.dec_iter, self.dec_queue, self.dec_stop
        def decode():
            try:
                for frame in dec_iter:
                    while not dec_stop.is_set():
                        try:
                            dec_queue.put(frame, timeout=.05)
                            break
                        except queue.Full:
                            pass
                    if dec_stop.is_set():
                        break
            finally:
                while not dec_stop.is_set():
                    try:
                        dec_queue.put(None, timeout=.05)
                        break
                    except queue.Full:
                        pass
        self.dec_thread = threading.Thread(target=decode, name="preview-decode", daemon=True)
        self.dec_thread.start()
        self.next_idx = 0
        self.eof = False
        if self.analyzer is not None:
            self.analyzer.reset(fps=float(self.info.fps))

    def next_display_idx(self) -> int:
        return self.buf[0][1] if self.buf else self.next_idx

    def _fill(self, wait: float = 0):
        while len(self.buf) < LOOKAHEAD and not self.eof:
            try:
                f = self.dec_queue.get(timeout=wait)
            except queue.Empty:
                break
            if f is None:
                self.eof = True
                if self.analyzer is not None:
                    self.analyzer.finish()
                break
            if self._retouch_on():
                self.analyzer.submit(f, self.w, self.h, self.high_bit, self.next_idx)
            self.buf.append((f, self.next_idx))
            self.next_idx += 1

    def _show_next(self) -> bool:
        self._fill(wait=1.0)
        if not self.buf:
            return False
        f, idx = self.buf.popleft()
        self._render_and_emit(f, idx, reanalyze=True)
        return True

    def _play_step(self):
        self._fill()
        if not self.buf:
            if not self.eof:
                time.sleep(.002)
                return
            self.playing = False
            self.playing_changed.emit(False)
            if self._set_preview_size(PREVIEW_SHORT):
                self._show_next()
            return
        period = 1 / float(self.info.fps)
        while self.buf:
            f, idx = self.buf[0]
            due = self.t_play0 + (idx - self.idx_play0) * period
            if time.perf_counter() + self.render_seconds > due + period:
                self.buf.popleft()
                if self._retouch_on():
                    self._advance_skipped(idx)
                self.dropped += 1
                self._fill()
                continue
            break
        if not self.buf:
            return
        f, idx = self.buf.popleft()
        due = self.t_play0 + (idx - self.idx_play0) * period
        wait = due - self.render_seconds - time.perf_counter()
        if wait > 0:
            time.sleep(min(wait, period))
        start = time.perf_counter()
        self._render_and_emit(f, idx, reanalyze=True)
        self.render_seconds = .8 * self.render_seconds + .2 * (time.perf_counter() - start)
        wait = due - time.perf_counter()
        if wait > 0:
            time.sleep(wait)
        self.displayed += 1
        elapsed = max(time.perf_counter() - self.t_play0, period)
        self.playback_stats.emit(self.displayed / elapsed, self.dropped)

    def _advance_skipped(self, idx: int):
        """Advance CPU trackers; collapse GPU EMA updates into the next shown frame."""
        fi = self.analyzer.result(idx)
        ah, aw = fi.layers.shape[:2]
        scale = np.array([self.w / aw, self.h / ah], np.float32)
        points = [np.asarray(face, np.float32) * scale for face in (fi.landmarks or [])]
        smoothed = self.renderer._tracker.update(points, fi.dt, fi.reset)
        warp = self.renderer._by_name.get('warp')
        if warp is not None:
            warp._update_tracks(replace(fi, landmarks=smoothed))
            warp.history_valid = False
        self.skipped_since_render += 1

    # ---------------------------------------------------------------- rendering
    def _retouch_on(self) -> bool:
        reshape = getattr(self.params, 'sections', {}).get('reshape', {})
        slim = reshape.get('slim', 0) if isinstance(reshape, dict) else reshape.slim
        eyes = reshape.get('eyes', 0) if isinstance(reshape, dict) else reshape.eyes
        return self.analyzer is not None and (self.params.retouch > 0 or bool(self.renderer and self.renderer.style and self.renderer.style.skin_lut and self.renderer.style.skin_protect > 0) or bool(slim or eyes))

    def _apply_params(self, kw: dict, force_style: bool = False):
        old_style = self.params.style
        for k, v in kw.items():
            setattr(self.params, k, v)
        p = self.params
        if 'demo_tint' in kw and 'sections' not in kw and hasattr(p, 'sections'):
            p.sections['demo_tint']['amount'] = kw['demo_tint']
        if self.renderer is None:
            return
        st = load_style(p.style)
        stamp = render_stamp(st, self.w, self.h, self.info.path) if force_style or p.style != old_style else None
        self.renderer.apply_recipe(Recipe(style=p.style, strength=p.strength,
                                          retouch=RetouchCfg(p.retouch, p.spots, p.eyes,
                                                             p.keep_moles, p.debug),
                                          skin_protect_scale=p.skin_protect_scale, sections=deepcopy(getattr(p, 'sections', {'demo_tint': {'amount': p.demo_tint}}))), stamp)
        reshape = getattr(p, 'sections', {}).get('reshape', {})
        slim = reshape.get('slim', 0) if isinstance(reshape, dict) else reshape.slim
        eyes = reshape.get('eyes', 0) if isinstance(reshape, dict) else reshape.eyes
        if (p.retouch > 0 or (self.renderer.style.skin_lut and self.renderer.style.skin_protect > 0) or slim or eyes) and self.analyzer is None:
            from ..face import Analyzer
            self.status.emit("正在加载精修模型（首次约 3～6 秒）…")
            self.analyzer = Analyzer(fps=float(self.info.fps))
            self.analyzer.wait_ready()
            self.status.emit("精修模型就绪")
            # frames already buffered were never submitted: restart from the current position
            if self.info is not None and (self.buf or self.last is not None):
                cur_t = self.base_t + (self.last[1] if self.last else 0) / float(self.info.fps)
                self._open_at(cur_t)
                if not self.playing:
                    self.last = None
                    self._show_next()

    def _render_and_emit(self, f: bytes, idx: int, reanalyze: bool):
        t0 = time.perf_counter()
        if self._retouch_on() and reanalyze:
            normal_alpha = self.renderer.mask_alpha
            if self.skipped_since_render:
                self.renderer.mask_alpha = 1 - (1 - normal_alpha) ** (self.skipped_since_render + 1)
            self.renderer.set_face(self.analyzer.result(idx))
            self.renderer.mask_alpha = normal_alpha
            self.skipped_since_render = 0
        elif not self._retouch_on():
            self.renderer.mask = None
            self.renderer.skin = None
        out = self.renderer.render(f, idx + (round(self.base_t * float(self.info.fps)) if self.renderer.style.shots else 0))
        ms = (time.perf_counter() - t0) * 1000
        original = QImage()
        if self.compare:
            orig = np.frombuffer(f, np.uint16 if self.high_bit else np.uint8).reshape(self.h, self.w, 3)
            if self.high_bit:
                orig = (orig >> 8).astype(np.uint8)
            original = _qimage(orig, self.w, self.h)
        self.last = (f, idx)
        t = self.base_t + idx / float(self.info.fps)
        self.frame_ready.emit(_qimage(out, self.w, self.h), original, t, ms)
