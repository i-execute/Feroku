# CopyLeft 2026 github.com/i-execute // i_execute.t.me
# Licensed under AGPLv3.

# (c) Dan Gazizullin, 2021-2023. This file is part of the Hikka Userbot: github.com/hikariatama/Hikka

import asyncio
import logging
import os
import sqlite3
import time
import typing

from telethon import TelegramClient, events
from telethon.errors.rpcerrorlist import (
    AccessTokenExpiredError,
    AccessTokenInvalidError,
    AuthKeyDuplicatedError,
    AuthKeyUnregisteredError,
    FloodWaitError,
)
from telethon.sessions import SQLiteSession
from telethon.tl.types import (
    Message,
    UpdateBotChatBoost,
    UpdateBotChatInviteRequester,
    UpdateBotGuestChatQuery,
    UpdateBotInlineSend,
    UpdateBotMessageReaction,
    UpdateBotMessageReactions,
    UpdateBotPrecheckoutQuery,
    UpdateBotShippingQuery,
    UpdateChannelParticipant,
    UpdateChatParticipant,
    UpdateMessagePoll,
    UpdateMessagePollVote,
)
from .. import main, utils
from ..database import Database
from ._strings import _ServiceStrings
from ..tl_cache import CustomTelegramClient
from .bot_pm import BotPM
from .events import Events
from .form import Form
from .gallery import Gallery
from .list import List
from .query_gallery import QueryGallery
from .tl import TelethonBot, web_document
from .utils import Utils

logger = logging.getLogger(__name__)

if typing.TYPE_CHECKING:
    from ..loader import Modules

BotUpdateType = typing.Literal[
    "message",
    "edited_message",
    "channel_post",
    "edited_channel_post",
    "inline_query",
    "callback_query",
    "chosen_inline_result",
    "shipping_query",
    "pre_checkout_query",
    "poll",
    "poll_answer",
    "my_chat_member",
    "chat_member",
    "chat_join_request",
    "message_reaction",
    "message_reaction_count",
    "chat_boost",
    "removed_chat_boost",
    "guest_message",
]

_BOT_UPDATE_EVENTS: dict[BotUpdateType, typing.Callable[[], object]] = {

    "message": lambda: events.NewMessage(),
    "edited_message": lambda: events.MessageEdited(),
    "channel_post": lambda: events.NewMessage(),
    "edited_channel_post": lambda: events.MessageEdited(),
    "inline_query": lambda: events.InlineQuery(),
    "callback_query": lambda: events.CallbackQuery(),

    "chosen_inline_result": lambda: events.Raw(types=UpdateBotInlineSend),
    "shipping_query": lambda: events.Raw(types=UpdateBotShippingQuery),
    "pre_checkout_query": lambda: events.Raw(types=UpdateBotPrecheckoutQuery),
    "poll": lambda: events.Raw(types=UpdateMessagePoll),
    "poll_answer": lambda: events.Raw(types=UpdateMessagePollVote),
    "my_chat_member": lambda: events.Raw(
        types=(UpdateChatParticipant, UpdateChannelParticipant)
    ),
    "chat_member": lambda: events.Raw(
        types=(UpdateChatParticipant, UpdateChannelParticipant)
    ),
    "chat_join_request": lambda: events.Raw(types=UpdateBotChatInviteRequester),
    "message_reaction": lambda: events.Raw(types=UpdateBotMessageReaction),
    "message_reaction_count": lambda: events.Raw(types=UpdateBotMessageReactions),
    "chat_boost": lambda: events.Raw(types=UpdateBotChatBoost),
    "removed_chat_boost": lambda: events.Raw(types=UpdateBotChatBoost),
    "guest_message": lambda: events.Raw(types=UpdateBotGuestChatQuery),
}

