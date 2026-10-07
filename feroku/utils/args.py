# CopyLeft 2026 github.com/i-execute // i_execute.t.me
# Licensed under AGPLv3.

# (c) Dan Gazizullin, 2021-2023. This file is part of the Hikka Userbot: github.com/hikariatama/Hikka

import inspect
import logging
import shlex
import typing

import telethon
import telethon.extensions
import telethon.extensions.html
from telethon.tl.custom.message import Message

from .entity import escape_html, relocate_entities

parser = telethon.utils.sanitize_parse_mode("html")
logger = logging.getLogger(__name__)

def iter_attrs(obj: typing.Any, /) -> list[tuple[str, typing.Any]]:
    return ((attr, getattr(obj, attr)) for attr in dir(obj))

def validate_html(html: str) -> str:
    text, entities = telethon.extensions.html.parse(html)
    return telethon.extensions.html.unparse(escape_html(text), entities)

def get_kwargs() -> dict[str, typing.Any]:
    keys, _, _, values = inspect.getargvalues(inspect.currentframe().f_back)
    return {key: values[key] for key in keys if key != "self"}

def get_args(message: Message | str) -> list[str]:
    if not (message := getattr(message, "message", message)):
        return False

    if len(message := message.split(maxsplit=1)) <= 1:
        return []

    message = message[1]

    try:
        split = shlex.split(message)
    except ValueError:
        return message

    return list(filter(lambda x: len(x) > 0, split))

def get_args_raw(message: Message | str) -> str:
    if not (message := getattr(message, "message", message)):
        return False

    return args[1] if len(args := message.split(maxsplit=1)) > 1 else ""

def get_args_html(message: Message) -> str:
    prefix = message.client.loader.get_prefix()

    if not (message := message.text):
        return False

    if prefix not in message:
        return message

    raw_text, entities = parser.parse(message)

    raw_text = parser._add_surrogate(raw_text)

    try:
        command = raw_text[
            raw_text.index(prefix) : raw_text.index(" ", raw_text.index(prefix) + 1)
        ]
    except ValueError:
        return ""

    command_len = len(command) + 1

    return parser.unparse(
        parser._del_surrogate(raw_text[command_len:]),
        relocate_entities(entities, -command_len, raw_text[command_len:]),
    )

def get_args_split_by(
    message: Message | str,
    separator: str,
) -> list[str]:
    args = get_args_raw(message)
    if isinstance(separator, str):
        sections = args.split(separator)
    else:
        sections = [args]
        for sep in separator:
            new_section = []
            for section in sections:
                new_section.extend(section.split(sep))
            sections = new_section
    return [section.strip() for section in sections if section.strip()]

def get_args_int(message: Message | str) -> list[int]:
    args = get_args(message)
    result = []
    for arg in args:
        try:
            result.append(int(arg))
        except ValueError:
            continue
    return result

def get_args_bool(message: Message | str) -> list[bool]:
    args = get_args(message)
    result = []
    for arg in args:
        lower_arg = arg.lower()
        if lower_arg in ["true", "yes", "1", "on"]:
            result.append(True)
        elif lower_arg in ["false", "no", "0", "off"]:
            result.append(False)
    return result
