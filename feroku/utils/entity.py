# CopyLeft 2026 github.com/i-execute // i_execute.t.me
# Licensed under AGPLv3.

# (c) Dan Gazizullin, 2021-2023. This file is part of the Hikka Userbot: github.com/hikariatama/Hikka

import asyncio
import inspect
import ipaddress
import logging
import re
import string
import time
import typing
from urllib.parse import urlparse

import emoji
import telethon
from telethon import hints
from telethon.tl.custom.message import Message
from telethon.tl.functions.account import UpdateNotifySettingsRequest
from telethon.tl.functions.channels import CreateChannelRequest, EditPhotoRequest
from telethon.tl.functions.messages import (
    CreateForumTopicRequest,
    EditForumTopicRequest,
    GetDialogFiltersRequest,
    GetForumTopicsByIDRequest,
    GetForumTopicsRequest,
    SetHistoryTTLRequest,
    UpdateDialogFilterRequest,
)
from telethon.tl.types import (
    Channel,
    ForumTopic,
    ForumTopicDeleted,
    InputPeerNotifySettings,
    MessageEntityBankCard,
    MessageEntityBlockquote,
    MessageEntityBold,
    MessageEntityBotCommand,
    MessageEntityCashtag,
    MessageEntityCode,
    MessageEntityEmail,
    MessageEntityHashtag,
    MessageEntityItalic,
    MessageEntityMention,
    MessageEntityMentionName,
    MessageEntityPhone,
    MessageEntityPre,
    MessageEntitySpoiler,
    MessageEntityStrike,
    MessageEntityTextUrl,
    MessageEntityUnderline,
    MessageEntityUnknown,
    MessageEntityUrl,
    PeerChannel,
    PeerChat,
    PeerUser,
    UpdateNewChannelMessage,
    User,
)

from .._compat import resolve_asset_name
from .._internal import fw_protect
from ..tl_cache import CustomTelegramClient
from ..types import Module
from pathlib import Path

from .other import invite_inline_bot

FormattingEntity = typing.Union[
    MessageEntityUnknown,
    MessageEntityMention,
    MessageEntityHashtag,
    MessageEntityBotCommand,
    MessageEntityUrl,
    MessageEntityEmail,
    MessageEntityBold,
    MessageEntityItalic,
    MessageEntityCode,
    MessageEntityPre,
    MessageEntityTextUrl,
    MessageEntityMentionName,
    MessageEntityPhone,
    MessageEntityCashtag,
    MessageEntityUnderline,
    MessageEntityStrike,
    MessageEntityBlockquote,
    MessageEntityBankCard,
    MessageEntitySpoiler,
]

parser = telethon.utils.sanitize_parse_mode("html")
logger = logging.getLogger(__name__)

TAG_RE = re.compile(r"</?([a-zA-Z][a-zA-Z0-9\-]*)(?:\s[^<>]*)?>")

TELEGRAM_HTML_TAGS = {
    "strong",
    "b",
    "em",
    "i",
    "tg-spoiler",
    "u",
    "del",
    "s",
    "blockquote",
    "code",
    "pre",
    "a",
}

def get_lang_flag(countrycode: str) -> str:
    if (
        len(
            code := [
                c
                for c in countrycode.lower()
                if c in string.ascii_letters + string.digits
            ]
        )
        == 2
    ):
        return "".join([chr(ord(c.upper()) + (ord("") - ord("A"))) for c in code])

    return countrycode

def get_entity_url(
    entity: User | Channel,
    openmessage: bool = False,
) -> str:
    return (
        (
            f"tg://openmessage?id={entity.id}"
            if openmessage
            else f"tg://user?id={entity.id}"
        )
        if isinstance(entity, User)
        else (
            f"tg://resolve?domain={entity.username}"
            if getattr(entity, "username", None)
            else ""
        )
    )

def get_link(user: User | Channel, /) -> str:
    return get_entity_url(user)

def remove_emoji(text: str) -> str:
    allchars = [str for str in text]
    emoji_list = [c for c in allchars if c in emoji.EMOJI_DATA]
    clean_text = "".join([str for str in text if not any(i in str for i in emoji_list)])
    return clean_text

