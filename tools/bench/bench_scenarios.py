import math
import time
from typing import Dict, List, Optional

from tools.bench.bench_runner import BenchmarkResult


def get_benchmarks():
    return {
        "z_compute": bench_z_compute,
        "z_compute_bigmesh": bench_z_compute_bigmesh,
        "z_total_bigmesh": bench_z_total_bigmesh,
        "z_build_only": bench_z_build_only,
        "z_query_only": bench_z_query_only,
        "lod_decimate": bench_lod_decimate,
        "render_cache_build_cpu": bench_render_cache_build_cpu,
    }


def bench_z_compute(repeats: int = 5, warmups: int = 1, params: Optional[dict] = None):
    np, trimesh, compute_z_for_points, cache_cls, err = _load_z_deps()
    if err:
        return _skip_z_compute_named("z_compute", err)
    grid_n = _get_int_param(params, "grid_n", 100, min_value=2)
    mesh = _make_box_mesh(trimesh)
    points_xy = _build_grid_points(np, mesh, grid_n)
    meta = {"grid_n": grid_n, "mesh_subdiv": 0, "mesh_type": "box"}
    return _bench_z_compute_common(
        "z_compute",
        mesh,
        points_xy,
        compute_z_for_points,
        cache_cls,
        repeats,
        warmups,
        meta,
    )


def bench_z_compute_bigmesh(repeats: int = 5, warmups: int = 1, params: Optional[dict] = None):
    np, trimesh, compute_z_for_points, cache_cls, err = _load_z_deps()
    if err:
        return _skip_z_compute_named("z_compute_bigmesh", err)
    grid_n = _get_int_param(params, "grid_n", 100, min_value=2)
    mesh_subdiv = _get_int_param(params, "mesh_subdiv", 4, min_value=0)
    mesh = _make_big_mesh(trimesh, mesh_subdiv)
    points_xy = _build_grid_points(np, mesh, grid_n)
    meta = {
        "grid_n": grid_n,
        "mesh_subdiv": mesh_subdiv,
        "mesh_type": "icosphere",
    }
    return _bench_z_compute_common(
        "z_compute_bigmesh",
        mesh,
        points_xy,
        compute_z_for_points,
        cache_cls,
        repeats,
        warmups,
        meta,
    )


def bench_z_total_bigmesh(repeats: int = 5, warmups: int = 1, params: Optional[dict] = None):
    np, trimesh, compute_z_for_points, cache_cls, err = _load_z_deps()
    if err:
        return _skip_z_compute_named("z_total_bigmesh", err)
    grid_n = _get_int_param(params, "grid_n", 100, min_value=2)
    mesh_subdiv = _get_int_param(params, "mesh_subdiv", 4, min_value=0)
    mesh = _make_big_mesh(trimesh, mesh_subdiv)
    points_xy = _build_grid_points(np, mesh, grid_n)
    meta = {
        "grid_n": grid_n,
        "mesh_subdiv": mesh_subdiv,
        "mesh_type": "icosphere",
    }
    return _bench_z_compute_common(
        "z_total_bigmesh",
        mesh,
        points_xy,
        compute_z_for_points,
        cache_cls,
        repeats,
        0,
        meta,
        include_warm_build=True,
    )


def bench_z_build_only(repeats: int = 5, warmups: int = 1, params: Optional[dict] = None):
    try:
        import trimesh
    except Exception as exc:
        return _skip_z_compute_named("z_build_only", str(exc))
    try:
        from core.mesh_intersector_cache import MeshIntersectorCache
    except Exception as exc:
        return _skip_z_compute_named("z_build_only", str(exc))

    grid_n = _get_int_param(params, "grid_n", 100, min_value=2)
    mesh_subdiv = _get_int_param(params, "mesh_subdiv", 4, min_value=0)
    mesh = _make_big_mesh(trimesh, mesh_subdiv)
    face_count = _mesh_faces(mesh)
    point_count = int(grid_n) * int(grid_n)

    cold_timings: List[float] = []
    warm_timings: List[float] = []

    cache = MeshIntersectorCache()
    for i in range(warmups):
        cache.get(mesh, mesh_version=1000 + i)
    start_builds = cache.build_count
    for i in range(repeats):
        t0 = time.perf_counter()
        cache.get(mesh, mesh_version=2000 + i)
        cold_timings.append((time.perf_counter() - t0) * 1000.0)
    cold_builds = cache.build_count - start_builds

    cache = MeshIntersectorCache()
    cache.get(mesh, mesh_version=1)
    for _ in range(warmups):
        cache.get(mesh, mesh_version=1)
    start_builds = cache.build_count
    for _ in range(repeats):
        t0 = time.perf_counter()
        cache.get(mesh, mesh_version=1)
        warm_timings.append((time.perf_counter() - t0) * 1000.0)
    warm_builds = cache.build_count - start_builds

    meta_base = {
        "point_count": point_count,
        "mesh_faces": face_count,
        "mesh_subdiv": mesh_subdiv,
        "grid_n": grid_n,
        "mesh_type": "icosphere",
        "cache_available": True,
    }

    cold_result = BenchmarkResult(
        name="z_build_only",
        params={"cache": "cold"},
        timings_ms=cold_timings,
        meta={**meta_base, "cache_builds": cold_builds},
    )
    warm_result = BenchmarkResult(
        name="z_build_only",
        params={"cache": "warm"},
        timings_ms=warm_timings,
        meta={**meta_base, "cache_builds": warm_builds},
    )
    return [cold_result, warm_result]


