import argparse
import os
import sys

from tools.encoding import mojibake_apply
from tools.encoding import mojibake_scan


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(0, f"{self.prog}: error: {message}\n")


def _run_scan(args) -> int:
    max_findings = max(1, int(args.max_findings))
    report, summary = mojibake_scan.scan_repo(os.getcwd(), max_findings)
    mojibake_scan.write_json(report, args.json_path)

    print("Mojibake scan summary:")
    print(f"- Files scanned: {report['files_scanned']}")
    print(f"- Files with findings: {summary['files_with_findings']}")
    print(f"- Lines with findings: {summary['lines_with_findings']}")
    print(f"- Findings recorded: {len(report['findings'])}")
    if len(report["findings"]) >= max_findings:
        print(f"- Findings capped at: {max_findings}")
    print(f"- JSON report: {args.json_path}")
    return 0


def main(argv=None) -> int:
    try:
        parser = _ArgumentParser(description="Encoding tools")
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

        apply_parser = subparsers.add_parser("apply", help="Apply mojibake fixes from report")
        apply_parser.add_argument(
            "--report",
            dest="report_path",
            default="encoding_report.json",
            help="Report JSON path",
        )
        apply_parser.add_argument("--apply", action="store_true", help="Write changes to files")
        apply_parser.add_argument("--dry-run", action="store_true", help="Only report changes")
        apply_parser.add_argument(
            "--write-json",
            dest="write_json_path",
            default=None,
            help="Write apply report to JSON path",
        )
        apply_parser.add_argument(
            "--limit-files",
            dest="limit_files",
            type=int,
            default=0,
            help="Limit number of files processed (0 = no limit)",
        )
        apply_parser.add_argument("--backup", action="store_true", help="Create .bak backup")

        args = parser.parse_args(argv)
        if args.command == "scan":
            return _run_scan(args)
        if args.command == "apply":
            return mojibake_apply.run_apply(
                report_path=args.report_path,
                apply=args.apply,
                dry_run=args.dry_run,
                write_json_path=args.write_json_path,
                limit_files=args.limit_files,
                backup=args.backup,
            )
        parser.print_help()
        return 0
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 0
    except Exception as exc:
        print(f"Unexpected error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
