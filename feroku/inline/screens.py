import asyncio
import html
import re

from .. import utils
from .types import InlineUnit

_BLOCK = r"details|summary|table|tr|th|td|blockquote|tg-button-row|img|h[1-6]|hr|pre|ul|ol|li"
_BLOCK_RE = re.compile(rf"\n*(</?(?:{_BLOCK})\b[^>]*>)\n*", re.IGNORECASE)
_PRE_RE = re.compile(r"(<pre\b[^>]*>.*?</pre>)", re.IGNORECASE | re.DOTALL)
_STYLES = {"primary", "success", "danger", "link"}
_ICONS = {
    "back": "‹",
    "close": "x",
    "copy": "copy",
    "warning": "!",
    "check": "ok",
    "on": "on",
    "off": "off",
    "add": "+",
    "remove": "x",
    "info": "i",
    "module": "module",
    "core": "core",
    "external": "external",
    "library": "library",
    "folder": "folder",
    "list": "list",
    "number": "#",
    "text": "text",
    "choice": "choice",
    "link": "link",
    "user": "user",
    "bot": "bot",
    "guest": "guest",
    "command": "command",
    "placeholder": "·",
    "page": "page",
    "help": "help",
    "settings": "settings",
    "edit": "edit",
    "reset": "reset",
    "eye": "view",
    "hide": "hide",
    "lock": "lock",
    "secret": "secret",
    "search": "search",
}


def _escape(value):
    return html.escape(str(value), quote=False)


def _attr(value):
    return html.escape(str(value), quote=True)


def _to_rich(source):
    parts = _PRE_RE.split(_BLOCK_RE.sub(r"\1", source.strip("\n")))
    return "".join(
        part if index % 2 else part.replace("\n", "<br>")
        for index, part in enumerate(parts)
    )


