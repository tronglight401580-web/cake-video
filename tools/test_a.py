"""Sample-based reshape review. Run with ``python tools/test_a.py``."""
import sys
import csv
import time
import tempfile
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cake.analysis.analyzer import FaceInputs, run_models
from cake.analysis.frames import analysis_size
from cake.core.recipe import Recipe, RetouchCfg
from cake.render.renderer import Renderer
from cake.render.passes.warp import JAW, LEFT_EYE, RIGHT_EYE, controls, yaw_weight
import cake.render.passes.warp as warp_module
from cake.pipeline import grade_video
from cake.probe import probe
from flicker import frame_stream, make_landmarker


def capture(name, seconds):
    cap = cv2.VideoCapture(str(ROOT / 'samples' / name))
    try:
        cap.set(cv2.CAP_PROP_POS_MSEC, seconds * 1000)
        ok, bgr = cap.read()
        if not ok:
            raise RuntimeError(f'cannot read {name} at {seconds}s')
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        scale = min(1., 720 / min(w, h))
        if scale < 1:
            rgb = cv2.resize(rgb, (round(w * scale), round(h * scale)))
        return rgb
    finally:
        cap.release()


def detect(rgb, ts):
    h, w = rgb.shape[:2]
    aw, ah = analysis_size(w, h)
    return run_models(cv2.resize(rgb, (aw, ah), interpolation=cv2.INTER_AREA), True, ts_ms=ts)


def measure(points):
    jaw = np.linalg.norm(points[132] - points[361])
    eyes = np.mean([np.linalg.norm(points[a] - points[b]) for a, b in ((33, 133), (362, 263))])
    return float(jaw), float(eyes)


def contour_roughness(points):
    """Mean absolute second difference of the detected output jaw, at 2 px spacing."""
    curve = points[list(JAW)].astype(np.float32)
    distance = np.r_[0., np.cumsum(np.linalg.norm(np.diff(curve, axis=0), axis=1))]
    sampled = np.arange(0., distance[-1], 2.)
    xy = np.stack([np.interp(sampled, distance, curve[:, axis]) for axis in (0, 1)], -1)
    return float(np.linalg.norm(np.diff(xy, n=2, axis=0), axis=1).mean())


def render(rgb, raw, slim, eyes):
    h, w = rgb.shape[:2]
    r = Renderer(w, h, False)
    try:
        recipe = Recipe(style='none', retouch=RetouchCfg(level=0.),
                        sections={'reshape': {'slim': slim, 'eyes': eyes}})
        r.apply_recipe(recipe)
        r.set_face(FaceInputs(raw.seg, raw.seg, 0., raw.layers, raw.face_h,
                              raw.boxes, True, raw.landmarks, raw.region_names, raw.regions))
        # Allow the appearance fade to settle, as it does after eight video frames.
        stage = r._by_name['warp']
        query = r._gl.gl.query(time=True) if slim or eyes else None
        if slim or eyes:
            stage._update_tracks(r._face)
            r._face = replace(r._face, reset=False)
            for _ in range(7):
                stage.last_face = None
                stage._update_tracks(r._face)
        if query is not None:
            original_run = stage.run
            def timed_run(fc):
                with query:
                    original_run(fc)
            stage.run = timed_run
            r.render(rgb.tobytes(), 0)
            r.render(rgb.tobytes(), 0)
        t0 = time.perf_counter()
        output = r.render(rgb.tobytes(), 0)
        elapsed = (time.perf_counter() - t0) * 1000
        gpu_ms = query.elapsed / 1e6 if query is not None else 0.
        max_move = 0.
        if stage.field is not None:
            field = np.frombuffer(stage.field.read(), np.float16).reshape(stage.field.height, stage.field.width, 2).astype(np.float32)
            max_move = float(np.linalg.norm(field * (w, h), axis=2).max())
        skin = None
        if stage.targets.get('skin'):
            texture = stage.targets['skin'][0]
            skin = np.frombuffer(texture.read(), np.float16).reshape(texture.height, texture.width, 4)[..., 0].astype(np.float32).copy()
        return np.frombuffer(output, np.uint8).reshape(h, w, 3).copy(), elapsed, skin, gpu_ms, max_move
    finally:
        r.release()


