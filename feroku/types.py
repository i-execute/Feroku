# CopyLeft 2026 github.com/i-execute // i_execute.t.me
# Licensed under AGPLv3.

# (c) Dan Gazizullin, 2021-2023. This file is part of the Hikka Userbot: github.com/hikariatama/Hikka

import ast
import asyncio
import collections
import contextlib
import copy
import inspect
import logging
import time
import typing
from dataclasses import dataclass, field
from importlib.abc import SourceLoader
from collections.abc import Hashable

from telethon.hints import EntityLike
from telethon.tl.types import ChannelFull, Message, UserFull

from ._compat import install_public_type_compat
from .inline.types import (
    BotInlineCall,
    BotInlineMessage,
    BotMessage,
    FerokuReplyMarkup,
    InlineCall,
    InlineMessage,
    InlineQuery,
    InlineUnit,
)
from .pointers import PointerDict, PointerList

if typing.TYPE_CHECKING:
    from .loader import Modules

__all__ = [
    "JSONSerializable",
    "FerokuReplyMarkup",
    "ListLike",
    "Command",
    "StringLoader",
    "Strings",
    "Module",
    "get_commands",
    "get_inline_handlers",
    "get_callback_handlers",
    "BotInlineCall",
    "BotMessage",
    "InlineCall",
    "InlineMessage",
    "InlineQuery",
    "InlineUnit",
    "BotInlineMessage",
    "PointerDict",
    "PointerList",
]
install_public_type_compat(globals(), FerokuReplyMarkup)

logger = logging.getLogger(__name__)

JSONSerializable = typing.Union[str, int, float, bool, list, dict, None]
ListLike = typing.Union[list, set, tuple]
Command = typing.Callable[..., typing.Awaitable[typing.Any]]

class Strings:
    def __init__(self, module: typing.Any):
        source = module.strings
        self._strings = dict(source) if isinstance(source, dict) else {}

    def __getitem__(self, key: str) -> str:
        return self._strings.get(key, f"Unknown string: {key}")

    def get(self, key: str, default: typing.Any = None) -> typing.Any:
        return self._strings.get(key, default)

    def __call__(self, key: str, _: typing.Any = None) -> str:
        return self[key]

    def __iter__(self):
        return iter(self._strings)

    def __contains__(self, key: str) -> bool:
        return key in self._strings


class StringLoader(SourceLoader):
    def __init__(self, data: str, origin: str):
        self.data = data.encode("utf-8") if isinstance(data, str) else data
        self.origin = origin

    def get_source(self, _=None) -> str:
        return self.data.decode("utf-8")

    def get_code(self, fullname: str) -> bytes:
        return (
            compile(source, self.origin, "exec", dont_inherit=True)
            if (source := self.get_data(fullname))
            else None
        )

    def get_filename(self, *args, **kwargs) -> str:
        return self.origin

    def get_data(self, *args, **kwargs) -> bytes:
        return self.data

