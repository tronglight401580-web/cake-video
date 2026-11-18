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


def detect_shots(clip):
    """Return half-open frame ranges on the decoder's constant-rate timeline."""
    info = probe(str(clip))
    w, h = target_size(info, 180)
    dec = Decoder(info, w, h, False)
    previous = None
    cuts = [0]
    count = 0
    minimum = max(1, round(float(info.fps) * .5))
    try:
        for i, frame in enumerate(dec):
            count = i + 1
            if i % 2:
                continue
            rgb = np.frombuffer(frame, np.uint8).reshape(h, w, 3)
            hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
            hist = cv2.calcHist([hsv], [0, 1, 2], None, [12, 4, 4], [0, 180, 0, 256, 0, 256]).ravel()
            hist /= max(hist.sum(), 1)
            if previous is not None:
                distance = .5 * np.sum((hist - previous) ** 2 / (hist + previous + 1e-10))
                if distance > .45 and i - cuts[-1] >= minimum:
                    cuts.append(i)
            previous = hist
    finally:
        err = dec.close()
    if not count:
        raise RuntimeError(f'Cannot decode {clip}: {err}')
    if len(cuts) > 1 and count - cuts[-1] < minimum:
        cuts.pop()
    return list(zip(cuts, cuts[1:] + [count]))


def build_reference_style(ref_image: str, clips: list[str], name: str | None = None,
                          skin_follow: float = .2, samples_per_clip: int = 8, method: str = "grade", per_shot: bool = False):
    if per_shot and (len(clips) != 1 or method != 'grade'):
        raise ValueError('per-shot fitting requires one clip and method=grade')
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
            if frame is None and t > 0:
                dec = Decoder(info, w, h, False, start=max(0, float(t) - 1/float(info.fps)), frames=1)
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
    if per_shot:
        info = probe(str(clips[0])); w, h = target_size(info, 360)
        data['shots'] = []
        for k, (start, end) in enumerate(detect_shots(clips[0])):
            shot_src, shot_skin = [], []
            for frame_index in np.linspace(start, end - 1, samples_per_clip, dtype=int):
                t = frame_index / float(info.fps)
                dec = Decoder(info, w, h, False, start=t, frames=1)
                try:
                    frame = next(iter(dec), None)
                finally:
                    dec.close()
                if frame is None:
                    continue
                try:
                    px, sk, _, _ = _sample(np.frombuffer(frame, np.uint8).reshape(h, w, 3), int(t * 1000))
                except ValueError:
                    continue
                shot_src.append(px); shot_skin.append(sk)
            if shot_src and sum(len(x) for x in shot_src) >= 100:
                shot_lab = _grade_fit(np.concatenate(shot_src), ref_px, lab)
                shot_skin_lab = lab + (shot_lab-lab)*np.array([.7,skin_follow,skin_follow])
                ss = np.concatenate(shot_skin)
                if (ref_mask >= .3).mean() >= .015 and len(ss):
                    shot_skin_lab += np.clip((ref_skin.mean(axis=0)-ss.mean(axis=0))*skin_follow, [-6,-4,-4], [6,4,4])
                shot_rgb = np.clip(soft_clip(lab_to_rgb(shot_lab)), 0, 1)
                shot_skin_rgb = np.clip(protect_skin(grid, np.clip(soft_clip(lab_to_rgb(shot_skin_lab)), 0, 1), 1), 0, 1)
            else:
                shot_rgb, shot_skin_rgb = global_rgb, skin_rgb
            lut_name, skin_name = f'{stem}_s{k}.cube', f'{stem}_s{k}_skin.cube'
            write_cube(LUT_DIR / lut_name, shot_rgb)
            write_cube(LUT_DIR / skin_name, shot_skin_rgb)
            data['shots'].append(dict(start=start, end=end, lut=lut_name, skin_lut=skin_name))
    (STYLE_DIR / (stem+'.json')).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    return load_style(stem)


# ---------------------------------------------------------------------------
# Paired fit: the reference is the SAME frame re-graded (e.g. by an image model),
# so every pixel is a (source colour -> target colour) sample. We regress a 3D LUT
# directly instead of matching statistics, which reproduces the grade far more
# faithfully than the conservative scene-to-scene `grade` method.

PAIRED_SHORT = 480   # working resolution (short side) for paired fitting


