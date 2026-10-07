# CopyLeft 2026 github.com/i-execute // i_execute.t.me
# Licensed under AGPLv3.

# (c) Dan Gazizullin, 2021-2023. This file is part of the Hikka Userbot: github.com/hikariatama/Hikka

import logging
import time
import typing

from .. import utils
from .types import InlineUnit

if typing.TYPE_CHECKING:
    from ..inline.core import InlineManager

logger = logging.getLogger(__name__)

class QueryGallery(InlineUnit):
    async def query_gallery(
        self: "InlineManager",
        query,
        items: list[dict[str, typing.Any]],
        *,
        force_me: bool = False,
        disable_security: bool = False,
        always_allow: list[int] | None = None,
    ) -> bool:
        if not isinstance(force_me, bool):
            logger.error(
                "Invalid type for `force_me`. Expected `bool`, got %s",
                type(force_me),
            )
            return False

        if not isinstance(disable_security, bool):
            logger.error(
                "Invalid type for `disable_security`. Expected `bool`, got %s",
                type(disable_security),
            )
            return False

        if always_allow and not isinstance(always_allow, list):
            logger.error(
                "Invalid type for `always_allow`. Expected `list`, got %s",
                type(always_allow),
            )
            return False

        if not always_allow:
            always_allow = []

        if (
            not isinstance(items, list)
            or not all(isinstance(i, dict) for i in items)
            or not all(
                "title" in i
                and "description" in i
                and "next_handler" in i
                and (
                    callable(i["next_handler"])
                    or isinstance(i["next_handler"], list)
                )
                and isinstance(i["title"], str)
                and isinstance(i["description"], str)
                for i in items
            )
        ):
            logger.error("Invalid `items` specified in query gallery")
            return False

        result = []
        for i in items:
            if "thumb_handler" not in i:
                photo_url = await self._call_photo(i["next_handler"])
                if not photo_url:
                    return False

                if isinstance(photo_url, list):
                    photo_url = photo_url[0]

                if not isinstance(photo_url, str):
                    logger.error(
                        "Invalid result from `next_handler`. Expected `str`, got %s",
                        type(photo_url),
                    )
                    continue
            else:
                photo_url = await self._call_photo(i["thumb_handler"])
                if not photo_url:
                    return False

                if isinstance(photo_url, list):
                    photo_url = photo_url[0]

                if not isinstance(photo_url, str):
                    logger.error(
                        "Invalid result from `thumb_handler`. Expected `str`, got %s",
                        type(photo_url),
                    )
                    continue

            id_ = utils.rand(16)

            self._custom_map[id_] = {
                "handler": i["next_handler"],
                "ttl": round(time.time()) + 120,
                **({"always_allow": always_allow} if always_allow else {}),
                **({"force_me": force_me} if force_me else {}),
                **({"disable_security": disable_security} if disable_security else {}),
                **({"caption": i["caption"]} if "caption" in i else {}),
            }

            result += [
                await query.builder.article(
                    title=i["title"],
                    description=i["description"],
                    text=f" <b>Opening gallery...</b>\n<i>#id: {id_}</i>",
                    parse_mode="HTML",
                    link_preview=False,
                    thumb=self._web_document(photo_url),
                    id=utils.rand(20),
                )
            ]

        await query.answer(result, cache_time=0)
        return True
