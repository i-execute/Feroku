# CopyLeft 2026 github.com/i-execute // i_execute.t.me
# Licensed under AGPLv3.

import importlib
import inspect
import logging
import os
import re
import shutil
import sys
import types

def redirect_import(name: str) -> str:
    if name == "heroku" or name.startswith("heroku."):
        return f"feroku{name[6:]}"
    if name == "hikka" or name.startswith("hikka."):
        return f"feroku{name[5:]}"
    if name.startswith("hikkatl"):
        return f"telethon{name[7:]}"
    if name.startswith("herokutl"):
        return f"telethon{name[8:]}"
    if name.startswith("ataraxiatl"):
        return f"telethon{name[10:]}"
    return name


def install_inline_type_compat(namespace: dict, markup) -> None:
    namespace["HerokuReplyMarkup"] = markup


def install_inline_token_compat(manager, token: str) -> None:
    manager._token = token
    if getattr(manager, "bot", None) is not None:
        manager.bot.token = token


def install_public_type_compat(namespace: dict, markup) -> None:
    namespace["HerokuReplyMarkup"] = markup
    namespace["__all__"].append("HerokuReplyMarkup")


def install_exception_compat(namespace: dict, exception) -> None:
    namespace["HerokuException"] = exception


def install_main_compat(namespace: dict, application, instance) -> None:
    namespace["Heroku"] = application
    namespace["heroku"] = instance


def resolve_asset_name(name: str) -> str:
    return "Feroku.PNG" if name == "Heroku.PNG" else name


def install_rich_compat(module) -> None:
    for name in (
        "telethon.extensions.rich",
        "herokutl.extensions.rich",
        "hikkatl.extensions.rich",
        "ataraxiatl.extensions.rich",
    ):
        sys.modules[name] = module

    rich_html = importlib.import_module("feroku.utils.rich_html")
    telethon_html = importlib.import_module("telethon.extensions.html")
    telethon_html.__dict__.update(
        {
            name: value
            for name, value in vars(rich_html).items()
            if not name.startswith("__")
        }
    )
    for package_name in ("telethon.extensions", "herokutl.extensions", "hikkatl.extensions", "ataraxiatl.extensions"):
        package = sys.modules.get(package_name)
        if package is not None:
            package.rich = module
            package.html = telethon_html if package_name == "telethon.extensions" else rich_html
    for name in (
        "herokutl.extensions.html",
        "hikkatl.extensions.html",
        "ataraxiatl.extensions.html",
    ):
        sys.modules[name] = rich_html


def migrate_legacy_sessions(base_dir: str, sessions_dir: str) -> None:
    with os.scandir(base_dir) as entries:
        legacy = [
            entry
            for entry in entries
            if entry.is_file()
            and entry.name.startswith("heroku-")
            and ".session" in entry.name
        ]
    for entry in legacy:
        target = os.path.join(sessions_dir, f"feroku-{entry.name[7:]}")
        if os.path.exists(target):
            continue
        try:
            shutil.move(entry.path, target)
        except OSError:
            logging.exception("Failed to migrate legacy session file %s", entry.path)

    with os.scandir(sessions_dir) as entries:
        legacy = [
            entry
            for entry in entries
            if entry.is_file() and entry.name.startswith("heroku-")
        ]
    for entry in legacy:
        target = os.path.join(sessions_dir, f"feroku-{entry.name[7:]}")
        if os.path.exists(target):
            continue
        try:
            os.replace(entry.path, target)
        except OSError:
            logging.exception("Failed to rename legacy session file %s", entry.path)


def match_legacy_minimum(doc: str):
    return re.search(r"# ?scope: ?heroku_min ((?:\d+\.){2}\d+)", doc)


def is_project_import(name: str) -> bool:
    return name.split(".", maxsplit=1)[0].lower() in {"feroku", "hikka", "heroku"}


