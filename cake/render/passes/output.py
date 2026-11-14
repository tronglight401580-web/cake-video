"""Output rendering stage."""
from ..context import COMMON

TOYUV = COMMON + """
uniform sampler2D src;
uniform vec2 src_texel;
uniform float plane;
uniform float frame;
void main() {
    vec3 c;
    if (plane < 0.5) {
        c = texture(src, uv).rgb;
    } else {
        vec2 d = src_texel * 0.5;
        c = 0.25 * (texture(src, uv + vec2(-d.x, -d.y)).rgb + texture(src, uv + vec2(d.x, -d.y)).rgb
                  + texture(src, uv + vec2(-d.x, d.y)).rgb + texture(src, uv + vec2(d.x, d.y)).rgb);
    }
    float y = dot(c, vec3(0.2126, 0.7152, 0.0722));
    float d1 = hash12(gl_FragCoord.xy + frame * 1.618 + plane * 7.0)
             - hash12(gl_FragCoord.xy * 1.37 + frame * 0.73 + 11.0 + plane * 3.0);
    if (plane < 0.5) {
        o = vec4(clamp((16.0 + 219.0 * y + d1) / 255.0, 0.0, 1.0), 0.0, 0.0, 1.0);
    } else {          // NV12: Cb, Cr interleaved in one half-res plane
        float d2 = hash12(gl_FragCoord.yx * 1.13 + frame * 0.37 + 5.0)
                 - hash12(gl_FragCoord.xy * 0.71 + frame * 1.91 + 17.0);
        float cb = (128.0 + 224.0 * (c.b - y) / 1.8556 + d1) / 255.0;
        float cr = (128.0 + 224.0 * (c.r - y) / 1.5748 + d2) / 255.0;
        o = vec4(clamp(cb, 0.0, 1.0), clamp(cr, 0.0, 1.0), 0.0, 1.0);
    }
}
"""

import moderngl
from ..context import PBOReadback
from ...core.registry import Pass, register_pass


@register_pass('output', 800)
class Output(Pass):
    reads, writes = ('out16',), ('nv12',)

    def setup(self, gl, width, height):
        self.gl, self.w, self.h = gl, width, height
        self.program, self.va = gl.program(TOYUV)
        self.planes = None
        self.readback = PBOReadback(gl.gl, width * height * 3 // 2)

    def enabled(self, recipe, fc):
        return fc.yuv

    def run(self, fc):
        if self.planes is None:
            self.planes = []
            for size, comps in (((self.w, self.h), 1), ((self.w // 2, self.h // 2), 2)):
                tex = self.gl.gl.texture(size, comps, dtype='f1')
                self.planes.append((tex, self.gl.gl.framebuffer(color_attachments=[tex]), comps))
        fc.textures['out16'].use(0)
        if fc.pipelined:
            # Keep draw and read interleaved for the two NV12 planes.
            if self.readback.buffers is None:
                self.readback.buffers = [self.gl.gl.buffer(reserve=self.readback.size),
                                         self.gl.gl.buffer(reserve=self.readback.size)]
            pbo = self.readback.buffers[self.readback.index]
            offset = 0
            for i, (tex, fb, comps) in enumerate(self.planes):
                fb.use()
                self.gl.uniforms(self.program, src=0, src_texel=(1 / self.w, 1 / self.h),
                                 plane=float(i), frame=float(fc.frame_index % 4096))
                self.va.render(moderngl.TRIANGLE_STRIP)
                fb.read_into(pbo, components=comps, alignment=1, write_offset=offset)
                offset += tex.width * tex.height * comps
            prev, self.readback.pending = self.readback.pending, pbo
            self.readback.index ^= 1
            fc.result = prev.read() if prev is not None else None
        else:
            parts = []
            for i, (tex, fb, comps) in enumerate(self.planes):
                fb.use()
                self.gl.uniforms(self.program, src=0, src_texel=(1 / self.w, 1 / self.h),
                                 plane=float(i), frame=float(fc.frame_index % 4096))
                self.va.render(moderngl.TRIANGLE_STRIP)
                parts.append(fb.read(components=comps, alignment=1))
            fc.result = b''.join(parts)

    def flush(self):
        return self.readback.flush()
