"""Geometry and GPU smoke tests for the optional reshape pass."""
from types import SimpleNamespace

import numpy as np

from cake.core.recipe import Recipe
from cake.render.context import RenderContext
from cake.render.frame import FrameContext
from cake.render.passes.warp import JAW, Warp, area_range, controls, displacement


def sample_points():
    points = np.zeros((478, 2), np.float32)
    points[:] = (64, 64)
    points[168] = (64, 42)
    points[152] = (64, 105)
    points[234] = (28, 70)
    points[454] = (100, 70)
    points[1] = (64, 62)
    for k, index in enumerate(JAW):
        angle = np.pi * (k / (len(JAW) - 1))
        points[index] = (64 - 36 * np.cos(angle), 70 + 35 * np.sin(angle))
    points[234], points[454] = (28, 70), (100, 70)
    for indices, cx in (((33, 160, 158, 133, 153, 144), 48),
                        ((362, 385, 387, 263, 373, 380), 80)):
        for k, index in enumerate(indices):
            points[index] = (cx - 9 * np.cos(k * np.pi / 3), 57 + 3 * np.sin(k * np.pi / 3))
    return points


def test_recipe_and_disabled_cost():
    recipe = Recipe()
    assert recipe.reshape.slim == recipe.reshape.eyes == 0
    recipe.reshape.slim = .7
    assert Recipe.from_dict(recipe.to_dict()).reshape.slim == .7
    gl = RenderContext(128, 128)
    stage = Warp()
    try:
        stage.setup(gl, 128, 128)
        assert not stage.enabled(Recipe(), None)
        assert stage.field is None and not stage.targets
    finally:
        stage.release()
        gl.gl.release()


def test_extreme_points_stay_monotonic():
    rng = np.random.default_rng(7)
    for _ in range(40):
        points = sample_points()
        points[list(JAW)] += rng.normal(0, 20, (len(JAW), 2))
        jaw, eyes = controls(points, 1., 1., 1.)
        grid = np.mgrid[15:114:3, 15:114:3].transpose(1, 2, 0).astype(np.float32)
        field = displacement(grid, jaw, eyes)
        minimum, maximum = area_range(field, 3.)
        assert minimum >= .8 and maximum <= 1.25, (minimum, maximum)
        mapped = grid + field
        dx = mapped[1:, :-1] - mapped[:-1, :-1]
        dy = mapped[:-1, 1:] - mapped[:-1, :-1]
        determinant = dx[..., 0] * dy[..., 1] - dx[..., 1] * dy[..., 0]
        assert determinant.min() > 0


def test_contour_field_has_no_point_scale_ripples():
    points = sample_points()
    jaw, eyes = controls(points, 1., 0., 1.)
    # Sample along each side of a smooth jaw at 1 px intervals.  The maximum
    # second difference of inverse displacement must stay below 0.02 px/px².
    for side in (JAW[:11], JAW[10:]):
        curve = points[list(side)]
        distances = np.r_[0., np.cumsum(np.linalg.norm(np.diff(curve, axis=0), axis=1))]
        samples = np.arange(0, distances[-1], 1.)
        path = np.stack([np.interp(samples, distances, curve[:, axis]) for axis in (0, 1)], -1)
        field = displacement(path[None, ...], jaw, eyes)[0]
        second = np.diff(field, n=2, axis=0)
        assert np.linalg.norm(second, axis=1).max() < .02


def test_face_local_geometry_suppresses_width_breathing_and_resets():
    stage = Warp()
    stage.tracks = []
    stage.last_face = None
    original = sample_points()
    first = SimpleNamespace(landmarks=[original], reset=False)
    stage._update_tracks(first)
    wider = original.copy()
    centre = (original[234] + original[454]) * .5
    wider[:, 0] = centre[0] + (wider[:, 0] - centre[0]) * 1.08
    stage._update_tracks(SimpleNamespace(landmarks=[wider], reset=False))
    stable_width = np.linalg.norm(stage.tracks[0]['points'][454] - stage.tracks[0]['points'][234])
    assert stable_width < np.linalg.norm(wider[454] - wider[234]) - 3
    stage._update_tracks(SimpleNamespace(landmarks=[wider], reset=True))
    reset_width = np.linalg.norm(stage.tracks[0]['points'][454] - stage.tracks[0]['points'][234])
    assert abs(reset_width - np.linalg.norm(wider[454] - wider[234])) < 1e-4


def test_gpu_warps_rgb_and_region_together():
    gl = RenderContext(128, 128)
    stage = Warp()
    stage.setup(gl, 128, 128)
    source, fb = gl.rt((128, 128))
    pattern = np.zeros((128, 128, 4), np.float16)
    pattern[:, :, 0] = np.arange(128)[None, :] / 128
    source.write(pattern.tobytes())
    recipe = Recipe(sections={'reshape': {'slim': 1., 'eyes': 1.}})
    face = SimpleNamespace(landmarks=[sample_points()], reset=False)
    fc = FrameContext(recipe, 0, 128, 128, face=face,
                      textures={'rgb': source, 'region:test': (source, 0)})
    try:
        stage.run(fc)
        assert stage.field.size == (64, 64)
        assert fc.textures['rgb'] is fc.textures['region:test'][0]
        output = np.frombuffer(fc.textures['rgb'].read(), np.float16).reshape(128, 128, 4)
        assert np.max(np.abs(output[:, :, 0] - pattern[:, :, 0])) > .001
    finally:
        stage.release()
        fb.release(); source.release(); gl.gl.release()
