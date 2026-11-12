# CopyLeft 2026 github.com/i-execute // i_execute.t.me
# Licensed under AGPLv3.

"""Database compatibility for Feroku, Heroku, Hikka, and Ataraxia.

The database is normalized when it is read or restored. Runtime reads and writes
through legacy owners are also redirected, so modules written for another fork
see the same values as native Feroku modules.
"""

_PROJECT_NAMES = ("hikka", "heroku", "ataraxia")

# Core module class names are database owners in all supported forks.
_MODULE_OWNER_ALIASES = {
    "hikkabackupmod": "Backup",
    "herokubackupmod": "Backup",
    "ataraxiabackupmod": "Backup",
    "hikkaconfigmod": "Config",
    "herokuconfigmod": "Config",
    "ataraxiaconfigmod": "Config",
    "evaluator": "Executor",
    "executormod": "Executor",
    "terminalmod": "Executor",
    "info": "FInfo",
    "infomod": "FInfo",
    "ferokuinfomod": "FInfo",
    "hikkainfomod": "FInfo",
    "herokuinfomod": "FInfo",
    "ataraxiainfomod": "FInfo",
    "finfomod": "FInfo",
    "loader": "Installer",
    "loadermod": "Installer",
    "hikkasecuritymod": "Security",
    "herokusecuritymod": "Security",
    "ataraxiasecuritymod": "Security",
    "coremod": "Settings",
    "hikkasettingsmod": "Settings",
    "herokusettingsmod": "Settings",
    "ataraxiasettingsmod": "Settings",
    "testmod": "Tester",
    "updatermod": "Restart",
}

_DATABASE_KEY_ALIASES = {
    ("Restart", "selfupdatemsg"): "restart_message",
    ("Restart", "restart_ts"): "restart_started",
    ("Restart", "upd_msg"): "restart_message",
}

_CONFIG_KEY_ALIASES = {
    "Help": {
        "quote_media": "media_quote",
    },
    "FInfo": {
        "custom_message1": "custom_message",
        "custom_message_1": "custom_message",
    },
    "Info": {
        "custom_message1": "custom_message",
        "custom_message_1": "custom_message",
    },
    "Tester": {
        "custom_message1": "custom_message",
        "custom_message_1": "custom_message",
    },
}


def resolve_database_owner(owner):
    if not isinstance(owner, str):
        return owner

    owner_folded = owner.casefold()
    for project in _PROJECT_NAMES:
        if owner_folded == project or owner_folded.startswith(f"{project}."):
            return f"feroku{owner[len(project):]}"

    return _MODULE_OWNER_ALIASES.get(owner_folded, owner)


def resolve_database_location(owner, key):
    owner = resolve_database_owner(owner)
    if isinstance(key, str):
        key = _DATABASE_KEY_ALIASES.get((owner, key), key)
    return owner, key


def _as_repository_list(value):
    if value is None:
        return []
    values = value if isinstance(value, (list, tuple, set)) else [value]
    result = []
    for item in values:
        if not isinstance(item, str):
            continue
        item = item.strip()
        if item.endswith("/full.txt"):
            item = item[:-9]
        if item and item not in result:
            result.append(item)
    return result


def normalize_module_config(owner, value):
    if not isinstance(value, dict):
        return value

    owner = resolve_database_owner(owner)
    result = dict(value)
    for old_key, new_key in _CONFIG_KEY_ALIASES.get(owner, {}).items():
        if old_key in result:
            result.setdefault(new_key, result[old_key])
            result.pop(old_key, None)

    if owner == "Installer":
        repositories = []
        for key in ("modules_repo", "MODULES_REPO", "ADDITIONAL_REPOS"):
            repositories.extend(_as_repository_list(result.pop(key, None)))
        if repositories:
            result["modules_repo"] = list(dict.fromkeys(repositories))

    return result


def normalize_database_value(owner, key, value):
    owner, key = resolve_database_location(owner, key)
    if key == "__config__":
        value = normalize_module_config(owner, value)
    return owner, key, value


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


def _merge_dicts(legacy, current):
    if not isinstance(legacy, dict):
        return current
    if not isinstance(current, dict):
        return legacy
    result = dict(legacy)
    for key, value in current.items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            nested = dict(result[key])
            nested.update(value)
            result[key] = nested
        else:
            result[key] = value
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


def normalize_module_aliases(value):
    if not isinstance(value, dict):
        return {}
    aliases = {}
    for alias, command in value.items():
        if not isinstance(alias, str) or not isinstance(command, str):
            continue
        alias = alias.strip().lower()
        command = command.strip()
        if alias and command:
            aliases[alias] = command
    return aliases


def migrate_module_alias_storage(value):
    if not isinstance(value, dict):
        return value
    result = dict(value)
    aliases = {}
    owners = [
        owner
        for owner in result
        if isinstance(owner, str)
        and resolve_database_owner(owner) == "Settings"
    ]
    owners.sort(key=lambda owner: owner == "Settings")
    has_aliases = False
    current_aliases = None
    for owner in owners:
        section = result.get(owner)
        if not isinstance(section, dict) or "aliases" not in section:
            continue
        has_aliases = True
        normalized = normalize_module_aliases(section.get("aliases"))
        if owner == "Settings":
            current_aliases = normalized
        else:
            aliases.update(normalized)
        if owner != "Settings":
            section = dict(section)
            section.pop("aliases", None)
            if section:
                result[owner] = section
            else:
                result.pop(owner, None)
    if has_aliases:
        if current_aliases is not None:
            aliases.update(current_aliases)
        settings = result.get("Settings")
        settings = dict(settings) if isinstance(settings, dict) else {}
        settings["aliases"] = aliases
        result["Settings"] = settings
    return result


