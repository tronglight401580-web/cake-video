"""Read / write Adobe .cube 3D LUTs. Data order: R fastest, then G, then B."""
from __future__ import annotations

from pathlib import Path

import numpy as np


def identity(n: int = 33) -> np.ndarray:
    """(n, n, n, 3) grid indexed [b, g, r] -> rgb, matching .cube / GL texture3D order."""
    x = np.linspace(0.0, 1.0, n, dtype=np.float64)
    b, g, r = np.meshgrid(x, x, x, indexing="ij")
    return np.stack([r, g, b], axis=-1)


def write_cube(path: str | Path, lut: np.ndarray, title: str = "") -> None:
    n = lut.shape[0]
    flat = np.clip(lut.reshape(-1, 3), 0.0, 1.0)
    lines = [f'TITLE "{title}"' if title else "# cake LUT", f"LUT_3D_SIZE {n}",
             "DOMAIN_MIN 0 0 0", "DOMAIN_MAX 1 1 1"]
    lines += [f"{r:.6f} {g:.6f} {b:.6f}" for r, g, b in flat]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_cube(path: str | Path) -> np.ndarray:
    """Returns float32 (n, n, n, 3) indexed [b, g, r]. Domain is normalised to [0, 1]."""
    size = None
    dmin = np.zeros(3)
    dmax = np.ones(3)
    rows = []
    for raw in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key = line.split()[0].upper()
        if key == "LUT_3D_SIZE":
            size = int(line.split()[1])
        elif key == "LUT_1D_SIZE":
            raise ValueError(f"{path}: 1D LUTs are not supported")
        elif key == "DOMAIN_MIN":
            dmin = np.array([float(v) for v in line.split()[1:4]])
        elif key == "DOMAIN_MAX":
            dmax = np.array([float(v) for v in line.split()[1:4]])
        elif key in ("TITLE", "LUT_3D_INPUT_RANGE"):
            continue
        elif key[0].isdigit() or key[0] in "-.":
            rows.append([float(v) for v in line.split()[:3]])
    if size is None or len(rows) != size ** 3:
        raise ValueError(f"{path}: expected {size}^3 entries, got {len(rows)}")
    lut = np.asarray(rows, dtype=np.float32).reshape(size, size, size, 3)
    if not (np.allclose(dmin, 0) and np.allclose(dmax, 1)):
        # Output values are in the same domain as input; renormalise.
        lut = (lut - dmin) / (dmax - dmin)
    return lut.astype(np.float32)
