import pickle
import numpy as np
from cake.analysis.regions_teeth import teeth_region, INNER_LIP
from cake.core.recipe import Recipe
from cake.core.registry import registered_passes


def test_b_sections_and_order():
    recipe = Recipe()
    assert recipe.shine.amount == recipe.teeth.amount == 0
    recipe.shine.amount = .8
    recipe.teeth.amount = .8
    restored = Recipe.from_dict(recipe.to_dict())
    assert restored.shine.amount == restored.teeth.amount == .8
    passes = {p.name: p.order for p in registered_passes()}
    assert passes['heal'] < passes['shine'] < passes['retouch'] < passes['teeth'] < passes['grade']
    for section in ('shine', 'teeth'):
        try:
            Recipe.from_dict({'sections': {section: {'amount': 1.1}}})
        except ValueError:
            pass
        else:
            raise AssertionError('out-of-range amount accepted')


def test_b_teeth_polygon_and_worker_import():
    face = np.zeros((478, 2), np.float32)
    angles = np.linspace(0, 2 * np.pi, len(INNER_LIP), endpoint=False)
    face[list(INNER_LIP)] = np.column_stack((32 + 15*np.cos(angles), 32 + 8*np.sin(angles)))
    mask = teeth_region([face], (64, 64))
    assert mask.dtype == np.float32 and mask[32, 32] == 1 and mask[0, 0] == 0
    assert not teeth_region([], (64, 64)).any()
    assert pickle.loads(pickle.dumps(teeth_region)) is teeth_region
