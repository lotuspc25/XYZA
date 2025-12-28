import argparse
import json
import os
import sys
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple

REPLACEMENT_CHAR = "\uFFFD"
REPLACEMENT_THRESHOLD = 3
SUSPICIOUS_SUBSTRINGS = ["�╗┐", "Ã", "Å", "Ä", "Â", REPLACEMENT_CHAR]
TURKISH_LETTERS = set("çğıöşüÇĞİÖŞÜ")

INCLUDE_EXTENSIONS = {
    ".py",
    ".md",
    ".txt",
    ".ini",
    ".cfg",
    ".json",
    ".yaml",
    ".yml",
}

EXCLUDE_DIRS = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "build",
    "dist",
    ".mypy_cache",
    ".pytest_cache",
}


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(0, f"{self.prog}: error: {message}\n")


def count_turkish(text: str) -> int:
    return sum(1 for ch in text if ch in TURKISH_LETTERS)


def suspicious_score(text: str) -> int:
    return sum(text.count(token) for token in SUSPICIOUS_SUBSTRINGS if token)


def suggest_fix(line: str) -> Optional[str]:
    original = line
    original_turkish = count_turkish(original)
    original_score = suspicious_score(original)
    candidates = ("latin-1", "cp1252")
    for enc in candidates:
        try:
            candidate = original.encode(enc).decode("utf-8")
        except Exception:
            continue
        if candidate == original:
            continue
        candidate_turkish = count_turkish(candidate)
        candidate_score = suspicious_score(candidate)
        improved = candidate_turkish > original_turkish or candidate_score < original_score
        if improved:
            return candidate
    return None


def find_first_match(line: str) -> Optional[Tuple[int, str]]:
    best_idx = None
    best_match = None
    for token in SUSPICIOUS_SUBSTRINGS:
        idx = line.find(token)
        if idx == -1:
            continue
        if best_idx is None or idx < best_idx or (idx == best_idx and len(token) > len(best_match)):
            best_idx = idx
            best_match = token
    if best_idx is None and line.count(REPLACEMENT_CHAR) >= REPLACEMENT_THRESHOLD:
        idx = line.find(REPLACEMENT_CHAR)
        if idx != -1:
            return idx, REPLACEMENT_CHAR
    if best_idx is None:
        return None
    return best_idx, best_match


def iter_text_files(root: str) -> Iterable[str]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDE_DIRS)
        for name in sorted(filenames):
            ext = os.path.splitext(name)[1].lower()
            if ext not in INCLUDE_EXTENSIONS:
                continue
            yield os.path.join(dirpath, name)


def scan_repo(root: str, max_findings: int) -> Tuple[Dict[str, object], Dict[str, int]]:
    abs_root = os.path.abspath(root)
    findings: List[Dict[str, object]] = []
    files_scanned = 0
    lines_with_findings = 0
    files_with_findings = set()

    for path in iter_text_files(abs_root):
        files_scanned += 1
        rel_path = os.path.relpath(path, abs_root)
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                for line_no, line in enumerate(handle, start=1):
                    raw_line = line.rstrip("\r\n")
                    match = find_first_match(raw_line)
                    if match is None:
                        continue
                    lines_with_findings += 1
                    files_with_findings.add(rel_path)
                    if len(findings) >= max_findings:
                        continue
                    col, match_text = match
                    entry = {
                        "path": rel_path,
                        "line_no": line_no,
                        "col": col + 1,
                        "match": match_text,
                        "raw_line": raw_line,
                    }
                    suggestion = suggest_fix(raw_line)
                    if suggestion:
                        entry["suggested"] = suggestion
                    findings.append(entry)
        except Exception:
            continue

    report = {
        "root": abs_root,
        "timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "files_scanned": files_scanned,
        "findings": findings,
    }
    summary = {
        "files_with_findings": len(files_with_findings),
        "lines_with_findings": lines_with_findings,
    }
    return report, summary


def write_json(report: Dict[str, object], path: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)


def _run_scan(args) -> int:
    max_findings = max(1, int(args.max_findings))
    report, summary = scan_repo(os.getcwd(), max_findings)
    write_json(report, args.json_path)

    print("Mojibake scan summary:")
    print(f"- Files scanned: {report['files_scanned']}")
    print(f"- Files with findings: {summary['files_with_findings']}")
    print(f"- Lines with findings: {summary['lines_with_findings']}")
    print(f"- Findings recorded: {len(report['findings'])}")
    if len(report["findings"]) >= max_findings:
        print(f"- Findings capped at: {max_findings}")
    print(f"- JSON report: {args.json_path}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    try:
        parser = _ArgumentParser(description="UTF-8 mojibake scanner")
        subparsers = parser.add_subparsers(dest="command")
        scan_parser = subparsers.add_parser("scan", help="Scan repo for mojibake")
        scan_parser.add_argument(
            "--json",
            dest="json_path",
            default="encoding_report.json",
            help="Write JSON output to path",
        )
        scan_parser.add_argument(
            "--max-findings",
            dest="max_findings",
            type=int,
            default=5000,
            help="Maximum findings to record",
        )

        args = parser.parse_args(argv)
        if args.command != "scan":
            parser.print_help()
            return 0
        return _run_scan(args)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 0
    except Exception as exc:
        print(f"Unexpected error: {exc}", file=sys.stderr)
        return 1
