"""OpenGL (moderngl) renderer: raw RGB frame in -> graded RGB24 frame out."""
from __future__ import annotations

import numpy as np
import moderngl

from . import shaders
from .styles import Style


class Renderer:
    def __init__(self, w: int, h: int, high_bit: bool, yuv: tuple | None = None):
        """yuv=(matrix, range) e.g. ('bt709', 'tv'): frames passed to render() are I420."""
        self.w, self.h = w, h
        self.high_bit = high_bit
        self.yuv = yuv
        self.scale = min(w, h) / 1080.0
        ctx = self.ctx = moderngl.create_standalone_context(require=330)

        quad = ctx.buffer(np.array([-1, -1, 1, -1, -1, 1, 1, 1], dtype="f4").tobytes())

        def prog(frag):
            p = ctx.program(vertex_shader=shaders.VERT, fragment_shader=frag)
            return p, ctx.vertex_array(p, [(quad, "2f", "in_pos")])

        self.p_maskbuild, self.va_maskbuild = prog(shaders.MASKBUILD)
        self.p_heal, self.va_heal = prog(shaders.HEAL)
        self.p_skindown, self.va_skindown = prog(shaders.SKINDOWN)
        self.p_blur4, self.va_blur4 = prog(shaders.BLUR4)
        self.p_retouch, self.va_retouch = prog(shaders.RETOUCH)
        self.p_grade, self.va_grade = prog(shaders.GRADE)
        self.p_bright, self.va_bright = prog(shaders.BRIGHT)
        self.p_blur, self.va_blur = prog(shaders.BLUR)
        self.p_finish, self.va_finish = prog(shaders.FINISH)
        self.p_toyuv, self.va_toyuv = prog(shaders.TOYUV)

        # moderngl: 'u1'/'u2' are *integer* textures (read as 0 by sampler2D);
        # normalized formats are 'f1' (RGB8) and 'nu2' (RGB16).
        dtype = "nu2" if high_bit else "f1"
        self.src = ctx.texture((w, h), 3, dtype=dtype, alignment=1)
        self.src.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.p_yuv2rgb, self.va_yuv2rgb = prog(shaders.YUV2RGB)
        if yuv:
            self.planes = [ctx.texture(s, 1, dtype="f1", alignment=1)
                           for s in ((w, h), (w // 2, h // 2), (w // 2, h // 2))]
            for t in self.planes:
                t.filter = (moderngl.LINEAR, moderngl.LINEAR)
                t.repeat_x = t.repeat_y = False
            kr, kb = (0.299, 0.114) if yuv[0] == "bt601" else (0.2126, 0.0722)
            self._yuv_uniforms = dict(ytex=0, utex=1, vtex=2, kr=kr, kb=kb,
                                      full_range=1.0 if yuv[1] == "pc" else 0.0)
            self._plane_sizes = (w * h, w * h // 4)

        def rt(size):
            t = ctx.texture(size, 4, dtype="f2")
            t.filter = (moderngl.LINEAR, moderngl.LINEAR)
            t.repeat_x = t.repeat_y = False
            return t, ctx.framebuffer(color_attachments=[t])

        self.graded, self.fb_graded = rt((w, h))
        if yuv:
            self.srcrgb, self.fb_srcrgb = rt((w, h))
        self.inp = self.src            # the RGB input texture all passes read (per frame)
        self.retouched, self.fb_retouched = rt((w, h))
        self.healed, self.fb_healed = rt((w, h))
        hw, hh = max(1, w // 2), max(1, h // 2)          # half-res pyramid for blemish detection
        self.hsize = (hw, hh)
        self.h1, self.fb_h1 = rt((hw, hh))
        self.h2, self.fb_h2 = rt((hw, hh))
        self.hmed, self.fb_hmed = rt((hw, hh))
        self.hbase, self.fb_hbase = rt((hw, hh))
        self.skin = None
        self.skin_protect_scale = 1.0
        self._zero_skin = ctx.texture((1, 1), 1, data=bytes(1))
        self.skin_lut = None
        self.mask = None           # current assembled mask (RGBA16F, analysis resolution)
        self._mask_rt = None       # [(tex, fb), (tex, fb)] ping-pong for the temporal EMA
        self._seg_cache: list = [] # [(numpy array, texture)] - key frames are uploaded once
        self._layers = None
        self.face_h = 0.0
        self.face_boxes: list = []
        self.mask_alpha = 0.55     # EMA weight of the new frame
        self.retouch = 0.0
        self.spots = None          # None = follow retouch level
        self.under = None
        self.mole_keep = 1.0
        self.debug = 0.0
        bw, bh = max(1, w // 4), max(1, h // 4)
        self.bsize = (bw, bh)
        self.b1, self.fb_b1 = rt((bw, bh))
        self.b2, self.fb_b2 = rt((bw, bh))
        self.out = ctx.texture((w, h), 4, dtype="f1")
        self.fb_out = ctx.framebuffer(color_attachments=[self.out])
        self.out16, self.fb_out16 = rt((w, h))       # finish target for the YUV output path
        self._yuv = None
        self._pbo = None                             # pipelined readback (2 pixel buffers)
        self._pbo_i = 0
        self._pending = None

        self.lut = None
        self.stamp = ctx.texture((1, 1), 4, data=bytes(4))
        self.style: Style | None = None
        self.strength = 1.0

    # ------------------------------------------------------------- setup
    def set_style(self, style: Style, strength: float = 1.0, stamp_rgba: np.ndarray | None = None):
        self.style, self.strength = style, float(strength)
        lut = style.load_lut()                      # (n, n, n, 3) [b, g, r]
        n = lut.shape[0]
        if self.lut is not None:
            self.lut.release()
        self.lut = self.ctx.texture3d((n, n, n), 3, data=np.ascontiguousarray(lut, "f4").tobytes(),
                                      dtype="f4")
        self.lut.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.lut.repeat_x = self.lut.repeat_y = self.lut.repeat_z = False
        self.lut_size = float(n)
        from .cube import identity
        sl = style.load_skin_lut() if style.skin_lut else identity(2).astype("f4")
        sn = sl.shape[0]
        if self.skin_lut is not None:
            self.skin_lut.release()
        self.skin_lut = self.ctx.texture3d((sn, sn, sn), 3, data=np.ascontiguousarray(sl, "f4").tobytes(), dtype="f4")
        self.skin_lut.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.skin_lut.repeat_x = self.skin_lut.repeat_y = self.skin_lut.repeat_z = False
        self.skin_lut_size = float(sn)
        if stamp_rgba is not None:
            self.stamp.release()
            self.stamp = self.ctx.texture((self.w, self.h), 4, data=stamp_rgba.tobytes(), alignment=1)
            self.use_stamp = 1.0
        else:
            self.use_stamp = 0.0

    def set_retouch(self, level: float, spots: float | None = None, under: float | None = None,
                    keep_moles: bool = True, debug: bool = False):
        """level: 0 = off, 0.5 = natural (default), 1 = strong.
        spots / under: blemish removal / dark-circle strength 0..1 (None = derived from level)."""
        self.retouch = max(0.0, min(1.0, float(level)))
        self.spots, self.under = spots, under
        self.mole_keep = 1.0 if keep_moles else 0.0
        self.debug = 1.0 if debug else 0.0

    def _u8_tex(self, arr: np.ndarray):
        h, w, c = arr.shape
        t = self.ctx.texture((w, h), c, data=np.ascontiguousarray(arr).tobytes(), dtype="f1",
                             alignment=1)
        t.filter = (moderngl.LINEAR, moderngl.LINEAR)
        t.repeat_x = t.repeat_y = False
        return t

    def _seg_tex(self, arr: np.ndarray):
        for a, t in self._seg_cache:
            if a is arr:
                return t
        t = self._u8_tex(arr)
        self._seg_cache.append((arr, t))
        if len(self._seg_cache) > 3:
            self._seg_cache.pop(0)[1].release()
        return t

    def set_face(self, fi) -> None:
        """fi: cake.face.FaceInputs. Uploads what changed, assembles the mask + EMA on the GPU."""
        from .face import OFFS_SCALE
        h, w = fi.layers.shape[:2]
        if self._mask_rt is None or self._mask_rt[0][0].size != (w, h):
            for tex, skin, fb in self._mask_rt or []:
                fb.release()
                tex.release()
                skin.release()
            self._mask_rt = []
            for _ in range(2):
                tex = self.ctx.texture((w, h), 4, dtype="f2")
                tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
                tex.repeat_x = tex.repeat_y = False
                skin = self.ctx.texture((w, h), 4, dtype="f2")
                skin.filter = (moderngl.LINEAR, moderngl.LINEAR)
                skin.repeat_x = skin.repeat_y = False
                self._mask_rt.append((tex, skin, self.ctx.framebuffer(color_attachments=[tex, skin])))
            self.mask = None
            self.skin = None
            if self._layers is not None:
                self._layers.release()
            self._layers = self._u8_tex(fi.layers)
        else:
            self._layers.write(np.ascontiguousarray(fi.layers).tobytes())
        ta, tb = self._seg_tex(fi.seg_a), self._seg_tex(fi.seg_b)
        cur = 0 if self.mask is self._mask_rt[0][0] else 1
        dst_tex, dst_skin, dst_fb = self._mask_rt[1 - cur]
        prev = self._mask_rt[cur][0]          # never sample the texture being rendered into
        dst_fb.use()
        ta.use(0)
        tb.use(1)
        self._layers.use(2)
        prev.use(3)
        self._mask_rt[cur][1].use(4)
        alpha = 1.0 if (fi.reset or self.mask is None) else self.mask_alpha
        self._set(self.p_maskbuild, segA=0, segB=1, layers=2, prev=3, prev_skin=4, t=float(fi.t),
                  alpha=alpha, offs_scale=OFFS_SCALE)
        self.va_maskbuild.render(moderngl.TRIANGLE_STRIP)
        self.mask = dst_tex
        self.skin = dst_skin
        self.face_h = fi.face_h
        self.face_boxes = fi.boxes

    def _retouch_params(self):
        r = self.retouch
        face_px = self.face_h * self.h
        radius = face_px * (0.02 + 0.025 * r) if face_px > 0 else 6.0 * self.scale
        radius = float(np.clip(radius, 2.5 * self.scale, 40.0))
        return dict(radius=radius, smooth_amt=min(1.0, r * 1.1), keep=0.85 - 0.45 * r,
                    sigma=0.05 + 0.04 * r, lift=0.05 * r, rosy=r)

    def _blur(self, src_tex, dst_fb, sigma_px: float):
        """Separable gaussian on the half-res buffers; sigma in half-res px (9-tap ~ 2*step)."""
        hw, hh = self.hsize
        step = max(sigma_px, 0.05) / 2.0
        self.fb_h2.use()
        src_tex.use(0)
        self._set(self.p_blur4, src=0, dir=(step / hw, 0.0))
        self.va_blur4.render(moderngl.TRIANGLE_STRIP)
        dst_fb.use()
        self.h2.use(0)
        self._set(self.p_blur4, src=0, dir=(0.0, step / hh))
        self.va_blur4.render(moderngl.TRIANGLE_STRIP)

    def _heal(self, spots: float, under: float):
        face_px = self.face_h * self.h if self.face_h > 0 else 300 * self.scale
        spot_r = float(np.clip(face_px * 0.012, 1.5, 14.0))      # typical pimple radius, px
        # half-res, skin-weighted downsample (background / hair / eyes never leak into the blurs)
        self.fb_h1.use()
        self.inp.use(0)
        self.mask.use(1)
        self._set(self.p_skindown, src=0, mask=1, src_texel=(0.5 / self.w, 0.5 / self.h))
        self.va_skindown.render(moderngl.TRIANGLE_STRIP)
        s_med, s_base = spot_r * 0.8 / 2, spot_r * 3.0 / 2
        self._blur(self.h1, self.fb_hmed, s_med)
        self._blur(self.hmed, self.fb_hbase, float(np.sqrt(max(s_base ** 2 - s_med ** 2, 0.01))))
        self.fb_healed.use()
        self.inp.use(0)
        self.mask.use(1)
        self.hmed.use(2)
        self.hbase.use(3)
        self._set(self.p_heal, src=0, mask=1, med=2, base=3, spots=spots, under_amt=under,
                  mole_keep=self.mole_keep, debug=self.debug,
                  spot_off=(2.5 * spot_r / self.w, 0.6 * spot_r / self.h),
                  hstep=(spot_r / self.w, spot_r / self.h), texel=(1 / self.w, 1 / self.h))
        self.va_heal.render(moderngl.TRIANGLE_STRIP)

    def _upload(self, frame: bytes) -> None:
        """Upload one input frame; for I420 input convert to RGB on the GPU."""
        if not self.yuv:
            self.src.write(frame)
            self.inp = self.src
            return
        ny, nc = self._plane_sizes
        mv = memoryview(frame)
        self.planes[0].write(mv[:ny])
        self.planes[1].write(mv[ny:ny + nc])
        self.planes[2].write(mv[ny + nc:ny + 2 * nc])
        self.fb_srcrgb.use()
        for i, t in enumerate(self.planes):
            t.use(i)
        self._set(self.p_yuv2rgb, **self._yuv_uniforms)
        self.va_yuv2rgb.render(moderngl.TRIANGLE_STRIP)
        self.inp = self.srcrgb

    @staticmethod
    def _set(p, **kw):
        for k, v in kw.items():
            if k in p:
                p[k].value = v

    # ------------------------------------------------------------- render
    def render(self, frame: bytes, index: int, yuv: bool = False,
               pipelined: bool = False) -> bytes | None:
        """Returns packed RGB24, or (yuv=True) NV12, BT.709 limited range.
        pipelined=True (with yuv): returns the PREVIOUS frame (None for the first); call flush()
        at the end - overlaps the GPU->CPU copy with the next frame's work."""
        st = self.style
        self._upload(frame)
        base = self.inp

        # 0. retouch (needs a mask from cake.face): a) blemishes + dark circles, b) smoothing
        if self.retouch > 0 and self.mask is not None:
            r = self.retouch
            spots = min(1.0, 1.6 * r) if self.spots is None else self.spots
            under = min(0.8, 0.9 * r) if self.under is None else self.under
            heal_src = self.inp
            if (spots > 0 or under > 0) and self.mask.components >= 4:
                self._heal(spots, under)
                heal_src = self.healed
            self.fb_retouched.use()
            heal_src.use(0)
            self.mask.use(1)
            self._set(self.p_retouch, src=0, mask=1, texel=(1 / self.w, 1 / self.h),
                      **self._retouch_params())
            self.va_retouch.render(moderngl.TRIANGLE_STRIP)
            base = self.retouched

        # 1. grade
        self.fb_graded.use()
        base.use(0)
        self.lut.use(1)
        self.skin_lut.use(2)
        (self.skin if self.skin is not None else self._zero_skin).use(3)
        self._set(self.p_grade, src=0, lut=1, lut_size=self.lut_size, skin_lut=2,
                  skin_lut_size=self.skin_lut_size, skin_mask=3,
                  skin_protect=st.skin_protect * self.skin_protect_scale if st.skin_lut else 0.0,
                  strength=min(1.0, st.lut_strength * self.strength))
        self.va_grade.render(moderngl.TRIANGLE_STRIP)

        # 2. bloom / halation
        bloom_on = st.bloom_amount > 0
        if bloom_on:
            bw, bh = self.bsize
            self.fb_b1.use()
            self.graded.use(0)
            self._set(self.p_bright, src=0, src_texel=(1 / self.w, 1 / self.h),
                      threshold=st.bloom_threshold, knee=st.bloom_knee)
            self.va_bright.render(moderngl.TRIANGLE_STRIP)
            # radius is in 1080p pixels; bloom buffer is 1/4 res
            r = st.bloom_radius * self.scale / 4.0 / 4.0
            for i, mul in enumerate((1.0, 2.2)):
                self.fb_b2.use()
                self.b1.use(0)
                self._set(self.p_blur, src=0, dir=(r * mul / bw, 0.0))
                self.va_blur.render(moderngl.TRIANGLE_STRIP)
                self.fb_b1.use()
                self.b2.use(0)
                self._set(self.p_blur, src=0, dir=(0.0, r * mul / bh))
                self.va_blur.render(moderngl.TRIANGLE_STRIP)

        # 3. finish (into a half-float target when the YUV pass does the final quantisation)
        (self.fb_out16 if yuv else self.fb_out).use()
        self.graded.use(0)
        self.b1.use(1)
        self.stamp.use(2)
        fx = self.strength
        self._set(self.p_finish, graded=0, bloom=1, stamp=2,
                  res=(float(self.w), float(self.h)), scale=self.scale, frame=float(index % 4096),
                  fx=fx, ca=st.ca, soften=st.soften,
                  bloom_amount=st.bloom_amount if bloom_on else 0.0,
                  bloom_tint=tuple(st.bloom_tint),
                  vignette=st.vignette, vignette_soft=st.vignette_soft,
                  grain=st.grain, grain_size=st.grain_size, grain_chroma=st.grain_chroma,
                  use_stamp=self.use_stamp, dither_amt=0.0 if yuv else 1.0)
        self.va_finish.render(moderngl.TRIANGLE_STRIP)
        if not yuv:
            return self.fb_out.read(components=3, alignment=1)

        # 4. RGB -> NV12 on the GPU (Y plane, then interleaved CbCr at half resolution)
        if self._yuv is None:
            planes = []
            for size, comps in (((self.w, self.h), 1), ((self.w // 2, self.h // 2), 2)):
                t = self.ctx.texture(size, comps, dtype="f1")
                planes.append((t, self.ctx.framebuffer(color_attachments=[t]), comps))
            self._yuv = planes
        self.out16.use(0)
        if pipelined:
            # read into a pixel-buffer object: glReadPixels returns immediately, the copy runs
            # on the GPU while the CPU moves on; we hand back the PREVIOUS frame's buffer.
            if self._pbo is None:
                n = self.w * self.h * 3 // 2
                self._pbo = [self.ctx.buffer(reserve=n), self.ctx.buffer(reserve=n)]
            pbo = self._pbo[self._pbo_i]
            offset = 0
            for i, (t, fb, comps) in enumerate(self._yuv):
                fb.use()
                self._set(self.p_toyuv, src=0, src_texel=(1 / self.w, 1 / self.h),
                          plane=float(i), frame=float(index % 4096))
                self.va_toyuv.render(moderngl.TRIANGLE_STRIP)
                fb.read_into(pbo, components=comps, alignment=1, write_offset=offset)
                offset += t.width * t.height * comps
            prev, self._pending = self._pending, pbo
            self._pbo_i ^= 1
            return prev.read() if prev is not None else None
        parts = []
        for i, (t, fb, comps) in enumerate(self._yuv):
            fb.use()
            self._set(self.p_toyuv, src=0, src_texel=(1 / self.w, 1 / self.h), plane=float(i),
                      frame=float(index % 4096))
            self.va_toyuv.render(moderngl.TRIANGLE_STRIP)
            parts.append(fb.read(components=comps, alignment=1))
        return b"".join(parts)

    def flush(self) -> bytes | None:
        """Pipelined mode: return the last frame still in flight (call once after the loop)."""
        prev, self._pending = self._pending, None
        return prev.read() if prev is not None else None

    def release(self):
        self.ctx.release()
