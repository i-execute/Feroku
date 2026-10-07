# CopyLeft 2026 github.com/i-execute // i_execute.t.me
# Licensed under AGPLv3.

# (c) Dan Gazizullin, 2021-2023. This file is part of the Hikka Userbot: github.com/hikariatama/Hikka

import asyncio
import collections
import contextlib
import inspect
import logging
from collections.abc import Callable
import re
import sys
import traceback
import typing

from telethon import events
from telethon.errors import FloodWaitError, RPCError
from telethon.tl.types import Message

from . import main, security, utils
from .database import Database
from .loader import Modules
from .tl_cache import CustomTelegramClient

logger = logging.getLogger(__name__)



ALL_TAGS = [
    "no_commands",
    "only_commands",
    "out",
    "in",
    "only_messages",
    "editable",
    "no_media",
    "only_media",
    "only_photos",
    "only_videos",
    "only_audios",
    "only_docs",
    "only_stickers",
    "only_inline",
    "only_channels",
    "only_groups",
    "only_pm",
    "no_pm",
    "no_channels",
    "no_groups",
    "no_inline",
    "no_stickers",
    "no_docs",
    "no_audios",
    "no_videos",
    "no_photos",
    "no_forwards",
    "no_reply",
    "no_mention",
    "mention",
    "only_reply",
    "only_forwards",
    "startswith",
    "endswith",
    "contains",
    "regex",
    "filter",
    "from_id",
    "chat_id",
    "alias",
    "aliases",
]

def _decrement_ratelimit(delay, data, key, severity):
    def inner():
        data[key] = max(0, data[key] - severity)

    asyncio.get_event_loop().call_later(delay, inner)

