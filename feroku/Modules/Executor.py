# CopyLeft 2026 github.com/i-execute // i_execute.t.me
# Licensed under AGPLv3.

# (c) Dan Gazizullin, 2021-2023. This file is part of the Hikka Userbot: github.com/hikariatama/Hikka

import asyncio
import contextlib
import itertools
import logging
import os
import random
import signal
import time
import typing
from collections.abc import Callable
from io import StringIO
from types import ModuleType

from telethon.errors.rpcerrorlist import MessageIdInvalidError, MessageNotModifiedError
from telethon.tl.types import Message
from meval import meval

from .. import loader, main, utils

logger = logging.getLogger(__name__)


async def read_stream(func: Callable, stream, delay: float):
    last_task = None
    data = b""
    while True:
        dat = await stream.read(1)
        if not dat:
            if last_task:
                last_task.cancel()
                await func(data.decode())
            break
        data += dat
        if last_task:
            last_task.cancel()
        last_task = asyncio.ensure_future(_sleep_for_task(func, data, delay))


async def _sleep_for_task(func: Callable, data: bytes, delay: float):
    await asyncio.sleep(delay)
    await func(data.decode())


def sudo_stdin_command(command: str, shell: str) -> str:
    if os.path.basename(os.path.realpath(shell)) == "fish":
        return (
            "function sudo\n"
            "    command sudo -S -p '[sudo-execution] password:' $argv\n"
            "end\n" + command
        )
    return (
        "sudo() { command sudo -S -p '[sudo-execution] password:' \"$@\"; };\n"
        + command
    )


class MessageEditor:
    def __init__(self, message, command, strings):
        self.message = message
        self.command = command
        self.stdout = ""
        self.stderr = ""
        self.rc = None
        self.strings = strings
        self.start_time = time.time()

    async def update_stdout(self, stdout):
        self.stdout = stdout
        await self.redraw()

    async def update_stderr(self, stderr):
        self.stderr = stderr
        await self.redraw()

    async def redraw(self):
        text = self.strings["running"].format(utils.escape_html(self.command))

        if self.rc is not None:
            text += self.strings["finished"].format(utils.escape_html(str(self.rc)))

        stdout = utils.escape_html(self.stdout[max(len(self.stdout) - 2048, 0):])
        stderr = utils.escape_html(self.stderr[max(len(self.stderr) - 1024, 0):])

        if stdout:
            text += self.strings["stdout"] + stdout
            if stderr:
                text += self.strings["stderr"] + stderr
            text += self.strings["end"]
        elif stderr:
            text += self.strings["stderr_only"] + stderr + self.strings["end"]

        if self.rc is not None:
            exec_time = time.time() - self.start_time
            text += self.strings["time_exec"].format(round(exec_time, 2))

        with contextlib.suppress(MessageNotModifiedError):
            try:
                self.message = await utils.answer(self.message, text)
            except Exception as e:
                logger.error(e)

    async def cmd_ended(self, rc):
        self.rc = rc
        await self.redraw()


