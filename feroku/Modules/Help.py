# CopyLeft 2026 github.com/i-execute // i_execute.t.me
# Licensed under AGPLv3.

# (c) Dan Gazizullin, 2021-2023. This file is part of the Hikka Userbot: github.com/hikariatama/Hikka

import asyncio
import difflib
import inspect
import logging
import re

from telethon.tl.types import Message
from telethon.types import InputMediaWebPage

from .. import loader, utils

logger = logging.getLogger(__name__)

@loader.tds
class Help(loader.Module):

    strings = {
        "name": "Help",
        "undoc": "No docs",
        "all_header": "<b>Available {} modules</b>",
        "help_lib": "<b>Package</b> <code>{}</code> <b>is a library.</b>\n<b>Libraries do not have descriptions...</b>",
        "offchats": "<a href=\"https://t.me/feroku_talks\"><b>Support chat</b></a>\n\n<a href=\"https://t.me/feroku_offtop\"><b>Offtop chat</b></a>\n\n<a href=\"https://t.me/feroku_ub\"><b>Official channel</b></a>",
        "_cls_doc": "Shows help for modules and commands",
        "_cmd_doc_help": "[module] - Show help for modules and commands",
        "_cmd_doc_support": "Show support chat link",
        "show_preview_in_help": "Show # meta banner in help preview [module]",
        "core_notice": "Core commands",
        "developer": "<b>Developer:</b> {}",
        "not_exact": "<i>An exact command match was not found.</i>",
        "partial_load": "<i>Modules are still loading.</i>",
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "core_emoji",
                "→",
                lambda: "Core module symbol",
            ),
            loader.ConfigValue(
                "plain_emoji",
                "→",
                lambda: "External module symbol",
            ),
            loader.ConfigValue(
                "command_emoji",
                "→",
                lambda: "Command symbol",
            ),
            loader.ConfigValue(
                "banner_url",
                None,
                lambda: "Banner for .help",
                validator=loader.validators.RandomLink(),
            ),
            loader.ConfigValue(
                "media_quote",
                "False",
                lambda: "quote a banner in help",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "invert_media",
                "False",
                lambda: "invert banner",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "show_preview_in_help",
                True,
                lambda: self.strings["show_preview_in_help"],
                validator=loader.validators.Boolean(),
            ),
        )

    def _get_banner_url(self, doc: str):
        match = re.search(r"# ?meta banner: ?(.+)", doc)
        return match.group(1).strip() if match else None

    def _module_emoji(self, module) -> str:
        return self.config[
            "core_emoji" if module.__origin__.startswith("<core") else "plain_emoji"
        ]

    def find_aliases(self, command: str) -> list:
        aliases = []
        _command = self.allmodules.commands[command]
        if getattr(_command, "alias", None) and not (
            aliases := getattr(_command, "aliases", None)
        ):
            aliases = [_command.alias]

        return aliases or []

    async def modhelp(self, message: Message, args: str):
        exact = True
        if not (module := self.lookup(args)):
            if method := self.allmodules.dispatch(
                args.lower().strip(self.get_prefix())
            )[1]:
                module = method.__self__
            else:
                module = self.lookup(
                    next(
                        (
                            reversed(
                                sorted(
                                    [
                                        module.strings["name"]
                                        for module in self.allmodules.modules
                                    ],
                                    key=lambda x: difflib.SequenceMatcher(
                                        None,
                                        args.lower(),
                                        x,
                                    ).ratio(),
                                )
                            )
                        ),
                        None,
                    )
                )

                exact = False

        try:
            name = module.strings("name")
        except (KeyError, AttributeError):
            name = getattr(module, "name", "ERROR")

        _name = (
            "{} (v{})".format(
                utils.escape_html(name), ".".join(map(str, module.__version__))
            )
            if hasattr(module, "__version__")
            else utils.escape_html(name)
        )

        reply = "{} <b>{}</b>:".format(
            "",
            _name,
        )
        inline_cmd = ""
        cmds = ""
        if module.__doc__:
            reply += (
                "\n<i>"
                + utils.escape_html(inspect.getdoc(module))
                + "\n</i>"
            )

        if isinstance(self.lookup(args), loader.Library):
            return await utils.answer(message, self.strings["help_lib"].format(name))

        commands = {
            name: func
            for name, func in module.commands.items()
            if await self.allmodules.check_security(message, func)
        }

        if hasattr(module, "inline_handlers"):
            for name, fun in module.inline_handlers.items():
                inline_cmd += (
                    "\n"
                    " <code>{}</code> {}".format(
                        f"@{self.inline.bot_username} {name}",
                        (
                            utils.escape_html(inspect.getdoc(fun))
                            if fun.__doc__
                            else self.strings["undoc"]
                        ),
                    )
                )

        lines = []
        for name, fun in commands.items():
            lines.append(
                self.config["command_emoji"]
                + " <code>{}{}</code>{} {}".format(
                    utils.escape_html(self.get_prefix()),
                    name,
                    (
                        " ({})".format(
                            ", ".join(
                                "<code>{}{}</code>".format(
                                    utils.escape_html(self.get_prefix()),
                                    alias,
                                )
                                for alias in self.find_aliases(name)
                            )
                        )
                        if self.find_aliases(name)
                        else ""
                    ),
                    (
                        utils.escape_html(inspect.getdoc(fun))
                        if fun.__doc__
                        else self.strings["undoc"]
                    ),
                )
            )
        cmds = "\n".join(lines)
        developer = re.search(
            r"# ?meta developer: ?(.+)", getattr(module, "__source__", None)
        )
        dev_text = developer.group(1) if developer else None
        placeholders = "\n".join(
            utils.help_placeholders(module.__class__.__name__, self)
        )

        banner_kwargs = {}
        banner_url = None
        if self.config["show_preview_in_help"]:
            try:
                source = getattr(module, "__source__", None)
                if source:
                    banner_url = self._get_banner_url(source)
                    if banner_url:
                        banner_kwargs = {
                            "file": InputMediaWebPage(banner_url, optional=True),
                            "invert_media": True,
                        }
            except Exception:
                pass


        await utils.answer(
            message,
            f"{reply}<blockquote expandable>{cmds}{inline_cmd}</blockquote>"
            + (
                f"<blockquote expandable>\n{placeholders}</blockquote>"
                if placeholders
                else ""
            )
            + (self.strings["developer"].format(dev_text) if dev_text else "")
            + (f"\n\n{self.strings['not_exact']}" if not exact else "")
            + (
                f"\n{self.strings['core_notice']}"
                if module.__origin__.startswith("<core")
                else ""
            ),
            **banner_kwargs,
        )

    @loader.command()
    async def help(self, message: Message):

        args = utils.get_args_raw(message)

        banner = str(self.config["banner_url"])

        if self.config["banner_url"] and self.config["media_quote"] is True:
            banner = InputMediaWebPage(str(self.config["banner_url"]))

        if (
            self.config["banner_url"] and self.client.feroku_me.premium is False
        ):
            banner = InputMediaWebPage(str(self.config["banner_url"]))

        if not self.config["banner_url"]:
            banner = None

        only_core = False
        if "-c" in args:
            args = args.replace(" -c", "").replace("-c", "")
            only_core = True

        only_loaded = False
        if "-l" in args:
            args = args.replace(" -l", "").replace("-l", "")
            only_loaded = True

        if args:
            await self.modhelp(message, args)
            return

        plain_ = []
        core_ = []
        plain_empty = []
        core_empty = []

        for mod in self.allmodules.modules:
            if not hasattr(mod, "commands"):
                logger.debug("Module %s is not inited yet", mod.__class__.__name__)
                continue

            try:
                name = mod.strings["name"]
            except KeyError:
                name = getattr(mod, "name", "ERROR")

            core = mod.__origin__.startswith("<core")
            placeholders = utils.module_placeholders(mod.__class__.__name__)

            if (
                not getattr(mod, "commands", None)
                and not getattr(mod, "inline_handlers", None)
                and not getattr(mod, "callback_handlers", None)
                and not placeholders
            ):
                target = core_empty if core else plain_empty
                target.append(
                    "{} <code>{}</code>".format(self._module_emoji(mod), name)
                )
                continue

            tmp = "{} <code>{}</code>".format(
                self._module_emoji(mod),
                name,
            )
            first = True
            commands = [
                command_name
                for command_name, func in mod.commands.items()
                if await self.allmodules.check_security(message, func)
            ]

            for command_name in commands:
                if first:
                    tmp += f": ( {command_name}"
                    first = False
                else:
                    tmp += f" | {command_name}"

            results = await asyncio.gather(
                *(
                    self.inline.check_inline_security(
                        func=func,
                        user=(
                            message.sender_id
                            if not message.out
                            else self._client.tg_id
                        ),
                    )
                    for func in mod.inline_handlers.values()
                )
            )
            inline_commands = [
                command_name
                for command_name, passed in zip(mod.inline_handlers.keys(), results)
                if passed is True
            ]

            for command_name in inline_commands:
                if first:
                    tmp += f": (  {command_name}"
                    first = False
                else:
                    tmp += f" |  {command_name}"

            for placeholder in placeholders:
                if first:
                    tmp += f": ( {{{placeholder}}}"
                    first = False
                else:
                    tmp += f" | {{{placeholder}}}"

            if commands or inline_commands or placeholders:
                tmp += " )"
                (core_ if core else plain_).append(tmp)

        for collection in (plain_, core_, plain_empty, core_empty):
            collection.sort(key=str.lower)

        if only_core:
            entries = core_ + core_empty
        elif only_loaded:
            entries = plain_ + plain_empty
        else:
            entries = core_ + plain_ + core_empty + plain_empty

        available = len(entries)
        if not self.lookup("Installer").fully_loaded:
            entries.append(self.strings["partial_load"])

        reply = self.strings["all_header"].format(available)
        module_list = "\n".join(entries)
        await utils.answer(
            message,
            f"{reply}\n<blockquote expandable>{module_list}</blockquote>",
            file=banner,
            invert_media=self.config["invert_media"],
        )

    @loader.command()
    async def support(self, message):

        await utils.answer(
            message,
            self.strings["offchats"],
        )
