"""Standalone GPUPixel reshape experiment.

Port of the thinFace/curveWarp and bigEye/enlargeEye shader mathematics in
pixpark/gpupixel src/filter/face_reshape_filter.cc, Copyright 2021 PixPark,
Apache License 2.0. Modified for MediaPipe landmarks, two faces and GL 3.3.
See https://github.com/pixpark/gpupixel/blob/main/LICENSE .
Run: python tools/proto/gpupixel_reshape.py [profile|compare]
"""
import cProfile
import io
import pstats
import sys
import time
from pathlib import Path

import cv2
import moderngl
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools')]
from test_a import capture, detect, measure, contour_roughness, render
from cake.render.context import RenderContext
from cake.render.passes.warp import JAW

# GPUPixel's 106-point pairs, approximated by corresponding MediaPipe contour
# and nose/mouth midline. The source has no published 106-to-478 correspondence.
# Only the 11 source pairs used by its shader are mapped; 106 unused slots are
# deliberately not invented. Each tuple is (origin, target), MediaPipe indices.
JAW_MAP = ((93, 1), (323, 1), (58, 4), (288, 4), (172, 2),
           (397, 2), (149, 152), (378, 152), (152, 152))
EYE_MAP = ((468, 33), (473, 263))  # iris centres and outer corners

SHADER = '''#version 330
in vec2 uv;
out vec4 o;
uniform sampler2D src;
uniform vec2 size;
uniform int jawCount;
uniform int eyeCount;
uniform vec4 jaw[18];
uniform vec4 eyes[4];
uniform float thinDelta;
uniform float eyeDelta;
void main() {
    vec2 p = uv * size;
    for (int i=0; i<jawCount; ++i) {
        vec2 origin = jaw[i].xy;
        vec2 target = jaw[i].zw;
        float radius = distance(target, origin);
        if (radius > 0.001) {
            float ratio = clamp(1.0 - distance(p, origin)/radius, 0.0, 1.0);
            p -= (target-origin) * thinDelta * ratio;
        }
    }
    for (int i=0; i<eyeCount; ++i) {
        vec2 origin = eyes[i].xy;
        vec2 target = eyes[i].zw;
        float radius = 5.0 * distance(target, origin);
        if (radius > 0.001) {
            float weight = distance(p, origin)/radius;
            weight = clamp(1.0-(1.0-weight*weight)*eyeDelta, 0.0, 1.0);
            p = origin + (p-origin)*weight;
        }
    }
    o = texture(src, clamp(p/size, vec2(0), vec2(1)));
}
'''


def mapped(points, width, height):
    """Map analysis-pixel MediaPipe landmarks into output-pixel control pairs."""
    points = np.asarray(points, np.float32)
    if len(points) < 474:
        raise ValueError('478 MediaPipe landmarks including iris points required')
    return (np.array([np.r_[points[a], points[b]] for a, b in JAW_MAP], np.float32),
            np.array([np.r_[points[a], points[b]] for a, b in EYE_MAP], np.float32))


class Port:
    def __init__(self, width, height):
        self.width, self.height = width, height
        self.ctx = RenderContext(width, height)
        self.program, self.va = self.ctx.program(SHADER)
        self.source = self.ctx.gl.texture((width, height), 3)
        self.source.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.target = self.ctx.gl.texture((width, height), 4)
        self.fb = self.ctx.gl.framebuffer(color_attachments=[self.target])

    def run(self, rgb, faces, thin, eye):
        h, w = rgb.shape[:2]
        t0 = time.perf_counter()
        jaws, eyes = [], []
        for points in faces[:2]:
            j, e = mapped(points, w, h)
            jaws.extend(j); eyes.extend(e)
        cpu_map = (time.perf_counter()-t0)*1000
        self.source.write(np.ascontiguousarray(rgb).tobytes())
        self.fb.use()
        self.source.use(0)
        self.ctx.uniforms(self.program, src=0, size=(w, h), jawCount=len(jaws),
                          eyeCount=len(eyes), thinDelta=thin, eyeDelta=eye)
        if jaws:
            self.program['jaw'].value = tuple(map(tuple, jaws)) + ((0, 0, 0, 0),)*(18-len(jaws))
            self.program['eyes'].value = tuple(map(tuple, eyes)) + ((0, 0, 0, 0),)*(4-len(eyes))
        cpu_submit = (time.perf_counter()-t0)*1000-cpu_map
        query = self.ctx.gl.query(time=True)
        with query:
            self.va.render(moderngl.TRIANGLE_STRIP)
        cpu_draw = (time.perf_counter()-t0)*1000-cpu_map-cpu_submit
        image = np.frombuffer(self.fb.read(components=3, alignment=1), np.uint8).reshape(h, w, 3).copy()
        total = (time.perf_counter()-t0)*1000
        return image, dict(map=cpu_map, upload_uniform=cpu_submit, draw_submit=cpu_draw,
                           readback_sync=total-cpu_map-cpu_submit-cpu_draw,
                           gpu=query.elapsed/1e6, total=total)


