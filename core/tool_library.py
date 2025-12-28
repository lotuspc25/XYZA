import configparser
import os
from typing import Dict, List, Optional


_NUMERIC_KEYS = {
    "knife_angle_deg",
    "blade_thickness_mm",
    "cut_length_mm",
    "disk_thickness_mm",
    "blade_length_mm",
    "cutting_edge_diam_mm",
    "body_diam_mm",
}


def _tool_section(tool_no: int) -> str:
    return f"Tool:{int(tool_no)}"


def load_active_tool_no(settings_ini_path: str) -> int:
    cfg = configparser.ConfigParser()
    if os.path.exists(settings_ini_path):
        cfg.read(settings_ini_path, encoding="utf-8")
    if cfg.has_option("Knife", "active_tool_no"):
        try:
            value = int(cfg.get("Knife", "active_tool_no"))
            return value if value > 0 else 1
        except (ValueError, configparser.Error):
            return 1
    return 1


def save_active_tool_no(settings_ini_path: str, tool_no: int) -> None:
    cfg = configparser.ConfigParser()
    if os.path.exists(settings_ini_path):
        cfg.read(settings_ini_path, encoding="utf-8")
    if "Knife" not in cfg:
        cfg["Knife"] = {}
    cfg["Knife"]["active_tool_no"] = str(int(tool_no))
    with open(settings_ini_path, "w", encoding="utf-8") as f:
        cfg.write(f)


def load_tool(tool_ini_path: str, tool_no: int) -> Optional[Dict[str, object]]:
    if not os.path.exists(tool_ini_path):
        return None
    cfg = configparser.ConfigParser()
    cfg.read(tool_ini_path, encoding="utf-8")
    section = _tool_section(tool_no)
    if not cfg.has_section(section):
        return None
    data: Dict[str, object] = {}
    for key, value in cfg.items(section):
        if key in _NUMERIC_KEYS:
            try:
                data[key] = float(value)
            except (ValueError, TypeError):
                continue
        else:
            data[key] = value
    return data


def save_tool(tool_ini_path: str, tool_no: int, tool_dict: Dict[str, object]) -> None:
    cfg = configparser.ConfigParser()
    if os.path.exists(tool_ini_path):
        cfg.read(tool_ini_path, encoding="utf-8")
    section = _tool_section(tool_no)
    if section not in cfg:
        cfg[section] = {}
    sec = cfg[section]
    for key, value in (tool_dict or {}).items():
        if key in _NUMERIC_KEYS:
            try:
                sec[key] = f"{float(value):.3f}"
            except (ValueError, TypeError):
                continue
        else:
            sec[key] = str(value)
    with open(tool_ini_path, "w", encoding="utf-8") as f:
        cfg.write(f)


def list_tools(tool_ini_path: str) -> List[int]:
    if not os.path.exists(tool_ini_path):
        return []
    cfg = configparser.ConfigParser()
    cfg.read(tool_ini_path, encoding="utf-8")
    tools: List[int] = []
    for section in cfg.sections():
        if section.lower().startswith("tool:"):
            try:
                tools.append(int(section.split(":", 1)[1]))
            except (ValueError, IndexError):
                continue
    return sorted(set(t for t in tools if t > 0))
