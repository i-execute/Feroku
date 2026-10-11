# CopyLeft 2026 github.com/i-execute // i_execute.t.me
# Licensed under AGPLv3.

from telethon.tl.types import Message

from .. import loader, main, utils


@loader.tds
class Restart(loader.Module):
    strings = {
        "name": "Restart",
        "restarting": "<b>Restarting Feroku</b>\n<blockquote>The userbot will return shortly.</blockquote>",
    }

    @loader.owner
    @loader.command()
    async def restart(self, message: Message):
        await utils.answer(message, self.strings["restarting"])
        await main.feroku.restart_runtime()
