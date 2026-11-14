"""Shared OpenGL primitives and readback buffers for render passes."""
import moderngl
import numpy as np


class RenderContext:
    def __init__(self, width, height):
        self.width, self.height = width, height
        self.gl = moderngl.create_standalone_context(require=330)
        self.quad = self.gl.buffer(np.array([-1, -1, 1, -1, -1, 1, 1, 1], dtype="f4").tobytes())
        self.programs = {}

    def program(self, frag):
        if frag not in self.programs:
            p = self.gl.program(vertex_shader=VERT, fragment_shader=frag)
            self.programs[frag] = (p, self.gl.vertex_array(p, [(self.quad, "2f", "in_pos")]))
        return self.programs[frag]

    def rt(self, size):
        tex = self.gl.texture(size, 4, dtype="f2")
        tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        tex.repeat_x = tex.repeat_y = False
        return tex, self.gl.framebuffer(color_attachments=[tex])

    @staticmethod
    def uniforms(program, **values):
        for name, value in values.items():
            if name in program:
                program[name].value = value


class PBOReadback:
    def __init__(self, gl, size):
        self.gl, self.size = gl, size
        self.buffers = None
        self.index = 0
        self.pending = None

    def next(self, planes):
        if self.buffers is None:
            self.buffers = [self.gl.buffer(reserve=self.size), self.gl.buffer(reserve=self.size)]
        current = self.buffers[self.index]
        offset = 0
        for tex, fb, components in planes:
            fb.read_into(current, components=components, alignment=1, write_offset=offset)
            offset += tex.width * tex.height * components
        previous, self.pending = self.pending, current
        self.index ^= 1
        return previous.read() if previous is not None else None

    def flush(self):
        previous, self.pending = self.pending, None
        return previous.read() if previous is not None else None


VERT = """
#version 330
in vec2 in_pos;
out vec2 uv;
void main() { uv = in_pos * 0.5 + 0.5; gl_Position = vec4(in_pos, 0.0, 1.0); }
"""

COMMON = """
#version 330
in vec2 uv;
out vec4 o;
const vec3 W709 = vec3(0.2126, 0.7152, 0.0722);
float luma(vec3 c) { return dot(c, W709); }
float hash12(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}
"""
