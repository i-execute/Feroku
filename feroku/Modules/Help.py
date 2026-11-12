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
    """Show help for modules and commands."""

    strings = {
        "name": "Help",
        "undoc": "No docs",
        "unknown_module": "ERROR",
        "no_mod": "<b>Specify at least one module.</b>",
        "hidden_shown": "<b>Help visibility updated</b>\n<blockquote>Hidden: {hidden}\nShown: {shown}</blockquote>",
        "all_header": "<b>Available {} modules</b>",
        "help_lib": "<b>Package</b> <code>{}</code> <b>is a library.</b>\n<b>Libraries do not have descriptions...</b>",
        "offchats": "<a href=\"https://t.me/feroku_talks\"><b>Support chat</b></a>\n\n<a href=\"https://t.me/feroku_offtop\"><b>Offtop chat</b></a>\n\n<a href=\"https://t.me/feroku_ub\"><b>Official channel</b></a>",
        "show_preview_in_help": "Show # meta banner in help preview [module]",
        "core_notice": "<blockquote>Core module</blockquote>",
        "developer": "<b>Developer:</b> {}",
        "core_emoji_doc": "Core module symbol",
        "plain_emoji_doc": "External module symbol",
        "empty_emoji_doc": "Module without commands symbol",
        "desc_icon_doc": "Module description symbol",
        "command_emoji_doc": "Command symbol",
        "inline_emoji_doc": "Inline command symbol",
        "banner_url_doc": "Banner for .help",
        "media_quote_doc": "Quote the help banner",
        "invert_media_doc": "Invert the help banner",
        "rich_mode_doc": "Render help as a Rich message",
        "rich_commands": "Commands",
        "rich_placeholders": "Placeholders",
        "rich_core": "Core modules",
        "rich_modules": "External modules",
        "not_exact": "\n<blockquote>An exact command match was not found.</blockquote>",
        "partial_load": "<i>Modules are still loading.</i>",
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "core_emoji",
                "→",
                lambda: self.strings["core_emoji_doc"],
            ),
            loader.ConfigValue(
                "plain_emoji",
                "→",
                lambda: self.strings["plain_emoji_doc"],
            ),
            loader.ConfigValue(
                "empty_emoji",
                "→",
                lambda: self.strings["empty_emoji_doc"],
            ),
            loader.ConfigValue(
                "desc_icon",
                "→",
                lambda: self.strings["desc_icon_doc"],
            ),
            loader.ConfigValue(
                "command_emoji",
                "→",
                lambda: self.strings["command_emoji_doc"],
            ),
            loader.ConfigValue(
                "inline_emoji",
                "→",
                lambda: self.strings["inline_emoji_doc"],
            ),
            loader.ConfigValue(
                "banner_url",
                None,
                lambda: self.strings["banner_url_doc"],
                validator=loader.validators.RandomLink(),
            ),
            loader.ConfigValue(
                "media_quote",
                "False",
                lambda: self.strings["media_quote_doc"],
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "invert_media",
                "False",
                lambda: self.strings["invert_media_doc"],
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "show_preview_in_help",
                True,
                lambda: self.strings["show_preview_in_help"],
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "rich_mode",
                False,
                lambda: self.strings["rich_mode_doc"],
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
            name = getattr(module, "name", self.strings["unknown_module"])

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
                "\n"
                + self.config["desc_icon"]
                + " <i>"
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
                    "\n{} <code>{}</code> {}".format(
                        self.config["inline_emoji"],
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

        if self.config["rich_mode"]:
            rich_commands = "".join(
                f"<p>{line.strip()}</p>" for line in lines if line.strip()
            )
            rich_inline = "".join(
                f"<p>{line.strip()}</p>"
                for line in inline_cmd.splitlines()
                if line.strip()
            )
            rich_placeholders = "".join(
                f"<p>{line.strip()}</p>"
                for line in placeholders.splitlines()
                if line.strip()
            )
            rich_message = (
                (
                    f'<figure><img src="{utils.escape_html(banner_url)}"/></figure>'
                    if banner_url
                    else ""
                )
                + reply.replace("\r\n", "<br>").replace("\n", "<br>")
                + (
                    f"<details><summary>{self.strings['rich_commands']}</summary>"
                    f"{rich_commands}{rich_inline}</details>"
                    if rich_commands or rich_inline
                    else ""
                )
                + (
                    f"<details><summary>{self.strings['rich_placeholders']}</summary>"
                    f"{rich_placeholders}</details>"
                    if rich_placeholders
                    else ""
                )
                + (f"<p>{self.strings['developer'].format(dev_text)}</p>" if dev_text else "")
                + (self.strings["not_exact"] if not exact else "")
                + (
                    self.strings["core_notice"]
                    if module.__origin__.startswith("<core")
                    else ""
                )
            )
            await utils.answer_with_media_fallback(
                message,
                rich_message=rich_message,
            )
            return

        await utils.answer_with_media_fallback(
            message,
            f"{reply}<blockquote expandable>{cmds}{inline_cmd}</blockquote>"
            + (
                f"<blockquote expandable>\n{placeholders}</blockquote>"
                if placeholders
                else ""
            )
            + (self.strings["developer"].format(dev_text) if dev_text else "")
            + (self.strings["not_exact"] if not exact else "")
            + (
                f"\n{self.strings['core_notice']}"
                if module.__origin__.startswith("<core")
                else ""
            ),
            **banner_kwargs,
        )

    @loader.command()
    async def helphide(self, message: Message):
        """<modules> - Toggle modules in the main help list."""
        modules = utils.get_args(message)
        if not modules:
            await utils.answer(message, self.strings["no_mod"])
            return

        currently_hidden = list(self.get("hide", []))
        hidden = []
        shown = []
        for name in modules:
            module = self.lookup(name)
            if not module:
                continue
            class_name = module.__class__.__name__
            if class_name in currently_hidden:
                currently_hidden.remove(class_name)
                shown.append(class_name)
            else:
                currently_hidden.append(class_name)
                hidden.append(class_name)
        self.set("hide", currently_hidden)
        await utils.answer(
            message,
            self.strings["hidden_shown"].format(
                hidden=utils.escape_html(", ".join(hidden) or "none"),
                shown=utils.escape_html(", ".join(shown) or "none"),
            ),
        )

    @loader.command()
    async def help(self, message: Message):
        """[module] - Show help for modules and commands."""
        args = utils.get_args_raw(message)
        force = False
        if "-f" in args:
            args = args.replace(" -f", "").replace("-f", "")
            force = True

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
            force = True

        only_loaded = False
        if "-l" in args:
            args = args.replace(" -l", "").replace("-l", "")
            only_loaded = True
            force = True

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
            if mod.__class__.__name__ in self.get("hide", []) and not force:
                continue

            try:
                name = mod.strings["name"]
            except KeyError:
                name = getattr(mod, "name", self.strings["unknown_module"])

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
                    "{} <code>{}</code>".format(
                        self.config["empty_emoji"],
                        name,
                    )
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
                if await self.allmodules.check_security(message, func) or force
            ]

            for command_name in commands:
                if first:
                    tmp += f": ( {command_name}"
                    first = False
                else:
                    tmp += f" | {command_name}"

            if force:
                inline_commands = list(mod.inline_handlers)
            else:
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
                    for command_name, passed in zip(
                        mod.inline_handlers.keys(),
                        results,
                    )
                    if passed is True
                ]

            for command_name in inline_commands:
                if first:
                    tmp += f": ( {self.config['inline_emoji']} {command_name}"
                    first = False
                else:
                    tmp += f" | {self.config['inline_emoji']} {command_name}"

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
        if self.config["rich_mode"]:
            core_entries = core_ + core_empty
            external_entries = plain_ + plain_empty
            if only_core:
                sections = [(self.strings["rich_core"], core_entries)]
            elif only_loaded:
                sections = [(self.strings["rich_modules"], external_entries)]
            else:
                sections = [
                    (self.strings["rich_core"], core_entries),
                    (self.strings["rich_modules"], external_entries),
                ]
            rich_message = (
                (
                    f'<figure><img src="{utils.escape_html(str(self.config["banner_url"]))}"/></figure>'
                    if self.config["banner_url"]
                    else ""
                )
                + reply
                + "".join(
                    f"<details><summary>{title}</summary>"
                    + "".join(f"<p>{item}</p>" for item in content)
                    + "</details>"
                    for title, content in sections
                    if content
                )
                + (
                    f"<p>{self.strings['partial_load']}</p>"
                    if not self.lookup("Installer").fully_loaded
                    else ""
                )
            )
            await utils.answer_with_media_fallback(
                message,
                rich_message=rich_message,
            )
            return

        module_list = "\n".join(entries)
        await utils.answer_with_media_fallback(
            message,
            f"{reply}\n<blockquote expandable>{module_list}</blockquote>",
            file=banner,
            invert_media=self.config["invert_media"],
        )

    @loader.command()
    async def support(self, message):
        """Show Feroku support links."""
        await utils.answer(
            message,
            self.strings["offchats"],
        )
