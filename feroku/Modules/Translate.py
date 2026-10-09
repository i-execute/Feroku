# CopyLeft 2026 github.com/i-execute // i_execute.t.me
# Licensed under AGPLv3.

# (c) Dan Gazizullin, 2021-2023. This file is part of the Hikka Userbot: github.com/hikariatama/Hikka

import logging

from telethon.extensions import html
from telethon.tl import functions, types
from telethon.tl.custom import Message

from .. import loader, utils

logger = logging.getLogger(__name__)


@loader.tds
class Translator(loader.Module):
    strings = {
        "name": "Translator",
        "no_args": "<b>Translation failed</b>\n<blockquote>Provide text or reply to a message.</blockquote>",
        "error": "<b>Translation failed</b>\n<blockquote>Telegram could not translate this text.</blockquote>",
        "language": "en",
        "translated_text": "<b>Translation</b>\n<blockquote>{tr_text}</blockquote>",
        "_cmd_doc_tr": "[language] [text] - Translate text through Telegram",
        "_cls_doc": "Translate text through Telegram",
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "only_text",
                False,
                "Send only the translated text",
                validator=loader.validators.Boolean(),
            )
        )

    @loader.command()
    async def tr(self, message: Message):
        args = utils.get_args_raw(message.raw_text)
        if not args:
            text = None
            language = self.strings["language"]
        else:
            first, *remaining = args.split(maxsplit=1)
            if len(first) == 2:
                language = first
                text = remaining[0] if remaining else None
            else:
                language = self.strings["language"]
                text = args

        reply = None
        if not text:
            reply = await message.get_reply_message()
            if not reply or not reply.raw_text:
                await utils.answer(message, self.strings["no_args"])
                return
            text = reply.raw_text
            entities = reply.entities
            source = reply
        else:
            entities = []
            source = message

        try:
            if reply:
                request = functions.messages.TranslateTextRequest(
                    peer=await self._client.get_input_entity(source.peer_id),
                    id=[source.id],
                    to_lang=language,
                )
            else:
                request = functions.messages.TranslateTextRequest(
                    text=[types.TextWithEntities(text=text, entities=entities)],
                    to_lang=language,
                )
            result = await self._client(request)
            if not result.result:
                raise ValueError("Telegram returned an empty translation")
            translated = html.unparse(
                result.result[0].text,
                result.result[0].entities,
            )
            if self.config["only_text"]:
                await utils.answer(message, translated)
            else:
                await utils.answer(
                    message,
                    self.strings["translated_text"].format(tr_text=translated),
                )
        except Exception:
            logger.exception("Unable to translate text")
            await utils.answer(message, self.strings["error"])
