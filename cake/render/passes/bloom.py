"""Bloom rendering stage."""
from ..context import COMMON

BRIGHT = COMMON + """
uniform sampler2D src;
uniform vec2 src_texel;
uniform float threshold;
uniform float knee;
void main() {
    vec2 d = src_texel * 1.0;
    vec3 c = 0.25 * (texture(src, uv + vec2(-d.x, -d.y)).rgb + texture(src, uv + vec2(d.x, -d.y)).rgb
                   + texture(src, uv + vec2(-d.x, d.y)).rgb + texture(src, uv + vec2(d.x, d.y)).rgb);
    float l = luma(c);
    float k = smoothstep(threshold, threshold + knee, l);
    o = vec4(c * k, 1.0);
}
"""

BLUR = COMMON + """
uniform sampler2D src;
uniform vec2 dir;    // texel step * radius scale
void main() {
    vec3 acc = texture(src, uv).rgb * 0.2270270270;
    acc += (texture(src, uv + dir * 1.3846153846).rgb + texture(src, uv - dir * 1.3846153846).rgb) * 0.3162162162;
    acc += (texture(src, uv + dir * 3.2307692308).rgb + texture(src, uv - dir * 3.2307692308).rgb) * 0.0702702703;
    o = vec4(acc, 1.0);
}
"""

import moderngl
from ...core.registry import Pass, register_pass


@register_pass('bloom', 600)
class Bloom(Pass):
    reads, writes = ('graded',), ('bloom',)

    def setup(self, gl, width, height):
        self.gl, self.w, self.h = gl, width, height
        self.p_bright, self.va_bright = gl.program(BRIGHT)
        self.p_blur, self.va_blur = gl.program(BLUR)
        bw, bh = max(1, width // 4), max(1, height // 4)
        self.bsize = (bw, bh)
        self.b1, self.fb_b1 = gl.rt((bw, bh))
        self.b2, self.fb_b2 = gl.rt((bw, bh))

    def enabled(self, recipe, fc):
        return recipe.bloom_amount > 0

    def run(self, fc):
        st, t = fc.recipe, fc.textures
        bw, bh = self.bsize
        self.fb_b1.use()
        t['graded'].use(0)
        self.gl.uniforms(self.p_bright, src=0, src_texel=(1 / self.w, 1 / self.h),
                         threshold=st.bloom_threshold, knee=st.bloom_knee)
        self.va_bright.render(moderngl.TRIANGLE_STRIP)
        r = st.bloom_radius * fc.uniforms['scale'] / 4.0 / 4.0
        for mul in (1.0, 2.2):
            self.fb_b2.use()
            self.b1.use(0)
            self.gl.uniforms(self.p_blur, src=0, dir=(r * mul / bw, 0.0))
            self.va_blur.render(moderngl.TRIANGLE_STRIP)
            self.fb_b1.use()
            self.b2.use(0)
            self.gl.uniforms(self.p_blur, src=0, dir=(0.0, r * mul / bh))
            self.va_blur.render(moderngl.TRIANGLE_STRIP)
        t['bloom'] = self.b1
