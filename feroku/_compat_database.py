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
    return result


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