class InlineSudoEditor:
    def __init__(self, command, strings, owner_id):
        self.command = command
        self.strings = strings
        self.owner_id = owner_id
        self.stdout = ""
        self.stderr = ""
        self.rc = None
        self.start_time = time.time()
        self.process = None
        self.form = None
        self.waiting_password = False
        self._prompt_end = 0
        self._password_token = None
        self._auth_notice = ""
        self._edit_lock = asyncio.Lock()

    @staticmethod
    def password_requested(stderr):
        import re

        return re.search(r"\[sudo-execution\] password:\s*$", stderr)

    def update_process(self, process):
        self.process = process

    def observe_password_prompt(self):
        prompt = self.password_requested(self.stderr)
        if (
            prompt
            and prompt.end() > self._prompt_end
            and self.rc is None
            and self.process is not None
            and self.process.returncode is None
        ):
            self._auth_notice = self.strings[
                "sudo_password_retry" if self._prompt_end else "sudo_password_required"
            ]
            self._prompt_end = prompt.end()
            self._password_token = utils.rand(24)
            self.waiting_password = True

    def get_reply_markup(self):
        if not self.waiting_password or self.rc is not None:
            return []
        return [
            [
                {
                    "text": self.strings["sudo_password_button"],
                    "input": self.strings["sudo_password_input"],
                    "marker": "🔐",
                    "handler": self.input_password,
                    "args": (self._password_token,),
                }
            ]
        ]

    async def input_password(self, call, query: str, token: str):
        if getattr(call.from_user, "id", None) != self.owner_id:
            return
        if (
            not self.waiting_password
            or token != self._password_token
            or self.rc is not None
            or self.process is None
            or self.process.returncode is not None
            or self.process.stdin is None
            or self.process.stdin.is_closing()
            or not query
            or any(char in query for char in "\r\n\x00")
        ):
            return
        self.waiting_password = False
        self._password_token = None
        self._auth_notice = ""
        try:
            self.process.stdin.write(query.encode() + b"\n")
            await self.process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            del query
        await self.redraw()

    def render_text(self):
        text = self.strings["running"].format(utils.escape_html(self.command))
        if self.rc is not None:
            text += self.strings["finished"].format(utils.escape_html(str(self.rc)))
        stdout = utils.escape_html(self.stdout[max(len(self.stdout) - 2048, 0):])
        stderr = utils.escape_html(self.stderr[max(len(self.stderr) - 1024, 0):])
        if stdout:
            text += self.strings["stdout"] + stdout
            if stderr:
                text += self.strings["stderr"] + stderr
            text += self.strings["end"]
        elif stderr:
            text += self.strings["stderr_only"] + stderr + self.strings["end"]
        if self.rc is not None:
            text += self.strings["time_exec"].format(
                round(time.time() - self.start_time, 2)
            )
        if self.waiting_password and self.rc is None:
            text += self._auth_notice
        return text

    async def redraw(self):
        async with self._edit_lock:
            if self.form is not None:
                with contextlib.suppress(Exception):
                    await self.form.edit(
                        self.render_text(),
                        reply_markup=self.get_reply_markup(),
                    )

    async def update_stdout(self, stdout):
        self.stdout = stdout
        await self.redraw()

    async def update_stderr(self, stderr):
        self.stderr = stderr
        self.observe_password_prompt()
        await self.redraw()

    async def cmd_ended(self, rc):
        self.rc = rc
        self.waiting_password = False
        self._password_token = None
        self._auth_notice = ""
        await self.redraw()

    def on_unload(self):
        self.waiting_password = False
        self._password_token = None
        if self.process and self.process.stdin and not self.process.stdin.is_closing():
            self.process.stdin.close()


class SudoMessageEditor(MessageEditor):
    def __init__(self, message, command, strings, module):
        super().__init__(message, command, strings)
        self.module = module
        self.process = None
        self.inline_editor = None
        self._output_lock = asyncio.Lock()

    def update_process(self, process):
        self.process = process

    async def update_stderr(self, stderr):
        async with self._output_lock:
            self.stderr = stderr
            if self.inline_editor is None and InlineSudoEditor.password_requested(stderr):
                editor = InlineSudoEditor(
                    self.command,
                    self.strings,
                    self.module.tg_id,
                )
                editor.stdout = self.stdout
                editor.stderr = self.stderr
                editor.start_time = self.start_time
                editor.update_process(self.process)
                editor.observe_password_prompt()
                form = await self.module.inline.form(
                    message=self.message,
                    text=editor.render_text(),
                    reply_markup=editor.get_reply_markup(),
                    force_me=True,
                    on_unload=editor.on_unload,
                )
                if not form:
                    if self.process.stdin and not self.process.stdin.is_closing():
                        self.process.stdin.close()
                    return
                editor.form = form
                self.inline_editor = editor
                self.module._bind_process_message(self.process.pid, form)
                self.module._sudo_sessions[form.unit_id] = editor
            elif self.inline_editor is not None:
                await self.inline_editor.update_stderr(stderr)
            else:
                await self.redraw()

    async def update_stdout(self, stdout):
        async with self._output_lock:
            self.stdout = stdout
            if self.inline_editor is not None:
                await self.inline_editor.update_stdout(stdout)
            else:
                await self.redraw()

    async def cmd_ended(self, rc):
        async with self._output_lock:
            self.rc = rc
            if self.inline_editor is not None:
                await self.inline_editor.cmd_ended(rc)
                if self.inline_editor.form is not None:
                    self.module._sudo_sessions.pop(
                        self.inline_editor.form.unit_id,
                        None,
                    )
            else:
                await self.redraw()


