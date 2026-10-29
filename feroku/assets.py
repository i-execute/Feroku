# CopyLeft 2026 github.com/i-execute // i_execute.t.me
# Licensed under AGPLv3.

from telethon.tl import types

FEROKU_IMAGE_URL = "https://raw.githubusercontent.com/i-execute/Feroku/main/Storage/Feroku.PNG"


def feroku_image_document() -> types.InputWebDocument:
    return types.InputWebDocument(
        url=FEROKU_IMAGE_URL,
        size=0,
        mime_type="image/jpeg",
        attributes=[types.DocumentAttributeImageSize(w=128, h=128)],
    )