class Screen:
    def __init__(self, *, premium=False, translate=None):
        self.premium = premium
        self._translate = translate
        self.body = []
        self.markup = []
        self.taps = {}
        self.notice = None
        self.toast = None
        self.alert = False
        self.reply_input = None
        self._low_inputs = []
        self._low_buttons = []

    @staticmethod
    def _style(style):
        if not style:
            return ""
        if style not in _STYLES:
            raise ValueError(f"Unknown button style: {style}")
        return f' style="{style}"'

    def t(self, key, default):
        value = self._translate(f"inline.{key}") if self._translate else None
        return value if isinstance(value, str) else default

    def icon(self, name):
        return _escape(_ICONS.get(name, name or ""))

    def fallback(self, name):
        return _ICONS.get(name, name or "")

    def _label(self, text, icon=None, style=None):
        mark = self.fallback(icon)
        body = str(text)
        return _escape(f"{mark} {body}".strip() or "·")

    def key(self, label, icon=None, style=None):
        text = f"{self.fallback(icon)} {label}".strip() if icon else str(label)
        button = {"text": text}
        if style:
            button["style"] = style
        return button

    def tap(
        self,
        label,
        callback,
        *args,
        style="link",
        icon=None,
        kwargs=None,
        **extra,
    ):
        data = utils.rand(30)
        self.taps[data] = {
            **self.key(label, icon, style if style != "link" else None),
            "callback": callback,
            "args": args,
            "kwargs": kwargs or {},
            "_callback_data": data,
            **extra,
        }
        return (
            f'<tg-button type="callback_data"{self._style(style)} data="{data}">'
            f"{self._label(label, icon, style)}</tg-button>"
        )

    def copy(self, label, value, *, icon="copy"):
        return (
            f'<tg-button type="copy_text" text="{_attr(str(value)[:256] or " ")}">'
            f"{self._label(label, icon)}</tg-button>"
        )

    def badge(self, text, style=None, *, icon=None):
        return (
            f'<tg-button type="disabled"{self._style(style)}>'
            f"{self._label(str(text), icon, style)}</tg-button>"
        )

    @staticmethod
    def row(*buttons, align="left"):
        items = [button for button in buttons if button]
        return "".join(
            f'<tg-button-row align="{_attr(align)}">{"".join(items[index:index + 8])}</tg-button-row>'
            for index in range(0, len(items), 8)
        )

    @staticmethod
    def details(summary, body, *, open=False):
        return f"<details{' open' if open else ''}><summary>{summary}</summary>{body}</details>"

    @staticmethod
    def table(rows, *, keys=True):
        body = "".join(
            "<tr>"
            + "".join(
                f"<th>{cell}</th>" if keys and index == 0 else f"<td>{cell}</td>"
                for index, cell in enumerate(row)
            )
            + "</tr>"
            for row in rows
        )
        return f"<table bordered compact>{body}</table>"

    @staticmethod
    def quote(body, *, expandable=False):
        return f"<blockquote{' expandable' if expandable else ''}>{body}</blockquote>"

    @staticmethod
    def image(url):
        return f'<img src="{_attr(url)}"/>'

    def button(
        self,
        label,
        callback,
        *args,
        style=None,
        icon=None,
        kwargs=None,
        **extra,
    ):
        return {
            **self.key(label, icon, style),
            "callback": callback,
            "args": args,
            "kwargs": kwargs or {},
            **extra,
        }

    def input(
        self,
        label,
        handler,
        prompt,
        *args,
        style=None,
        icon=None,
        kwargs=None,
    ):
        return {
            **self.key(label, icon, style),
            "input": prompt,
            "handler": handler,
            "args": args,
            "kwargs": kwargs or {},
        }

    def copy_button(self, label, value, *, icon="copy"):
        return {**self.key(label, icon), "copy": str(value)[:256] or " "}

    @staticmethod
    def label(text):
        return {"text": str(text), "disabled": True}

    def back(self, callback, *args, kwargs=None):
        return self.button(
            self.t("screen_back", "Back"),
            callback,
            *args,
            icon="back",
            kwargs=kwargs,
        )

    def close(self):
        return {**self.key(self.t("screen_close", "Close"), "close"), "action": "close"}

    def footer(self, back=None, *args, kwargs=None):
        return ([self.back(back, *args, kwargs=kwargs)] if back else []) + [
            self.close()
        ]

    def pager(self, callback, page, pages, *args, kwargs=None):
        if pages <= 1:
            return []
        kwargs = kwargs or {}

        def move(label, target):
            if not 0 <= target < pages:
                return self.label("·")
            return {
                "text": label,
                "callback": callback,
                "args": args,
                "kwargs": {**kwargs, "page": target},
            }

        return [
            move("‹", page - 1),
            self.label(f"{page + 1} / {pages}"),
            move("›", page + 1),
        ]

    @staticmethod
    def page(items, page, size):
        pages = max(1, -(-len(items) // size))
        page = max(0, min(int(page or 0), pages - 1))
        return items[page * size : (page + 1) * size], page, pages

    def add(self, *lines):
        self.body += [line for line in lines if line]
        return self

    def keyboard(self, *rows):
        self.markup += [list(row) for row in rows if row]
        return self

    def warn(self, text):
        self.notice = f"{self.icon('warning')} {_escape(text)}"
        return self

    def reply(self, handler, *args, kwargs=None):
        self.reply_input = {
            "handler": handler,
            "args": args,
            "kwargs": kwargs or {},
        }
        return self

    @property
    def source(self):
        return "\n".join(([self.notice] if self.notice else []) + self.body)

    def html(self):
        return _to_rich(self.source)

    def without_widgets(self):
        """Move unsupported in-text buttons to a normal inline keyboard."""
        source = self.html()
        rows = []

        def button(match):
            attrs = dict(
                re.findall(
                    r"([\w-]+)\s*=\s*[\"']([^\"']*)[\"']",
                    match.group(1),
                )
            )
            label = html.unescape(re.sub(r"<[^>]+>", "", match.group(2))).strip()
            kind = attrs.get("type")
            if kind == "copy_text":
                rows.append([{"text": label or "·", "copy": attrs.get("text", " ")}])
            elif kind == "disabled":
                rows.append([self.label(label or "·")])
            return ""

        source = re.sub(
            r"<tg-button\b([^>]*)>(.*?)</tg-button>",
            button,
            source,
            flags=re.IGNORECASE | re.DOTALL,
        )
        rows += [list(chunk) for chunk in utils.chunks(list(self.taps.values()), 2)]
        source = re.sub(r"</?tg-button-row\b[^>]*>", "", source, flags=re.IGNORECASE)
        return source, rows

    def plain(self):
        """Render Rich screen markup as Telegram HTML plus fallback keyboard rows."""
        source, rows = self.without_widgets()
        source = re.sub(r"<img\b[^>]*/?>", "", source, flags=re.IGNORECASE)
        source = re.sub(r"<br\s*/?>", "\n", source, flags=re.IGNORECASE)
        source = re.sub(
            r"</?(?:details|summary|table|tbody|thead|ul|ol)\b[^>]*>",
            "",
            source,
            flags=re.IGNORECASE,
        )
        source = re.sub(
            r"</?(?:tr|h[1-6]|li)\b[^>]*>",
            "\n",
            source,
            flags=re.IGNORECASE,
        )
        source = re.sub(r"</?(?:th|td)\b[^>]*>", " ", source, flags=re.IGNORECASE)
        source = re.sub(r"<hr\s*/?>", "\n", source, flags=re.IGNORECASE)
        source = re.sub(r"\n{3,}", "\n\n", source).strip()
        return source, rows


class Screens(InlineUnit):
    def screen(self):
        translate = getattr(getattr(self, "translator", None), "getkey", None)
        return Screen(premium=self._premium(), translate=translate)

    def _premium(self):
        return bool(getattr(getattr(self._client, "feroku_me", None), "premium", False))

    async def show(self, call, screen):
        result = await call.edit(rich_html=screen)
        if getattr(call, "data", None) is not None and hasattr(call, "answer"):
            try:
                await call.answer(
                    screen.toast or None,
                    show_alert=screen.alert or None,
                )
            except Exception:
                pass
        return result

    def _bind_screen(self, unit_id, screen, *, fresh=False):
        unit = self._units.get(unit_id) if unit_id is not None else None
        if unit is not None and not fresh:
            for data, entry in self._custom_map.copy().items():
                if entry.get("unit_id") == unit_id:
                    self._custom_map.pop(data, None)
        taps = list(screen.taps.values()) if screen is not None else []
        for tap in taps:
            self._custom_map[tap["_callback_data"]] = {
                "handler": tap["callback"],
                "args": tuple(tap.get("args", ())),
                "kwargs": dict(tap.get("kwargs", {})),
                "force_me": tap.get("force_me", False),
                "disable_security": tap.get("disable_security", False),
                "always_allow": tap.get("always_allow", []) or [],
                "unit_id": unit_id if unit is not None else None,
            }
        if unit is not None:
            unit["rich_buttons"] = taps
            unit["reply_input"] = screen.reply_input if screen is not None else None

    async def _wait_chosen_result(self, unit_id):
        unit = self._units.get(unit_id, {})
        future = unit.get("future")
        try:
            if future is not None:
                await asyncio.wait_for(future.wait(), timeout=10)
        except asyncio.TimeoutError:
            return False
        finally:
            unit.pop("future", None)
            unit.pop("_chosen_result_id", None)
        return True

    @staticmethod
    def _is_not_modified(error):
        return "message is not modified" in str(error).lower()

    def _forget_unit(self, unit_id):
        for data, entry in self._custom_map.copy().items():
            if entry.get("unit_id") == unit_id:
                self._custom_map.pop(data, None)
        return self._units.pop(unit_id, None)
