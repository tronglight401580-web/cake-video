"""Heal rendering stage."""
from ..context import COMMON

HEAL = COMMON + """
uniform sampler2D src;
uniform sampler2D mask;      // R smooth/skin, G tone, B under-eye, A cheek offset (uv)
uniform sampler2D med;       // skin-only normalised blurs: rgb premultiplied by skin, a = skin
uniform sampler2D base;
uniform float spots;
uniform float mole_keep;
uniform float under_amt;
uniform vec2 spot_off;       // uv offset of the texture donor patch
uniform vec2 hstep;          // Hessian step (uv), ~ spot radius
uniform vec2 texel;          // 1 / output size
uniform float debug;
float redness(vec3 c) { return c.r - 0.5 * (c.g + c.b); }
vec3 skin_avg(sampler2D t, vec2 p) { vec4 v = texture(t, p); return v.rgb / max(v.a, 1e-3); }
// "spot signal": lower = darker and/or redder
float D(vec3 c) { return luma(c) - 0.8 * redness(c); }
float Dm(vec2 p) { return D(skin_avg(med, p)); }
void main() {
    vec3 c = texture(src, uv).rgb;
    vec4 mk = texture(mask, uv);
    vec3 outc = c;
    float score = 0.0;
    float skin_m = texture(med, uv).a;
    if (spots > 0.0 && mk.r > 0.05 && skin_m > 0.3) {
        vec3 m = skin_avg(med, uv);
        vec3 b = skin_avg(base, uv);
        float s = D(b) - D(m);                         // band-pass: spot-sized darker / redder
        score = smoothstep(0.012, 0.045, s);
        // shape: Hessian of the spot signal must be positive-definite and round (a blob),
        // which rejects lines and edges (nose sides, folds, eyelid creases, face contour).
        if (score > 0.0) {
            float d0 = Dm(uv);
            float lxx = Dm(uv + vec2(hstep.x, 0)) + Dm(uv - vec2(hstep.x, 0)) - 2.0 * d0;
            float lyy = Dm(uv + vec2(0, hstep.y)) + Dm(uv - vec2(0, hstep.y)) - 2.0 * d0;
            float lxy = 0.25 * (Dm(uv + hstep) - Dm(uv + vec2(hstep.x, -hstep.y))
                              - Dm(uv + vec2(-hstep.x, hstep.y)) + Dm(uv - hstep));
            float tr = lxx + lyy;
            float disc = sqrt(max(tr * tr * 0.25 - (lxx * lyy - lxy * lxy), 0.0));
            float l1 = tr * 0.5 + disc, l2 = tr * 0.5 - disc;
            float round_ = (l1 > 1e-5) ? clamp(l2 / l1, -1.0, 1.0) : -1.0;
            score *= smoothstep(0.25, 0.55, round_);
        }
        // the pixel itself must be darker / redder than the surrounding skin
        // (otherwise the bright side of an edge gets "healed" -> ghost line)
        score *= smoothstep(0.008, 0.03, D(b) - D(c));
        // isolation: a blemish has brighter skin on (almost) all sides; an edge, fold or the
        // rim of an excluded feature has a dark / non-skin side. 8-point ring at 2x spot radius.
        if (score > 0.0) {
            float d0 = Dm(uv);
            float n = 0.0;
            for (int i = 0; i < 8; i++) {
                float a = float(i) * 0.785398;
                vec2 p = uv + vec2(cos(a), sin(a)) * hstep * 2.2;
                vec4 r = texture(med, p);
                float brighter = (r.a > 0.5) ? smoothstep(0.004, 0.015, D(r.rgb / r.a) - d0) : 0.0;
                n += brighter;
            }
            score *= smoothstep(6.0, 7.5, n);
        }
        float dl = luma(b) - luma(m);
        score *= 1.0 - mole_keep * smoothstep(0.09, 0.15, dl);   // very dark = mole, keep
        // the surround (base) must itself be mostly skin, else its colour is biased
        // (e.g. next to the excluded eyes it skews bright -> a light patch)
        score *= smoothstep(0.05, 0.4, mk.r) * smoothstep(0.5, 0.85, skin_m)
               * smoothstep(0.55, 0.8, texture(base, uv).a) * spots;
        if (score > 0.001) {
            // borrow only pore-level texture (~1 px high-pass, clamped) from a nearby patch:
            // a wider band would drag neighbouring edges in and leave a ghost line.
            vec2 dp = uv + spot_off;
            vec2 t = texel;
            vec3 avg = 0.25 * (texture(src, dp + vec2(t.x, 0)).rgb + texture(src, dp - vec2(t.x, 0)).rgb
                             + texture(src, dp + vec2(0, t.y)).rgb + texture(src, dp - vec2(0, t.y)).rgb);
            vec3 donor = clamp(texture(src, dp).rgb - avg, -0.025, 0.025);
            outc = mix(c, b + donor, score);
        }
    }
    float ue = mk.b * under_amt;
    if (ue > 0.002) {
        vec3 d = skin_avg(base, uv + vec2(0.0, mk.a)) - skin_avg(base, uv);
        float dlum = luma(d);
        if (dlum < 0.0) d -= dlum;          // never darken; keep the colour correction only
        outc += d * ue;
    }
    if (debug > 0.5) {
        outc = mix(outc * 0.6, vec3(1.0, 0.1, 0.1), clamp(score * 1.5, 0.0, 1.0));
        outc = mix(outc, vec3(0.2, 0.4, 1.0), clamp(ue * 1.2, 0.0, 0.7));
    }
    o = vec4(clamp(outc, 0.0, 1.0), 1.0);
}
"""

