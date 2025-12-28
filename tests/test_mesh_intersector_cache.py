import unittest

import numpy as np

try:
    import trimesh
except ImportError:
    trimesh = None

from core.mesh_intersector_cache import MeshIntersectorCache


class MeshIntersectorCacheTests(unittest.TestCase):
    def test_cache_reuse_by_version(self):
        if trimesh is None:
            self.skipTest("trimesh not available")
        vertices = np.array(
            [
                [0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                [1.0, 1.0, 0.0],
                [0.0, 1.0, 0.0],
            ],
            dtype=np.float64,
        )
        faces = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int64)
        mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
        cache = MeshIntersectorCache()
        intersector_1 = cache.get(mesh, mesh_version=1)
        intersector_2 = cache.get(mesh, mesh_version=1)
        self.assertIsNotNone(intersector_1)
        self.assertIs(intersector_1, intersector_2)
        self.assertEqual(cache.build_count, 1)

        mesh_2 = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
        intersector_3 = cache.get(mesh_2, mesh_version=2)
        self.assertIsNotNone(intersector_3)
        self.assertEqual(cache.build_count, 2)


if __name__ == "__main__":
    unittest.main()
