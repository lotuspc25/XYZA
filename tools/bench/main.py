import argparse
import sys

from tools.bench import bench_scenarios
from tools.bench.bench_runner import run_benchmarks


def _parse_params(items, parser) -> dict:
    params = {}
    for raw in items or []:
        if "=" not in raw:
            parser.error(f"Invalid --param '{raw}'. Expected KEY=VALUE.")
        key, value = raw.split("=", 1)
        key = key.strip()
        if not key:
            parser.error(f"Invalid --param '{raw}'. Empty key.")
        params[key] = _coerce_value(value)
    return params


def _coerce_value(value: str):
    text = value.strip()
    lower = text.lower()
    if lower in ("true", "false"):
        return lower == "true"
    try:
        if lower.startswith("0") and len(lower) > 1 and lower[1].isdigit():
            raise ValueError
        return int(text)
    except Exception:
        pass
    try:
        return float(text)
    except Exception:
        return text


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Micro-benchmark runner")
    parser.add_argument("--list", action="store_true", help="List available benchmarks")
    parser.add_argument("--only", action="append", default=[], help="Run only named benchmark")
    parser.add_argument("--repeats", type=int, default=5, help="Repeat count per benchmark")
    parser.add_argument("--warmups", type=int, default=1, help="Warmup count per benchmark")
    parser.add_argument("--param", action="append", default=[], help="Benchmark param KEY=VALUE")
    parser.add_argument("--json", dest="json_path", default=None, help="Write JSON output to path")
    args = parser.parse_args(argv)

    if args.list:
        names = sorted(bench_scenarios.get_benchmarks().keys())
        for name in names:
            print(name)
        return 0

    params = _parse_params(args.param, parser)
    selected = args.only if args.only else None
    run_benchmarks(
        selected=selected,
        repeats=args.repeats,
        warmups=args.warmups,
        output_json_path=args.json_path,
        params=params,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
