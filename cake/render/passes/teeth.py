from dataclasses import dataclass, field
import moderngl
from ...core.recipe import meta, register_section
from ...core.registry import Pass, register_pass
from ..context import COMMON

@register_section('teeth')
@dataclass
class TeethSection:
    amount: float = field(default=0., metadata=meta('牙齿美白', 0., 0, 1, .01, '人像精修'))

MEDIAN = COMMON + """
uniform sampler2D src, region;
uniform int channel;
uniform vec4 bounds;
void main() {
    int bins[64];
    for (int i=0; i<64; ++i) bins[i]=0;
    int count=0;
    for (int y=0; y<32; ++y) for (int x=0; x<32; ++x) {
        vec2 p = mix(bounds.xy, bounds.zw, (vec2(x,y)+0.5)/32.0);
        if (texture(region, p)[channel] > 0.5) {
            int bin = clamp(int(luma(texture(src,p).rgb)*64.0),0,63);
            bins[bin]++; count++;
        }
    }
    int sum=0; float median=0.0;
    for (int i=0; i<64; ++i) { sum+=bins[i]; if (sum*2>=count && count>0) { median=(float(i)+0.5)/64.0; break; } }
    o=vec4(median,0.0,0.0,1.0);
}
"""

TEETH = COMMON + """
uniform sampler2D src, region, median_tex;
uniform int channel;
uniform float amount;
void main() {
    vec3 c = texture(src, uv).rgb;
    float m = texture(region, uv)[channel];
    float hi = max(max(c.r,c.g),c.b), lo = min(min(c.r,c.g),c.b);
    float sat = (hi-lo)/max(hi,0.001);
    float median = texelFetch(median_tex, ivec2(0), 0).r;
    float bright = smoothstep(median - 0.05, median + 0.08, luma(c));
    float nonred = 1.0-smoothstep(0.035,0.14,c.r-max(c.g,c.b));
    float w = m * bright * (1.0-smoothstep(0.32,0.65,sat)) * nonred * amount;
    vec3 lin = pow(max(c,0.0),vec3(2.2));
    float yellow = max(0.0, 0.5*(lin.r+lin.g)-lin.b);
    lin.b += yellow * 0.65 * w;
    lin += vec3(0.035*w);
    o = vec4(clamp(pow(max(lin,0.0),vec3(1.0/2.2)),0.0,1.0),1.0);
}
"""

@register_pass('teeth', 450)
class Teeth(Pass):
    reads, writes = ('rgb','retouched','region:teeth'), ('retouched',)
    def setup(self, gl, width, height):
        self.gl = gl
        self.program, self.va = gl.program(TEETH)
        self.median_program, self.median_va = gl.program(MEDIAN)
        self.median, self.median_fb = gl.rt((1,1))
        self.output, self.fb = gl.rt((width,height))
    def enabled(self, recipe, fc):
        return recipe.teeth.amount > 0 and 'region:teeth' in fc.textures
    def run(self, fc):
        t = fc.textures
        region, channel = fc.region('teeth')
        src = t.get('retouched',t['rgb'])
        self.median_fb.use(); src.use(0); region.use(1)
        bounds = (0., 0., 1., 1.)
        if fc.face is not None and fc.face.landmarks_norm:
            import numpy as np
            indices = [78,191,80,81,82,13,312,311,310,415,308,324,318,402,317,14,87,178,88,95]
            points = np.concatenate([p[indices] for p in fc.face.landmarks_norm])
            lo, hi = points.min(axis=0), points.max(axis=0)
            bounds = (float(lo[0]), float(lo[1]), float(hi[0]), float(hi[1]))
        self.gl.uniforms(self.median_program, src=0, region=1, channel=channel, bounds=bounds)
        self.median_va.render(moderngl.TRIANGLE_STRIP)
        self.fb.use(); src.use(0); region.use(1); self.median.use(2)
        self.gl.uniforms(self.program, src=0, region=1, median_tex=2, channel=channel, amount=fc.recipe.teeth.amount)
        self.va.render(moderngl.TRIANGLE_STRIP)
        t['retouched'] = self.output
    def release(self):
        self.fb.release(); self.output.release(); self.median_fb.release(); self.median.release()
