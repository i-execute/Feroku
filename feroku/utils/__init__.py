# CopyLeft 2026 github.com/i-execute // i_execute.t.me
# Licensed under AGPLv3.

# (c) Dan Gazizullin, 2021-2023. This file is part of the Hikka Userbot: github.com/hikariatama/Hikka

from importlib import import_module


_MODULES = (
    "messages",
    "rich",
    "other",
    "entity",
    "feroku",
    "platform",
    "git",
    "args",
    "placeholders",
)

for _module_name in _MODULES:
    _module = import_module(f"{__name__}.{_module_name}")
    _names = getattr(
        _module,
        "__all__",
        tuple(name for name in vars(_module) if not name.startswith("_")),
    )
    globals().update({name: getattr(_module, name) for name in _names})

del _module_name, _module, _names, import_module