async def _edit_message(
    self,
    entity,
    message=None,
    text=None,
    *,
    parse_mode=(),
    attributes=None,
    formatting_entities=None,
    link_preview=True,
    file=None,
    thumb=None,
    invert_media=False,
    force_document=False,
    buttons=None,
    supports_streaming=False,
    schedule=None,
    rich=None,
):
    from telethon import functions, utils
    from telethon.tl import types as tl_types

    rich_input = _to_input_rich(rich) if rich is not None else None
    if rich is not None and text is None and not isinstance(message, str):
        text = _rich_fallback_text(rich)
        parse_mode = None

    if isinstance(
        entity,
        (tl_types.InputBotInlineMessageID, tl_types.InputBotInlineMessageID64),
    ):
        text = text or message
        message = entity
    elif isinstance(entity, tl_types.Message):
        if rich is None:
            text = message
        message = entity
        entity = entity.peer_id
    if formatting_entities is None:
        text, formatting_entities = await self._parse_message_text(text, parse_mode)
    _, media, _ = await self._file_to_media(
        file,
        supports_streaming=supports_streaming,
        thumb=thumb,
        attributes=attributes,
        force_document=force_document,
    )
    if isinstance(
        entity,
        (tl_types.InputBotInlineMessageID, tl_types.InputBotInlineMessageID64),
    ):
        request = functions.messages.EditInlineBotMessageRequest(
            id=entity,
            message=text,
            no_webpage=not link_preview,
            invert_media=invert_media,
            entities=formatting_entities,
            media=media,
            reply_markup=self.build_reply_markup(buttons),
            rich_message=rich_input,
        )
        if self.session.dc_id != entity.dc_id:
            sender = await self._borrow_exported_sender(entity.dc_id)
            try:
                return await self._call(sender, request)
            finally:
                await self._return_exported_sender(sender)
        return await self(request)
    entity = await self.get_input_entity(entity)
    request = functions.messages.EditMessageRequest(
        peer=entity,
        id=utils.get_message_id(message),
        message=text,
        no_webpage=not link_preview,
        invert_media=invert_media,
        entities=formatting_entities,
        media=media,
        reply_markup=self.build_reply_markup(buttons),
        schedule_date=schedule,
        rich_message=rich_input,
    )
    return self._get_response_message(request, await self(request), entity)


_original_send_message = None
_original_send_file = None
_original_forward_messages = None

_ATARAXIA_SEND_MESSAGE_KWARGS = (
    "noforwards",
    "update_stickersets_order",
    "allow_paid_floodskip",
    "schedule_repeat_period",
    "quick_reply_shortcut",
    "allow_paid_stars",
    "suggested_post",
)
_ATARAXIA_SEND_FILE_KWARGS = _ATARAXIA_SEND_MESSAGE_KWARGS + ("workers",)


def _to_input_rich(value):
    if value is None or type(value).__name__.startswith("InputRichMessage"):
        return value
    from telethon.tl.types import InputRichMessageMarkdown

    if isinstance(value, str):
        return InputRichMessageMarkdown(markdown=value)
    from .utils.rich import to_input

    return to_input(value)


def _rich_fallback_text(value):
    from telethon.extensions import html as html_parser

    if isinstance(value, str):
        return value or " "
    html = getattr(value, "html", None)
    if html:
        text, _ = html_parser.parse(html)
        return text or " "
    markdown = getattr(value, "markdown", None)
    if markdown:
        return str(markdown)
    from .utils.rich import to_text

    return to_text(value) or " "


def _drop_kwargs(kwargs: dict, names: tuple[str, ...]) -> None:
    for name in names:
        kwargs.pop(name, None)


async def _apply_invert_media(client, result, link_preview=True):
    from telethon.tl import types as tl_types

    if isinstance(result, list):
        return [
            await _apply_invert_media(client, message, link_preview)
            for message in result
        ]
    if not isinstance(result, tl_types.Message):
        return result
    return await client.edit_message(
        result,
        result.message or "",
        formatting_entities=result.entities or [],
        link_preview=link_preview,
        invert_media=True,
    )


async def _send_message(self, *args, invert_media=False, rich=None, **kwargs):
    if rich is not None and hasattr(self, "send_rich_message"):
        from telethon import utils as telethon_utils

        if kwargs.get("file") is not None:
            raise ValueError("rich messages cannot be combined with a file")
        entity = args[0] if args else kwargs.get("entity")
        return await self.send_rich_message(
            entity,
            markdown=rich if isinstance(rich, str) else None,
            rich_message=None if isinstance(rich, str) else _to_input_rich(rich),
            reply_to=telethon_utils.get_message_id(kwargs.get("reply_to")),
            buttons=kwargs.get("buttons"),
            silent=kwargs.get("silent"),
        )
    _drop_kwargs(kwargs, _ATARAXIA_SEND_MESSAGE_KWARGS)
    if rich is not None:
        text = _rich_fallback_text(rich)
        args = list(args)
        if len(args) > 1:
            args[1] = text
        else:
            kwargs["message"] = text
        kwargs["parse_mode"] = None
    result = await _original_send_message(self, *args, **kwargs)
    if not invert_media:
        return result
    return await _apply_invert_media(
        self,
        result,
        kwargs.get("link_preview", True),
    )


async def _send_file(self, *args, invert_media=False, **kwargs):
    _drop_kwargs(kwargs, _ATARAXIA_SEND_FILE_KWARGS)
    result = await _original_send_file(self, *args, **kwargs)
    if not invert_media:
        return result
    return await _apply_invert_media(self, result)


