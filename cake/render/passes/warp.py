"""Small, tracked inverse-map face reshaping shared by colour and spatial masks."""
from dataclasses import dataclass, field

import moderngl
import numpy as np

from ...core.recipe import meta, register_section
from ...core.registry import Pass, register_pass
from ..context import COMMON

JAW = (234, 93, 132, 58, 172, 136, 150, 149, 176, 148,
       152, 377, 400, 378, 379, 365, 397, 288, 361, 323, 454)
LEFT_EYE = (33, 160, 158, 133, 153, 144)
RIGHT_EYE = (362, 385, 387, 263, 373, 380)
MAX_JAW = 42
MAX_EYES = 4


@register_section('reshape')
@dataclass
class ReshapeSection:
    slim: float = field(default=0., metadata=meta('瘦脸', 0., 0, 1, .01, '人像精修'))
    eyes: float = field(default=0., metadata=meta('大眼', 0., 0, 1, .01, '人像精修'))


FIELD = COMMON + """
uniform vec2 full_size;
uniform vec4 active_bounds;
uniform int jaw_count;
uniform vec4 jaw[42];      // output pixel x/y, inward displacement x/y
uniform vec2 jaw_shape[42]; // radius, lower-face transition centre y
uniform int eye_count;
uniform vec4 eye[4];       // centre x/y, radius, strength
void main() {
    vec2 p = uv * full_size;
    if (p.x < active_bounds.x || p.y < active_bounds.y ||
        p.x > active_bounds.z || p.y > active_bounds.w) {
        o = vec4(0.0, 0.0, 0.0, 1.0);
        return;
    }
    vec2 weighted = vec2(0.0);
    float total = 0.0;
    for (int i = 0; i < jaw_count; ++i) {
        vec2 q = (p - jaw[i].xy) / jaw_shape[i].x;
        float z = dot(q, q);
        if (z < 1.0) {
            float weight = (1.0 - z) * (1.0 - z) *
                smoothstep(jaw_shape[i].y - jaw_shape[i].x * 0.25,
                           jaw_shape[i].y + jaw_shape[i].x * 0.25, p.y);
            weighted += jaw[i].zw * weight;
            total += weight;
        }
    }
    // Shepard interpolation removes the peaks at individual landmarks.  The
    // compact envelope restores exact zero displacement beyond their radii.
    vec2 delta = -weighted / max(1.0 + total, 1e-6);
    for (int i = 0; i < eye_count; ++i) {
        vec2 q = (p - eye[i].xy) / eye[i].z;
        float z = dot(q, q);
        if (z < 1.0) {
            float weight = (1.0 - z) * (1.0 - z);
            delta -= (p - eye[i].xy) * vec2(1.0, 0.25) * eye[i].w * weight;
        }
    }
    o = vec4(delta / full_size, 0.0, 1.0);
}
"""

APPLY = COMMON + """
uniform sampler2D src;
uniform sampler2D displacement;
void main() {
    vec2 d = texture(displacement, uv).rg;
    o = texture(src, clamp(uv + d, vec2(0.0), vec2(1.0)));
}
"""

BLUR = COMMON + """
uniform sampler2D src;
uniform vec2 step_uv;
void main() {
    o = texture(src, uv) * 0.375;
    o += (texture(src, uv + step_uv) + texture(src, uv - step_uv)) * 0.25;
    o += (texture(src, uv + 2.0 * step_uv) + texture(src, uv - 2.0 * step_uv)) * 0.0625;
}
"""

TEMPORAL = COMMON + """
uniform sampler2D current_field;
uniform sampler2D previous_field;
uniform vec2 shift_uv;
uniform float alpha;
void main() {
    if (alpha >= 1.0) {
        o = vec4(texture(current_field, uv).rg, 0.0, 1.0);
        return;
    }
    vec2 previous_uv = uv - shift_uv;
    vec2 old_field = vec2(0.0);
    if (all(greaterThanEqual(previous_uv, vec2(0.0))) &&
        all(lessThanEqual(previous_uv, vec2(1.0)))) {
        old_field = texture(previous_field, previous_uv).rg;
    }
    o = vec4(mix(old_field, texture(current_field, uv).rg, alpha), 0.0, 1.0);
}
"""


