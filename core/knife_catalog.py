from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class KnifeDef:
    id: str
    name: str
    kind: str
    thumbnail: str
    meta: str
    defaults: Dict[str, float]


def load_catalog() -> List[KnifeDef]:
    return [
        KnifeDef(
            id="TL-052",
            name="Scalpel 30deg",
            kind="scalpel_pointed",
            thumbnail="resources/knives/TL-052_256.png",
            meta="Edge 0.10mm | Body 0.50mm",
            defaults={
                "blade_thickness_mm": 0.10,
                "cut_length_mm": 12.0,
                "disk_thickness_mm": 1.0,
                "blade_length_mm": 50.0,
                "cutting_edge_diam_mm": 0.10,
                "body_diam_mm": 0.50,
                "knife_angle_deg": 0.0,
            },
        ),
        KnifeDef(
            id="TL-166",
            name="Scalpel Rounded",
            kind="scalpel_rounded",
            thumbnail="resources/knives/TL-166_256.png",
            meta="Edge 0.25mm | Body 1.00mm",
            defaults={
                "blade_thickness_mm": 0.12,
                "cut_length_mm": 10.0,
                "disk_thickness_mm": 1.0,
                "blade_length_mm": 40.0,
                "cutting_edge_diam_mm": 0.25,
                "body_diam_mm": 1.00,
                "knife_angle_deg": 0.0,
            },
        ),
        KnifeDef(
            id="TL-001",
            name="Rotary Disk",
            kind="rotary_disk",
            thumbnail="resources/knives/TL-001_256.png",
            meta="Disk 25mm | Thick 1.00mm",
            defaults={
                "blade_thickness_mm": 0.10,
                "cut_length_mm": 0.0,
                "disk_thickness_mm": 1.0,
                "blade_length_mm": 25.0,
                "cutting_edge_diam_mm": 25.0,
                "body_diam_mm": 3.00,
                "knife_angle_deg": 0.0,
            },
        ),
        KnifeDef(
            id="Z70",
            name="Straight Blade 70",
            kind="straight_blade",
            thumbnail="resources/knives/Z70_256.png",
            meta="Straight | 70mm",
            defaults={
                "blade_thickness_mm": 0.20,
                "cut_length_mm": 70.0,
                "disk_thickness_mm": 1.0,
                "blade_length_mm": 70.0,
                "cutting_edge_diam_mm": 0.20,
                "body_diam_mm": 0.50,
                "knife_angle_deg": 0.0,
            },
        ),
        KnifeDef(
            id="Z71",
            name="Straight Blade 71",
            kind="straight_blade",
            thumbnail="resources/knives/Z71_256.png",
            meta="Straight | 71mm",
            defaults={
                "blade_thickness_mm": 0.20,
                "cut_length_mm": 71.0,
                "disk_thickness_mm": 1.0,
                "blade_length_mm": 71.0,
                "cutting_edge_diam_mm": 0.20,
                "body_diam_mm": 0.50,
                "knife_angle_deg": 0.0,
            },
        ),
    ]
