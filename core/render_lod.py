import math
from typing import Iterable

import numpy as np


def decimate_line_strip(points: Iterable, target_max: int) -> np.ndarray:
    pts = np.asarray(points, dtype=np.float32)
    if pts.ndim != 2 or pts.shape[1] != 3:
        return pts
    if target_max <= 0:
        return pts
    n = int(pts.shape[0])
    if n <= target_max:
        return pts
    if target_max < 2:
        return pts[:1]
    step = int(math.ceil((n - 1) / float(target_max - 1)))
    idx = np.arange(0, n, step, dtype=np.int32)
    if idx[-1] != n - 1:
        idx = np.append(idx, n - 1)
    return pts[idx]
