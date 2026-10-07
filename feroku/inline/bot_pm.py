# CopyLeft 2026 github.com/i-execute // i_execute.t.me
# Licensed under AGPLv3.

# (c) Dan Gazizullin, 2021-2023. This file is part of the Hikka Userbot: github.com/hikariatama/Hikka

import logging
import typing

from .types import InlineUnit

if typing.TYPE_CHECKING:
    from ..inline.core import InlineManager

logger = logging.getLogger(__name__)

class BotPM(InlineUnit):
    def set_fsm_state(
        self: "InlineManager",
        user: str | int,
        state: str | bool,
    ) -> bool:
        if not isinstance(user, (str, int)):
            logger.error(
                (
                    "Invalid type for `user` in `set_fsm_state`. Expected `str` or"
                    " `int`, got %s"
                ),
                type(user),
            )
            return False

        if not isinstance(state, (str, bool)):
            logger.error(
                (
                    "Invalid type for `state` in `set_fsm_state`. Expected `str` or"
                    " `bool`, got %s"
                ),
                type(state),
            )
            return False

        match True:
            case _ if state:
                self.fsm[str(user)] = state
            case _ if str(user) in self.fsm:
                del self.fsm[str(user)]

        return True

    ss = set_fsm_state

    def get_fsm_state(self: "InlineManager", user: str | int) -> bool | str:
        if not isinstance(user, (str, int)):
            logger.error(
                (
                    "Invalid type for `user` in `get_fsm_state`. Expected `str` or"
                    " `int`, got %s"
                ),
                type(user),
            )
            return False

        return self.fsm.get(str(user), False)

    gs = get_fsm_state
