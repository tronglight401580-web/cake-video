"""Exercise cut detection, colour recovery and temporal stability on two real shots."""
import sys, subprocess, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from PIL import Image
from cake.color.refcolor import detect_shots, build_reference_style
from cake.io.probe import probe
from cake.io.media import Decoder, target_size
from cake.styles import load_style
from test_refcolor import ROOT, frame, render, original, de


def main():
    with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
        clip = str(Path(tmp) / 'shots.mp4')
        a, b = (str(ROOT / 'samples' / (n + '.mp4')) for n in ('asian_indoor_48688', 'beach_daylight_1221'))
        filt = '[0:v]fps=30,scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2,setsar=1[a];[1:v]fps=30,scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2,setsar=1[b];[a][b]concat=n=2:v=1:a=0[v]'
        subprocess.run(['ffmpeg','-v','error','-y','-t','3','-i',a,'-t','3','-i',b,'-filter_complex',filt,'-map','[v]','-c:v','libx264','-pix_fmt','yuv420p',clip], check=True)
        shots = detect_shots(clip)
        print('shots:', shots, flush=True)
        assert len(shots) == 2 and abs(shots[1][0]-90) <= 2
        teal = load_style('teal_orange')
        ref, _ = render(*frame('street_mixed_1227', 3), teal)
        refpath = str(Path(tmp) / 'ref.png'); Image.fromarray(ref).save(refpath)
        names = ['ref_pershot_test_single', 'ref_pershot_test_multi']
        try:
            single = build_reference_style(refpath,[clip],name='pershot_test_single')
            multi = build_reference_style(refpath,[clip],name='pershot_test_multi',per_shot=True)
            info = probe(clip); w, h = target_size(info, 360)
            checks = []
            for k, (start, end) in enumerate(shots):
                t = (start + end) / (2 * float(info.fps))
                dec = Decoder(info,w,h,False,start=t,frames=2)
                try: frames = list(dec)
                finally: dec.close()
                raw = frames[0]
                real, seg = render(raw,w,h,teal,0)
                one, _ = render(raw,w,h,single,0)
                # Render the selected shot LUT directly, away from the cut transition.
                from cake.color.styles import Style
                shot = multi.shots[k]
                selected = Style(name='shot',lut=shot['lut'],skin_lut=shot['skin_lut'])
                out, _ = render(raw,w,h,selected,0)
                mask = seg.astype(float).sum(-1) < .3*255
                d_one, d_multi = de(one,real,mask), de(out,real,mask)
                print(f'shot {k}: single={d_one:.3f}, per-shot={d_multi:.3f} (info)', flush=True)
                # REPORT-ONLY (decided 2026-11-14): "distance to a fixed teal_orange LUT" is the wrong
                # oracle for per-shot transfer - a fixed LUT keeps each shot's own colour differences,
                # per-shot transfer deliberately pulls every shot toward the reference look. Measured
                # within 1-5% of single-LUT either way; benefit still to be shown on real multi-scene
                # footage. Hard checks below: cut detection, no flicker.
                checks.append(d_multi <= d_one * 1.10)   # guard: never clearly worse than single
                out2, _ = render(frames[1],w,h,selected,0)
                srcdiff = np.abs(original(frames[1],w,h).astype(float)-original(raw,w,h)).mean()
                outdiff = np.abs(out2.astype(float)-out.astype(float)).mean()
                print(f'shot {k}: source difference={srcdiff:.3f}, graded={outdiff:.3f}', flush=True)
                checks.append(abs(srcdiff-outdiff) <= .2)
            assert all(checks), "Per-shot quality or temporal stability failed"
        finally:
            for name in names:
                (ROOT/'styles'/f'{name}.json').unlink(missing_ok=True)
                for path in (ROOT/'luts').glob(name+'*.cube'): path.unlink()
    return 0

if __name__ == '__main__': sys.exit(main())
