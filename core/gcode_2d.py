from typing import Iterable, Sequence


def build_xya_gcode(
    points_xy: Iterable[Sequence[float]],
    angles_deg: Iterable[float],
    feed_rate: float = 2000.0,
    precision: int = 3,
) -> str:
    pts = list(points_xy or [])
    angs = list(angles_deg or [])
    count = min(len(pts), len(angs))
    if count <= 0:
        return ""
    precision = int(precision)
    if precision < 0:
        precision = 0
    fmt = f"{{:.{precision}f}}"
    lines = ["G21", "G90", "G17", f"F{fmt.format(float(feed_rate))}"]
    for i in range(count):
        pt = pts[i]
        x = float(pt[0])
        y = float(pt[1])
        a = float(angs[i])
        lines.append(f"G1 X{fmt.format(x)} Y{fmt.format(y)} A{fmt.format(a)}")
    return "\n".join(lines)
