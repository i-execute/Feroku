# CopyLeft 2026 github.com/i-execute // i_execute.t.me
# Licensed under AGPLv3.

# (c) Dan Gazizullin, 2021-2023. This file is part of the Hikka Userbot: github.com/hikariatama/Hikka

import asyncio
import logging
import os
import random
import sys
_background_tasks: set[asyncio.Task] = set()

def _track_task(task: asyncio.Task) -> asyncio.Task:
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task

def install_task_tracking():
    loop_cls = asyncio.base_events.BaseEventLoop
    if getattr(loop_cls.create_task, "_feroku_tracked", False):
        return

    original_create_task = loop_cls.create_task

    def create_task(self, coro, **kwargs):
        return _track_task(original_create_task(self, coro, **kwargs))

    create_task._feroku_tracked = True
    loop_cls.create_task = create_task

async def fw_protect():
    await asyncio.sleep(random.randint(1000, 2000) / 1000)

def restart():
    logging.shutdown()
    os.execv(
        sys.executable,
        [sys.executable, "-m", "feroku", *sys.argv[1:]],
    )
