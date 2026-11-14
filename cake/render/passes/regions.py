"""Upload and temporally smooth landmark regions in RGBA groups."""
import numpy as np
import moderngl

from ...core.registry import Pass, register_pass

REGION_EMA = """#version 330
in vec2 uv;
out vec4 o;
uniform sampler2D current_region;
uniform sampler2D previous_region;
uniform float alpha;
void main() {
    vec4 now = texture(current_region, uv);
    o = alpha >= 0.999 ? now : mix(texture(previous_region, uv), now, alpha);
}
"""


def pack_regions(stack):
    """Return contiguous RGBA planes; absent regions require no texture allocation."""
    if stack is None or stack.shape[2] == 0:
        return []
    h, w, n = stack.shape
    if stack.dtype != np.uint8:
        raise ValueError('region stack must be uint8')
    planes = []
    for start in range(0, n, 4):
        plane = np.zeros((h, w, 4), np.uint8)
        plane[:, :, :min(4, n-start)] = stack[:, :, start:start+4]
        planes.append(plane)
    return planes


@register_pass('regions', 210)
class Regions(Pass):
    stage = 'face'
    reads, writes = ('regions',), ('region:*',)

    def setup(self, gl, width, height):
        self.gl = gl
        self.program, self.va = gl.program(REGION_EMA)
        self.source = []
        self.targets = []
        self.output = []
        self.size = None

    def _clear(self):
        for texture in self.source:
            texture.release()
        for pair in self.targets:
            for texture, framebuffer in pair:
                framebuffer.release()
                texture.release()
        self.source, self.targets, self.output = [], [], []
        self.size = None

    def _allocate(self, size, count):
        self._clear()
        self.size = size
        for _ in range(count):
            source = self.gl.gl.texture(size, 4, dtype='f1')
            source.filter = (moderngl.LINEAR, moderngl.LINEAR)
            source.repeat_x = source.repeat_y = False
            pair = []
            for _ in range(2):
                texture = self.gl.gl.texture(size, 4, dtype='f2')
                texture.filter = (moderngl.LINEAR, moderngl.LINEAR)
                texture.repeat_x = texture.repeat_y = False
                pair.append((texture, self.gl.gl.framebuffer(color_attachments=[texture])))
            self.source.append(source)
            self.targets.append(pair)

    def run(self, frame_ctx):
        face = frame_ctx.face
        names = face.region_names or ()
        planes = pack_regions(face.regions)
        if len(names) != (0 if face.regions is None else face.regions.shape[2]):
            raise ValueError('region names and stack disagree')
        if not planes:
            self._clear()
            return
        size = (planes[0].shape[1], planes[0].shape[0])
        if self.size != size or len(self.source) != len(planes):
            self._allocate(size, len(planes))
        alpha = 1.0 if face.reset or not self.output else frame_ctx.uniforms['mask_alpha']
        next_output = []
        for i, plane in enumerate(planes):
            self.source[i].write(np.ascontiguousarray(plane).tobytes())
            pair = self.targets[i]
            previous = self.output[i] if self.output else pair[0][0]
            dest = pair[1] if previous is pair[0][0] else pair[0]
            dest[1].use()
            self.source[i].use(0)
            previous.use(1)
            self.gl.uniforms(self.program, current_region=0, previous_region=1, alpha=alpha)
            self.va.render(moderngl.TRIANGLE_STRIP)
            next_output.append(dest[0])
        self.output = next_output
        for i, name in enumerate(names):
            frame_ctx.textures['region:' + name] = (self.output[i // 4], i % 4)

    def release(self):
        self._clear()
