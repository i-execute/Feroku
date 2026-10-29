import asyncio
import html
import re

from .. import utils
from .types import InlineUnit

_BLOCK = r"details|summary|table|tr|th|td|blockquote|tg-button-row|img|h[1-6]|hr|pre|ul|ol|li"
_BLOCK_RE = re.compile(rf"\n*(</?(?:{_BLOCK})\b[^>]*>)\n*", re.IGNORECASE)
_PRE_RE = re.compile(r"(<pre\b[^>]*>.*?</pre>)", re.IGNORECASE | re.DOTALL)
_STYLES = {"primary", "success", "danger", "link"}


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

    @staticmethod
    def key(label, style=None):
        button = {"text": str(label)}
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
        text = f"{icon} {label}".strip() if icon else str(label)
        self.taps[data] = {
            **self.key(text, style if style != "link" else None),
            "callback": callback,
            "args": args,
            "kwargs": kwargs or {},
            "_callback_data": data,
            **extra,
        }
        return (
            f'<tg-button type="callback_data"{self._style(style)} data="{data}">'
            f"{_escape(text) or '·'}</tg-button>"
        )

    def copy(self, label, value):
        return (
            f'<tg-button type="copy_text" text="{_attr(str(value)[:256] or " ")}">'
            f"{_escape(label) or '·'}</tg-button>"
        )

    def badge(self, text, style=None):
        return (
            f'<tg-button type="disabled"{self._style(style)}>'
            f"{_escape(text) or '·'}</tg-button>"
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

    def button(self, label, callback, *args, style=None, kwargs=None, **extra):
        return {
            **self.key(label, style),
            "callback": callback,
            "args": args,
            "kwargs": kwargs or {},
            **extra,
        }

    def input(self, label, handler, prompt, *args, style=None, kwargs=None):
        return {
            **self.key(label, style),
            "input": prompt,
            "handler": handler,
            "args": args,
            "kwargs": kwargs or {},
        }

    @staticmethod
    def label(text):
        return {"text": str(text), "disabled": True}

    def add(self, *lines):
        self.body += [line for line in lines if line]
        return self

    def keyboard(self, *rows):
        self.markup += [list(row) for row in rows if row]
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


class Screens(InlineUnit):
    def screen(self):
        translate = getattr(getattr(self, "translator", None), "getkey", None)
        return Screen(premium=self._premium(), translate=translate)

    def _premium(self):
        return bool(getattr(getattr(self._client, "feroku_me", None), "premium", False))

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