def remove_html(text: str, escape: bool = False, keep_emojis: bool = False) -> str:
    return (escape_html if escape else str)(
        re.sub(
            (
                r"(<\/?a.*?>|<\/?b>|<\/?i>|<\/?u>|<\/?strong>|<\/?em>|<\/?code.*?>|<\/?strike>|<\/?del>|<\/?pre.*?>|<\/?blockquote.*?>)"
                if keep_emojis
                else r"(<\/?a.*?>|<\/?b>|<\/?i>|<\/?u>|<\/?strong>|<\/?em>|<\/?code.*?>|<\/?strike>|<\/?del>|<\/?pre.*?>|<\/?emoji.*?>|<\/?blockquote.*?>)"
            ),
            "",
            text,
        )
    )

def normalize_git_url(url: str) -> str:

    if not url:
        return ""
    url = url.strip().rstrip("/")
    if "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    if "raw.githubusercontent.com" in (parsed.netloc or ""):
        return url
    if "github.com" not in (parsed.netloc or ""):
        return url
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) == 2:
        parts.append("main")
    if len(parts) < 3:
        return url
    owner, repo, ref, *rest = parts
    if ref in ("tree", "blob", "raw"):
        branch, *rest = rest
    else:
        branch = ref
    path = "/".join(rest)
    base = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}"
    return f"{base}/{path}" if path else base


def check_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc:
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        if hostname.replace(".", "").replace(":", "").isdigit():
            return False
        try:
            ipaddress.ip_address(hostname.strip("[]"))
            return False
        except ValueError:
            pass
        return True
    except Exception:
        return False

async def asset_channel(
    client: CustomTelegramClient,
    title: str,
    description: str,
    *,
    channel: bool = False,
    silent: bool = False,
    archive: bool = False,
    invite_bot: bool = False,
    avatar: str | None = None,
    ttl: int | None = None,
    forum: bool = False,
    hide_general: bool = False,
    _folder: str | None = None,
    force_new: bool = False,
) -> tuple[Channel, bool]:
    if not hasattr(client, "_channels_cache"):
        client._channels_cache = {}

    if (
        not force_new
        and title in client._channels_cache
        and client._channels_cache[title]["exp"] > time.time()
    ):
        return client._channels_cache[title]["peer"], False

    if not force_new:
        async for d in client.iter_dialogs():
            if d.title == title:
                client._channels_cache[title] = {
                    "peer": d.entity,
                    "exp": int(time.time()),
                }
                if invite_bot:
                    if all(
                        participant.id != client.loader.inline.bot_id
                        for participant in await client.get_participants(
                            d.entity, limit=100
                        )
                    ):
                        await fw_protect()
                        await invite_inline_bot(client, d.entity)

                return d.entity, False

    await fw_protect()

    peer = (
        await client(
            CreateChannelRequest(
                title,
                description,
                broadcast=channel,
                megagroup=not channel,
                forum=forum,
            )
        )
    ).chats[0]

    if invite_bot:
        await fw_protect()
        await invite_inline_bot(client, peer)

    if silent:
        await fw_protect()
        await dnd(client, peer, archive)
    elif archive:
        await fw_protect()
        await client.edit_folder(peer, 1)

    if avatar:
        await fw_protect()
        await set_avatar(client, peer, avatar)

    if hide_general and forum:
        await fw_protect()
        await client(EditForumTopicRequest(peer=peer, topic_id=1, hidden=True))

    if ttl:
        await fw_protect()
        await client(SetHistoryTTLRequest(peer=peer, period=ttl))

    if _folder:
        folders = (await client(GetDialogFiltersRequest())).filters

        try:
            folder = next(
                folder
                for folder in folders
                if not isinstance(folder, telethon.tl.types.DialogFilterDefault)
                and folder.title.text.lower() == _folder.lower()
            )
        except Exception:
            folder = None

        if folder and not any(
            peer.id == getattr(folder_peer, "channel_id", None)
            for folder_peer in folder.include_peers
        ):
            folder.include_peers.append(await client.get_input_entity(peer))

            await client(
                UpdateDialogFilterRequest(
                    folder.id,
                    folder,
                )
            )

    client._channels_cache[title] = {"peer": peer, "exp": int(time.time())}
    return peer, True

if typing.TYPE_CHECKING:
    from ..database import Database

