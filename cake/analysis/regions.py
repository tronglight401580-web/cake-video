"""Registry for landmark-derived, analysis-resolution masks."""
import numpy as np

_regions = {}

def register_region(name):
    def decorate(fn):
        if not isinstance(name, str) or not name:
            raise ValueError("region name must be nonempty")
        if name in _regions:
            raise ValueError(f"duplicate region name: {name}")
        _regions[name] = fn
        return fn
    return decorate

def registered_regions():
    return tuple(_regions.items())

def compute_regions(faces, shape, definitions=None):
    """Return names and an H x W x N uint8 stack, or None when empty."""
    regions = registered_regions() if definitions is None else definitions
    if not regions:
        return (), None
    planes = []
    for name, fn in regions:
        plane = np.asarray(fn(faces, shape))
        if plane.shape != tuple(shape) or plane.dtype != np.float32:
            raise ValueError(f"region {name} must return float32 with shape {shape}")
        if not np.isfinite(plane).all() or np.any((plane < 0) | (plane > 1)):
            raise ValueError(f"region {name} must be finite and between 0 and 1")
        planes.append(np.rint(plane * 255).astype(np.uint8))
    return tuple(name for name, _ in regions), np.stack(planes, axis=-1)
