# CopyLeft 2026 github.com/i-execute // i_execute.t.me
# Licensed under AGPLv3.

# (c) Dan Gazizullin, 2021-2023. This file is part of the Hikka Userbot: github.com/hikariatama/Hikka

import datetime
import io
import logging
import os
import zipfile
import orjson
import requests

from pathlib import Path

from telethon.tl.types import Message

from .. import loader, utils
from .._compat_database import prepare_backup_database

logger = logging.getLogger(__name__)


def _without_inline_bot_token(value):
    if not isinstance(value, dict):
        return value
    result = dict(value)
    inline = result.get("feroku.inline")
    if isinstance(inline, dict):
        inline = dict(inline)
        inline.pop("bot_token", None)
        result["feroku.inline"] = inline
    return result


@loader.tds
class Backup(loader.Module):

    strings = {
        "name": "Backup",
        "backupall_info": "<b>Feroku backup</b>\n<blockquote>This file contains private data. Keep it secure. To restore it, reply with <code>{prefix}restore</code>.</blockquote>",
        "restoring_backup": "<b>Restoring backup</b>\n<blockquote>Database and modules are being restored.</blockquote>",
        "all_restored": "<b>Backup restored</b>\n<blockquote>Feroku is restarting.</blockquote>",
        "reply_to_file": "<b>Backup file required</b>\n<blockquote>Reply to a JSON or Feroku backup file.</blockquote>",
        "db_restored": "<b>Database restored</b>\n<blockquote>Feroku is restarting.</blockquote>",
        "backupall_sent": "<b>Backup created</b>\n<blockquote><a href=\"{}\">Open backup</a></blockquote>",
        "backup_failed": "<b>Backup failed</b>\n<blockquote>Check the service logs for details</blockquote>",
        "_cls_doc": "Processes database and module backups",
    }

    async def client_ready(self):
        self._content_channel_id = await utils.wait_for_content_channel(self._db)

    @staticmethod
    def _message_id(message) -> int:
        if isinstance(message, (list, tuple)) and message:
            message = message[0]
        message_id = getattr(message, "message_id", None) or getattr(
            message, "id", None
        )
        if message_id is None and isinstance(message, dict):
            message_id = message.get("message_id") or message.get("id")
        if not isinstance(message_id, int):
            raise RuntimeError("Backup message ID is unavailable")
        return message_id

    def _build_archive(self) -> io.BytesIO:
        database_file = io.BytesIO(
            orjson.dumps(
                _without_inline_bot_token(dict(self._db)),
                option=orjson.OPT_INDENT_2 | orjson.OPT_NON_STR_KEYS,
            )
        )
        modules_file = io.BytesIO()
        with zipfile.ZipFile(modules_file, "w", zipfile.ZIP_DEFLATED) as archive:
            for root, _, files in os.walk(loader.MODULES_DIR):
                for filename in files:
                    if filename.endswith(".py"):
                        path = os.path.join(root, filename)
                        with open(path, "rb") as module_file:
                            archive.writestr(filename, module_file.read())
        result = io.BytesIO()
        with zipfile.ZipFile(result, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("db.json", database_file.getvalue())
            archive.writestr("mods.zip", modules_file.getvalue())
        result.seek(0)
        result.name = f"Feroku-{datetime.datetime.now():%d-%m-%Y-%H-%M}.backup"
        return result

    async def _send_backup(self, caption: str | None = None):
        caption = caption or self.strings["backupall_info"].format(
            prefix=utils.escape_html(self.get_prefix())
        )
        backup_topic_id = await utils.get_topic_id(self._db, "Backups")
        if not backup_topic_id:
            raise RuntimeError("Backups topic not found in database")
        message = await self.inline.bot.send_document(
            int(f"-100{self._content_channel_id}"),
            self._build_archive(),
            caption=caption,
            message_thread_id=backup_topic_id,
        )
        self.set("last_backup", round(datetime.datetime.now().timestamp()))
        return message, backup_topic_id

    @loader.loop(interval=3600, autostart=True)
    async def handler(self):
        try:
            await self._send_backup()
        except loader.StopLoop:
            raise
        except Exception:
            logger.exception("Backup failed")

    @loader.command()
    async def backup(self, message: Message):
        try:
            backup_message, backup_topic_id = await self._send_backup(
                self.strings["backupall_info"].format(
                    prefix=utils.escape_html(self.get_prefix())
                )
            )
        except Exception:
            logger.exception("Backup failed")
            await utils.answer(message, self.strings["backup_failed"])
            return
        await utils.answer(
            message,
            self.strings["backupall_sent"].format(
                f"https://t.me/c/{self._content_channel_id}/{backup_topic_id}/"
                f"{self._message_id(backup_message)}"
            ),
        )



    @loader.command()
    async def restore(self, message: Message):
        if not (reply := await message.get_reply_message()) or not reply.media:
            await utils.answer(message, self.strings["reply_to_file"])
            return

        file = await reply.download_media(bytes)

        try:
            decoded_text = orjson.loads(file.decode())
        except (UnicodeDecodeError, orjson.JSONDecodeError):
            decoded_text = None

        if decoded_text is not None:
            decoded_text = prepare_backup_database(
                _without_inline_bot_token(decoded_text)
            )

            if not self._db.process_db_autofix(decoded_text):
                raise RuntimeError("Attempted to restore broken database")

            self._db.clear()
            self._db.update(**decoded_text)
            self._db.save()

            await utils.answer(message, self.strings["db_restored"])
            await self.invoke("restart", "-f", peer=message.peer_id)
            return

        status_message = await utils.answer(message, self.strings["restoring_backup"])
        try:
            zipfile_bytes = io.BytesIO(file)
            with zipfile.ZipFile(zipfile_bytes) as zf:
                with zf.open("db.json") as f:
                    db_data = orjson.loads(f.read().decode())

                db_data = prepare_backup_database(
                    _without_inline_bot_token(db_data)
                )

                if not self._db.process_db_autofix(db_data):
                    raise RuntimeError("Attempted to restore broken database")

                self._db.clear()
                self._db.update(**db_data)
                self._db.save()

                if "mods.zip" in zf.namelist():
                    with zf.open("mods.zip") as modzip_bytes:
                        with zipfile.ZipFile(io.BytesIO(modzip_bytes.read())) as modzip:
                            names = modzip.namelist()
                            restored_classes = set()
                            for name in names:
                                if not Path(name).name.endswith(".py"):
                                    continue

                                with modzip.open(name, "r") as module:
                                    source = module.read()
                                class_name = loader.module_class_name(source)
                                if not class_name:
                                    logger.warning(
                                        "restore: skipped %s: module class not found", name
                                    )
                                    continue
                                loader.save_module_source(source, class_name)
                                restored_classes.add(class_name)

                            if "db_mods.json" in names:
                                links = orjson.loads(modzip.read("db_mods.json"))
                                fetched = skipped = 0
                                for mod, url in links.items():
                                    if mod in restored_classes:
                                        continue
                                    try:
                                        r = await utils.run_sync(
                                            requests.get, url, timeout=30
                                        )
                                        r.raise_for_status()
                                        class_name = loader.module_class_name(r.content)
                                        if not class_name:
                                            raise ValueError("module class not found")
                                        loader.save_module_source(r.content, class_name)
                                        restored_classes.add(class_name)
                                        fetched += 1
                                    except Exception as e:
                                        skipped += 1
                                        logger.warning(
                                            "restore: failed to fetch %s from %s: %s",
                                            mod,
                                            url,
                                            e,
                                        )
                                logger.info(
                                    "restore: fetched %d modules by url, %d failed",
                                    fetched,
                                    skipped,
                                )
        except Exception:
            logger.exception("Restore failed")
            await utils.answer(status_message, self.strings["reply_to_file"])
            return

        await utils.answer(status_message, self.strings["all_restored"])
        await self.invoke("restart", "-f", peer=message.peer_id)
