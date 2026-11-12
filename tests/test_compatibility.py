import asyncio
import hashlib
import importlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import telethon
from telethon.errors import WebpageMediaEmptyError
from telethon.tl.types import (
    InputBotInlineMessageText,
    Message,
    MessageReplyHeader,
    PeerChannel,
)

from feroku import loader, security
from feroku._compat import install_client_compat
from feroku._compat_database import migrate_database_items
from feroku.database import Database, NoAssetsChannel, NoContentChannel
from feroku.inline.list import MAX_PAGES, Pages
from feroku.inline.screens import Screen
from feroku.inline.types import InlineMessage


class CompatDatabaseTests(unittest.TestCase):
    def test_cross_project_migration_and_config_aliases(self):
        original = {
            "hikka.main": {"command_prefix": "!"},
            "LoaderMod": {
                "loaded_modules": {"AMod": "https://example/a.py"},
                "unloaded_modules": ["OldMod"],
            },
            "AtaraxiaInfoMod": {
                "__config__": {
                    "custom_message1": "hello",
                    "banner_url": "https://example/banner.png",
                    "help_banner_url": "https://example/help.png",
                    "quote_media": False,
                    "rich_mode": True,
                },
                "hide": ["HiddenMod"],
            },
            "TestMod": {
                "__config__": {
                    "force_send_all": True,
                    "tglog_level": "WARNING",
                }
            },
            "AtaraxiaSettingsMod": {
                "__config__": {
                    "show_restart": False,
                    "custom_link": "https://example/link",
                }
            },
        }
        result = migrate_database_items(original)
        self.assertEqual(result["feroku.main"]["command_prefix"], "!")
        self.assertEqual(
            result["Installer"]["loaded_modules"]["AMod"],
            "https://example/a.py",
        )
        self.assertIn("OldMod", result["Installer"]["unloaded_modules"])
        info = result["FInfo"]
        self.assertEqual(info["__config__"]["custom_message"], "hello")
        self.assertEqual(info["__config__"]["banner_url"], "https://example/banner.png")
        self.assertFalse(info["__config__"]["quote_media"])
        help_section = result["Help"]
        self.assertIn("HiddenMod", help_section["hide"])
        help_config = help_section["__config__"]
        self.assertEqual(help_config["banner_url"], "https://example/help.png")
        self.assertFalse(help_config["media_quote"])
        self.assertTrue(help_config["rich_mode"])
        tester = result["Tester"]["__config__"]
        self.assertTrue(tester["force_send_all"])
        self.assertEqual(tester["tglog_level"], "WARNING")
        settings = result["Settings"]["__config__"]
        self.assertFalse(settings["show_restart"])
        self.assertEqual(settings["custom_link"], "https://example/link")

    def test_runtime_legacy_reads_writes_pointers_and_direct_assignment(self):
        db = Database(Mock())
        db.save = Mock(return_value=True)
        db.set("heroku.main", "command_prefix", "?")
        self.assertEqual(db.get("ataraxia.main", "command_prefix"), "?")
        db["HikkaInfoMod"] = {
            "__config__": {"custom_message1": "legacy"}
        }
        self.assertEqual(
            db.get("FInfo", "__config__")["custom_message"],
            "legacy",
        )
        self.assertEqual(
            db.get("Info", "__config__")["custom_message"],
            "legacy",
        )
        self.assertEqual(
            db.get("AtaraxiaInfoMod", "__config__")["custom_message"],
            "legacy",
        )
        db.set("AtaraxiaSettingsMod", "aliases", {"x": "ping"})
        pointer = db.pointer("HerokuSettingsMod", "aliases", {})
        pointer["y"] = "help"
        self.assertEqual(db.get("Settings", "aliases")["y"], "help")
        self.assertTrue(db.flush())