class Module:
    strings = {"name": "Unknown"}

    def config_complete(self):
        pass
    async def client_ready(self):

        pass

    def internal_init(self):
        self.allmodules: "Modules"

        self.db = self.allmodules.db
        self._db = self.allmodules.db
        self.client = self.allmodules.client
        self._client = self.allmodules.client
        self.lookup = self.allmodules.lookup
        self.get_prefix = self.allmodules.get_prefix
        self.get_prefixes = self.allmodules.get_prefixes
        self.inline = self.allmodules.inline
        self.tg_id: int = self._client.tg_id
        self._tg_id: int = self._client.tg_id

    async def on_unload(self):
        pass
    async def on_dlmod(self):
        pass
    async def invoke(
        self,
        command: str,
        args: str | None = None,
        peer: EntityLike | None = None,
        message: Message | None = None,
        edit: bool = False,
    ) -> Message:
        if command not in self.allmodules.commands:
            raise ValueError(f"Command {command} not found")

        if not message and not peer:
            raise ValueError("Either peer or message must be specified")

        cmd = f"{self.get_prefix()}{command} {args or ''}".strip()

        message = (
            (await self._client.send_message(peer, cmd))
            if peer
            else (await (message.edit if edit else message.respond)(cmd))
        )
        await self.allmodules.commands[command](message)
        return message

    @property
    def commands(self) -> dict[str, Command]:
        return get_commands(self)

    @property
    def feroku_commands(self) -> dict[str, Command]:
        return get_commands(self)

    @property
    def inline_handlers(self) -> dict[str, Command]:
        return get_inline_handlers(self)

    @property
    def feroku_inline_handlers(self) -> dict[str, Command]:
        return get_inline_handlers(self)

    @property
    def callback_handlers(self) -> dict[str, Command]:
        return get_callback_handlers(self)

    @property
    def feroku_callback_handlers(self) -> dict[str, Command]:
        return get_callback_handlers(self)

    @property
    def watchers(self) -> dict[str, Command]:
        return get_watchers(self)

    @property
    def feroku_watchers(self) -> dict[str, Command]:
        return get_watchers(self)

    @commands.setter
    def commands(self, _):
        pass

    @feroku_commands.setter
    def feroku_commands(self, _):
        pass

    @inline_handlers.setter
    def inline_handlers(self, _):
        pass

    @feroku_inline_handlers.setter
    def feroku_inline_handlers(self, _):
        pass

    @callback_handlers.setter
    def callback_handlers(self, _):
        pass

    @feroku_callback_handlers.setter
    def feroku_callback_handlers(self, _):
        pass

    @watchers.setter
    def watchers(self, _):
        pass

    @feroku_watchers.setter
    def feroku_watchers(self, _):
        pass

    async def animate(
        self,
        message: Message | InlineMessage,
        frames: list[str],
        interval: float | int,
        *,
        inline: bool = False,
    ) -> None:
        from . import utils

        if interval < 0.1:
            logger.warning(
                "Resetting animation interval to 0.1s, because it may get you in"
                " floodwaits"
            )
            interval = 0.1

        for frame in frames:
            match message:
                case Message() if inline:
                    message = await self.inline.form(
                        message=message,
                        text=frame,
                        reply_markup={"text": "\u0020\u2800", "data": "empty"},
                    )
                case Message():
                    message = await utils.answer(message, frame)
                case InlineMessage() if inline:
                    await message.edit(frame)

            await asyncio.sleep(interval)

        return message

    def get(
        self,
        key: str,
        default: JSONSerializable | None = None,
    ) -> JSONSerializable:
        return self._db.get(self.__class__.__name__, key, default)

    def set(self, key: str, value: JSONSerializable) -> bool:
        self._db.set(self.__class__.__name__, key, value)

    def pointer(
        self,
        key: str,
        default: JSONSerializable | None = None,
        item_type: typing.Any | None = None,
    ) -> JSONSerializable | PointerList | PointerDict:
        return self._db.pointer(self.__class__.__name__, key, default, item_type)

    def _lib_get(
        self,
        key: str,
        default: JSONSerializable | None = None,
    ) -> JSONSerializable:
        return self._db.get(self.__class__.__name__, key, default)

    def _lib_set(self, key: str, value: JSONSerializable) -> bool:
        self._db.set(self.__class__.__name__, key, value)

    def _lib_pointer(
        self,
        key: str,
        default: JSONSerializable | None = None,
    ) -> JSONSerializable | PointerDict | PointerList:
        return self._db.pointer(self.__class__.__name__, key, default)

class Library:
    def internal_init(self):
        self.name = self.__class__.__name__
        self.db = self.allmodules.db
        self._db = self.allmodules.db
        self.client = self.allmodules.client
        self._client = self.allmodules.client
        self.tg_id = self._client.tg_id
        self._tg_id = self._client.tg_id
        self.lookup = self.allmodules.lookup
        self.get_prefix = self.allmodules.get_prefix
        self.get_prefixes = self.allmodules.get_prefixes
        self.inline = self.allmodules.inline

class LoadError(Exception):
    def __init__(self, error_message: str):
        self._error = error_message

    def __str__(self) -> str:
        return self._error

class CoreOverwriteError(LoadError):
    def __init__(
        self,
        module: str | None = None,
        command: str | None = None,
    ):
        self.type = "module" if module else "command"
        self.target = module or command
        super().__init__(str(self))

    def __str__(self) -> str:
        return (
            f"{'Module' if self.type == 'module' else 'command'} {self.target} will not"
            " be overwritten, because it's core"
        )

class CoreUnloadError(Exception):
    def __init__(self, module: str):
        self.module = module
        super().__init__()

    def __str__(self) -> str:
        return f"Module {self.module} will not be unloaded, because it's core"

class SelfUnload(Exception):
    def __init__(self, error_message: str = ""):
        super().__init__()
        self._error = error_message

    def __str__(self) -> str:
        return self._error

class SelfSuspend(Exception):
    def __init__(self, error_message: str = ""):
        super().__init__()
        self._error = error_message

    def __str__(self) -> str:
        return self._error

class StopLoop(Exception):
    pass
