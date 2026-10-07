# CopyLeft 2026 github.com/i-execute // i_execute.t.me
# Licensed under AGPLv3.

# (c) Dan Gazizullin, 2021-2023. This file is part of the Hikka Userbot: github.com/hikariatama/Hikka

import logging
import os

import telethon

parser = telethon.utils.sanitize_parse_mode("html")
logger = logging.getLogger(__name__)

def get_version_raw() -> str:
    from .. import version

    return ".".join(map(str, list(version.__version__)))

def get_base_dir() -> str:
    return get_dir(__file__)

def get_dir(mod: str) -> str:
    return os.getcwd() + "/feroku"

version = get_version_raw
