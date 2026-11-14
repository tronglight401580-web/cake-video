"""Retouch rendering stage."""
from ..context import COMMON

RETOUCH = COMMON + """
uniform sampler2D src;
uniform sampler2D mask;      // R = smooth weight, G = tone weight
uniform vec2 texel;          // 1 / output size
uniform float radius;        // px
uniform float smooth_amt;    // 0..1
uniform float keep;          // fine-texture retained 0..1
uniform float sigma;         // bilateral colour sigma (0..1 units)
uniform float lift;          // skin mid-tone lift
uniform float rosy;          // pull skin a touch toward pink
const int TAPS = 32;
void main() {
    vec3 c = texture(src, uv).rgb;
    vec2 m = texture(mask, uv).rg;
    float ws = m.r * smooth_amt;
    float wt = m.g;
    if (ws < 0.004 && wt * lift < 0.0005) { o = vec4(c, 1.0); return; }

    vec3 outc = c;
    if (ws >= 0.004) {
        vec3 acc = c;
        float wsum = 1.0;
        float inv2s2 = 1.0 / (2.0 * sigma * sigma);
        for (int i = 0; i < TAPS; i++) {
            float fi = float(i) + 0.5;
            float r = radius * sqrt(fi / float(TAPS));
            float a = fi * 2.39996323;
            vec2 p = uv + vec2(cos(a), sin(a)) * r * texel;
            vec3 s = texture(src, p).rgb;
            vec3 d = s - c;
            float w = exp(-dot(d, d) * inv2s2) * texture(mask, p).r;
            acc += s * w;
            wsum += w;
        }
        vec3 base = acc / wsum;
        vec2 t = texel * 0.75;
        vec3 small = 0.25 * (texture(src, uv + vec2(t.x, t.y)).rgb + texture(src, uv - vec2(t.x, t.y)).rgb
                           + texture(src, uv + vec2(t.x, -t.y)).rgb + texture(src, uv + vec2(-t.x, t.y)).rgb);
        vec3 smoothed = base + (c - small) * keep;
        outc = mix(c, smoothed, ws);
    }
    // tone: brighten skin mid-tones, slightly cleaner / rosier
    float L = luma(outc);
    float k = wt * lift * 4.0 * L * (1.0 - L);
    outc += k;
    outc += wt * rosy * vec3(0.004, -0.003, 0.002);
    o = vec4(clamp(outc, 0.0, 1.0), 1.0);
}
"""

import moderngl
import numpy as np
from ...core.registry import Pass, register_pass


@register_pass('retouch', 400)
class Retouch(Pass):
    reads, writes = ('rgb', 'healed', 'mask'), ('retouched',)

    def setup(self, gl, width, height):
        self.gl, self.w, self.h = gl, width, height
        self.program, self.va = gl.program(RETOUCH)
        self.retouched, self.fb = gl.rt((width, height))

    def enabled(self, recipe, fc):
        return fc.uniforms['retouch'] > 0 and fc.textures.get('mask') is not None

    def run(self, fc):
        u, t = fc.uniforms, fc.textures
        r = u['retouch']
        face_px = u['face_h'] * self.h
        radius = face_px * (0.02 + 0.025 * r) if face_px > 0 else 6.0 * u['scale']
        radius = float(np.clip(radius, 2.5 * u['scale'], 40.0))
        self.fb.use()
        t.get('healed', t['rgb']).use(0)
        t['mask'].use(1)
        self.gl.uniforms(self.program, src=0, mask=1, texel=(1 / self.w, 1 / self.h),
                         radius=radius, smooth_amt=min(1.0, r * 1.1), keep=0.85 - 0.45 * r,
                         sigma=0.05 + 0.04 * r, lift=0.05 * r, rosy=r)
        self.va.render(moderngl.TRIANGLE_STRIP)
        t['retouched'] = self.retouched
