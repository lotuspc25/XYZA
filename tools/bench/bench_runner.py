import json
import platform
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional


@dataclass
class BenchmarkResult:
    name: str
    params: Dict[str, Any] = field(default_factory=dict)
    timings_ms: List[float] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "params": self.params,
            "timings_ms": self.timings_ms,
            "meta": self.meta,
        }


def run_benchmarks(
    selected: Optional[Iterable[str]] = None,
    repeats: int = 5,
    warmups: int = 1,
    output_json_path: Optional[str] = None,
    params: Optional[Dict[str, Any]] = None,
) -> List[BenchmarkResult]:
    from tools.bench import bench_scenarios

    bench_map = bench_scenarios.get_benchmarks()
    names = list(selected) if selected else sorted(bench_map.keys())
    params_dict = dict(params) if params else {}
    results: List[BenchmarkResult] = []
    for name in names:
        bench_fn = bench_map.get(name)
        if bench_fn is None:
            results.append(
                BenchmarkResult(
                    name=name,
                    params={},
                    timings_ms=[],
                    meta={"skipped": True, "reason": "unknown benchmark"},
                )
            )
            continue
        try:
            result = bench_fn(repeats=repeats, warmups=warmups, params=params_dict)
        except TypeError:
            result = bench_fn(repeats=repeats, warmups=warmups)
        if isinstance(result, (list, tuple)):
            results.extend(result)
        else:
            results.append(result)
    summarize_to_console(results)
    if output_json_path:
        write_json(results, output_json_path, params_dict)
    return results


def summarize_to_console(results: List[BenchmarkResult]) -> None:
    print("Benchmarks:")
    if not results:
        print("  (none)")
        return
    for result in results:
        params = result.params or {}
        param_text = ""
        if params:
            parts = [f"{k}={params[k]}" for k in sorted(params)]
            param_text = " (" + ", ".join(parts) + ")"
        if result.meta.get("skipped"):
            reason = result.meta.get("reason", "skipped")
            print(f"- {result.name}{param_text}: skipped ({reason})")
            continue
        if result.timings_ms:
            avg_ms = sum(result.timings_ms) / float(len(result.timings_ms))
            extra = ""
            if "cache_builds" in result.meta:
                extra = f", cache_builds={result.meta.get('cache_builds')}"
            print(
                f"- {result.name}{param_text}: {avg_ms:.2f} ms avg over "
                f"{len(result.timings_ms)} runs{extra}"
            )
        else:
            print(f"- {result.name}{param_text}: no timings")


def write_json(results: List[BenchmarkResult], path: str, params: Dict[str, Any]) -> None:
    payload = {
        "timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "params": params or {},
        "results": [r.to_dict() for r in results],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=False)
