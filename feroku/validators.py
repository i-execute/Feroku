# CopyLeft 2026 github.com/i-execute // i_execute.t.me
# Licensed under AGPLv3.

# (c) Dan Gazizullin, 2021-2023. This file is part of the Hikka Userbot: github.com/hikariatama/Hikka

import functools
import re
import typing
from collections.abc import Callable

import grapheme
import emoji

from . import utils
_VALIDATORS_STRINGS = {
    "validators.boolean": "boolean",
    "validators.positive": "positive ",
    "validators.negative": "negative ",
    "validators.digits": " with exactly {digits} digits",
    "validators.integer_min": "{sign}integer greater than {minimum}{digits}",
    "validators.integer_range": "{sign}integer from {minimum} to {maximum}{digits}",
    "validators.integer": "{sign}integer{digits}",
    "validators.integer_max": "{sign}integer less than {maximum}{digits}",
    "validators.choice": "one of the following: {possible}",
    "validators.multichoice": "list of values, where each one must be one of: {possible}",
    "validators.each": ", each value must be {each}",
    "validators.fixed_len": " with exactly {fixed_len} items",
    "validators.max_len": " with up to {max_len} items",
    "validators.len_range": " with {min_len} to {max_len} items",
    "validators.min_len": " with at least {min_len} items",
    "validators.series": "list of values{len}{each}, separated by commas",
    "validators.link": "link",
    "validators.string_fixed_len": "string of length {length}",
    "validators.string": "string",
    "validators.string_max_len": "string of length up to {max_len}",
    "validators.string_len_range": "string of length from {min_len} to {max_len}",
    "validators.string_min_len": "string of length at least {min_len}",
    "validators.regex": "string matching pattern «{regex}»",
    "validators.float_min": "{sign}float greater than {minimum}",
    "validators.float_range": "{sign}float from {minimum} to {maximum}",
    "validators.float": "{sign}float",
    "validators.float_max": "{sign}float less than {maximum}",
    "validators.union": "one of the following:",
    "validators.empty": "empty value",
    "validators.emoji_fixed_len": "{length} emojis",
    "validators.emoji_len_range": "{min_len} to {max_len} emojis",
    "validators.emoji_min_len": "at least {min_len} emoji",
    "validators.emoji_max_len": "no more than {max_len} emojis",
    "validators.emoji": "emoji",
    "validators.entity_like": "link to entity, username or Telegram ID",
}

ConfigAllowedTypes = typing.Union[tuple, list, str, int, bool, None]

ALLOWED_EMOJIS = set(emoji.EMOJI_DATA.keys())

def _getdoc(key: str, **kwargs) -> str:
    value = _VALIDATORS_STRINGS[key]
    return value.format(**kwargs) if kwargs else value


class ValidationError(Exception):
    pass
class Validator:
    def __init__(
        self,
        validator: Callable,
        doc: str | None = None,
        _internal_id: str | None = None,
    ):
        self.validate = validator
        self.doc = doc or "value"
        self.internal_id = _internal_id

class Boolean(Validator):
    _TRUE_VALUES = frozenset(
        ("True", "true", "1", 1, True, "yes", "Yes", "on", "On", "y", "Y")
    )
    _FALSE_VALUES = frozenset(
        ("False", "false", "0", 0, False, "no", "No", "off", "Off", "n", "N")
    )
    _ALL_VALUES = _TRUE_VALUES | _FALSE_VALUES

    def __init__(self):
        super().__init__(
            self._validate,
            _getdoc("validators.boolean"),
            _internal_id="Boolean",
        )

    @staticmethod
    def _validate(value: ConfigAllowedTypes, /) -> bool:
        if value not in Boolean._ALL_VALUES:
            raise ValidationError("Passed value must be a boolean")

        return value in Boolean._TRUE_VALUES

