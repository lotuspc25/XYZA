# toolpath_optimizer.py
# ----------------------
# Takım yolu iyileştirme (smoothing / temizleme) fonksiyonları için iskelet.
# Bu aşamada gerçek algoritmalar henüz uygulanmıyor; sadece yapı hazırlanıyor.

import math
from dataclasses import dataclass
from typing import Iterable, List, Tuple

from project_state import ToolpathPoint  # Use shared ToolpathPoint model (single source).


@dataclass
class OptimizeSettings:
    """Otomatik yol iyileştirme seçenekleri."""

    smooth_a: bool = True              # A eksenini yumuşat
    smooth_z: bool = True              # Z eğrisini yumuşat
    clean_micro_segments: bool = True  # Çok kısa mikro segmentleri temizle
    adaptive_resample: bool = True     # Eğriliğe göre adaptif örnekleme
    round_corners: bool = True         # Keskin köşeleri yaylara çevir
    fix_loops: bool = True             # küçük loop/spike temizleme
    flatten_waviness: bool = True      # XY ondülasyon smoothing
    fix_jitter: bool = True            # Zigzag / jitter düzeltme


@dataclass
class OptimizationStats:
    points_count: int
    path_length_mm: float
    max_a_jump_deg: float


@dataclass
class OptimizationReport:
    before: OptimizationStats
    after: OptimizationStats
    applied_steps: List[str]

    def as_text(self) -> str:
        lines: List[str] = []
        lines.append("Önce / Sonra karşılaştırması:")
        lines.append(
            f"- Nokta sayısı: {self.before.points_count} → {self.after.points_count}"
        )
        lines.append(
            f"- Yol uzunluğu: {self.before.path_length_mm:.3f} mm → {self.after.path_length_mm:.3f} mm"
        )
        lines.append(
            f"- Maks A sıçraması: {self.before.max_a_jump_deg:.2f}° → {self.after.max_a_jump_deg:.2f}°"
        )
        lines.append("")
        if self.applied_steps:
            lines.append("Uygulanan adımlar:")
            for s in self.applied_steps:
                lines.append(f"- {s}")
        else:
            lines.append("Herhangi bir otomatik iyileştirme adımı uygulanmadı.")
        return "\n".join(lines)


def _compute_stats(points: List[ToolpathPoint]) -> "OptimizationStats":
    if not points:
        return OptimizationStats(0, 0.0, 0.0)

    length = 0.0
    max_jump = 0.0
    for i in range(1, len(points)):
        p0 = points[i - 1]
        p1 = points[i]
        dx = p1.x - p0.x
        dy = p1.y - p0.y
        dz = p1.z - p0.z
        length += math.sqrt(dx * dx + dy * dy + dz * dz)
        da = abs(p1.a - p0.a)
        if da > max_jump:
            max_jump = da

    return OptimizationStats(
        points_count=len(points),
        path_length_mm=length,
        max_a_jump_deg=max_jump,
    )


def _wrap_angle_deg(angle: float) -> float:
    """Açıyı [-180, 180) aralığına sar."""
    return (angle + 180.0) % 360.0 - 180.0


def _unwrap_angles_deg(angles: Iterable[float]) -> List[float]:
    """
    Ardışık açıları unwrap ederek süreklilik sağlar.
    Örn: 179, -179, -178 -> 179, 181, 182 gibi.
    """
    angles = list(angles)
    if not angles:
        return []

    unwrapped = [angles[0]]
    for a in angles[1:]:
        prev = unwrapped[-1]
        delta = (a - prev + 180.0) % 360.0 - 180.0  # [-180, 180) fark
        unwrapped.append(prev + delta)
    return unwrapped


def _moving_average(values: List[float], window: int) -> List[float]:
    """
    Basit hareketli ortalama filtresi.
    Kenarlarda pencere küçültülür (merkezli smoothing).
    """
    n = len(values)
    if n == 0 or window <= 1:
        return list(values)

    half = window // 2
    smoothed: List[float] = []
    for i in range(n):
        start = max(0, i - half)
        end = min(n, i + half + 1)
        segment = values[start:end]
        smoothed.append(sum(segment) / len(segment))
    return smoothed


