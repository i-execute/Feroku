import asyncio
import contextlib
import html
import io
import logging
import os

import qrcode
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import MemorySession, SQLiteSession

from . import main as feroku_main
from .botpm import BotPM

logger = logging.getLogger(__name__)

QR_REFRESH = 15
TOTAL_TIMEOUT = 180


def _bot_session_path(owner_id: int, token: str) -> str:
    bot_uid = token.split(":", 1)[0]
    return os.path.join(
        feroku_main.SESSIONS_DIR,
        f"feroku-{owner_id}-bot-{bot_uid}",
    )


async def _run_nuke():
    process = await asyncio.create_subprocess_exec(
        "bash",
        os.path.join(feroku_main.BASE_DIR, "Storage", "Nuke.sh"),
    )
    await process.wait()


def _qr_bytes(url: str) -> bytes:
    image = qrcode.make(url)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


async def _delete_inline_messages(client, bot: BotPM):
    if not bot.username or not bot.bot_id:
        return
    try:
        messages = await client.get_messages(bot.username, limit=100)
    except Exception:
        logger.debug("Failed to load registration input messages", exc_info=True)
        return
    message_ids = [
        message.id
        for message in messages
        if getattr(message, "out", False)
        and getattr(message, "via_bot_id", None) == bot.bot_id
        and getattr(message, "raw_text", None) in {"📝", "🔐", "\u2063"}
    ]
    if not message_ids:
        return
    with contextlib.suppress(Exception):
        await client.delete_messages(bot.username, message_ids)


async def _save_session(client, me) -> None:
    session = SQLiteSession(
        os.path.join(feroku_main.SESSIONS_DIR, f"feroku-{me.id}")
    )
    session.set_dc(
        client.session.dc_id, client.session.server_address, client.session.port
    )
    session.auth_key = client.session.auth_key
    session.save()
    session.close()


async def _qr_login(client, bot: BotPM):
    await client.connect()
    qr = await client.qr_login()
    await bot.send_photo(
        _qr_bytes(qr.url),
        "<b>Open Telegram &gt; Settings &gt; Devices &gt; Link Desktop Device</b>\n"
        "<blockquote>The QR code refreshes automatically.</blockquote>",
    )
    elapsed = 0.0
    while elapsed < TOTAL_TIMEOUT:
        try:
            return await asyncio.wait_for(
                qr.wait(), timeout=min(QR_REFRESH, TOTAL_TIMEOUT - elapsed)
            )
        except SessionPasswordNeededError:
            password = await asyncio.wait_for(
                bot.ask(
                    "<b>Two-factor authentication</b>\n"
                    "<blockquote>Enter the 2FA password.</blockquote>",
                    "Enter password",
                    "🔐",
                ),
                timeout=TOTAL_TIMEOUT,
            )
            await client.sign_in(password=password)
            return await client.get_me()
        except asyncio.TimeoutError:
            elapsed += QR_REFRESH
            if elapsed >= TOTAL_TIMEOUT:
                break
            await qr.recreate()
            await bot.edit_photo(
                _qr_bytes(qr.url),
                "<b>The QR code was refreshed</b>\n"
                "<blockquote>Scan the new code.</blockquote>",
            )
    return None


async def _phone_login(client, bot: BotPM):
    await client.connect()
    phone = await asyncio.wait_for(
        bot.ask(
            "<b>Phone authorization</b>\n"
            "<blockquote>Enter the phone number in international format.</blockquote>",
            "Enter phone",
            "📝",
        ),
        timeout=TOTAL_TIMEOUT,
    )
    sent = await client.send_code_request(phone)
    password_required = False
    for _ in range(3):
        code = await asyncio.wait_for(
            bot.ask(
                "<b>Telegram login code</b>\n"
                "<blockquote>Enter the received login code.</blockquote>",
                "Enter code",
                "📝",
            ),
            timeout=TOTAL_TIMEOUT,
        )
        code = code.replace(" ", "").replace("-", "")
        try:
            await client.sign_in(
                phone=phone,
                code=code,
                phone_code_hash=sent.phone_code_hash,
            )
            return await client.get_me()
        except SessionPasswordNeededError:
            password_required = True
            break
        except Exception as error:
            await bot.send(
                "<b>Login code error</b>\n"
                f"<blockquote>{html.escape(str(error))}</blockquote>"
            )
    if not password_required:
        return None
    for _ in range(3):
        password = await asyncio.wait_for(
            bot.ask(
                "<b>Two-factor authentication</b>\n"
                "<blockquote>Enter the 2FA password.</blockquote>",
                "Enter password",
                "🔐",
            ),
            timeout=TOTAL_TIMEOUT,
        )
        try:
            await client.sign_in(password=password)
            return await client.get_me()
        except Exception as error:
            await bot.send(
                "<b>Password error</b>\n"
                f"<blockquote>{html.escape(str(error))}</blockquote>"
            )
    return None


