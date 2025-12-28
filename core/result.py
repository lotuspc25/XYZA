from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Generic, List, Optional, TypeVar


T = TypeVar("T")


@dataclass
class WarningItem:
    code: str
    message: str
    context: Dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.context is None:
            self.context = {}

    def to_text(self) -> str:
        return format_warning(self)


def format_warning(warning: WarningItem) -> str:
    context = warning.context or {}
    if context:
        items = ", ".join(f"{key}={value}" for key, value in sorted(context.items()))
        return f"{warning.code}: {warning.message} ({items})"
    return f"{warning.code}: {warning.message}"


@dataclass
class Result(Generic[T]):
    ok: bool
    data: Optional[T] = None
    warnings: List[WarningItem] = field(default_factory=list)
    error: Optional[Exception] = None

    @classmethod
    def ok(cls, data: T, warnings: Optional[List[WarningItem]] = None) -> "Result[T]":
        return cls(ok=True, data=data, warnings=warnings or [], error=None)

    @classmethod
    def fail(cls, error: Exception, warnings: Optional[List[WarningItem]] = None) -> "Result[T]":
        return cls(ok=False, data=None, warnings=warnings or [], error=error)

    def merge_warnings(self, other_warnings: Optional[List[WarningItem]]) -> None:
        if not other_warnings:
            return
        if self.warnings is None:
            self.warnings = []
        self.warnings.extend(other_warnings)
