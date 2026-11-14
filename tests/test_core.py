import tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from cake.cube import identity, read_cube, write_cube
from cake.looks import soft_clip, s_curve
from cake.refcolor import rgb_to_lab, lab_to_rgb
from cake.core.recipe import Recipe
from cake.core.registry import Pass, register_pass, registered_passes, _registry
from cake.core.bus import EventBus

def test_cube_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'identity.cube'
        expected = identity(7)
        write_cube(path, expected)
        np.testing.assert_allclose(read_cube(path), expected, atol=1e-6)

def test_curves_monotonic():
    x = np.linspace(0, 1, 1000)
    assert np.all(np.diff(soft_clip(x)) >= 0)
    assert np.all(np.diff(s_curve(x, 1.3)) >= 0)

def test_lab_roundtrip():
    rgb = np.random.default_rng(42).random((100, 3))
    np.testing.assert_allclose(lab_to_rgb(rgb_to_lab(rgb)), rgb, atol=1e-10)

def test_recipe():
    recipe = Recipe.from_legacy({'style': 'ccd', 'retouch': .7, 'skin_protect': .4,
                                 'opts': {'under': .8, 'spots': .2, 'keep_moles': False}})
    assert recipe == Recipe.from_dict(recipe.to_dict())
    assert recipe.retouch.eyes == .8 and recipe.skin_protect_scale == .5

def test_registry():
    try:
        @register_pass('unit_later', 20)
        class Later(Pass): pass
        @register_pass('unit_earlier', 10)
        class Earlier(Pass): pass
        assert registered_passes().index(Earlier) < registered_passes().index(Later)
        try:
            register_pass('unit_later', 40)(Later)
        except ValueError:
            pass
        else:
            raise AssertionError('duplicate accepted')
    finally:
        _registry.pop('unit_later', None)
        _registry.pop('unit_earlier', None)

def test_bus_threads():
    bus = EventBus()
    received = []
    unsubscribe = bus.subscribe('progress', lambda n: received.append(n))
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda n: bus.publish('progress', n=n), range(1000)))
    unsubscribe()
    bus.publish('progress', n=1001)
    assert sorted(received) == list(range(1000))
