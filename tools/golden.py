"""Record and compare raw NV12 output from the original video pipeline."""
import argparse
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cake import pipeline, refcolor
from cake.media import target_size
from cake.probe import probe
from cake.styles import load_style

RESULTS = ROOT / 'tools' / 'results' / 'golden'
CONFIGS = [
    ('g1', 'asian_hush_48036.mp4', 'film_warm', .5, {}),
    ('g2', 'street_mixed_1227.mp4', 'teal_orange_portrait', 1., {}),
    ('g3', 'neon_night_1230.mp4', 'ccd', 0., {}),
    ('g4', 'asian_mother_child_48689.mp4', 'none', .5, {'spots': 1., 'under': .8, 'keep_moles': False}),
    ('g5', 'beach_daylight_1221.mp4', 'golden_ref', 0., {}),
]

class CaptureEncoder:
    frames = None
    def __init__(self, *args, **kwargs):
        self.frames = []
        CaptureEncoder.frames = self.frames
    def write(self, frame):
        self.frames.append(np.frombuffer(frame, dtype=np.uint8).copy())
    def close(self):
        return 0, ''

def reference_style(tmp):
    import cake.styles as styles
    path = str(ROOT / 'samples' / 'street_mixed_1227.mp4')
    info = probe(path)
    w, h = target_size(info, 360)
    frame = pipeline._grab_frame(info, 0, w, h, False, 'mobius')
    image = Path(tmp) / 'reference.png'
    Image.fromarray(np.frombuffer(frame, np.uint8).reshape(h, w, 3)).save(image)
    lut_dir, style_dir = Path(tmp) / 'luts', Path(tmp) / 'styles'
    old = refcolor.LUT_DIR, refcolor.STYLE_DIR, styles.LUT_DIR, styles.STYLE_DIR
    refcolor.LUT_DIR = styles.LUT_DIR = lut_dir
    refcolor.STYLE_DIR = styles.STYLE_DIR = style_dir
    try:
        style = refcolor.build_reference_style(str(image), [str(ROOT / 'samples' / 'beach_daylight_1221.mp4')], name='golden_ref')
        # Load before restoring the paths: Style normally loads LUTs lazily.
        global_lut, skin_lut = style.load_lut(), style.load_skin_lut()
        style.load_lut = lambda: global_lut
        style.load_skin_lut = lambda: skin_lut
        return style
    finally:
        refcolor.LUT_DIR, refcolor.STYLE_DIR, styles.LUT_DIR, styles.STYLE_DIR = old

def capture(config, reference, tmp):
    ident, clip, name, retouch, opts = config
    path = str(ROOT / 'samples' / clip)
    info = probe(path)
    style = pipeline._identity_style() if name == 'none' else reference if name == 'golden_ref' else load_style(name)
    old = pipeline.Encoder
    pipeline.Encoder = CaptureEncoder
    try:
        pipeline.grade_video(path, str(Path(tmp) / 'unused.mp4'), style, retouch=retouch,
                             retouch_opts=opts, duration=24 / float(info.fps), skin_protect_scale=1.0)
        frames = np.stack(CaptureEncoder.frames)
        if len(frames) != 24:
            raise RuntimeError(f'{ident}: expected 24 frames, got {len(frames)}')
        return frames
    finally:
        pipeline.Encoder = old

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['record', 'check'])
    args = parser.parse_args()
    RESULTS.mkdir(parents=True, exist_ok=True)
    manifest_path = RESULTS / 'manifest.json'
    manifest = {'configs': {}, 'mean_tolerance': .05, 'max_tolerance': 2}
    if args.command == 'check':
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    failed = False
    with tempfile.TemporaryDirectory(dir=RESULTS) as tmp:
        reference = reference_style(tmp)
        for config in CONFIGS:
            ident = config[0]
            frames = capture(config, reference, tmp)
            dest = RESULTS / (ident + '.npz')
            if args.command == 'record':
                np.savez_compressed(dest, frames=frames)
                manifest['configs'][ident] = {'clip': config[1], 'style': config[2], 'retouch': config[3], 'options': config[4], 'shape': list(frames.shape)}
                print(f'{ident}: recorded {len(frames)} frames', flush=True)
            else:
                baseline = np.load(dest)['frames']
                if baseline.shape != frames.shape:
                    raise ValueError(f'{ident}: shape mismatch: {baseline.shape} != {frames.shape}')
                diff = np.abs(frames.astype(np.int16) - baseline.astype(np.int16))
                mean, maximum = float(diff.mean()), int(diff.max())
                passed = mean <= manifest['mean_tolerance'] and maximum <= manifest['max_tolerance']
                print(f'{ident}: {"PASS" if passed else "FAIL"} mean={mean:.6f} max={maximum}', flush=True)
                failed |= not passed
    if args.command == 'record':
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return int(failed)

if __name__ == '__main__':
    sys.exit(main())
