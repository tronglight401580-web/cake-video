import numpy as np
import cv2
import pickle
from cake.analysis import regions
from cake.analysis.smoothing import OneEuro, FaceTracker
from cake.render.passes.regions import pack_regions


def test_region_registry_computes_and_rejects_duplicates():
    name = "test_mouth"
    try:
        @regions.register_region(name)
        def mouth(faces, shape):
            out = np.zeros(shape, np.float32)
            for face in faces:
                x, y = face[0].astype(int)
                out[y, x] = 1
            return out
        face = np.zeros((478, 2), np.float32)
        face[0] = (3, 2)
        names, stack = regions.compute_regions([face], (6, 7))
        assert names[-1] == name and stack[2, 3, -1] == 255
        face[0] = (4, 2)
        _, moved = regions.compute_regions([face], (6, 7))
        assert moved[2, 4, -1] == 255 and moved[2, 3, -1] == 0
        try:
            regions.register_region(name)(mouth)
        except ValueError:
            pass
        else:
            raise AssertionError("duplicate accepted")
    finally:
        regions._regions.pop(name, None)


def test_five_regions_pack_into_two_textures_and_zero_allocates_none():
    from cake.analysis.analyzer import FaceInputs
    from cake.render.renderer import Renderer
    stack = np.zeros((5, 7, 5), np.uint8)
    for i in range(5):
        stack[:, :, i] = i + 1
    planes = pack_regions(stack)
    assert len(planes) == 2
    assert planes[0][0, 0].tolist() == [1, 2, 3, 4]
    assert planes[1][0, 0].tolist() == [5, 0, 0, 0]
    assert pack_regions(None) == []
    renderer = Renderer(7, 5, False)
    try:
        stage = renderer._by_name['regions']
        assert not stage.source and not stage.targets
        seg = np.zeros((5, 7, 2), np.uint8)
        layers = np.zeros((5, 7, 4), np.uint8)
        renderer.set_face(FaceInputs(seg, seg, 0, layers, 0, [], True,
                                     region_names=tuple('abcde'), regions=stack))
        assert len(stage.source) == len(stage.targets) == 2
        assert len(renderer._region_slots) == 5
        assert renderer._region_slots['region:e'][1] == 0
        old_texture = renderer._region_slots['region:a'][0]
        blank = np.zeros_like(stack)
        renderer.set_face(FaceInputs(seg, seg, 0, layers, 0, [], False,
                                     region_names=tuple('abcde'), regions=blank))
        texture = renderer._region_slots['region:a'][0]
        assert texture is not old_texture
        value = np.frombuffer(texture.read(), np.float16).reshape(5, 7, 4)[2, 3, 0]
        assert abs(float(value) - (1 - renderer.mask_alpha) / 255) < 0.001
        renderer.set_face(FaceInputs(seg, seg, 0, layers, 0, [], True,
                                     region_names=tuple('abcde'), regions=blank))
        texture = renderer._region_slots['region:a'][0]
        assert float(np.frombuffer(texture.read(), np.float16).max()) == 0
        renderer.set_face(FaceInputs(seg, seg, 0, layers, 0, [], True))
        assert not stage.source and not stage.targets and not renderer._region_slots
    finally:
        renderer.release()


def test_region_worker_arguments_are_picklable():
    # Worker arguments use the same module-level function reference mechanism.
    definitions = (('picklable', regions.compute_regions),)
    assert pickle.loads(pickle.dumps(definitions))[0][1] is regions.compute_regions


def test_one_euro_reduces_noisy_track_and_tracker_resets():
    rng = np.random.default_rng(42)
    noisy = 50 + rng.normal(0, 2, 120)
    filt = OneEuro(min_cutoff=1.0, beta=0.0)
    smooth = np.array([filt(np.array([x], np.float32), 1 / 30)[0] for x in noisy])
    assert smooth[20:].std() < noisy[20:].std() * 0.6
    tracker = FaceTracker()
    face = np.zeros((478, 2), np.float32)
    face[:, 0] = np.linspace(40, 60, 478)
    tracker.update([face], 1 / 30)
    face[:, 0] += 4
    assert tracker.update([face], 1 / 30)[0][0, 0] < 44
    assert tracker.update([face], 1 / 30, reset=True)[0][0, 0] == 44
    assert tracker.update([], 1 / 30) == [] and not tracker.tracks


def test_mouth_region_sample_reaches_face_pass_and_tracks_landmarks():
    from cake.analysis.analyzer import FaceInputs, run_models
    from cake.analysis.frames import analysis_size
    from cake.analysis.layers import LIPS
    from cake.core.registry import Pass, register_pass, _registry
    from cake.render.renderer import Renderer
    from pathlib import Path

    name = 'test_mouth'
    observations = []
    try:
        @regions.register_region(name)
        def mouth(faces, shape):
            plane = np.zeros(shape, np.uint8)
            for face in faces:
                cv2.fillConvexPoly(plane, cv2.convexHull(face[LIPS].astype(np.int32)), 255)
            return plane.astype(np.float32) / 255

        @register_pass('test_region_reader', 220)
        class Reader(Pass):
            stage = 'face'
            def setup(self, gl, width, height):
                pass
            def run(self, fc):
                texture, channel = fc.region(name)
                data = np.frombuffer(texture.read(), np.float16).reshape(texture.height, texture.width, 4)
                ys, xs = np.nonzero(data[:, :, channel] > 0.5)
                observations.append(np.array([xs.mean(), ys.mean()]))

        cap = cv2.VideoCapture(str(Path('samples/asian_hush_48036.mp4')))
        try:
            frames = []
            for index in (0, 15):
                cap.set(cv2.CAP_PROP_POS_FRAMES, index)
                ok, bgr = cap.read()
                assert ok
                frames.append(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        finally:
            cap.release()
        h, w = frames[0].shape[:2]
        aw, ah = analysis_size(w, h)
        seg = np.zeros((ah, aw, 2), np.uint8)
        renderer = Renderer(w, h, False)
        try:
            for index, rgb in zip((0, 15), frames):
                small = cv2.resize(rgb, (aw, ah), interpolation=cv2.INTER_AREA)
                raw = run_models(small, False, ts_ms=index * 40)
                assert raw.landmarks and raw.regions is not None
                renderer.set_face(FaceInputs(seg, seg, 0, raw.layers, raw.face_h, raw.boxes,
                                             index == 0, raw.landmarks, raw.region_names,
                                             raw.regions))
                expected = raw.landmarks[0][LIPS].mean(0)
                assert np.linalg.norm(observations[-1] - expected) < 6
                assert renderer._face.landmarks[0].shape == (478, 2)
                assert np.all((renderer._face.landmarks_norm[0] >= 0) &
                              (renderer._face.landmarks_norm[0] <= 1))
            assert len(observations) == 2
            assert np.linalg.norm(observations[1] - observations[0]) > 0.5
        finally:
            renderer.release()
    finally:
        regions._regions.pop(name, None)
        _registry.pop('test_region_reader', None)
