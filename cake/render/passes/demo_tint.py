"""Optional example tint applied to the graded texture."""
import moderngl
from ...core.registry import Pass, register_pass
from ..context import COMMON

TINT = COMMON + """
uniform sampler2D src;
uniform float amount;
void main() {
    vec3 c = texture(src, uv).rgb;
    o = vec4(mix(c, c * vec3(1.0, 0.85, 0.8), amount), 1.0);
}
"""

@register_pass('demo_tint', 650)
class DemoTint(Pass):
    reads, writes = ('graded',), ('graded',)

    def setup(self, gl, width, height):
        self.gl = gl
        self.program, self.va = gl.program(TINT)
        self.texture, self.fb = gl.rt((width, height))

    def enabled(self, recipe, frame_ctx):
        return recipe.demo_tint > 0

    def run(self, frame_ctx):
        self.fb.use()
        frame_ctx.textures['graded'].use(0)
        self.gl.uniforms(self.program, src=0, amount=frame_ctx.recipe.demo_tint)
        self.va.render(moderngl.TRIANGLE_STRIP)
        frame_ctx.textures['graded'] = self.texture

    def release(self):
        self.fb.release()
        self.texture.release()