async def asset_forum_topic(
    client: CustomTelegramClient,
    db: "Database",
    peer: hints.Entity,
    title: str,
    description: str | None = None,
    icon_emoji_id: int | None = None,
    invite_bot: bool = False,
) -> ForumTopic:
    entity = await client.get_entity(peer)

    if not isinstance(entity, Channel):
        raise TypeError(
            f"Expected entity to be 'Channel', but got '{type(entity).__name__}'"
        )

    async def create_topic() -> ForumTopic:
        result = await client(
            CreateForumTopicRequest(
                peer=entity,
                title=title,
                icon_emoji_id=(icon_emoji_id if client.feroku_me.premium else None),
            )
        )

        await fw_protect()

        await client.send_message(
            entity=entity,
            message=(
                description
                if description
                else f"<b>Content related to <i>'{title}'</i> will be here</b>"
            ),
            reply_to=result.updates[0].id,
        )

        await fw_protect()

        result = await client(
            GetForumTopicsByIDRequest(peer=entity, topics=[result.updates[0].id])
        )

        return result.topics[0]

    forums_cache = db.pointer("feroku.forums", "forums_cache", {})

    async def _search_topic(topic_title: str) -> int | None:
        result = await client(
            GetForumTopicsRequest(
                peer=entity,
                offset_date=None,
                offset_id=0,
                offset_topic=0,
                limit=100,
            )
        )
        await fw_protect()
        for found_topic in result.topics:
            if isinstance(found_topic, ForumTopicDeleted):
                continue
            if found_topic.title == topic_title:
                forums_cache.setdefault(entity.title, {})[topic_title] = found_topic.id
                return found_topic.id
        return None

    if topic_id := forums_cache.get(entity.title, {}).get(title) or await _search_topic(
        title
    ):
        await fw_protect()
        new_topic = await client(
            GetForumTopicsByIDRequest(peer=entity, topics=[topic_id])
        )
        new_topic = new_topic.topics[0]

        if isinstance(new_topic, ForumTopicDeleted):
            logger.warning(
                f"Topic: '{title}' was found in the database but does not exist in the channel and will be recreated"
            )
            await fw_protect()
            new_topic = await create_topic()
            forums_cache[entity.title][title] = new_topic.id

    else:
        await fw_protect()
        new_topic = await create_topic()
        forums_cache.setdefault(entity.title, {})[title] = new_topic.id

    if invite_bot:
        await fw_protect()
        if all(
            p.id != client.loader.inline.bot_id
            for p in await client.get_participants(entity, limit=20)
        ):
            await fw_protect()
            await invite_inline_bot(client, entity)

    return new_topic

async def wait_for_content_channel(db: "Database", delay: float = 10) -> int:
    cid = db.get("feroku.forums", "channel_id", None)

    while not cid:
        logger.warning(
            "Feroku content channel not found in database. Sleeping 10 seconds..."
        )
        await asyncio.sleep(delay)
        cid = db.get("feroku.forums", "channel_id", None)

    return cid

async def get_topic_id(db: "Database", topic_name: str) -> int | None:
    try:
        forums_cache = db.get("feroku.forums", "forums_cache", {})
        return forums_cache.get("feroku-userbot", {}).get(topic_name)
    except Exception:
        return None

async def set_avatar(
    client: CustomTelegramClient,
    peer: hints.Entity,
    avatar: str,
) -> bool:
    if isinstance(avatar, str) and (Path(__file__).parent.parent.parent / avatar).is_file():
        f = (Path(__file__).parent.parent.parent / avatar).read_bytes()
    elif isinstance(avatar, bytes):
        f = avatar
    else:
        return False

    await fw_protect()
    res = await client(
        EditPhotoRequest(
            channel=peer,
            photo=await client.upload_file(f, file_name="photo.png"),
        )
    )

    await fw_protect()

    try:
        await client.delete_messages(
            peer,
            message_ids=[
                next(
                    update
                    for update in res.updates
                    if isinstance(update, UpdateNewChannelMessage)
                ).message.id
            ],
        )
    except Exception:
        pass

    return True