def bench_z_query_only(repeats: int = 5, warmups: int = 1, params: Optional[dict] = None):
    try:
        import numpy as np
    except Exception as exc:
        return _skip_query_only(str(exc))
    try:
        import trimesh
    except Exception as exc:
        return _skip_query_only(str(exc))

    cache_cls = None
    try:
        from core.mesh_intersector_cache import MeshIntersectorCache

        cache_cls = MeshIntersectorCache
    except Exception:
        cache_cls = None

    mesh_subdiv = _get_int_param(params, "mesh_subdiv", 4, min_value=0)
    grid_n = _get_int_param(params, "grid_n", 100, min_value=2)
    mesh = _make_big_mesh(trimesh, mesh_subdiv)
    points_xy = _build_grid_points(np, mesh, grid_n)
    face_count = _mesh_faces(mesh)
    point_count = int(points_xy.shape[0])

    bounds = getattr(mesh, "bounds", None)
    if bounds is None or len(bounds) < 2:
        return _skip_query_only("mesh bounds unavailable", grid_n, mesh_subdiv)
    z_min = float(bounds[0][2])
    z_max = float(bounds[1][2])
    margin = max(1.0, (z_max - z_min) * 0.1)
    origins = np.column_stack(
        [points_xy.astype(np.float64), np.full(len(points_xy), z_max + margin, dtype=np.float64)]
    )
    directions = np.tile(np.array([0.0, 0.0, -1.0], dtype=np.float64), (len(points_xy), 1))

    cache_builds = None
    cache_available = cache_cls is not None
    if cache_cls is not None:
        cache = cache_cls()
        intersector = cache.get(mesh, mesh_version=1)
        cache_builds = cache.build_count
    else:
        intersector = getattr(mesh, "ray", None)

    if intersector is None or not hasattr(intersector, "intersects_location"):
        return _skip_query_only("intersector unavailable", grid_n, mesh_subdiv, cache_available, cache_builds)

    for _ in range(warmups):
        intersector.intersects_location(
            ray_origins=origins,
            ray_directions=directions,
            multiple_hits=True,
        )

    timings: List[float] = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        intersector.intersects_location(
            ray_origins=origins,
            ray_directions=directions,
            multiple_hits=True,
        )
        timings.append((time.perf_counter() - t0) * 1000.0)

    return BenchmarkResult(
        name="z_query_only",
        params={"cache": "warm"} if cache_available else {},
        timings_ms=timings,
        meta={
            "point_count": point_count,
            "mesh_faces": face_count,
            "mesh_subdiv": mesh_subdiv,
            "grid_n": grid_n,
            "mesh_type": "icosphere",
            "cache_available": cache_available,
            "cache_builds": cache_builds,
        },
    )


def bench_lod_decimate(repeats: int = 5, warmups: int = 1, params: Optional[dict] = None):
    try:
        import numpy as np
    except Exception as exc:
        return _skip_result("lod_decimate", str(exc))
    try:
        from core.render_lod import decimate_line_strip
    except Exception as exc:
        return _skip_result("lod_decimate", str(exc))

    point_count = _get_int_param(params, "point_count", 100000, min_value=2)
    target_max = _get_int_param(params, "lod_target", 10000, min_value=2)
    if params and "target_max" in params and "lod_target" not in params:
        target_max = _get_int_param(params, "target_max", target_max, min_value=2)

    t = np.linspace(0.0, 20.0 * math.pi, point_count, dtype=np.float64)
    x = np.cos(t) * (t * 0.05)
    y = np.sin(t) * (t * 0.05)
    z = np.zeros_like(t)
    points = np.column_stack([x, y, z]).astype(np.float32)

    result = decimate_line_strip(points, target_max)
    if int(result.shape[0]) > target_max:
        raise AssertionError("LOD result exceeds target_max")
    if not np.allclose(result[0], points[0]):
        raise AssertionError("LOD result does not preserve first point")
    if not np.allclose(result[-1], points[-1]):
        raise AssertionError("LOD result does not preserve last point")

    for _ in range(warmups):
        decimate_line_strip(points, target_max)

    timings: List[float] = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        decimate_line_strip(points, target_max)
        timings.append((time.perf_counter() - t0) * 1000.0)

    return BenchmarkResult(
        name="lod_decimate",
        params={"points": point_count, "target_max": target_max},
        timings_ms=timings,
        meta={"point_count": point_count, "lod_target": target_max},
    )


