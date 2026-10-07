import asyncio
import contextlib
import hashlib
import io

from telethon import TelegramClient, events
from telethon.errors import (
    AuthKeyDuplicatedError,
    AuthKeyUnregisteredError,
    FloodWaitError,
)
from telethon.sessions import SQLiteSession, StringSession
from telethon.tl.custom.button import Button
from telethon.tl.types import InputPeerUser, UpdateBotInlineSend

from .utils.other import rand as utils_rand


class BotPM:
    def __init__(self, api_id: int, api_hash: str, token: str, session=None):
        self.token = token
        self.client = TelegramClient(
            session if session is not None else StringSession(),
            api_id,
            api_hash,
            connection_retries=None,
        )
        self.chat_id: int | None = None
        self.owner_id: int | None = None
        self._ask_state: tuple | None = None
        self._choice_state: asyncio.Future | None = None
        self._choice_options: dict[str, str] = {}
        self._qr_msg = None
        self.bot_id: int | None = None
        self.username: str | None = None
        self.owner_access_hash: int | None = None
        self._started = False
        self._handlers_registered = False
        self._start_lock = asyncio.Lock()
        self._flow_message_ids: set[int] = set()
        self._seen_starts: dict[int, tuple[int, int | None]] = {}

    async def start(self):
        async with self._start_lock:
            if self._started and self.client.is_connected():
                return await self.client.get_me()
            while True:
                try:
                    await self.client.start(bot_token=self.token)
                    break
                except (AuthKeyDuplicatedError, AuthKeyUnregisteredError):
                    await self.client.disconnect()
                    self.client.session.auth_key = None
                    self.client.session.save()
                except FloodWaitError as error:
                    await self.client.disconnect()
                    await asyncio.sleep(max(int(error.seconds), 1) + 1)
            me = await self.client.get_me()
            self.bot_id = me.id
            self.username = me.username
            if not self._handlers_registered:
                self.client.add_event_handler(self._on_iq, events.InlineQuery())
                self.client.add_event_handler(self._on_callback, events.CallbackQuery())
                self.client.add_event_handler(
                    self._on_inline_send, events.Raw(types=UpdateBotInlineSend)
                )
                self.client.add_event_handler(
                    self._on_input_marker, events.NewMessage(incoming=True)
                )
                self._handlers_registered = True
            self._started = True
            return me

    def save_session(self, path: str):
        session = SQLiteSession(path)
        session.set_dc(
            self.client.session.dc_id,
            self.client.session.server_address,
            self.client.session.port,
        )
        session.auth_key = self.client.session.auth_key
        session.save()
        session.close()

    async def bind_owner(self, owner_id: int, access_hash=None):
        self.owner_id = int(owner_id)
        if access_hash:
            self.owner_access_hash = int(access_hash)
        try:
            self.chat_id = await self.client.get_input_entity(self.owner_id)
            self.owner_access_hash = getattr(
                self.chat_id,
                "access_hash",
                self.owner_access_hash,
            )
        except Exception:
            self.chat_id = InputPeerUser(
                self.owner_id,
                self.owner_access_hash or 0,
            )

    async def _on_iq(self, event):
        state = self._ask_state
        if not state:
            return
        token, _, label, marker = state
        if self.owner_id and event.query.user_id != self.owner_id:
            return
        text = event.text or ""
        parts = text.split(maxsplit=1)
        if not parts or parts[0] != token:
            return
        await event.answer(
            [
                await event.builder.article(
                    label,
                    description=label,
                    text=marker,
                    parse_mode=None,
                    id=hashlib.sha256(text.encode()).hexdigest(),
                )
            ],
            cache_time=0,
            private=True,
        )

    async def _on_inline_send(self, update):
        state = self._ask_state
        if not state:
            return
        token, fut, *_ = state
        if fut.done() or self.owner_id and update.user_id != self.owner_id:
            return
        query = getattr(update, "query", "") or ""
        parts = query.split(maxsplit=1)
        if len(parts) < 2 or parts[0] != token:
            return
        fut.set_result(parts[1])

    async def _on_input_marker(self, event):
        message = event.message
        state = self._ask_state
        if (
            not state
            or self.owner_id
            and event.sender_id != self.owner_id
            or getattr(message, "via_bot_id", None) != self.bot_id
            or getattr(message, "raw_text", None) != state[3]
        ):
            return
        with contextlib.suppress(asyncio.TimeoutError, asyncio.CancelledError):
            await asyncio.wait_for(asyncio.shield(state[1]), timeout=10)
        with contextlib.suppress(Exception):
            await event.delete()

    async def _on_callback(self, event):
        if not self._choice_state or self._choice_state.done():
            return
        if self.owner_id and event.sender_id != self.owner_id:
            await event.answer("Not for you", alert=True)
            return
        data = event.data.decode(errors="ignore")
        if data not in self._choice_options:
            return
        self._choice_state.set_result(self._choice_options[data])
        await event.answer()
        with contextlib.suppress(Exception):
            await event.delete()

    async def _remember_start(self, event) -> None:
        access_hash = None
        with contextlib.suppress(Exception):
            sender = await event.get_sender()
            access_hash = getattr(sender, "access_hash", None)
        self._seen_starts[event.sender_id] = (event.chat_id, access_hash)

    def _bind_owner_id(self, expected_id: int | None) -> None:
        waiter = asyncio.get_running_loop().create_future()

        @self.client.on(events.NewMessage(pattern=r"^/start"))
        async def _on_start(event):
            await self._remember_start(event)
            if expected_id and event.sender_id != expected_id:
                with contextlib.suppress(Exception):
                    await event.reply("<b>Not for you</b>", parse_mode="HTML")
                return
            if not waiter.done():
                self.chat_id = event.chat_id
                self.owner_access_hash = self._seen_starts[event.sender_id][1]
                waiter.set_result(event.chat_id)

        self._waiter = waiter

    def start_echo(self):
        @self.client.on(events.NewMessage(pattern=r"^/start"))
        async def _echo(event):
            await self._remember_start(event)
            with contextlib.suppress(Exception):
                await event.reply(
                    "<b>Your Telegram ID</b>\n"
                    f"<blockquote><code>{event.sender_id}</code></blockquote>",
                    parse_mode="HTML",
                )

        self._echo_handler = _echo

    def stop_echo(self):
        if getattr(self, "_echo_handler", None):
            self.client.remove_event_handler(self._echo_handler)
            self._echo_handler = None

    async def wait_start(self, expected_id: int | None = None) -> int:
        if expected_id in self._seen_starts:
            self.chat_id, self.owner_access_hash = self._seen_starts[expected_id]
            return self.chat_id
        self._bind_owner_id(expected_id)
        return await self._waiter

    def _track_message(self, message):
        message_id = getattr(message, "id", None)
        if isinstance(message_id, int):
            self._flow_message_ids.add(message_id)
        return message

    async def clear_flow_messages(self):
        if self.chat_id and self._flow_message_ids:
            with contextlib.suppress(Exception):
                await self.client.delete_messages(
                    self.chat_id,
                    list(self._flow_message_ids),
                )
        self._flow_message_ids.clear()
        self._qr_msg = None

    async def send(self, text: str, *, track: bool = True):
        message = await self.client.send_message(
            self.chat_id,
            text,
            buttons=Button.clear(),
            parse_mode="HTML",
        )
        return self._track_message(message) if track else message

    async def _choose(self, text: str, buttons, options: dict[str, str]) -> str:
        self._choice_state = asyncio.get_running_loop().create_future()
        self._choice_options = options
        self._track_message(
            await self.client.send_message(
                self.chat_id,
                text,
                buttons=buttons,
                parse_mode="HTML",
            )
        )
        try:
            return await self._choice_state
        finally:
            self._choice_state = None
            self._choice_options = {}

    async def choose_auth(self) -> str:
        return await self._choose(
            "<b>Choose the login method</b>\n"
            "<blockquote>Select QR code or phone number.</blockquote>",
            [
                [
                    Button.inline("QR code", b"auth_qr", style="primary"),
                    Button.inline("Phone number", b"auth_phone", style="success"),
                ]
            ],
            {"auth_qr": "qr", "auth_phone": "phone"},
        )

    async def choose_recovery(self) -> str:
        return await self._choose(
            "<b>The user session is no longer valid</b>\n"
            "<blockquote>Create a new session or remove Feroku.</blockquote>",
            [
                [
                    Button.inline(
                        "Create new session", b"recovery_create", style="success"
                    )
                ],
                [
                    Button.inline("Run Nuke.sh", b"recovery_nuke", style="danger")
                ],
            ],
            {"recovery_create": "create", "recovery_nuke": "nuke"},
        )

    async def confirm_nuke(self) -> str:
        return await self._choose(
            "<b>Permanent removal</b>\n"
            "<blockquote>Nuke.sh will remove Feroku, its sessions, databases "
            "and modules.</blockquote>",
            [
                [
                    Button.inline(
                        "Confirm removal", b"nuke_confirm", style="danger"
                    )
                ],
                [Button.inline("Back", b"nuke_back", style="primary")],
            ],
            {"nuke_confirm": "confirm", "nuke_back": "back"},
        )

    async def ask(
        self,
        prompt: str,
        label: str = "Enter value",
        marker: str = "📝",
    ) -> str:
        token = utils_rand(10)
        fut = asyncio.get_running_loop().create_future()
        self._ask_state = (token, fut, label, marker)
        self._track_message(
            await self.client.send_message(
                self.chat_id,
                prompt,
                buttons=Button.switch_inline(
                    label, query=token, same_peer=True, style="primary"
                ),
                parse_mode="HTML",
            )
        )
        try:
            return await fut
        finally:
            self._ask_state = None

    async def send_photo(self, png: bytes, caption: str):
        bio = io.BytesIO(png)
        bio.name = "qr.png"
        msg = await self.client.send_file(
            self.chat_id,
            file=bio,
            caption=caption,
            force_document=False,
            parse_mode="HTML",
        )
        if self._qr_msg is not None:
            with contextlib.suppress(Exception):
                await self._qr_msg.delete()
        self._qr_msg = msg
        return self._track_message(msg)

    async def edit_photo(self, png: bytes, caption: str):
        if self._qr_msg is None:
            return await self.send_photo(png, caption)
        bio = io.BytesIO(png)
        bio.name = "qr.png"
        try:
            self._qr_msg = await self.client.edit_message(
                self.chat_id,
                self._qr_msg,
                text=caption,
                file=bio,
                parse_mode="HTML",
            )
            return self._qr_msg
        except Exception:
            return await self.send_photo(png, caption)

    async def close(self):
        await self.client.disconnect()
        self._started = False
