# CopyLeft 2026 github.com/i-execute // i_execute.t.me
# Licensed under AGPLv3.

# (c) Dan Gazizullin, 2021-2023. This file is part of the Hikka Userbot: github.com/hikariatama/Hikka

import logging
import subprocess
from typing import Literal

import git
import telethon

from .. import version

parser = telethon.utils.sanitize_parse_mode("html")
logger = logging.getLogger(__name__)

def get_git_info() -> tuple[str, str]:
    hash_ = get_git_hash() or ""
    return (
        hash_,
        f"https://github.com/i-execute/Feroku/commit/{hash_}" if hash_ else "",
    )

def get_git_hash() -> str | Literal[False]:
    try:
        with git.Repo() as repo:
            return repo.head.commit.hexsha
    except Exception:
        return False

def get_commit_url() -> str:
    try:
        hash_ = get_git_hash()
        if not hash_:
            return "Unknown"
        return f'<a href="https://github.com/i-execute/Feroku/commit/{hash_}">#{hash_[:7]}</a>'
    except Exception:
        return "Unknown"

def get_git_status() -> str:
    try:
        process = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if process.returncode != 0:
            return "Not a Git repo"

        output = process.stdout.strip()

        if not output:
            return "Clean"

        count = len(output.splitlines())
        word = "file" if count == 1 else "files"
        return f"{count} {word} modified"

    except subprocess.TimeoutExpired:
        return "Unknown"
    except Exception:
        return "Unknown"

def get_last_commit_message() -> str:
    try:
        with git.Repo() as repo:
            message = repo.head.commit.message
            if isinstance(message, bytes):
                return message.decode(errors="replace").strip()
            return message.strip()
    except Exception:
        return "Unknown"

def get_commit_count() -> int:
    try:
        with git.Repo() as repo:
            return len(list(repo.iter_commits()))
    except Exception:
        return 0

def is_up_to_date():
    with git.Repo(search_parent_directories=True) as repo:
        diff = any(repo.iter_commits(f"HEAD..origin/{version.branch}", max_count=1))
        return not diff