def smooth_a_angles(points: List[ToolpathPoint], window: int = 7) -> List[ToolpathPoint]:
    """
    A ekseni açılarını yumuşatır.

    Adımlar:
      - A listesini al
      - unwrap ederek süreklilik sağla
      - hareketli ortalama uygula
      - sonuçları tekrar [-180, 180) aralığına wrap et
      - Yeni ToolpathPoint listesi döndür (X, Y, Z aynı kalır, sadece A değişir)
    """
    if not points or window <= 1:
        return list(points)

    a_list = [p.a for p in points]
    unwrapped = _unwrap_angles_deg(a_list)
    smoothed_unwrapped = _moving_average(unwrapped, window)
    smoothed_wrapped = [_wrap_angle_deg(a) for a in smoothed_unwrapped]

    new_points: List[ToolpathPoint] = []
    for p, a in zip(points, smoothed_wrapped):
        new_points.append(ToolpathPoint(x=p.x, y=p.y, z=p.z, a=a))

    return new_points


def smooth_z_values(
    points: List[ToolpathPoint],
    window: int = 7,
    preserve_threshold: float = 3.0,
) -> List[ToolpathPoint]:
    """
    Z ekseni değerlerini yumuşatır.

    - Küçük titreşimleri (±1–2 mm) azaltır.
    - Çok büyük seviye değişimlerinde (ör. > preserve_threshold)
      orijinal Z değerine daha yakın kalır.
    """
    if not points or window <= 1:
        return list(points)

    z_list = [p.z for p in points]
    z_smooth = _moving_average(z_list, window)

    new_points: List[ToolpathPoint] = []
    for p, z_orig, z_sm in zip(points, z_list, z_smooth):
        dz = abs(z_sm - z_orig)
        if dz <= preserve_threshold:
            z_final = z_sm
        else:
            alpha = 0.3  # büyük sıçramalarda orijinale daha yakın kal
            z_final = (1.0 - alpha) * z_orig + alpha * z_sm

        new_points.append(ToolpathPoint(x=p.x, y=p.y, z=z_final, a=p.a))

    return new_points


def remove_micro_segments(
    points: List[ToolpathPoint],
    min_dist: float = 0.05,
) -> List[ToolpathPoint]:
    """
    Birbirine çok yakın (min_dist'ten kısa) ardışık nokta segmentlerini temizler.

    - min_dist birim: mm (3B Öklid mesafesi, X/Y/Z birlikte düşünülür).
    - Yolun genel şekli korunur, sadece üst üste binen çok küçük adımlar atılır.
    """
    if not points or len(points) < 2:
        return list(points)

    kept: List[ToolpathPoint] = [points[0]]
    last = points[0]

    for p in points[1:]:
        dx = p.x - last.x
        dy = p.y - last.y
        dz = p.z - last.z
        dist = math.sqrt(dx * dx + dy * dy + dz * dz)
        if dist >= min_dist:
            kept.append(p)
            last = p
        # else: mikro segment atla

    if len(kept) < 2:
        return list(points)

    return kept


def _segment_xy_length(p0: ToolpathPoint, p1: ToolpathPoint) -> float:
    """XY düzlemindeki segment uzunluğunu döndürür (mm)."""
    dx = p1.x - p0.x
    dy = p1.y - p0.y
    return math.hypot(dx, dy)