async def send_qr_recovery(api_id: int, api_hash: str) -> bool:
    token = feroku_main.get_config_key("bot_token")
    owner_id = feroku_main.get_config_key("owner_id")
    if not token or not owner_id:
        logging.error("Recovery requires bot_token and owner_id in config.json")
        return False
    owner_id = int(owner_id)
    bot = BotPM(
        api_id,
        api_hash,
        token,
        SQLiteSession(_bot_session_path(owner_id, token)),
    )
    try:
        await bot.start()
        await bot.bind_owner(
            owner_id,
            feroku_main.get_config_key("owner_access_hash"),
        )
        if bot.owner_access_hash:
            feroku_main.save_config_key(
                "owner_access_hash",
                bot.owner_access_hash,
            )
        while True:
            action = await bot.choose_recovery()
            if action == "nuke":
                if await bot.confirm_nuke() != "confirm":
                    continue
                await bot.send(
                    "<b>Removing Feroku</b>\n"
                    "<blockquote>Stopping the service.</blockquote>"
                )
                await bot.close()
                await _run_nuke()
                return False

            client = TelegramClient(
                MemorySession(), api_id, api_hash, connection_retries=None
            )
            try:
                method = await bot.choose_auth()
                user = (
                    await _phone_login(client, bot)
                    if method == "phone"
                    else await _qr_login(client, bot)
                )
                if user is None:
                    await bot.send(
                        "<b>Login timed out or failed</b>\n"
                        "<blockquote>Choose what to do next.</blockquote>"
                    )
                    continue
                if user.id != owner_id:
                    await bot.send(
                        "<b>Account mismatch</b>\n"
                        "<blockquote>The authorized account does not match the "
                        "configured owner. Choose what to do next.</blockquote>"
                    )
                    continue
                await _delete_inline_messages(client, bot)
                await _save_session(client, user)
                await bot.clear_flow_messages()
                await bot.send(
                    "<blockquote><b>The session was restored. "
                    "Restarting.</b></blockquote>",
                    track=False,
                )
                return True
            except asyncio.TimeoutError:
                await bot.send(
                    "<b>Login timed out</b>\n"
                    "<blockquote>Choose what to do next.</blockquote>"
                )
            except Exception as error:
                logger.exception("Recovery login failed")
                await bot.send(
                    "<b>Login failed</b>\n"
                    f"<blockquote>{html.escape(str(error))}</blockquote>"
                )
            finally:
                await client.disconnect()
    except Exception:
        logger.exception("Recovery failed")
        return False
    finally:
        await bot.close()


async def run_bot_setup() -> bool | str:
    api_id = int(feroku_main.get_config_key("api_id"))
    api_hash = feroku_main.get_config_key("api_hash")
    token = feroku_main.get_config_key("bot_token")
    if not token:
        logging.error("Bot token is missing")
        return False
    pending = bool(feroku_main.get_config_key("setup_pending"))
    owner_id = feroku_main.get_config_key("owner_id")
    bot = BotPM(
        api_id,
        api_hash,
        token,
        SQLiteSession(_bot_session_path(int(owner_id), token))
        if pending and owner_id
        else None,
    )
    client = TelegramClient(
        MemorySession(), api_id, api_hash, connection_retries=None
    )
    try:
        me = await bot.start()
        if not pending or not owner_id:
            print(f"Open @{me.username} and send /start to get your Telegram ID.")
            bot.start_echo()
            owner_id = int(
                (await asyncio.to_thread(input, "Enter your Telegram ID: ")).strip()
            )
            bot.stop_echo()
            bot.owner_id = owner_id
            if owner_id in bot._seen_starts:
                bot.chat_id, bot.owner_access_hash = bot._seen_starts[owner_id]
            feroku_main.save_config_key("owner_id", owner_id)
            if bot.owner_access_hash:
                feroku_main.save_config_key(
                    "owner_access_hash",
                    bot.owner_access_hash,
                )
            feroku_main.save_config_key("setup_pending", True)
            bot.save_session(_bot_session_path(owner_id, token))
            return "handoff"

        owner_id = int(owner_id)
        await bot.bind_owner(
            owner_id,
            feroku_main.get_config_key("owner_access_hash"),
        )
        if bot.owner_access_hash:
            feroku_main.save_config_key(
                "owner_access_hash",
                bot.owner_access_hash,
            )
        method = await bot.choose_auth()
        user = (
            await _phone_login(client, bot)
            if method == "phone"
            else await _qr_login(client, bot)
        )
        if user is None:
            await bot.send(
                "<b>Login timed out or failed</b>\n"
                "<blockquote>Restart the userbot and try again.</blockquote>"
            )
            return False
        if user.id != owner_id:
            await bot.send(
                "<b>Account mismatch</b>\n"
                "<blockquote>The authorized account does not match the entered "
                "Telegram ID.</blockquote>"
            )
            return False
        await _delete_inline_messages(client, bot)
        await _save_session(client, user)
        feroku_main.save_config_key("setup_pending", False)
        await bot.clear_flow_messages()
        await bot.send(
            "<blockquote><b>The session was restored. "
            "Restarting.</b></blockquote>",
            track=False,
        )
        return True
    except Exception:
        logger.exception("Bot setup failed")
        return False
    finally:
        await client.disconnect()
        await bot.close()