class ModuleConfig(dict):
    def __init__(self, *entries: typing.Union[str, "ConfigValue", "ConfigCategory"]):
        self._option_categories: dict[str, str] = dict()
        self._categories: dict[str, "ConfigCategory"] = dict()

        if all(isinstance(entry, (ConfigValue, ConfigCategory)) for entry in entries):

            self._config = {}
            for entry in entries:
                if isinstance(entry, ConfigCategory):
                    self._categories[entry.name] = entry
                    for cv in entry:
                        self._config[cv.option] = cv
                        self._option_categories[cv.option] = entry.name
                else:
                    self._config[entry.option] = entry
        else:

            keys = []
            values = []
            defaults = []
            docstrings = []
            for i, entry in enumerate(entries):
                if i % 3 == 0:
                    keys += [entry]
                elif i % 3 == 1:
                    values += [entry]
                    defaults += [entry]
                else:
                    docstrings += [entry]

            self._config = {
                key: ConfigValue(option=key, default=default, doc=doc)
                for key, default, doc in zip(keys, defaults, docstrings)
            }

        super().__init__(
            {option: config.value for option, config in self._config.items()}
        )

    def getdoc(self, key: str, message: Message | None = None) -> str:
        ret = self._config[key].doc

        if callable(ret):
            try:

                ret = ret(message)
            except Exception:
                ret = ret()

        return ret

    def getdef(self, key: str) -> str:
        return self._config[key].default

    def get_category(self, key: str) -> typing.Optional["ConfigCategory"]:
        cat_name = self._option_categories.get(key)
        return self._categories.get(cat_name) if cat_name else None

    def grouped_options(
        self,
    ) -> "collections.OrderedDict[str | None, list[str]]":
        result = collections.OrderedDict()
        for option in self._config:
            cat = self._option_categories.get(option)
            result.setdefault(cat, []).append(option)
        return result

    def __setitem__(self, key: str, value: typing.Any):
        self._config[key].value = value
        super().__setitem__(key, value)

    def set_no_raise(self, key: str, value: typing.Any):
        self._config[key].set_no_raise(value)
        super().__setitem__(key, value)

    def __getitem__(self, key: str) -> typing.Any:
        try:
            return self._config[key].value
        except KeyError:
            return None

    def reload(self):
        for key in self._config:
            super().__setitem__(key, self._config[key].value)

    def change_validator(
        self,
        key: str,
        validator: typing.Callable[[JSONSerializable], JSONSerializable],
    ):
        self._config[key].validator = validator

LibraryConfig = ModuleConfig

class _Placeholder:
    pass
async def wrap(func: typing.Callable[[], typing.Awaitable]) -> typing.Any:
    with contextlib.suppress(Exception):
        return await func()

def syncwrap(func: typing.Callable[[], typing.Any]) -> typing.Any:
    with contextlib.suppress(Exception):
        return func()

@dataclass(repr=True)
class ConfigValue:
    option: str
    default: typing.Any = None
    doc: typing.Callable[[], str] | str = "No description"
    value: typing.Any = field(default_factory=_Placeholder)
    validator: None | (typing.Callable[[JSONSerializable], JSONSerializable]) = None
    on_change: None | (typing.Callable[[], typing.Awaitable] | typing.Callable) = None
    folder: str | None = None

    def __post_init__(self):
        if isinstance(self.value, _Placeholder):
            self.value = self.default

    def set_no_raise(self, value: typing.Any) -> bool:
        return self.__setattr__("value", value, ignore_validation=True)

    def __setattr__(
        self,
        key: str,
        value: typing.Any,
        *,
        ignore_validation: bool = False,
    ):
        if key == "value":
            try:
                value = ast.literal_eval(value)
            except Exception:
                pass

            if isinstance(value, (set, tuple)):
                value = list(value)

            if isinstance(value, list):
                value = [
                    item.strip() if isinstance(item, str) else item for item in value
                ]

            if self.validator is not None:
                if value is not None:
                    from . import validators

                    try:
                        value = self.validator.validate(value)
                    except validators.ValidationError as e:
                        if not ignore_validation:
                            raise e

                        logger.debug(
                            "Config value was broken (%s), so it was reset to %s",
                            value,
                            self.default,
                        )

                        value = self.default
                else:
                    match self.validator.internal_id:
                        case "String":
                            default_val = ""
                        case "Integer":
                            default_val = 0
                        case "Boolean":
                            default_val = False
                        case "Series":
                            default_val = []
                        case "Float":
                            default_val = 0.0
                        case _:
                            default_val = None

                    if default_val is not None:
                        logger.debug(
                            "Config value was None, so it was reset to %s",
                            default_val,
                        )
                        value = default_val

            self._save_marker = True

        object.__setattr__(self, key, value)

        if key == "value" and not ignore_validation and callable(self.on_change):
            if inspect.iscoroutinefunction(self.on_change):
                asyncio.ensure_future(wrap(self.on_change))
            else:
                syncwrap(self.on_change)

