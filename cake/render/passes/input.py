"""Input rendering stage."""
from ..context import COMMON

YUV2RGB = COMMON + """
uniform sampler2D ytex;
uniform sampler2D utex;
uniform sampler2D vtex;
uniform float kr;
uniform float kb;
uniform float full_range;
void main() {
    float Y = texture(ytex, uv).r, U = texture(utex, uv).r, V = texture(vtex, uv).r;
    float y, cb, cr;
    if (full_range > 0.5) {
        y = Y; cb = U - 0.5; cr = V - 0.5;
    } else {
        y = (Y - 16.0 / 255.0) * (255.0 / 219.0);
        cb = (U - 128.0 / 255.0) * (255.0 / 224.0);
        cr = (V - 128.0 / 255.0) * (255.0 / 224.0);
    }
    float r = y + 2.0 * (1.0 - kr) * cr;
    float b = y + 2.0 * (1.0 - kb) * cb;
    float g = (y - kr * r - kb * b) / (1.0 - kr - kb);
    o = vec4(clamp(vec3(r, g, b), 0.0, 1.0), 1.0);
}
"""

import moderngl
from ...core.registry import Pass, register_pass


@register_pass('input', 100)
class Input(Pass):
    reads, writes = (), ('rgb',)

    def setup(self, gl, width, height):
        self.gl, self.w, self.h = gl, width, height
        self.program, self.va = gl.program(YUV2RGB)
        self.src = gl.gl.texture((width, height), 3, dtype=self.dtype, alignment=1)
        self.src.filter = (moderngl.LINEAR, moderngl.LINEAR)
        if self.yuv:
            self.planes = [gl.gl.texture(s, 1, dtype='f1', alignment=1)
                           for s in ((width, height), (width // 2, height // 2), (width // 2, height // 2))]
            for tex in self.planes:
                tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
                tex.repeat_x = tex.repeat_y = False
            self.srcrgb, self.fb_srcrgb = gl.rt((width, height))
            kr, kb = (0.299, 0.114) if self.yuv[0] == 'bt601' else (0.2126, 0.0722)
            self.yuv_uniforms = dict(ytex=0, utex=1, vtex=2, kr=kr, kb=kb,
                                     full_range=1.0 if self.yuv[1] == 'pc' else 0.0)
            self.plane_sizes = (width * height, width * height // 4)

    def run(self, frame_ctx):
        if not self.yuv:
            self.src.write(frame_ctx.frame)
            frame_ctx.textures['rgb'] = self.src
            return
        ny, nc = self.plane_sizes
        mv = memoryview(frame_ctx.frame)
        self.planes[0].write(mv[:ny])
        self.planes[1].write(mv[ny:ny + nc])
        self.planes[2].write(mv[ny + nc:ny + 2 * nc])
        self.fb_srcrgb.use()
        for i, tex in enumerate(self.planes):
            tex.use(i)
        self.gl.uniforms(self.program, **self.yuv_uniforms)
        self.va.render(moderngl.TRIANGLE_STRIP)
        frame_ctx.textures['rgb'] = self.srcrgb
