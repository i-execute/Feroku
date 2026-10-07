# CopyLeft 2026 github.com/i-execute // i_execute.t.me
# Licensed under AGPLv3.

# (c) Dan Gazizullin, 2021-2023. This file is part of the Hikka Userbot: github.com/hikariatama/Hikka

import typing

custom_placeholders = {}

def register_placeholder(
    placeholder: str,
    callback: typing.Callable,
    description: str | None = None,
):
    module_name = callback.__self__.__class__.__name__
    module_instance = callback.__self__
    custom_placeholders[placeholder] = {
        "module_name": module_name,
        "module_instance": module_instance,
        "callback": callback,
        "description": description,
        "placeholder_name": placeholder,
    }
    return True

async def get_placeholder(placeholder: str, data: dict | None = None):
    callback = custom_placeholders[placeholder]["callback"]
    try:
        callback_data = str(await callback(data))
    except Exception:
        callback_data = str(await callback())
    return callback_data

async def get_placeholders(data, custom_message):
    if custom_message is None:
        return data
    for placeholder in custom_placeholders.values():
        if f"{{{placeholder['placeholder_name']}}}" in custom_message:
            data[placeholder["placeholder_name"]] = await get_placeholder(
                placeholder["placeholder_name"], data
            )
    return data

def unregister_placeholders(module_name: str) -> int:
    placeholders_to_remove = []
    for placeholder_name, placeholder_data in custom_placeholders.items():
        if placeholder_data.get("module_name") == module_name:
            placeholders_to_remove.append(placeholder_name)
    for placeholder_name in placeholders_to_remove:
        del custom_placeholders[placeholder_name]
    return True

def config_placeholders():
    result = []
    for placeholder_name, placeholder_data in custom_placeholders.items():
        result.append(
            f"{{{placeholder_name}}} - {placeholder_data.get('description') if placeholder_data.get('description') is not None else 'No docs'}"
        )
    if result == []:
        return None
    else:
        return "\n".join(result)

def module_placeholders(module_name: str) -> list[str]:
    result = []
    for placeholder_name, placeholder_data in custom_placeholders.items():
        if placeholder_data.get("module_name") == module_name:
            result.append(placeholder_name)
    return result

def help_placeholders(module_name, self):
    result = []
    for placeholder_name, placeholder_data in custom_placeholders.items():
        if placeholder_data.get("module_name") == module_name:
            if placeholder_data.get("description") is not None:
                result.append(
                    self.db.get("Help", "__config__", None).get("command_emoji")
                    + f" {{{placeholder_name}}} - {placeholder_data.get('description')}"
                )
            else:
                result.append(
                    self.db.get("Help", "__config__", None).get("command_emoji")
                    + f" {{{placeholder_name}}} - No docs"
                )
    return result

def debug_placeholders():
    return custom_placeholders
