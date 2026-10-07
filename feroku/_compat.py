# CopyLeft 2026 github.com/i-execute // i_execute.t.me
# Licensed under AGPLv3.

# (c) Dan Gazizullin, 2021-2023. This file is part of the Hikka Userbot: github.com/hikariatama/Hikka




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
    return name


def install_inline_type_compat(namespace: dict, markup) -> None:
    namespace["HerokuReplyMarkup"] = markup


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
):
    from telethon import functions, utils
    from telethon.tl import types as tl_types

    if isinstance(
        entity,
        (tl_types.InputBotInlineMessageID, tl_types.InputBotInlineMessageID64),
    ):
        text = text or message
        message = entity
    elif isinstance(entity, tl_types.Message):
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
    )
    return self._get_response_message(request, await self(request), entity)


_original_send_message = None
_original_send_file = None


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


async def _send_message(self, *args, invert_media=False, **kwargs):
    result = await _original_send_message(self, *args, **kwargs)
    if not invert_media:
        return result
    return await _apply_invert_media(
        self,
        result,
        kwargs.get("link_preview", True),
    )


async def _send_file(self, *args, invert_media=False, **kwargs):
    result = await _original_send_file(self, *args, **kwargs)
    if not invert_media:
        return result
    return await _apply_invert_media(self, result)


def install_telethon_compat():
    global _original_send_file, _original_send_message

    from telethon.client.messages import MessageMethods
    from telethon.client.uploads import UploadMethods

    if "invert_media" not in inspect.signature(MessageMethods.edit_message).parameters:
        MessageMethods.edit_message = _edit_message
    if "invert_media" not in inspect.signature(MessageMethods.send_message).parameters:
        _original_send_message = MessageMethods.send_message
        MessageMethods.send_message = _send_message
    if "invert_media" not in inspect.signature(UploadMethods.send_file).parameters:
        _original_send_file = UploadMethods.send_file
        UploadMethods.send_file = _send_file


class _TelethonCompatModule(types.ModuleType):
    def __getattr__(self, name: str):
        import telethon

        try:
            real = getattr(telethon, name)
        except AttributeError:
            root = self.__name__.split(".", 1)[0]
            raise AttributeError(f"module '{root}' has no attribute '{name}'") from None

        setattr(self, name, real)
        return real


def _install() -> None:
    for alias in ("herokutl", "hikkatl"):
        if alias in sys.modules:
            continue
        module = _TelethonCompatModule(alias)
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
    module.__dict__.update(
        {key: value for key, value in vars(real).items() if not key.startswith("__")}
    )
    sys.modules[module_name] = module
    return module


_install()

for _alias in ("herokutl", "hikkatl"):
    for _path in (
        "errors",
        "errors.common",
        "errors.rpcerrorlist",
        "network",
        "network.requeststate",
        "tl",
        "tl.tlobject",
        "tl.types",
        "types",
    ):
        _install_submodule(_alias, _path)

install_telethon_compat()