def displacement(grid, jaw, eyes):
    """CPU counterpart of FIELD, in pixels, for the area and smoothness guards."""
    weighted = np.zeros_like(grid, dtype=np.float32)
    total = np.zeros(grid.shape[:2], np.float32)
    for x, y, dx, dy, radius, gate_y in jaw:
        q = (grid - (x, y)) / radius
        z = np.sum(q * q, axis=-1)
        t = np.clip((grid[..., 1] - (gate_y - radius * .25)) / (radius * .5), 0, 1)
        weight = np.maximum(1 - z, 0)**2 * t * t * (3 - 2 * t)
        weighted += weight[..., None] * (dx, dy)
        total += weight
    result = -weighted / (1 + total[..., None])
    for x, y, radius, strength in eyes:
        diff = grid - (x, y)
        z = np.sum(diff * diff, axis=-1) / radius**2
        result -= diff * (strength * np.maximum(1 - z, 0)**2)[..., None] * (1., .25)
    return result


def area_range(field, step):
    """det(I + grad D), sampled over grid cells."""
    ddx = (field[:, 2:] - field[:, :-2]) / (2 * step)
    ddy = (field[2:] - field[:-2]) / (2 * step)
    a, b = ddx[1:-1, :, 0], ddy[:, 1:-1, 0]
    c, d = ddx[1:-1, :, 1], ddy[:, 1:-1, 1]
    det = (1 + a) * (1 + d) - b * c
    return float(det.min()), float(det.max())


def guard_controls(jaw, eyes):
    """Globally reduce both effects until sampled local area is in [0.8, 1.25]."""
    extents = [(x-r, y-r, x+r, y+r) for x, y, _, _, r, _ in jaw]
    extents += [(x-r, y-r, x+r, y+r) for x, y, r, _ in eyes]
    if not extents:
        return jaw, eyes
    # A 2 px grid resolves the narrowest eye kernel and includes the envelope.
    step = 2.
    lo = np.min(np.array(extents)[:, :2], axis=0) - 4
    hi = np.max(np.array(extents)[:, 2:], axis=0) + 4
    xx, yy = np.meshgrid(np.arange(lo[0], hi[0] + step, step),
                         np.arange(lo[1], hi[1] + step, step))
    field = displacement(np.stack((xx, yy), -1), jaw, eyes)
    low, high = 0., 1.
    for _ in range(14):
        scale = (low + high) * .5
        minimum, maximum = area_range(field * scale, step)
        if minimum >= .805 and maximum <= 1.245:
            low = scale
        else:
            high = scale
    return ([(x, y, dx * low, dy * low, r, gate) for x, y, dx, dy, r, gate in jaw],
            [(x, y, r, strength * low) for x, y, r, strength in eyes])


def yaw_weight(points):
    """Conservative profile fade from nose-tip offset between the two cheeks."""
    left, right = points[234], points[454]
    width = max(float(np.linalg.norm(right - left)), 1.)
    midpoint = (left + right) * .5
    offset = abs(float(points[1, 0] - midpoint[0])) / width
    return float(np.clip((.38 - offset) / .22, 0., 1.))


def controls(points, slim, eyes, fade):
    """Return pixel-space jaw and eye controls, capped by a global fold bound."""
    if len(points) < 455 or not np.isfinite(points).all():
        return [], []
    width = float(np.linalg.norm(points[454] - points[234]))
    if width < 8:
        return [], []
    axis = points[152] - points[168]
    length = float(np.linalg.norm(axis))
    if length < 1:
        return [], []
    normal = np.array([axis[1], -axis[0]], np.float32) / length
    # Slider strength is linear; temporal stability belongs in the tracked
    # geometry rather than a curve that hides the effect at partial settings.
    # Three or more landmark spacings per kernel keeps the contour interpolation
    # broad even around the sparse upper jaw. The envelope remains compact.
    contour = points[list(JAW)]
    spacing = float(np.max(np.linalg.norm(np.diff(contour, axis=0), axis=1)))
    radius = max(.30 * width, 3. * spacing, 2.)
    gate_y = float(points[1, 1] - .2 * width)
    jaw = []
    for index in JAW:
        p = points[index]
        along = float(np.dot(p - points[168], normal))
        # The chin lies close to the centre line and receives almost no push.
        vector = -np.sign(along) * normal * min(abs(along) / (.5 * width), 1.) * (.07 * width * slim * fade)
        jaw.append((float(p[0]), float(p[1]), float(vector[0]), float(vector[1]), radius, gate_y))
    eye_controls = []
    for contour in (LEFT_EYE, RIGHT_EYE):
        shape = points[list(contour)]
        centre = shape.mean(axis=0)
        eye_width = float(np.linalg.norm(shape[3] - shape[0]))
        if eye_width >= 3:
            eye_controls.append((float(centre[0]), float(centre[1]), 1.15 * eye_width,
                                 min(.24 * eyes * fade, .24)))
    return guard_controls(jaw, eye_controls)