def _dist3(p0: ToolpathPoint, p1: ToolpathPoint) -> float:
    """3B Öklidyen mesafeyi döndürür."""
    dx = p1.x - p0.x
    dy = p1.y - p0.y
    dz = p1.z - p0.z
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def _xy_turn_angle(prev_p: ToolpathPoint, p: ToolpathPoint, next_p: ToolpathPoint) -> float:
    """
    Returns the turning angle in degrees between segments (prev->p) and (p->next) in XY plane.
    0 deg means straight, larger angle means sharper turn.
    """
    v1x = p.x - prev_p.x
    v1y = p.y - prev_p.y
    v2x = next_p.x - p.x
    v2y = next_p.y - p.y

    n1 = math.hypot(v1x, v1y)
    n2 = math.hypot(v2x, v2y)
    if n1 < 1e-6 or n2 < 1e-6:
        return 0.0

    dot = (v1x * v2x + v1y * v2y) / (n1 * n2)
    dot = max(-1.0, min(1.0, dot))
    return math.degrees(math.acos(dot))


def _xy_signed_turn_angle(prev_p: ToolpathPoint, p: ToolpathPoint, next_p: ToolpathPoint) -> float:
    """
    XY düzleminde (prev->p) ve (p->next) vektörleri arasındaki işaretli dönüş açısını verir.
    Pozitif: sola dönüş, negatif: sağa dönüş, derece cinsinden (-180..180).
    """
    v1x = p.x - prev_p.x
    v1y = p.y - prev_p.y
    v2x = next_p.x - p.x
    v2y = next_p.y - p.y

    n1 = math.hypot(v1x, v1y)
    n2 = math.hypot(v2x, v2y)
    if n1 < 1e-6 or n2 < 1e-6:
        return 0.0

    # Dot / cross ile işaretli açı
    dot = (v1x * v2x + v1y * v2y) / (n1 * n2)
    dot = max(-1.0, min(1.0, dot))
    unsigned = math.acos(dot)

    cross = v1x * v2y - v1y * v2x  # z-bileşeni
    sign = 1.0 if cross >= 0.0 else -1.0
    return math.degrees(unsigned) * sign


def adaptive_resample(
    points: List[ToolpathPoint],
    low_factor: float = 0.5,
    high_factor: float = 2.0,
) -> List[ToolpathPoint]:
    """
    Curvature-aware resampling:
      - In low-curvature (almost straight) regions, target spacing is larger
        (we can drop more points).
      - In high-curvature regions, target spacing is smaller (keep more points).

    low_factor  -> multiplier for spacing at high curvature (smaller spacing).
    high_factor -> multiplier for spacing at low curvature (larger spacing).
    """
    if not points or len(points) < 3:
        return list(points)

    total_dist = 0.0
    for i in range(1, len(points)):
        p0 = points[i - 1]
        p1 = points[i]
        dx = p1.x - p0.x
        dy = p1.y - p0.y
        dz = p1.z - p0.z
        total_dist += math.sqrt(dx * dx + dy * dy + dz * dz)

    avg_dist = total_dist / max(1, len(points) - 1)
    if avg_dist <= 0.0:
        return list(points)

    low_factor = max(0.1, float(low_factor))
    high_factor = max(low_factor, float(high_factor))

    kept: List[ToolpathPoint] = [points[0]]
    last_keep_index = 0
    last_keep_point = points[0]

    n = len(points)
    for i in range(1, n - 1):
        prev_p = points[i - 1]
        p = points[i]
        next_p = points[i + 1]

        dx = p.x - last_keep_point.x
        dy = p.y - last_keep_point.y
        dz = p.z - last_keep_point.z
        dist_since_keep = math.sqrt(dx * dx + dy * dy + dz * dz)

        ang = _xy_turn_angle(prev_p, p, next_p)  # 0..180 deg
        t = min(ang, 90.0) / 90.0  # 0: straight, 1: strong turn

        target_spacing = avg_dist * (
            low_factor + (1.0 - t) * (high_factor - low_factor)
        )

        if dist_since_keep >= target_spacing:
            kept.append(p)
            last_keep_point = p
            last_keep_index = i

    if last_keep_index != n - 1:
        kept.append(points[-1])

    if len(kept) < 2:
        return list(points)

    return kept