def main():
    cases = [('asian_hush_48036.mp4', 4), ('asian_indoor_48688.mp4', 3),
             ('asian_mother_child_48689.mp4', 2)]
    panels = []
    failures = []
    for case, seconds in cases:
        rgb = capture(case, seconds)
        raw = detect(rgb, int(seconds * 1000))
        if not raw.landmarks:
            raise AssertionError(f'no input face: {case}')
        baseline, _, _, _, _ = render(rgb, raw, 0., 0.)
        half, _, _, _, _ = render(rgb, raw, .5, 0.) if case != 'asian_mother_child_48689.mp4' else (None, 0, None, 0, 0)
        changed, ms, skin, gpu_ms, max_move = render(rgb, raw, 1., 1.)
        output_raw = detect(changed, int(seconds * 1000) + 100)
        if not output_raw.landmarks:
            raise AssertionError(f'no output face: {case}')
        before = measure(raw.landmarks[0])
        after = measure(output_raw.landmarks[0])
        jaw_pct = 100 * (1 - after[0] / before[0])
        eye_pct = 100 * (after[1] / before[1] - 1)
        if half is not None:
            half_raw = detect(half, int(seconds * 1000) + 200)
            full_jaw, _, _, _, _ = render(rgb, raw, 1., 0.)
            full_raw = detect(full_jaw, int(seconds * 1000) + 300)
            half_reduction = before[0] - measure(half_raw.landmarks[0])[0]
            full_reduction = before[0] - measure(full_raw.landmarks[0])[0]
            slider_ratio = half_reduction / max(full_reduction, 1e-6)
            print(f'  slim 0.5 / 1.0 jaw reduction: {slider_ratio:.3f} ({half_reduction:.2f} / {full_reduction:.2f} px)')
            if not .35 <= slider_ratio <= .65:
                failures.append(f'{case}: slim slider ratio {slider_ratio:.3f} outside 0.35-0.65')
        input_rough = contour_roughness(raw.landmarks[0])
        output_rough = contour_roughness(output_raw.landmarks[0])
        rough_ratio = output_rough / max(input_rough, 1e-9)
        if skin is not None:
            predicted = np.clip(output_raw.seg.astype(np.float32).sum(axis=2) / 255, 0, 1)
            if predicted.shape != skin.shape:
                predicted = cv2.resize(predicted, (skin.shape[1], skin.shape[0]))
            iou = float(np.minimum(skin, predicted).sum() / max(np.maximum(skin, predicted).sum(), 1))
        else:
            iou = float('nan')
        print(f'{case}: jaw {jaw_pct:+.2f}% narrower, eyes {eye_pct:+.2f}% wider; contour second-difference ratio {rough_ratio:.3f}; skin IoU {iou:.3f}; warp GPU {gpu_ms:.2f} ms, render {ms:.2f} ms, max move {max_move:.1f} px')
        if rough_ratio > 1.15:
            failures.append(f'{case}: contour roughness ratio {rough_ratio:.3f} above 1.15')
        if case in ('asian_hush_48036.mp4', 'asian_indoor_48688.mp4') and not 3 <= jaw_pct <= 6:
            failures.append(f'{case}: jaw reduction {jaw_pct:.2f}% outside 3-6%')
        if eye_pct <= 0:
            failures.append(f'{case}: eye width did not grow')
        if case in ('asian_hush_48036.mp4', 'asian_indoor_48688.mp4') and eye_pct < 3:
            failures.append(f'{case}: eye growth {eye_pct:.2f}% below 3%')
        if iou < .9:
            failures.append(f'{case}: skin IoU {iou:.3f} below 0.9')
        h, w = rgb.shape[:2]
        points = raw.landmarks[0] * np.array([w / raw.layers.shape[1], h / raw.layers.shape[0]])
        outside = np.ones((h, w), np.uint8)
        for raw_points in raw.landmarks[:2]:
            face_points = raw_points * np.array([w / raw.layers.shape[1], h / raw.layers.shape[0]])
            jaw_controls, eye_controls = controls(face_points, 1., 1., 1.)
            for x, y, _, _, radius, _ in jaw_controls:
                cv2.circle(outside, (round(x), round(y)), round(1.3 * radius), 0, -1)
            for x, y, radius, _ in eye_controls:
                cv2.circle(outside, (round(x), round(y)), round(1.3 * radius), 0, -1)
        unchanged = bool(np.array_equal(baseline[outside > 0], changed[outside > 0]))
        print(f'  pixels beyond 1.3R identical: {unchanged}')
        if not unchanged:
            failures.append(f'{case}: distant pixels changed')
        x0, y0 = np.maximum(points.min(axis=0) - 25, 0).astype(int)
        x1, y1 = np.minimum(points.max(axis=0) + 25, (w, h)).astype(int)
        crop_a, crop_b = baseline[y0:y1, x0:x1], changed[y0:y1, x0:x1]
        thumb_width = 320
        def thumb(a, height):
            return Image.fromarray(cv2.resize(a, (thumb_width, height)))
        full_h = round(h * thumb_width / w)
        crop_h = round((y1 - y0) * thumb_width / max(x1 - x0, 1))
        panel = Image.new('RGB', (thumb_width * 4, max(full_h, crop_h) + 32), 'white')
        for i, item in enumerate((baseline, changed, crop_a, crop_b)):
            image = thumb(item, full_h if i < 2 else crop_h)
            panel.paste(image, (i * thumb_width, 32))
        draw = ImageDraw.Draw(panel)
        for i, title in enumerate((f'{case} before', 'after', 'face before', 'face after')):
            draw.text((i * thumb_width + 4, 6), title, fill='black')
        panels.append(panel)
        if case == 'asian_hush_48036.mp4':
            half_review, _, _, _, _ = render(rgb, raw, .5, 1.)
            half_crop = half_review[y0:y1, x0:x1]
            slider_panel = Image.new('RGB', (thumb_width * 2, crop_h + 32), 'white')
            slider_panel.paste(thumb(half_crop, crop_h), (0, 32))
            slider_panel.paste(thumb(changed[y0:y1, x0:x1], crop_h), (thumb_width, 32))
            ImageDraw.Draw(slider_panel).text((4, 6), 'hush face: slim 0.5 / slim 1.0 (eyes 1.0 both)', fill='black')
            panels.append(slider_panel)
        if case in ('asian_hush_48036.mp4', 'asian_mother_child_48689.mp4'):
            # Exact 3x pixel crops around the left cheek/hair boundary.
            cheek = points[list(JAW[2:7])].mean(axis=0)
            face_width = float(np.linalg.norm(points[454] - points[234]))
            half = max(round(face_width * .16), 20)
            cx, cy = np.round(cheek).astype(int)
            lx, rx = max(cx-half, 0), min(cx+half, w)
            ty, by = max(cy-half, 0), min(cy+half, h)
            a = Image.fromarray(baseline[ty:by, lx:rx]).resize(((rx-lx)*3, (by-ty)*3))
            b = Image.fromarray(changed[ty:by, lx:rx]).resize(((rx-lx)*3, (by-ty)*3))
            detail = Image.new('RGB', (a.width + b.width, max(a.height, b.height) + 28), 'white')
            detail.paste(a, (0, 28)); detail.paste(b, (a.width, 28))
            ImageDraw.Draw(detail).text((4, 6), f'{case} left contour 3x: before / after', fill='black')
            panels.append(detail)
    review = Image.new('RGB', (max(p.width for p in panels), sum(p.height for p in panels)), 'white')
    y = 0
    for panel in panels:
        review.paste(panel, (0, y)); y += panel.height
    out = ROOT / 'tools' / 'results' / 'a_review.jpg'
    review.save(out, quality=90)
    print(f'review: {out}')
    return failures