def bench_render_cache_build_cpu(repeats: int = 5, warmups: int = 1, params: Optional[dict] = None):
    try:
        import numpy as np
    except Exception as exc:
        return _skip_result("render_cache_build_cpu", str(exc))
    try:
        from core.render_lod import decimate_line_strip
    except Exception as exc:
        return _skip_result("render_cache_build_cpu", str(exc))

    point_count = _get_int_param(params, "point_count", 100000, min_value=2)
    target_max = _get_int_param(params, "lod_target", 10000, min_value=2)
    if params and "target_max" in params and "lod_target" not in params:
        target_max = _get_int_param(params, "target_max", target_max, min_value=2)

    t = np.linspace(0.0, 20.0 * math.pi, point_count, dtype=np.float64)
    x = np.cos(t) * (t * 0.05)
    y = np.sin(t) * (t * 0.05)
    z = np.zeros_like(t)
    points = np.column_stack([x, y, z]).astype(np.float32)

    cache_impl = "equivalent"
    import_error = None
    try:
        from gl_viewer import ToolpathRenderCache
    except Exception as exc:
        ToolpathRenderCache = None
        import_error = str(exc)

    if ToolpathRenderCache is not None:
        cache_impl = "toolpath_render_cache"
        cache = ToolpathRenderCache(lod_target=target_max)

        def _build():
            cache.build_cpu_arrays(points)

    else:
        def _build():
            pts = np.asarray(points, dtype=np.float32)
            pts = np.ascontiguousarray(pts)
            lod = decimate_line_strip(pts, target_max)
            _ = np.ascontiguousarray(lod)

    for _ in range(warmups):
        _build()

    timings: List[float] = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        _build()
        timings.append((time.perf_counter() - t0) * 1000.0)

    meta = {
        "point_count": point_count,
        "lod_target": target_max,
        "impl": cache_impl,
    }
    if import_error and cache_impl != "toolpath_render_cache":
        meta["note"] = "ToolpathRenderCache import failed"
        meta["import_error"] = import_error

    return BenchmarkResult(
        name="render_cache_build_cpu",
        params={"points": point_count, "target_max": target_max},
        timings_ms=timings,
        meta=meta,
    )


def _load_z_deps():
    try:
        import numpy as np
    except Exception as exc:
        return None, None, None, None, str(exc)
    try:
        import trimesh
    except Exception as exc:
        return np, None, None, None, str(exc)
    try:
        from toolpath_generator import compute_z_for_points
    except Exception as exc:
        return np, trimesh, None, None, str(exc)
    try:
        from core.mesh_intersector_cache import MeshIntersectorCache
    except Exception:
        MeshIntersectorCache = None
    return np, trimesh, compute_z_for_points, MeshIntersectorCache, None


def _make_box_mesh(trimesh):
    return trimesh.creation.box(extents=(100.0, 100.0, 10.0))


def _make_big_mesh(trimesh, mesh_subdiv: int):
    return trimesh.creation.icosphere(subdivisions=mesh_subdiv)


def _build_grid_points(np, mesh, grid_n: int):
    bounds = getattr(mesh, "bounds", None)
    if bounds is None or len(bounds) < 2:
        return np.zeros((0, 2), dtype=np.float32)
    min_x, min_y = float(bounds[0][0]), float(bounds[0][1])
    max_x, max_y = float(bounds[1][0]), float(bounds[1][1])
    margin_x = (max_x - min_x) * 0.1
    margin_y = (max_y - min_y) * 0.1
    xs = np.linspace(min_x + margin_x, max_x - margin_x, grid_n, dtype=np.float64)
    ys = np.linspace(min_y + margin_y, max_y - margin_y, grid_n, dtype=np.float64)
    xx, yy = np.meshgrid(xs, ys)
    return np.column_stack([xx.ravel(), yy.ravel()]).astype(np.float32)


