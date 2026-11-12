# CopyLeft 2026 github.com/i-execute // i_execute.t.me
# Licensed under AGPLv3.

# (c) Dan Gazizullin, 2021-2023. This file is part of the Hikka Userbot: github.com/hikariatama/Hikka

import ast
import asyncio
import collections
import contextlib
import copy
import importlib
import inspect
import logging
import os
import re
import sys
import time
import typing
from dataclasses import dataclass, field
from importlib.abc import SourceLoader
from collections.abc import Hashable

from telethon.hints import EntityLike
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.types import Channel, ChannelForbidden, ChannelFull, Message, UserFull

from ._compat import install_public_type_compat, match_legacy_minimum
from ._reference_finder import replace_all_refs
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
    "get_guest_handlers",
    "InlineDownError",
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

    async def inline_ready(self):
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
        self.allclients = self.allmodules.allclients
        self.tg_id: int = self._client.tg_id
        self._tg_id: int = self._client.tg_id

    def create_task(self, coroutine, *, name=None):
        if getattr(self, "_unloading", False):
            coroutine.close()
            raise RuntimeError("Module is unloading")
        if "_managed_tasks" not in self.__dict__:
            self._managed_tasks = set()
        task = asyncio.create_task(coroutine, name=name)
        self._managed_tasks.add(task)
        task.add_done_callback(self._managed_tasks.discard)
        return task

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

    feroku_commands = commands
    heroku_commands = commands
    hikka_commands = commands
    ataraxia_commands = commands

    @property
    def inline_handlers(self) -> dict[str, Command]:
        return get_inline_handlers(self)

    feroku_inline_handlers = inline_handlers
    heroku_inline_handlers = inline_handlers
    hikka_inline_handlers = inline_handlers
    ataraxia_inline_handlers = inline_handlers

    @property
    def callback_handlers(self) -> dict[str, Command]:
        return get_callback_handlers(self)

    feroku_callback_handlers = callback_handlers
    heroku_callback_handlers = callback_handlers
    hikka_callback_handlers = callback_handlers
    ataraxia_callback_handlers = callback_handlers

    @property
    def watchers(self) -> dict[str, Command]:
        return get_watchers(self)

    feroku_watchers = watchers
    heroku_watchers = watchers
    hikka_watchers = watchers
    ataraxia_watchers = watchers

    @property
    def guest_handlers(self) -> dict[str, Command]:
        return get_guest_handlers(self)

    ataraxia_guest_handlers = guest_handlers

    @commands.setter
    def commands(self, _):
        pass

    @inline_handlers.setter
    def inline_handlers(self, _):
        pass

    @callback_handlers.setter
    def callback_handlers(self, _):
        pass

    @watchers.setter
    def watchers(self, _):
        pass

    @guest_handlers.setter
    def guest_handlers(self, _):
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

    async def _approve_join(self, call, channel, event):
        try:
            await self._client(JoinChannelRequest(channel))
            event.status = True
        finally:
            event.set()
            with contextlib.suppress(Exception):
                await call.delete()

    async def _decline_join(self, call, channel, event):
        declined = self._db.get("feroku.main", "declined_joins", [])
        if channel.id not in declined:
            self._db.set("feroku.main", "declined_joins", [*declined, channel.id])
        event.status = False
        event.set()
        with contextlib.suppress(Exception):
            await call.delete()

    async def request_join(
        self,
        peer: EntityLike,
        reason: str,
        assure_joined: bool | None = False,
    ) -> bool:
        """Ask the owner before joining a channel required by a module."""
        from . import utils

        channel = await self.client.get_entity(peer)
        if isinstance(channel, ChannelForbidden):
            if assure_joined:
                raise LoadError(f"Joining {peer} is required, but the account is banned")
            return False
        if not isinstance(channel, Channel):
            raise TypeError("peer must be a channel")
        if not getattr(channel, "left", True):
            return True

        declined = self._db.get("feroku.main", "declined_joins", [])
        if channel.id in declined:
            if assure_joined:
                raise LoadError(f"Joining {peer} is required to use this module")
            return False
        if not getattr(self.inline, "init_complete", False):
            if assure_joined:
                raise LoadError("Inline mode is required to confirm a channel join")
            return False

        event = asyncio.Event()
        event.status = False
        title = utils.escape_html(getattr(channel, "title", str(peer)))
        await self.inline.bot.send_message(
            self.tg_id,
            (
                f"<b>{utils.escape_html(self.__class__.__name__)}</b> requests permission "
                f"to join <b>{title}</b>.\n<blockquote>{utils.escape_html(reason)}</blockquote>"
            ),
            reply_markup=self.inline.generate_markup(
                [
                    {
                        "text": "Approve",
                        "callback": self._approve_join,
                        "args": (channel, event),
                    },
                    {
                        "text": "Decline",
                        "callback": self._decline_join,
                        "args": (channel, event),
                    },
                ]
            ),
        )
        await event.wait()
        if assure_joined and not event.status:
            raise LoadError(f"Joining {peer} is required to use this module")
        return event.status

    async def import_lib(
        self,
        url: str,
        *,
        suspend_on_error: bool | None = False,
        _did_requirements: bool = False,
    ) -> "Library":
        """Download, initialize, and register a compatible external library."""
        import requests

        from . import loader, main, utils

        def fail(error):
            if suspend_on_error:
                raise SelfSuspend("Required library is unavailable or invalid") from error
            raise error

        if not utils.check_url(url):
            fail(ValueError("Invalid library URL"))

        response = await utils.run_sync(requests.get, url, timeout=30)
        response.raise_for_status()
        code = response.text

        minimum = re.search(
            r"# ?scope: ?feroku_min ((?:\d+\.){2}\d+)",
            code,
        ) or match_legacy_minimum(code)
        if minimum and main.__version__ < tuple(map(int, minimum.group(1).split("."))):
            fail(RuntimeError(f"Library requires version {minimum.group(1)} or newer"))

        module_name = f"feroku.libraries.{url.replace('%', '%%').replace('.', '%d')}"
        origin = f"<library {url}>"
        spec = importlib.machinery.ModuleSpec(
            module_name,
            StringLoader(code, origin),
            origin=origin,
        )
        try:
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        except ImportError as error:
            if reason := loader.unsupported_import(error):
                fail(ImportError(reason, name=error.name))
            match = loader.VALID_PIP_PACKAGES.search(code)
            requirements = (
                [item for item in map(str.strip, match.group(1).split()) if item]
                if match
                else [error.name.split(".", 1)[0]]
                if getattr(error, "name", None)
                else []
            )
            if _did_requirements or not requirements:
                fail(error)
            if not await loader.pip_install(requirements):
                fail(error)
            importlib.invalidate_caches()
            return await self.import_lib(
                url,
                suspend_on_error=suspend_on_error,
                _did_requirements=True,
            )

        lib_obj = next(
            (
                value()
                for value in vars(module).values()
                if inspect.isclass(value)
                and issubclass(value, Library)
                and value is not Library
                and value.__module__ == module.__name__
            ),
            None,
        )
        if lib_obj is None:
            fail(ImportError("Invalid library: no Library subclass found"))
        if not lib_obj.__class__.__name__.endswith("Lib"):
            fail(ImportError("Library class name must end with Lib"))

        lib_obj.source_url = url.rstrip("/")
        lib_obj.allmodules = self.allmodules
        lib_obj.internal_init()
        for old_lib in self.allmodules.libraries:
            if old_lib.name == lib_obj.name and (
                not isinstance(getattr(old_lib, "version", None), tuple)
                or not isinstance(getattr(lib_obj, "version", None), tuple)
                or old_lib.version >= lib_obj.version
            ):
                return old_lib

        if hasattr(lib_obj, "init"):
            if not callable(lib_obj.init):
                fail(ValueError("Library init must be callable"))
            try:
                await lib_obj.init()
            except Exception as error:
                failure = RuntimeError("Library init failed")
                failure.__cause__ = error
                fail(failure)

        if hasattr(lib_obj, "config"):
            if not isinstance(lib_obj.config, LibraryConfig):
                fail(RuntimeError("Library config must be LibraryConfig"))
            stored = lib_obj.db.get(lib_obj.__class__.__name__, "__config__", {})
            for option in lib_obj.config:
                with contextlib.suppress(Exception):
                    lib_obj.config.set_no_raise(
                        option,
                        stored.get(
                            option,
                            os.environ.get(f"{lib_obj.__class__.__name__}.{option}")
                            or lib_obj.config.getdef(option),
                        ),
                    )

        if isinstance(getattr(lib_obj, "strings", None), dict):
            lib_obj.strings = Strings(lib_obj)
        for old_lib in list(self.allmodules.libraries):
            if old_lib.name != lib_obj.name:
                continue
            if callable(getattr(old_lib, "on_lib_update", None)):
                await old_lib.on_lib_update(lib_obj)
            replace_all_refs(old_lib, lib_obj)
            self.allmodules.libraries.remove(old_lib)
        self.allmodules.libraries.append(lib_obj)
        return lib_obj

    def get(
        self,
        key: str,
        default: JSONSerializable | None = None,
    ) -> JSONSerializable:
        return self._db.get(self.__class__.__name__, key, default)

    def set(self, key: str, value: JSONSerializable) -> bool:
        return self._db.set(self.__class__.__name__, key, value)

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
        self.allclients = self.allmodules.allclients

    def _lib_get(
        self,
        key: str,
        default: JSONSerializable | None = None,
    ) -> JSONSerializable:
        return self._db.get(self.__class__.__name__, key, default)

    def _lib_set(self, key: str, value: JSONSerializable) -> bool:
        return self._db.set(self.__class__.__name__, key, value)

    def _lib_pointer(
        self,
        key: str,
        default: JSONSerializable | None = None,
    ) -> JSONSerializable | PointerDict | PointerList:
        return self._db.pointer(self.__class__.__name__, key, default)

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

class InlineDownError(AttributeError):
    def __init__(self):
        super().__init__(
            "Inline bot is not running because initialization has not completed"
        )

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

def get_guest_handlers(mod: Module) -> dict:
    return _get_members(mod, "_guest_handler", "is_guest_handler")

def get_watchers(mod: Module) -> dict:
    return _get_members(
        mod,
        "watcher",
        "is_watcher",
        strict=True,
    )
