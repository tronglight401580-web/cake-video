"""One Euro landmark smoothing with nearest-centre face association."""
import math
import numpy as np

from ..core.config import LANDMARK_MIN_CUTOFF, LANDMARK_BETA


class OneEuro:
    def __init__(self, min_cutoff=LANDMARK_MIN_CUTOFF, beta=LANDMARK_BETA, d_cutoff=1.0):
        self.min_cutoff, self.beta, self.d_cutoff = min_cutoff, beta, d_cutoff
        self.value = self.derivative = None

    @staticmethod
    def _alpha(cutoff, dt):
        return 1.0 / (1.0 + 1.0 / (2.0 * math.pi * cutoff * dt))

    def __call__(self, value, dt):
        value = np.asarray(value, np.float32)
        if self.value is None:
            self.value = value.copy()
            self.derivative = np.zeros_like(value)
            return self.value.copy()
        dt = max(float(dt), 1e-6)
        dx = (value - self.value) / dt
        a_d = self._alpha(self.d_cutoff, dt)
        self.derivative += a_d * (dx - self.derivative)
        cutoff = self.min_cutoff + self.beta * np.abs(self.derivative)
        self.value += self._alpha(cutoff, dt) * (value - self.value)
        return self.value.copy()


class FaceTracker:
    def __init__(self):
        self.tracks = []

    def reset(self):
        self.tracks = []

    def update(self, faces, dt, reset=False):
        if reset or not faces:
            self.reset()
        used = set()
        next_tracks, output = [], []
        for face in faces:
            lo, hi = face.min(axis=0), face.max(axis=0)
            center = (lo + hi) * 0.5
            radius = max(float(np.linalg.norm(hi - lo)) * 0.5, 1.0)
            candidates = [(float(np.linalg.norm(center - old_center)), i)
                          for i, (old_center, _, _) in enumerate(self.tracks) if i not in used]
            distance, i = min(candidates, default=(float('inf'), -1))
            if i >= 0 and distance < max(radius, self.tracks[i][2]):
                used.add(i)
                filt = self.tracks[i][1]
            else:
                filt = OneEuro()
            smooth = filt(face, dt)
            output.append(smooth)
            next_tracks.append((center, filt, radius))
        self.tracks = next_tracks
        return output