class Integer(Validator):
    def __init__(
        self,
        *,
        digits: int | None = None,
        minimum: int | None = None,
        maximum: int | None = None,
    ):
        sign = (
            _getdoc("validators.positive")
            if minimum == 0
            else _getdoc("validators.negative")
            if maximum == 0
            else ""
        )
        digits_doc = (
            _getdoc("validators.digits", digits=digits) if digits is not None else ""
        )
        if minimum is not None and minimum != 0:
            key = "validators.integer_min" if maximum is None else "validators.integer_range"
        elif maximum is None:
            key = "validators.integer"
        else:
            key = "validators.integer_max"
        doc = _getdoc(key).format(
            sign=sign,
            digits=digits_doc,
            minimum=minimum,
            maximum=maximum,
        )
        super().__init__(
            functools.partial(
                self._validate,
                digits=digits,
                minimum=minimum,
                maximum=maximum,
            ),
            doc,
            _internal_id="Integer",
        )

    @staticmethod
    def _validate(
        value: ConfigAllowedTypes,
        /,
        *,
        digits: int | None,
        minimum: int | None,
        maximum: int | None,
    ) -> int:
        try:
            value = int(str(value).strip())
        except ValueError as error:
            raise ValidationError(f"Passed value ({value}) must be a number") from error
        if minimum is not None and value < minimum:
            raise ValidationError(f"Passed value ({value}) is lower than minimum one")
        if maximum is not None and value > maximum:
            raise ValidationError(f"Passed value ({value}) is greater than maximum one")
        if digits is not None and len(str(value)) != digits:
            raise ValidationError(
                f"The length of passed value ({value}) is incorrect "
                f"(Must be exactly {digits} digits)"
            )
        return value

class Choice(Validator):
    def __init__(
        self,
        possible_values: list[ConfigAllowedTypes],
        /,
    ):
        super().__init__(
            functools.partial(self._validate, possible_values=possible_values),
            _getdoc(
                "validators.choice",
                possible=" / ".join(list(map(str, possible_values))),
            ),
            _internal_id="Choice",
        )

    @staticmethod
    def _validate(
        value: ConfigAllowedTypes,
        /,
        *,
        possible_values: list[ConfigAllowedTypes],
    ) -> ConfigAllowedTypes:
        if value not in possible_values:
            raise ValidationError(
                f"Passed value ({value}) is not one of the following:"
                f" {' / '.join(list(map(str, possible_values)))}"
            )

        return value

class MultiChoice(Validator):
    def __init__(
        self,
        possible_values: list[ConfigAllowedTypes],
        /,
    ):
        possible = " / ".join(list(map(str, possible_values)))
        super().__init__(
            functools.partial(self._validate, possible_values=possible_values),
            _getdoc("validators.multichoice", possible=possible),
            _internal_id="MultiChoice",
        )

    @staticmethod
    def _validate(
        value: list[ConfigAllowedTypes],
        /,
        *,
        possible_values: list[ConfigAllowedTypes],
    ) -> list[ConfigAllowedTypes]:
        if not isinstance(value, (list, tuple)):
            value = [value]

        for item in value:
            if item not in possible_values:
                raise ValidationError(
                    f"One of passed values ({item}) is not one of the following:"
                    f" {' / '.join(list(map(str, possible_values)))}"
                )

        return list(set(value))

