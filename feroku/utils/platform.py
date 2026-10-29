# CopyLeft 2026 github.com/i-execute // i_execute.t.me
# Licensed under AGPLv3.

# (c) Dan Gazizullin, 2021-2023. This file is part of the Hikka Userbot: github.com/hikariatama/Hikka

import contextlib
import logging
import os
import threading
import time
from datetime import timedelta

import telethon

parser = telethon.utils.sanitize_parse_mode("html")
logger = logging.getLogger(__name__)

IS_DOCKER = "DOCKER" in os.environ
IS_MACOS = "com.apple" in os.environ.get("PATH", "")
IS_USERLAND = "userland" in os.environ.get("USER", "")
IS_WSL = False
IS_WINDOWS = False
with contextlib.suppress(Exception):
    from platform import uname

    if "microsoft-standard" in uname().release:
        IS_WSL = True
    elif uname().system == "Windows":
        IS_WINDOWS = True

def get_named_platform() -> str:
    with contextlib.suppress(Exception):
        if os.path.isfile("/proc/device-tree/model"):
            with open("/proc/device-tree/model") as f:
                model = f.read().strip()
                if any(board in model for board in ("Orange", "Raspberry")):
                    return model

    match True:

        case _ if IS_WSL:
            return "WSL"

        case _ if IS_WINDOWS:
            return "Windows"

        case _ if IS_MACOS:
            return "MacOS"

        case _ if IS_USERLAND:
            return "UserLand"


        case _ if IS_DOCKER:
            return "Docker"

        case _:
            return "VDS"

def get_named_platform_emoji() -> str:
    with contextlib.suppress(Exception):
        if os.path.isfile("/proc/device-tree/model"):
            with open("/proc/device-tree/model") as f:
                model = f.read()
                if "Orange" in model:
                    return " "

                if "Raspberry" in model:
                    return " "
                else:
                    return "?"

    match True:

        case _ if IS_WSL:
            return " "

        case _ if IS_WINDOWS:
            return " "

        case _ if IS_MACOS:
            return " "

        case _ if IS_USERLAND:
            return " "

        case _ if IS_DOCKER:
            return " "

        case _:
            return " "

def get_platform_emoji() -> str:
    return ""

def uptime() -> int:
    current_uptime = round(time.perf_counter() - init_ts)
    return current_uptime

def formatted_uptime() -> str:
    total_seconds = uptime()
    days, remainder = divmod(total_seconds, 86400)
    time_formatted = str(timedelta(seconds=remainder))
    if days > 0:
        return f"{days} day(s), {time_formatted}"
    return time_formatted

def get_ram_usage() -> float:
    try:
        import psutil

        current_process = psutil.Process(os.getpid())
        mem = current_process.memory_info()[0] / 2.0**20
        for child in current_process.children(recursive=True):
            mem += child.memory_info()[0] / 2.0**20
        return round(mem, 1)
    except Exception:
        return 0

def get_ram_usage_system() -> dict:
    try:
        import psutil

        vm = psutil.virtual_memory()
        return {
            "percent": round(vm.percent, 1),
            "used": round(vm.used / 1024 / 1024),
            "total": round(vm.total / 1024 / 1024),
        }
    except Exception:
        return {"error": "Failed to get RAM usage"}

def get_swap_usage() -> dict:
    try:
        import psutil

        swap = psutil.swap_memory()
        if swap.total == 0:
            return {"error": "Swap is not configured on this system"}
        return {
            "percent": round(swap.percent, 1),
            "used": round(swap.used / 1024 / 1024),
            "total": round(swap.total / 1024 / 1024),
        }
    except Exception:
        return {"error": "Failed to get swap usage"}

_CPU_TIMES_LOCK = threading.Lock()
_CPU_TIMES_PREVIOUS = None


def get_cpu_usage():
    import psutil

    global _CPU_TIMES_PREVIOUS

    try:
        with _CPU_TIMES_LOCK:
            cpu_times = psutil.cpu_times()
            counters = tuple(
                getattr(cpu_times, name, 0.0)
                for name in (
                    "user",
                    "nice",
                    "system",
                    "idle",
                    "iowait",
                    "irq",
                    "softirq",
                    "steal",
                )
            )
            total = sum(counters)
            idle = getattr(cpu_times, "idle", 0.0) + getattr(cpu_times, "iowait", 0.0)
            current = (total, idle)
            previous = _CPU_TIMES_PREVIOUS
            _CPU_TIMES_PREVIOUS = current

        if previous is None:
            return "0.00"

        total_delta = total - previous[0]
        idle_delta = idle - previous[1]
        if total_delta <= 0:
            return "0.00"

        cpu_percent = max(0.0, min(100.0, (total_delta - idle_delta) * 100 / total_delta))
        return f"{cpu_percent:.2f}"
    except Exception:
        return "0.00"

init_ts = time.perf_counter()

get_platform_name = get_named_platform

def get_disk_usage() -> dict:
    try:
        import psutil

        disk = psutil.disk_usage("/")
        return {
            "total": round(disk.total / (1024**3), 2),
            "used": round(disk.used / (1024**3), 2),
            "free": round(disk.free / (1024**3), 2),
            "percent": disk.percent,
        }
    except Exception:
        return {"total": 0, "used": 0, "free": 0, "percent": 0}