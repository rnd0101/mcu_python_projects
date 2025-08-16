#!/usr/bin/env python3
# Python 3.11 deploy script using mpremote, with auto-creation of remote dirs
import os
import sys
import subprocess
from pathlib import Path
import shutil
import fnmatch

PORT = os.environ.get("PORT", "/dev/ttyACM0")  # override with env PORT
SRC_DIR = Path("src")
EXCLUDES_FILE = Path(".mpyignore")


def run(cmd, **kw):
    return subprocess.run(cmd, **kw)


def check_output(cmd, **kw):
    return subprocess.check_output(cmd, **kw)


def list_files_with_git():
    cmd = ["git", "ls-files", "-co"]
    if EXCLUDES_FILE.exists():
        cmd += [f"--exclude-from={EXCLUDES_FILE}"]
    try:
        out = check_output(cmd, text=True, cwd=SRC_DIR).splitlines()
        return [SRC_DIR / p for p in out if p]
    except Exception:
        return None


def load_excludes():
    patterns = []
    if EXCLUDES_FILE.exists():
        for line in EXCLUDES_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            patterns.append(line)
    return patterns


def is_excluded(path: Path, patterns):
    rel = path.as_posix()
    for pat in patterns:
        if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(path.name, pat):
            return True
        if pat.endswith("/") and rel.startswith(pat):
            return True
    return False


def list_files_fallback():
    patterns = load_excludes()
    files = []
    for p in SRC_DIR.rglob("*"):
        if p.is_file() and not is_excluded(p.relative_to(Path.cwd()), patterns):
            files.append(p)
    return files


def ensure_remote_dirs(dev_path: str):
    """
    Ensure all parent directories of dev_path (which starts with ':')
    exist on the MicroPython filesystem by creating them if needed.
    """
    assert dev_path.startswith(":"), "device path must start with ':'"
    parts = dev_path[1:].split("/")  # drop leading ':'
    # no dirs to create if file is at root (e.g., :main.py)
    if len(parts) <= 1:
        return
    cur = ":"
    for part in parts[:-1]:
        if not part:
            continue
        cur = f"{cur}{part}/" if cur.endswith(":") else f"{cur}/{part}/"
        # mpremote doesn't have -p; mkdir will fail if exists, so ignore errors
        run(["mpremote", "connect", PORT, "fs", "mkdir", cur.rstrip("/")], check=False)


def push_file(f: Path):
    rel = f.relative_to(SRC_DIR).as_posix()
    dev_path = f":{rel}"
    print(f"-> {f}  =>  {dev_path}")
    ensure_remote_dirs(dev_path)
    run(["mpremote", "connect", PORT, "fs", "cp", str(f), dev_path], check=True)


def main():
    if not SRC_DIR.exists():
        print("Error: 'src' directory not found.", file=sys.stderr)
        sys.exit(1)

    files = None
    if (SRC_DIR / ".git").exists() or (Path.cwd() / ".git").exists():
        if shutil.which("git"):
            files = list_files_with_git()
    if files is None:
        files = list_files_fallback()

    files = sorted(files, key=lambda p: p.as_posix())

    for f in files:
        push_file(f)

    print("Done. Resetting...")
    run(["mpremote", "connect", PORT, "reset"], check=True)


if __name__ == "__main__":
    main()