class Series(Validator):
    def __init__(
        self,
        validator: Validator | None = None,
        min_len: int | None = None,
        max_len: int | None = None,
        fixed_len: int | None = None,
    ):
        each = (
            _getdoc("validators.each", each=validator.doc)
            if validator is not None
            else ""
        )
        if fixed_len is not None:
            length = _getdoc("validators.fixed_len", fixed_len=fixed_len)
        elif min_len is None:
            length = (
                "" if max_len is None else _getdoc("validators.max_len", max_len=max_len)
            )
        elif max_len is not None:
            length = _getdoc(
                "validators.len_range", min_len=min_len, max_len=max_len
            )
        else:
            length = _getdoc("validators.min_len", min_len=min_len)
        super().__init__(
            functools.partial(
                self._validate,
                validator=validator,
                min_len=min_len,
                max_len=max_len,
                fixed_len=fixed_len,
            ),
            _getdoc("validators.series").format(each=each, len=length),
            _internal_id="Series",
        )

    @staticmethod
    def _validate(
        value: ConfigAllowedTypes,
        /,
        *,
        validator: Validator | None = None,
        min_len: int | None = None,
        max_len: int | None = None,
        fixed_len: int | None = None,
    ) -> list[ConfigAllowedTypes]:
        if not isinstance(value, (list, tuple, set)):
            value = str(value).split(",")
        if isinstance(value, (tuple, set)):
            value = list(value)
        if min_len is not None and len(value) < min_len:
            raise ValidationError(
                f"Passed value ({value}) contains less than {min_len} items"
            )
        if max_len is not None and len(value) > max_len:
            raise ValidationError(
                f"Passed value ({value}) contains more than {max_len} items"
            )
        if fixed_len is not None and len(value) != fixed_len:
            raise ValidationError(
                f"Passed value ({value}) must contain exactly {fixed_len} items"
            )
        value = [item.strip() if isinstance(item, str) else item for item in value]
        if isinstance(validator, Validator):
            for index, item in enumerate(value):
                try:
                    value[index] = validator.validate(item)
                except ValidationError as error:
                    raise ValidationError(
                        f"Passed value ({value}) contains invalid item "
                        f"({str(item).strip()}), which must be {validator.doc}"
                    ) from error
        return list(filter(lambda item: item, value))

class Link(Validator):
    def __init__(self):
        super().__init__(
            lambda value: self._validate(value),
            _getdoc("validators.link"),
            _internal_id="Link",
        )

    @staticmethod
    def _validate(value: ConfigAllowedTypes, /) -> str:
        try:
            if not utils.check_url(value):
                raise Exception("Invalid URL")
        except Exception:
            raise ValidationError(f"Passed value ({value}) is not a valid URL")

        return value

class String(Validator):
    def __init__(
        self,
        length: int | None = None,
        min_len: int | None = None,
        max_len: int | None = None,
    ):
        if length is not None:
            doc = _getdoc("validators.string_fixed_len", length=length)
        else:
            match True:
                case _ if min_len is None:
                    if max_len is None:
                        doc = _getdoc("validators.string")
                    else:
                        doc = _getdoc(
                            "validators.string_max_len", max_len=max_len
                        )
                case _ if max_len is not None:
                    doc = _getdoc(
                        "validators.string_len_range", min_len=min_len, max_len=max_len
                    )
                case _:
                    doc = _getdoc(
                        "validators.string_min_len", min_len=min_len
                    )

        super().__init__(
            functools.partial(
                self._validate,
                length=length,
                min_len=min_len,
                max_len=max_len,
            ),
            doc,
            _internal_id="String",
        )

    @staticmethod
    def _validate(
        value: ConfigAllowedTypes,
        /,
        *,
        length: int | None,
        min_len: int | None,
        max_len: int | None,
    ) -> str:
        if (
            isinstance(length, int)
            and len(list(grapheme.graphemes(str(value)))) != length
        ):
            raise ValidationError(
                f"Passed value ({value}) must be a length of {length}"
            )

        if (
            isinstance(min_len, int)
            and len(list(grapheme.graphemes(str(value)))) < min_len
        ):
            raise ValidationError(
                f"Passed value ({value}) must be a length of at least {min_len}"
            )

        if (
            isinstance(max_len, int)
            and len(list(grapheme.graphemes(str(value)))) > max_len
        ):
            raise ValidationError(
                f"Passed value ({value}) must be a length of up to {max_len}"
            )

        return str(value)