def main_profile():
    from dataclasses import replace
    from cake.analysis.analyzer import FaceInputs
    from cake.core.recipe import Recipe, RetouchCfg
    from cake.render.renderer import Renderer
    rgb = capture('asian_hush_48036.mp4', 4)
    h, w = rgb.shape[:2]
    rgb = cv2.resize(rgb, (1080, 1920)) if h > w else cv2.resize(rgb, (1920, 1080))
    raw = detect(rgb, 4000)
    r = Renderer(rgb.shape[1], rgb.shape[0], False)
    try:
        r.apply_recipe(Recipe(style='none', retouch=RetouchCfg(level=0.),
                              sections={'reshape': {'slim': 1., 'eyes': 1.}}))
        r.set_face(FaceInputs(raw.seg, raw.seg, 0., raw.layers, raw.face_h,
                              raw.boxes, True, raw.landmarks, raw.region_names, raw.regions))
        stage = r._by_name['warp']
        stage._update_tracks(r._face)
        r._face = replace(r._face, reset=False)
        for _ in range(7):
            stage.last_face = None
            stage._update_tracks(r._face)
        q = r._gl.gl.query(time=True)
        original = stage.run
        def timed(fc):
            with q:
                original(fc)
        stage.run = timed
        r.render(rgb.tobytes(), 0)
        profile = cProfile.Profile()
        profile.enable()
        t0 = time.perf_counter()
        r.render(rgb.tobytes(), 1)
        total = (time.perf_counter()-t0)*1000
        profile.disable()
        out = io.StringIO()
        pstats.Stats(profile, stream=out).sort_stats('tottime').print_stats(22)
        print(f'OUR full render wall {total:.2f} ms; warp GPU {q.elapsed/1e6:.2f} ms')
        print(out.getvalue())
    finally:
        r.release()


def main_compare():
    cases = [('asian_hush_48036.mp4', 4), ('asian_indoor_48688.mp4', 3),
             ('asian_mother_child_48689.mp4', 3)]
    panels = []
    for name, seconds in cases:
        rgb = capture(name, seconds)
        h, w = rgb.shape[:2]
        rgb = cv2.resize(rgb, (1080, 1920)) if h > w else cv2.resize(rgb, (1920, 1080))
        raw = detect(rgb, seconds*1000)
        faces = [p * (rgb.shape[1]/raw.layers.shape[1], rgb.shape[0]/raw.layers.shape[0]) for p in raw.landmarks[:2]]
        ours_base, _, _, _, _ = render(rgb, raw, 0., 0.)
        ours, ours_wall, _, ours_gpu, _ = render(rgb, raw, 1., 1.)
        port = Port(rgb.shape[1], rgb.shape[0])
        port_base, _ = port.run(rgb, faces, 0., 0.)
        # Match approximately 5% jaw narrowing; report exact output measurements.
        gp, timing = port.run(rgb, faces, .03, .12)
        outside = np.ones(rgb.shape[:2], np.uint8)
        face_area = np.zeros(rgb.shape[:2], np.uint8)
        for p in faces:
            left, top = np.floor(p.min(axis=0)).astype(int)
            right, bottom = np.ceil(p.max(axis=0)).astype(int)
            margin = int(max(right-left,bottom-top)*.18)
            cv2.rectangle(outside, (left-margin,top-margin), (right+margin,bottom+margin), 0, -1)
            cv2.rectangle(face_area, (left,top), (right,bottom), 1, -1)
        outer = outside.astype(bool)
        near = (~outer) & (~face_area.astype(bool))
        for label, image, base in [('ours', ours, ours_base), ('port', gp, port_base)]:
            delta = np.max(np.abs(image.astype(np.int16)-base.astype(np.int16)), axis=2)
            print(name, label, 'far_changed_%', round(100*np.mean(delta[outer]>2),3),
                  'far_max_channel', int(delta[outer].max()), 'far_mean', round(float(delta[outer].mean()),3),
                  'near_changed_%',round(100*np.mean(delta[near]>2),3),
                  'near_mean',round(float(delta[near].mean()),3))
        for label, image in [('ours', ours), ('port', gp)]:
            detected = detect(image, seconds*1000+100)
            remaining = list(detected.landmarks)
            for fi, before in enumerate(raw.landmarks[:2]):
                if not remaining:
                    print(name, label, fi, 'output face undetected'); continue
                # MediaPipe's multi-face output order is not stable.
                idx = min(range(len(remaining)), key=lambda k: np.linalg.norm(
                    remaining[k][[234,454]].mean(axis=0)-before[[234,454]].mean(axis=0)))
                after = remaining.pop(idx)
                bj, be = measure(before); aj, ae = measure(after)
                print(name, label, fi, 'jaw%', round(100*(1-aj/bj),2),
                      'eye%', round(100*(ae/be-1),2), 'roughness',
                      round(contour_roughness(after)/contour_roughness(before),3))
        print(name, 'ours wall/GPU', round(ours_wall,2), round(ours_gpu,2),
              'port times', timing)
        for image in (rgb, ours, gp):
            x0 = max(0, int(min(p[:,0].min() for p in faces)) - 100)
            x1 = min(rgb.shape[1], int(max(p[:,0].max() for p in faces)) + 100)
            y0 = max(0, int(min(p[:,1].min() for p in faces)) - 100)
            y1 = min(rgb.shape[0], int(max(p[:,1].max() for p in faces)) + 100)
            crop = cv2.resize(image[y0:y1,x0:x1], (480,480))
            panels.append(crop)
    review = np.concatenate([np.concatenate(panels[i:i+3], axis=1) for i in range(0,len(panels),3)], axis=0)
    path = ROOT/'tools/results/proto_reshape_review.jpg'
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), cv2.cvtColor(review, cv2.COLOR_RGB2BGR))
    print('review', path)


