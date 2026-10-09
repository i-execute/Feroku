# CopyLeft 2026 github.com/i-execute // i_execute.t.me
# Licensed under AGPLv3.

# (c) Dan Gazizullin, 2021-2023. This file is part of the Hikka Userbot: github.com/hikariatama/Hikka

import asyncio
import collections
import contextlib
import importlib
import json
import logging
import os
import random
import shutil
import signal
import sqlite3
import subprocess
import sys
import traceback
from pathlib import Path

import aiohttp

try:
    import fcntl
except ImportError:
    fcntl = None

from telethon.errors import (
    ApiIdInvalidError,
    AuthKeyDuplicatedError,
)
from telethon.errors.rpcbaseerrors import UnauthorizedError
from telethon.network.connection import (
    ConnectionTcpFull,
)
from telethon.sessions import SQLiteSession

from . import database, loader, utils, version
from ._compat import install_main_compat, migrate_legacy_sessions
from ._internal import install_task_tracking, restart
from .dispatcher import CommandDispatcher
from .tl_cache import CustomTelegramClient
from .version import __version__

BASE_DIR = (
    "/data"
    if "DOCKER" in os.environ
    else os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
)

BASE_PATH = Path(BASE_DIR)
CONFIG_PATH = BASE_PATH / "config.json"
SESSIONS_DIR = os.path.join(BASE_DIR, "sessions")
_CONFIG_CACHE: dict | None = None
_CONFIG_MTIME_NS: int | None = None

def generate_random_system_version() -> str:
    number = random.randint(11, 18)
    return random.choice(
        (
            f"iPhone {number}",
            f"iPhone {number} Pro",
            f"iPhone {number} Pro Max",
        )
    )

def run_config():
    from . import configurator

    return configurator.api_config()

def _read_config() -> dict:
    global _CONFIG_CACHE, _CONFIG_MTIME_NS

    try:
        stat = CONFIG_PATH.stat()
    except FileNotFoundError:
        _CONFIG_CACHE = {}
        _CONFIG_MTIME_NS = None
        return {}

    if _CONFIG_CACHE is not None and _CONFIG_MTIME_NS == stat.st_mtime_ns:
        return _CONFIG_CACHE

    try:
        _CONFIG_CACHE = json.loads(CONFIG_PATH.read_text())
    except json.decoder.JSONDecodeError:
        logging.warning("config.json is corrupted, resetting")
        _CONFIG_CACHE = {}
    _CONFIG_MTIME_NS = stat.st_mtime_ns
    return _CONFIG_CACHE

def get_config_key(key: str) -> str | bool:
    try:
        return _read_config().get(key, False)
    except FileNotFoundError:
        return False

def save_config_key(key: str, value: str) -> bool:
    global _CONFIG_CACHE, _CONFIG_MTIME_NS

    try:

        config = _read_config().copy()
    except FileNotFoundError:

        config = {}

    config[key] = value

    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(config, indent=4))
    os.replace(tmp, CONFIG_PATH)
    CONFIG_PATH.chmod(0o600)
    _CONFIG_CACHE = config
    _CONFIG_MTIME_NS = CONFIG_PATH.stat().st_mtime_ns
    return True

class InteractiveAuthRequired(Exception):
    pass

