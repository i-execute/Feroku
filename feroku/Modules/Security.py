import contextlib

from telethon.tl.custom import Message
from telethon.tl.types import User
from telethon.utils import get_display_name

from .. import loader, main, utils
from ..inline.types import InlineCall


@loader.tds
class Security(loader.Module):
    strings = {
        "name": "Security",
        "title": (
            "<b>Owner access</b>\n"
            "<blockquote>Owners can execute every userbot command and access private data.</blockquote>\n"
            "<b>Main prefix:</b> <code>{prefix}</code>\n"
            "<b>Primary owner:</b> <code>1</code>\n"
            "<b>Additional owners:</b> <code>{additional}</code>"
        ),
        "detail": (
            "<b>Owner account</b>\n"
            "<blockquote><b>Account:</b> {identity}\n"
            "<b>ID:</b> <code>{user_id}</code>\n"
            "<b>Role:</b> {role}\n"
            "<b>Effective prefix:</b> <code>{prefix}</code>\n"
            "<b>Prefix source:</b> {prefix_source}</blockquote>"
        ),
        "confirm_add": (
            "<b>Grant owner access?</b>\n"
            "<blockquote><b>Account:</b> {identity}\n"
            "<b>ID:</b> <code>{user_id}</code>\n"
            "<b>Prefix:</b> <code>{prefix}</code>\n"
            "This account will receive unrestricted access to commands and private data.</blockquote>"
        ),
        "confirm_remove": (
            "<b>Remove owner access?</b>\n"
            "<blockquote><b>Account:</b> {identity}\n"
            "<b>ID:</b> <code>{user_id}</code>\n"
            "Owner access and the personal command prefix will be removed.</blockquote>"
        ),
        "invalid_user": (
            "<b>User not found</b>\n"
            "<blockquote>Reply to a user or enter a Telegram ID or username.</blockquote>"
        ),
        "invalid_bot": (
            "<b>Unsupported account</b>\n"
            "<blockquote>Bots and deleted accounts cannot receive owner access.</blockquote>"
        ),
        "primary_protected": (
            "<b>Primary owner</b>\n"
            "<blockquote>The primary owner cannot be removed.</blockquote>"
        ),
        "not_owner": (
            "<b>Owner access is not enabled</b>\n"
            "<blockquote>{identity} is not an owner.</blockquote>"
        ),
        "prefix_invalid": (
            "<b>Invalid prefix</b>\n"
            "<blockquote>The prefix must contain exactly one non-space character.</blockquote>"
        ),
        "added": "Owner access granted",
        "removed": "Owner access removed",
        "prefix_updated": (
            "<b>Command prefix updated</b>\n"
            "<blockquote><b>Account:</b> {identity}\n"
            "<b>Current prefix:</b> <code>{prefix}</code></blockquote>"
        ),
        "prefix_reset": "Personal prefix removed",
        "main_prefix_reset": "Main prefix restored",
        "primary": "Primary owner",
        "additional": "Additional owner",
        "main": "Main prefix",
        "personal": "Personal prefix",
        "inherited": "Inherited from the main prefix",
        "add": "Add owner",
        "remove": "Remove owner",
        "set_prefix": "Set prefix",
        "set_main_prefix": "Set main prefix",
        "reset_prefix": "Reset prefix",
        "use_main_prefix": "Use main prefix",
        "grant": "Grant access",
        "cancel": "Cancel",
        "confirm_remove_button": "Remove access",
        "back": "Back",
        "close": "Close",
        "previous": "Previous",
        "next": "Next",
        "input_user": "Enter Telegram ID or username",
        "input_prefix": "Enter one-symbol prefix",
        "loading": "<b>Opening owner access management</b>",
        "unavailable": "Unavailable account",
        "_cmd_doc_owner": "[add|remove] [user] - Manage owner access and personal prefixes",
        "_cls_doc": "Manage owner access and personal command prefixes",
    }

    def _owner_ids(self) -> list[int]:
        values = [self.tg_id, *self._client.dispatcher.security.owner]
        return list(dict.fromkeys(value for value in values if isinstance(value, int)))

    def _main_prefix(self) -> str:
        return utils.normalize_prefix(
            self._db.get(main.__name__, "command_prefix", ".")
        )

    def _prefixes(self) -> dict:
        prefixes = self._db.get(main.__name__, "command_prefixes", {})
        return dict(prefixes) if isinstance(prefixes, dict) else {}

    def _custom_prefix(self, user_id: int) -> str | None:
        prefix = self._prefixes().get(str(user_id))
        if isinstance(prefix, str) and len(prefix) == 1 and not prefix.isspace():
            return prefix
        return None

    def _effective_prefix(self, user_id: int) -> str:
        if user_id == self.tg_id:
            return self._main_prefix()
        return self._custom_prefix(user_id) or self._main_prefix()

    @staticmethod
    def _valid_prefix(prefix: str) -> bool:
        return isinstance(prefix, str) and len(prefix) == 1 and not prefix.isspace()

    async def _get_user(self, user_id: int) -> User | None:
        with contextlib.suppress(Exception):
            user = await self._client.get_entity(user_id, exp=0)
            if isinstance(user, User):
                return user
        return None

    async def _resolve(self, value: str) -> User | None:
        value = value.strip().removeprefix("@")
        if not value:
            return None
        entity = int(value) if value.lstrip("-").isdigit() else value
        with contextlib.suppress(Exception):
            user = await self._client.get_entity(entity, exp=0)
            if isinstance(user, User):
                return user
        return None

    async def _resolve_message_target(
        self,
        message: Message,
        value: str = "",
    ) -> User | None:
        if value.strip():
            return await self._resolve(value)
        reply = None
        with contextlib.suppress(Exception):
            reply = await message.get_reply_message()
        if reply is None and getattr(message, "reply_to_msg_id", None):
            with contextlib.suppress(Exception):
                reply = await self._client.get_messages(
                    message.peer_id,
                    ids=message.reply_to_msg_id,
                )
        if reply is None:
            return None
        sender_id = getattr(reply, "sender_id", None)
        if sender_id:
            with contextlib.suppress(Exception):
                user = await self._client.get_entity(sender_id, exp=0)
                if isinstance(user, User):
                    return user
        with contextlib.suppress(Exception):
            user = await reply.get_sender()
            if isinstance(user, User):
                return user
        return None

    def _identity(self, user: User | None, user_id: int) -> str:
        if user is None:
            return f"{self.strings['unavailable']} <code>{user_id}</code>"
        name = utils.escape_html(get_display_name(user) or str(user.id))
        return f'<a href="{utils.get_entity_url(user)}">{name}</a>'

    def _button_name(self, user: User | None, user_id: int) -> str:
        name = (
            get_display_name(user)
            if user is not None and get_display_name(user)
            else f"ID {user_id}"
        )
        name = str(name).replace("\n", " ")[:32]
        role = self.strings["primary"] if user_id == self.tg_id else self.strings["additional"]
        return f"{role}: {name} [{self._effective_prefix(user_id)}]"

    async def _open(self, message: Message, callback, *args):
        form = await self.inline.form(
            self.strings["loading"],
            message=message,
            reply_markup=[
                [
                    {
                        "text": self.strings["close"],
                        "action": "close",
                        "style": "danger",
                    }
                ]
            ],
        )
        if form:
            await callback(form, *args)

    async def _show(self, call: InlineCall, page: int = 0):
        owner_ids = self._owner_ids()
        page_size = 7
        pages = max(1, (len(owner_ids) + page_size - 1) // page_size)
        page = max(0, min(page, pages - 1))
        rows = []
        for user_id in owner_ids[page * page_size : (page + 1) * page_size]:
            user = await self._get_user(user_id)
            rows.append(
                [
                    {
                        "text": self._button_name(user, user_id),
                        "callback": self._detail,
                        "args": (user_id, page),
                        "style": "primary",
                    }
                ]
            )
        navigation = []
        if page > 0:
            navigation.append(
                {
                    "text": self.strings["previous"],
                    "callback": self._show,
                    "args": (page - 1,),
                    "style": "primary",
                }
            )
        if page < pages - 1:
            navigation.append(
                {
                    "text": self.strings["next"],
                    "callback": self._show,
                    "args": (page + 1,),
                    "style": "primary",
                }
            )
        if navigation:
            rows.append(navigation)
        rows.extend(
            [
                [
                    {
                        "text": self.strings["set_main_prefix"],
                        "input": self.strings["input_prefix"],
                        "handler": self._prefix_input,
                        "args": (self.tg_id, page, False),
                        "style": "primary",
                    }
                ],
                [
                    {
                        "text": self.strings["add"],
                        "input": self.strings["input_user"],
                        "handler": self._add_input,
                        "args": (page,),
                        "style": "success",
                    }
                ],
                [
                    {
                        "text": self.strings["close"],
                        "action": "close",
                        "style": "danger",
                    }
                ],
            ]
        )
        await call.edit(
            self.strings["title"].format(
                prefix=utils.escape_html(self._main_prefix()),
                additional=max(0, len(owner_ids) - 1),
            ),
            reply_markup=rows,
        )

    async def _detail(self, call: InlineCall, user_id: int, page: int = 0):
        if user_id not in self._owner_ids():
            await self._show(call, page)
            return
        user = await self._get_user(user_id)
        custom_prefix = self._custom_prefix(user_id)
        if user_id == self.tg_id:
            role = self.strings["primary"]
            source = self.strings["main"]
        elif custom_prefix:
            role = self.strings["additional"]
            source = self.strings["personal"]
        else:
            role = self.strings["additional"]
            source = self.strings["inherited"]
        rows = [
            [
                {
                    "text": (
                        self.strings["set_main_prefix"]
                        if user_id == self.tg_id
                        else self.strings["set_prefix"]
                    ),
                    "input": self.strings["input_prefix"],
                    "handler": self._prefix_input,
                    "args": (user_id, page, False),
                    "style": "primary",
                }
            ]
        ]
        if custom_prefix or user_id == self.tg_id and self._main_prefix() != ".":
            rows.append(
                [
                    {
                        "text": self.strings["reset_prefix"],
                        "callback": self._reset_prefix,
                        "args": (user_id, page),
                        "style": "danger",
                    }
                ]
            )
        if user_id != self.tg_id:
            rows.append(
                [
                    {
                        "text": self.strings["remove"],
                        "callback": self._remove_confirm,
                        "args": (user_id, page),
                        "style": "danger",
                    }
                ]
            )
        rows.append(
            [
                {
                    "text": self.strings["back"],
                    "callback": self._show,
                    "args": (page,),
                    "style": "primary",
                },
                {
                    "text": self.strings["close"],
                    "action": "close",
                    "style": "danger",
                },
            ]
        )
        await call.edit(
            self.strings["detail"].format(
                identity=self._identity(user, user_id),
                user_id=user_id,
                role=role,
                prefix=utils.escape_html(self._effective_prefix(user_id)),
                prefix_source=source,
            ),
            reply_markup=rows,
        )

    async def _add_input(self, call: InlineCall, query: str, page: int = 0):
        user = await self._resolve(query)
        if user is None:
            await call.edit(
                self.strings["invalid_user"],
                reply_markup=[
                    [
                        {
                            "text": self.strings["back"],
                            "callback": self._show,
                            "args": (page,),
                            "style": "primary",
                        }
                    ]
                ],
            )
            return
        if user.id in self._owner_ids():
            await self._detail(call, user.id, page)
            return
        await self._add_confirm(call, user.id, page)

    async def _add_confirm(
        self,
        call: InlineCall,
        user_id: int,
        page: int = 0,
        prefix: str | None = None,
    ):
        if user_id in self._owner_ids():
            await self._detail(call, user_id, page)
            return
        user = await self._get_user(user_id)
        if user is None:
            await call.edit(
                self.strings["invalid_user"],
                reply_markup=[
                    [
                        {
                            "text": self.strings["back"],
                            "callback": self._show,
                            "args": (page,),
                            "style": "primary",
                        }
                    ]
                ],
            )
            return
        if getattr(user, "bot", False) or getattr(user, "deleted", False):
            await call.edit(
                self.strings["invalid_bot"],
                reply_markup=[
                    [
                        {
                            "text": self.strings["back"],
                            "callback": self._show,
                            "args": (page,),
                            "style": "primary",
                        }
                    ]
                ],
            )
            return
        selected_prefix = prefix or self._main_prefix()
        rows = [
            [
                {
                    "text": self.strings["set_prefix"],
                    "input": self.strings["input_prefix"],
                    "handler": self._prefix_input,
                    "args": (user_id, page, True),
                    "style": "primary",
                }
            ]
        ]
        if prefix is not None:
            rows.append(
                [
                    {
                        "text": self.strings["use_main_prefix"],
                        "callback": self._add_confirm,
                        "args": (user_id, page, None),
                        "style": "primary",
                    }
                ]
            )
        rows.append(
            [
                {
                    "text": self.strings["grant"],
                    "callback": self._add,
                    "args": (user_id, page, prefix),
                    "style": "success",
                },
                {
                    "text": self.strings["cancel"],
                    "action": "close",
                    "style": "danger",
                },
            ]
        )
        await call.edit(
            self.strings["confirm_add"].format(
                identity=self._identity(user, user_id),
                user_id=user_id,
                prefix=utils.escape_html(selected_prefix),
            ),
            reply_markup=rows,
        )

    async def _add(
        self,
        call: InlineCall,
        user_id: int,
        page: int = 0,
        prefix: str | None = None,
    ):
        if user_id == self.tg_id:
            await call.answer(self.strings["primary_protected"])
            await self._detail(call, user_id, page)
            return
        user = await self._get_user(user_id)
        if user is None or getattr(user, "bot", False) or getattr(user, "deleted", False):
            await call.answer(self.strings["invalid_user"])
            await self._show(call, page)
            return
        owners = self._client.dispatcher.security.owner
        if user_id not in owners:
            owners.append(user_id)
        if prefix is not None and self._valid_prefix(prefix):
            prefixes = self._prefixes()
            prefixes[str(user_id)] = prefix
            self._db.set(main.__name__, "command_prefixes", prefixes)
        self._client.dispatcher.security._reload_rights(force=True)
        await call.answer(self.strings["added"])
        await self._detail(call, user_id, page)

    async def _remove_confirm(
        self,
        call: InlineCall,
        user_id: int,
        page: int = 0,
    ):
        if user_id == self.tg_id:
            await call.edit(
                self.strings["primary_protected"],
                reply_markup=[
                    [
                        {
                            "text": self.strings["back"],
                            "callback": self._detail,
                            "args": (user_id, page),
                            "style": "primary",
                        }
                    ]
                ],
            )
            return
        if user_id not in self._owner_ids():
            await self._show(call, page)
            return
        user = await self._get_user(user_id)
        await call.edit(
            self.strings["confirm_remove"].format(
                identity=self._identity(user, user_id),
                user_id=user_id,
            ),
            reply_markup=[
                [
                    {
                        "text": self.strings["confirm_remove_button"],
                        "callback": self._remove,
                        "args": (user_id, page),
                        "style": "danger",
                    },
                    {
                        "text": self.strings["back"],
                        "callback": self._detail,
                        "args": (user_id, page),
                        "style": "primary",
                    },
                ]
            ],
        )

    async def _remove(self, call: InlineCall, user_id: int, page: int = 0):
        if user_id == self.tg_id:
            await call.answer(self.strings["primary_protected"])
            await self._detail(call, user_id, page)
            return
        owners = self._client.dispatcher.security.owner
        while user_id in owners:
            owners.remove(user_id)
        prefixes = self._prefixes()
        if str(user_id) in prefixes:
            del prefixes[str(user_id)]
            self._db.set(main.__name__, "command_prefixes", prefixes)
        self._client.dispatcher.security._reload_rights(force=True)
        await call.answer(self.strings["removed"])
        await self._show(call, page)

    async def _prefix_input(
        self,
        call: InlineCall,
        query: str,
        user_id: int,
        page: int = 0,
        adding: bool = False,
    ):
        prefix = query.strip()
        if not self._valid_prefix(prefix):
            callback = self._add_confirm if adding else self._detail
            await call.edit(
                self.strings["prefix_invalid"],
                reply_markup=[
                    [
                        {
                            "text": self.strings["back"],
                            "callback": callback,
                            "args": (user_id, page),
                            "style": "primary",
                        }
                    ]
                ],
            )
            return
        if adding:
            await self._add_confirm(call, user_id, page, prefix)
            return
        if user_id not in self._owner_ids():
            await self._show(call, page)
            return
        self._set_prefix(user_id, prefix)
        user = await self._get_user(user_id)
        await call.edit(
            self.strings["prefix_updated"].format(
                identity=self._identity(user, user_id),
                prefix=utils.escape_html(self._effective_prefix(user_id)),
            ),
            reply_markup=[
                [
                    {
                        "text": self.strings["back"],
                        "callback": self._detail,
                        "args": (user_id, page),
                        "style": "primary",
                    }
                ]
            ],
        )

    def _set_prefix(self, user_id: int, prefix: str):
        if user_id == self.tg_id:
            self._db.set(main.__name__, "command_prefix", prefix)
            self._client.command_prefix = prefix
            return
        prefixes = self._prefixes()
        prefixes[str(user_id)] = prefix
        self._db.set(main.__name__, "command_prefixes", prefixes)
        self._client.dispatcher.security._reload_rights(force=True)

    async def _reset_prefix(
        self,
        call: InlineCall,
        user_id: int,
        page: int = 0,
    ):
        if user_id == self.tg_id:
            self._db.set(main.__name__, "command_prefix", ".")
            self._client.command_prefix = "."
            await call.answer(self.strings["main_prefix_reset"])
        else:
            prefixes = self._prefixes()
            if str(user_id) in prefixes:
                del prefixes[str(user_id)]
                self._db.set(main.__name__, "command_prefixes", prefixes)
            self._client.dispatcher.security._reload_rights(force=True)
            await call.answer(self.strings["prefix_reset"])
        await self._detail(call, user_id, page)

    @loader.command()
    async def owner(self, message: Message):
        args = utils.get_args(message)
        if not isinstance(args, list):
            args = []
        actions = {
            "add": "add",
            "grant": "add",
            "remove": "remove",
            "rm": "remove",
            "delete": "remove",
            "del": "remove",
            "list": "list",
            "manage": "list",
        }
        action = actions.get(args[0].lower()) if args else None
        rest = args[1:] if action else args
        if action == "list":
            await self._open(message, self._show)
            return
        if not action and not rest:
            has_reply = bool(
                getattr(message, "is_reply", False)
                or getattr(message, "reply_to_msg_id", None)
            )
            target = await self._resolve_message_target(message)
            if target is None:
                if has_reply:
                    await utils.answer(message, self.strings["invalid_user"])
                else:
                    await self._open(message, self._show)
                return
            if target.id == self.tg_id:
                await self._open(message, self._detail, target.id)
            elif target.id in self._owner_ids():
                await self._open(message, self._remove_confirm, target.id)
            else:
                await self._open(message, self._add_confirm, target.id)
            return
        target = await self._resolve_message_target(message, " ".join(rest))
        if target is None:
            await utils.answer(message, self.strings["invalid_user"])
            return
        if action == "add":
            if target.id in self._owner_ids():
                await self._open(message, self._detail, target.id)
            else:
                await self._open(message, self._add_confirm, target.id)
            return
        if action == "remove":
            if target.id == self.tg_id:
                await utils.answer(message, self.strings["primary_protected"])
            elif target.id not in self._owner_ids():
                await utils.answer(
                    message,
                    self.strings["not_owner"].format(
                        identity=self._identity(target, target.id)
                    ),
                )
            else:
                await self._open(message, self._remove_confirm, target.id)
            return
        if target.id in self._owner_ids():
            await self._open(message, self._detail, target.id)
        else:
            await self._open(message, self._add_confirm, target.id)
