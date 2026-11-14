"""Per-frame texture slots and parameter view passed to registered stages."""
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
    uniforms: dict = field(default_factory=dict)
    frame: Any = None
    yuv: bool = False
    pipelined: bool = False
    result: Any = None

    @property
    def style(self):
        return self.uniforms.get('style')
