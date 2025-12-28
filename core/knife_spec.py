import configparser
import os
from typing import Dict, Optional

from core.path_utils import find_or_create_config

INI_PATH = str(find_or_create_config()[0])


def normalize_profile(profile: Optional[str], name: Optional[str] = None) -> str:
    value = (profile or "").strip().lower()
    if not value:
        needle = (name or "").strip().lower()
        if "d\u00f6ner" in needle or "doner" in needle or "disk" in needle:
            return "rotary_disk"
        if "yuvarlak" in needle or "rounded" in needle:
            return "scalpel_rounded"
        return "scalpel_pointed"
    if value in ("scalpel", "scalpelpointed", "scalpel_pointed", "pointed"):
        return "scalpel_pointed"
    if value in ("scalpelrounded", "scalpel_rounded", "rounded"):
        return "scalpel_rounded"
    if value in ("rotarydisk", "rotary_disk", "disk", "rotary", "doner", "d\u00f6ner"):
        return "rotary_disk"
    return value


def build_knife_spec(
    name: str,
    length_mm: float,
    tip_diameter_mm: float,
    body_diameter_mm: float,
    a0_deg: float,
    profile: Optional[str] = None,
) -> Dict[str, float]:
    norm_profile = normalize_profile(profile, name)
    return {
        "name": name or "",
        "profile": norm_profile,
        "length_mm": float(length_mm),
        "tip_diameter_mm": float(tip_diameter_mm),
        "body_diameter_mm": float(body_diameter_mm),
        "a0_deg": float(a0_deg),
    }


def load_knife_spec(cfg_path: str = INI_PATH) -> Dict[str, float]:
    cfg = configparser.ConfigParser()
    if os.path.exists(cfg_path):
        cfg.read(cfg_path, encoding="utf-8")

    knives_sec = cfg["KNIVES"] if "KNIVES" in cfg else {}
    current = knives_sec.get("current", "") or "Varsayilan Bicak"
    sect_name = f"KNIFE_{current}"
    ksec = cfg[sect_name] if sect_name in cfg else {}

    length_mm = float(ksec.get("length_mm", 30.0))
    tip_diameter_mm = float(ksec.get("tip_diameter_mm", 2.0))
    body_diameter_mm = float(ksec.get("body_diameter_mm", 6.0))
    a0_deg = float(ksec.get("angle_deg", 0.0))
    profile = ksec.get("profile", "")

    return build_knife_spec(
        current,
        length_mm,
        tip_diameter_mm,
        body_diameter_mm,
        a0_deg,
        profile=profile,
    )