class RegExp(Validator):
    def __init__(
        self,
        regex: str,
        flags: re.RegexFlag | None = None,
        description: str | dict | None = None,
    ):
        flags = flags or 0
        try:
            re.compile(regex, flags=flags)
        except re.error as error:
            raise ValueError(f"{regex} is not a valid regex") from error
        if isinstance(description, dict):
            description = next(iter(description.values()), None)
        doc = description or _getdoc("validators.regex", regex=regex)
        super().__init__(
            functools.partial(self._validate, regex=regex, flags=flags),
            doc,
            _internal_id="RegExp",
        )

    @staticmethod
    def _validate(
        value: ConfigAllowedTypes,
        /,
        *,
        regex: str,
        flags: re.RegexFlag | None,
    ) -> str:
        if not re.match(regex, str(value), flags=flags):
            raise ValidationError(f"Passed value ({value}) must follow pattern {regex}")
        return str(value)

class Float(Validator):
    def __init__(
        self,
        minimum: float | None = None,
        maximum: float | None = None,
    ):
        sign = (
            _getdoc("validators.positive")
            if minimum == 0
            else _getdoc("validators.negative")
            if maximum == 0
            else ""
        )
        if minimum is not None and minimum != 0:
            key = "validators.float_min" if maximum is None else "validators.float_range"
        elif maximum is None:
            key = "validators.float"
        else:
            key = "validators.float_max"
        doc = _getdoc(key).format(
            sign=sign,
            minimum=minimum,
            maximum=maximum,
        )
        super().__init__(
            functools.partial(self._validate, minimum=minimum, maximum=maximum),
            doc,
            _internal_id="Float",
        )

    @staticmethod
    def _validate(
        value: ConfigAllowedTypes,
        /,
        *,
        minimum: float | None = None,
        maximum: float | None = None,
    ) -> float:
        try:
            value = float(str(value).strip().replace(",", "."))
        except ValueError as error:
            raise ValidationError(f"Passed value ({value}) must be a float") from error
        if minimum is not None and value < minimum:
            raise ValidationError(f"Passed value ({value}) is lower than minimum one")
        if maximum is not None and value > maximum:
            raise ValidationError(f"Passed value ({value}) is greater than maximum one")
        return value

class TelegramID(Validator):
    def __init__(self):
        super().__init__(
            self._validate,
            "Telegram ID",
            _internal_id="TelegramID",
        )

    @staticmethod
    def _validate(value: ConfigAllowedTypes, /) -> int:
        e = ValidationError(f"Passed value ({value}) is not a valid telegram id")

        try:
            value = int(str(value).strip())
        except Exception:
            raise e

        if str(value).startswith("-100"):
            value = int(str(value)[4:])

        if value > 2**64 - 1 or value < 0:
            raise e

        return value

class Union(Validator):
    def __init__(self, *validators):
        lines = [validator.doc[:1].upper() + validator.doc[1:] for validator in validators]
        doc = _getdoc("validators.union") + "\n" + "\n".join(
            f"- {line}" for line in lines
        )
        super().__init__(
            functools.partial(self._validate, validators=validators),
            doc.strip(),
            _internal_id="Union",
        )

    @staticmethod
    def _validate(
        value: ConfigAllowedTypes,
        /,
        *,
        validators: list,
    ) -> ConfigAllowedTypes:
        for validator in validators:
            try:
                return validator.validate(value)
            except ValidationError:
                pass
        raise ValidationError(f"Passed value ({value}) is not valid")

class NoneType(Validator):
    def __init__(self):
        super().__init__(
            self._validate,
            _getdoc("validators.empty"),
            _internal_id="NoneType",
        )

    @staticmethod
    def _validate(value: ConfigAllowedTypes, /) -> None:
        if not value:
            raise ValidationError(f"Passed value ({value}) is not None")

        return None

