# tabs/knife_model.py
# ----------------------------------------------------------
# Knife STL'den mesh yükler, parametrelerle ölçekler ve Z eksenine hizalar.
# ----------------------------------------------------------

import struct
from dataclasses import dataclass
from pathlib import Path
import numpy as np


# ----------------------------------------------------------
# STL OKUMA
# ----------------------------------------------------------
def load_stl_binary(path: Path):
    """Binary STL okur -> (vertices, normals) float32."""
    with path.open("rb") as f:
        f.read(80)  # header
        tri_count = struct.unpack("<I", f.read(4))[0]

        verts = np.zeros((tri_count * 3, 3), dtype=np.float32)
        norms = np.zeros((tri_count * 3, 3), dtype=np.float32)

        for i in range(tri_count):
            nx, ny, nz = struct.unpack("<fff", f.read(12))
            v1 = struct.unpack("<fff", f.read(12))
            v2 = struct.unpack("<fff", f.read(12))
            v3 = struct.unpack("<fff", f.read(12))
            f.read(2)  # attribute

            base = i * 3
            verts[base + 0] = v1
            verts[base + 1] = v2
            verts[base + 2] = v3

            norms[base + 0] = (nx, ny, nz)
            norms[base + 1] = (nx, ny, nz)
            norms[base + 2] = (nx, ny, nz)

    return verts, norms


def load_knife_stl(path: str = "tabs/knife.STL"):
    """tabs klasöründeki knife.STL'yi yükler; yoksa boş mesh döner."""
    p = Path(path)
    if not p.exists():
        return np.zeros((0, 3), dtype=np.float32), np.zeros((0, 3), dtype=np.float32)
    return load_stl_binary(p)


# ----------------------------------------------------------
# Parametre veri sınıfı
# ----------------------------------------------------------
@dataclass
class KnifeParams:
    length_mm: float
    tip_diam_mm: float
    body_diam_mm: float


# ----------------------------------------------------------
# Mesh üretimi
# ----------------------------------------------------------
def generate_knife_mesh(params: KnifeParams):
    """
    knife.STL'yi yükler, en uzun ekseni Z'ye hizalar, boyu ve gövde çapını parametrelere göre ölçekler.
    Uç Z- yönünde kalır, taban Z=0'a taşınır.
    """
    verts, norms = load_knife_stl()
    if verts.size == 0:
        return verts, norms

    # En uzun ekseni Z'ye hizala
    ext = verts.max(axis=0) - verts.min(axis=0)
    longest = int(np.argmax(ext))

    def _reorder(arr, order):
        return arr[:, order]

    if longest == 0:  # X -> Z
        verts = _reorder(verts, [2, 1, 0])
        norms = _reorder(norms, [2, 1, 0])
    elif longest == 1:  # Y -> Z
        verts = _reorder(verts, [0, 2, 1])
        norms = _reorder(norms, [0, 2, 1])

    # Ölçekler
    model_len = np.ptp(verts[:, 2])
    sz = params.length_mm / model_len if model_len > 0 and params.length_mm > 0 else 1.0

    body_span_xy = max(np.ptp(verts[:, 0]), np.ptp(verts[:, 1]))
    s_xy = params.body_diam_mm / body_span_xy if body_span_xy > 0 and params.body_diam_mm > 0 else 1.0

    scale_vec = np.array([s_xy, s_xy, sz], dtype=np.float32)
    verts = verts * scale_vec

    # Ucu Z- yönüne çevir: hangi uç daha inceyse o ucu negatifte bırak
    z_min, z_max = verts[:, 2].min(), verts[:, 2].max()
    z_len = max(z_max - z_min, 1e-6)

    def _span_at(z_slice):
        sel = verts[np.isclose(verts[:, 2], z_slice, atol=z_len * 0.02)]
        if sel.size == 0:
            return float("inf")
        return max(np.ptp(sel[:, 0]), np.ptp(sel[:, 1]))

    tip_at_min = _span_at(z_min) <= _span_at(z_max)
    if not tip_at_min:
        verts[:, 2] *= -1
        norms[:, 2] *= -1
        z_min, z_max = -z_max, -z_min

    # Tabanı Z=0'a taşı, uç Z- tarafında kalsın
    verts[:, 2] -= verts[:, 2].max()

    return verts.astype(np.float32), norms.astype(np.float32)


if __name__ == "__main__":
    p = KnifeParams(length_mm=40.0, tip_diam_mm=0.3, body_diam_mm=3.0)
    v, n = generate_knife_mesh(p)
    print("vertex:", v.shape[0], "triangles:", v.shape[0] // 3)
