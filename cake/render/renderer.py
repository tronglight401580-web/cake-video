"""Orchestrate registered render and face-update stages."""
from __future__ import annotations

from ..core.registry import registered_passes
from ..core.recipe import Recipe, RetouchCfg
from .context import RenderContext
from .frame import FrameContext
from ..analysis.smoothing import FaceTracker
from ..core.config import REGION_EMA_ALPHA
import numpy as np
from dataclasses import replace
from . import passes  # noqa: F401 - imports register built-in stages


class Renderer:
    def __init__(self, w: int, h: int, high_bit: bool, yuv: tuple | None = None):
        self.w, self.h, self.high_bit, self.yuv = w, h, high_bit, yuv
        self.scale = min(w, h) / 1080.0
        self._gl = RenderContext(w, h)
        self.ctx = self._gl.gl
        self._passes = [cls() for cls in registered_passes()]
        self._by_name = {p.name: p for p in self._passes}
        for p in self._passes:
            if p.name == 'input':
                p.dtype = 'nu2' if high_bit else 'f1'
                p.yuv = yuv
            p.setup(self._gl, w, h)
        self.mask = self.skin = None
        self.face_h = 0.0
        self.face_boxes = []
        self.mask_alpha = REGION_EMA_ALPHA
        self.skin_protect_scale = 1.0
        self.retouch = 0.0
        self.spots = self.under = None
        self.mole_keep = 1.0
        self.debug = 0.0
        self.style = None
        self.strength = 1.0
        self._face = None
        self._tracker = FaceTracker()
        self._region_slots = {}
        self._stamp_rgba = None
        self.recipe = Recipe()

    @staticmethod
    def _set(program, **values):
        RenderContext.uniforms(program, **values)

    def set_style(self, style, strength: float = 1.0, stamp_rgba=None):
        self.style, self.strength = style, float(strength)
        self._stamp_rgba = stamp_rgba
        self.recipe.style, self.recipe.strength = style.name, self.strength
        self._by_name['grade'].set_style(style)
        self._by_name['finish'].set_stamp(stamp_rgba)

    def set_retouch(self, level: float, spots: float | None = None, under: float | None = None,
                    keep_moles: bool = True, debug: bool = False):
        self.retouch = max(0.0, min(1.0, float(level)))
        self.spots, self.under = spots, under
        self.mole_keep = 1.0 if keep_moles else 0.0
        self.debug = 1.0 if debug else 0.0
        self.recipe.retouch = RetouchCfg(self.retouch, spots, under, keep_moles, debug)

    def apply_recipe(self, recipe: Recipe, stamp_rgba=None):
        from ..styles import load_style
        recipe.validate()
        style_changed = self.style is None or self.style.name != recipe.style
        self.set_style(self.style if self.style is not None and self.style.name == recipe.style
                       else load_style(recipe.style), recipe.strength,
                       stamp_rgba if stamp_rgba is not None else None if style_changed else self._stamp_rgba)
        r = recipe.retouch
        self.set_retouch(r.level, r.spots, r.eyes, r.keep_moles, r.debug)
        self.skin_protect_scale = recipe.skin_protect_scale
        self.recipe = Recipe.from_dict(recipe.to_dict())

    def _uniforms(self):
        return dict(scale=self.scale, mask_alpha=self.mask_alpha, skin_protect_scale=self.skin_protect_scale,
                    retouch=self.retouch, spots=self.spots, under=self.under,
                    mole_keep=self.mole_keep, debug=self.debug, face_h=self.face_h,
                    strength=self.strength)

    def set_face(self, fi):
        ah, aw = fi.layers.shape[:2]
        raw_landmarks = fi.landmarks or []
        scale = np.array([self.w / aw, self.h / ah], np.float32)
        output_landmarks = [np.asarray(face, np.float32) * scale for face in raw_landmarks]
        smoothed = self._tracker.update(output_landmarks, fi.dt, fi.reset)
        normalizer = np.array([self.w, self.h], np.float32)
        face = replace(fi, landmarks=smoothed,
                       landmarks_norm=[np.clip(points / normalizer, 0, 1)
                                       for points in smoothed])
        self._face = face
        fc = FrameContext(self.recipe, 0, self.w, self.h, face=face,
                          uniforms={**self._uniforms(), 'style': self.style})
        for p in self._passes:
            if getattr(p, 'stage', 'frame') == 'face' and p.enabled(fc.recipe, fc):
                p.run(fc)
        self.mask, self.skin = fc.textures.get('mask'), fc.textures.get('skin')
        self._region_slots = {key: value for key, value in fc.textures.items()
                              if key.startswith('region:')}
        self.face_h, self.face_boxes = fi.face_h, fi.boxes

    def render(self, frame: bytes, index: int, yuv: bool = False,
               pipelined: bool = False) -> bytes | None:
        slots = {}
        if self.mask is not None:
            slots['mask'] = self.mask
        if self.skin is not None:
            slots['skin'] = self.skin
        slots.update(self._region_slots)
        fc = FrameContext(self.recipe, index, self.w, self.h, face=self._face,
                          textures=slots, uniforms={**self._uniforms(), 'style': self.style}, frame=frame,
                          yuv=yuv, pipelined=pipelined)
        for p in self._passes:
            if getattr(p, 'stage', 'frame') == 'frame' and p.enabled(fc.recipe, fc):
                p.run(fc)
        return fc.result

    def flush(self) -> bytes | None:
        return self._by_name['output'].flush()

    def release(self):
        for p in self._passes:
            p.release()
        self.ctx.release()
