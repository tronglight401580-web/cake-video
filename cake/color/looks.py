"""Procedural 3D-LUT looks. All maths is on display-referred Rec.709 RGB in [0, 1].

`python -m cake build-luts` writes luts/<name>.cube for every look in LOOKS.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .cube import identity, write_cube

W709 = np.array([0.2126, 0.7152, 0.0722])


# ---------------------------------------------------------------- primitives
def luma(c):
    return c @ W709


def to_lin(c):
    return np.clip(c, 0, None) ** 2.4


def from_lin(c):
    return np.clip(c, 0, None) ** (1 / 2.4)


def white_balance(c, gains):
    """Channel gains applied in linear light, luminance kept constant."""
    g = np.asarray(gains, float)
    g = g / (g @ W709)
    return from_lin(to_lin(c) * g)


def exposure(c, stops):
    return from_lin(to_lin(c) * 2.0 ** stops)


def s_curve(x, gamma, pivot=0.5):
    """Contrast S-curve fixing 0 and 1; `pivot` is the grey that stays put."""
    x = np.clip(x, 1e-6, 1 - 1e-6)
    k = np.log(0.5) / np.log(pivot)
    x = x ** k
    y = x ** gamma / (x ** gamma + (1 - x) ** gamma)
    return y ** (1 / k)


def contrast(c, gamma, pivot=0.45):
    """S-curve on luminance, chroma scaled along (keeps hue, avoids per-channel hue skew)."""
    lum = luma(c)[..., None]
    new = s_curve(lum, gamma, pivot)
    return new + (c - lum) * (new / np.maximum(lum, 1e-4)) ** 0.5


def saturation(c, s):
    lum = luma(c)[..., None]
    return lum + (c - lum) * s


def levels(c, black=0.0, white=1.0, black_tint=(0, 0, 0)):
    """Film fade: lift blacks (optionally tinted) and pull whites down."""
    bt = np.asarray(black_tint, float)
    return black + bt + (white - black - bt) * c


def soft_clip(c, knee=0.85, max_in=1.08):
    """Highlight shoulder: slope 1 at `knee` (no kink), maps `max_in` exactly to 1.0.
    Only compresses values that overshoot 1.0 — pure white stays (near) white, because
    Douyin viewers read capped whites as grey / muddy."""
    rng = 1 - knee
    t = np.clip(c - knee, 0, None) / rng
    tm = (max_in - knee) / rng
    b = (tm - 1) / tm
    y = knee + rng * t / (1 + b * t)
    return np.where(c > knee, np.minimum(y, 1.0), c)


def split_tone(c, shadows, highlights, balance=0.0):
    """Add chroma-only tints weighted by luminance. Tints are small RGB offsets."""
    lum = np.clip(luma(c) + balance, 0, 1)[..., None]
    sh = np.asarray(shadows, float)
    hi = np.asarray(highlights, float)
    sh = sh - sh @ W709
    hi = hi - hi @ W709
    return c + sh * (1 - lum) ** 2 + hi * lum ** 2


def rgb_to_hsv(c):
    r, g, b = c[..., 0], c[..., 1], c[..., 2]
    mx = c.max(-1)
    mn = c.min(-1)
    d = mx - mn
    h = np.zeros_like(mx)
    m = d > 1e-9
    rm = m & (mx == r)
    gm = m & (mx == g) & ~rm
    bm = m & ~rm & ~gm
    h[rm] = ((g - b)[rm] / d[rm]) % 6
    h[gm] = (b - r)[gm] / d[gm] + 2
    h[bm] = (r - g)[bm] / d[bm] + 4
    h = h * 60.0
    s = np.where(mx > 1e-9, d / np.maximum(mx, 1e-9), 0)
    return np.stack([h, s, mx], -1)


def hsv_to_rgb(hsv):
    h, s, v = hsv[..., 0] % 360, np.clip(hsv[..., 1], 0, 1), hsv[..., 2]
    i = np.floor(h / 60).astype(int) % 6
    f = h / 60 - np.floor(h / 60)
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    choices = [np.stack(x, -1) for x in
               ((v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q))]
    out = np.zeros(h.shape + (3,))
    for k in range(6):
        out[i == k] = choices[k][i == k]
    return out


def _hue_weight(h, center, width):
    d = (h - center + 180) % 360 - 180
    return np.exp(-(d / width) ** 2)


def hue_adjust(c, bands):
    """bands: list of (center_deg, width_deg, hue_shift_deg, sat_mul, val_mul).
    Weighted by saturation so near-greys are untouched."""
    hsv = rgb_to_hsv(np.clip(c, 0, 1))
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    sw = np.clip(s * 3, 0, 1)
    dh = np.zeros_like(h)
    ds = np.ones_like(h)
    dv = np.ones_like(h)
    for center, width, shift, smul, vmul in bands:
        w = _hue_weight(h, center, width) * sw
        dh += w * shift
        ds *= 1 + w * (smul - 1)
        dv *= 1 + w * (vmul - 1)
    return hsv_to_rgb(np.stack([h + dh, s * ds, v * dv], -1))


SKIN_HUE = 17.0   # target: rosy-neutral ("白里透红"); 22-30 reads as yellow / sallow


def skin_weight(c):
    hsv = rgb_to_hsv(np.clip(c, 0, 1))
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    w = _hue_weight(h, SKIN_HUE, 18)
    w *= np.clip((s - 0.08) / 0.15, 0, 1) * np.clip(1 - (s - 0.6) / 0.25, 0, 1)
    w *= np.clip((v - 0.15) / 0.2, 0, 1)
    return w


def protect_skin(original, graded, amount, target_hue=SKIN_HUE, max_sat=0.5,
                 lift=0.0, sat_mul=0.92):
    # lift defaults to 0: skin brightening now happens in the retouch shader with a real
    # (ML) skin mask, so sand / wood / walls no longer get brightened by the LUT.
    """Skin pass, tuned for Douyin portrait taste (bright, rosy, clean):
    - pull skin hue toward a rosy-neutral target (looks must never turn faces yellow/green)
    - lift skin brightness by `lift` (gamma space, strongest in mid-tones)
    - slightly lower skin saturation for a 'clean / 通透' look."""
    w = (skin_weight(original) * amount)[..., None]
    hsv = rgb_to_hsv(np.clip(graded, 0, 1))
    d = (target_hue - hsv[..., 0] + 180) % 360 - 180
    hsv[..., 0] += d * 0.5      # partial pull: keeps some of coloured lighting (neon) on faces
    hsv[..., 1] = np.minimum(hsv[..., 1] * sat_mul, max_sat)
    fixed = hsv_to_rgb(hsv)
    lum = luma(graded)
    target_lum = lum + lift * 4 * lum * (1 - lum)      # mid-tone lift, 0 and 1 stay put
    fixed += (target_lum - luma(fixed))[..., None]
    return graded + (fixed - graded) * w


# ---------------------------------------------------------------- looks
def look_film_warm(c):
    """胶片暖调: Portra-like. Soft contrast, warm cream highlights, olive greens,
    gently lifted blacks, slightly muted saturation."""
    o = c
    o = exposure(o, 0.08)
    o = white_balance(o, (1.04, 1.0, 0.94))
    o = contrast(o, 1.2, pivot=0.42)
    o = hue_adjust(o, [
        (110, 35, -14, 0.72, 0.97),    # greens -> olive / yellow, muted
        (60, 20, -4, 0.92, 1.0),       # yellows slightly toward orange
        (215, 30, -10, 0.9, 1.0),      # blues -> cyan-ish, slightly muted
        (15, 20, 2, 1.04, 1.02),       # reds/oranges a touch richer
    ])
    o = split_tone(o, shadows=(0.0, 0.035, 0.05), highlights=(0.05, 0.025, -0.03))
    o = saturation(o, 0.92)
    o = soft_clip(o, 0.85, 1.06)
    o = levels(o, black=0.022, white=0.995, black_tint=(0.008, 0.004, 0.0))
    o = protect_skin(c, o, 0.7)    # warmth goes to the scene, not the face
    return o


def look_teal_orange(c):
    """青橙电影: stronger contrast, teal shadows/background, orange highlights & skin."""
    o = c
    o = contrast(o, 1.3, pivot=0.40)
    o = hue_adjust(o, [
        (210, 35, -18, 1.08, 0.95),    # blues -> teal
        (175, 25, 0, 1.05, 0.95),      # cyans stay teal
        (115, 35, 45, 0.55, 0.92),     # greens -> teal, heavily muted
        (300, 35, 0, 0.5, 1.0),        # magentas / purples killed
        (5, 15, 8, 1.0, 1.0),          # reds -> orange
        (30, 18, 0, 1.14, 1.02),       # oranges richer (keeps skin from going pale)
    ])
    o = split_tone(o, shadows=(-0.02, 0.05, 0.08), highlights=(0.08, 0.035, -0.05))
    o = saturation(o, 1.02)
    o = soft_clip(o, 0.88, 1.08)
    o = levels(o, black=0.015, white=0.995, black_tint=(0.0, 0.008, 0.012))
    o = protect_skin(c, o, 0.85, target_hue=18, max_sat=0.48)
    return o


def look_ccd(c):
    """CCD 复古: 2000s pocket digicam. Bright, punchy, cool-cyan cast, hard-ish highlight
    clip, saturated reds/blues. (Bloom / softness / date stamp are in the shader.)"""
    o = c
    o = exposure(o, 0.15)
    o = white_balance(o, (0.96, 1.0, 1.045))
    o = contrast(o, 1.22, pivot=0.5)
    o = hue_adjust(o, [
        (220, 30, -6, 1.22, 1.0),      # blues saturated, toward cyan
        (352, 10, 0, 1.12, 1.0),       # pure reds punchy (narrow: stay off skin hues)
        (110, 35, 12, 0.9, 1.0),       # greens slightly cyan
    ])
    o = split_tone(o, shadows=(0.0, 0.03, 0.045), highlights=(0.0, 0.01, 0.02))
    o = saturation(o, 1.15)
    o = soft_clip(o, 0.9, 1.08)
    o = levels(o, black=0.012)               # keep shadow detail on phone screens
    o = protect_skin(c, o, 0.5, target_hue=17, max_sat=0.46)
    return o


def look_japanese_fresh(c):
    o = exposure(c, 0.15)
    o = white_balance(o, (0.97, 1, 1.03))
    o = contrast(o, 0.92, pivot=0.5)
    o = hue_adjust(o, [(110, 35, 10, 0.85, 1), (220, 30, 0, 0.9, 1)])
    o = saturation(o, 0.88)
    o = split_tone(o, (0, 0.02, 0.03), (0.01, 0.01, 0))
    o = levels(o, 0.03, 0.995)
    return protect_skin(c, o, 0.6)


def look_hk_retro(c):
    o = white_balance(c, (1.06, 1, 0.90))
    o = contrast(o, 1.25, pivot=0.45)
    o = hue_adjust(o, [(110, 35, -15, 0.8, 1), (352, 12, 0, 1.15, 1)])
    o = split_tone(o, (-0.01, 0.04, 0), (0.06, 0.03, -0.04))
    o = saturation(o, 1.05)
    o = levels(o, 0.03, 1, (0, 0.01, 0))
    return protect_skin(c, o, 0.78, target_hue=17)


def look_creamy(c):
    o = exposure(c, 0.12)
    o = white_balance(o, (1.02, 1, 0.97))
    o = contrast(o, 0.95)
    o = saturation(o, 0.9)
    o = split_tone(o, (0, 0, 0), (0.03, 0.02, -0.01))
    o = soft_clip(o, 0.85, 1.06)
    o = levels(o, 0.02)
    return protect_skin(c, o, 0.8, target_hue=16, max_sat=0.42)


def look_black_gold(c):
    o = exposure(c, 0.10)
    o = hue_adjust(o, [(210, 45, 0, 0.1, 1), (175, 25, 0, 0.1, 1),
                       (110, 40, 0, 0.1, 1), (300, 35, 0, 0.1, 1),
                       (45, 15, -5, 1.2, 1)])
    o = contrast(o, 1.15)
    o = levels(o, 0)
    return protect_skin(c, o, 0.7)


LOOKS = {
    "identity": lambda c: c,          # for "不调色（仅精修）"
    "film_warm": look_film_warm,
    "teal_orange": look_teal_orange,
    "ccd": look_ccd,
    "japanese_fresh": look_japanese_fresh,
    "hk_retro": look_hk_retro,
    "creamy": look_creamy,
    "black_gold": look_black_gold,
}


def build_luts(outdir: str | Path, size: int = 33, names=None) -> list[Path]:
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, fn in LOOKS.items():
        if names and name not in names:
            continue
        grid = identity(size)
        lut = np.clip(fn(grid), 0, 1)
        p = outdir / f"{name}.cube"
        write_cube(p, lut, title=name)
        written.append(p)
    return written
