# CopyLeft 2026 github.com/i-execute // i_execute.t.me
# Licensed under AGPLv3.


def normalize_module_origins(value):
    if not isinstance(value, dict):
        return {}
    result = {}
    for class_name, url in value.items():
        if not isinstance(class_name, str) or not class_name.isidentifier():
            continue
        if not isinstance(url, str):
            continue
        url = url.strip()
        if url.startswith(("http://", "https://")):
            result[class_name] = url
    return result


def migrate_module_origin_storage(value):
    if not isinstance(value, dict):
        return value
    result = dict(value)
    installer = result.get("Installer")
    legacy = result.get("LoaderMod")
    current_present = isinstance(installer, dict) and "loaded_modules" in installer
    legacy_present = isinstance(legacy, dict) and "loaded_modules" in legacy
    if current_present or legacy_present:
        origins = normalize_module_origins(
            legacy.get("loaded_modules") if isinstance(legacy, dict) else None
        )
        origins.update(
            normalize_module_origins(
                installer.get("loaded_modules")
                if isinstance(installer, dict)
                else None
            )
        )
        installer = dict(installer) if isinstance(installer, dict) else {}
        installer["loaded_modules"] = origins
        result["Installer"] = installer
    if legacy_present:
        legacy = dict(legacy)
        legacy.pop("loaded_modules", None)
        if legacy:
            result["LoaderMod"] = legacy
        else:
            result.pop("LoaderMod", None)
    return result


def migrate_database_items(value):
    if not isinstance(value, dict):
        return value
    result = dict(value)
    for key in list(result):
        if key == "heroku" or key.startswith("heroku."):
            target = f"feroku{key[6:]}"
            legacy = result.pop(key)
            current = result.get(target)
            if isinstance(legacy, dict) and isinstance(current, dict):
                legacy = dict(legacy)
                legacy.update(current)
                result[target] = legacy
            elif target not in result:
                result[target] = legacy
    forums = result.get("feroku.forums")
    if isinstance(forums, dict):
        forums = dict(forums)
        cache = forums.get("forums_cache")
        if isinstance(cache, dict):
            cache = dict(cache)
            if "heroku-userbot" in cache:
                cache.setdefault("feroku-userbot", cache.pop("heroku-userbot"))
            forums["forums_cache"] = cache
        result["feroku.forums"] = forums
    return migrate_module_origin_storage(result)


def prepare_backup_database(value):
    if not isinstance(value, dict):
        return value
    result = dict(value)
    inline = result.get("heroku.inline")
    if isinstance(inline, dict):
        inline = dict(inline)
        inline.pop("bot_token", None)
        result["heroku.inline"] = inline
    return migrate_database_items(result)
