# CopyLeft 2026 github.com/i-execute // i_execute.t.me
# Licensed under AGPLv3.

# (c) Dan Gazizullin, 2021-2023. This file is part of the Hikka Userbot: github.com/hikariatama/Hikka

import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from ._internal import restart

def get_data_root():
    for index, arg in enumerate(sys.argv):
        if arg == "--data-root" and index + 1 < len(sys.argv):
            return Path(sys.argv[index + 1]).expanduser()

        if arg.startswith("--data-root="):
            return Path(arg.split("=", maxsplit=1)[1]).expanduser()

    return Path(
        "/data"
        if "DOCKER" in os.environ
        else os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    )

def wipe_data():
    if not {"-w", "--wipe"} & set(sys.argv):
        return

    print(
        "Are you sure you want to completely delete all session files, "
        "their databases and modules? This action is irreversible [y/N]"
    )
    if input("> ").strip().lower() not in {"yes", "y"}:
        print("Cancelled")
        sys.exit(0)

    data_root = get_data_root()
    patterns = (
        "config.json",
        "config-*.json",
        "*.session",
        "*.session-journal",
        "api_token.txt",
    )
    dirs = ("loaded_modules", "sessions")
    removed = 0

    for pattern in patterns:
        for path in data_root.glob(pattern):
            if not path.is_file():
                continue

            path.unlink()
            removed += 1

    for dirname in dirs:
        path = data_root / dirname
        if not path.is_dir():
            continue

        shutil.rmtree(path)
        removed += 1

    print(f"Removed files: {removed}")
    sys.exit(0)

wipe_data()

def get_file_hash(filename):
    hasher = hashlib.sha256()
    try:
        with open(filename, "rb") as f:
            hasher.update(f.read())
        return hasher.hexdigest()
    except FileNotFoundError:
        return None

def deps():
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--upgrade",
            "-q",
            "--disable-pip-version-check",
            "--no-warn-script-location",
            "-r",
            "Storage/requirements.txt",
        ],
        check=True,
        timeout=600,
        capture_output=True,
    )
    with open(".requirements_hash", "w") as f:
        f.write(get_file_hash("Storage/requirements.txt"))

if sys.version_info < (3, 10, 0):
    print("Error: you must use at least Python version 3.10.0")
elif __package__ != "feroku":
    print(
        "Error: you cannot run this as a script; you must execute as a package"
    )
else:
    try:
        import telethon

        ver_ = tuple(
            int(match.group()) if (match := re.match(r"\d+", part)) else 0
            for part in telethon.__version__.split(".")
        )
        if ver_ < (1, 7, 2):
            raise ImportError
    except ImportError:
        print("Installing dependencies...")
        deps()
        restart()

    try:
        from . import log

        log.init()
        from . import main
    except ImportError as e:
        print(
            f"{str(e)}\nAttempting dependencies installation... Just wait "
        )
        deps()
        restart()

    prev_hash = None
    if os.path.exists(".requirements_hash"):
        with open(".requirements_hash") as f:
            prev_hash = f.read().strip()

    if prev_hash != get_file_hash("Storage/requirements.txt"):
        print(
            "Detected changes in requirements.txt, updating dependencies..."
        )
        deps()
        restart()

    main.feroku.main()
