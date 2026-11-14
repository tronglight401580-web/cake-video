"""Compatibility names for shader sources owned by render stages."""
from .render.context import VERT, COMMON
from .render.passes.input import YUV2RGB
from .render.passes.maskbuild import MASKBUILD
from .render.passes.heal import HEAL, SKINDOWN, BLUR4
from .render.passes.retouch import RETOUCH
from .render.passes.grade import GRADE
from .render.passes.bloom import BRIGHT, BLUR
from .render.passes.finish import FINISH
from .render.passes.output import TOYUV
