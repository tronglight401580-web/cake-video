"""Fit an affine Lab colour transfer to analysis-size non-skin pixels."""
from __future__ import annotations
import json
import re
from datetime import datetime
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageOps
from .cube import identity, write_cube
from ..face import analysis_size, run_models
from .looks import soft_clip, protect_skin
from ..io.media import Decoder, target_size
from ..io.probe import probe
from .styles import LUT_DIR, STYLE_DIR, load_style

_M = np.array([[.4124564,.3575761,.1804375],[.2126729,.7151522,.0721750],[.0193339,.1191920,.9503041]])
_WHITE = np.array([.95047,1.,1.08883])

def rgb_to_lab(rgb):
    rgb = np.asarray(rgb, dtype=np.float64)
    linear = np.where(rgb <= .04045, rgb / 12.92, ((rgb + .055) / 1.055) ** 2.4)
    xyz = (linear @ _M.T) / _WHITE
    d = 6 / 29
    f = np.where(xyz > d**3, np.cbrt(xyz), xyz / (3*d*d) + 4/29)
    return np.stack([116*f[...,1]-16, 500*(f[...,0]-f[...,1]), 200*(f[...,1]-f[...,2])], axis=-1)

def lab_to_rgb(lab):
    fy = (lab[...,0]+16)/116
    f = np.stack([fy + lab[...,1]/500, fy, fy - lab[...,2]/200], axis=-1)
    d = 6/29
    xyz = np.where(f > d, f**3, 3*d*d*(f-4/29))*_WHITE
    lin = xyz @ np.linalg.inv(_M).T
    return np.where(lin <= .0031308, 12.92*lin, 1.055*np.maximum(lin,0)**(1/2.4)-.055)

def _sample(image, ts):
    seg = run_models(image, True, ts).seg.astype(np.float32) / 255
    skin = np.clip(seg.sum(axis=-1), 0, 1)
    lab = rgb_to_lab(image / 255.)
    valid = (lab[...,0] > 3) & (lab[...,0] < 97) # discard near-black and near-white pixels
    use = valid & (skin < .3)                   # exclude uncertain skin from global fit
    if use.mean() < .02:                        # fallback when under 2% of image is usable
        use = valid
    if not use.any():
        raise ValueError('No unclipped pixels available for colour statistics')
    return lab[use], lab[skin >= .3], skin.mean(), skin

def _root(a, inverse=False):
    vals, vec = np.linalg.eigh(a)
    vals = np.maximum(vals, max(np.trace(a)*1e-4, 1e-8)) # regularise nearly singular covariance
    return (vec * (vals ** (-.5 if inverse else .5))) @ vec.T

def _bands(l):
    # Adjacent cosine ramps form a smooth partition of unity.
    l = np.asarray(l)
    t1 = np.clip((l - 20) / 30, 0, 1)
    t2 = np.clip((l - 50) / 30, 0, 1)
    a = (1 - np.cos(np.pi * t1)) / 2
    b = (1 - np.cos(np.pi * t2)) / 2
    return np.stack((1-a, a-b, b), axis=-1)


def _grade_fit(source, reference, grid_lab):
    x = np.linspace(0, 100, 256)
    quantiles = np.linspace(0, 1, 1025)
    src_q = np.quantile(source[:, 0], quantiles)
    ref_q = np.quantile(reference[:, 0], quantiles)
    matched = np.interp(x, src_q, ref_q)
    curve = x + .35 * (matched - x)
    # Contract the displacement until both exposure and contrast bounds hold.
    for _ in range(40):
        curve[0], curve[-1] = 0, 100
        curve = np.maximum.accumulate(curve)
        mapped = np.interp(source[:, 0], x, curve)
        gain = mapped.std() / max(source[:, 0].std(), 1e-8)
        if abs(mapped.mean()-source[:, 0].mean()) <= 6 and .85 <= gain <= 1.25:
            break
        curve = x + .9 * (curve-x)
    source_l = np.interp(source[:, 0], x, curve)
    sw, rw = _bands(source_l), _bands(reference[:, 0])
    out = grid_lab.copy()
    out[..., 0] = np.interp(grid_lab[..., 0], x, curve)
    weights = _bands(out[..., 0])
    chroma = np.zeros_like(grid_lab[..., 1:])
    for i in range(3):
        def stats(pixels, w):
            total = max(w.sum(), 1e-8)
            mean = (pixels * w[:, None]).sum(axis=0) / total
            std = np.sqrt(((pixels-mean)**2 * w[:, None]).sum(axis=0) / total)
            return mean, std
        sm, ss = stats(source[:, 1:], sw[:, i])
        rm, rs = stats(reference[:, 1:], rw[:, i])
        offset = np.clip(rm-sm, -20, 20)
        scale = np.clip(rs / np.maximum(ss, 1e-8), .6, 1.5)
        chroma += weights[..., i, None] * (sm + scale*(grid_lab[..., 1:]-sm) + offset)
    out[..., 1:] = chroma
    return out


