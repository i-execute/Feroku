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

    strings = {
        "name": "Tester",
        "configping": "Ping response template. Available placeholders include {ping}, {uptime}, {ping_hint}, and {hostname}.",
        "configpingph": "Custom placeholders: {}",
        "hint": "Set a hint",
        "ping_emoji": "Symbol shown in the ping response",
        "banner_url": "Image for your ping, for example: Storage/Feroku.PNG",
        "_cmd_doc_ping": "Measure userbot response time",
        "_cls_doc": "Perform operations based on userbot self-testing",
    }

    def __init__(self):
        self._memory = {}
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "custom_message",
                "{ping_emoji} <b>Ping</b>\n<blockquote><b>Latency:</b> <code>{ping} ms</code>\n<b>Uptime:</b> <code>{uptime}</code></blockquote>",
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
                "Switch preview media to quote in ping",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "invert_media",
                False,
                "Switch preview invert media in ping",
                validator=loader.validators.Boolean(),
            ),
        )

    @loader.command()
    async def ping(self, message: Message):
        start = time.perf_counter_ns()
        message = await utils.answer(message, "...")
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
        }
        data = await utils.get_placeholders(data, self.config["custom_message"])
        try:
            placeholders_msg = self.config["custom_message"].format(**data)
        except KeyError:
            logger.exception("Missing placeholder in custom_message")
            placeholders_msg = ""

        await utils.answer(
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
