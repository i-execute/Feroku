# CopyLeft 2026 github.com/i-execute // i_execute.t.me
# Licensed under AGPLv3.

# (c) Dan Gazizullin, 2021-2023. This file is part of the Hikka Userbot: github.com/hikariatama/Hikka

__version__ = (2, 2, 2)

import os

import git

try:
    with git.Repo(
        path=os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    ) as repo:
        branch = repo.active_branch.name
except Exception:
    branch = "master"
