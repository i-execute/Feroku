# CopyLeft 2026 github.com/i-execute // i_execute.t.me
# Licensed under AGPLv3.

import asyncio
import logging
import re
import sys
import time

import aiohttp
import telethon
from telethon.tl.alltlobjects import LAYER
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

    @staticmethod
    def _version_key(value: str) -> tuple[int, ...]:
        return tuple(int(part) for part in re.findall(r"\d+", value))

    @staticmethod
    async def _layer_data() -> tuple[str | None, int | None, int | None]:
        timeout = aiohttp.ClientTimeout(total=12)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get("https://pypi.org/pypi/telethon/json") as response:
                response.raise_for_status()
                latest_version = (await response.json())["info"]["version"]
            stable_url = (
                "https://codeberg.org/Lonami/Telethon/raw/tag/"
                f"v{latest_version}/telethon_generator/data/api.tl"
            )
            telegram_url = (
                "https://raw.githubusercontent.com/telegramdesktop/tdesktop/dev/"
                "Telegram/SourceFiles/mtproto/scheme/api.tl"
            )

            async def fetch_layer(url):
                async with session.get(url) as response:
                    response.raise_for_status()
                    found = re.search(
                        r"(?m)^//\s*LAYER\s*(\d+)\s*$",
                        await response.text(),
                    )
                    return int(found.group(1)) if found else None

            stable_layer, telegram_layer = await asyncio.gather(
                fetch_layer(stable_url),
                fetch_layer(telegram_url),
            )
        return latest_version, stable_layer, telegram_layer

    async def _update_telethon(self, call, version: str):
        if not re.fullmatch(r"\d+(?:\.\d+){1,3}(?:[a-zA-Z0-9.-]*)?", version):
            await call.edit("<b>Invalid Telethon version</b>")
            return
        await call.edit(
            f"<b>Updating Telethon to <code>{version}</code></b>"
            "\n<blockquote>Feroku will restart after installation.</blockquote>"
        )
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-input",
            "--upgrade",
            f"telethon=={version}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=300)
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            await call.edit(
                "<b>Telethon update timed out</b>"
                "\n<blockquote>The current installation was kept.</blockquote>"
            )
            return
        if process.returncode:
            detail = (stderr or stdout).decode(errors="replace")[-1500:]
            await call.edit(
                "<b>Telethon update failed</b>"
                f"\n<blockquote expandable>{utils.escape_html(detail)}</blockquote>"
            )
            return
        await call.edit(
            f"<b>Telethon <code>{version}</code> installed</b>"
            "\n<blockquote>Restarting Feroku.</blockquote>"
        )
        await asyncio.sleep(1)
        await main.feroku.restart_runtime()

    @loader.owner
    @loader.command()
    async def layer(self, message: Message):
        current_version = telethon.__version__
        try:
            latest_version, stable_layer, telegram_layer = await self._layer_data()
        except Exception as error:
            logger.warning("Failed to check Telethon layer metadata: %s", error)
            await utils.answer(
                message,
                "<b>MTProto layer</b>"
                f"\n<blockquote><b>Telethon:</b> <code>{current_version}</code>"
                f"\n<b>Current layer:</b> <code>{LAYER}</code>"
                "\n<b>Update check:</b> unavailable</blockquote>",
            )
            return
        update_available = (
            self._version_key(latest_version) > self._version_key(current_version)
            and (stable_layer is None or stable_layer >= LAYER)
        )
        if update_available:
            status = "A newer stable Telethon release is available."
        elif telegram_layer is not None and telegram_layer > LAYER:
            status = "Telegram has a newer layer, but no newer stable Telethon release is available."
        else:
            status = "No stable update is available."
        lines = [
            "<b>MTProto layer</b>",
            "<blockquote>",
            f"<b>Telethon:</b> <code>{current_version}</code>",
            f"<b>Current layer:</b> <code>{LAYER}</code>",
            f"<b>Latest Telethon:</b> <code>{latest_version}</code>",
        ]
        if stable_layer is not None:
            lines.append(f"<b>Latest stable layer:</b> <code>{stable_layer}</code>")
        if telegram_layer is not None:
            lines.append(f"<b>Latest Telegram layer:</b> <code>{telegram_layer}</code>")
        lines.extend((f"<b>Status:</b> {status}", "</blockquote>"))
        markup = None
        if update_available:
            markup = [[{
                "text": "Update Telethon and restart",
                "callback": self._update_telethon,
                "args": (latest_version,),
                "force_me": True,
            }]]
        await utils.answer(message, "\n".join(lines), reply_markup=markup)

    @loader.owner
    @loader.command()
    async def restart(self, message: Message):
        message = await utils.answer(message, self.strings["restarting"])
        chat_id = getattr(message, "chat_id", None) or utils.get_chat_id(message)
        self.set("restart_started", time.time())
        self.set("restart_message", [chat_id, message.id])
        self.set("userbot_load_time", None)
        await main.feroku.restart_runtime()