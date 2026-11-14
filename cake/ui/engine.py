"""Preview engine: one QThread owns the decoder, the GL renderer and the analysis processes.

The UI never touches those objects; it sends commands (queue) and receives frames (signal).
While paused, parameter changes re-render the current frame immediately.
"""
from __future__ import annotations

import queue
import time
from collections import deque
from dataclasses import dataclass, field

import numpy as np
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from ..gpu import Renderer
from ..media import Decoder, target_size
from ..probe import probe
from ..styles import load_style, render_stamp

from ..core.config import PREVIEW_SHORT, LOOKAHEAD
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

    def __init__(self):
        super().__init__()
        self.cmds: queue.Queue = queue.Queue()
        self.params = Params()
        self.recipe = Recipe(style='film_warm')

    # ---------------------------------------------------------------- UI-side API (any thread)
    def load(self, path: str, t: float = 0.0):
        self.cmds.put(("load", path, t))

    def play(self):
        self.cmds.put(("play",))

    def pause(self):
        self.cmds.put(("pause",))

    def seek(self, t: float):
        self.cmds.put(("seek", t))

    def set_params(self, **kw):
        data = self.recipe.to_dict()
        for key, value in kw.items():
            if key in ('retouch', 'spots', 'eyes', 'keep_moles', 'debug'):
                data['retouch'][{'retouch': 'level'}.get(key, key)] = value
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
            if self.eof and not self.buf:
                self._open_at(0.0)
            self.playing = True
            self.t_play0, self.idx_play0 = time.perf_counter(), self.next_display_idx()
            self.playing_changed.emit(True)
        elif kind == "pause":
            self.playing = False
            self.playing_changed.emit(False)
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
                                    skin_protect_scale=r.skin_protect_scale, demo_tint=r.demo_tint))
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

    def _close_decoder(self):
        if self.dec is not None:
            self.dec.kill()
        self.dec = self.dec_iter = None
        self.buf.clear()

    def _open_at(self, t: float):
        self._close_decoder()
        t = max(0.0, min(t, max(0.0, self.info.duration - 0.05)))
        self.base_t = t
        self.dec = Decoder(self.info, self.w, self.h, self.high_bit, start=t or None)
        self.dec_iter = iter(self.dec)
        self.next_idx = 0
        self.eof = False
        if self.analyzer is not None:
            self.analyzer.reset(fps=float(self.info.fps))

    def next_display_idx(self) -> int:
        return self.buf[0][1] if self.buf else self.next_idx

    def _fill(self):
        while len(self.buf) < LOOKAHEAD and not self.eof:
            f = next(self.dec_iter, None)
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
        self._fill()
        if not self.buf:
            return False
        f, idx = self.buf.popleft()
        self._render_and_emit(f, idx, reanalyze=True)
        return True

    def _play_step(self):
        self._fill()
        if not self.buf:
            self.playing = False
            self.playing_changed.emit(False)
            return
        f, idx = self.buf.popleft()
        self._render_and_emit(f, idx, reanalyze=True)
        # pace to the clip frame rate (if rendering is slower we simply play slower)
        due = self.t_play0 + (idx - self.idx_play0) / float(self.info.fps)
        wait = due - time.perf_counter()
        if wait > 0:
            time.sleep(min(wait, 0.1))

    # ---------------------------------------------------------------- rendering
    def _retouch_on(self) -> bool:
        return self.analyzer is not None and (self.params.retouch > 0 or bool(self.renderer and self.renderer.style and self.renderer.style.skin_lut and self.renderer.style.skin_protect > 0))

    def _apply_params(self, kw: dict, force_style: bool = False):
        old_style = self.params.style
        for k, v in kw.items():
            setattr(self.params, k, v)
        p = self.params
        if self.renderer is None:
            return
        st = load_style(p.style)
        stamp = render_stamp(st, self.w, self.h, self.info.path) if force_style or p.style != old_style else None
        self.renderer.apply_recipe(Recipe(style=p.style, strength=p.strength,
                                          retouch=RetouchCfg(p.retouch, p.spots, p.eyes,
                                                             p.keep_moles, p.debug),
                                          skin_protect_scale=p.skin_protect_scale, demo_tint=p.demo_tint), stamp)
        if (p.retouch > 0 or (self.renderer.style.skin_lut and self.renderer.style.skin_protect > 0)) and self.analyzer is None:
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
            self.renderer.set_face(self.analyzer.result(idx))
        elif not self._retouch_on():
            self.renderer.mask = None
            self.renderer.skin = None
        out = self.renderer.render(f, idx)
        ms = (time.perf_counter() - t0) * 1000
        orig = np.frombuffer(f, np.uint16 if self.high_bit else np.uint8).reshape(self.h, self.w, 3)
        if self.high_bit:
            orig = (orig >> 8).astype(np.uint8)
        self.last = (f, idx)
        t = self.base_t + idx / float(self.info.fps)
        self.frame_ready.emit(_qimage(out, self.w, self.h), _qimage(orig, self.w, self.h), t, ms)
