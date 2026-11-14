"""Pass registration and shared frame state."""
from dataclasses import dataclass, field
from typing import Any

@dataclass
class FrameContext:
    recipe: Any
    frame_index: int
    width: int
    height: int
    face: Any = None
    textures: dict = field(default_factory=dict)

class Pass:
    name = ''
    order = 0
    reads = ()
    writes = ()
    def enabled(self, recipe, frame_ctx):
        return True
    def setup(self, gl, width, height):
        pass
    def run(self, frame_ctx):
        raise NotImplementedError
    def release(self):
        pass

_registry = {}

def register_pass(name, order):
    def decorate(cls):
        if name in _registry:
            raise ValueError(f'duplicate pass name: {name}')
        if not issubclass(cls, Pass):
            raise TypeError('registered pass must inherit Pass')
        cls.name, cls.order = name, order
        _registry[name] = cls
        return cls
    return decorate

def registered_passes():
    return tuple(sorted(_registry.values(), key=lambda cls: (cls.order, cls.name)))