SKINDOWN = COMMON + """
uniform sampler2D src;
uniform sampler2D mask;
uniform vec2 src_texel;
void main() {
    vec2 d = src_texel;
    vec3 c = 0.25 * (texture(src, uv + vec2(-d.x, -d.y)).rgb + texture(src, uv + vec2(d.x, -d.y)).rgb
                   + texture(src, uv + vec2(-d.x, d.y)).rgb + texture(src, uv + vec2(d.x, d.y)).rgb);
    float s = texture(mask, uv).r;
    o = vec4(c * s, s);
}
"""

BLUR4 = COMMON + """
uniform sampler2D src;
uniform vec2 dir;
void main() {
    vec4 acc = texture(src, uv) * 0.2270270270;
    acc += (texture(src, uv + dir * 1.3846153846) + texture(src, uv - dir * 1.3846153846)) * 0.3162162162;
    acc += (texture(src, uv + dir * 3.2307692308) + texture(src, uv - dir * 3.2307692308)) * 0.0702702703;
    o = acc;
}
"""

import moderngl
import numpy as np
from ...core.registry import Pass, register_pass


@register_pass('heal', 300)
class Heal(Pass):
    reads, writes = ('rgb', 'mask'), ('healed',)

    def setup(self, gl, width, height):
        self.gl, self.w, self.h = gl, width, height
        self.p_heal, self.va_heal = gl.program(HEAL)
        self.p_skindown, self.va_skindown = gl.program(SKINDOWN)
        self.p_blur4, self.va_blur4 = gl.program(BLUR4)
        self.healed, self.fb_healed = gl.rt((width, height))
        hw, hh = max(1, width // 2), max(1, height // 2)
        self.hsize = (hw, hh)
        self.h1, self.fb_h1 = gl.rt((hw, hh))
        self.h2, self.fb_h2 = gl.rt((hw, hh))
        self.hmed, self.fb_hmed = gl.rt((hw, hh))
        self.hbase, self.fb_hbase = gl.rt((hw, hh))

    def enabled(self, recipe, fc):
        u = fc.uniforms
        if not (u['retouch'] > 0 and fc.textures.get('mask') is not None):
            return False
        spots = min(1.0, 1.6 * u['retouch']) if u['spots'] is None else u['spots']
        under = min(0.8, 0.9 * u['retouch']) if u['under'] is None else u['under']
        return (spots > 0 or under > 0) and fc.textures['mask'].components >= 4

    def blur(self, src_tex, dst_fb, sigma_px):
        hw, hh = self.hsize
        step = max(sigma_px, 0.05) / 2.0
        self.fb_h2.use()
        src_tex.use(0)
        self.gl.uniforms(self.p_blur4, src=0, dir=(step / hw, 0.0))
        self.va_blur4.render(moderngl.TRIANGLE_STRIP)
        dst_fb.use()
        self.h2.use(0)
        self.gl.uniforms(self.p_blur4, src=0, dir=(0.0, step / hh))
        self.va_blur4.render(moderngl.TRIANGLE_STRIP)

    def run(self, fc):
        u, t = fc.uniforms, fc.textures
        r = u['retouch']
        spots = min(1.0, 1.6 * r) if u['spots'] is None else u['spots']
        under = min(0.8, 0.9 * r) if u['under'] is None else u['under']
        face_px = u['face_h'] * self.h if u['face_h'] > 0 else 300 * u['scale']
        spot_r = float(np.clip(face_px * 0.012, 1.5, 14.0))
        self.fb_h1.use()
        t['rgb'].use(0); t['mask'].use(1)
        self.gl.uniforms(self.p_skindown, src=0, mask=1, src_texel=(0.5 / self.w, 0.5 / self.h))
        self.va_skindown.render(moderngl.TRIANGLE_STRIP)
        s_med, s_base = spot_r * 0.8 / 2, spot_r * 3.0 / 2
        self.blur(self.h1, self.fb_hmed, s_med)
        self.blur(self.hmed, self.fb_hbase, float(np.sqrt(max(s_base ** 2 - s_med ** 2, 0.01))))
        self.fb_healed.use()
        t['rgb'].use(0); t['mask'].use(1); self.hmed.use(2); self.hbase.use(3)
        self.gl.uniforms(self.p_heal, src=0, mask=1, med=2, base=3, spots=spots, under_amt=under,
                         mole_keep=u['mole_keep'], debug=u['debug'],
                         spot_off=(2.5 * spot_r / self.w, 0.6 * spot_r / self.h),
                         hstep=(spot_r / self.w, spot_r / self.h), texel=(1 / self.w, 1 / self.h))
        self.va_heal.render(moderngl.TRIANGLE_STRIP)
        t['healed'] = self.healed