class InlineManager(
    Utils,
    Events,
    Form,
    Gallery,
    QueryGallery,
    List,
    BotPM,
):
    def __init__(
        self,
        client: CustomTelegramClient,
        db: Database,
        allmodules: "Modules",
    ):
        self._client = client
        self._db = db
        self._allmodules = allmodules
        self.translator = _ServiceStrings()

        self._units: dict[str, dict] = {}
        self._custom_map: dict[str, callable] = {}
        self.fsm: dict[str, str] = {}
        self._error_events: dict[str, asyncio.Event] = {}

        self._markup_ttl = 60 * 60 * 24
        self.init_complete = False

        self._me: int = None
        self._bot_client: TelegramClient = None
        self._cleaner_task: asyncio.Future = None
        self.bot: TelethonBot = None
        self.bot_id: int = None
        self.bot_username: str = None

        self._bot_update_handlers: dict[str, tuple[str, typing.Callable]] = {}
        self._bot_handler_refs: dict[str, tuple[typing.Callable, object]] = {}
        self._input_marker_event = None
        self._input_marker_events = asyncio.Queue()

    async def _cleaner(self):
        while True:
            for unit_id, unit in self._units.copy().items():
                if (unit.get("ttl") or (time.time() + self._markup_ttl)) < time.time():
                    await self._unload_unit(unit_id)

            await asyncio.sleep(5)

    @staticmethod
    def _web_document(url: str | None, **kwargs):
        return web_document(url, **kwargs)

    def _register_bot_handler(
        self,
        handler: typing.Callable,
        event_builder,
        *,
        handler_id: str | None = None,
    ):
        self._bot_client.add_event_handler(handler, event_builder)
        if handler_id:
            self._bot_handler_refs[handler_id] = (handler, event_builder)

    def _register_builtin_handlers(self):
        self._register_bot_handler(self._inline_handler, events.InlineQuery())
        self._register_bot_handler(self._callback_query_handler, events.CallbackQuery())
        self._register_bot_handler(
            self._chosen_inline_handler, events.Raw(types=UpdateBotInlineSend)
        )
        self._register_bot_handler(self._message_handler, events.NewMessage())

        if self._input_marker_event is None:
            self._input_marker_event = events.NewMessage(outgoing=True)
            self._client.add_event_handler(
                self._inline_input_marker_handler,
                self._input_marker_event,
            )

        for handler_id, (update_type, handler) in self._bot_update_handlers.items():
            self._attach_custom_handler(handler_id, update_type, handler)

    def _cleanup_stale_bot_sessions(self, bot_uid: str):
        prefix = f"feroku-{self._me}-bot-"
        keep_stem = f"{prefix}{bot_uid}"

        try:
            entries = list(os.scandir(main.SESSIONS_DIR))
        except FileNotFoundError:
            return

        for entry in entries:
            if not entry.is_file() or not entry.name.startswith(prefix):
                continue

            if entry.name.split(".session", 1)[0] == keep_stem:
                continue

            try:
                os.remove(entry.path)
            except OSError:
                logger.exception(
                    "Failed to remove stale bot session file %s", entry.path
                )

    async def register_manager(self):
        self._me = self._client.tg_id
        token = main.get_config_key("bot_token")
        self.init_complete = False
        if not token:
            logger.critical("Bot token is missing. Restart and enter it in the terminal.")
            return False
        if self._bot_client:
            try:
                await self._bot_client.disconnect()
            except Exception:
                pass
        bot_uid = token.split(":", 1)[0]
        self._cleanup_stale_bot_sessions(bot_uid)
        self._bot_client = TelegramClient(
            SQLiteSession(
                os.path.join(main.SESSIONS_DIR, f"feroku-{self._me}-bot-{bot_uid}")
            ),
            self._client.api_id,
            self._client.api_hash,
            receive_updates=True,
        )
        while True:
            try:
                await self._bot_client.start(bot_token=token)
                bot_me = await self._bot_client.get_me()
                break
            except (AccessTokenExpiredError, AccessTokenInvalidError):
                logger.critical("Bot token is invalid. Restart and enter a valid token.")
                main.save_config_key("bot_token", "")
                return False
            except (AuthKeyDuplicatedError, AuthKeyUnregisteredError):
                await self._bot_client.disconnect()
                self._bot_client.session.auth_key = None
                self._bot_client.session.save()
            except FloodWaitError as error:
                delay = max(int(error.seconds), 1) + 1
                logger.warning("Inline bot authorization will retry in %s seconds", delay)
                await self._bot_client.disconnect()
                await asyncio.sleep(delay)
            except sqlite3.OperationalError:
                logger.critical("Bot session database is locked", exc_info=True)
                return False
        if getattr(bot_me, "bot_inline_placeholder", None) is None:
            logger.critical("Inline mode is disabled for @%s", bot_me.username)
            await self._bot_client.disconnect()
            return False
        self.bot = TelethonBot(self._bot_client)
        self._bot_client._tg_id = bot_me.id
        self._bot_client.tg_id = bot_me.id
        self._bot_client.feroku_me = bot_me
        self.bot_username = bot_me.username
        self.bot_id = bot_me.id
        self._register_builtin_handlers()
        self._cleaner_task = asyncio.ensure_future(self._cleaner())
        self.init_complete = True
        return True

    def _attach_custom_handler(
        self,
        handler_id: str,
        update_type: str,
        handler: typing.Callable,
    ):
        builder_factory = _BOT_UPDATE_EVENTS.get(update_type)
        if not builder_factory or not self._bot_client:
            return

        event_builder = builder_factory()
        self._register_bot_handler(handler, event_builder, handler_id=handler_id)

    def register_bot_update_handler(
        self,
        handler_id: str,
        update_type: str,
        handler: typing.Callable,
    ):
        if update_type not in _BOT_UPDATE_EVENTS:
            logger.warning(
                "Unsupported bot update type: %s (handler_id=%s)",
                update_type,
                handler_id,
            )
            return

        self._bot_update_handlers[handler_id] = (update_type, handler)
        logger.debug(
            "Registered bot update handler %s for update type %s",
            handler_id,
            update_type,
        )

        if self.init_complete and self._bot_client:
            self._attach_custom_handler(handler_id, update_type, handler)

    def unregister_bot_update_handler(self, handler_id: str):
        if handler_id not in self._bot_update_handlers:
            return

        del self._bot_update_handlers[handler_id]
        removed_ref = self._bot_handler_refs.pop(handler_id, None)
        logger.debug("Unregistered bot update handler %s", handler_id)

        if not self._bot_client:
            return

        refs = list(self._bot_handler_refs.values())
        if removed_ref:
            refs.append(removed_ref)

        for handler, event_builder in refs:
            self._bot_client.remove_event_handler(handler, event_builder)
        self._bot_handler_refs.clear()

        for hid, (update_type, handler) in self._bot_update_handlers.items():
            builder_factory = _BOT_UPDATE_EVENTS.get(update_type)
            if not builder_factory:
                continue
            event_builder = builder_factory()
            self._bot_client.add_event_handler(handler, event_builder)
            self._bot_handler_refs[hid] = (handler, event_builder)
        logger.debug("Rebuilt custom handlers after unregistering %s", handler_id)

    async def _invoke_unit(
        self,
        unit_id: str,
        message: Message,
        reply_to: Message | int | None = None,
    ) -> Message:
        event = asyncio.Event()
        self._error_events[unit_id] = event

        q = None
        exception: Exception = None

        async def result_getter():
            nonlocal q
            try:
                q = await self._client.inline_query(self.bot_username, unit_id)
            except Exception:
                logger.exception("Inline query for unit %s failed", unit_id)

        async def event_poller():
            nonlocal exception
            try:
                await asyncio.wait_for(event.wait(), timeout=10)
            except asyncio.TimeoutError:
                logger.debug("Inline query for unit %s timed out after 10s", unit_id)
                return
            if self._error_events.get(unit_id):
                exception = self._error_events[unit_id]

        result_getter_task = asyncio.ensure_future(result_getter())
        event_poller_task = asyncio.ensure_future(event_poller())

        _, pending = await asyncio.wait(
            [result_getter_task, event_poller_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in pending:
            task.cancel()

        self._error_events.pop(unit_id, None)

        if exception:
            raise exception

        if not q:
            raise Exception("No query results")

        return await q[0].click(
            utils.get_chat_id(message) if isinstance(message, Message) else message,
            reply_to=(
                reply_to
                if reply_to is not None
                else (
                    message.reply_to_msg_id if isinstance(message, Message) else None
                )
            ),
        )
