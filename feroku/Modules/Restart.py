# CopyLeft 2026 github.com/i-execute // i_execute.t.me
# Licensed under AGPLv3.

import logging
import time

from telethon.tl.types import Message

from .. import loader, main, utils


logger = logging.getLogger(__name__)


@loader.tds
class Restart(loader.Module):
    strings = {
        "name": "Restart",
        "restarting": "<b>Restarting Feroku</b>\n<blockquote>The userbot will return shortly.</blockquote>",
        "loaded": "<blockquote>Userbot loaded with {} sec</blockquote>",
        "fully_loaded": "<blockquote>Userbot loaded with {} sec and full restart took {} sec</blockquote>",
    }

    @staticmethod
    def _elapsed(started) -> int | str:
        try:
            return round(time.time() - float(started))
        except (TypeError, ValueError):
            return "n/a"

    def _message_ref(self) -> tuple[int, int] | None:
        reference = self.get("restart_message")
        if not isinstance(reference, list) or len(reference) != 2:
            return None
        try:
            return int(reference[0]), int(reference[1])
        except (TypeError, ValueError):
            return None

    async def _edit_restart_message(self, text: str) -> bool:
        reference = self._message_ref()
        if reference is None:
            return False
        try:
            await self._client.edit_message(
                reference[0],
                reference[1],
                text,
                parse_mode="HTML",
            )
        except Exception:
            logger.exception("Failed to edit the restart status message")
            return False
        return True

    async def client_ready(self):
        started = self.get("restart_started")
        if started is None or self._message_ref() is None:
            return
        loaded = self._elapsed(started)
        self.set("userbot_load_time", loaded)
        await self._edit_restart_message(
            f"{self.strings['restarting']}\n{self.strings['loaded'].format(loaded)}"
        )

    async def full_restart_complete(self):
        started = self.get("restart_started")
        loaded = self.get("userbot_load_time")
        if started is None or loaded is None or self._message_ref() is None:
            return
        total = self._elapsed(started)
        await self._edit_restart_message(
            f"{self.strings['restarting']}\n"
            f"{self.strings['fully_loaded'].format(loaded, total)}"
        )
        self.set("restart_started", None)
        self.set("restart_message", None)
        self.set("userbot_load_time", None)

    @loader.owner
    @loader.command()
    async def restart(self, message: Message):
        message = await utils.answer(message, self.strings["restarting"])
        chat_id = getattr(message, "chat_id", None) or utils.get_chat_id(message)
        self.set("restart_started", time.time())
        self.set("restart_message", [chat_id, message.id])
        self.set("userbot_load_time", None)
        await main.feroku.restart_runtime()