def fix_loops_and_spikes(
    points: List[ToolpathPoint],
    spike_angle_deg: float = 150.0,
    spike_max_len: float = 0.30,
    loop_window: int = 40,
    loop_close_dist: float = 0.50,
    loop_min_perimeter: float = 0.50,
    loop_max_perimeter: float = 10.0,
) -> List[ToolpathPoint]:
    """
    Küçük loop (girdap) ve çok sert, kısa spike geri dönüşlerini temizler.

    - Spike:
        p[i-1] -> p[i] -> p[i+1] üçlüsünde:
          * XY açı > spike_angle_deg (neredeyse geri dönüş)
          * Her iki segment de spike_max_len'den kısa
        ise p[i] (ve bazen p[i+1]) kaldırılır.
    - Loop:
        Kısa bir pencere içinde (loop_window),
        başlangıç ve bitiş noktaları XY'de loop_close_dist'ten yakın,
        fakat aradaki yol uzunluğu loop_min_perimeter..loop_max_perimeter
        arasındaysa: aradaki noktalar kaldırılır, sadece uçlar bırakılır.

    Not: Bu fonksiyon sadece küçük ve lokal bozuklukları hedefler.
    Büyük topolojik değişiklikler yapmaz.
    """
    n = len(points)
    if n < 3:
        return list(points)

    # -----------------------------
    # 1) Spike temizleme (yerel ters dönüşler)
    # -----------------------------
    spike_filtered: List[ToolpathPoint] = [points[0]]
    i = 1
    while i < n - 1:
        p_prev = spike_filtered[-1]
        p_curr = points[i]
        p_next = points[i + 1]

        ang = _xy_turn_angle(p_prev, p_curr, p_next)
        len1 = _segment_xy_length(p_prev, p_curr)
        len2 = _segment_xy_length(p_curr, p_next)

        if ang >= spike_angle_deg and len1 <= spike_max_len and len2 <= spike_max_len:
            # p_curr noktasını atla (spike gövdesi)
            # Biraz daha agresif olmak için p_next'i de atlamayı deneyebiliriz;
            # şimdilik sadece p_curr'ü atlıyoruz ve döngüyü p_next ile devam ettiriyoruz.
            i += 1
            continue
        else:
            spike_filtered.append(p_curr)
            i += 1

    # Son noktayı ekle
    spike_filtered.append(points[-1])

    if len(spike_filtered) < 3:
        return spike_filtered

    # -----------------------------
    # 2) Küçük loop (girdap) temizleme
    # -----------------------------
    cleaned: List[ToolpathPoint] = []
    i = 0
    m = len(spike_filtered)

    while i < m:
        cleaned.append(spike_filtered[i])

        # Loop aramaya uygun mu?
        # i sabitken, sonraki birkaç noktaya bak.
        loop_found = False
        max_j = min(m - 1, i + loop_window)

        for j in range(i + 3, max_j + 1):
            p_start = spike_filtered[i]
            p_end = spike_filtered[j]

            # Uçlar XY'de birbirine yeterince yakın mı?
            close_xy = _segment_xy_length(p_start, p_end)
            if close_xy > loop_close_dist:
                continue

            # Aradaki yol uzunluğunu hesapla
            perim = 0.0
            for k in range(i, j):
                perim += _segment_xy_length(spike_filtered[k], spike_filtered[k + 1])

            if loop_min_perimeter <= perim <= loop_max_perimeter:
                # i..j arasındaki küçük girdapı kaldır:
                # i zaten cleaned'e eklendi, i+1..j-1 atlanıyor.
                # j noktasını bir sonraki adımda cleaned'e ekleyeceğiz.
                cleaned.append(p_end)
                i = j  # döngü j'den devam etsin
                loop_found = True
                break

        if not loop_found:
            i += 1

    if len(cleaned) < 2:
        return spike_filtered

    return cleaned


