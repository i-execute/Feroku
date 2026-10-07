# CopyLeft 2026 github.com/i-execute // i_execute.t.me
# Licensed under AGPLv3.

# (c) Dan Gazizullin, 2021-2023. This file is part of the Hikka Userbot: github.com/hikariatama/Hikka

import string
import sys

def api_config():
    from . import main

    print("Welcome to Feroku fork without backdoors!")


    while api_id := input("Enter API ID: "):
        if api_id.isdigit():
            break

        print("Invalid ID")

    if not api_id:
        print("Cancelled")
        sys.exit(0)

    while api_hash := input("Enter API hash: "):
        if len(api_hash) == 32 and all(
            symbol in string.hexdigits for symbol in api_hash
        ):
            print("Completed!")
            break

        print("Invalid hash")

    if not api_hash:
        print("Cancelled")
        sys.exit(0)

    import json

    with main.CONFIG_PATH.open("w") as f:
        json.dump({"api_id": int(api_id), "api_hash": api_hash}, f)
