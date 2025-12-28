import os
import shutil
import sys
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=None)
def get_app_dir() -> Path:
    """
    Returns the base directory of the app:
    - Frozen: directory of the executable (or _MEIPASS when available)
    - Dev: project root (two levels up from this file)
    """
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_path(relative: str) -> Path:
    """Resolve packaged resource path for both frozen and dev modes."""
    base = Path(sys._MEIPASS) if hasattr(sys, "_MEIPASS") else Path(__file__).resolve().parent.parent
    return (base / relative).resolve()


def get_user_config_dir() -> Path:
    """Location under %APPDATA% for user configs."""
    return Path(os.getenv("APPDATA", Path.home())) / "ZYZA"


@lru_cache(maxsize=None)
def find_or_create_config():
    """
    Returns (settings_path, tool_path), preferring portable (next to exe),
    then %APPDATA%/ZYZA, creating from defaults if missing.
    """
    app_dir = get_app_dir()
    portable_settings = app_dir / "settings.ini"
    portable_tool = app_dir / "tool.ini"

    user_dir = get_user_config_dir()
    user_dir.mkdir(parents=True, exist_ok=True)
    user_settings = user_dir / "settings.ini"
    user_tool = user_dir / "tool.ini"

    default_settings = resource_path("resources/default_settings.ini")
    default_tool = resource_path("resources/default_tool.ini")
    portable_default_settings = app_dir / "default_settings.ini"
    portable_default_tool = app_dir / "default_tool.ini"

    # Settings path resolution (prefer portable; copy defaults on first run)
    if portable_settings.exists():
        settings_path = portable_settings
    elif portable_default_settings.exists():
        shutil.copy(portable_default_settings, portable_settings)
        settings_path = portable_settings
    elif user_settings.exists():
        settings_path = user_settings
    else:
        target = user_settings
        if default_settings.exists():
            shutil.copy(default_settings, target)
        else:
            target.touch()
        settings_path = target

    # Tool path resolution
    if portable_tool.exists():
        tool_path = portable_tool
    elif portable_default_tool.exists():
        shutil.copy(portable_default_tool, portable_tool)
        tool_path = portable_tool
    elif user_tool.exists():
        tool_path = user_tool
    else:
        target = user_tool
        if default_tool.exists():
            shutil.copy(default_tool, target)
        else:
            target.touch()
        tool_path = target

    return settings_path, tool_path


def get_config_paths():
    """Alias for readability."""
    return find_or_create_config()