@register_pass('warp', 250)
class Warp(Pass):
    reads = ('rgb', 'mask', 'skin', 'region:*')
    writes = reads

    def setup(self, gl, width, height):
        self.gl, self.width, self.height = gl, width, height
        self.field = self.field_fb = None
        self.blur_x = self.blur_y = None
        self.blur_x_fb = self.blur_y_fb = None
        self.history = []
        self.history_fb = []
        self.history_index = 0
        self.history_valid = False
        self.previous_centre = None
        self.last_strength = None
        self.targets = {}
        self.tracks = []
        self.last_face = None

    def enabled(self, recipe, frame_ctx):
        active = bool(recipe.reshape.slim or recipe.reshape.eyes)
        if not active:
            self.history_valid = False
        return active

    def _setup_gpu(self):
        if self.field is not None:
            return
        self.field_program, self.field_va = self.gl.program(FIELD)
        self.apply_program, self.apply_va = self.gl.program(APPLY)
        self.blur_program, self.blur_va = self.gl.program(BLUR)
        self.temporal_program, self.temporal_va = self.gl.program(TEMPORAL)
        size = ((self.width + 1) // 2, (self.height + 1) // 2)
        self.field = self.gl.gl.texture(size, 2, dtype='f2')
        self.field.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.field.repeat_x = self.field.repeat_y = False
        self.field_fb = self.gl.gl.framebuffer(color_attachments=[self.field])
        self.blur_x = self.gl.gl.texture(size, 2, dtype='f2')
        self.blur_y = self.gl.gl.texture(size, 2, dtype='f2')
        for texture in (self.blur_x, self.blur_y):
            texture.filter = (moderngl.LINEAR, moderngl.LINEAR)
            texture.repeat_x = texture.repeat_y = False
        self.blur_x_fb = self.gl.gl.framebuffer(color_attachments=[self.blur_x])
        self.blur_y_fb = self.gl.gl.framebuffer(color_attachments=[self.blur_y])
        for _ in range(2):
            texture = self.gl.gl.texture(size, 2, dtype='f2')
            texture.filter = (moderngl.LINEAR, moderngl.LINEAR)
            texture.repeat_x = texture.repeat_y = False
            self.history.append(texture)
            self.history_fb.append(self.gl.gl.framebuffer(color_attachments=[texture]))

    def _update_tracks(self, face):
        if face is self.last_face:
            return
        self.last_face = face
        if face is not None and face.reset:
            self.tracks.clear()
            self.history_valid = False
        landmarks = [] if face is None else list(face.landmarks or [])
        landmarks.sort(key=lambda p: -float(np.linalg.norm(p[454] - p[234])))
        landmarks = landmarks[:2]
        previous = self.tracks
        next_tracks = []
        used = set()
        for points in landmarks:
            centre = (points[234] + points[454]) * .5
            width = max(float(np.linalg.norm(points[454] - points[234])), 1.)
            choices = [(float(np.linalg.norm(centre - t['centre'])), i)
                       for i, t in enumerate(previous) if i not in used]
            distance, index = min(choices, default=(float('inf'), -1))
            if index >= 0 and distance < width * .6:
                track = previous[index]
                used.add(index)
            else:
                track = {'fade': 0.}
            # Smooth shape, size, centre and axis in a face-local frame. This
            # stronger EMA removes detector-driven field motion while keeping
            # translation and rotation in the same tracked coordinate frame.
            axis = points[152] - points[168]
            axis /= max(float(np.linalg.norm(axis)), 1.)
            side = np.array([axis[1], -axis[0]], np.float32)
            basis = np.stack((side, axis), axis=1)
            local = (points - centre) @ basis / width
            if 'local' in track:
                track['local'] = .12 * local + .88 * track['local']
                track['width'] = .12 * width + .88 * track['width']
                track['stable_centre'] = .18 * centre + .82 * track['stable_centre']
                track['axis'] = .18 * axis + .82 * track['axis']
                track['axis'] /= max(float(np.linalg.norm(track['axis'])), 1e-6)
            else:
                track['local'] = local.copy()
                track['width'] = width
                track['stable_centre'] = centre.copy()
                track['axis'] = axis.copy()
            stable_axis = track['axis']
            stable_side = np.array([stable_axis[1], -stable_axis[0]], np.float32)
            stable_basis = np.stack((stable_side, stable_axis), axis=1)
            stable = track['stable_centre'] + (track['local'] * track['width']) @ stable_basis.T
            track.update(points=stable, centre=centre,
                         fade=min(1., track['fade'] + .125))
            next_tracks.append(track)
        for i, track in enumerate(previous):
            if i not in used and not any(track is item for item in next_tracks):
                track['fade'] -= .125
                if track['fade'] > 0:
                    next_tracks.append(track)
        self.tracks = next_tracks

    def _target(self, name, source):
        size = source.size
        existing = self.targets.get(name)
        if existing is not None and existing[0].size != size:
            existing[1].release(); existing[0].release()
            existing = None
        if existing is None:
            texture = self.gl.gl.texture(size, 4, dtype=source.dtype)
            texture.filter = (moderngl.LINEAR, moderngl.LINEAR)
            texture.repeat_x = texture.repeat_y = False
            existing = texture, self.gl.gl.framebuffer(color_attachments=[texture])
            self.targets[name] = existing
        return existing

    def run(self, frame_ctx):
        strength = (frame_ctx.recipe.reshape.slim, frame_ctx.recipe.reshape.eyes)
        if strength != self.last_strength:
            self.history_valid = False
            self.last_strength = strength
        self._update_tracks(frame_ctx.face)
        jaw, eyes = [], []
        for track in self.tracks[:2]:
            weight = track['fade'] * yaw_weight(track['points'])
            j, e = controls(track['points'], frame_ctx.recipe.reshape.slim,
                            frame_ctx.recipe.reshape.eyes, weight)
            jaw.extend(j); eyes.extend(e)
        if not jaw and not eyes:
            self.history_valid = False
            return
        jaw, eyes = guard_controls(jaw, eyes)
        self._setup_gpu()
        extents = [(x-r, y-r, x+r, y+r) for x, y, _, _, r, _ in jaw]
        extents += [(x-r, y-r, x+r, y+r) for x, y, r, _ in eyes]
        bounds = (min(v[0] for v in extents), min(v[1] for v in extents),
                  max(v[2] for v in extents), max(v[3] for v in extents))
        self.field_fb.use()
        self.gl.uniforms(self.field_program, full_size=(self.width, self.height),
                         active_bounds=bounds, jaw_count=len(jaw), eye_count=len(eyes))
        if jaw:
            self.field_program['jaw'].value = tuple(control[:4] for control in jaw) + ((0., 0., 0., 0.),) * (MAX_JAW - len(jaw))
            self.field_program['jaw_shape'].value = tuple(control[4:6] for control in jaw) + ((1., 0.),) * (MAX_JAW - len(jaw))
        if eyes:
            self.field_program['eye'].value = tuple(eyes) + ((0., 0., 0., 0.),) * (MAX_EYES - len(eyes))
        self.field_va.render(moderngl.TRIANGLE_STRIP)
        self.blur_x_fb.use()
        self.field.use(0)
        self.gl.uniforms(self.blur_program, src=0, step_uv=(1 / self.field.width, 0.))
        self.blur_va.render(moderngl.TRIANGLE_STRIP)
        self.blur_y_fb.use()
        self.blur_x.use(0)
        self.gl.uniforms(self.blur_program, src=0, step_uv=(0., 1 / self.field.height))
        self.blur_va.render(moderngl.TRIANGLE_STRIP)
        centre = self.tracks[0]['stable_centre']
        shift = (np.asarray(centre) - self.previous_centre) / (self.width, self.height) if self.history_valid else (0., 0.)
        self.history_index = 1 - self.history_index
        self.history_fb[self.history_index].use()
        self.blur_y.use(0)
        self.history[1 - self.history_index].use(1)
        self.gl.uniforms(self.temporal_program, current_field=0, previous_field=1,
                         shift_uv=tuple(shift), alpha=.12 if self.history_valid else 1.)
        self.temporal_va.render(moderngl.TRIANGLE_STRIP)
        self.history_valid = True
        self.previous_centre = np.asarray(centre).copy()
        mapped = {}
        for name, slot in list(frame_ctx.textures.items()):
            if name not in ('rgb', 'mask', 'skin') and not name.startswith('region:'):
                continue
            source = slot[0] if isinstance(slot, tuple) else slot
            key = id(source)
            if key not in mapped:
                target, fb = self._target(name, source)
                fb.use()
                source.use(0); self.history[self.history_index].use(1)
                self.gl.uniforms(self.apply_program, src=0, displacement=1)
                self.apply_va.render(moderngl.TRIANGLE_STRIP)
                mapped[key] = target
            frame_ctx.textures[name] = (mapped[key], slot[1]) if isinstance(slot, tuple) else mapped[key]

    def release(self):
        for target, fb in self.targets.values():
            fb.release(); target.release()
        if self.field_fb is not None:
            self.field_fb.release(); self.field.release()
            self.blur_x_fb.release(); self.blur_x.release()
            self.blur_y_fb.release(); self.blur_y.release()
            for fb, texture in zip(self.history_fb, self.history):
                fb.release(); texture.release()