@loader.tds
class Executor(loader.Module):

    strings = {
        "name": "Executor",
        "running": "<b>Execution:</b> <code>{}</code>",
        "finished": "\n<b>With code:</b> <code>{}</code>",
        "stdout": "\n<pre><code class=\"language-stdout\">",
        "stderr": "</code></pre>\n<pre><code class=\"language-stderr\">",
        "stderr_only": "\n<pre><code class=\"language-stderr\">",
        "end": "</code></pre>",
        "time_exec": "\n<b>Time:</b> <code>{}s</code>",
        "err": (
            "\n<b>Error</b>\n"
            "<blockquote>{}</blockquote>"
        ),
        "eval_py": (
            "<b>Executed code:</b>\n"
            "<blockquote expandable><code>{}</code></blockquote>"
        ),
        "eval_result": (
            "\n<b>Result</b>\n"
            "<pre><code class=\"language-python\">{}</code></pre>"
        ),
        "print_outp": (
            "\n<b>Print</b>\n"
            "<pre><code class=\"language-stdout\">{}</code></pre>"
        ),
        "no_cmd": (
            "<b>Error</b>\n"
            "<blockquote>No active command found in reply</blockquote>"
        ),
        "killed": (
            "<b>Killed</b>\n"
            "<blockquote>Process terminated</blockquote>"
        ),
        "kill_fail": (
            "<b>Error</b>\n"
            "<blockquote>Failed to kill process</blockquote>"
        ),
        "active_processes": "<b>Active Executor processes</b>\n<blockquote>Total: {}</blockquote>",
        "no_active_processes": "<b>No active Executor processes</b>",
        "process_info": "<b>Executor process</b>\n<blockquote><b>PID:</b> <code>{}</code>\n<b>Type:</b> <code>{}</code>\n<b>Runtime:</b> <code>{}s</code>\n<b>Command:</b> <code>{}</code></blockquote>",
        "kill_process": "Kill",
        "refresh_processes": "Refresh",
        "back": "Back",
        "close": "Close",
        "dangerous_command": (
            "<b>Blocked</b>\n"
            "<blockquote>Dangerous command: <code>{}</code></blockquote>"
        ),
        "no_args": (
            "<b>Error</b>\n"
            "<blockquote>No code provided</blockquote>"
        ),
        "exec_error": (
            "<b>Error</b>\n"
            "<blockquote>{}</blockquote>"
        ),
        "fw_protect": "Flood wait protection delay in seconds",
        "command_protect": "Block dangerous commands",
        "eval_debug_loop": "Update the running evaluation timer every 1 to 5 seconds",
        "sudo_password_button": "Input password",
        "sudo_password_input": "🔐 Submit sudo password",
        "sudo_password_required": "<b>sudo password required</b>",
        "sudo_password_retry": "<b>Enter the sudo password again</b>",
    }

    COMMAND_PROTECT = "command_protect"
    DANGEROUS_RM_TARGETS = {
        "/", "/bin", "/boot", "/dev", "/etc", "/lib", "/lib64",
        "/opt", "/proc", "/root", "/sbin", "/sys", "/usr", "/var",
    }
    DANGEROUS_COMMANDS = [
        r"dd\s+.*if=.*of=/dev/",
        r"mkfs\.",
        r"fdisk\s+\/dev/",
        r"chmod\s+.*000\s+.*\/",
        r":\(\)\s*\{\s*:\|:&\s*\}\s*;\s*:",
        r"curl\s+.*\|\s*(sh|bash|zsh|dash|ksh)",
        r"wget\s+.*-O\s*-\s*\|\s*(sh|bash|zsh|dash|ksh)",
        r"nc\s+.*-e\s+(sh|bash|zsh)",
        r"python[23]?\s+-c\s+[\"']import\s+os",
        r"kill\s+-9\s+1\b",
        r"shred\s+",
    ]

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "FLOOD_WAIT_PROTECT",
                2,
                lambda: self.strings["fw_protect"],
                validator=loader.validators.Integer(minimum=0),
            ),
            loader.ConfigValue(
                self.COMMAND_PROTECT,
                True,
                lambda: self.strings["command_protect"],
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "eval_debug_loop",
                True,
                lambda: self.strings["eval_debug_loop"],
                validator=loader.validators.Boolean(),
            ),
        )
        self.activecmds: dict[int, dict[str, typing.Any]] = {}
        self._message_processes: dict[str, int] = {}
        self._virtual_pid = 10_000_000
        self._sudo_sessions: dict[str, InlineSudoEditor] = {}

    @staticmethod
    def _message_key(message) -> str | None:
        form = getattr(message, "form", {})
        if not isinstance(form, dict):
            form = {}
        chat_id = getattr(message, "chat_id", None) or form.get("chat")
        message_id = (
            getattr(message, "id", None)
            or getattr(message, "message_id", None)
            or form.get("message_id")
        )
        if chat_id is None:
            with contextlib.suppress(Exception):
                chat_id = utils.get_chat_id(message)
        if chat_id is None or message_id is None:
            return None
        return f"{chat_id}:{message_id}"

    def _next_virtual_pid(self) -> int:
        while self._virtual_pid in self.activecmds:
            self._virtual_pid += 1
        pid = self._virtual_pid
        self._virtual_pid += 1
        return pid

    def _bind_process_message(self, pid: int, message) -> None:
        entry = self.activecmds.get(pid)
        key = self._message_key(message)
        if entry is None or key is None:
            return
        entry["message_keys"].add(key)
        self._message_processes[key] = pid

    def _register_process(
        self,
        kind: str,
        command: str,
        target,
        message,
        pid: int | None = None,
    ) -> int:
        pid = pid if pid is not None else self._next_virtual_pid()
        self.activecmds[pid] = {
            "pid": pid,
            "kind": kind,
            "command": command,
            "target": target,
            "started": time.monotonic(),
            "message_keys": set(),
        }
        self._bind_process_message(pid, message)
        return pid

    def _drop_process(self, pid: int) -> None:
        entry = self.activecmds.pop(pid, None)
        if entry is None:
            return
        for key in entry["message_keys"]:
            if self._message_processes.get(key) == pid:
                self._message_processes.pop(key, None)

    @staticmethod
    def _process_active(entry: dict[str, typing.Any]) -> bool:
        target = entry["target"]
        if entry["kind"] == "exec":
            return target.returncode is None
        return not target.done()

    def _active_processes(self) -> list[dict[str, typing.Any]]:
        for pid, entry in list(self.activecmds.items()):
            if not self._process_active(entry):
                self._drop_process(pid)
        return sorted(self.activecmds.values(), key=lambda entry: entry["started"])

    async def _stop_process(self, pid: int) -> bool:
        entry = self.activecmds.get(pid)
        if entry is None or not self._process_active(entry):
            self._drop_process(pid)
            return False
        try:
            if entry["kind"] == "exec":
                os.killpg(entry["target"].pid, signal.SIGTERM)
            else:
                entry["target"].cancel()
        except (OSError, RuntimeError):
            self._drop_process(pid)
            return False
        return True

    async def client_ready(self, client, db):
        self._client = client
        self._db = db

    async def on_unload(self):
        for pid in list(self.activecmds):
            await self._stop_process(pid)
        for editor in self._sudo_sessions.values():
            editor.on_unload()
        self._sudo_sessions.clear()

    def _is_dangerous(self, cmd: str) -> bool:
        if not self.config[self.COMMAND_PROTECT]:
            return False
        import re
        import shlex
        try:
            tokens = list(shlex.shlex(cmd, posix=True, punctuation_chars=True))
        except ValueError:
            tokens = []
        rm_names = {"rm", "/bin/rm", "/usr/bin/rm"}
        separators = {";", "&&", "||", "|", "&"}
        for idx, tok in enumerate(tokens):
            if tok not in rm_names:
                continue
            for target in tokens[idx + 1:]:
                if target in separators:
                    break
                if target == "--":
                    continue
                if os.path.normpath(target.rstrip()) in self.DANGEROUS_RM_TARGETS:
                    return True
        for pattern in self.DANGEROUS_COMMANDS:
            if re.search(pattern, cmd, re.IGNORECASE):
                return True
        return False



    @loader.command()
    async def exec(self, message: Message):
        cmd = utils.get_args_raw(message)
        reply = await message.get_reply_message()
        if not cmd and reply and reply.text:
            cmd = reply.message
        if not cmd:
            await utils.answer(message, self.strings["no_args"])
            return
        if self._is_dangerous(cmd):
            await utils.answer(
                message,
                self.strings["dangerous_command"].format(utils.escape_html(cmd)),
            )
            return
        await self._execute_shell(message, cmd)

    async def _execute_shell(self, message: Message, cmd: str):
        shell = os.environ.get("SHELL", "/bin/sh")
        utils.ensure_child_watcher()
        try:
            sproc = await asyncio.create_subprocess_exec(
                shell,
                "-c",
                sudo_stdin_command(cmd, shell),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=utils.get_base_dir(),
                preexec_fn=os.setsid,
            )
        except Exception as e:
            await utils.answer(
                message,
                self.strings["exec_error"].format(utils.escape_html(str(e))),
            )
            return

        editor = SudoMessageEditor(message, cmd, self.strings, self)
        editor.update_process(sproc)
        pid = self._register_process("exec", cmd, sproc, message, sproc.pid)

        try:
            await editor.redraw()
            self._bind_process_message(pid, editor.message)
            await asyncio.gather(
                read_stream(
                    editor.update_stdout,
                    sproc.stdout,
                    self.config["FLOOD_WAIT_PROTECT"],
                ),
                read_stream(
                    editor.update_stderr,
                    sproc.stderr,
                    self.config["FLOOD_WAIT_PROTECT"],
                ),
            )
            await editor.cmd_ended(await sproc.wait())
        finally:
            self._drop_process(pid)

    def _eval_status(self, code: str, elapsed: float) -> str:
        return self.strings["eval_py"].format(
            utils.escape_html(code)
        ) + self.strings["time_exec"].format(f"{elapsed:.2f}")

    async def _eval_debug_timer(self, state: list, code: str, started: float):
        while True:
            await asyncio.sleep(random.uniform(1, 5))
            with contextlib.suppress(Exception):
                state[0] = await utils.answer(
                    state[0],
                    self._eval_status(code, time.monotonic() - started),
                )

    @loader.command()
    async def e(self, message: Message):
        args = utils.get_args_raw(message)
        reply = await message.get_reply_message()
        if not args and reply and reply.text:
            args = reply.message
        if not args:
            await utils.answer(message, self.strings["no_args"])
            return

        args = args.replace("\xa0", "\x20")
        skip_output = args.startswith(("-so ", "--skip-output "))
        if skip_output:
            args = args.split(" ", 1)[1]

        started = time.monotonic()
        state = [await utils.answer(message, self._eval_status(args, 0))]
        timer = (
            asyncio.create_task(self._eval_debug_timer(state, args, started))
            if self.config["eval_debug_loop"]
            else None
        )
        output_print = StringIO()
        result = None
        error = None
        cancelled = False

        async def evaluate():
            with contextlib.redirect_stdout(output_print):
                return await meval(
                    args,
                    globals(),
                    **await self._getattrs(message),
                )

        evaluation = asyncio.create_task(evaluate())
        pid = self._register_process("e", args, evaluation, message)
        self._bind_process_message(pid, state[0])
        try:
            result = await evaluation
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            import traceback

            error = traceback.format_exc()
        finally:
            self._drop_process(pid)
            if timer:
                timer.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await timer

        if cancelled:
            await utils.answer(state[0], self.strings["killed"])
            return

        print_output = output_print.getvalue()
        exec_time = time.monotonic() - started

        if error is not None:
            await utils.answer(
                state[0],
                self.strings["eval_py"].format(utils.escape_html(args))
                + self.strings["err"].format(utils.escape_html(error))
                + (
                    self.strings["print_outp"].format(
                        utils.escape_html(print_output),
                    )
                    if print_output
                    else ""
                )
                + self.strings["time_exec"].format(f"{exec_time:.2f}"),
            )
            return

        if skip_output:
            await utils.answer(state[0], self._eval_status(args, exec_time))
            return

        if callable(getattr(result, "stringify", None)):
            with contextlib.suppress(Exception):
                result = str(result.stringify())

        with contextlib.suppress(MessageIdInvalidError):
            await utils.answer(
                state[0],
                self.strings["eval_py"].format(
                    utils.escape_html(args),
                )
                + (
                    self.strings["eval_result"].format(
                        utils.escape_html(str(result)),
                    )
                    if result or not print_output
                    else ""
                )
                + (
                    self.strings["print_outp"].format(
                        utils.escape_html(print_output),
                    )
                    if print_output
                    else ""
                )
                + self.strings["time_exec"].format(f"{exec_time:.2f}"),
            )

    def _processes_markup(self, page: int = 0) -> tuple[str, list]:
        processes = self._active_processes()
        pages = max(1, (len(processes) + 7) // 8)
        page = min(max(page, 0), pages - 1)
        markup = [
            [
                {
                    "text": f"PID {entry['pid']}",
                    "callback": self._inline_process_info,
                    "args": (entry["pid"], page),
                }
            ]
            for entry in processes[page * 8 : (page + 1) * 8]
        ]
        if len(processes) > 8:
            row = []
            if page > 0:
                row.append(
                    {
                        "text": "←",
                        "callback": self._inline_processes,
                        "args": (page - 1,),
                        "style": "primary",
                    }
                )
            row.append(
                {
                    "text": f"{page + 1}/{pages}",
                    "callback": self._inline_processes,
                    "args": (page,),
                }
            )
            if page < pages - 1:
                row.append(
                    {
                        "text": "→",
                        "callback": self._inline_processes,
                        "args": (page + 1,),
                        "style": "primary",
                    }
                )
            markup.append(row)
        markup.append(
            [
                {
                    "text": self.strings["refresh_processes"],
                    "callback": self._inline_processes,
                    "args": (page,),
                },
                {
                    "text": self.strings["close"],
                    "action": "close",
                    "style": "primary",
                },
            ]
        )
        text = (
            self.strings["active_processes"].format(len(processes))
            if processes
            else self.strings["no_active_processes"]
        )
        return text, markup

    async def _inline_processes(self, call, page: int = 0):
        text, markup = self._processes_markup(page)
        await call.edit(text, reply_markup=markup)

    async def _inline_process_info(self, call, pid: int, page: int = 0):
        entry = self.activecmds.get(pid)
        if entry is None or not self._process_active(entry):
            self._drop_process(pid)
            await self._inline_processes(call, page)
            return
        await call.edit(
            self.strings["process_info"].format(
                entry["pid"],
                entry["kind"],
                f"{time.monotonic() - entry['started']:.2f}",
                utils.escape_html(entry["command"]),
            ),
            reply_markup=[
                [
                    {
                        "text": self.strings["kill_process"],
                        "callback": self._inline_kill_process,
                        "args": (pid, page),
                        "style": "danger",
                    },
                    {
                        "text": self.strings["back"],
                        "callback": self._inline_processes,
                        "args": (page,),
                        "style": "primary",
                    },
                ]
            ],
        )

    async def _inline_kill_process(self, call, pid: int, page: int = 0):
        if not await self._stop_process(pid):
            await call.edit(
                self.strings["kill_fail"],
                reply_markup=[
                    {
                        "text": self.strings["back"],
                        "callback": self._inline_processes,
                        "args": (page,),
                        "style": "primary",
                    }
                ],
            )
            return
        await call.edit(
            self.strings["killed"],
            reply_markup=[
                {
                    "text": self.strings["back"],
                    "callback": self._inline_processes,
                    "args": (page,),
                    "style": "primary",
                }
            ],
        )

    @loader.command()
    async def kill(self, message: Message):
        args = utils.get_args_raw(message).strip()
        pid = None
        if args:
            with contextlib.suppress(ValueError):
                pid = int(args)
        elif message.is_reply:
            reply = await message.get_reply_message()
            key = self._message_key(reply) if reply else None
            if key is not None:
                pid = self._message_processes.get(key)
        else:
            text, markup = self._processes_markup()
            await self.inline.form(
                text,
                message=message,
                reply_markup=markup,
                silent=True,
            )
            return

        if pid is None or pid not in self.activecmds:
            await utils.answer(message, self.strings["no_cmd"])
            return
        if await self._stop_process(pid):
            await utils.answer(message, self.strings["killed"])
        else:
            await utils.answer(message, self.strings["kill_fail"])


    async def _getattrs(self, message: Message) -> dict:
        reply = await message.get_reply_message()
        return {
            "message": message,
            "client": self._client,
            "reply": reply,
            "r": reply,
            "event": message,
            "chat": message.to_id,
            "telethon": __import__("telethon"),
            "utils": utils,
            "main": main,
            "loader": loader,
            "c": self._client,
            "m": message,
            "lookup": self.lookup,
            "self": self,
            "db": self.db,
            **self._get_sub(__import__("telethon").tl.functions),
            **self._get_sub(__import__("telethon").tl.types),
        }

    def _get_sub(self, obj: typing.Any, _depth: int = 1) -> dict:
        return {
            **dict(filter(
                lambda x: x[0][0] != "_" and x[0][0].upper() == x[0][0] and callable(x[1]),
                obj.__dict__.items(),
            )),
            **dict(itertools.chain.from_iterable([
                self._get_sub(y[1], _depth + 1).items()
                for y in filter(
                    lambda x: x[0][0] != "_"
                    and isinstance(x[1], ModuleType)
                    and x[1] != obj
                    and x[1].__package__.rsplit(".", _depth)[0] == "telethon.tl",
                    obj.__dict__.items(),
                )
            ])),
        }
