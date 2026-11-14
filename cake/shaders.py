"""GLSL sources. uv.y == 0 is the TOP of the image everywhere (no flips needed:
uploaded row 0 is the top, and readback returns fbo row 0 first)."""

VERT = """
#version 330
in vec2 in_pos;
out vec2 uv;
void main() { uv = in_pos * 0.5 + 0.5; gl_Position = vec4(in_pos, 0.0, 1.0); }
"""

COMMON = """
#version 330
in vec2 uv;
out vec4 o;
const vec3 W709 = vec3(0.2126, 0.7152, 0.0722);
float luma(vec3 c) { return dot(c, W709); }
float hash12(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}
"""

# I420 input -> RGB (display-referred, gamma). Replaces ffmpeg's CPU conversion on 8-bit SDR
# sources. kr/kb: BT.709 (0.2126, 0.0722) or BT.601 (0.299, 0.114); limited or full range.
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

# Mask assembly + temporal EMA, at analysis resolution (was ~30 ms/frame of numpy on the CPU).
# segA/segB: face-skin / body-skin of the two neighbouring segmentation key frames, interpolated
# by t. layers: R eyes/brows/lips cut-out, G nostril cut-out, B under-eye band, A offset*8.
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

# Pass 0a (optional): blemish removal + dark circles, before smoothing.
#  med  = src blurred at ~spot size, base = src blurred at ~3x spot size (both half-res).
#  Spot  : medium scale darker / redder than the surrounding skin -> replaced by the surrounding
#          skin colour (base) plus fine texture borrowed from a nearby patch (no flat "hole").
#  Moles : very dark, crisp spots are kept unless mole_keep = 0.
#  Under-eye: only the LOW-frequency difference to the cheek below is added (lifts the shadow and
#          removes the brown / purple cast) - fine texture of the eye bag area is untouched.
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

# Pass 0b (optional): skin retouch, driven by the low-res ML mask.
# Frequency separation: an edge-aware (bilateral) average over a golden-angle disk removes
# mid-frequency unevenness (blemishes, blotches, shadows of pores); the original's finest detail
# (pores, ~1 px) is added back so skin keeps texture instead of going plastic.
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

# Pass 1: exposure + 3D LUT with strength -> half-float buffer.
GRADE = COMMON + """
uniform sampler2D src;
uniform sampler3D lut;
uniform float lut_size;
uniform sampler3D skin_lut;
uniform float skin_lut_size;
uniform sampler2D skin_mask;
uniform float skin_protect;
uniform float strength;
void main() {
    vec3 c = clamp(texture(src, uv).rgb, 0.0, 1.0);
    vec3 coord = c * ((lut_size - 1.0) / lut_size) + 0.5 / lut_size;
    vec3 g = texture(lut, coord).rgb;
    vec3 sc = c * ((skin_lut_size - 1.0) / skin_lut_size) + 0.5 / skin_lut_size;
    g = mix(g, texture(skin_lut, sc).rgb, clamp(texture(skin_mask, uv).r * skin_protect, 0.0, 1.0));
    o = vec4(mix(c, g, strength), 1.0);
}
"""

# Pass 2: bright-pass + 4-tap downsample to bloom resolution.
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

# Skin-weighted downsample for the blemish pyramid: rgb premultiplied by skin weight, a = skin.
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

# Separable 9-tap gaussian on all four channels (for premultiplied skin buffers).
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

# Pass 3: separable 9-tap gaussian.
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

# Pass 4: composite. CA, softness, bloom/halation, vignette, grain, stamp, dither.
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

# RGB (display-referred, gamma) -> BT.709 limited-range NV12 (Y plane + interleaved CbCr).
# Replaces ffmpeg's single-threaded swscale conversion and halves the pipe traffic; NV12 is what
# hardware encoders want and x264 takes it natively. plane: 0 = Y, 1 = CbCr (half res, 2x2 box).
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
