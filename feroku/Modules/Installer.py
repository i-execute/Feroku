# CopyLeft 2026 github.com/i-execute // i_execute.t.me
# Licensed under AGPLv3.

# (c) Dan Gazizullin, 2021-2023. This file is part of the Hikka Userbot: github.com/hikariatama/Hikka

from pathlib import Path
import ast
import asyncio
import contextlib
import difflib
import inspect
import io
import logging
import os
import re
import requests
import subprocess
import uuid
from importlib.machinery import ModuleSpec
from urllib.parse import unquote, urlparse

from telethon.tl.custom import Message
from telethon.tl.types import InputMediaWebPage
from telethon.errors.rpcerrorlist import MediaCaptionTooLongError

from .. import loader, main, utils
from .._compat import match_legacy_minimum
from ..inline.types import InlineCall
from ..types import CoreOverwriteError, CoreUnloadError

logger = logging.getLogger(__name__)

class ModuleInstallError(RuntimeError):
    pass

@loader.tds
class Installer(loader.Module):

    strings = {
        "name": "Installer",
        "link": "<b>File of</b> {class_name}\n\n<b>{prefix}lm in reply to this message to install</b>\n\n<code>{prefix}dlm {url}</code>\n\n{not_exact}",
        "file": "<b>File of</b> {class_name}\n\n<b>{prefix}lm in reply to this message to install</b>\n\n{not_exact}",
        "loading_module_via_file": "<b>Installing module</b>",
        "ml_load_module": "<b>Preparing module file</b>",
        "no_ml": "<b>Module</b> <code>{}</code> <b>cannot be exported as a file</b>",
        "not_exact": "<i>No exact match has been found, so the closest result is shown instead</i>",
        "args": "<b>You must specify arguments</b>",
        "provide_module": "<b>Provide a module to load</b>",
        "bad_unicode": "<b>Invalid Unicode formatting in module</b>",
        "load_failed": "<b>Module installation failed</b>\n<blockquote>Check the service logs for details.</blockquote>",
        "loaded": "<b>Module</b> <code>{}</code> <b>loaded</b>",
        "no_class": "<b>What class needs to be unloaded?</b>",
        "unloaded": "{} <b>Module {} unloaded.</b>",
        "unload_suggestions": "<b>Module</b> <code>{}</code> <b>not found.</b>\n\n<b>Maybe you meant:</b>",
        "modules_unloaded": "<b>Unloaded {unloaded_num} modules:</b>\n<blockquote expandable>{unloaded}</blockquote>",
        "not_unloaded": "<b>Module not unloaded.</b>",
        "modules_not_unloaded": "<b>Failed to unload {not_unloaded} modules.</b>\n<blockquote expandable>{errors}</blockquote>",
        "requirements_failed": "<b>Requirements installation failed</b>",
        "undoc": "No docs",
        "ihandler": "<code>{}</code> {}",
        "inline_init_failed": "<b>This module requires the Feroku inline feature, but InlineManager initialization failed.</b>\n<i>Check the configured bot token and inline mode, then restart the service.</i>",
        "version_incompatible": "<b>This module requires Feroku {}+\nPull the latest code and restart the service.</b>",
        "ffmpeg_required": "<b>This module requires FFMPEG, which is not installed</b>",
        "developer": "<b>Developer:</b> {}",
        "depends_from": "<b>Dependencies:</b> \n{}",
        "by": "by",
        "cancel": "Cancel",
        "unload_core": "<b>You can't unload core module</b> <code>{}</code><b></b>\n\n<i> Don't report it as bug. It's a security measure to prevent replacing core modules with some junk</i>",
        "cannot_unload_lib": "<b>You can't unload library</b>",
        "_cls_doc": "Loads modules",
        "404": "<b>Module not found</b>",
        "_cmd_doc_ml": "<module> - Send module as a file",
        "installing": "<b>Downloading module</b> <code>{}</code>...",
        "no_module": "<b>Can't download module from this link.</b>",
        "_cmd_doc_dlm": "[module/URL] - Browse or load modules",
        "_cmd_doc_lm": "<reply to file> - Load a module from file",
        "_cmd_doc_ulm": "<module> - Unload a module",
        "confirm_nuke": "<b>This will fully remove the userbot: stop service, delete systemd unit and ~/Feroku.</b>",
        "nuke": "Remove userbot",
        "nuking": "<b>Removing userbot...</b>",
        "dlmall_no_repo": "<b>Add at least one modules repository:</b> <code>.cfg Installer modules_repo &lt;url&gt;</code>",
        "dlmall_start": "<b>Installing all modules from</b> <code>{}</code>",
        "dlmall_failed": "<b>Installed {} of {} modules.</b>\nFailed:\n<blockquote expandable>{}</blockquote>",
        "dlmall_done": "<b>Installed {} modules.</b>",
        "repositories": "<b>Select a modules repository</b>\n<blockquote>Repositories: {}</blockquote>",
        "repository_modules": "<b>Modules in</b> <code>{}</code>\n<blockquote>Total modules: {}</blockquote>",
        "repository_failed": "<b>Could not read modules from</b> <code>{}</code>",
        "install_all": "Install all",
        "refresh_modules": "Refresh",
        "install_module_confirm": "<b>Install module</b> <code>{}</code><b>?</b>",
        "install_module": "Install",
        "back": "Back",
        "close": "Close",
        "overwrite_module": "<b>This module attempted to override the core one (</b><code>{}</code><b>)</b>\n\n<i> Don't report it as bug. It's a security measure to prevent replacing core modules with some junk</i>",
        "overwrite_command": "<b>This module attempted to override the core command (</b><code>{}{}</code><b>)</b>\n\n<i> Don't report it as bug. It's a security measure to prevent replacing core modules' commands with some junk</i>",
    }

    def __init__(self):
        self.fully_loaded = False
        self._repo_modules_cache = {}

        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "modules_repo",
                [],
                lambda: "Base URLs of modules repositories with full.txt",
                validator=loader.validators.Series(loader.validators.String()),
            ),
        )

    async def client_ready(self):
        while not (settings := self.lookup("settings")):
            await asyncio.sleep(0.5)

        self.allmodules.add_aliases(settings.get("aliases", {}))

        main.feroku.ready.set()

        asyncio.ensure_future(self._update_modules())

    @loader.loop(interval=3, wait_before=True, autostart=True)
    async def _config_autosaver(self):
        for mod in self.allmodules.modules:
            if (
                not hasattr(mod, "config")
                or not mod.config
                or not isinstance(mod.config, loader.ModuleConfig)
            ):
                continue

            for option, config in mod.config._config.items():
                if not hasattr(config, "_save_marker"):
                    continue

                delattr(mod.config._config[option], "_save_marker")
                mod.pointer("__config__", {})[option] = config.value

        for lib in self.allmodules.libraries:
            if (
                not hasattr(lib, "config")
                or not lib.config
                or not isinstance(lib.config, loader.ModuleConfig)
            ):
                continue

            for option, config in lib.config._config.items():
                if not hasattr(config, "_save_marker"):
                    continue

                delattr(lib.config._config[option], "_save_marker")
                lib._lib_pointer("__config__", {})[option] = config.value

        self._db.save()

    def _repositories(self) -> list[str]:
        configured = self.config["modules_repo"]
        if isinstance(configured, str):
            configured = [configured]
        if not isinstance(configured, (list, tuple, set)):
            return []

        repositories = []
        for value in configured:
            repo = utils.normalize_git_url(str(value)).rstrip("/")
            if repo.endswith("/full.txt"):
                repo = repo[:-9]
            if utils.check_url(repo) and repo not in repositories:
                repositories.append(repo)
        return repositories

    @staticmethod
    def _looks_like_url(value: str) -> bool:
        value = value.strip().lower()
        return value.startswith(
            ("https://", "github.com/", "raw.githubusercontent.com/")
        )

    @staticmethod
    def _repo_label(repo: str) -> str:
        parsed = urlparse(repo)
        parts = [unquote(part) for part in parsed.path.split("/") if part]
        if parsed.netloc == "raw.githubusercontent.com" and len(parts) >= 3:
            label = "/".join(parts[:3])
        elif parsed.netloc == "github.com" and len(parts) >= 2:
            owner, name = parts[:2]
            branch = "main"
            if len(parts) >= 4 and parts[2] in {"tree", "blob", "raw"}:
                branch = parts[3]
            elif len(parts) >= 3:
                branch = parts[2]
            label = f"{owner}/{name}/{branch}"
        else:
            label = "/".join([parsed.netloc, *parts]).strip("/")
        return label[:64] or repo[:64]

    @staticmethod
    def _module_entry(repo: str, value: str) -> dict[str, str] | None:
        value = value.strip()
        if not value or value.startswith("#"):
            return None

        if Installer._looks_like_url(value):
            url = utils.normalize_git_url(value)
            name = Path(unquote(urlparse(url).path)).stem
        else:
            relative = value.lstrip("/")
            if not relative.lower().endswith(".py"):
                relative += ".py"
            url = f"{repo.rstrip('/')}/{relative}"
            name = Path(relative).stem

        if not utils.check_url(url) or not name:
            return None
        return {"name": name, "url": url}

    async def _download_text(self, url: str) -> str:
        response = await utils.run_sync(
            requests.get,
            url,
            timeout=30,
            allow_redirects=True,
        )
        response.raise_for_status()
        if not isinstance(response.text, str):
            raise ValueError("Response is not text")
        return response.text

    async def _get_repo_modules(
        self,
        repo: str,
        force: bool = False,
    ) -> list[dict[str, str]]:
        cache = getattr(self, "_repo_modules_cache", None)
        if not isinstance(cache, dict):
            cache = {}
            self._repo_modules_cache = cache
        if repo in cache and not force:
            return cache[repo]

        source = await self._download_text(f"{repo.rstrip('/')}/full.txt")
        modules = []
        seen = set()
        for line in source.splitlines():
            entry = self._module_entry(repo, line)
            if not entry or entry["name"].lower() in seen:
                continue
            seen.add(entry["name"].lower())
            modules.append(entry)
        modules.sort(key=lambda item: item["name"].lower())
        cache[repo] = modules
        return modules

    @staticmethod
    def _page(value: int, total: int, size: int) -> tuple[int, int]:
        pages = max(1, (total + size - 1) // size)
        return min(max(value, 0), pages - 1), pages

    def _repositories_markup(self, page: int) -> tuple[str, list]:
        repositories = self._repositories()
        page, pages = self._page(page, len(repositories), 3)
        markup = [
            [
                {
                    "text": self._repo_label(repo),
                    "callback": self._inline__open_repository,
                    "args": (repo, 0, False),
                }
            ]
            for repo in repositories[page * 3 : (page + 1) * 3]
        ]
        if len(repositories) > 3:
            row = []
            if page > 0:
                row.append(
                    {
                        "text": "←",
                        "callback": self._inline__repositories,
                        "args": (page - 1,),
                        "style": "primary",
                    }
                )
            row.append(
                {
                    "text": f"{page + 1}/{pages}",
                    "callback": self._inline__repositories,
                    "args": (page,),
                }
            )
            if page < pages - 1:
                row.append(
                    {
                        "text": "→",
                        "callback": self._inline__repositories,
                        "args": (page + 1,),
                        "style": "primary",
                    }
                )
            markup.append(row)
        markup.append(
            [
                {
                    "text": self.strings["close"],
                    "action": "close",
                    "style": "primary",
                }
            ]
        )
        text = self.strings["repositories"].format(len(repositories))
        return text, markup

    async def _inline__repositories(self, call: InlineCall, page: int = 0):
        text, markup = self._repositories_markup(page)
        await call.edit(text, reply_markup=markup)

    def _modules_markup(
        self,
        repo: str,
        modules: list[dict[str, str]],
        page: int,
    ) -> tuple[str, list]:
        page, pages = self._page(page, len(modules), 5)
        markup = [
            [
                {
                    "text": module["name"][:64],
                    "callback": self._inline__confirm_module,
                    "args": (repo, module["name"], module["url"], page),
                }
            ]
            for module in modules[page * 5 : (page + 1) * 5]
        ]
        if len(modules) > 5:
            row = []
            if page > 0:
                row.append(
                    {
                        "text": "←",
                        "callback": self._inline__open_repository,
                        "args": (repo, page - 1, False),
                        "style": "primary",
                    }
                )
            row.append(
                {
                    "text": f"{page + 1}/{pages}",
                    "callback": self._inline__open_repository,
                    "args": (repo, page, False),
                }
            )
            if page < pages - 1:
                row.append(
                    {
                        "text": "→",
                        "callback": self._inline__open_repository,
                        "args": (repo, page + 1, False),
                        "style": "primary",
                    }
                )
            markup.append(row)
        markup.extend(
            [
                [
                    {
                        "text": self.strings["install_all"],
                        "callback": self._inline__install_all,
                        "args": (repo,),
                        "style": "success",
                    },
                    {
                        "text": self.strings["refresh_modules"],
                        "callback": self._inline__open_repository,
                        "args": (repo, page, True),
                    },
                ],
                [
                    {
                        "text": self.strings["back"],
                        "callback": self._inline__repositories,
                        "args": (self._repositories().index(repo) // 3,),
                        "style": "primary",
                    },
                    {
                        "text": self.strings["close"],
                        "action": "close",
                        "style": "primary",
                    },
                ],
            ]
        )
        text = self.strings["repository_modules"].format(
            utils.escape_html(self._repo_label(repo)),
            len(modules),
        )
        return text, markup

    async def _inline__open_repository(
        self,
        call: InlineCall,
        repo: str,
        page: int = 0,
        force: bool = False,
    ):
        try:
            modules = await self._get_repo_modules(repo, force=force)
        except Exception as error:
            logger.warning("Failed to fetch full.txt from %s: %s", repo, error)
            await call.edit(
                self.strings["repository_failed"].format(
                    utils.escape_html(self._repo_label(repo))
                ),
                reply_markup=[
                    [
                        {
                            "text": self.strings["back"],
                            "callback": self._inline__repositories,
                            "args": (0,),
                            "style": "primary",
                        }
                    ]
                ],
            )
            return

        text, markup = self._modules_markup(repo, modules, page)
        await call.edit(text, reply_markup=markup)

    async def _inline__confirm_module(
        self,
        call: InlineCall,
        repo: str,
        name: str,
        url: str,
        page: int,
    ):
        await call.edit(
            self.strings["install_module_confirm"].format(utils.escape_html(name)),
            reply_markup=[
                [
                    {
                        "text": self.strings["install_module"],
                        "callback": self._inline__install_module,
                        "args": (name, url),
                        "style": "success",
                    },
                    {
                        "text": self.strings["back"],
                        "callback": self._inline__open_repository,
                        "args": (repo, page, False),
                        "style": "primary",
                    },
                ]
            ],
        )

    async def _inline__install_module(
        self,
        call: InlineCall,
        name: str,
        url: str,
    ):
        await call.edit(self.strings["installing"].format(utils.escape_html(name)))
        try:
            source = await self._download_text(url)
        except Exception as error:
            logger.warning("Failed to download module from %s: %s", url, error)
            await call.edit(self.strings["no_module"])
            return
        await self.load_module(source, call, origin=url, save_fs=True)

    async def _inline__install_all(self, call: InlineCall, repo: str):
        try:
            modules = await self._get_repo_modules(repo)
        except Exception as error:
            logger.warning("Failed to fetch full.txt from %s: %s", repo, error)
            await call.edit(self.strings["no_module"])
            return

        await call.edit(self.strings["dlmall_start"].format(self._repo_label(repo)))
        failed = []
        for module in modules:
            try:
                source = await self._download_text(module["url"])
                if not await self.load_module(
                    source,
                    call,
                    origin=module["url"],
                    save_fs=True,
                ):
                    failed.append(module["name"])
            except Exception as error:
                logger.warning("dlmall: failed %s: %s", module["url"], error)
                failed.append(module["name"])

        installed = len(modules) - len(failed)
        if installed == 0:
            text = self.strings["no_module"]
        elif failed:
            text = self.strings["dlmall_failed"].format(
                installed,
                len(modules),
                "\n".join(map(utils.escape_html, failed)),
            )
        else:
            text = self.strings["dlmall_done"].format(installed)
        await call.edit(
            text,
            reply_markup=[
                [
                    {
                        "text": self.strings["close"],
                        "action": "close",
                        "style": "primary",
                    }
                ]
            ],
        )

    @loader.command()
    async def dlm(self, message: Message):
        args = utils.get_args_raw(message).strip()
        repositories = self._repositories()

        if not args:
            if not repositories:
                await utils.answer(message, self.strings["dlmall_no_repo"])
                return
            text, markup = self._repositories_markup(0)
            await self.inline.form(
                text,
                message=message,
                reply_markup=markup,
                silent=True,
            )
            return

        if self._looks_like_url(args):
            url = utils.normalize_git_url(args)
            if not utils.check_url(url):
                await utils.answer(message, self.strings["no_module"])
                return
            await utils.answer(
                message,
                self.strings["installing"].format(utils.escape_html(url)),
            )
            try:
                source = await self._download_text(url)
            except Exception as error:
                logger.warning("Failed to download module from %s: %s", url, error)
                await utils.answer(message, self.strings["no_module"])
                return
            await self.load_module(source, message, origin=url, save_fs=True)
            return

        target = args.removesuffix(".py").lower()
        for repo in repositories:
            try:
                modules = await self._get_repo_modules(repo)
            except Exception as error:
                logger.warning("Failed to fetch full.txt from %s: %s", repo, error)
                continue
            module = next(
                (item for item in modules if item["name"].lower() == target),
                None,
            )
            if not module:
                continue
            await utils.answer(
                message,
                self.strings["installing"].format(
                    utils.escape_html(module["name"])
                ),
            )
            try:
                source = await self._download_text(module["url"])
            except Exception as error:
                logger.warning(
                    "Failed to download module from %s: %s",
                    module["url"],
                    error,
                )
                await utils.answer(message, self.strings["no_module"])
                return
            await self.load_module(
                source,
                message,
                origin=module["url"],
                save_fs=True,
            )
            return

        await utils.answer(message, self.strings["no_module"])

    @loader.command()
    async def lm(self, message: Message):
        msg = message if message.file else (await message.get_reply_message())

        if msg is None or msg.media is None:
            await utils.answer(message, self.strings["provide_module"])
            return

        await utils.answer(message, self.strings["loading_module_via_file"])

        doc = await msg.download_media(bytes)

        try:
            doc = doc.decode()
        except UnicodeDecodeError:
            await utils.answer(message, self.strings["bad_unicode"])
            return

        await self.load_module(doc, message, save_fs=True)


    async def load_module(
        self,
        doc: str,
        message: Message,
        name: str | None = None,
        origin: str = "<string>",
        save_fs: bool = True,
        _raise_install_errors: bool = False,
    ) -> bool:
        module_label = name or origin

        if any(
            line.replace(" ", "") == "#scope:ffmpeg" for line in doc.splitlines()
        ) and os.system("ffmpeg -version 1>/dev/null 2>/dev/null"):
            logger.error(
                "Module %s requires ffmpeg, but ffmpeg is not installed",
                module_label,
            )
            if isinstance(message, Message):
                await utils.answer(message, self.strings["ffmpeg_required"])
            return False

        if (
            any(line.replace(" ", "") == "#scope:inline" for line in doc.splitlines())
            and not self.inline.init_complete
        ):
            logger.error(
                "Module %s requires inline mode, but inline initialization failed",
                module_label,
            )
            if isinstance(message, Message):
                await utils.answer(message, self.strings["inline_init_failed"])
            return False

        minimum = re.search(
            r"# ?scope: ?feroku_min ((?:\d+\.){2}\d+)", doc
        ) or match_legacy_minimum(doc)
        if minimum:
            ver = minimum.group(1)
            ver_ = tuple(map(int, ver.split(".")))
            if main.__version__ < ver_:
                logger.error(
                    "Module %s requires Feroku %s, current version is %s",
                    module_label,
                    ver,
                    ".".join(map(str, main.__version__)),
                )
                if isinstance(message, Message):
                    await utils.answer(
                        message, self.strings["version_incompatible"].format(ver)
                    )
                return False

        developer = re.search(r"# ?meta developer: ?(.+)", doc)
        developer = developer.group(1) if developer else False
        banner = re.search(r"# ?meta banner: ?(.+)", doc)
        banner = banner.group(1).strip() if banner else None
        banner_kwargs = (
            {
                "file": InputMediaWebPage(banner, optional=True),
                "invert_media": True,
            }
            if banner and utils.check_url(banner)
            else {}
        )

        if name is None:
            try:
                node = ast.parse(doc)
                uid = next(
                    n.name
                    for n in node.body
                    if isinstance(n, ast.ClassDef)
                    and any(
                        isinstance(base, (ast.Attribute, ast.Name))
                        and ast.unparse(base).split(".")[-1] == "Module"
                        for base in n.bases
                    )
                )
            except Exception:
                uid = "__extmod_" + str(uuid.uuid4())
        else:

            uid = name.replace("%", "%%").replace(".", "%d")

        module_name = f"feroku.Modules.{uid}"

        async def core_overwrite(e: CoreOverwriteError):

            with contextlib.suppress(Exception):
                self.allmodules.modules.remove(instance)

            if not message:
                return

            await utils.answer(
                message,
                self.strings[f"overwrite_{e.type}"].format(
                    *(
                        (e.target,)
                        if e.type == "module"
                        else (utils.escape_html(self.get_prefix()), e.target)
                    )
                ),
            )

        try:
            try:
                spec = ModuleSpec(
                    module_name,
                    loader.StringLoader(doc, f"<external {module_name}>"),
                    origin=f"<external {module_name}>",
                )
                instance = await self.allmodules.register_module(
                    spec,
                    module_name,
                    origin,
                    save_fs=save_fs,
                )
            except ImportError as e:
                logger.error(
                    "Module %s failed to load, missing dependency: %s",
                    module_label,
                    getattr(e, "name", e),
                )
                if message is not None:
                    await utils.answer(message, self.strings["requirements_failed"])

                return False
            except CoreOverwriteError as e:
                logger.error(
                    "Module %s tried to overwrite core %s %s",
                    module_label,
                    e.type,
                    e.target,
                )
                await core_overwrite(e)
                return False
            except loader.LoadError as e:
                logger.error("Module %s failed security checks: %s", module_label, e)
                with contextlib.suppress(Exception):
                    await self.allmodules.unload_module(instance.__class__.__name__)

                with contextlib.suppress(Exception):
                    self.allmodules.modules.remove(instance)

                if message:
                    if isinstance(e, loader.LoadError):
                        await utils.answer(
                            message,
                            (
                                ""
                                f" <b>{utils.escape_html(str(e))}</b>"
                            ),
                        )
                return False
        except Exception as e:
            logger.exception("Loading external module failed due to %s", e)

            if message is not None:
                await utils.answer(message, self.strings["load_failed"])

            return False

        try:
            try:
                self.allmodules.send_config_one(instance)

                await self.allmodules.send_ready_one(
                    instance,
                    no_self_unload=True,
                    from_dlmod=bool(message),
                )
            except CoreOverwriteError as e:
                logger.error(
                    "Module %s tried to overwrite core %s %s during ready stage",
                    module_label,
                    e.type,
                    e.target,
                )
                await core_overwrite(e)
                return False
            except loader.LoadError as e:
                logger.error(
                    "Module %s failed during ready security checks: %s",
                    module_label,
                    e,
                )
                with contextlib.suppress(Exception):
                    await self.allmodules.unload_module(instance.__class__.__name__)

                with contextlib.suppress(Exception):
                    self.allmodules.modules.remove(instance)

                if message:
                    if isinstance(e, loader.LoadError):
                        await utils.answer(
                            message,
                            (
                                ""
                                f" <b>{utils.escape_html(str(e))}</b>"
                            ),
                        )
                return False
            except loader.SelfUnload as e:
                logger.warning(
                    "Module %s unloaded itself during installation: %s",
                    module_label,
                    e,
                )
                with contextlib.suppress(Exception):
                    await self.allmodules.unload_module(instance.__class__.__name__)

                with contextlib.suppress(Exception):
                    self.allmodules.modules.remove(instance)

                if message:
                    await utils.answer(
                        message,
                        (
                            ""
                            f" <b>{utils.escape_html(str(e))}</b>"
                        ),
                    )
                return False
            except loader.SelfSuspend as e:
                logger.warning(
                    "Module %s suspended itself during installation: %s",
                    module_label,
                    e,
                )
                if message:
                    await utils.answer(
                        message,
                        (
                            " <b>Module suspended itself\nReason:"
                            f" {utils.escape_html(str(e))}</b>"
                        ),
                    )
                return False
        except Exception as e:
            logger.exception("Module threw because of %s", e)

            if message is not None:
                await utils.answer(message, self.strings["load_failed"])

            return False

        instance.feroku_meta_pic = next(
            (
                line.replace(" ", "").split("#metapic:", maxsplit=1)[1]
                for line in doc.splitlines()
                if line.replace(" ", "").startswith("#metapic:")
            ),
            None,
        )

        for alias, cmd in self.lookup("settings").get("aliases", {}).items():
            _cmd = cmd.split(maxsplit=1)
            if _cmd[0] in instance.commands:
                self.allmodules.add_alias(alias, *_cmd)

        try:
            modname = instance.strings("name")
        except (KeyError, AttributeError):
            modname = getattr(instance, "name", instance.__class__.__name__)

        if message is None:
            return True

        modhelp = []
        mod_doc = ""

        if instance.__doc__:
            mod_doc = f"<i>{utils.escape_html(inspect.getdoc(instance))}</i>"

        depends_from = []
        for key in dir(instance):
            value = getattr(instance, key)
            if isinstance(value, loader.Library):
                depends_from.append(
                    ""
                    " <code>{}</code> <b>{}</b> <code>{}</code>".format(
                        value.__class__.__name__,
                        self.strings["by"],
                        (
                            value.developer
                            if isinstance(getattr(value, "developer", None), str)
                            else "Unknown"
                        ),
                    )
                )
        placeholders = utils.help_placeholders(
            getattr(getattr(instance, "__class__"), "__name__"), self
        )

        depends_from = (
            self.strings["depends_from"].format("\n".join(depends_from))
            if depends_from
            else ""
        )

        if developer:
            developer = self.strings["developer"].format(utils.escape_html(developer))
        else:
            developer = ""

        def loaded_msg():
            sections = [self.strings["loaded"].format(modname.strip())]
            if mod_doc:
                sections.append(mod_doc)
            if modhelp:
                sections.append(
                    "<blockquote expandable>{}</blockquote>".format(
                        "\n".join(modhelp)
                    )
                )
            if placeholders:
                sections.append(
                    "<blockquote expandable>{}</blockquote>".format(
                        "\n".join(placeholders)
                    )
                )
            if developer:
                sections.append(developer)
            if depends_from:
                sections.append(depends_from)
            return re.sub(r"\n{2,}", "\n", "\n".join(sections)).strip()

        if any(
            line.replace(" ", "") == "#scope:disable_onload_docs"
            for line in doc.splitlines()
        ):
            await utils.answer(message, loaded_msg(), **banner_kwargs)
            return True

        help_module = self.lookup("help")
        command_emoji = (
            help_module.config["command_emoji"]
            if help_module and hasattr(help_module, "config")
            else "→"
        )

        for _name, fun in sorted(
            instance.commands.items(),
            key=lambda x: x[0],
        ):
            modhelp.append(
                "{} <code>{}{}</code> {}".format(
                    command_emoji,
                    utils.escape_html(self.get_prefix()),
                    _name,
                    (
                        utils.escape_html(inspect.getdoc(fun))
                        if fun.__doc__
                        else self.strings["undoc"]
                    ),
                )
            )

        if self.inline.init_complete:
            for _name, fun in sorted(
                instance.inline_handlers.items(),
                key=lambda x: x[0],
            ):
                modhelp.append(
                    self.strings["ihandler"].format(
                        f"@{self.inline.bot_username} {_name}",
                        (
                            utils.escape_html(inspect.getdoc(fun))
                            if fun.__doc__
                            else self.strings["undoc"]
                        ),
                    )
                )

        try:
            await utils.answer(message, loaded_msg(), **banner_kwargs)
        except MediaCaptionTooLongError:
            if hasattr(message, "reply"):
                await message.reply(loaded_msg(), **banner_kwargs)
            else:
                await message.edit(loaded_msg(), **banner_kwargs)

        return True

    @loader.command()
    async def ulm(self, message: Message):
        if not (raw_args := utils.get_args_raw(message)):
            await utils.answer(message, self.strings["no_class"])
            return

        args = raw_args
        force = False
        first_line = args.split("\n", 1)[0].strip()
        if first_line == "-f":
            force = True
            rest = args.split("\n", 1)
            args = rest[1].strip() if len(rest) > 1 else ""
        elif args.startswith("-f "):
            force = True
            args = args[3:].strip()

        if not args:
            await utils.answer(message, self.strings["no_class"])
            return

        raw_list = re.split(r"[,\n]", args)
        modules = [m.strip() for m in raw_list if m.strip()]

        if len(modules) == 1:
            if not self.lookup(modules[0]):
                suggestions = self._get_unload_suggestions(modules[0])
                if suggestions:
                    await self.inline.form(
                        self.strings["unload_suggestions"].format(
                            utils.escape_html(modules[0])
                        ),
                        message=message,
                        reply_markup=[
                            [
                                {
                                    "text": label,
                                    "callback": self._inline__unload_suggested, "style": "primary",
                                    "args": (classname, force),
                                }
                            ]
                            for classname, label in suggestions
                        ]
                        + [
                            [
                                {
                                    "text": self.strings["cancel"].replace("", ""),
                                    "action": "close", "style": "primary",
                                }
                            ]
                        ],
                        silent=True,
                    )
                    return

            msg = await self.unload_module(modules[0], force=force)
        else:
            success = []
            errors = []
            msg = ""
            for module in modules:
                status = await self.unload_module(module)
                if "" in status or "" in status or "" in status:
                    if "" in status:
                        status = status.split("<code>")[0]

                    errors.append(f"<code>{module}</code>: {status}")
                else:
                    success.append(f"<code>{module}</code>")

            if success:
                msg += self.strings["modules_unloaded"].format(
                    unloaded_num=len(success), unloaded=", ".join(success)
                )
            if errors:
                msg += "\n" + self.strings["modules_not_unloaded"].format(
                    not_unloaded=len(errors),
                    errors="\n".join(errors),
                )

        await utils.answer(message, msg)

    def _get_unload_suggestions(
        self,
        query: str,
        limit: int = 3,
    ) -> list[tuple[str, str]]:
        query = query.lower()
        scored = []

        for module in self.allmodules.modules:
            if self._is_core_module(module):
                continue

            classname = module.__class__.__name__
            public_name = str(getattr(module, "name", "") or module.strings["name"])
            names = {
                classname,
                classname[:-3] if classname.endswith("Mod") else classname,
                public_name,
            }
            score = max(
                difflib.SequenceMatcher(None, query, name.lower()).ratio()
                for name in names
                if name
            )
            label = public_name
            scored.append((score, classname.lower(), classname, label))

        return [
            (classname, label)
            for _, _, classname, label in sorted(scored, reverse=True)[:limit]
        ]

    def _is_core_module(self, module) -> bool:
        module_name = getattr(module.__class__, "__module__", "")
        if not module_name.startswith("feroku.Modules."):
            return False

        module_file = module_name.rsplit(".", 1)[-1]
        return os.path.isfile(
            os.path.join(utils.get_base_dir(), "Modules", f"{module_file}.py")
        )

    async def _inline__unload_suggested(
        self,
        call: InlineCall,
        module: str,
        force: bool = False,
    ):
        await call.edit(await self.unload_module(module, force=force))

    async def unload_module(self, module: str, force: bool = False) -> str:
        instance = self.lookup(module)

        if instance and self._is_core_module(instance):
            return self.strings["unload_core"].format(module)

        if instance and issubclass(instance.__class__, loader.Library):
            return self.strings["cannot_unload_lib"]

        try:
            worked = await self.allmodules.unload_module(module)
        except CoreUnloadError:
            return self.strings["unload_core"].format(module)

        msg = (
            self.strings["unloaded"].format(
                "",
                ", ".join(
                    [(mod[:-3] if mod.endswith("Mod") else mod) for mod in worked]
                ),
            )
            if worked
            else self.strings["not_unloaded"]
        )
        for mod_name in worked:
            utils.unregister_placeholders(mod_name)

        if force and worked:
            try:
                for key in list(self._db.keys()):
                    if not isinstance(key, str):
                        continue
                    low = key.lower()
                    for mod_name in worked:
                        base = mod_name[:-3] if mod_name.endswith("Mod") else mod_name
                        candidates = {mod_name.lower(), base.lower()}
                        if any(
                            low == c
                            or low.startswith(c + ".")
                            or low.startswith(c + "_")
                            or c in low
                            for c in candidates
                        ):
                            try:
                                del self._db[key]
                            except Exception:
                                pass

                try:
                    self._db.save()
                except Exception:
                    logger.debug(
                        "Failed to save DB after force-unload cleanup", exc_info=True
                    )
            except Exception:
                logger.exception("Failed to cleanup DB for force unload")

        return msg

    @loader.command()
    async def nuke(self, message: Message):
        await self.inline.form(
            self.strings["confirm_nuke"],
            message,
            reply_markup=[
                {
                    "text": self.strings["nuke"],
                    "callback": self._inline__nuke, "style": "primary",
                },
                {
                    "text": self.strings["cancel"],
                    "action": "close",
                    "style": "primary",
                },
            ],
        )

    async def _inline__nuke(self, call: InlineCall):
        await utils.answer(call, self.strings["nuking"])
        await asyncio.sleep(1)
        subprocess.Popen(
            ["bash", str(Path(__file__).resolve().parent.parent.parent / "Storage" / "Nuke.sh")],
            start_new_session=True,
        )

    async def _update_modules(self):
        self._secure_boot = False

        if self._db.get(loader.__name__, "secure_boot", False):
            self._db.set(loader.__name__, "secure_boot", False)
            self._secure_boot = True
        else:
            aliases = {
                alias: cmd
                for alias, cmd in self.lookup("settings").get("aliases", {}).items()
                if self.allmodules.add_alias(alias, *cmd.split(maxsplit=1))
            }

            self.lookup("settings").set("aliases", aliases)

        self.fully_loaded = True

    async def reload_core(self) -> int:
        self.fully_loaded = False

        if self._secure_boot:
            self._db.set(loader.__name__, "secure_boot", True)

        if not self._db.get(main.__name__, "remove_core_protection", False):
            for module in self.allmodules.modules:
                if module.__origin__.startswith("<core"):
                    module.__origin__ = "<reload-core>"

        loaded = await self.allmodules.register_all(no_external=True)
        for instance in loaded:
            self.allmodules.send_config_one(instance)
            await self.allmodules.send_ready_one(
                instance,
                no_self_unload=False,
                from_dlmod=False,
            )

        self.fully_loaded = True
        return len(loaded)

    @loader.command()
    async def ml(self, message: Message):
        if not (args := utils.get_args_raw(message)):
            await utils.answer(message, self.strings["args"])
            return

        await utils.answer(message, self.strings["ml_load_module"])

        exact = True
        if not (
            class_name := next(
                (
                    module.strings("name")
                    for module in self.allmodules.modules
                    if args.lower()
                    in {
                        module.strings("name").lower(),
                        module.__class__.__name__.lower(),
                    }
                ),
                None,
            )
        ):
            if not (
                class_name := next(
                    reversed(
                        sorted(
                            [
                                module.strings["name"].lower()
                                for module in self.allmodules.modules
                            ]
                            + [
                                module.__class__.__name__.lower()
                                for module in self.allmodules.modules
                            ],
                            key=lambda x: difflib.SequenceMatcher(
                                None,
                                args.lower(),
                                x,
                            ).ratio(),
                        )
                    ),
                    None,
                )
            ):
                await utils.answer(message, self.strings["404"])
                return

            exact = False

        try:
            module = self.lookup(class_name)
            sys_module = inspect.getmodule(module)
        except Exception:
            await utils.answer(message, self.strings["404"])
            return

        module_data = sys_module.__loader__.data
        if isinstance(module_data, str):
            module_data = module_data.encode("utf-8")

        module_doc = (
            module_data.decode("utf-8", errors="ignore")
            if isinstance(module_data, (bytes, bytearray))
            else str(module_data)
        )

        if any(
            line.replace(" ", "") == "#scope:no_ml" for line in module_doc.splitlines()
        ):
            await utils.answer(
                message,
                self.strings["no_ml"].format(utils.escape_html(class_name)),
            )
            return

        link = module.__origin__

        text = (
            f"<b> {utils.escape_html(class_name)}</b>"
            if not utils.check_url(link)
            else (
                f' <b><a href="{link}">Link</a> for'
                f" {utils.escape_html(class_name)}:</b>"
                f' <code>{link}</code>\n\n{self.strings["not_exact"] if not exact else ""}'
            )
        )

        text = (
            self.strings["link"].format(
                class_name=utils.escape_html(class_name),
                url=link,
                not_exact=self.strings["not_exact"] if not exact else "",
                prefix=utils.escape_html(self.get_prefix()),
            )
            if utils.check_url(link)
            else self.strings["file"].format(
                class_name=utils.escape_html(class_name),
                not_exact=self.strings["not_exact"] if not exact else "",
                prefix=utils.escape_html(self.get_prefix()),
            )
        )

        file = io.BytesIO(module_data)
        file.name = f"{class_name}.py"
        file.seek(0)

        await utils.answer(
            message,
            text,
            file=file,
            reply_to=getattr(message, "reply_to_msg_id", None),
        )