def build_reference_style(ref_image: str, clips: list[str], name: str | None = None,
                          skin_follow: float = .2, samples_per_clip: int = 8, method: str = "grade"):
    if method not in ('grade', 'mkl'):
        raise ValueError('method must be grade or mkl')
    if not clips or samples_per_clip < 1 or not 0 <= skin_follow <= 1:
        raise ValueError('Provide clips, a positive sample count and skin_follow in [0,1]')
    with Image.open(ref_image) as im:
        im = ImageOps.exif_transpose(im).convert('RGB')
        ref = cv2.resize(np.asarray(im), analysis_size(*im.size), interpolation=cv2.INTER_AREA)
    ref_px, ref_skin, _, ref_mask = _sample(ref, 0)
    src, src_skin = [], []
    for path in clips:
        info = probe(str(path)); w,h = target_size(info, 360)
        for t in np.linspace(0, max(0, info.duration - 1/float(info.fps)), samples_per_clip):
            dec = Decoder(info,w,h,False,start=float(t),frames=1)
            try:
                frame = next(iter(dec), None)
            finally:
                err = dec.close()
            if frame is None:
                raise RuntimeError(f'Cannot decode {path} at {t:.2f}: {err}')
            arr = np.frombuffer(frame,np.uint8).reshape(h,w,3)
            try:
                px, skin, _, _ = _sample(arr, int(t*1000))
            except ValueError:  # fully clipped frame (for example a fade to black)
                continue
            src.append(px); src_skin.append(skin)
    if not src:
        raise ValueError("No unclipped pixels found in the source clips")
    source = np.concatenate(src); mus = source.mean(axis=0); mur = ref_px.mean(axis=0)
    grid = identity(33); lab = rgb_to_lab(grid)
    if method == 'mkl':
        cs = np.cov(source, rowvar=False); cr = np.cov(ref_px, rowvar=False)
        root = _root(cs); inv = _root(cs, True)
        transform = inv @ _root(root @ cr @ root) @ inv
        # Blend toward identity just enough to keep diagonal gains in safe ranges.
        blend = 1.
        for gain, low, high in zip(np.diag(transform), [.6,.4,.4], [1.6,2.,2.]):
            if gain < low: blend = min(blend, (1-low)/(1-gain))
            if gain > high: blend = min(blend, (high-1)/(gain-1))
        transform = np.eye(3) + blend*(transform-np.eye(3))
        shift = np.clip(mur-mus, [-25,-30,-30], [25,30,30]) # maximum mean displacement in Lab
        global_lab = (lab-mus) @ transform.T + mus + shift
    else:
        global_lab = _grade_fit(source, ref_px, lab)
    skin_lab = lab + (global_lab-lab)*np.array([.7,skin_follow,skin_follow])
    source_skin = np.concatenate(src_skin)
    if (ref_mask >= .3).mean() >= .015 and len(source_skin): # reference skin occupies >= 1.5%
        adjustment = (ref_skin.mean(axis=0)-source_skin.mean(axis=0))*skin_follow
        skin_lab += np.clip(adjustment, [-6,-4,-4], [6,4,4])
    global_rgb = np.clip(soft_clip(lab_to_rgb(global_lab)),0,1)
    skin_rgb = np.clip(protect_skin(grid, np.clip(soft_clip(lab_to_rgb(skin_lab)),0,1), 1),0,1)
    slug = re.sub(r'[^a-z0-9_]+', '_', (name or Path(ref_image).stem).lower()).strip('_')
    slug = slug or 'ref_' + datetime.now().strftime('%Y%m%d_%H%M%S')
    stem = 'ref_' + slug
    LUT_DIR.mkdir(exist_ok=True); STYLE_DIR.mkdir(exist_ok=True)
    write_cube(LUT_DIR / (stem+'.cube'), global_rgb)
    write_cube(LUT_DIR / (stem+'_skin.cube'), skin_rgb)
    data = {'title':'追色·'+slug,'lut':stem+'.cube','skin_lut':stem+'_skin.cube',
            'skin_protect':1.0,'comment':'Reference photo colour transfer','reference':str(ref_image)}
    (STYLE_DIR / (stem+'.json')).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    return load_style(stem)
