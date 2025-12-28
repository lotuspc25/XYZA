from typing import List

from core.result import WarningItem, format_warning


def warnings_to_multiline_text(warnings: List[WarningItem]) -> str:
    if not warnings:
        return "No warnings."
    return "\n".join(f"{idx}. {format_warning(warning)}" for idx, warning in enumerate(warnings, 1))


def warnings_summary(warnings: List[WarningItem]) -> str:
    if not warnings:
        return ""
    codes = []
    for warning in warnings:
        if warning.code not in codes:
            codes.append(warning.code)
    return f"{len(warnings)} warnings: {', '.join(codes)}"
