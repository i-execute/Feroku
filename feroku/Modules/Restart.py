# CopyLeft 2026 github.com/i-execute // i_execute.t.me
# Licensed under AGPLv3.

import asyncio
import logging
import re
import sys
import time

import aiohttp
import telethon
from telethon.tl import types
from telethon.tl.alltlobjects import LAYER
from telethon.tl.types import Message

from .. import loader, main, utils
from ..inline.types import InlineCall


logger = logging.getLogger(__name__)


@loader.tds
class Restart(loader.Module):
    """Inspect protocol versions and restart Feroku."""

    strings = {
        "name": "Restart",
        "restarting": "<b>Restarting Feroku</b>\n<blockquote>The userbot will return shortly.</blockquote>",
        "restart_confirm": "<b>Restart Feroku?</b><blockquote>The current runtime will be stopped and started again.</blockquote>",
        "restart_cancelled": "<b>Restart cancelled</b>",
        "loaded": "<blockquote>Userbot loaded with {} sec</blockquote>",
        "fully_loaded": "<blockquote>Userbot loaded with {} sec and full restart took {} sec</blockquote>",
        "not_available": "n/a",
        "not_checked": "Not checked",
        "status_update_available": "A newer stable Telethon release is available.",
        "status_layer_ahead": "Telegram has a newer layer, but no validated stable Telethon update is selected.",
        "status_current": "No stable update is available.",
        "status_prompt": "Use the buttons below to check current releases and layers.",
        "installed_telethon": "<b>Installed Telethon:</b> <code>{}</code>",
        "current_layer": "<b>Current layer:</b> <code>{}</code>",
        "latest_telethon": "<b>Latest Telethon:</b> <code>{}</code>",
        "latest_stable_layer": "<b>Latest stable layer:</b> <code>{}</code>",
        "telegram_desktop_layer": "<b>Telegram Desktop layer:</b> <code>{}</code>",
        "tdlib_layer": "<b>TDLib layer:</b> <code>{}</code>",
        "layer_status": "<b>Status:</b> {}",
        "last_error": "<b>Last error:</b> <code>{}</code>",
        "layer_result": "<b>MTProto layer</b><blockquote>{}</blockquote>",
        "layer_loading": "<b>MTProto layer</b><blockquote>Loading {}...</blockquote>",
        "check_all": "Check all",
        "telethon_release": "Telethon release",
        "telegram_layer": "Telegram layer",
        "tdlib_layer_button": "TDLib layer",
        "update_button": "Update Telethon and restart",
        "restart_button": "Restart Feroku",
        "restart_confirm_button": "Restart",
        "cancel": "Cancel",
        "close": "Close",
        "check_all_loading": "release and layer data",
        "invalid_version": "<b>Invalid Telethon version</b>",
        "updating_telethon": "<b>Updating Telethon to <code>{}</code></b><blockquote>Feroku will restart after installation.</blockquote>",
        "update_timeout": "<b>Telethon update timed out</b><blockquote>The current installation was kept.</blockquote>",
        "update_failed": "<b>Telethon update failed</b><blockquote expandable>{}</blockquote>",
        "update_installed": "<b>Telethon <code>{}</code> installed</b><blockquote>Restarting Feroku.</blockquote>",
    }

    def __init__(self):
        self._runtime_id = utils.rand(20)
        self._restart_task = None

    def _elapsed(self, started, monotonic_started=None) -> int | str:
        try:
            monotonic_elapsed = time.monotonic() - float(monotonic_started)
            if monotonic_elapsed >= 0:
                return round(monotonic_elapsed)
        except (TypeError, ValueError):
            pass
        try:
            return max(0, round(time.time() - float(started)))
        except (TypeError, ValueError):
            return self.strings["not_available"]

    @staticmethod
    def _version_key(value: str) -> tuple[int, ...]:
        return tuple(int(part) for part in re.findall(r"\d+", value))

    def _layer_cache(self) -> dict:
        cache = getattr(self, "_layer_values", None)
        if not isinstance(cache, dict):
            cache = {}
            self._layer_values = cache
        return cache

    @staticmethod
    def _encode_inline_id(inline_id):
        if isinstance(inline_id, types.InputBotInlineMessageID64):
            return {
                "kind": "64",
                "dc_id": inline_id.dc_id,
                "owner_id": inline_id.owner_id,
                "id": inline_id.id,
                "access_hash": inline_id.access_hash,
            }
        if isinstance(inline_id, types.InputBotInlineMessageID):
            return {
                "kind": "32",
                "dc_id": inline_id.dc_id,
                "id": inline_id.id,
                "access_hash": inline_id.access_hash,
            }
        return None

    @staticmethod
    def _decode_inline_id(data):
        if not isinstance(data, dict):
            return None
        try:
            if data.get("kind") == "64":
                return types.InputBotInlineMessageID64(
                    dc_id=int(data["dc_id"]),
                    owner_id=int(data["owner_id"]),
                    id=int(data["id"]),
                    access_hash=int(data["access_hash"]),
                )
            if data.get("kind") == "32":
                return types.InputBotInlineMessageID(
                    dc_id=int(data["dc_id"]),
                    id=int(data["id"]),
                    access_hash=int(data["access_hash"]),
                )
        except (KeyError, TypeError, ValueError):
            return None
        return None

    def _restart_reference(self):
        reference = self.get("restart_message")
        if isinstance(reference, list) and len(reference) == 2:
            try:
                return {"chat": int(reference[0]), "message_id": int(reference[1])}
            except (TypeError, ValueError):
                return None
        return reference if isinstance(reference, dict) else None

    def _clear_restart_state(self):
        for key in (
            "restart_pending",
            "restart_started",
            "restart_monotonic",
            "restart_runtime_id",
            "restart_message",
            "userbot_load_time",
        ):
            self.set(key, None)

    def _begin_restart(self, target):
        form = getattr(target, "form", {})
        inline_id = getattr(target, "inline_message_id", None)
        if inline_id is not None and isinstance(form, dict):
            reference = {
                "inline": self._encode_inline_id(inline_id),
                "chat": form.get("chat"),
                "message_id": form.get("message_id"),
            }
        else:
            reference = {
                "inline": None,
                "chat": getattr(target, "chat_id", None) or utils.get_chat_id(target),
                "message_id": getattr(target, "id", None)
                or getattr(target, "message_id", None),
            }
        self.set("restart_pending", False)
        self.set("restart_started", time.time())
        self.set("restart_monotonic", time.monotonic())
        self.set("restart_runtime_id", None)
        self.set("restart_message", reference)
        self.set("userbot_load_time", None)
        self.set("restart_pending", True)

    def _queue_restart(self):
        async def run():
            try:
                await main.feroku.restart_runtime()
            except Exception:
                self._clear_restart_state()
                logger.exception("Failed to restart Feroku")

        self._restart_task = asyncio.create_task(run())

    async def _edit_restart_message(self, text: str) -> bool:
        reference = self._restart_reference()
        if reference is None:
            return False
        inline_id = self._decode_inline_id(reference.get("inline"))
        if inline_id is not None and getattr(self.inline, "bot", None) is not None:
            try:
                await self.inline.bot.edit_message_text(
                    text=text,
                    inline_message_id=inline_id,
                    reply_markup=[],
                )
                return True
            except Exception:
                logger.warning("Failed to edit the inline restart status", exc_info=True)
        if reference.get("chat") is None or reference.get("message_id") is None:
            return False
        try:
            await self._client.edit_message(
                int(reference["chat"]),
                int(reference["message_id"]),
                text,
                parse_mode="HTML",
            )
            return True
        except Exception:
            logger.warning("Failed to edit the restart status message", exc_info=True)
            return False

    async def client_ready(self):
        if not self.get("restart_pending", False):
            if any(
                self.get(key) is not None
                for key in (
                    "restart_started",
                    "restart_monotonic",
                    "restart_runtime_id",
                    "restart_message",
                    "userbot_load_time",
                )
            ):
                self._clear_restart_state()
            return
        if self.get("restart_runtime_id") is not None:
            self._clear_restart_state()
            return
        started = self.get("restart_started")
        if started is None or self._restart_reference() is None:
            self._clear_restart_state()
            return
        loaded = self._elapsed(started, self.get("restart_monotonic"))
        self.set("userbot_load_time", loaded)
        self.set("restart_runtime_id", self._runtime_id)
        await self._edit_restart_message(
            f"{self.strings['restarting']}\n{self.strings['loaded'].format(loaded)}"
        )

    async def full_restart_complete(self):
        started = self.get("restart_started")
        loaded = self.get("userbot_load_time")
        if (
            not self.get("restart_pending", False)
            or self.get("restart_runtime_id") != self._runtime_id
            or started is None
            or loaded is None
            or self._restart_reference() is None
        ):
            return
        total = self._elapsed(started, self.get("restart_monotonic"))
        await self._edit_restart_message(
            f"{self.strings['restarting']}\n"
            f"{self.strings['fully_loaded'].format(loaded, total)}"
        )
        self._clear_restart_state()

    @staticmethod
    async def _get_json(session, url):
        async with session.get(url) as response:
            response.raise_for_status()
            return await response.json()

    @staticmethod
    async def _get_text(session, url):
        async with session.get(url) as response:
            response.raise_for_status()
            return await response.text()

    @staticmethod
    def _parse_layer(text):
        found = re.search(r"(?m)^//\s*LAYER\s*(\d+)\s*$", text)
        return int(found.group(1)) if found else None

    async def _fetch_release(self):
        timeout = aiohttp.ClientTimeout(total=12)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            data = await self._get_json(session, "https://pypi.org/pypi/telethon/json")
            version = data["info"]["version"]
            schema = await self._get_text(
                session,
                "https://codeberg.org/Lonami/Telethon/raw/tag/"
                f"v{version}/telethon_generator/data/api.tl",
            )
        return version, self._parse_layer(schema)

    async def _fetch_telegram_layer(self):
        timeout = aiohttp.ClientTimeout(total=12)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            schema = await self._get_text(
                session,
                "https://raw.githubusercontent.com/telegramdesktop/tdesktop/dev/"
                "Telegram/SourceFiles/mtproto/scheme/api.tl",
            )
        return self._parse_layer(schema)

    async def _fetch_tdlib_layer(self):
        timeout = aiohttp.ClientTimeout(total=12)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            source = await self._get_text(
                session,
                "https://raw.githubusercontent.com/tdlib/td/master/td/telegram/Version.h",
            )
        found = re.search(r"MTPROTO_LAYER\s*=\s*(\d+)", source)
        return int(found.group(1)) if found else None

    def _layer_status(self) -> str:
        cache = self._layer_cache()
        latest = cache.get("latest_version")
        stable = cache.get("stable_layer")
        telegram_layer = cache.get("telegram_layer")
        tdlib_layer = cache.get("tdlib_layer")
        if (
            latest
            and stable is not None
            and self._version_key(latest) > self._version_key(telethon.__version__)
            and stable >= LAYER
        ):
            return self.strings["status_update_available"]
        known_layers = [value for value in (telegram_layer, tdlib_layer) if value is not None]
        if known_layers and max(known_layers) > LAYER:
            return self.strings["status_layer_ahead"]
        if cache.get("checked"):
            return self.strings["status_current"]
        return self.strings["status_prompt"]

    def _layer_text(self) -> str:
        cache = self._layer_cache()
        value = lambda key: (
            cache.get(key)
            if cache.get(key) is not None
            else self.strings["not_checked"]
        )
        lines = [
            self.strings["installed_telethon"].format(telethon.__version__),
            self.strings["current_layer"].format(LAYER),
            self.strings["latest_telethon"].format(value("latest_version")),
            self.strings["latest_stable_layer"].format(value("stable_layer")),
            self.strings["telegram_desktop_layer"].format(
                value("telegram_layer")
            ),
            self.strings["tdlib_layer"].format(value("tdlib_layer")),
            self.strings["layer_status"].format(self._layer_status()),
        ]
        if cache.get("error"):
            lines.append(
                self.strings["last_error"].format(
                    utils.escape_html(cache["error"])
                )
            )
        return self.strings["layer_result"].format("\n".join(lines))

    def _loading_text(self, label: str) -> str:
        return self.strings["layer_loading"].format(label)

    def _layer_rows(self):
        rows = [
            [
                {
                    "text": self.strings["check_all"],
                    "callback": self._check_all,
                    "style": "primary",
                },
                {
                    "text": self.strings["telethon_release"],
                    "callback": self._check_release,
                },
            ],
            [
                {
                    "text": self.strings["telegram_layer"],
                    "callback": self._check_telegram,
                },
                {
                    "text": self.strings["tdlib_layer_button"],
                    "callback": self._check_tdlib,
                },
            ],
        ]
        cache = self._layer_cache()
        latest = cache.get("latest_version")
        stable = cache.get("stable_layer")
        if (
            latest
            and stable is not None
            and self._version_key(latest) > self._version_key(telethon.__version__)
            and stable >= LAYER
        ):
            rows.append(
                [
                    {
                        "text": self.strings["update_button"],
                        "callback": self._update_telethon,
                        "args": (latest,),
                        "style": "success",
                    }
                ]
            )
        rows.extend(
            [
                [
                    {
                        "text": self.strings["restart_button"],
                        "callback": self._show_restart,
                    }
                ],
                [
                    {
                        "text": self.strings["close"],
                        "callback": self._close,
                        "style": "danger",
                    }
                ],
            ]
        )
        return rows

    async def _show_layer(self, target):
        await target.edit(self._layer_text(), reply_markup=self._layer_rows())

    async def _run_check(self, call, label, loader_method):
        await call.edit(
            self._loading_text(label),
            reply_markup=[
                [
                    {
                        "text": self.strings["close"],
                        "callback": self._close,
                        "style": "danger",
                    }
                ]
            ],
        )
        cache = self._layer_cache()
        cache.pop("error", None)
        try:
            await loader_method()
            cache["checked"] = True
        except Exception as error:
            cache["error"] = f"{type(error).__name__}: {error}"[:300]
            logger.warning("Layer check failed: %s", error)
        await self._show_layer(call)

    async def _load_release(self):
        version, layer = await self._fetch_release()
        cache = self._layer_cache()
        cache["latest_version"] = version
        cache["stable_layer"] = layer

    async def _load_telegram(self):
        self._layer_cache()["telegram_layer"] = await self._fetch_telegram_layer()

    async def _load_tdlib(self):
        self._layer_cache()["tdlib_layer"] = await self._fetch_tdlib_layer()

    async def _check_release(self, call: InlineCall):
        await self._run_check(
            call,
            self.strings["telethon_release"],
            self._load_release,
        )

    async def _check_telegram(self, call: InlineCall):
        await self._run_check(
            call,
            self.strings["telegram_layer"],
            self._load_telegram,
        )

    async def _check_tdlib(self, call: InlineCall):
        await self._run_check(
            call,
            self.strings["tdlib_layer_button"],
            self._load_tdlib,
        )

    async def _check_all(self, call: InlineCall):
        async def load_all():
            results = await asyncio.gather(
                self._load_release(),
                self._load_telegram(),
                self._load_tdlib(),
                return_exceptions=True,
            )
            errors = [result for result in results if isinstance(result, Exception)]
            if errors:
                raise errors[0]

        await self._run_check(
            call,
            self.strings["check_all_loading"],
            load_all,
        )

    async def _close(self, call: InlineCall):
        await call.delete()

    async def _show_restart(self, call: InlineCall):
        await call.edit(
            self.strings["restart_confirm"],
            reply_markup=self._restart_rows(),
        )

    def _restart_rows(self):
        return [
            [
                {
                    "text": self.strings["restart_confirm_button"],
                    "callback": self._restart_confirm,
                    "style": "danger",
                },
                {
                    "text": self.strings["cancel"],
                    "callback": self._restart_cancel,
                },
            ]
        ]

    async def _restart_cancel(self, call: InlineCall):
        await call.edit(
            self.strings["restart_cancelled"],
            reply_markup=[
                [
                    {
                        "text": self.strings["close"],
                        "callback": self._close,
                        "style": "danger",
                    }
                ]
            ],
        )

    async def _restart_confirm(self, call: InlineCall):
        await call.edit(self.strings["restarting"], reply_markup=[])
        self._begin_restart(call)
        self._queue_restart()

    async def _update_telethon(self, call: InlineCall, version: str):
        if not re.fullmatch(r"\d+(?:\.\d+){1,3}(?:[a-zA-Z0-9.-]*)?", version):
            await call.edit(
                self.strings["invalid_version"],
                reply_markup=self._layer_rows(),
            )
            return
        await call.edit(
            self.strings["updating_telethon"].format(
                utils.escape_html(version)
            ),
            reply_markup=[],
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
                self.strings["update_timeout"],
                reply_markup=self._layer_rows(),
            )
            return
        if process.returncode:
            detail = (stderr or stdout).decode(errors="replace")[-1500:]
            await call.edit(
                self.strings["update_failed"].format(
                    utils.escape_html(detail)
                ),
                reply_markup=self._layer_rows(),
            )
            return
        await call.edit(
            self.strings["update_installed"].format(
                utils.escape_html(version)
            ),
            reply_markup=[],
        )
        await asyncio.sleep(1)
        self._begin_restart(call)
        self._queue_restart()

    @loader.owner
    @loader.command()
    async def layer(self, message: Message):
        """Show MTProto layer and Telethon release information."""
        form = await self.inline.form(
            text=self._loading_text(self.strings["check_all_loading"]),
            message=message,
            reply_markup=[
                [
                    {
                        "text": self.strings["close"],
                        "callback": self._close,
                        "style": "danger",
                    }
                ]
            ],
            force_me=True,
        )
        if form:
            await self._check_all(form)

    @loader.owner
    @loader.command()
    async def restart(self, message: Message):
        """Restart Feroku immediately."""
        status = await utils.answer(message, self.strings["restarting"])
        self._begin_restart(status)
        self._queue_restart()