async def get_target(message: Message, arg_no: int = 0) -> int | None:
    from .args import get_args

    if any(
        isinstance(entity, MessageEntityMentionName)
        for entity in (message.entities or [])
    ):
        e = sorted(
            filter(lambda x: isinstance(x, MessageEntityMentionName), message.entities),
            key=lambda x: x.offset,
        )[0]
        return e.user_id

    if len(get_args(message)) > arg_no:
        user = get_args(message)[arg_no]
    elif message.is_reply:
        return (await message.get_reply_message()).sender_id
    elif hasattr(message.peer_id, "user_id"):
        user = message.peer_id.user_id
    else:
        return None

    try:
        entity = await message.client.get_entity(user)
    except ValueError:
        return None
    else:
        if isinstance(entity, User):
            return entity.id

async def get_user(message: Message) -> User | None:
    try:
        return await message.get_sender()
    except ValueError:
        logger.debug("User not in session cache. Searching...")

    if isinstance(message.peer_id, PeerUser):
        await message.client.get_dialogs()
        return await message.get_sender()

    if isinstance(message.peer_id, (PeerChannel, PeerChat)):
        async for user in message.client.iter_participants(
            message.peer_id,
            aggressive=True,
        ):
            if user.id == message.sender_id:
                return user

        logger.error("User isn't in the group where they sent the message")
        return None

    logger.error("`peer_id` is not a user, chat or channel")
    return None

def get_chat_id(message: Message) -> int:
    return telethon.utils.resolve_id(
        getattr(message, "chat_id", None)
        or getattr(getattr(message, "chat", None), "id", None)
    )[0]

def get_entity_id(entity: hints.Entity) -> int:
    return telethon.utils.get_peer_id(entity)

def escape_html(text: str, /) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def escape_non_html(text: str) -> str:
    out = []
    last = 0
    for m in TAG_RE.finditer(text):
        out.append(escape_html(text[last : m.start()]))
        out.append(
            m.group(0)
            if m.group(1).lower() in TELEGRAM_HTML_TAGS
            else escape_html(m.group(0))
        )
        last = m.end()

    out.append(escape_html(text[last:]))

    return "".join(out)

def escape_quotes(text: str, /) -> str:
    return escape_html(text).replace('"', "&quot;")

def relocate_entities(
    entities: list[FormattingEntity],
    offset: int,
    text: str | None = None,
) -> list[FormattingEntity]:
    length = len(text) if text is not None else 0

    for ent in entities.copy() if entities else ():
        ent.offset += offset
        if ent.offset < 0:
            ent.length += ent.offset
            ent.offset = 0
        if text is not None and ent.offset + ent.length > length:
            ent.length = length - ent.offset
        if ent.length <= 0:
            entities.remove(ent)

    return entities

def find_caller(
    stack: list[inspect.FrameInfo] | None = None,
) -> typing.Any:
    caller = next(
        (
            frame_info
            for frame_info in stack or inspect.stack()
            if hasattr(frame_info, "function")
            and any(
                inspect.isclass(cls_)
                and issubclass(cls_, Module)
                and cls_ is not Module
                for cls_ in frame_info.frame.f_globals.values()
            )
        ),
        None,
    )

    if not caller:
        return next(
            (
                frame_info.frame.f_locals["func"]
                for frame_info in stack or inspect.stack()
                if hasattr(frame_info, "function")
                and frame_info.function == "future_dispatcher"
                and (
                    "CommandDispatcher"
                    in getattr(getattr(frame_info, "frame", None), "f_globals", {})
                )
            ),
            None,
        )

    return next(
        (
            getattr(cls_, caller.function, None)
            for cls_ in caller.frame.f_globals.values()
            if inspect.isclass(cls_) and issubclass(cls_, Module)
        ),
        None,
    )

async def dnd(
    client: CustomTelegramClient,
    peer: hints.Entity,
    archive: bool = True,
) -> bool:
    try:
        await client(
            UpdateNotifySettingsRequest(
                peer=peer,
                settings=InputPeerNotifySettings(
                    show_previews=False,
                    silent=True,
                    mute_until=2**31 - 1,
                ),
            )
        )

        if archive:
            await fw_protect()
            await client.edit_folder(peer, 1)
    except Exception:
        logger.exception("utils.dnd error")
        return False

    return True

def get_asset_path(name: str) -> str:
    name = resolve_asset_name(name)
    return str(Path(__file__).resolve().parent.parent.parent / "Storage" / name)