def fix_zigzag_jitter(
    points: List[ToolpathPoint],
    angle_threshold: float = 20.0,
    max_segment: float = 0.5,
) -> List[ToolpathPoint]:
    """
    Küçük zigzag / jitter efektlerini temizler.

    Fikir:
      - Üçlüler halinde bak: prev, curr, next.
      - Eğer prev->curr ve curr->next segmentleri çok kısa ise (max_segment'ten küçük),
        ve işaretli dönüş açısı belirli bir eşikten büyük ise (sağa/sola ani küçük kırılma),
        curr noktasını atarak zigzag'ı düzleştir.
      - remove_loops_and_spikes'ye göre daha lokal, küçük açı/jitter odaklı çalışır.
    """
    n = len(points)
    if n < 3:
        return list(points)

    result: List[ToolpathPoint] = [points[0]]
    i = 1
    while i < n - 1:
        prev_p = result[-1]
        curr_p = points[i]
        next_p = points[i + 1]

        d1 = _dist3(prev_p, curr_p)
        d2 = _dist3(curr_p, next_p)

        # Sadece kısa segmentlerle ilgilen
        if d1 < max_segment and d2 < max_segment:
            # İşaretli açı: sağ/sol kırılmayı ölç
            ang_signed = _xy_signed_turn_angle(prev_p, curr_p, next_p)
            ang_abs = abs(ang_signed)

            # Küçük ama belirgin bir zigzag ise: curr'ı atla
            if angle_threshold <= ang_abs <= 120.0:
                # curr'ı eklemeden atla, bir sonraki noktaya geç
                i += 1
                continue

        # Normal durumda curr'ı koru
        result.append(curr_p)
        i += 1

    # Son noktayı her zaman koru
    if result[-1] is not points[-1]:
        result.append(points[-1])

    if len(result) < 2:
        return list(points)

    return result


def smooth_xy_waviness(
    points: List[ToolpathPoint],
    window: int = 11,
    corner_angle_deg: float = 30.0,
    max_blend: float = 0.8,
) -> List[ToolpathPoint]:
    """
    XY düzleminde orta frekanslı ondülasyonları yumuşatır.

    Fikir:
      - X ve Y için ayrı ayrı global hareketli ortalama uygula (window uzun).
      - Her nokta için yerel dönme açısını (curvature) hesapla:
          * Düz bölgelerde (küçük açı) smoothing'i güçlü uygula.
          * Keskin köşelerde (büyük açı) smoothing'i azalt veya neredeyse kapat.
      - Z ve A, optimize pipeline'ın önceki adımlarında zaten yumuşatılmış kabul edilir;
        burada Z/A'yı değiştirmiyoruz, sadece XY'yi düzlüyoruz.
    """
    n = len(points)
    if n == 0 or n < 3 or window <= 1:
        return list(points)

    # Orijinal koordinat dizileri
    xs = [p.x for p in points]
    ys = [p.y for p in points]

    # Global moving average ile smooth X/Y
    sx = _moving_average(xs, window)
    sy = _moving_average(ys, window)

    # Her nokta için XY turn angle hesapla (0..180)
    angles: List[float] = [0.0] * n
    for i in range(1, n - 1):
        angles[i] = _xy_turn_angle(points[i - 1], points[i], points[i + 1])
    angles[0] = angles[1] if n > 1 else 0.0
    angles[-1] = angles[-2] if n > 1 else 0.0

    corner_angle_deg = max(1.0, float(corner_angle_deg))
    max_blend = max(0.0, min(1.0, float(max_blend)))

    new_points: List[ToolpathPoint] = []
    for i, (p, ax, ay, ang) in enumerate(zip(points, sx, sy, angles)):
        # 0 deg: düz,  corner_angle_deg ve üstü: köşe.
        # Düzde daha çok smoothing, köşede daha az.
        t = min(ang, corner_angle_deg) / corner_angle_deg  # 0: düz, 1: köşe
        smooth_factor = (1.0 - t) * max_blend  # düzde max_blend, köşede ~0

        if smooth_factor <= 0.0:
            # Köşe: orijinal nokta
            new_points.append(p)
        else:
            # Orijinal ile smoothed koordinatlar arasında interpolate et
            nx = (1.0 - smooth_factor) * p.x + smooth_factor * ax
            ny = (1.0 - smooth_factor) * p.y + smooth_factor * ay

            new_points.append(
                ToolpathPoint(
                    x=nx,
                    y=ny,
                    z=p.z,  # Z/A daha önceki smoothing adımlarından geliyor
                    a=p.a,
                )
            )

    return new_points