class ApiCompatibilityTests(unittest.TestCase):
    def test_project_namespace_aliases_and_public_types(self):
        for name in (
            "hikka.loader",
            "heroku.loader",
            "ataraxia.loader",
            "hikka.types",
            "heroku.types",
            "ataraxia.types",
            "hikka.inline.types",
            "heroku.inline.types",
            "ataraxia.inline.types",
        ):
            self.assertIsNotNone(importlib.import_module(name))
        from feroku import types as module_types

        for name in (
            "HikkaReplyMarkup",
            "HerokuReplyMarkup",
            "ataraxiaReplyMarkup",
            "Library",
            "Module",
        ):
            self.assertTrue(hasattr(module_types, name), name)
        module = module_types.Module()
        self.assertEqual(module.heroku_commands, module.feroku_commands)
        self.assertEqual(module.ataraxia_inline_handlers, module.feroku_inline_handlers)
        self.assertEqual(module.hikka_watchers, module.feroku_watchers)

    def test_loader_api_and_unsupported_dependency_filter(self):
        self.assertTrue(hasattr(loader, "translatable_docstring"))
        self.assertTrue(hasattr(loader, "get_module_hash"))
        self.assertTrue(hasattr(loader, "set_data_root"))
        self.assertTrue(hasattr(loader, "VALID_APT_PACKAGES"))
        self.assertEqual(loader.drop_unsupported(["aiogram==3.0", "requests"]), ["requests"])
        module = loader.Module()
        module.__source__ = "class Sample: pass\n"
        self.assertEqual(len(loader.get_module_hash(module)), 64)

    def test_client_aliases(self):
        client = types.SimpleNamespace()
        me = types.SimpleNamespace(id=123)
        inline = object()
        install_client_compat(client, me=me, inline=inline)
        self.assertIs(client.feroku_me, me)
        self.assertIs(client.hikka_me, me)
        self.assertIs(client.heroku_me, me)
        self.assertIs(client.ataraxia_me, me)
        self.assertIs(client.feroku_inline, inline)
        self.assertIs(client.hikka_inline, inline)
        self.assertIs(client.heroku_inline, inline)
        self.assertIs(client.ataraxia_inline, inline)

    def test_external_module_source_imports_across_namespaces(self):
        source = '''
from ataraxia import loader
from heroku.inline.screens import Screen
from hikka.types import Module

@loader.tds
class CrossForkMod(Module):
    strings = {"name": "CrossFork"}

    @loader.command()
    async def crossfork(self, message):
        """Compatibility command."""
        return Screen().add("ok")
'''
        namespace = {"__name__": "feroku.modules.crossfork"}
        exec(compile(source, "<cross-fork-module>", "exec"), namespace)
        module = namespace["CrossForkMod"]()
        self.assertIn("crossfork", module.commands)

    def test_telethon_is_pinned_and_supports_caption_position(self):
        self.assertEqual(telethon.__version__, "1.45.0")
        content = InputBotInlineMessageText("test", invert_media=True)
        self.assertTrue(content.invert_media)
        requirements = Path("Storage/requirements.txt").read_text(encoding="utf-8")
        self.assertIn("telethon==1.45.0", requirements.splitlines())
        self.assertNotIn("aiogram", requirements.lower())
        self.assertFalse(Path("Storage/Compat.sh").exists())
        self.assertFalse(Path("Storage/Heroku.PNG").exists())
        self.assertTrue(Path("Storage/Feroku.PNG").exists())
        source = "\n".join(
            path.read_text(encoding="utf-8", errors="ignore")
            for path in Path("feroku").rglob("*.py")
        )
        self.assertNotIn("ferokutl", source)

    def test_inline_input_results_remain_private_and_uncached(self):
        source = Path("feroku/inline/form.py").read_text(encoding="utf-8")
        marker = 'title=button["input"] + " " + symbol'
        start = source.index(marker)
        end = source.index("return", start)
        result_block = source[start:end]
        self.assertIn('"🔐" if button.get("marker") == "🔐" else "📝"', result_block)
        self.assertIn("cache_time=0", result_block)
        self.assertIn("is_personal=True", result_block)


class SecurityCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_mask_helpers_use_stable_bound_method_key(self):
        class Demo:
            async def ping(self):
                return None

        demo = Demo()
        legacy = f"{demo.ping.__module__}.{demo.ping.__name__}"
        masks = {legacy: security.PM}
        self.assertEqual(security.get_mask(masks, demo.ping, security.OWNER), security.PM)
        security.set_mask(masks, demo.ping, security.GROUP_MEMBER)
        self.assertNotIn(legacy, masks)
        self.assertEqual(masks["Demo.ping"], security.GROUP_MEMBER)

    async def test_check_user_without_message(self):
        manager = security.SecurityManager.__new__(security.SecurityManager)
        manager._client = types.SimpleNamespace(
            tg_id=100,
            loader=types.SimpleNamespace(commands={}),
        )
        manager._db = types.SimpleNamespace(_get_raw=lambda *args: [])
        manager._owner = [100]
        manager._sgroups = {}
        manager._tsec_user = []
        manager._tsec_chat = []
        manager._reload_rights = Mock()
        manager.get_flags = Mock(return_value=security.EVERYONE)
        self.assertTrue(await manager.check_user(security.EVERYONE, 200))
        manager.get_flags = Mock(return_value=security.OWNER)
        self.assertFalse(await manager.check_user(security.OWNER, 200))


