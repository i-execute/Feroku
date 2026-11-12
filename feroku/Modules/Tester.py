# CopyLeft 2026 github.com/i-execute // i_execute.t.me
# Licensed under AGPLv3.

# (c) Dan Gazizullin, 2021-2023. This file is part of the Hikka Userbot: github.com/hikariatama/Hikka

import getpass
import logging
import os
import platform as lib_platform
import random
import time

from telethon.tl.types import Message
from telethon.types import InputMediaWebPage

from .. import loader, utils

logger = logging.getLogger(__name__)

DEBUG_MODS_DIR = os.path.join(utils.get_base_dir(), "debug_modules")

if not os.path.isdir(DEBUG_MODS_DIR):
    os.mkdir(DEBUG_MODS_DIR, mode=0o755)

for mod in os.scandir(DEBUG_MODS_DIR):
    os.remove(mod.path)

@loader.tds
class Tester(loader.Module):
    """Measure userbot responsiveness and runtime status."""

    strings = {
        "name": "Tester",
        "force_send_all_doc": "Send all log records through Telegram logging",
        "tglog_level_doc": "Minimum Telegram log level",
        "ignore_common_doc": "Ignore common noisy log records",
        "disable_internet_warn_doc": "Disable internet warning prompts",
        "configping": "Ping response template. Available placeholders include {ping}, {uptime}, {ping_hint}, {hostname}, and {img}.",
        "configpingph": "Custom placeholders: {}",
        "hint": "Set a hint",
        "ping_emoji": "Symbol shown in the ping response",
        "banner_url": "Image for your ping, for example: Storage/Feroku.PNG",
        "default_message": "{ping_emoji} <b>Ping</b>\n<blockquote><b>Latency:</b> <code>{ping} ms</code>\n<b>Uptime:</b> <code>{uptime}</code></blockquote>",
        "quote_media_doc": "Switch ping preview media to a quote",
        "invert_media_doc": "Invert ping preview media",
        "rich_mode_doc": "Render the ping response as a Rich message",
        "loading": "...",
    }

    def __init__(self):
        self._memory = {}
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "force_send_all",
                False,
                lambda: self.strings["force_send_all_doc"],
                validator=loader.validators.Boolean(),
                on_change=self._pass_config_to_logger,
            ),
            loader.ConfigValue(
                "tglog_level",
                "ERROR",
                lambda: self.strings["tglog_level_doc"],
                validator=loader.validators.Choice(
                    [
                        "ALL",
                        "DEBUG",
                        "INFO",
                        "WARNING",
                        "ERROR",
                        "CRITICAL",
                        "DISABLE",
                    ]
                ),
                on_change=self._pass_config_to_logger,
            ),
            loader.ConfigValue(
                "ignore_common",
                True,
                lambda: self.strings["ignore_common_doc"],
                validator=loader.validators.Boolean(),
                on_change=self._pass_config_to_logger,
            ),
            loader.ConfigValue(
                "disable_internet_warn",
                False,
                lambda: self.strings["disable_internet_warn_doc"],
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "custom_message",
                self.strings["default_message"],
                lambda: (
                    self.strings["configping"]
                    + (
                        "\n"
                        + self.strings["configpingph"].format(
                            "\n" + utils.config_placeholders()
                        )
                        if utils.config_placeholders()
                        else ""
                    )
                ),
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "hint",
                None,
                lambda: self.strings["hint"],
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "ping_emoji",
                "→",
                lambda: self.strings["ping_emoji"],
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "banner_url",
                None,
                lambda: self.strings["banner_url"],
                validator=loader.validators.RandomLink(),
            ),
            loader.ConfigValue(
                "quote_media",
                False,
                lambda: self.strings["quote_media_doc"],
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "rich_mode",
                False,
                lambda: self.strings["rich_mode_doc"],
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "invert_media",
                False,
                lambda: self.strings["invert_media_doc"],
                validator=loader.validators.Boolean(),
            ),
        )

    def _pass_config_to_logger(self):
        client_id = getattr(self, "tg_id", None)
        if client_id is None or not logging.getLogger().handlers:
            return
        handler = logging.getLogger().handlers[0]
        if not hasattr(handler, "set_client_options"):
            return
        handler.set_client_options(
            client_id,
            force_send_all=self.config["force_send_all"],
            tg_level={
                "ALL": 0,
                "DEBUG": 10,
                "INFO": 20,
                "WARNING": 30,
                "ERROR": 40,
                "CRITICAL": 50,
                "DISABLE": 50000,
            }[self.config["tglog_level"]],
            ignore_common=self.config["ignore_common"],
        )

    @loader.command()
    async def ping(self, message: Message):
        """Measure userbot response time."""
        start = time.perf_counter_ns()
        message = await utils.answer(message, self.strings["loading"])
        banner = str(self.config["banner_url"])

        if self.config["banner_url"] and self.config["quote_media"] is True:
            banner = InputMediaWebPage(str(self.config["banner_url"]), optional=True)

        elif not self.config["banner_url"]:
            banner = None

        data = {
            "ping": round((time.perf_counter_ns() - start) / 10**6, 3),
            "uptime": utils.formatted_uptime(),
            "ping_hint": (
                (self.config["hint"]) if random.choice([0, 0, 1]) == 1 else ""
            ),
            "ping_emoji": self.config["ping_emoji"],
            "hostname": lib_platform.node(),
            "user": getpass.getuser(),
            "platform": utils.get_platform_name(),
            "img": (
                f'<img src="{utils.escape_html(str(self.config["banner_url"]))}"/>'
                if self.config["rich_mode"] and self.config["banner_url"]
                else ""
            ),
        }
        data = await utils.get_placeholders(data, self.config["custom_message"])
        try:
            placeholders_msg = self.config["custom_message"].format(**data)
        except KeyError:
            logger.exception("Missing placeholder in custom_message")
            placeholders_msg = ""

        if self.config["rich_mode"]:
            await utils.answer_with_media_fallback(
                message,
                rich_message=placeholders_msg.replace("\r\n", "<br>").replace(
                    "\n",
                    "<br>",
                ),
            )
            return

        await utils.answer_with_media_fallback(
            message,
            placeholders_msg,
            file=banner,
            invert_media=self.config["invert_media"],
        )

    async def client_ready(self):
        self._content_channel_id = await utils.wait_for_content_channel(self._db)
        self.logchat = int(f"-100{self._content_channel_id}")
        logging.getLogger().handlers[0].install_tg_log(self)
        logger.debug("Bot logging installed for %s", self.logchat)
        self._pass_config_to_logger()
