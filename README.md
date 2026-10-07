<p align="center">
  <a href="https://t.me/I_execute"><img src="https://img.shields.io/badge/Telegram-@I__execute-26A5E4?style=flat&logo=telegram&logoColor=white" alt="Telegram" /></a>
</p>

# Feroku Userbot

Feroku is a modular Telegram userbot built with Telethon. It supports terminal-based first-time configuration, Telegram authorization through a private bot, automatic daemon installation, module management, backups, and session recovery.

## Requirements

- Linux with systemd recommended
- Python 3.10 or newer
- Git
- A Telegram API ID and API hash from [my.telegram.org](https://my.telegram.org)
- A Telegram bot created with [BotFather](https://t.me/BotFather)
- Inline mode enabled for the bot

The bot token must be entered in the terminal. Feroku does not create a bot, open BotFather, enable inline mode, or restore the primary bot token from a backup.

## Installation

Run the following commands:

```bash
git clone https://github.com/i-execute/Feroku.git
cd Feroku
python3 -m venv venv
source venv/bin/activate
python3 -m pip install -r Storage/requirements.txt
python3 -m feroku
```

Complete the terminal prompts in this order:

1. Enter the Telegram API ID.
2. Enter the Telegram API hash.
3. Enter the bot token.
4. Open the bot in Telegram and send `/start` to receive your Telegram ID.
5. Enter that Telegram ID in the terminal.

After the Telegram ID is entered, no further SSH interaction is required. Feroku saves the setup state, creates `feroku.service`, releases the temporary process lock, and continues authorization independently. You can disconnect from SSH when the terminal confirms that setup is continuing in Telegram.

## License

Feroku is distributed under the GNU Affero General Public License v3.0. See [LICENSE](LICENSE) for details.