def round_corners(
    points: List[ToolpathPoint],
    corner_angle_deg: float = 40.0,
    samples_per_corner: int = 4,
) -> List[ToolpathPoint]:
    """
    XY düzleminde keskin dönüş yapan köşeleri quadratic Bezier ile yuvarlar.
    """
    if not points or len(points) < 3:
        return list(points)

    n = len(points)
    result: List[ToolpathPoint] = [points[0]]

    for i in range(1, n - 1):
        p0 = points[i - 1]
        p1 = points[i]
        p2 = points[i + 1]

        ang = _xy_turn_angle(p0, p1, p2)

        if ang < corner_angle_deg and samples_per_corner > 0:
            for j in range(1, samples_per_corner + 1):
                t = j / float(samples_per_corner + 1)
                one_minus_t = 1.0 - t

                bx = one_minus_t * one_minus_t * p0.x + 2.0 * one_minus_t * t * p1.x + t * t * p2.x
                by = one_minus_t * one_minus_t * p0.y + 2.0 * one_minus_t * t * p1.y + t * t * p2.y
                bz = one_minus_t * one_minus_t * p0.z + 2.0 * one_minus_t * t * p1.z + t * t * p2.z

                ba = one_minus_t * p0.a + t * p2.a

                result.append(ToolpathPoint(x=bx, y=by, z=bz, a=ba))
        else:
            result.append(p1)

    result.append(points[-1])

    if len(result) < 2:
        return list(points)

    return result


def optimize_all(
    points: List[ToolpathPoint],
    settings: OptimizeSettings,
) -> Tuple[List[ToolpathPoint], OptimizationReport]:
    """
    Verilen takım yolunu OptimizeSettings'e göre iyileştirir ve rapor döndürür.
    """
    if not points:
        empty_report = OptimizationReport(
            before=_compute_stats([]),
            after=_compute_stats([]),
            applied_steps=[],
        )
        return [], empty_report

    original: List[ToolpathPoint] = list(points)
    current: List[ToolpathPoint] = list(points)
    applied_steps: List[str] = []

    if settings.smooth_a:
        current = smooth_a_angles(current, window=7)
        applied_steps.append("smooth_a_angles")

    if settings.smooth_z:
        current = smooth_z_values(
            current,
            window=7,
            preserve_threshold=3.0,
        )
        applied_steps.append("smooth_z_values")

    if settings.clean_micro_segments:
        current = remove_micro_segments(
            current,
            min_dist=0.05,
        )
        applied_steps.append("remove_micro_segments")

    if settings.fix_loops:
        current = fix_loops_and_spikes(
            current,
            spike_angle_deg=150.0,
            spike_max_len=0.30,
            loop_window=40,
            loop_close_dist=0.50,
            loop_min_perimeter=0.50,
            loop_max_perimeter=10.0,
        )
        applied_steps.append("fix_loops_and_spikes")

    if settings.flatten_waviness:
        current = smooth_xy_waviness(
            current,
            window=11,
            corner_angle_deg=30.0,
            max_blend=0.8,
        )
        applied_steps.append("smooth_xy_waviness")

    if settings.fix_jitter:
        current = fix_zigzag_jitter(
            current,
            angle_threshold=20.0,
            max_segment=0.5,
        )
        applied_steps.append("fix_zigzag_jitter")

    if settings.adaptive_resample:
        current = adaptive_resample(
            current,
            low_factor=0.5,
            high_factor=2.0,
        )
        applied_steps.append("adaptive_resample")

    if settings.round_corners:
        current = round_corners(
            current,
            corner_angle_deg=40.0,
            samples_per_corner=4,
        )
        applied_steps.append("round_corners")

    report = OptimizationReport(
        before=_compute_stats(original),
        after=_compute_stats(current),
        applied_steps=applied_steps,
    )
    return current, report
