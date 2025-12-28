from dataclasses import dataclass, field
from typing import Optional, List

from core.mesh_intersector_cache import MeshIntersectorCache


@dataclass
class STLModel:
    vertices: Optional[List[float]] = None
    faces: Optional[List[int]] = None
    path: Optional[str] = None


@dataclass
class KnifeConfig:
    length: float = 20.0
    offset: float = 5.0
    angle_limit: float = 60.0
    name: str = "Varsayılan Bıçak"


@dataclass
class SimulationSettings:
    show_axes: bool = True
    show_grid: bool = True
    camera_distance: float = 1200.0


@dataclass
class TableConfig:
    width: float = 1600.0
    height: float = 1000.0
    grid_step: float = 50.0


@dataclass
class ToolpathPoint:
    x: float
    y: float
    z: float
    a: Optional[float] = None


@dataclass
class ToolpathResult:
    points: List[ToolpathPoint] = field(default_factory=list)
    gcode_text: str = ""
    z_stats: dict = field(default_factory=dict)
    issues: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)


@dataclass
class ProjectState:
    model: Optional[STLModel] = None
    knife: KnifeConfig = field(default_factory=KnifeConfig)
    sim: SimulationSettings = field(default_factory=SimulationSettings)
    table: TableConfig = field(default_factory=TableConfig)
    toolpath: List[ToolpathPoint] = field(default_factory=list)
    toolpath_points: List[ToolpathPoint] = field(default_factory=list)  # Keep a single shared list for toolpath.
    toolpath_result: Optional[ToolpathResult] = None  # Pipeline result (single source of truth).
    prepared_points: List[ToolpathPoint] = field(default_factory=list)
    prepared_meta: dict = field(default_factory=dict)
    a_path_2d: Optional[dict] = None  # Last 2D A-path result (for 3D attachment).
    a_applied_to_3d: bool = False  # Guard to prevent double-attach of A in 3D.
    gcode_text: str = ""  # Store generated G-code when explicitly requested.
    mesh_intersector_cache: MeshIntersectorCache = field(default_factory=MeshIntersectorCache)

    def clear_toolpath(self):
        self.toolpath.clear()
        self.toolpath_points.clear()
        self.toolpath_result = None
        self.prepared_points.clear()
        self.prepared_meta.clear()
        self.a_applied_to_3d = False
        self.gcode_text = ""

    def has_model(self):
        return self.model is not None and self.model.vertices is not None