def temporal():
    import mediapipe as mp

    failures, worst, fade_worst = [], [], []
    results_dir = ROOT / 'tools' / 'results'
    results_dir.mkdir(parents=True, exist_ok=True)
    video = results_dir / 'a_compare.mp4'
    writer = None
    with tempfile.TemporaryDirectory(prefix='warp-temporal-') as tmp:
        model_path = Path(tmp) / 'landmarker.task'
        shutil.copyfile(ROOT / 'models' / 'face_landmarker.task', model_path)
        with make_landmarker(model_path) as model:
            for name in ('asian_hush_48036.mp4', 'asian_indoor_48688.mp4'):
                source = ROOT / 'samples' / name
                cap = cv2.VideoCapture(str(source))
                fps = float(probe(str(source)).fps)
                width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                cap.release()
                scale = min(1., 360 / min(width, height))
                width, height = round(width * scale), round(height * scale)
                if writer is None:
                    writer = subprocess.Popen(['ffmpeg', '-y', '-v', 'error', '-f', 'rawvideo',
                        '-pix_fmt', 'rgb24', '-s', '1280x720', '-r', str(fps), '-i', '-',
                        '-an', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(video)], stdin=subprocess.PIPE)
                positions = {key: [] for key in ('base', 'noise', 'partial', 'full')}
                metrics = {'partial': [], 'full': []}
                previous = {}
                outside_max = {'partial': 0., 'full': 0.}
                cap = cv2.VideoCapture(str(source))
                frames = []
                try:
                    for _ in range(120):
                        ok, bgr = cap.read()
                        if not ok:
                            break
                        frames.append(cv2.resize(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), (width, height), interpolation=cv2.INTER_AREA))
                finally:
                    cap.release()
                raws = [detect(frame, round(i * 1000 / fps)) for i, frame in enumerate(frames)]
                renders = {}
                for key, slim, eyes in (('base', 0., 0.), ('partial', .7, .5), ('full', 1., 1.)):
                    renderer = Renderer(width, height, False)
                    try:
                        renderer.apply_recipe(Recipe(style='none', retouch=RetouchCfg(level=0.),
                            sections={'reshape': {'slim': slim, 'eyes': eyes}}))
                        outputs = []
                        for i, (frame, raw) in enumerate(zip(frames, raws)):
                            renderer.set_face(FaceInputs(raw.seg, raw.seg, 0., raw.layers, raw.face_h,
                                raw.boxes, i == 0, raw.landmarks, raw.region_names, raw.regions))
                            output = renderer.render(frame.tobytes(), i)
                            outputs.append(np.frombuffer(output, np.uint8).reshape(height, width, 3).copy())
                            if key != 'base':
                                stage = renderer._by_name['warp']
                                records = []
                                if stage.history_valid:
                                    texture = stage.history[stage.history_index]
                                    field = np.frombuffer(texture.read(), np.float16).reshape(texture.height, texture.width, 2).astype(np.float32)
                                    field *= (width, height)
                                    for track in stage.tracks[:2]:
                                        points = track['points']
                                        def sample(xy):
                                            xy = np.asarray(xy, np.float32)
                                            mx = (xy[:, 0] / width * texture.width - .5).reshape(-1, 1)
                                            my = (xy[:, 1] / height * texture.height - .5).reshape(-1, 1)
                                            return cv2.remap(field, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE).reshape(-1, 2)
                                        jaw = np.linalg.norm(sample(points[list(JAW)]), axis=1).mean()
                                        eye_values = []
                                        for contour in (LEFT_EYE, RIGHT_EYE):
                                            shape = points[list(contour)]
                                            centre = shape.mean(axis=0)
                                            radius = 1.15 * np.linalg.norm(shape[3] - shape[0])
                                            offset = max(radius * .15, 1.)
                                            d = sample([centre + (-offset, 0), centre + (offset, 0)])
                                            eye_values.append(-(d[1, 0] - d[0, 0]) / (2 * offset))
                                        records.append((float(jaw), float(np.mean(eye_values)), track['fade'] < 1 or yaw_weight(points) < .999))
                                metrics[key].append(records)
                        renders[key] = outputs
                    finally:
                        renderer.release()
                for frame_no, (frame, raw) in enumerate(zip(frames, raws)):
                    if not raw.landmarks:
                        failures.append(f'{name} frame {frame_no}: input face missing')
                        continue
                    rendered = {key: outputs[frame_no] for key, outputs in renders.items()}
                    centre = raw.landmarks[0][[234, 454]].mean(axis=0) * (width / raw.layers.shape[1], height / raw.layers.shape[0])
                    matrix = np.array([[1.002, 0, .37 - .002 * centre[0]], [0, 1.002, .37 - .002 * centre[1]]], np.float32)
                    rendered['noise'] = cv2.warpAffine(rendered['base'], matrix, (width, height), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)
                    for key, image in rendered.items():
                        result = model.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(image)))
                        points = (np.array([(p.x * width, p.y * height) for p in result.face_landmarks[0]])
                                  if result.face_landmarks else None)
                        positions[key].append(points)
                    outside = np.ones((height, width), np.uint8)
                    for face in raw.landmarks[:2]:
                        points = face * np.array([width / raw.layers.shape[1], height / raw.layers.shape[0]])
                        jaw, eyes = controls(points, 1., 1., 1.)
                        for x, y, _, _, radius, _ in jaw:
                            cv2.circle(outside, (round(x), round(y)), int(np.ceil(1.3 * radius)), 0, -1)
                        for x, y, radius, _ in eyes:
                            cv2.circle(outside, (round(x), round(y)), int(np.ceil(1.3 * radius)), 0, -1)
                    if previous:
                        mask = (outside > 0) & (previous['outside'] > 0)
                        for key in outside_max:
                            # flicker.py's signed luminance change difference, before encoding.
                            weights = np.array([.2126, .7152, .0722])
                            delta = ((rendered[key].astype(float) - previous[key]) -
                                     (rendered['base'].astype(float) - previous['base'])) @ weights
                            outside_max[key] = max(outside_max[key], float(np.max(np.abs(delta[mask]), initial=0)))
                    previous = {key: image.astype(float) for key, image in rendered.items()}
                    previous['outside'] = outside
                    def panel(image, label):
                        canvas = np.zeros((720, 640, 3), np.uint8)
                        factor = min(640 / width, 680 / height)
                        thumb = cv2.resize(image, (round(width * factor), round(height * factor)))
                        x, y = (640-thumb.shape[1])//2, 40+(680-thumb.shape[0])//2
                        canvas[y:y+thumb.shape[0], x:x+thumb.shape[1]] = thumb
                        cv2.putText(canvas, label, (8, 26), cv2.FONT_HERSHEY_SIMPLEX, .6, (255,255,255), 1)
                        return canvas
                    comparison = np.concatenate((panel(rendered['base'], f'{name} {frame_no}: unwarped'),
                                                 panel(rendered['full'], 'slim 1.0 / eyes 1.0')), axis=1)
                    writer.stdin.write(comparison.tobytes())
                    if frame_no and metrics['full'][frame_no] and metrics['full'][frame_no-1]:
                        now, before = metrics['full'][frame_no][0], metrics['full'][frame_no-1][0]
                        entry = (abs(now[0] - before[0]), name, frame_no, comparison)
                        if not now[2] and not before[2]:
                            worst.append(entry)
                        else:
                            fade_worst.append(entry)
                with (results_dir / (name + '_warp_metrics.csv')).open('w', newline='') as log:
                    rows = csv.writer(log)
                    rows.writerow(('setting', 'frame', 'face', 'jaw_displacement_px', 'eye_magnification', 'fade'))
                    for setting, frames_metrics in metrics.items():
                        for frame_index, records in enumerate(frames_metrics):
                            for face_index, record in enumerate(records):
                                rows.writerow((setting, frame_index, face_index, *record))
                for key in ('partial', 'full'):
                    face_count = max((len(row) for row in metrics[key]), default=0)
                    for face in range(face_count):
                        fade = sum(face < len(row) and row[face][2] for row in metrics[key])
                        valid = [i for i, row in enumerate(metrics[key]) if face < len(row) and not row[face][2]]
                        print(f'  field {key} face {face}: fade frames {fade}, eligible frames {len(valid)}')
                        for column, label in ((0, 'jaw displacement px'), (1, 'eye magnification')):
                            values = np.array([metrics[key][i][face][column] for i in valid])
                            if len(values) < 3 or values.mean() <= 0:
                                failures.append(f'{name} {key} face {face} {label}: insufficient valid metrics')
                                continue
                            steps = np.array([abs(values[j] - values[j-1]) for j in range(1, len(valid)) if valid[j] == valid[j-1] + 1])
                            detrended = values - np.polyval(np.polyfit(valid, values, 1), valid)
                            p95 = np.percentile(steps, 95) / values.mean()
                            std = np.std(detrended) / values.mean()
                            print(f'  field {key} face {face} {label}: mean {values.mean():.6f}, step p95 {p95:.2%}, detrended std {std:.2%}, fade frames {fade}')
                            if p95 > .02 or std > .04:
                                failures.append(f'{name} {key} face {face} {label}: field step {p95:.2%}, std {std:.2%}')
                print(f'{name}: frames {len(positions["base"])}/120')
                if len(positions['base']) != 120:
                    failures.append(f'{name}: fewer than 120 frames')
                noise_stats = {}
                for key in ('noise', 'partial', 'full'):
                    valid = [i for i in range(len(positions['base'])) if positions['base'][i] is not None and positions[key][i] is not None]
                    print(f'  {key}: landmark pairs {len(valid)}/120')
                    if len(valid) < 120:
                        failures.append(f'{name} {key}: missing landmark detections')
                    for label, pairs, limit_diff, limit_std in (
                        ('jaw 234-454', ((234,454),), .004, .006),
                        ('jaw 132-361', ((132,361),), .004, .006),
                        ('eyes', ((33,133),(362,263)), .006, .010)):
                        ratios = []
                        for i in valid:
                            def width_at(points):
                                return np.mean([np.linalg.norm(points[a]-points[b]) for a,b in pairs])
                            ratios.append(width_at(positions[key][i]) / width_at(positions['base'][i]))
                        if len(ratios) < 2:
                            failures.append(f'{name} {key} {label}: insufficient detections')
                            continue
                        values = np.array(ratios)
                        steps = np.array([abs(values[j]-values[j-1]) for j in range(1,len(valid)) if valid[j] == valid[j-1]+1])
                        if not len(steps):
                            failures.append(f'{name} {key} {label}: no consecutive detections')
                            continue
                        detrended = values - np.polyval(np.polyfit(valid, values, 1), valid)
                        p95, std = np.percentile(steps,95), np.std(detrended)
                        print(f'    {label}: ratio mean {values.mean():.6f}, step mean {steps.mean():.6f} std {steps.std():.6f} p95 {p95:.6f}, detrended std {std:.6f}')
                        if key == 'noise':
                            noise_stats[label] = (p95, std)
                        else:
                            # Detector variation under a known subpixel resampling sets a practical floor.
                            floor_p95, floor_std = noise_stats[label]
                            allowed_p95, allowed_std = max(limit_diff, 1.5 * floor_p95), max(limit_std, 1.5 * floor_std)
                            if p95 > allowed_p95 or std > allowed_std:
                                failures.append(f'{name} {key} {label}: p95 {p95:.6f}, detrended std {std:.6f} exceed {allowed_p95:.6f}/{allowed_std:.6f}')
                    if key != 'noise':
                        def jitter(which):
                            vals = []
                            for i in range(1,len(positions[which])):
                                before, after = positions[which][i-1:i+1]
                                if before is None or after is None:
                                    continue
                                motion = after-before
                                shift = np.median(motion,axis=0)
                                vals.append(np.sqrt(np.mean((motion[[1,33,133,132,152,263,362,361,454,234]]-shift)**2)))
                            return float(np.percentile(vals,95)) if vals else float('nan')
                        base_jitter, warp_jitter = jitter('base'), jitter(key)
                        print(f'    jitter p95 base {base_jitter:.6f}, warped {warp_jitter:.6f}; outside flicker max {outside_max[key]:.6f}')
                        if not np.isfinite(warp_jitter) or warp_jitter > 1.2 * base_jitter:
                            failures.append(f'{name} {key}: jitter exceeds base +20%')
                        if outside_max[key] != 0:
                            failures.append(f'{name} {key}: outside flicker {outside_max[key]:.6f} is nonzero')
    if writer:
        writer.stdin.close()
        if writer.wait() != 0:
            failures.append('comparison video encoding failed')
    if writer and writer.returncode == 0:
        probe_result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_name,width,height,nb_frames', '-of', 'default=noprint_wrappers=1', str(video)], capture_output=True, text=True)
        print('ffprobe:', probe_result.stdout.strip().replace('\n', ', '))
        if probe_result.returncode != 0:
            failures.append('comparison video ffprobe failed')
    if not worst and fade_worst:
        print('worst frames: no fade-free steps; showing largest fade-affected jaw steps')
        worst = fade_worst
    if worst:
        selected = sorted(worst, key=lambda item: item[0], reverse=True)[:3]
        review = Image.new('RGB', (1280, 720 * len(selected)))
        for i, (score, name, frame_no, image) in enumerate(selected):
            review.paste(Image.fromarray(image), (0, i * 720))
            ImageDraw.Draw(review).text((850, i * 720 + 6), f'change {score:.6f}', fill='white')
        review.save(results_dir / 'a_worst.jpg', quality=90)
    print(f'comparison: {video}; worst frames: {results_dir / "a_worst.jpg"}')
    return failures


def performance_1080():
    rgb = capture('asian_hush_48036.mp4', 4)
    h, w = rgb.shape[:2]
    rgb = cv2.resize(rgb, (round(w * 1080 / min(w, h)), round(h * 1080 / min(w, h))))
    raw = detect(rgb, 4000)
    _, wall_ms, _, gpu_ms, max_move = render(rgb, raw, .7, .5)
    print(f'1080x1920 warp: GPU {gpu_ms:.2f} ms, full render wall {wall_ms:.2f} ms, max move {max_move:.1f} px')
    return [] if gpu_ms <= 2 else [f'1080x1920 warp GPU {gpu_ms:.2f} ms above 2 ms']


if __name__ == '__main__':
    failures = main()
    failures += temporal()
    if '--perf' in sys.argv:
        failures += performance_1080()
    if failures:
        raise AssertionError('; '.join(failures))
