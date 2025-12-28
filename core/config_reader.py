import configparser
from typing import Any, Callable, List, Optional, Set

from core.result import WarningItem


def _append_warning(
    warnings_out: Optional[List[WarningItem]],
    code: str,
    message: str,
    context: dict,
) -> None:
    if warnings_out is None:
        return
    warnings_out.append(WarningItem(code=code, message=message, context=context))


def get_cfg_value(
    cfg: configparser.ConfigParser,
    section: str,
    option: str,
    getter: Callable[..., Any],
    fallback: Any,
    warnings_out: Optional[List[WarningItem]] = None,
    missing_sections: Optional[Set[str]] = None,
) -> Any:
    if missing_sections is None:
        missing_sections = set()
    if not cfg.has_section(section):
        if section not in missing_sections:
            _append_warning(
                warnings_out,
                code="settings.missing_section",
                message=f"Missing section [{section}]; using defaults.",
                context={"section": section},
            )
            missing_sections.add(section)
        return fallback
    if not cfg.has_option(section, option):
        _append_warning(
            warnings_out,
            code="settings.missing_option",
            message=f"Missing option {section}.{option}; using default.",
            context={"section": section, "option": option},
        )
        return fallback
    try:
        return getter(section, option, fallback=fallback)
    except (ValueError, configparser.Error) as exc:
        raw_value = None
        try:
            raw_value = cfg.get(section, option)
        except configparser.Error:
            raw_value = None
        _append_warning(
            warnings_out,
            code="settings.invalid_value",
            message=f"Invalid value for {section}.{option}; using default.",
            context={"section": section, "option": option, "value": raw_value, "error": str(exc)},
        )
        return fallback
