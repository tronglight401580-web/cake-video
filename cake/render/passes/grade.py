"""Grade rendering stage."""
from ..context import COMMON

GRADE = COMMON + """
uniform sampler2D src;
uniform sampler3D lut;
uniform float lut_size;
uniform sampler3D skin_lut;
uniform float skin_lut_size;
uniform sampler2D skin_mask;
uniform float skin_protect;
uniform float strength;
uniform sampler3D previous_lut;
uniform sampler3D previous_skin_lut;
uniform float previous_lut_size;
uniform float previous_skin_lut_size;
uniform float shot_mix;
void main() {
    vec3 c = clamp(texture(src, uv).rgb, 0.0, 1.0);
    vec3 coord = c * ((lut_size - 1.0) / lut_size) + 0.5 / lut_size;
    vec3 g = texture(lut, coord).rgb;
    vec3 sc = c * ((skin_lut_size - 1.0) / skin_lut_size) + 0.5 / skin_lut_size;
    g = mix(g, texture(skin_lut, sc).rgb, clamp(texture(skin_mask, uv).r * skin_protect, 0.0, 1.0));
    if (shot_mix < 1.0) {
        vec3 pc = c * ((previous_lut_size - 1.0) / previous_lut_size) + 0.5 / previous_lut_size;
        vec3 ps = c * ((previous_skin_lut_size - 1.0) / previous_skin_lut_size) + 0.5 / previous_skin_lut_size;
        vec3 pg = mix(texture(previous_lut, pc).rgb, texture(previous_skin_lut, ps).rgb,
                      clamp(texture(skin_mask, uv).r * skin_protect, 0.0, 1.0));
        g = mix(pg, g, shot_mix);
    }
    o = vec4(mix(c, g, strength), 1.0);
}
"""

import moderngl
import numpy as np
from ...core.registry import Pass, register_pass


@register_pass('grade', 500)
class Grade(Pass):
    reads, writes = ('rgb', 'retouched', 'skin'), ('graded',)

    def setup(self, gl, width, height):
        self.gl = gl
        self.program, self.va = gl.program(GRADE)
        self.graded, self.fb = gl.rt((width, height))
        self.zero_skin = gl.gl.texture((1, 1), 1, data=bytes(1))
        self.lut = self.skin_lut = None
        self.shot_luts = []

    def set_style(self, style):
        from ...cube import identity
        from ...color.styles import Style
        for pair in self.shot_luts:
            for tex, _ in pair:
                tex.release()
        self.shot_luts = []
        for shot in style.shots or []:
            item = Style(name='', lut=shot['lut'], skin_lut=shot.get('skin_lut', ''))
            pair = []
            for arr in (item.load_lut(), item.load_skin_lut() if item.skin_lut else identity(2)):
                n = arr.shape[0]
                tex = self.gl.gl.texture3d((n, n, n), 3, data=np.ascontiguousarray(arr, 'f4').tobytes(), dtype='f4')
                tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
                tex.repeat_x = tex.repeat_y = tex.repeat_z = False
                pair.append((tex, float(n)))
            self.shot_luts.append(pair)
        lut = style.load_lut()
        n = lut.shape[0]
        if self.lut is not None:
            self.lut.release()
        self.lut = self.gl.gl.texture3d((n, n, n), 3,
                                         data=np.ascontiguousarray(lut, 'f4').tobytes(), dtype='f4')
        self.lut.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.lut.repeat_x = self.lut.repeat_y = self.lut.repeat_z = False
        self.lut_size = float(n)
        sl = style.load_skin_lut() if style.skin_lut else identity(2).astype('f4')
        sn = sl.shape[0]
        if self.skin_lut is not None:
            self.skin_lut.release()
        self.skin_lut = self.gl.gl.texture3d((sn, sn, sn), 3,
                                              data=np.ascontiguousarray(sl, 'f4').tobytes(), dtype='f4')
        self.skin_lut.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.skin_lut.repeat_x = self.skin_lut.repeat_y = self.skin_lut.repeat_z = False
        self.skin_lut_size = float(sn)

    def run(self, fc):
        u, t, st = fc.uniforms, fc.textures, fc.style
        self.fb.use()
        t.get('retouched', t['rgb']).use(0)
        lut, skin, lut_size, skin_size = self.lut, self.skin_lut, self.lut_size, self.skin_lut_size
        previous, previous_skin, prev_size, prev_skin_size = lut, skin, lut_size, skin_size
        shot_mix = 1.0
        if self.shot_luts:
            index = next((i for i, shot in enumerate(st.shots) if shot['start'] <= fc.frame_index < shot['end']), None)
            if index is not None:
                (lut, lut_size), (skin, skin_size) = self.shot_luts[index]
                if index and fc.frame_index < st.shots[index]['start'] + 8:
                    (previous, prev_size), (previous_skin, prev_skin_size) = self.shot_luts[index - 1]
                    shot_mix = (fc.frame_index - st.shots[index]['start'] + 1) / 8.0
        lut.use(1); skin.use(2)
        previous.use(4); previous_skin.use(5)
        t.get('skin', self.zero_skin).use(3)
        self.gl.uniforms(self.program, src=0, lut=1, lut_size=lut_size, skin_lut=2,
                         skin_lut_size=skin_size, skin_mask=3, previous_lut=4, previous_skin_lut=5,
                         previous_lut_size=prev_size, previous_skin_lut_size=prev_skin_size, shot_mix=shot_mix,
                         skin_protect=st.skin_protect * u['skin_protect_scale'] if st.skin_lut else 0.0,
                         strength=min(1.0, st.lut_strength * u['strength']))
        self.va.render(moderngl.TRIANGLE_STRIP)
        t['graded'] = self.graded

    def release(self):
        for pair in self.shot_luts:
            for tex, _ in pair:
                tex.release()
        for obj in (self.lut, self.skin_lut, self.zero_skin, self.fb, self.graded, self.va, self.program):
            if obj is not None:
                obj.release()
