# CopyLeft 2026 github.com/i-execute // i_execute.t.me
# Licensed under AGPLv3.

# (c) Dan Gazizullin, 2021-2023. This file is part of the Hikka Userbot: github.com/hikariatama/Hikka

import asyncio
import atexit as _atexit
import contextlib
import functools
import logging
import random
import signal
import sys
import typing
import warnings

import telethon
from telethon import hints
from telethon.tl.functions.channels import (
    EditAdminRequest,
    InviteToChannelRequest,
)
from telethon.tl.types import (
    ChatAdminRights,
)

from ..tl_cache import CustomTelegramClient
from ..types import ListLike

parser = telethon.utils.sanitize_parse_mode("html")
logger = logging.getLogger(__name__)

def ensure_child_watcher():
    if sys.platform == "win32" or sys.version_info >= (3, 14):
        return

    with warnings.catch_warnings():

        warnings.simplefilter("ignore", DeprecationWarning)
        try:
            asyncio.get_event_loop_policy().get_child_watcher()
            return
        except NotImplementedError:
            pass

        asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
        with contextlib.suppress(RuntimeError):
            asyncio.set_event_loop(asyncio.get_running_loop())

custom_placeholders = {}

def rand(size: int, /) -> str:
    return "".join(
        [random.choice("abcdefghijklmnopqrstuvwxyz1234567890") for _ in range(size)]
    )

async def invite_inline_bot(
    client: CustomTelegramClient,
    peer: hints.EntityLike,
) -> None:
    try:
        await client(InviteToChannelRequest(peer, [client.loader.inline.bot_username]))
    except Exception as e:
        logging.warning(
            "Can't invite inline bot to asset chat (continuing without it): %s", e
        )

    with contextlib.suppress(Exception):
        await client(
            EditAdminRequest(
                channel=peer,
                user_id=client.loader.inline.bot_username,
                admin_rights=ChatAdminRights(ban_users=True),
                rank="Feroku",
            )
        )

def run_sync(func, *args, **kwargs):
    return asyncio.get_event_loop().run_in_executor(
        None,
        functools.partial(func, *args, **kwargs),
    )

def run_async(loop: asyncio.AbstractEventLoop, coro: typing.Awaitable) -> typing.Any:
    return asyncio.run_coroutine_threadsafe(coro, loop).result()

def merge(
    a: dict,
    b: dict,
    /,
    *,
    deep: bool = True,
) -> dict:
    for key, a_value in a.items():
        b_value = b.get(key)

        match (
            key not in b,
            isinstance(a_value, dict) and isinstance(b_value, dict) and deep,
            isinstance(a_value, list) and isinstance(b_value, list),
        ):
            case (True, _, _):
                b[key] = a_value
            case (False, True, _):
                b[key] = merge(a_value, b_value, deep=deep)
            case (False, False, True):
                b[key] = list(dict.fromkeys(b_value + a_value))
            case _:
                b[key] = a_value

    return b

def chunks(_list: ListLike, n: int, /) -> list[list[typing.Any]]:
    return [_list[i : i + n] for i in range(0, len(_list), n)]

def atexit(
    func: typing.Callable,
    use_signal: int | None = None,
    *args,
    **kwargs,
) -> None:
    if use_signal:
        signal.signal(use_signal, lambda *_: func(*args, **kwargs))
        return

    _atexit.register(functools.partial(func, *args, **kwargs))

def _copy_tl(o, **kwargs):
    d = o.to_dict()
    del d["_"]
    d.update(kwargs)
    return o.__class__(**d)

def get_iso_time() -> str:
    from datetime import datetime

    return datetime.utcnow().isoformat() + "Z"

def safe_getattr(obj, attr, default=None):
    try:
        return getattr(obj, attr, default)
    except AttributeError:
        return default

def normalize_prefix(value: typing.Any, default: str = ".") -> str:
    return value if isinstance(value, str) and len(value) == 1 else default