def _merge_forum_sections(*sections):
    merged = {}
    merged_cache = {}
    for section in sections:
        if not isinstance(section, dict):
            continue
        for key, item in section.items():
            if key != "forums_cache":
                merged[key] = item
                continue
            if not isinstance(item, dict):
                continue
            for channel, topics in item.items():
                if not isinstance(channel, str) or not isinstance(topics, dict):
                    continue
                merged_cache.setdefault(channel, {}).update(topics)

    canonical = {}
    for channel in (
        "hikka-userbot",
        "heroku-userbot",
        "ataraxia-userbot",
        "feroku-userbot",
    ):
        topics = merged_cache.get(channel)
        if isinstance(topics, dict):
            canonical.update(topics)
    if canonical:
        merged_cache["feroku-userbot"] = canonical
    if merged_cache:
        merged["forums_cache"] = merged_cache
    return merged


def _migrate_project_namespaces(result):
    forums = []
    for project in _PROJECT_NAMES:
        for key in list(result):
            if not isinstance(key, str):
                continue
            folded = key.casefold()
            if folded != project and not folded.startswith(f"{project}."):
                continue
            target = f"feroku{key[len(project):]}"
            legacy = result.pop(key)
            if target.casefold() == "feroku.forums":
                forums.append(legacy)
                continue
            result[target] = _merge_dicts(legacy, result.get(target))

    current_forums = result.get("feroku.forums")
    if forums or isinstance(current_forums, dict):
        result["feroku.forums"] = _merge_forum_sections(
            *forums,
            current_forums,
        )
    return result


def _migrate_combined_info(result):
    """Ataraxia keeps Help and Info state in one module owner."""
    for owner in list(result):
        if not isinstance(owner, str) or owner.casefold() != "ataraxiainfomod":
            continue
        section = result.get(owner)
        if not isinstance(section, dict):
            continue
        help_section = {}
        if "hide" in section:
            help_section["hide"] = section["hide"]
        config = section.get("__config__")
        if isinstance(config, dict):
            help_config = {}
            if "help_banner_url" in config:
                help_config["banner_url"] = config["help_banner_url"]
            for key in (
                "show_preview_in_help",
                "media_quote",
                "rich_mode",
                "invert_media",
            ):
                if key in config:
                    help_config[key] = config[key]
            if "quote_media" in config:
                help_config["media_quote"] = config["quote_media"]
            if help_config:
                help_section["__config__"] = help_config
        if help_section:
            result["Help"] = _merge_dicts(help_section, result.get("Help"))
    return result


def _merge_module_sections(owner, legacy, current):
    merged = _merge_dicts(legacy, current)
    if owner != "Installer" or not isinstance(merged, dict):
        return merged

    repositories = []
    for section in (legacy, current):
        if not isinstance(section, dict):
            continue
        config = normalize_module_config(owner, section.get("__config__"))
        if isinstance(config, dict):
            repositories.extend(_as_repository_list(config.get("modules_repo")))
    if repositories:
        config = dict(merged.get("__config__", {}))
        config["modules_repo"] = list(dict.fromkeys(repositories))
        merged["__config__"] = config
    return merged


def _migrate_module_owners(result):
    for owner in list(result):
        if not isinstance(owner, str):
            continue
        target = _MODULE_OWNER_ALIASES.get(owner.casefold())
        if not target or owner == target:
            continue
        legacy = result.pop(owner)
        if isinstance(legacy, dict) and "__config__" in legacy:
            legacy = dict(legacy)
            legacy["__config__"] = normalize_module_config(
                target,
                legacy["__config__"],
            )
        result[target] = _merge_module_sections(
            target,
            legacy,
            result.get(target),
        )

    for owner, section in list(result.items()):
        if isinstance(section, dict) and "__config__" in section:
            section = dict(section)
            section["__config__"] = normalize_module_config(
                owner,
                section["__config__"],
            )
            result[owner] = section
    return result


def _migrate_database_keys(result):
    for (owner, legacy_key), current_key in _DATABASE_KEY_ALIASES.items():
        section = result.get(owner)
        if not isinstance(section, dict) or legacy_key not in section:
            continue
        section = dict(section)
        section.setdefault(current_key, section[legacy_key])
        section.pop(legacy_key, None)
        result[owner] = section
    return result


def migrate_database_items(value):
    if not isinstance(value, dict):
        return value

    result = _migrate_project_namespaces(dict(value))
    result = migrate_module_origin_storage(result)
    result = _migrate_combined_info(result)
    result = migrate_module_alias_storage(result)
    result = _migrate_module_owners(result)
    return _migrate_database_keys(result)


def prepare_backup_database(value):
    if not isinstance(value, dict):
        return value
    result = migrate_database_items(value)
    inline = result.get("feroku.inline")
    if isinstance(inline, dict):
        inline = dict(inline)
        inline.pop("bot_token", None)
        result["feroku.inline"] = inline
    return result
