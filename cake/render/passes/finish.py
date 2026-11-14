"""Finish rendering stage."""
from ..context import COMMON

FINISH = COMMON + """
uniform sampler2D graded;
uniform sampler2D bloom;
uniform sampler2D stamp;
uniform vec2 res;            // output pixels
uniform float scale;         // short side / 1080
uniform float frame;
uniform float fx;            // global effect strength
uniform float ca;            // chromatic aberration (fraction of radius)
uniform float soften;        // 0..1 mix toward a ~1.5px blur
uniform float bloom_amount;
uniform vec3  bloom_tint;
uniform float vignette;
uniform float vignette_soft;
uniform float grain;
uniform float grain_size;    // px at 1080p
uniform float grain_chroma;
uniform float use_stamp;
uniform float dither_amt;

float vnoise(vec2 p, float seed) {
    vec2 i = floor(p), f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    vec2 s = vec2(seed * 17.13, seed * 3.71);
    float a = hash12(i + s), b = hash12(i + vec2(1, 0) + s);
    float c = hash12(i + vec2(0, 1) + s), d = hash12(i + vec2(1, 1) + s);
    return mix(mix(a, b, u.x), mix(c, d, u.x), u.y) * 2.0 - 1.0;
}

void main() {
    vec2 px = 1.0 / res;
    vec2 d = uv - 0.5;
    vec3 c;
    float cak = ca * fx;
    if (cak > 0.0) {
        c.r = texture(graded, 0.5 + d * (1.0 + cak)).r;
        c.g = texture(graded, uv).g;
        c.b = texture(graded, 0.5 + d * (1.0 - cak)).b;
    } else {
        c = texture(graded, uv).rgb;
    }
    if (soften > 0.0) {
        vec2 s = px * 1.5 * scale;
        vec3 b = 0.25 * (texture(graded, uv + vec2(s.x, s.y)).rgb + texture(graded, uv - vec2(s.x, s.y)).rgb
                       + texture(graded, uv + vec2(s.x, -s.y)).rgb + texture(graded, uv - vec2(s.x, -s.y)).rgb);
        c = mix(c, b, soften * fx);
    }
    // bloom / halation: screen blend keeps it below 1.0
    vec3 bl = texture(bloom, uv).rgb * bloom_tint * bloom_amount * fx;
    c = 1.0 - (1.0 - clamp(c, 0.0, 1.0)) * (1.0 - clamp(bl, 0.0, 1.0));

    // vignette (aspect-aware, on the long axis it's gentler)
    vec2 dv = d * vec2(res.x / max(res.x, res.y), res.y / max(res.x, res.y)) * 2.0;
    float r = length(dv);
    float v = 1.0 - vignette * fx * smoothstep(1.0 - vignette_soft, 1.0 + 0.4, r);
    c *= v;

    // film grain: two octaves of value noise, strongest in the mid-tones;
    // size is resolution-independent so it survives the platform re-encode.
    if (grain > 0.0) {
        vec2 gp = uv * res / (grain_size * scale);
        float f = frame;
        float n = vnoise(gp, f) * 0.7 + vnoise(gp * 2.03, f + 0.5) * 0.3;
        float L = luma(c);
        float mask = 0.35 + 0.65 * (1.0 - pow(abs(2.0 * L - 1.0), 2.0));
        vec3 cn = vec3(vnoise(gp * 1.7, f + 0.2), vnoise(gp * 1.7, f + 0.4), vnoise(gp * 1.7, f + 0.6));
        c += (vec3(n) + cn * grain_chroma) * grain * fx * mask;
    }

    if (use_stamp > 0.5) {
        vec4 s = texture(stamp, uv);
        c = mix(c, s.rgb, s.a);
    }

    // TPDF dither to 8 bit (off when the YUV pass does the final quantisation instead)
    float dt = hash12(gl_FragCoord.xy + frame * 1.618) - hash12(gl_FragCoord.xy * 1.37 + frame * 0.73 + 11.0);
    c += dt / 255.0 * dither_amt;
    o = vec4(clamp(c, 0.0, 1.0), 1.0);
}
"""

import moderngl
from ...core.registry import Pass, register_pass


@register_pass('finish', 700)
class Finish(Pass):
    reads, writes = ('graded', 'bloom'), ('out8', 'out16')

    def setup(self, gl, width, height):
        self.gl, self.w, self.h = gl, width, height
        self.program, self.va = gl.program(FINISH)
        self.out = gl.gl.texture((width, height), 4, dtype='f1')
        self.fb_out = gl.gl.framebuffer(color_attachments=[self.out])
        self.out16, self.fb_out16 = gl.rt((width, height))
        self.stamp = gl.gl.texture((1, 1), 4, data=bytes(4))
        self.zero_bloom = gl.gl.texture((1, 1), 4, data=bytes(8), dtype='f2')
        self.use_stamp = 0.0

    def set_stamp(self, rgba):
        if rgba is not None:
            self.stamp.release()
            self.stamp = self.gl.gl.texture((self.w, self.h), 4, data=rgba.tobytes(), alignment=1)
            self.use_stamp = 1.0
        else:
            self.use_stamp = 0.0

    def run(self, fc):
        st, t, u = fc.style, fc.textures, fc.uniforms
        (self.fb_out16 if fc.yuv else self.fb_out).use()
        t['graded'].use(0); t.get('bloom', self.zero_bloom).use(1); self.stamp.use(2)
        self.gl.uniforms(self.program, graded=0, bloom=1, stamp=2,
                         res=(float(self.w), float(self.h)), scale=u['scale'],
                         frame=float(fc.frame_index % 4096), fx=u['strength'], ca=st.ca,
                         soften=st.soften, bloom_amount=st.bloom_amount if st.bloom_amount > 0 else 0.0,
                         bloom_tint=tuple(st.bloom_tint), vignette=st.vignette,
                         vignette_soft=st.vignette_soft, grain=st.grain, grain_size=st.grain_size,
                         grain_chroma=st.grain_chroma, use_stamp=self.use_stamp,
                         dither_amt=0.0 if fc.yuv else 1.0)
        self.va.render(moderngl.TRIANGLE_STRIP)
        t['out16' if fc.yuv else 'out8'] = self.out16 if fc.yuv else self.out
        if not fc.yuv:
            fc.result = self.fb_out.read(components=3, alignment=1)