def apply_lut(lut, rgb):
    """Trilinear lookup. lut (n,n,n,3) indexed [b,g,r]; rgb (...,3) float in [0,1]."""
    n = lut.shape[0]
    c = np.clip(np.asarray(rgb, np.float64), 0, 1) * (n - 1)
    i0 = np.minimum(np.floor(c).astype(int), n - 2)
    f = c - i0
    out = np.zeros(c.shape, np.float64)
    for db in (0, 1):
        for dg in (0, 1):
            for dr in (0, 1):
                w = ((f[..., 2] if db else 1 - f[..., 2]) * (f[..., 1] if dg else 1 - f[..., 1])
                     * (f[..., 0] if dr else 1 - f[..., 0]))
                out += w[..., None] * lut[i0[..., 2] + db, i0[..., 1] + dg, i0[..., 0] + dr]
    return out


def _blur3(a, sigma):
    """Separable Gaussian over the three grid axes of a (n,n,n,...) array (zero padded)."""
    n = a.shape[0]
    x = np.arange(n)
    k = np.exp(-(x[:, None] - x[None, :]) ** 2 / (2 * sigma * sigma))
    for axis in range(3):
        a = np.moveaxis(np.tensordot(k, np.moveaxis(a, axis, 0), axes=(1, 0)), 0, axis)
    return a


def align_pair(src, tgt):
    """Resize `tgt` to `src` and undo small shifts / scales an image model may introduce.
    ECC runs on histogram-equalised grey so the colour grade itself does not bias it.
    Returns (aligned uint8 RGB, ok)."""
    h, w = src.shape[:2]
    tgt = cv2.resize(tgt, (w, h), interpolation=cv2.INTER_AREA)
    g1 = cv2.equalizeHist(cv2.cvtColor(src, cv2.COLOR_RGB2GRAY)).astype(np.float32) / 255
    g2 = cv2.equalizeHist(cv2.cvtColor(tgt, cv2.COLOR_RGB2GRAY)).astype(np.float32) / 255
    warp = np.eye(2, 3, dtype=np.float32)
    try:
        _, warp = cv2.findTransformECC(g1, g2, warp, cv2.MOTION_AFFINE,
                                       (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 80, 1e-5), None, 5)
    except cv2.error:
        return tgt, False
    if np.abs(warp[:, :2] - np.eye(2)).max() > .06 or np.abs(warp[:, 2]).max() > .06 * max(w, h):
        return tgt, False   # implausible warp: content changed too much, keep the plain resize
    return cv2.warpAffine(tgt, warp, (w, h), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                          borderMode=cv2.BORDER_REPLICATE), True


def fit_paired_lut(src, tgt, weight=None, n=33, sigma=1.2, confidence=5.0):
    """Regress a smooth 3D LUT from paired colours.

    src, tgt: (N,3) floats in [0,1]. An affine RGB fit (ridge toward identity) is the prior;
    the per-node residual is splatted trilinearly, Gaussian-blurred in grid space and shrunk
    toward the prior where fewer than ~`confidence` samples support a node, so colours the
    frame never shows follow the global trend instead of extrapolating."""
    src = np.asarray(src, np.float64)
    tgt = np.asarray(tgt, np.float64)
    w = np.ones(len(src)) if weight is None else np.asarray(weight, np.float64)
    x = np.c_[src, np.ones(len(src))]
    lam = 1e-3 * w.sum()
    eye = np.r_[np.eye(3), np.zeros((1, 3))]
    m = np.linalg.solve((x * w[:, None]).T @ x + lam * np.eye(4), (x * w[:, None]).T @ tgt + lam * eye)
    grid = identity(n)
    prior = grid + np.clip(np.c_[grid.reshape(-1, 3), np.ones(n ** 3)] @ m - grid.reshape(-1, 3),
                           -.3, .3).reshape(grid.shape)
    resid = tgt - (src + np.clip(x @ m - src, -.3, .3))
    c = np.clip(src, 0, 1) * (n - 1)
    i0 = np.minimum(np.floor(c).astype(int), n - 2)
    f = c - i0
    acc_w = np.zeros(n ** 3)
    acc_d = np.zeros((n ** 3, 3))
    for db in (0, 1):
        for dg in (0, 1):
            for dr in (0, 1):
                tw = w * ((f[:, 2] if db else 1 - f[:, 2]) * (f[:, 1] if dg else 1 - f[:, 1])
                          * (f[:, 0] if dr else 1 - f[:, 0]))
                idx = ((i0[:, 2] + db) * n + i0[:, 1] + dg) * n + i0[:, 0] + dr
                acc_w += np.bincount(idx, tw, n ** 3)
                for ch in range(3):
                    acc_d[:, ch] += np.bincount(idx, tw * resid[:, ch], n ** 3)
    bw = _blur3(acc_w.reshape(n, n, n), sigma)
    bd = _blur3(acc_d.reshape(n, n, n, 3), sigma)
    return np.clip(prior + bd / (bw + confidence)[..., None], 0, 1)