def _bench_z_compute_common(
    name: str,
    mesh,
    points_xy,
    compute_z_for_points,
    cache_cls,
    repeats: int,
    warmups: int,
    meta: Dict[str, int],
    include_warm_build: bool = False,
):
    point_count = int(points_xy.shape[0])
    face_count = _mesh_faces(mesh)
    cache_available = cache_cls is not None
    grid_n = 0
    mesh_subdiv = 0
    if meta:
        try:
            grid_n = int(meta.get("grid_n", 0))
        except Exception:
            grid_n = 0
        try:
            mesh_subdiv = int(meta.get("mesh_subdiv", 0))
        except Exception:
            mesh_subdiv = 0

    def _run(cache, mesh_version):
        compute_z_for_points(
            mesh,
            points_xy,
            "A",
            intersector_cache=cache,
            mesh_version=mesh_version,
        )

    cold_timings: List[float] = []
    warm_timings: List[float] = []

    cold_builds = None
    if cache_available:
        cache = cache_cls()
        for i in range(warmups):
            _run(cache, 1000 + i)
        start_builds = cache.build_count
        for i in range(repeats):
            t0 = time.perf_counter()
            _run(cache, 2000 + i)
            cold_timings.append((time.perf_counter() - t0) * 1000.0)
        cold_builds = cache.build_count - start_builds
    else:
        for _ in range(warmups):
            _run(None, None)
        for _ in range(repeats):
            t0 = time.perf_counter()
            _run(None, None)
            cold_timings.append((time.perf_counter() - t0) * 1000.0)

    warm_builds = None
    if cache_available:
        cache = cache_cls()
        warm_warmups = 0 if include_warm_build else warmups
        if not include_warm_build:
            _run(cache, 1)
        for _ in range(warm_warmups):
            _run(cache, 1)
        start_builds = cache.build_count
        for _ in range(repeats):
            t0 = time.perf_counter()
            _run(cache, 1)
            warm_timings.append((time.perf_counter() - t0) * 1000.0)
        warm_builds = cache.build_count - start_builds
    else:
        warm_warmups = 0 if include_warm_build else warmups
        for _ in range(warm_warmups):
            _run(None, None)
        for _ in range(repeats):
            t0 = time.perf_counter()
            _run(None, None)
            warm_timings.append((time.perf_counter() - t0) * 1000.0)

    meta_base = {
        "point_count": point_count,
        "mesh_faces": face_count,
        "mesh_subdiv": mesh_subdiv,
        "grid_n": grid_n,
        "cache_available": cache_available,
    }
    meta_base.update(meta or {})

    cold_result = BenchmarkResult(
        name=name,
        params={"cache": "cold"},
        timings_ms=cold_timings,
        meta={**meta_base, "cache_builds": cold_builds},
    )
    warm_result = BenchmarkResult(
        name=name,
        params={"cache": "warm"},
        timings_ms=warm_timings,
        meta={**meta_base, "cache_builds": warm_builds},
    )
    return [cold_result, warm_result]


def _mesh_faces(mesh) -> int:
    try:
        return int(len(mesh.faces))
    except Exception:
        return 0


def _get_int_param(
    params: Optional[dict],
    key: str,
    default: int,
    min_value: Optional[int] = None,
    max_value: Optional[int] = None,
) -> int:
    value = default
    if params and key in params:
        try:
            value = int(params.get(key))
        except Exception:
            value = default
    if min_value is not None and value < min_value:
        value = min_value
    if max_value is not None and value > max_value:
        value = max_value
    return value


def _skip_result(name: str, reason: str):
    return BenchmarkResult(
        name=name,
        params={},
        timings_ms=[],
        meta={"skipped": True, "reason": reason},
    )


def _skip_z_compute(reason: str):
    return _skip_z_compute_named("z_compute", reason)


def _skip_z_compute_named(name: str, reason: str):
    meta = {
        "skipped": True,
        "reason": reason,
        "point_count": 0,
        "mesh_faces": 0,
        "mesh_subdiv": 0,
        "grid_n": 0,
        "cache_available": False,
        "cache_builds": None,
    }
    cold = BenchmarkResult(
        name=name,
        params={"cache": "cold"},
        timings_ms=[],
        meta=meta,
    )
    warm = BenchmarkResult(
        name=name,
        params={"cache": "warm"},
        timings_ms=[],
        meta=meta,
    )
    return [cold, warm]


def _skip_query_only(
    reason: str,
    grid_n: int = 0,
    mesh_subdiv: int = 0,
    cache_available: bool = False,
    cache_builds: Optional[int] = None,
):
    return BenchmarkResult(
        name="z_query_only",
        params={},
        timings_ms=[],
        meta={
            "skipped": True,
            "reason": reason,
            "point_count": 0,
            "mesh_faces": 0,
            "mesh_subdiv": mesh_subdiv,
            "grid_n": grid_n,
            "cache_available": cache_available,
            "cache_builds": cache_builds,
        },
    )