class Hidden(Validator):
    def __init__(self, validator: Validator | None = None):
        if not validator:
            validator = String()

        super().__init__(
            functools.partial(self._validate, validator=validator),
            validator.doc,
            _internal_id="Hidden",
        )

    @staticmethod
    def _validate(
        value: ConfigAllowedTypes,
        /,
        *,
        validator: Validator,
    ) -> ConfigAllowedTypes:
        return validator.validate(value)

class Emoji(Validator):
    def __init__(
        self,
        length: int | None = None,
        min_len: int | None = None,
        max_len: int | None = None,
    ):
        match True:
            case _ if length is not None:
                doc = _getdoc("validators.emoji_fixed_len", length=length)
            case _ if min_len is not None and max_len is not None:
                doc = _getdoc(
                    "validators.emoji_len_range", min_len=min_len, max_len=max_len
                )
            case _ if min_len is not None:
                doc = _getdoc("validators.emoji_min_len", min_len=min_len)
            case _ if max_len is not None:
                doc = _getdoc("validators.emoji_max_len", max_len=max_len)
            case _:
                doc = _getdoc("validators.emoji")

        super().__init__(
            functools.partial(
                self._validate,
                length=length,
                min_len=min_len,
                max_len=max_len,
            ),
            doc,
            _internal_id="Emoji",
        )

    @staticmethod
    def _validate(
        value: ConfigAllowedTypes,
        /,
        *,
        length: int | None,
        min_len: int | None,
        max_len: int | None,
    ) -> str:
        value = str(value)
        passed_length = len(list(grapheme.graphemes(value)))

        if length is not None and passed_length != length:
            raise ValidationError(f"Passed value ({value}) is not {length} emojis long")

        if (
            min_len is not None
            and max_len is not None
            and (passed_length < min_len or passed_length > max_len)
        ):
            raise ValidationError(
                f"Passed value ({value}) is not between {min_len} and {max_len} emojis"
                " long"
            )

        if min_len is not None and passed_length < min_len:
            raise ValidationError(
                f"Passed value ({value}) is not at least {min_len} emojis long"
            )

        if max_len is not None and passed_length > max_len:
            raise ValidationError(
                f"Passed value ({value}) is not no more than {max_len} emojis long"
            )

        if any(emoji not in ALLOWED_EMOJIS for emoji in grapheme.graphemes(value)):
            raise ValidationError(
                f"Passed value ({value}) is not a valid string with emojis"
            )

        return value

class EntityLike(RegExp):
    def __init__(self):
        super().__init__(
            regex=r"^(?:@|https?://t\.me/)?(?:[a-zA-Z0-9_]{5,32}|[a-zA-Z0-9_]{1,32}\?[a-zA-Z0-9_]{1,32})$",
            description=_getdoc("validators.entity_like"),
        )

    @staticmethod
    def _validate(
        value: ConfigAllowedTypes,
        /,
        *,
        regex: str,
        flags: re.RegexFlag | None,
    ) -> str | int:
        value = super()._validate(value, regex=regex, flags=flags)

        if value.isdigit():
            if value.startswith("-100"):
                value = value[4:]

            value = int(value)

        if value.startswith("https://t.me/"):
            value = value.split("https://t.me/")[1]

        if not value.startswith("@"):
            value = f"@{value}"

        return value

class RandomLinkList(list):
    def __str__(self):
        import random

        if not self:
            return ""
        return str(random.choice(self))

    def __bytes__(self):
        return str(self).encode("utf-8")

    def __repr__(self):
        return super().__repr__()

class RandomLink(Series):
    def __init__(self):
        super().__init__(validator=Link(), min_len=1)
        self.internal_id = "Series"
        self.doc = "A list of links, one of which will be chosen randomly"

    @staticmethod
    def _validate(value: ConfigAllowedTypes, /, **kwargs) -> RandomLinkList:
        val_args = kwargs.copy()
        if "validator" not in val_args:
            val_args["validator"] = Link()
        if "min_len" not in val_args:
            val_args["min_len"] = 1
        clean_list = Series._validate(value, **val_args)
        return RandomLinkList(clean_list)