class ConfigCategory(list):
    def __init__(
        self,
        name: str,
        *config_values: ConfigValue,
        doc: typing.Callable[[], str] | str | "ConfigValue" = "No description",
    ):
        super().__init__(config_values)
        self.name = str(name)
        self.doc = doc

    def getdoc(self) -> str:
        if callable(self.doc):
            try:
                return self.doc()
            except Exception:
                return "No description"
        return self.doc

    @property
    def _config_values(self) -> tuple[ConfigValue, ...]:
        return tuple(self)

def _get_members(
    mod: Module,
    ending: str,
    attribute: str | None = None,
    strict: bool = False,
) -> dict:
    return {
        (
            method_name.rsplit(ending, maxsplit=1)[0]
            if (method_name == ending if strict else method_name.endswith(ending))
            else method_name
        ).lower(): getattr(mod, method_name)
        for method_name in dir(mod)
        if not isinstance(getattr(type(mod), method_name, None), property)
        and callable(getattr(mod, method_name))
        and (
            (method_name == ending if strict else method_name.endswith(ending))
            or attribute
            and getattr(getattr(mod, method_name), attribute, False)
        )
    }

class CacheRecordEntity:
    def __init__(
        self,
        hashable_entity: "Hashable",
        resolved_entity: EntityLike,
        exp: int,
    ):
        self.entity = copy.deepcopy(resolved_entity)
        self._hashable_entity = copy.deepcopy(hashable_entity)
        self._exp = round(time.time() + exp)
        self.ts = time.time()

    @property
    def expired(self) -> bool:
        return self._exp < time.time()

    def __eq__(self, record: "CacheRecordEntity") -> bool:
        return hash(record) == hash(self)

    def __hash__(self) -> int:
        return hash(self._hashable_entity)

    def __str__(self) -> str:
        return f"CacheRecordEntity of {self.entity}"

    def __repr__(self) -> str:
        return (
            f"CacheRecordEntity(entity={type(self.entity).__name__}(...),"
            f" exp={self._exp})"
        )

class CacheRecordPerms:
    def __init__(
        self,
        hashable_entity: "Hashable",
        hashable_user: "Hashable",
        resolved_perms: EntityLike,
        exp: int,
    ):
        self.perms = copy.deepcopy(resolved_perms)
        self._hashable_entity = copy.deepcopy(hashable_entity)
        self._hashable_user = copy.deepcopy(hashable_user)
        self._exp = round(time.time() + exp)
        self.ts = time.time()

    @property
    def expired(self) -> bool:
        return self._exp < time.time()

    def __eq__(self, record: "CacheRecordPerms") -> bool:
        return hash(record) == hash(self)

    def __hash__(self) -> int:
        return hash((self._hashable_entity, self._hashable_user))

    def __str__(self) -> str:
        return f"CacheRecordPerms of {self.perms}"

    def __repr__(self) -> str:
        return (
            f"CacheRecordPerms(perms={type(self.perms).__name__}(...), exp={self._exp})"
        )

class CacheRecordFullChannel:
    def __init__(self, channel_id: int, full_channel: ChannelFull, exp: int):
        self.channel_id = channel_id
        self.full_channel = full_channel
        self._exp = round(time.time() + exp)
        self.ts = time.time()

    @property
    def expired(self) -> bool:
        return self._exp < time.time()

    def __eq__(self, record: "CacheRecordFullChannel") -> bool:
        return hash(record) == hash(self)

    def __hash__(self) -> int:
        return hash((self._hashable_entity, self._hashable_user))

    def __str__(self) -> str:
        return f"CacheRecordFullChannel of {self.channel_id}"

    def __repr__(self) -> str:
        return (
            f"CacheRecordFullChannel(channel_id={self.channel_id}(...),"
            f" exp={self._exp})"
        )

class CacheRecordFullUser:
    def __init__(self, user_id: int, full_user: UserFull, exp: int):
        self.user_id = user_id
        self.full_user = full_user
        self._exp = round(time.time() + exp)
        self.ts = time.time()

    @property
    def expired(self) -> bool:
        return self._exp < time.time()

    def __eq__(self, record: "CacheRecordFullUser") -> bool:
        return hash(record) == hash(self)

    def __hash__(self) -> int:
        return hash((self._hashable_entity, self._hashable_user))

    def __str__(self) -> str:
        return f"CacheRecordFullUser of {self.user_id}"

    def __repr__(self) -> str:
        return f"CacheRecordFullUser(channel_id={self.user_id}(...), exp={self._exp})"

def get_commands(mod: Module) -> dict:
    return _get_members(mod, "cmd", "is_command")

def get_inline_handlers(mod: Module) -> dict:
    return _get_members(mod, "_inline_handler", "is_inline_handler")

def get_callback_handlers(mod: Module) -> dict:
    return _get_members(mod, "_callback_handler", "is_callback_handler")

def get_watchers(mod: Module) -> dict:
    return _get_members(
        mod,
        "watcher",
        "is_watcher",
        strict=True,
    )
