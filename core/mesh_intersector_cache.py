import logging
from typing import Optional, Tuple

try:
    import trimesh
except ImportError:
    trimesh = None

logger = logging.getLogger(__name__)


class MeshIntersectorCache:
    def __init__(self):
        self._key: Optional[Tuple[object, ...]] = None
        self._intersector = None
        self.build_count = 0

    def invalidate(self) -> None:
        self._key = None
        self._intersector = None

    def _make_key(self, mesh, mesh_version: Optional[int]) -> Tuple[object, ...]:
        if mesh_version is not None:
            return ("v", int(mesh_version))
        try:
            v_count = int(len(mesh.vertices))
            f_count = int(len(mesh.faces))
        except Exception:
            v_count = 0
            f_count = 0
        return ("id", id(mesh), v_count, f_count)

    def _build_intersector(self, mesh):
        if trimesh is None:
            return None
        try:
            return trimesh.ray.ray_triangle.RayMeshIntersector(mesh)
        except Exception:
            try:
                return mesh.ray
            except Exception:
                return None

    def get(self, mesh, mesh_version: Optional[int] = None):
        if mesh is None:
            return None
        key = self._make_key(mesh, mesh_version)
        if key == self._key and self._intersector is not None:
            logger.info("BVH cache: reuse (mesh_version=%s)", mesh_version)
            return self._intersector
        intersector = self._build_intersector(mesh)
        if intersector is None:
            return None
        self._key = key
        self._intersector = intersector
        self.build_count += 1
        face_count = 0
        try:
            face_count = int(len(mesh.faces))
        except Exception:
            face_count = 0
        logger.info("BVH cache: built (mesh_version=%s, faces=%s)", mesh_version, face_count)
        return intersector