def main_temporal():
    """120 consecutive hush frames, same 15-frame high-pass/acceleration as test_a."""
    from dataclasses import replace
    from cake.analysis.analyzer import FaceInputs
    from cake.core.recipe import Recipe, RetouchCfg
    from cake.render.renderer import Renderer
    cap = cv2.VideoCapture(str(ROOT/'samples/asian_hush_48036.mp4'))
    fps = cap.get(cv2.CAP_PROP_FPS)
    values = {'ours':[], 'port':[]}
    r = None
    try:
        for i in range(120):
            ok, bgr = cap.read()
            if not ok: break
            h0,w0 = bgr.shape[:2]
            w,h = (round(w0*360/min(w0,h0)),round(h0*360/min(w0,h0)))
            rgb = cv2.resize(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB),(w,h))
            raw = detect(rgb,round(i*1000/fps))
            if not raw.landmarks: continue
            points = raw.landmarks[0]
            if r is None:
                r = Renderer(w,h,False)
                r.apply_recipe(Recipe(style='none',retouch=RetouchCfg(level=0.),
                                      sections={'reshape':{'slim':1.,'eyes':1.}}))
            r.set_face(FaceInputs(raw.seg,raw.seg,0.,raw.layers,raw.face_h,raw.boxes,
                                  i==0,raw.landmarks,raw.region_names,raw.regions))
            r.render(rgb.tobytes(),i)
            stage = r._by_name['warp']
            if stage.history_valid:
                tex = stage.history[stage.history_index]
                field = np.frombuffer(tex.read(),np.float16).reshape(tex.height,tex.width,2)
                xy = points[list(JAW)]
                x = np.clip((xy[:,0]/w*tex.width).astype(int),0,tex.width-1)
                y = np.clip((xy[:,1]/h*tex.height).astype(int),0,tex.height-1)
                values['ours'].append(float(np.mean(np.linalg.norm(field[y,x]*[w,h],axis=1))))
            j,e = mapped(points,w,h)
            xy = points[list(JAW)].copy()
            orig = xy.copy()
            for a,b,c,d in j:
                origin=np.array([a,b]); target=np.array([c,d]); radius=np.linalg.norm(target-origin)
                if radius>0: xy -= (target-origin)*.03*np.clip(1-np.linalg.norm(xy-origin,axis=1)/radius,0,1)[:,None]
            values['port'].append(float(np.mean(np.linalg.norm(xy-orig,axis=1))))
        for key, v in values.items():
            v=np.asarray(v)
            smooth=np.convolve(v,np.ones(15)/15,mode='valid')
            denom=max(np.median(v),1e-9)
            print('temporal',key,'frames',len(v),'mean_px',round(float(v.mean()),4),
                  'highpass_std_%',round(float(100*np.std(v[7:-7]-smooth)/denom),3),
                  'accel_p95_%',round(float(100*np.percentile(abs(np.diff(v,2)),95)/denom),3))
    finally:
        cap.release()
        if r is not None:r.release()


if __name__ == '__main__':
    {'profile': main_profile, 'compare': main_compare, 'temporal': main_temporal}[sys.argv[1] if len(sys.argv)>1 else 'compare']()
