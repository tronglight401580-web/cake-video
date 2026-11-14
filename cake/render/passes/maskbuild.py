"""Maskbuild rendering stage."""
from ..context import COMMON

MASKBUILD = COMMON.replace("out vec4 o;", "layout(location = 0) out vec4 o;\nlayout(location = 1) out vec4 o2;") + """
uniform sampler2D segA;
uniform sampler2D segB;
uniform sampler2D layers;
uniform sampler2D prev;
uniform sampler2D prev_skin;
uniform float t;
uniform float alpha;         // 1 = no history (first frame / scene cut)
uniform float offs_scale;
void main() {
    vec2 s = mix(texture(segA, uv).rg, texture(segB, uv).rg, t);
    float face = s.r, body = s.g;
    vec4 L = texture(layers, uv);
    float smooth_w = (face * (1.0 - L.r) + body * 0.6) * (1.0 - 0.9 * L.g);
    float tone = clamp(face + body, 0.0, 1.0) * (1.0 - 0.5 * L.r);
    float under = L.b * clamp(face * 1.5, 0.0, 1.0);
    vec4 m = vec4(clamp(smooth_w, 0.0, 1.0), tone, under, L.a / offs_scale);
    // alpha = 1: ignore history entirely (it may be uninitialised memory, even NaN)
    o = (alpha >= 0.999) ? m : mix(texture(prev, uv), m, alpha);
    vec4 skin = vec4(clamp(face + body, 0.0, 1.0), 0.0, 0.0, 1.0);
    o2 = (alpha >= 0.999) ? skin : mix(texture(prev_skin, uv), skin, alpha);
}
"""

import numpy as np
import moderngl
from ...core.registry import Pass, register_pass


@register_pass('maskbuild', 200)
class MaskBuild(Pass):
    reads, writes = ('seg_a', 'seg_b', 'layers'), ('mask', 'skin')
    stage = 'face'

    def setup(self, gl, width, height):
        self.gl = gl
        self.program, self.va = gl.program(MASKBUILD)
        self.mask = self.skin = self.layers = None
        self.mask_rt = None
        self.seg_cache = []

    def u8_tex(self, arr):
        h, w, c = arr.shape
        tex = self.gl.gl.texture((w, h), c, data=np.ascontiguousarray(arr).tobytes(),
                                 dtype='f1', alignment=1)
        tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        tex.repeat_x = tex.repeat_y = False
        return tex

    def seg_tex(self, arr):
        for old, tex in self.seg_cache:
            if old is arr:
                return tex
        tex = self.u8_tex(arr)
        self.seg_cache.append((arr, tex))
        if len(self.seg_cache) > 3:
            self.seg_cache.pop(0)[1].release()
        return tex

    def run(self, frame_ctx):
        from ...face import OFFS_SCALE
        fi = frame_ctx.face
        h, w = fi.layers.shape[:2]
        if self.mask_rt is None or self.mask_rt[0][0].size != (w, h):
            for tex, skin, fb in self.mask_rt or []:
                fb.release(); tex.release(); skin.release()
            self.mask_rt = []
            for _ in range(2):
                tex = self.gl.gl.texture((w, h), 4, dtype='f2')
                tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
                tex.repeat_x = tex.repeat_y = False
                skin = self.gl.gl.texture((w, h), 4, dtype='f2')
                skin.filter = (moderngl.LINEAR, moderngl.LINEAR)
                skin.repeat_x = skin.repeat_y = False
                self.mask_rt.append((tex, skin, self.gl.gl.framebuffer(color_attachments=[tex, skin])))
            self.mask = self.skin = None
            if self.layers is not None:
                self.layers.release()
            self.layers = self.u8_tex(fi.layers)
        else:
            self.layers.write(np.ascontiguousarray(fi.layers).tobytes())
        ta, tb = self.seg_tex(fi.seg_a), self.seg_tex(fi.seg_b)
        cur = 0 if self.mask is self.mask_rt[0][0] else 1
        dst_tex, dst_skin, dst_fb = self.mask_rt[1 - cur]
        prev = self.mask_rt[cur][0]
        dst_fb.use()
        ta.use(0); tb.use(1); self.layers.use(2); prev.use(3); self.mask_rt[cur][1].use(4)
        alpha = 1.0 if (fi.reset or self.mask is None) else frame_ctx.uniforms['mask_alpha']
        self.gl.uniforms(self.program, segA=0, segB=1, layers=2, prev=3, prev_skin=4,
                         t=float(fi.t), alpha=alpha, offs_scale=OFFS_SCALE)
        self.va.render(moderngl.TRIANGLE_STRIP)
        self.mask, self.skin = dst_tex, dst_skin
        frame_ctx.textures['mask'] = dst_tex
        frame_ctx.textures['skin'] = dst_skin