def build_paired_style(src_image, graded_image, name: str | None = None,
                       skin_follow: float = .2, reference: str | None = None):
    """Fit a style from a frame and the same frame re-graded (Codex / any photo editor).

    src_image / graded_image: paths or RGB uint8 arrays. Returns (Style, fit_de76) where
    fit_de76 is the mean CIE76 distance between LUT(frame) and the graded frame."""
    if not 0 <= skin_follow <= 1:
        raise ValueError('skin_follow must be in [0,1]')

    def load(img):
        if isinstance(img, np.ndarray):
            return img[..., :3].astype(np.uint8)
        with Image.open(img) as im:
            return np.asarray(ImageOps.exif_transpose(im).convert('RGB'))

    src, tgt = load(src_image), load(graded_image)
    h, w = src.shape[:2]
    k = min(1.0, PAIRED_SHORT / min(h, w))
    src = cv2.resize(src, (max(2, round(w * k)), max(2, round(h * k))), interpolation=cv2.INTER_AREA)
    sa, ta = src.shape, tgt.shape
    if abs(sa[1] / sa[0] - ta[1] / ta[0]) > .04 * sa[1] / sa[0]:
        raise ValueError(f'graded image aspect {ta[1]}x{ta[0]} does not match the frame '
                         f'{sa[1]}x{sa[0]}: the model must not crop or change the framing')
    tgt, _ = align_pair(src, tgt)
    # Blur both slightly: residual misregistration and generator texture average out.
    s = cv2.GaussianBlur(src, (0, 0), 1.2).reshape(-1, 3) / 255.
    t = cv2.GaussianBlur(tgt, (0, 0), 1.2).reshape(-1, 3) / 255.
    grey = cv2.cvtColor(src, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255
    grad = np.hypot(cv2.Sobel(grey, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(grey, cv2.CV_32F, 0, 1, ksize=3))
    weight = 1 / (1 + (grad.reshape(-1) / .15) ** 2)   # edges are where misalignment hurts
    lut = fit_paired_lut(s, t, weight)
    fit = float(np.linalg.norm(rgb_to_lab(apply_lut(lut, s)) - rgb_to_lab(t), axis=-1).mean())
    grid = identity(33)
    lab, global_lab = rgb_to_lab(grid), rgb_to_lab(lut)
    skin_lab = lab + (global_lab - lab) * np.array([.7, skin_follow, skin_follow])
    skin_rgb = np.clip(protect_skin(grid, np.clip(soft_clip(lab_to_rgb(skin_lab)), 0, 1), 1), 0, 1)
    ref_path = reference or ('' if isinstance(graded_image, np.ndarray) else str(graded_image))
    slug = re.sub(r'[^a-z0-9_]+', '_', (name or Path(ref_path or 'codex').stem).lower()).strip('_')
    slug = slug or 'ref_' + datetime.now().strftime('%Y%m%d_%H%M%S')
    stem = 'ref_' + slug
    LUT_DIR.mkdir(exist_ok=True); STYLE_DIR.mkdir(exist_ok=True)
    write_cube(LUT_DIR / (stem + '.cube'), lut)
    write_cube(LUT_DIR / (stem + '_skin.cube'), skin_rgb)
    data = {'title': '追色·' + slug, 'lut': stem + '.cube', 'skin_lut': stem + '_skin.cube',
            'skin_protect': 1.0, 'comment': f'Paired-frame colour fit (mean dE76 {fit:.2f})',
            'reference': ref_path}
    (STYLE_DIR / (stem + '.json')).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return load_style(stem), fit
