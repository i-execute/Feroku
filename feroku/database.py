# CopyLeft 2026 github.com/i-execute // i_execute.t.me
# Licensed under AGPLv3.

# (c) Dan Gazizullin, 2021-2023. This file is part of the Hikka Userbot: github.com/hikariatama/Hikka

import collections
import copy
import json
import logging
import re
import time

import typing

from telethon import utils as tl_utils
from telethon.tl.types import PeerChannel, User

from . import main, utils
from ._compat_database import migrate_database_items
from .pointers import (
    BaseSerializingMiddlewareDict,
    BaseSerializingMiddlewareList,
    NamedTupleMiddlewareDict,
    NamedTupleMiddlewareList,
    PointerDict,
    PointerList,
)
from .tl_cache import CustomTelegramClient
from .types import JSONSerializable

__all__ = [
    "Database",
    "PointerList",
    "PointerDict",
    "NamedTupleMiddlewareDict",
    "NamedTupleMiddlewareList",
    "BaseSerializingMiddlewareDict",
    "BaseSerializingMiddlewareList",
]

logger = logging.getLogger(__name__)

class NoAssetsChannel(Exception):
    pass
class NoContentChannel(Exception):
    pass
class Database(dict):
    def __init__(self, client: CustomTelegramClient):
        super().__init__()
        self._client: CustomTelegramClient = client
        self._next_revision_call: int = 0
        self._revisions: list[dict] = []
        self._me: User = None

    def __repr__(self):
        return object.__repr__(self)

    async def init(self):
        self._db_file = main.BASE_PATH / f"config-{self._client.tg_id}.json"
        self.read()

    async def ensure_content_channel(self):
        content_channel = None
        existing_channel_id = self.get("feroku.forums", "channel_id", None)

        if existing_channel_id:
            stored_channel_id = int(existing_channel_id)
            channel_id = (
                tl_utils.resolve_id(stored_channel_id)[0]
                if stored_channel_id < 0
                else stored_channel_id
            )
            try:
                content_channel = await self._client.get_entity(
                    PeerChannel(channel_id)
                )
            except Exception:
                async for dialog in self._client.iter_dialogs():
                    if getattr(dialog.entity, "id", None) == channel_id:
                        content_channel = dialog.entity
                        break
            if content_channel:
                logger.debug(
                    "Found configured content channel with ID %s",
                    channel_id,
                )
                if stored_channel_id != channel_id:
                    self.set("feroku.forums", "channel_id", channel_id)
            else:
                logger.warning(
                    "Configured content channel %s is inaccessible and will be recreated",
                    channel_id,
                )
                self.set("feroku.forums", "forums_cache", {"feroku-userbot": {}})

        if not content_channel:
            content_channel, _ = await utils.asset_channel(
                client=self._client,
                title="feroku-userbot",
                description=" Content related to Feroku will be here",
                silent=True,
                invite_bot=True,
                avatar=utils.get_asset_path("Feroku.PNG"),
                forum=True,
                hide_general=True,
                _folder="feroku",
                force_new=True,
            )
            self.set("feroku.forums", "channel_id", int(content_channel.id))

        for title, description in (
            ("Logs", " Inline logs and error reports will be stored here"),
            ("Backups", " Your Feroku backups will be stored here"),
        ):
            if not await utils.get_topic_id(self, title):
                await utils.asset_forum_topic(
                    self._client,
                    self,
                    content_channel,
                    title,
                    description,
                    5877307202888273539,
                    invite_bot=True,
                )

        return content_channel

    def read(self):
        try:
            db = self._db_file.read_text()
            if re.search(r'"(legacy\.)(\S+\":)', db):
                logging.warning("Converting db after update")
                db = re.sub(r"(legacy\.)(\S+\":)", lambda m: "feroku." + m.group(2), db)
            self._update_from_read(migrate_database_items(json.loads(db)))
        except json.decoder.JSONDecodeError:
            logger.warning("Database read failed! Backing up corrupted file...")
            try:
                import os, time

                os.replace(
                    self._db_file,
                    self._db_file.with_suffix(f".corrupt.{int(time.time())}"),
                )
            except OSError:
                pass
        except FileNotFoundError:
            logger.debug("Database file not found, creating new one...")

    def _update_from_read(self, items: dict) -> None:
        super().update(items)

    def process_db_autofix(self, db: dict) -> bool:
        if not utils.is_serializable(db):
            return False

        for key, value in db.copy().items():
            if not isinstance(key, (str, int)):
                logger.warning(
                    "DbAutoFix: Dropped key %s, because it is not string or int",
                    key,
                )
                continue

            if not isinstance(value, dict):

                del db[key]
                logger.warning(
                    "DbAutoFix: Dropped key %s, because it is non-dict, but %s",
                    key,
                    type(value),
                )
                continue

            for subkey in value:
                if not isinstance(subkey, (str, int)):
                    del db[key][subkey]
                    logger.warning(
                        (
                            "DbAutoFix: Dropped subkey %s of db key %s, because it is"
                            " not string or int"
                        ),
                        subkey,
                        key,
                    )
                    continue

        return True

    def save(self) -> bool:
        if not self.process_db_autofix(self):
            try:
                rev = self._revisions.pop()
                while not self.process_db_autofix(rev):
                    rev = self._revisions.pop()
            except IndexError:
                raise RuntimeError(
                    "Can't find revision to restore broken database from "
                    "database is most likely broken and will lead to problems, "
                    "so its save is forbidden."
                )

            self.clear()
            self.update(**rev)

            raise RuntimeError(
                "Rewriting database to the last revision because new one destructed it"
            )

        if self._next_revision_call < time.time():
            self._revisions += [dict(self)]
            self._next_revision_call = time.time() + 3

        while len(self._revisions) > 15:
            self._revisions.pop()

        try:
            tmp = self._db_file.with_suffix(self._db_file.suffix + ".tmp")
            tmp.write_text(json.dumps(self, indent=4))
            import os

            os.replace(tmp, self._db_file)
        except Exception:
            logger.exception("Database save failed!")
            return False

        return True

    def get(
        self,
        owner: str,
        key: str,
        default: JSONSerializable | None = None,
    ) -> JSONSerializable:
        return copy.deepcopy(self._get_raw(owner, key, default))

    def _get_raw(
        self,
        owner: str,
        key: str,
        default: JSONSerializable | None = None,
    ) -> JSONSerializable:
        if owner == "heroku" or owner.startswith("heroku."):
            owner = f"feroku{owner[6:]}"
        try:
            return self[owner][key]
        except KeyError:
            return default

    def set(self, owner: str, key: str, value: JSONSerializable) -> bool:
        if not utils.is_serializable(owner):
            raise RuntimeError(
                "Attempted to write object to "
                f"{owner=} ({type(owner)=}) of database. It is not "
                "JSON-serializable key which will cause errors"
            )

        if not utils.is_serializable(key):
            raise RuntimeError(
                "Attempted to write object to "
                f"{key=} ({type(key)=}) of database. It is not "
                "JSON-serializable key which will cause errors"
            )

        if not utils.is_serializable(value):
            raise RuntimeError(
                "Attempted to write object of "
                f"{key=} ({type(value)=}) to database. It is not "
                "JSON-serializable value which will cause errors"
            )

        super().setdefault(owner, {})[key] = value
        return self.save()

    def __setitem__(self, owner: str, value: JSONSerializable) -> None:
        if not utils.is_serializable(owner):
            raise RuntimeError(
                "Attempted to write object to "
                f"{owner=} ({type(owner)=}) of database. It is not "
                "JSON-serializable key which will cause errors"
            )

        if not utils.is_serializable(value):
            raise RuntimeError(
                "Attempted to write object of "
                f"{owner=} ({type(value)=}) to database. It is not "
                "JSON-serializable value which will cause errors"
            )

        super().__setitem__(owner, value)

    def update(self, *args, **kwargs) -> None:
        items = dict(*args, **kwargs)
        return super().update(items)

    def pointer(
        self,
        owner: str,
        key: str,
        default: JSONSerializable | None = None,
        item_type: typing.Any | None = None,
    ) -> JSONSerializable | PointerList | PointerDict:
        value = self._get_raw(owner, key, default)
        mapping = {
            list: PointerList,
            dict: PointerDict,
            collections.abc.Hashable: lambda v: v,
        }

        pointer_constructor = next(
            (pointer for type_, pointer in mapping.items() if isinstance(value, type_)),
            None,
        )

        if (current_value := self._get_raw(owner, key, None)) and type(
            current_value
        ) is not type(default):
            raise ValueError(
                f"Can't switch the type of pointer in database (current: {type(current_value)}, requested: {type(default)})"
            )

        if pointer_constructor is None:
            raise ValueError(
                f"Pointer for type {type(value).__name__} is not implemented"
            )

        if item_type is not None:
            if isinstance(value, list):
                for item in self._get_raw(owner, key, default):
                    if not isinstance(item, dict):
                        raise ValueError(
                            "Item type can only be specified for dedicated keys and"
                            " can't be mixed with other ones"
                        )

                return NamedTupleMiddlewareList(
                    pointer_constructor(self, owner, key, default),
                    item_type,
                )
            if isinstance(value, dict):
                for item in self._get_raw(owner, key, default).values():
                    if not isinstance(item, dict):
                        raise ValueError(
                            "Item type can only be specified for dedicated keys and"
                            " can't be mixed with other ones"
                        )

                return NamedTupleMiddlewareDict(
                    pointer_constructor(self, owner, key, default),
                    item_type,
                )

        return pointer_constructor(self, owner, key, default)
