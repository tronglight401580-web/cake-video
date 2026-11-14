from dataclasses import dataclass, field
import moderngl
from ...core.recipe import meta, register_section
from ...core.registry import Pass, register_pass
from ..context import COMMON
from .heal import SKINDOWN, BLUR4

@register_section('shine')
@dataclass
class ShineSection:
    amount: float = field(default=0., metadata=meta('去油光', 0., 0, 1, .01, '人像精修'))

SHINE = COMMON + """
uniform sampler2D src, mask, base, fine;
uniform float amount;
void main() {
    vec3 c = texture(src, uv).rgb;
    vec4 b = texture(base, uv);
    vec3 avg = b.rgb / max(b.a, 0.001);
    vec4 f = texture(fine, uv);
    vec3 local = f.rgb / max(f.a, 0.001);
    float sat = (max(max(c.r,c.g),c.b)-min(min(c.r,c.g),c.b)) / max(max(max(c.r,c.g),c.b),0.001);
    float w = smoothstep(0.005, 0.02, luma(local)-luma(avg)) * smoothstep(0.025, 0.06, luma(c)-luma(avg)) * (1.0-smoothstep(0.12,0.48,sat));
    w *= smoothstep(0.66,0.70,luma(c)) * smoothstep(0.2,0.8,b.a) * texture(mask,uv).r * amount * 0.7;
    o = vec4(mix(c, avg, w), 1.0);
}
"""

@register_pass('shine', 350)
class Shine(Pass):
    reads, writes = ('rgb', 'healed', 'mask'), ('rgb', 'healed')
    def setup(self, gl, width, height):
        self.gl, self.w, self.h = gl, width, height
        self.down, self.vdown = gl.program(SKINDOWN)
        self.blur, self.vblur = gl.program(BLUR4)
        self.program, self.va = gl.program(SHINE)
        self.size = (max(1,width//2), max(1,height//2))
        self.a, self.fa = gl.rt(self.size)
        self.b, self.fb = gl.rt(self.size)
        self.c, self.fc = gl.rt(self.size)
        self.d, self.fd = gl.rt(self.size)
        self.e, self.fe = gl.rt(self.size)
        self.output, self.fo = gl.rt((width,height))
    def enabled(self, recipe, fc):
        return recipe.shine.amount > 0 and fc.textures.get('mask') is not None
    def run(self, fc):
        t = fc.textures
        src = t.get('healed', t['rgb'])
        self.fa.use(); src.use(0); t['mask'].use(1)
        self.gl.uniforms(self.down, src=0, mask=1, src_texel=(.5/self.w,.5/self.h)); self.vdown.render(moderngl.TRIANGLE_STRIP)
        step = max(3., min(self.w,self.h)*.025)
        self.fb.use(); self.a.use(0); self.gl.uniforms(self.blur, src=0, dir=(step/self.size[0],0.)); self.vblur.render(moderngl.TRIANGLE_STRIP)
        self.fc.use(); self.b.use(0); self.gl.uniforms(self.blur, src=0, dir=(0.,step/self.size[1])); self.vblur.render(moderngl.TRIANGLE_STRIP)
        fine_step = max(1., step * .2)
        self.fd.use(); self.a.use(0); self.gl.uniforms(self.blur, src=0, dir=(fine_step/self.size[0],0.)); self.vblur.render(moderngl.TRIANGLE_STRIP)
        self.fe.use(); self.d.use(0); self.gl.uniforms(self.blur, src=0, dir=(0.,fine_step/self.size[1])); self.vblur.render(moderngl.TRIANGLE_STRIP)
        self.fo.use(); src.use(0); t['mask'].use(1); self.c.use(2); self.e.use(3)
        self.gl.uniforms(self.program, src=0, mask=1, base=2, fine=3, amount=fc.recipe.shine.amount); self.va.render(moderngl.TRIANGLE_STRIP)
        t['rgb'] = t['healed'] = self.output
    def release(self):
        for obj in (self.fa,self.fb,self.fc,self.fd,self.fe,self.fo,self.a,self.b,self.c,self.d,self.e,self.output): obj.release()