class CommandDispatcher:
    def __init__(
        self,
        modules: Modules,
        client: CustomTelegramClient,
        db: Database,
    ):
        self._modules = modules
        self._client = client
        self.client = client
        self._db = db

        self._ratelimit_storage_user = collections.defaultdict(int)
        self._ratelimit_storage_chat = collections.defaultdict(int)
        self._ratelimit_max_user = db.get(__name__, "ratelimit_max_user", 30)
        self._ratelimit_max_chat = db.get(__name__, "ratelimit_max_chat", 100)

        self.security = security.SecurityManager(client, db)

        self.check_security = self.security.check
        self._me = self._client.feroku_me.id
        self._cached_usernames = set()

        if self._client.feroku_me.username:
            self._cached_usernames.add(self._client.feroku_me.username.lower())

        if self._client.feroku_me.usernames:
            self._cached_usernames.update(
                u.username.lower()
                for u in getattr(self._client.feroku_me, "usernames", [])
            )

        self._cached_usernames.add(str(self._client.feroku_me.id))

        self.raw_handlers = []



        self._pending_tasks: set[asyncio.Task] = set()












    @property
    def pending_tasks(self) -> set[asyncio.Task]:

        return self._pending_tasks

    def _default_handlers(self) -> list[tuple[Callable, typing.Any]]:
        return [
            (self.handle_incoming, events.NewMessage()),
            (self.handle_incoming, events.ChatAction()),
            (self.handle_command, events.NewMessage(forwards=False)),
            (self.handle_command, events.MessageEdited()),
            (self.handle_raw, events.Raw()),
        ]

    def _track(self, task: asyncio.Task) -> asyncio.Task:
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)
        return task

    def attach_handlers(self):
        for callback, builder in self._default_handlers():
            self._client.add_event_handler(callback, builder)

    async def _handle_ratelimit(self, message: Message, func: Callable) -> bool:
        if await self.security.check(message, security.OWNER):
            return True

        func = getattr(func, "__func__", func)
        ret = True
        chat = self._ratelimit_storage_chat[message.chat_id]

        if message.sender_id:
            user = self._ratelimit_storage_user[message.sender_id]
            severity = (5 if getattr(func, "ratelimit", False) else 2) * (
                (user + chat) // 30 + 1
            )
            user += severity
            self._ratelimit_storage_user[message.sender_id] = user
            if user > self._ratelimit_max_user:
                ret = False
            else:
                self._ratelimit_storage_chat[message.chat_id] = chat

            _decrement_ratelimit(
                self._ratelimit_max_user * severity,
                self._ratelimit_storage_user,
                message.sender_id,
                severity,
            )
        else:
            severity = (5 if getattr(func, "ratelimit", False) else 2) * (
                chat // 15 + 1
            )

        chat += severity

        if chat > self._ratelimit_max_chat:
            ret = False

        _decrement_ratelimit(
            self._ratelimit_max_chat * severity,
            self._ratelimit_storage_chat,
            message.chat_id,
            severity,
        )

        return ret

    def _handle_grep(self, message: Message) -> Message:

        if "||grep" in message.text or "|| grep" in message.text:
            message.raw_text = re.sub(r"\|\| ?grep", "| grep", message.raw_text)
            message.text = re.sub(r"\|\| ?grep", "| grep", message.text)
            message.message = re.sub(r"\|\| ?grep", "| grep", message.message)
            return message

        grep = False
        if not re.search(r".+\| ?grep (.+)", message.raw_text):
            return message

        grep = re.search(r".+\| ?grep (.+)", message.raw_text).group(1)
        message.text = re.sub(r"\| ?grep.+", "", message.text)
        message.raw_text = re.sub(r"\| ?grep.+", "", message.raw_text)
        message.message = re.sub(r"\| ?grep.+", "", message.message)

        ungrep = False

        if re.search(r"-v (.+)", grep):
            ungrep = re.search(r"-v (.+)", grep).group(1)
            grep = re.sub(r"(.+) -v .+", r"\g<1>", grep)

        grep = utils.escape_html(grep).strip() if grep else False
        ungrep = utils.escape_html(ungrep).strip() if ungrep else False

        old_edit = message.edit
        old_reply = message.reply
        old_respond = message.respond

        def process_text(text: str) -> str:
            res = []

            for line in text.split("\n"):
                if (
                    grep
                    and grep in utils.remove_html(line)
                    and (not ungrep or ungrep not in utils.remove_html(line))
                ):
                    res.append(
                        utils.remove_html(line, escape=True).replace(
                            grep, f"<u>{grep}</u>"
                        )
                    )

                if not grep and ungrep and ungrep not in utils.remove_html(line):
                    res.append(utils.remove_html(line, escape=True))

            cont = (
                (f"contain <b>{grep}</b>" if grep else "")
                + (" and" if grep and ungrep else "")
                + ((" do not contain <b>" + ungrep + "</b>") if ungrep else "")
            )

            if res:
                text = f"<i> Lines that {cont}:</i>\n" + "\n".join(res)
            else:
                text = f" <i>No lines that {cont}</i>"

            return text

        async def my_edit(text, *args, **kwargs):
            text = process_text(text)
            kwargs["parse_mode"] = "HTML"
            return await old_edit(text, *args, **kwargs)

        async def my_reply(text, *args, **kwargs):
            text = process_text(text)
            kwargs["parse_mode"] = "HTML"
            return await old_reply(text, *args, **kwargs)

        async def my_respond(text, *args, **kwargs):
            text = process_text(text)
            kwargs["parse_mode"] = "HTML"
            kwargs.setdefault("reply_to", utils.get_topic(message))
            return await old_respond(text, *args, **kwargs)

        message.edit = my_edit
        message.reply = my_reply
        message.respond = my_respond
        message.feroku_grepped = True

        return message

    async def _handle_command(
        self,
        event: events.NewMessage | events.MessageDeleted,
        watcher: bool = False,
    ) -> bool | tuple[Message, str, str, callable]:
        if not hasattr(event, "message") or not hasattr(event.message, "message"):
            return False

        initiator = getattr(event, "sender_id", 0)

        stored_prefix = self._db.get(main.__name__, "command_prefix", ".")
        main_prefix = utils.normalize_prefix(stored_prefix)
        if main_prefix != stored_prefix:
            self._db.set(main.__name__, "command_prefix", main_prefix)
        if initiator == self._client.tg_id:
            prefix = main_prefix
        else:
            prefix = self._db.get(main.__name__, "command_prefixes", {})
            prefix = utils.normalize_prefix(
                prefix.get(str(initiator)), main_prefix
            )

        message = utils.censor(event.message)

        if not event.message.message:
            return False

        if (
            message.out
            and len(message.message) > len(prefix) * 2
            and message.message.startswith(prefix * 2)
            and any(s != prefix for s in message.message)
        ):
            possible_cmd_str = message.message[len(prefix) * 2 :]
            possible_cmd = (
                possible_cmd_str.strip().split(maxsplit=1)[0].split("@", maxsplit=1)[0]
            )

            _, func = self._modules.dispatch(possible_cmd)

            if func:
                if not watcher:
                    await message.edit(
                        message.message[len(prefix) :],
                        parse_mode=lambda s: (
                            s,
                            utils.relocate_entities(message.entities, -1)
                            or (),
                        ),
                    )
                return False

        if not event.message.message.startswith(prefix):
            return False
        _msg = message.message

        if (
            event.sticker
            or event.dice
            or event.audio
            or event.via_bot_id
            or (getattr(event, "reactions", False) and getattr(event, "edit_hide", False))
        ):
            return False

        blacklist_chats = self._db.get(main.__name__, "blacklist_chats", [])
        whitelist_chats = self._db.get(main.__name__, "whitelist_chats", [])
        whitelist_modules = self._db.get(main.__name__, "whitelist_modules", [])

        if (chat_id := utils.get_chat_id(message)) in blacklist_chats or (
            whitelist_chats and chat_id not in whitelist_chats
        ):
            return False

        if not _msg or len(_msg.strip()) == len(prefix):
            return False

        _cmd = _msg[len(prefix) :]
        command = _cmd.strip().split(maxsplit=1)[0]
        tag = command.split("@", maxsplit=1)

        if len(tag) == 2:
            if tag[1] == "me":
                if not message.out:
                    return False
            elif tag[1].lower() not in self._cached_usernames:
                return False
        elif (
            event.out
            or event.mentioned
            and event.message is not None
            and event.message.message is not None
            and not any(
                f"@{username}" in command.lower() for username in self._cached_usernames
            )
        ):
            pass
        elif (
            not event.is_private
            and not self._db.get(main.__name__, "no_nickname", False)
            and command not in self._db.get(main.__name__, "nonickcmds", [])
            and initiator not in self._db.get(main.__name__, "nonickusers", [])
            and not self.security.check_tsec(initiator, command)
            and utils.get_chat_id(event)
            not in self._db.get(main.__name__, "nonickchats", [])
        ):
            return False

        txt, func = self._modules.dispatch(tag[0])

        if (
            not func
            or not await self._handle_ratelimit(message, func)
            or not await self.security.check(
                message,
                func,
                usernames=self._cached_usernames,
            )
        ):
            return False

        if message.is_channel and message.edit_date and not message.is_group:
            async for event in self._client.iter_admin_log(
                chat_id,
                limit=10,
                edit=True,
            ):
                if event.action.prev_message.id == message.id:
                    if event.user_id != self._client.tg_id:
                        logger.debug("Ignoring edit in channel")
                        return False

                    break

            return False

        _cmd_offset = len(prefix) + len(_cmd) - len(_cmd.strip())
        if not watcher:
            new_text = prefix + txt + _msg[_cmd_offset + len(command) :]
            if new_text != message.message:
                _offset = len(new_text) - len(message.message)

                if _offset:
                    utils.relocate_entities(message.entities, _offset)

                message._text = None
                message.message = new_text

        if (
            f"{str(chat_id)}.{func.__self__.__module__}" in blacklist_chats
            or whitelist_modules
            and f"{chat_id}.{func.__self__.__module__}" not in whitelist_modules
        ):
            return False

        if await self._handle_tags(event, func):
            return False

        if self._db.get(main.__name__, "grep", False) and not watcher:
            message = self._handle_grep(message)

        return message, prefix, txt, func

    async def handle_raw(self, event: events.Raw):
        for handler in self.raw_handlers:
            if isinstance(event, tuple(handler.updates)):
                try:
                    await handler(event)
                except Exception as e:
                    logger.exception("Error in raw handler %s: %s", handler.id, e)

    async def handle_command(
        self,
        event: events.NewMessage | events.MessageDeleted,
    ):
        message = await self._handle_command(event)
        if not message:
            return

        message, _, _, func = message

        self._track(
            asyncio.ensure_future(
                self.future_dispatcher(
                    func,
                    message,
                    self.command_exc,
                )
            )
        )

    async def command_exc(self, _, message: Message):
        exc = sys.exc_info()[1]
        logger.exception("Command failed", extra={"stack": inspect.stack()})
        if isinstance(exc, RPCError):
            if isinstance(exc, FloodWaitError):
                hours = exc.seconds // 3600
                minutes = (exc.seconds % 3600) // 60
                seconds = exc.seconds % 60
                hours = f"{hours} hours, " if hours else ""
                minutes = f"{minutes} minutes, " if minutes else ""
                seconds = f"{seconds} seconds" if seconds else ""
                fw_time = f"{hours}{minutes}{seconds}"
                txt = (
                    "<b>Call</b> <code>{}</code><b> failed due to flood wait ({}):</b> <code>{}</code>".format(
                        utils.escape_html(message.message),
                        fw_time,
                        type(exc.request).__name__,
                    )
                )
            else:
                txt = (
                    " <b>Call"
                    f" </b><code>{utils.escape_html(message.message)}</code><b> failed"
                    " due to RPC (Telegram) error:</b>"
                    f" <code>{utils.escape_html(str(exc))}</code>"
                )
                txt = (
                    "<b>Call</b> <code>{}</code><b> failed due to RPC (Telegram) error:</b> <code>{}</code>".format(
                        utils.escape_html(message.message),
                        utils.escape_html(str(exc)),
                    )
                )
        else:
            if not self._db.get(main.__name__, "inlinelogs", True):
                txt = (
                    "<b> Call</b>"
                    f" <code>{utils.escape_html(message.message)}</code><b>"
                    " failed!</b>"
                )
            else:
                exc = "\n".join(traceback.format_exc().splitlines()[1:])
                txt = (
                    "<b> Call</b>"
                    f" <code>{utils.escape_html(message.message)}</code><b>"
                    " failed!</b>\n\n<b> Logs:</b>\n<pre><code"
                    f' class="language-logs">{utils.escape_html(exc)}</code></pre>'
                )

        with contextlib.suppress(Exception):
            await (message.edit if message.out else message.reply)(txt)

    async def watcher_exc(self, *_):
        logger.exception("Error running watcher", extra={"stack": inspect.stack()})

    async def _handle_tags(
        self,
        event: events.NewMessage | events.MessageDeleted,
        func: Callable,
    ) -> bool:
        return bool(await self._handle_tags_ext(event, func))

    async def _handle_tags_ext(
        self,
        event: events.NewMessage | events.MessageDeleted,
        func: Callable,
    ) -> str:
        m = event if isinstance(event, Message) else getattr(event, "message", event)

        reverse_mapping = {
            "out": lambda: getattr(m, "out", True),
            "in": lambda: not getattr(m, "out", True),
            "only_messages": lambda: isinstance(m, Message),
            "editable": (
                lambda: not getattr(m, "out", False)
                and not getattr(m, "fwd_from", False)
                and not getattr(m, "sticker", False)
                and not getattr(m, "via_bot_id", False)
            ),
            "no_media": lambda: (
                not isinstance(m, Message) or not getattr(m, "media", False)
            ),
            "only_media": lambda: isinstance(m, Message) and getattr(m, "media", False),
            "only_photos": lambda: utils.mime_type(m).startswith("image/"),
            "only_videos": lambda: utils.mime_type(m).startswith("video/"),
            "only_audios": lambda: utils.mime_type(m).startswith("audio/"),
            "only_stickers": lambda: getattr(m, "sticker", False),
            "only_docs": lambda: getattr(m, "document", False),
            "only_inline": lambda: getattr(m, "via_bot_id", False),
            "only_channels": lambda: (
                getattr(m, "is_channel", False) and not getattr(m, "is_group", False)
            ),
            "no_channels": lambda: not getattr(m, "is_channel", False),
            "no_groups": (
                lambda: not getattr(m, "is_group", False)
                or getattr(m, "is_private", False)
                or getattr(m, "is_channel", False)
            ),
            "only_groups": (
                lambda: getattr(m, "is_group", False)
                or not getattr(m, "is_private", False)
                and not getattr(m, "is_channel", False)
            ),
            "no_pm": lambda: not getattr(m, "is_private", False),
            "only_pm": lambda: getattr(m, "is_private", False),
            "no_inline": lambda: not getattr(m, "via_bot_id", False),
            "no_stickers": lambda: not getattr(m, "sticker", False),
            "no_docs": lambda: not getattr(m, "document", False),
            "no_audios": lambda: not utils.mime_type(m).startswith("audio/"),
            "no_videos": lambda: not utils.mime_type(m).startswith("video/"),
            "no_photos": lambda: not utils.mime_type(m).startswith("image/"),
            "no_forwards": lambda: not getattr(m, "fwd_from", False),
            "no_reply": lambda: not getattr(m, "reply_to_msg_id", False),
            "only_forwards": lambda: getattr(m, "fwd_from", False),
            "only_reply": lambda: getattr(m, "reply_to_msg_id", False),
            "mention": lambda: getattr(m, "mentioned", False),
            "no_mention": lambda: not getattr(m, "mentioned", False),
            "startswith": lambda: (
                isinstance(m, Message) and m.raw_text.startswith(func.startswith)
            ),
            "endswith": lambda: (
                isinstance(m, Message) and m.raw_text.endswith(func.endswith)
            ),
            "contains": lambda: isinstance(m, Message) and func.contains in m.raw_text,
            "filter": lambda: callable(func.filter) and func.filter(m),
            "from_id": lambda: getattr(m, "sender_id", None) == func.from_id,
            "chat_id": lambda: utils.get_chat_id(m)
            == (
                func.chat_id
                if not str(func.chat_id).startswith("-100")
                else int(str(func.chat_id)[4:])
            ),
            "regex": lambda: (
                isinstance(m, Message) and re.search(func.regex, m.raw_text)
            ),
        }

        return (
            "no_commands"
            if getattr(func, "no_commands", False)
            and await self._handle_command(event, watcher=True)
            else (
                "only_commands"
                if getattr(func, "only_commands", False)
                and not await self._handle_command(event, watcher=True)
                else next(
                    (
                        tag
                        for tag in ALL_TAGS
                        if getattr(func, tag, False)
                        and tag in reverse_mapping
                        and not reverse_mapping[tag]()
                    ),
                    None,
                )
            )
        )

    async def handle_incoming(
        self,
        event: events.NewMessage | events.MessageDeleted,
    ):
        message = utils.censor(getattr(event, "message", event))

        blacklist_chats = self._db.get(main.__name__, "blacklist_chats", [])
        whitelist_chats = self._db.get(main.__name__, "whitelist_chats", [])
        whitelist_modules = self._db.get(main.__name__, "whitelist_modules", [])

        if (chat_id := utils.get_chat_id(message)) in blacklist_chats or (
            whitelist_chats and chat_id not in whitelist_chats
        ):
            logger.debug("Message is blocklisted")
            return True

        for func in self._modules.watchers:
            bl = self._db.get(main.__name__, "disabled_watchers", {})
            modname = str(func.__self__.__class__.strings["name"])

            if (
                modname in bl
                and isinstance(message, Message)
                and (
                    "*" in bl[modname]
                    or chat_id in bl[modname]
                    or "only_chats" in bl[modname]
                    and message.is_private
                    or "only_pm" in bl[modname]
                    and not message.is_private
                    or "out" in bl[modname]
                    and not message.out
                    or "in" in bl[modname]
                    and message.out
                )
                or f"{str(chat_id)}.{func.__self__.__module__}" in blacklist_chats
                or whitelist_modules
                and f"{str(chat_id)}.{func.__self__.__module__}"
                not in whitelist_modules
                or await self._handle_tags(event, func)
            ):
                continue

            for placeholder in {"text", "raw_text", "out"}:
                try:
                    if not hasattr(message, placeholder):
                        setattr(message, placeholder, "")
                except UnicodeDecodeError:
                    pass

            self._track(
                asyncio.ensure_future(
                    self.future_dispatcher(
                        func,
                        message,
                        self.watcher_exc,
                    )
                )
            )

    async def future_dispatcher(
        self,
        func: Callable,
        message: Message,
        exception_handler: Callable,
        *args,
    ):
        try:
            await func(message)
        except Exception as e:
            await exception_handler(e, message, *args)