class ScreenAndInlineTests(unittest.IsolatedAsyncioTestCase):
    async def test_screen_builders_plain_fallback_and_pages(self):
        callback = AsyncMock()
        screen = Screen(translate=lambda key: None)
        screen.add(
            "<h1>Title</h1>",
            screen.row(
                screen.tap("Run", callback, 1, style="primary"),
                screen.copy("Copy", "value"),
            ),
            screen.details("More", screen.table([["Key", "Value"]])),
        )
        screen.keyboard(screen.footer(callback))
        screen.warn("Notice")
        rich = screen.html()
        plain, rows = screen.plain()
        self.assertIn("<tg-button", rich)
        self.assertNotIn("<tg-button", plain)
        self.assertIn("Title", plain)
        self.assertTrue(any(button.get("callback") is callback for row in rows for button in row))
        self.assertTrue(any(button.get("copy") == "value" for row in rows for button in row))
        pager = screen.pager(callback, 1, 3)
        self.assertEqual(pager[1]["text"], "2 / 3")
        chunk, page, pages = screen.page(list(range(8)), 1, 3)
        self.assertEqual((chunk, page, pages), ([3, 4, 5], 1, 3))
        page_form = Pages(["one", "two"], markdown=True)
        self.assertEqual(page_form.content(1), {"markdown": "two"})
        self.assertEqual(MAX_PAGES, 50)

    async def test_inline_message_screen_edit_routes_rich_and_binds(self):
        callback = AsyncMock()
        screen = Screen()
        screen.add("<b>Hello</b>", screen.tap("noop", callback))
        screen.keyboard([screen.close()])
        bot = types.SimpleNamespace(edit_rich_message=AsyncMock())
        manager = types.SimpleNamespace(
            _units={"unit": {"buttons": []}},
            bot=bot,
            generate_markup=lambda value: value,
            _bind_screen=Mock(),
        )
        message = InlineMessage(manager, "unit", "inline-id")
        returned = await message.edit(rich_html=screen)
        self.assertIs(returned, message)
        bot.edit_rich_message.assert_awaited_once()
        kwargs = bot.edit_rich_message.await_args.kwargs
        self.assertEqual(kwargs["inline_message_id"], "inline-id")
        self.assertNotIn("tg-button", kwargs["html"])
        self.assertIn("<b>Hello</b>", kwargs["html"])
        manager._bind_screen.assert_called_once_with("unit", screen)

    async def test_inline_ready_lifecycle(self):
        first = types.SimpleNamespace(inline_ready=AsyncMock())
        second = types.SimpleNamespace(inline_ready=AsyncMock())
        modules = loader.Modules.__new__(loader.Modules)
        modules.modules = [first, second]
        modules._ready_sent = True
        modules.inline = types.SimpleNamespace(init_complete=True)
        await modules.send_inline_ready()
        first.inline_ready.assert_awaited_once()
        second.inline_ready.assert_awaited_once()


class ExecutorAndTopicRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_executor_source_is_the_verified_sudo_build(self):
        path = Path("feroku/Modules/Executor.py")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(
            digest,
            "d29bfa5c2c0476df8b21ce42d55488a5677d8869d4e61bf37cfb4d4b88c925a9",
        )
        from feroku.Modules.Executor import (
            alias_prelude,
            normalize_sudo_stderr,
            sudo_stdin_command,
        )

        self.assertIn("expand_aliases", alias_prelude("/bin/bash"))
        self.assertEqual(alias_prelude("/bin/sh"), "")
        self.assertIn("sudo -S -p '[sudo-execution] password:'", sudo_stdin_command("id", "/bin/bash"))
        self.assertIn("function sudo", sudo_stdin_command("id", "/usr/bin/fish"))
        self.assertIn(
            "[sudo-execution] password:",
            normalize_sudo_stderr("[sudo: [sudo-execution] password:] password:"),
        )

    async def test_topic_is_preserved_when_clicking_inline_result(self):
        from feroku.inline.core import InlineManager

        clicked = AsyncMock(return_value=types.SimpleNamespace(id=5))
        result = types.SimpleNamespace(
            result=types.SimpleNamespace(id="chosen"),
            click=clicked,
        )
        client = types.SimpleNamespace(
            inline_query=AsyncMock(return_value=[result])
        )
        manager = InlineManager.__new__(InlineManager)
        manager._client = client
        manager.bot_username = "inline_bot"
        manager._error_events = {}
        manager._units = {"unit": {}}
        message = Message(
            id=2,
            peer_id=PeerChannel(10),
            date=None,
            message=".test",
            reply_to=MessageReplyHeader(
                reply_to_msg_id=77,
                reply_to_top_id=77,
                forum_topic=True,
            ),
        )
        await manager._invoke_unit("unit", message, top_msg_id=77)
        self.assertEqual(clicked.await_args.kwargs["reply_to"], 77)
        self.assertEqual(manager._units["unit"]["_chosen_result_id"], "chosen")


class SystemModuleTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_core_modules_register(self):
        before = set(asyncio.all_tasks())
        client = types.SimpleNamespace(
            tg_id=1,
            add_event_handler=Mock(),
            remove_event_handler=Mock(),
        )
        db = Database(client)
        db.save = Mock(return_value=True)
        modules = loader.Modules(client, db)
        loaded = await modules.register_all(None)
        self.assertEqual(
            {module.__class__.__name__ for module in loaded},
            {
                "Backup",
                "Config",
                "Executor",
                "Help",
                "Installer",
                "Restart",
                "Security",
                "Settings",
                "Tester",
                "Translator",
            },
        )
        created = set(asyncio.all_tasks()) - before - {asyncio.current_task()}
        for task in created:
            task.cancel()
        await asyncio.gather(*created, return_exceptions=True)

    async def test_system_module_compatible_config_surfaces(self):
        from feroku.Modules.Help import Help
        from feroku.Modules.Installer import Installer
        from feroku.Modules.Settings import Settings
        from feroku.Modules.Tester import Tester
        from feroku.Modules.Translate import Translator

        expected = {
            Help: {
                "banner_url",
                "desc_icon",
                "empty_emoji",
                "invert_media",
                "media_quote",
                "rich_mode",
            },
            Installer: {"modules_repo", "rich_mode"},
            Settings: {
                "alias_emoji",
                "allow_nonstandart_prefixes",
                "keep_message_state",
                "rich_mode",
            },
            Tester: {
                "custom_message",
                "disable_internet_warn",
                "force_send_all",
                "ignore_common",
                "rich_mode",
                "tglog_level",
            },
            Translator: {"only_text", "provider"},
        }
        for cls, keys in expected.items():
            self.assertTrue(keys.issubset(set(cls().config.keys())), cls.__name__)

    async def test_rich_media_fallback_removes_unsupported_cover(self):
        from feroku.utils import messages

        answer = AsyncMock(
            side_effect=[WebpageMediaEmptyError(request=None), "fallback-result"]
        )
        with patch.object(messages, "answer", answer):
            result = await messages.answer_with_media_fallback(
                object(),
                rich_message='<img src="https://example/image.png"><h1>Result</h1>',
            )
        self.assertEqual(result, "fallback-result")
        second = answer.await_args_list[1]
        self.assertNotIn("<img", second.kwargs["rich_message"])
        self.assertFalse(second.kwargs["link_preview"])

    async def test_failed_persisted_module_can_be_unloaded(self):
        from feroku.Modules.Installer import Installer

        db = Database(Mock())
        db.save = Mock(return_value=True)
        db.set("Installer", "loaded_modules", {"BrokenMod": "https://example/broken.py"})
        with tempfile.TemporaryDirectory() as directory, patch.object(
            loader,
            "MODULES_PATH",
            Path(directory),
        ):
            source = Path(directory) / "BrokenMod.py"
            source.write_text("class BrokenMod:\n    pass\n", encoding="utf-8")
            installer = Installer()
            installer._db = db
            installer.lookup = Mock(return_value=None)
            installer.allmodules = types.SimpleNamespace(
                unload_module=AsyncMock(return_value=[])
            )
            message = await installer.unload_module("Broken")
            self.assertIn("Broken", message)
            self.assertFalse(source.exists())
            self.assertEqual(loader.get_module_origins(db), {})
            self.assertIn("BrokenMod", loader.get_unloaded_modules(db))


class AssetCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_store_and_fetch_assets(self):
        stored = types.SimpleNamespace(id=44)
        fetched = types.SimpleNamespace(id=44)
        client = types.SimpleNamespace(
            send_message=AsyncMock(return_value=stored),
            send_file=AsyncMock(return_value=stored),
            get_messages=AsyncMock(return_value=[fetched]),
        )
        db = Database(client)
        db.save = Mock(return_value=True)
        db.update(
            {
                "feroku.forums": {
                    "channel_id": 10,
                    "forums_cache": {"feroku-userbot": {"Assets": 20}},
                }
            }
        )
        message = Message(id=1, peer_id=None, date=None, message="asset")
        self.assertEqual(await db.store_asset(message), 44)
        client.send_message.assert_awaited_once_with(10, message, reply_to=20)
        self.assertEqual((await db.fetch_asset(44)).id, 44)
        client.get_messages.assert_awaited_once_with(10, reply_to=20, ids=[44])
        self.assertEqual(await db.store_asset(b"data"), 44)
        client.send_file.assert_awaited_once()

    async def test_asset_errors(self):
        db = Database(types.SimpleNamespace())
        db.save = Mock(return_value=True)
        with self.assertRaises(NoContentChannel):
            await db.fetch_asset(1)
        db.update({"feroku.forums": {"channel_id": 10, "forums_cache": {}}})
        with self.assertRaises(NoAssetsChannel):
            await db.fetch_asset(1)


def tearDownModule():
    main_module = sys.modules.get("feroku.main")
    application = getattr(main_module, "feroku", None) if main_module else None
    if application is None:
        return
    application._release_instance_lock()
    if not application.loop.is_closed():
        application.loop.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