async def _forward_messages(
    self,
    entity,
    messages,
    from_peer=None,
    *,
    background=None,
    with_my_score=None,
    silent=None,
    as_album=None,
    schedule=None,
    drop_author=None,
    drop_media_captions=None,
    noforwards=None,
    allow_paid_floodskip=None,
    top_msg_id=None,
    schedule_repeat_period=None,
    send_as=None,
    quick_reply_shortcut=None,
    message_effect_id=None,
    video_timestamp=None,
    allow_paid_stars=None,
    suggested_post=None,
    reply_to=None,
):
    return await _original_forward_messages(
        self,
        entity,
        messages,
        from_peer,
        background=background,
        with_my_score=with_my_score,
        silent=silent,
        as_album=as_album,
        schedule=schedule,
        drop_author=drop_author,
        drop_media_captions=drop_media_captions,
    )


def install_telethon_compat():
    global _original_forward_messages, _original_send_file, _original_send_message

    from telethon.client.messages import MessageMethods
    from telethon.client.uploads import UploadMethods
    from telethon.extensions import html as telethon_html
    from telethon.helpers import add_surrogate, del_surrogate

    aliases = {
        "_add_surrogate": add_surrogate,
        "_del_surrogate": del_surrogate,
        "CUSTOM_EMOJIS": True,
        "DATE_FORMAT": (
            ("r", "relative"),
            ("w", "day_of_week"),
            ("d", "short_date"),
            ("D", "long_date"),
            ("t", "short_time"),
            ("T", "long_time"),
        ),
    }
    for name, value in aliases.items():
        if not hasattr(telethon_html, name):
            setattr(telethon_html, name, value)

    if "invert_media" not in inspect.signature(MessageMethods.edit_message).parameters:
        MessageMethods.edit_message = _edit_message
    if "invert_media" not in inspect.signature(MessageMethods.send_message).parameters:
        _original_send_message = MessageMethods.send_message
        MessageMethods.send_message = _send_message
    if "noforwards" not in inspect.signature(MessageMethods.forward_messages).parameters:
        _original_forward_messages = MessageMethods.forward_messages
        MessageMethods.forward_messages = _forward_messages
    if "invert_media" not in inspect.signature(UploadMethods.send_file).parameters:
        _original_send_file = UploadMethods.send_file
        UploadMethods.send_file = _send_file


class _TelethonCompatModule(types.ModuleType):
    def __getattr__(self, name: str):
        target = self.__dict__.get("_target_name", "telethon")
        real_module = importlib.import_module(target)
        try:
            real = getattr(real_module, name)
        except AttributeError:
            root = self.__name__.split(".", 1)[0]
            raise AttributeError(f"module '{root}' has no attribute '{name}'") from None

        setattr(self, name, real)
        return real


def _install() -> None:
    for alias in ("herokutl", "hikkatl", "ataraxiatl"):
        if alias in sys.modules:
            continue
        module = _TelethonCompatModule(alias)
        module._target_name = "telethon"
        module.__path__ = []
        sys.modules[alias] = module


_original_import_module = importlib.import_module


def _import_module(name: str, package: str | None = None):
    return _original_import_module(redirect_import(name), package)


def install_project_compat() -> None:
    importlib.import_module = _import_module
    for name, module in list(sys.modules.items()):
        if name == "feroku" or name.startswith("feroku."):
            sys.modules.setdefault(f"heroku{name[6:]}", module)


def _install_submodule(alias: str, name: str) -> types.ModuleType:
    import telethon

    real = telethon
    for part in name.split("."):
        real = getattr(real, part)

    module_name = f"{alias}.{name}"
    module = sys.modules.get(module_name)
    if module is not None and type(module) is _TelethonCompatModule:
        return module

    module = _TelethonCompatModule(module_name)
    module._target_name = f"telethon.{name}"
    module.__dict__.update(
        {key: value for key, value in vars(real).items() if not key.startswith("__")}
    )
    if hasattr(real, "__path__"):
        module.__path__ = []
    sys.modules[module_name] = module
    return module


_install()

for _alias in ("herokutl", "hikkatl", "ataraxiatl"):
    for _path in (
        "client",
        "client.messages",
        "client.uploads",
        "custom",
        "errors",
        "errors.common",
        "errors.rpcbaseerrors",
        "errors.rpcerrorlist",
        "events",
        "extensions",
        "extensions.html",
        "extensions.markdown",
        "functions",
        "helpers",
        "hints",
        "network",
        "network.requeststate",
        "password",
        "sessions",
        "tl",
        "tl.custom",
        "tl.custom.message",
        "tl.tlobject",
        "tl.types",
        "types",
        "utils",
    ):
        _install_submodule(_alias, _path)

install_telethon_compat()