class Feroku:
    def __init__(self):
        self.omit_log = False
        self.proxy = None
        self.conn = ConnectionTcpFull
        try:
            self.loop = asyncio.get_running_loop()

        except RuntimeError:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)

        install_task_tracking()

        self.clients = []
        self.ready = asyncio.Event()
        self._restart_lock = asyncio.Lock()
        self._restart_requested = False
        self._shutdown_lock = asyncio.Lock()
        self._shutdown_started = False
        self._shutdown_complete = False
        self._migrate_sessions()
        self._acquire_instance_lock()
        self._read_sessions()
        self._get_api_token()

    def _migrate_sessions(self):
        os.makedirs(SESSIONS_DIR, exist_ok=True)
        migrate_legacy_sessions(BASE_DIR, SESSIONS_DIR)

        with os.scandir(BASE_DIR) as entries:
            legacy = [
                entry
                for entry in entries
                if entry.is_file()
                and entry.name.startswith("feroku-")
                and ".session" in entry.name
            ]

        for entry in legacy:
            target = os.path.join(SESSIONS_DIR, entry.name)
            if os.path.exists(target):
                continue

            try:
                shutil.move(entry.path, target)
            except OSError:
                logging.exception(
                    "Failed to migrate legacy session file %s", entry.path
                )

    def _acquire_instance_lock(self):
        lock_path = Path(SESSIONS_DIR) / ".instance.lock"
        self._instance_lock = lock_path.open("a+")
        os.set_inheritable(self._instance_lock.fileno(), False)
        if fcntl is None:
            return
        try:
            fcntl.flock(
                self._instance_lock.fileno(),
                fcntl.LOCK_EX | fcntl.LOCK_NB,
            )
        except BlockingIOError as error:
            self._instance_lock.close()
            raise RuntimeError("Another Feroku process is already running") from error

    def _release_instance_lock(self):
        if getattr(self, "_instance_lock", None) is None:
            return
        if self._instance_lock.closed:
            return
        if fcntl is not None:
            with contextlib.suppress(OSError):
                fcntl.flock(self._instance_lock.fileno(), fcntl.LOCK_UN)
        self._instance_lock.close()

    def _read_sessions(self):
        self.sessions = []
        with os.scandir(SESSIONS_DIR) as entries:
            self.sessions += [
                SQLiteSession(entry.path.rsplit(".session", maxsplit=1)[0])
                for entry in entries
                if entry.is_file()
                and entry.name.startswith("feroku-")
                and entry.name.endswith(".session")
                and "-bot-" not in entry.name
            ]

    def _get_api_token(self):
        api_token_type = collections.namedtuple("api_token", ("ID", "HASH"))

        try:

            if not get_config_key("api_id"):
                api_id, api_hash = (
                    line.strip()
                    for line in (Path(BASE_DIR) / "api_token.txt")
                    .read_text()
                    .splitlines()
                )
                save_config_key("api_id", int(api_id))
                save_config_key("api_hash", api_hash)
                (Path(BASE_DIR) / "api_token.txt").unlink()
                logging.debug("Migrated api_token.txt to config.json")

            api_token = api_token_type(
                get_config_key("api_id"),
                get_config_key("api_hash"),
            )
        except FileNotFoundError:
            try:
                from . import api_token
            except ImportError:
                try:
                    api_token = api_token_type(
                        os.environ["api_id"],
                        os.environ["api_hash"],
                    )
                except KeyError:
                    api_token = None

        self.api_token = api_token

    async def _get_token(self):
        while self.api_token is None:
            run_config()
            importlib.invalidate_caches()
            self._get_api_token()

    @staticmethod
    def _token_shape_valid(token: str) -> bool:
        if not isinstance(token, str) or ":" not in token:
            return False
        bot_id, secret = token.split(":", 1)
        return bot_id.isdigit() and len(secret) >= 20

    async def _check_bot_token(self, token: str) -> str:
        if not self._token_shape_valid(token):
            return "invalid"
        timeout = aiohttp.ClientTimeout(total=20)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(
                    f"https://api.telegram.org/bot{token}/getMe"
                ) as response:
                    payload = await response.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as error:
            logging.error(
                "Bot token validation request failed: %s",
                type(error).__name__,
            )
            return "network"
        if not isinstance(payload, dict) or not payload.get("ok"):
            error_code = payload.get("error_code") if isinstance(payload, dict) else None
            return "invalid" if error_code in {401, 404} else "network"
        bot = payload.get("result")
        if not isinstance(bot, dict) or not bot.get("is_bot"):
            return "invalid"
        if bot.get("supports_inline_queries") is not True:
            return "inline"
        return "ok"

    @staticmethod
    async def _terminal_input(prompt: str = "") -> str | None:
        try:
            return await asyncio.to_thread(input, prompt)
        except EOFError:
            return None

    async def _get_bot_token(self):
        token = get_config_key("bot_token") or ""
        while True:
            if not token:
                entered = await self._terminal_input("Bot token: ")
                if entered is None:
                    logging.error(
                        "Bot token is missing. Stop the service and run Feroku from a terminal to enter it."
                    )
                    await asyncio.Event().wait()
                token = entered.strip()
            status = await self._check_bot_token(token)
            if status == "ok":
                save_config_key("bot_token", token)
                return
            if status == "inline":
                print("Inline mode is disabled for this bot.")
                entered = await self._terminal_input(
                    "Enable inline mode in @BotFather and press Enter to retry: "
                )
                if entered is None:
                    logging.error(
                        "Inline mode must be enabled before starting the service."
                    )
                    await asyncio.Event().wait()
                continue
            if status == "network":
                print("Could not validate the bot token. Check the connection.")
                entered = await self._terminal_input(
                    "Press Enter to retry or close the terminal to retry in 60 seconds: "
                )
                if entered is None:
                    await asyncio.sleep(60)
                continue
            print("Invalid bot token.")
            save_config_key("bot_token", "")
            token = ""

    async def save_client_session(
        self,
        client: CustomTelegramClient,
        *,
        delay_restart: bool = False,
    ):
        if hasattr(client, "tg_id"):
            telegram_id = client.tg_id
        else:
            if not (me := await client.get_me()):
                raise RuntimeError("Attempted to save non-inited session")

            telegram_id = me.id
            client._tg_id = telegram_id
            client.tg_id = telegram_id
            client.feroku_me = me
            client.feroku_me = me

        session = SQLiteSession(
            os.path.join(
                SESSIONS_DIR,
                f"feroku-{telegram_id}",
            )
        )

        session.set_dc(
            client.session.dc_id,
            client.session.server_address,
            client.session.port,
        )

        session.auth_key = client.session.auth_key

        session.save()

        if not delay_restart:
            await client.disconnect()
            restart()

        client.session = session
        client.feroku_db = database.Database(client)
        await client.feroku_db.init()

        if delay_restart:
            await client.disconnect()
            await asyncio.sleep(3600)

    async def _activate_restored_session(self) -> bool:
        self.clients.clear()
        self._read_sessions()
        if not self.sessions:
            logging.error("Session recovery completed without creating a session file")
            return False
        try:
            connected = await self._init_clients()
        except Exception:
            logging.exception("The restored session failed during connection")
            connected = False
        if not connected:
            await self._disconnect_clients()
            self.clients.clear()
            logging.error("The restored session could not be connected")
            return False
        return True

    @staticmethod
    def _systemd_quote(value: str) -> str:
        escaped = (
            value.replace("\\", "\\\\").replace('"', '\\"')
        )
        return f'"{escaped}"'

    @staticmethod
    def _daemon_command(command: list[str], env=None, timeout: int = 30) -> bool:
        try:
            return (
                subprocess.run(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=env,
                    timeout=timeout,
                    check=False,
                ).returncode
                == 0
            )
        except (OSError, subprocess.SubprocessError):
            return False

    def _start_detached_daemon(self, executable: str, repository: str) -> bool:
        try:
            with (BASE_PATH / "feroku.log").open("a") as log:
                process = subprocess.Popen(
                    [executable, "-m", "feroku"],
                    cwd=repository,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    close_fds=True,
                )
            if process.poll() is not None:
                return False
            pid_path = Path(SESSIONS_DIR) / ".daemon.pid"
            with contextlib.suppress(OSError):
                pid_path.write_text(str(process.pid))
                pid_path.chmod(0o600)
            return True
        except OSError:
            return False

    def _install_daemon(self) -> bool:
        executable = os.path.abspath(sys.executable)
        repository = str(BASE_PATH.resolve())
        is_root = hasattr(os, "geteuid") and os.geteuid() == 0
        user_unit = not is_root
        unit_dir = (
            Path("/etc/systemd/system")
            if is_root
            else Path.home() / ".config" / "systemd" / "user"
        )
        unit_path = unit_dir / "feroku.service"
        target = "default.target" if user_unit else "multi-user.target"
        unit = (
            "[Unit]\n"
            "Description=Feroku userbot\n"
            "After=network-online.target\n"
            "Wants=network-online.target\n\n"
            "[Service]\n"
            "Type=simple\n"
            f"WorkingDirectory={self._systemd_quote(repository)}\n"
            f"ExecStart={self._systemd_quote(executable)} -m feroku\n"
            "Restart=always\n"
            "RestartSec=5\n"
            "Environment=PYTHONUNBUFFERED=1\n\n"
            "[Install]\n"
            f"WantedBy={target}\n"
        )
        service_written = False
        try:
            unit_dir.mkdir(parents=True, exist_ok=True)
            unit_path.write_text(unit)
            unit_path.chmod(0o644)
            service_written = True
        except OSError:
            logging.exception("Failed to write %s", unit_path)

        env = os.environ.copy()
        linger_enabled = not user_unit
        if user_unit and hasattr(os, "getuid"):
            runtime_dir = Path("/run/user") / str(os.getuid())
            if runtime_dir.is_dir():
                env.setdefault("XDG_RUNTIME_DIR", str(runtime_dir))
                env.setdefault(
                    "DBUS_SESSION_BUS_ADDRESS",
                    f"unix:path={runtime_dir / 'bus'}",
                )
            try:
                import pwd

                username = pwd.getpwuid(os.getuid()).pw_name
                linger_enabled = self._daemon_command(
                    ["sudo", "-n", "loginctl", "enable-linger", username],
                    timeout=5,
                ) or self._daemon_command(
                    ["loginctl", "enable-linger", username],
                    timeout=5,
                )
                linger_enabled = linger_enabled or (
                    Path("/var/lib/systemd/linger") / username
                ).exists()
            except (ImportError, KeyError):
                pass

        service_ready = False
        systemctl = ["systemctl", "--user"] if user_unit else ["systemctl"]
        if service_written:
            service_ready = self._daemon_command(
                systemctl + ["daemon-reload"], env
            ) and self._daemon_command(
                systemctl + ["enable", "feroku.service"], env
            )

        self._release_instance_lock()
        if service_ready and linger_enabled and self._daemon_command(
            systemctl + ["start", "feroku.service"], env
        ):
            return True
        return self._start_detached_daemon(executable, repository)

    async def _initial_setup(self) -> bool:
        if get_config_key("setup_pending") or not get_config_key("owner_id"):
            from .qr_recovery import run_bot_setup

            setup = await run_bot_setup()
            if setup == "handoff":
                if self._install_daemon():
                    print(
                        "Setup continues in Telegram. You can disconnect from SSH now."
                    )
                else:
                    logging.error("Failed to start the Feroku daemon")
                return False
            if not setup:
                return False
            return await self._activate_restored_session()

        from .qr_recovery import send_qr_recovery

        while True:
            if not await send_qr_recovery(
                int(self.api_token.ID), self.api_token.HASH
            ):
                return False
            if await self._activate_restored_session():
                return True
            logging.error("Session activation failed; recovery will be opened again")
            await asyncio.sleep(3)

    def _discard_session(self, session: SQLiteSession):
        filename = getattr(session, "filename", None)
        with contextlib.suppress(Exception):
            session.auth_key = None
            session.save()
        with contextlib.suppress(Exception):
            session.close()
        if filename:
            for suffix in ("", "-journal", "-wal", "-shm"):
                Path(f"{filename}{suffix}").unlink(missing_ok=True)
        with contextlib.suppress(ValueError):
            self.sessions.remove(session)

    async def _init_clients(self) -> bool:
        for session in self.sessions.copy():
            client = None
            try:
                device_model = generate_random_system_version()
                client = CustomTelegramClient(
                    session,
                    self.api_token.ID,
                    self.api_token.HASH,
                    connection=self.conn,
                    proxy=self.proxy,
                    connection_retries=None,
                    device_model=device_model,
                    system_version=device_model,
                    app_version=".".join(map(str, __version__)) + " x64",
                    lang_code="en",
                    system_lang_code="en-US",
                )
                await client.connect()
                if not await client.is_user_authorized():
                    raise InteractiveAuthRequired()
                me = await client.get_me()
                if me is None:
                    raise InteractiveAuthRequired()
                client.phone = "None"
                client._tg_id = me.id
                client.tg_id = me.id
                client.feroku_me = me

                temp_db = database.Database(client)
                await temp_db.init()

                if temp_db.get("feroku.inline", "bot_token", False):
                    temp_db.set("feroku.inline", "bot_token", None)

                self.clients.append(client)
            except sqlite3.OperationalError as error:
                if client:
                    with contextlib.suppress(Exception):
                        await client.disconnect()
                logging.error(
                    "Check that this is the only instance running. "
                    "If that doesn't help, delete the file '%s'",
                    session.filename,
                )
                raise RuntimeError("User session database is locked") from error
            except (AuthKeyDuplicatedError, UnauthorizedError, InteractiveAuthRequired):
                if client:
                    with contextlib.suppress(Exception):
                        await client.disconnect()
                logging.error(
                    "Session %s is no longer valid and must be recreated",
                    session.filename,
                )
                self._discard_session(session)
            except (ValueError, ApiIdInvalidError):
                if client:
                    with contextlib.suppress(Exception):
                        await client.disconnect()
                run_config()
                return False

        return bool(self.clients)

    async def _client_authorization_state(
        self,
        client: CustomTelegramClient,
    ) -> bool | None:
        try:
            if not client.is_connected():
                await client.connect()
            if not await client.is_user_authorized():
                return False
            return await client.get_me() is not None
        except (AuthKeyDuplicatedError, UnauthorizedError):
            return False
        except Exception:
            logging.exception("Failed to verify the user session after disconnect")
            return None

    async def amain_wrapper(self, client: CustomTelegramClient):
        session_dead = False
        try:
            completed = await self.amain(True, client)
            if (
                completed
                and not self._restart_requested
                and not self._shutdown_started
            ):
                authorization = await self._client_authorization_state(client)
                if authorization is False:
                    session_dead = True
                elif authorization is True:
                    logging.warning(
                        "The user client stopped unexpectedly and will be reconnected"
                    )
                    await self.restart_runtime()
        except (AuthKeyDuplicatedError, UnauthorizedError, InteractiveAuthRequired):
            session_dead = True
        finally:
            with contextlib.suppress(Exception):
                await client.disconnect()

        if (
            session_dead
            and not self._restart_requested
            and not self._shutdown_started
        ):
            logging.error("The user session was revoked during runtime")
            self._discard_session(client.session)
            await self.restart_runtime()

    async def _badge(self, client: CustomTelegramClient):
        try:
            import git

            with git.Repo() as repo:
                build = repo.head.commit.hexsha
                diff = repo.git.log([f"HEAD..origin/{version.branch}", "--oneline"])
            upd = "Update required" if diff else "Up-to-date"
            pref = client.feroku_db.get("feroku.main", "command_prefix", None)

            if not self.omit_log:
                logging.info(
                    "Feroku %s #%s (%s)",
                    ".".join(map(str, __version__)),
                    build[:7],
                    upd,
                )
                self.omit_log = True

            try:
                handler = logging.getLogger().handlers[0]
                message_thread_id = await handler.get_logs_topic_id()
                log_chat_id = handler.mod.logchat

                await client.feroku_inline.bot.send_photo(
                    log_chat_id,
                    utils.get_asset_path("Feroku.PNG"),
                    caption=(
                        "{} <b>{} started!</b>\n\n <b>GitHub commit SHA: <a"
                        ' href="https://github.com/i-execute/Feroku/commit/{}">{}</a></b>\n'
                        " <b>Update status: {}</b>\n <b>Prefix:</b> <code>{}</code>"
                    ).format(
                        (
                            utils.get_platform_emoji()
                            if client.feroku_me.premium is True
                            else " Feroku"
                        ),
                        ".".join(list(map(str, list(__version__)))),
                        build,
                        build[:7],
                        upd,
                        "." if pref is None else pref,
                    ),
                    message_thread_id=message_thread_id,
                )
            except Exception as badge_error:
                logging.debug(f"Failed to send badge photo: {badge_error}")
            logging.debug(
                "· Started for %s · Prefix: «%s» ·",
                client.tg_id,
                client.feroku_db.get(__name__, "command_prefix", False) or ".",
            )
        except Exception:
            logging.exception("Badge error")

    async def _add_dispatcher(
        self,
        client: CustomTelegramClient,
        modules: loader.Modules,
        db: database.Database,
    ):
        dispatcher = CommandDispatcher(modules, client, db)
        client.dispatcher = dispatcher
        modules.check_security = dispatcher.check_security
        dispatcher.attach_handlers()

    async def amain(self, first: bool, client: CustomTelegramClient):
        client.parse_mode = "HTML"

        db = database.Database(client)
        client.feroku_db = db
        await db.init()
        stored_prefix = db.get(__name__, "command_prefix", ".")
        client.command_prefix = utils.normalize_prefix(stored_prefix)
        if client.command_prefix != stored_prefix:
            db.set(__name__, "command_prefix", client.command_prefix)
        logging.debug("Got DB")
        logging.debug("Loading logging config...")

        modules = loader.Modules(client, db)
        client.loader = modules

        await self._add_dispatcher(client, modules, db)

        await modules.register_all(None)
        modules.send_config()
        if not await modules.inline.register_manager():
            return False
        await db.ensure_content_channel()
        await modules.send_ready()

        if first:
            await self._badge(client)

        await client.run_until_disconnected()
        return True

    @staticmethod
    def _loop_exception_handler(_, context: dict):
        culprit = (
            context.get("task") or context.get("future") or context.get("handle")
        )
        details = f" [{culprit!r}]" if culprit is not None else ""
        source = context.get("source_traceback")

        if source:
            details += "\nTask was created at:\n" + "".join(
                traceback.format_list(source[-5:])
            ).rstrip()

        exception = context.get("exception")
        exc_info = (
            (type(exception), exception, exception.__traceback__)
            if exception is not None
            else None
        )

        logging.error(
            "Exception on event loop! %s%s",
            context.get("message", "unknown error"),
            details,
            exc_info=exc_info,
        )

    async def _main(self):
        await self._get_token()
        await self._get_bot_token()

        if self.sessions:
            await self._init_clients()
        if not self.clients and not await self._initial_setup():
            return

        self.loop.set_exception_handler(self._loop_exception_handler)
        await asyncio.gather(
            *[self.amain_wrapper(client) for client in self.clients]
        )

    async def _disconnect_clients(self):
        for client in self.clients:
            inline = getattr(getattr(client, "loader", None), "inline", None)
            if not inline:
                continue
            if inline._cleaner_task:
                inline._cleaner_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await inline._cleaner_task
            if inline._bot_client:
                with contextlib.suppress(Exception):
                    await inline._bot_client.disconnect()
        for client in self.clients:
            with contextlib.suppress(Exception):
                await client.disconnect()

    async def restart_runtime(self):
        async with self._restart_lock:
            if self._restart_requested:
                return
            self._restart_requested = True
            await self._disconnect_clients()
            restart()

    async def _shutdown_handler(self):
        self._shutdown_started = True
        async with self._shutdown_lock:
            if self._shutdown_complete:
                return
            await self._disconnect_clients()
            self._shutdown_complete = True

    def main(self):
        if hasattr(signal, "SIGHUP"):
            signal.signal(signal.SIGHUP, signal.SIG_IGN)
        if sys.platform != "win32":
            try:
                self.loop.add_signal_handler(
                    signal.SIGINT, lambda: asyncio.create_task(self._shutdown_handler())
                )
            except NotImplementedError:
                logging.warning("Signal handlers not supported on this platform.")
        else:
            logging.info("Running on Windows - skipping signal handler.")

        try:
            self.loop.run_until_complete(self._main())
        except KeyboardInterrupt:
            self.loop.run_until_complete(self._shutdown_handler())
        except Exception as e:
            logging.exception("Unexpected exception in main loop: %s", e)
        finally:
            try:
                self.loop.run_until_complete(self._shutdown_handler())
            except Exception:
                pass

feroku = Feroku()
install_main_compat(globals(), Feroku, feroku)
