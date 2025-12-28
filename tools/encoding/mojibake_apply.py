import json
import os
import shutil
import sys
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from tools.encoding.mojibake_map import MOJIBAKE_MAP

UTF8_BOM = "\ufeff"


def load_report(path: str) -> Tuple[Optional[Dict[str, object]], Optional[str]]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            return None, "report is not a JSON object"
        return data, None
    except FileNotFoundError:
        return None, f"report not found: {path}"
    except Exception as exc:
        return None, f"failed to read report: {exc}"


def collect_paths(report: Dict[str, object]) -> List[str]:
    findings = report.get("findings")
    if not isinstance(findings, list):
        return []
    seen = set()
    ordered = []
    for item in findings:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        if not path or path in seen:
            continue
        seen.add(path)
        ordered.append(path)
    return ordered


def read_text(path: str) -> Tuple[Optional[str], Optional[str]]:
    try:
        with open(path, "r", encoding="utf-8", errors="strict", newline="") as handle:
            return handle.read(), None
    except UnicodeDecodeError:
        try:
            with open(path, "r", encoding="utf-8", errors="replace", newline="") as handle:
                return handle.read(), "decode_replace"
        except Exception as exc:
            return None, str(exc)
    except Exception as exc:
        return None, str(exc)


def apply_mapping(text: str) -> Tuple[str, int]:
    replacements = 0
    if text.startswith(UTF8_BOM):
        text = text[len(UTF8_BOM) :]
        replacements += 1
    for src, dst in MOJIBAKE_MAP.items():
        count = text.count(src)
        if count:
            text = text.replace(src, dst)
            replacements += count
    return text, replacements


def write_text(path: str, text: str) -> Optional[str]:
    try:
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        return None
    except Exception as exc:
        return str(exc)


def process_file(
    abs_path: str,
    rel_path: str,
    apply: bool,
    backup: bool,
) -> Dict[str, object]:
    entry = {
        "path": rel_path,
        "changed": False,
        "replacements": 0,
        "bytes_before": None,
        "bytes_after": None,
    }
    text, error = read_text(abs_path)
    if text is None:
        entry["error"] = error or "read_failed"
        return entry

    bytes_before = len(text.encode("utf-8"))
    updated, replacements = apply_mapping(text)
    changed = updated != text
    bytes_after = len(updated.encode("utf-8"))

    entry["changed"] = changed
    entry["replacements"] = replacements
    entry["bytes_before"] = bytes_before
    entry["bytes_after"] = bytes_after

    if apply and changed:
        if backup:
            backup_path = abs_path + ".bak"
            try:
                shutil.copyfile(abs_path, backup_path)
            except Exception as exc:
                entry["backup_error"] = str(exc)
        write_error = write_text(abs_path, updated)
        if write_error:
            entry["error"] = write_error
    return entry


def write_apply_report(path: str, payload: Dict[str, object]) -> Optional[str]:
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        return None
    except Exception as exc:
        return str(exc)


def run_apply(
    report_path: str,
    apply: bool,
    dry_run: bool,
    write_json_path: Optional[str],
    limit_files: int,
    backup: bool,
) -> int:
    report, error = load_report(report_path)
    if report is None:
        print(f"Mojibake apply (dry-run): {error}")
        print("files_total=0, files_changed=0, replacements=0")
        return 0

    base_root = report.get("root")
    if not isinstance(base_root, str) or not base_root:
        base_root = os.getcwd()

    mode = "apply" if apply and not dry_run else "dry-run"
    paths = collect_paths(report)
    if limit_files and limit_files > 0:
        paths = paths[: int(limit_files)]

    files_total = len(paths)
    files_changed = 0
    total_replacements = 0
    file_results: List[Dict[str, object]] = []
    changed_list = []

    for rel_path in paths:
        abs_path = os.path.normpath(os.path.join(base_root, rel_path))
        result = process_file(abs_path, rel_path, apply and mode == "apply", backup)
        file_results.append(result)
        total_replacements += int(result.get("replacements", 0) or 0)
        if result.get("changed"):
            files_changed += 1
            changed_list.append((rel_path, result.get("replacements", 0)))

    print(f"Mojibake apply ({mode})")
    print(f"files_total={files_total}, files_changed={files_changed}, replacements={total_replacements}")
    if changed_list:
        print("Changed files:")
        for path, repl in changed_list:
            print(f"- {path} (repl={repl})")

    if write_json_path:
        payload = {
            "timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "mode": mode,
            "report_path": report_path,
            "files_total": files_total,
            "files_changed": files_changed,
            "replacements": total_replacements,
            "files": file_results,
        }
        write_error = write_apply_report(write_json_path, payload)
        if write_error:
            print(f"Failed to write JSON report: {write_error}", file=sys.stderr)
    return 0
