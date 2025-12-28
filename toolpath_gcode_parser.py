import math
from dataclasses import dataclass
from typing import List, Optional

from core.result import WarningItem


@dataclass
class GcodeSegment:
    type: str  # RAPID / FEED / ARC_CW / ARC_CCW
    start: tuple
    end: tuple
    i: Optional[float] = None
    j: Optional[float] = None
    feed: Optional[float] = None
    line_no: int = 0
    raw: str = ""


def _append_warning(warnings_out: Optional[List[WarningItem]], code: str, message: str, context: dict) -> None:
    if warnings_out is None:
        return
    warnings_out.append(WarningItem(code=code, message=message, context=context))


def _parse_words(line: str, line_no: int, raw: str, warnings_out: Optional[List[WarningItem]]):
    words = {}
    buf = ""
    key = None
    for ch in line:
        if ch.isalpha():
            if key is not None and buf:
                try:
                    words[key] = float(buf)
                except ValueError:
                    _append_warning(
                        warnings_out,
                        code="gcode.invalid_number",
                        message="Invalid numeric value while parsing word.",
                        context={"line_no": line_no, "raw": raw.strip(), "token": f"{key}{buf}"},
                    )
            key = ch.upper()
            buf = ""
        elif ch in "+-.0123456789":
            buf += ch
        else:
            if key is not None and buf:
                try:
                    words[key] = float(buf)
                except ValueError:
                    _append_warning(
                        warnings_out,
                        code="gcode.invalid_number",
                        message="Invalid numeric value while parsing word.",
                        context={"line_no": line_no, "raw": raw.strip(), "token": f"{key}{buf}"},
                    )
                key = None
                buf = ""
    if key is not None and buf:
        try:
            words[key] = float(buf)
        except ValueError:
            _append_warning(
                warnings_out,
                code="gcode.invalid_number",
                message="Invalid numeric value while parsing word.",
                context={"line_no": line_no, "raw": raw.strip(), "token": f"{key}{buf}"},
            )
    return words


def parse_gcode(text: str, warnings_out: Optional[List[WarningItem]] = None) -> List[GcodeSegment]:
    segs: List[GcodeSegment] = []
    if not text:
        return segs

    modal = {"G": 0, "F": None, "X": 0.0, "Y": 0.0, "Z": 0.0, "A": None, "UNITS": "MM", "ABS": True}

    for idx, raw in enumerate(text.splitlines(), 1):
        stripped = raw.split(";")[0].split("(")[0].strip()
        if not stripped:
            continue
        words = _parse_words(stripped, idx, raw, warnings_out)
        if "G" in words:
            try:
                gcode = int(words["G"])
            except (ValueError, KeyError, IndexError, TypeError):
                _append_warning(
                    warnings_out,
                    code="gcode.invalid_g",
                    message="Invalid G-code value; line skipped.",
                    context={"line_no": idx, "raw": raw.strip(), "value": words.get("G")},
                )
                continue
            if gcode in (0, 1, 2, 3):
                modal["G"] = gcode
            elif gcode == 20:
                modal["UNITS"] = "IN"
            elif gcode == 21:
                modal["UNITS"] = "MM"
            elif gcode == 90:
                modal["ABS"] = True
            elif gcode == 91:
                modal["ABS"] = False
            else:
                continue
        if "F" in words:
            modal["F"] = words["F"]

        target = {
            "X": modal["X"],
            "Y": modal["Y"],
            "Z": modal["Z"],
            "A": modal["A"],
        }
        for ax in ("X", "Y", "Z", "A"):
            if ax in words:
                try:
                    if modal["ABS"]:
                        target[ax] = words[ax]
                    else:
                        target[ax] += words[ax]
                except (ValueError, KeyError, IndexError, TypeError):
                    _append_warning(
                        warnings_out,
                        code="gcode.invalid_axis",
                        message="Invalid axis value; using previous value.",
                        context={"line_no": idx, "raw": raw.strip(), "axis": ax, "value": words.get(ax)},
                    )

        cur = (modal["X"], modal["Y"], modal["Z"], modal["A"])
        nxt = (target["X"], target["Y"], target["Z"], target["A"])

        mode = modal["G"]
        if mode == 0:
            seg_type = "RAPID"
        elif mode == 1:
            seg_type = "FEED"
        elif mode == 2:
            seg_type = "ARC_CW"
        elif mode == 3:
            seg_type = "ARC_CCW"
        else:
            seg_type = None

        if seg_type:
            seg = GcodeSegment(
                type=seg_type,
                start=cur,
                end=nxt,
                i=words.get("I"),
                j=words.get("J"),
                feed=modal["F"],
                line_no=idx,
                raw=raw.strip(),
            )
            segs.append(seg)

        modal["X"], modal["Y"], modal["Z"], modal["A"] = nxt

    return segs
