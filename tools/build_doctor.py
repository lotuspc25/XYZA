import subprocess
import sys
import shutil
import os
from pathlib import Path


def run():
    root = Path(__file__).resolve().parent.parent
    build_dir = root / "build"
    build_dir.mkdir(exist_ok=True, parents=True)
    log_path = build_dir / "build_log.txt"

    spec_path = root / "build" / "xyza.spec"
    cmd = [sys.executable, "-m", "PyInstaller", str(spec_path), "--noconfirm", "--clean"]
    env = os.environ.copy()
    skip_build = env.get("BUILD_SKIP_PYI") == "1"

    with open(log_path, "w", encoding="utf-8") as log:
        log.write(f"Python: {sys.executable}\n")
        log.write(f"Workdir: {root}\n")
        log.write(f"Spec: {spec_path}\n")
        log.write("Command: " + " ".join(cmd) + "\n")
        log.write(f"Skip build: {skip_build}\n\n")
        try:
            pip = subprocess.run(
                [sys.executable, "-m", "pip", "freeze"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )
            log.write("=== pip freeze ===\n")
            log.write(pip.stdout)
            if pip.stderr:
                log.write("\n[pip stderr]\n" + pip.stderr + "\n")
            log.write("\n===================\n\n")
        except Exception as exc:
            log.write(f"pip freeze failed: {exc}\n\n")

        rc = 0
        if not skip_build:
            proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True, env=env)
            log.write(proc.stdout)
            if proc.stderr:
                log.write("\n[stderr]\n")
                log.write(proc.stderr)
            rc = proc.returncode

    candidates = [
        root / "dist" / "XYZA.exe",
        root / "dist" / "XYZA" / "XYZA.exe",
    ]
    exe_path = next((p for p in candidates if p.exists()), None)

    if exe_path and rc == 0:
        print(f"Build OK: {exe_path}")
        return 0

    print("Build failed. See build/build_log.txt")
    try:
        tail = (log_path.read_text(encoding="utf-8", errors="ignore").splitlines())[-200:]
        for line in tail:
            print(line)
    except Exception:
        pass
    return 1


if __name__ == "__main__":
    sys.exit(run())
