import tempfile
import unittest
import json
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import patch

from qq_cs2_bot.cs2_updates import (UpdateError, _format_points, clean_patch_notes,
                                    history_page, poll_updates, translate_update)
from qq_cs2_bot.esports_commands import command_reply
from qq_cs2_bot.esports_subscriptions import SubscriptionStore
from qq_cs2_bot.esports_service import news_settings


def article(gid, date):
    return {"gid": gid, "date": date, "appid": 730,
            "feedname": "steam_community_announcements", "tags": ["patchnotes"],
            "title": "Counter-Strike 2 Update", "contents": "[p]Fixed a crash[/p]",
            "url": "https://store.steampowered.com/news/app/730"}


def event(mid, text, role="member"):
    return {"post_type": "message", "message_type": "group", "group_id": 123456789,
            "user_id": 111111111, "self_id": 222222222, "message_id": mid,
            "sender": {"role": role},
            "message": [{"type": "text", "data": {"text": text}}]}


class Cs2UpdateTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = SubscriptionStore(Path(folder.name) / "esports.sqlite3")

    def test_group_switch_needs_admin_and_translation(self):
        self.assertIn("仅群主或管理员", command_reply(event(1, "#更新播报 开"), self.store,
                                                 "token", translation_ready=True))
        self.assertIn("翻译密钥", command_reply(event(2, "#更新播报 开", "admin"), self.store,
                                            "token"))
        self.assertFalse(self.store.news_enabled("123456789"))
        self.assertIn("已开", command_reply(event(3, "#更新播报 开", "admin"), self.store,
                                         "token", translation_ready=True))
        self.assertTrue(self.store.news_enabled("123456789"))
        self.assertIn("已关", command_reply(event(4, "#更新播报 关", "owner"), self.store,
                                         "token", translation_ready=True))

    def test_broadcast_content_switch_needs_admin_and_keeps_one_section(self):
        self.assertIn("仅群主或管理员", command_reply(event(11, "#播报解读 开"), self.store,
                                                 "token"))
        self.assertIn("已开", command_reply(event(12, "#更新播报 解读 开", "admin"),
                                         self.store, "token"))
        self.assertIn("已关", command_reply(event(13, "#播报原文 关", "owner"),
                                         self.store, "token"))
        self.assertEqual(self.store.news_broadcast_settings("123456789"), (True, False))
        self.assertIn("至少要显示", command_reply(event(14, "#播报解读 关", "owner"),
                                            self.store, "token"))
        self.assertEqual(self.store.news_broadcast_settings("123456789"), (True, False))
        self.assertIn("关", command_reply(event(15, "#更新播报 原文 状态"), self.store,
                                      "token"))

    @patch("qq_cs2_bot.cs2_updates.send_group_text", return_value="message-1")
    @patch("qq_cs2_bot.cs2_updates.translate_update")
    @patch("qq_cs2_bot.cs2_updates.fetch_updates")
    @patch("qq_cs2_bot.cs2_updates.time.time", return_value=200000)
    def test_broadcast_uses_each_groups_content_settings(self, now, fetch, translate, send):
        with patch("qq_cs2_bot.esports_subscriptions.time.time", return_value=199000):
            self.store.set_news_enabled("123456789", True)
            self.store.set_news_enabled("987654321", True)
            self.store.set_news_broadcast_settings("987654321", True, False)
        translate.side_effect = lambda item, key, model, interpret, **kwargs: (
            "• 修复崩溃\n简要解读：玩家遇到崩溃的概率可能降低。" if interpret else "• 修复崩溃")
        fetch.return_value = [article("1", 199500)]
        poll_updates(self.store, ai_key="key", ai_model="model", napcat_token="napcat")
        fetch.return_value = [article("2", 199800), article("1", 199500)]
        self.assertEqual(poll_updates(self.store, ai_key="key", ai_model="model",
                                      napcat_token="napcat"), 2)
        messages = {call.args[0]: call.args[1] for call in send.call_args_list}
        self.assertIn("• 修复崩溃", messages["123456789"])
        self.assertEqual(messages["987654321"], "简要解读：玩家遇到崩溃的概率可能降低。")
        self.assertEqual(translate.call_count, 2)

    @patch("qq_cs2_bot.cs2_updates.send_group_text", return_value="message-1")
    @patch("qq_cs2_bot.cs2_updates.translate_update", return_value="修复了一处崩溃。")
    @patch("qq_cs2_bot.cs2_updates.fetch_updates")
    @patch("qq_cs2_bot.cs2_updates.time.time", return_value=200000)
    def test_baseline_then_new_patch_sent_once(self, now, fetch, translate, send):
        with patch("qq_cs2_bot.esports_subscriptions.time.time", return_value=199000):
            self.store.set_news_enabled("123456789", True)
        fetch.return_value = [article("1", 199500)]
        self.assertEqual(poll_updates(self.store, ai_key="key", ai_model="model",
                                      napcat_token="napcat"), 0)
        fetch.return_value = [article("2", 199800), article("1", 199500)]
        self.assertEqual(poll_updates(self.store, ai_key="key", ai_model="model",
                                      napcat_token="napcat"), 1)
        self.assertEqual(poll_updates(self.store, ai_key="key", ai_model="model",
                                      napcat_token="napcat"), 0)
        translate.assert_called_once()
        send.assert_called_once()

    @patch("qq_cs2_bot.cs2_updates.send_group_text")
    @patch("qq_cs2_bot.cs2_updates.translate_update", side_effect=UpdateError("failed"))
    @patch("qq_cs2_bot.cs2_updates.fetch_updates")
    @patch("qq_cs2_bot.cs2_updates.time.time", return_value=200000)
    def test_translation_failure_does_not_send_english(self, now, fetch, translate, send):
        with patch("qq_cs2_bot.esports_subscriptions.time.time", return_value=199000):
            self.store.set_news_enabled("123456789", True)
        fetch.return_value = [article("1", 199500)]
        poll_updates(self.store, ai_key="key", ai_model="model", napcat_token="napcat")
        fetch.return_value = [article("2", 199800), article("1", 199500)]
        self.assertEqual(poll_updates(self.store, ai_key="key", ai_model="model",
                                      napcat_token="napcat"), 0)
        send.assert_not_called()
        self.assertEqual(len(self.store.pending_news()), 1)

    def test_patch_notes_keep_categories(self):
        self.assertIn("[ MAP SCRIPTING ]", clean_patch_notes(r"[p]\[ MAP SCRIPTING ][/p]"))

    def test_ai_prose_is_formatted_as_short_points(self):
        self.assertEqual(_format_points("修复崩溃\n2. 调整地图\n简要解读：可能影响比赛"),
                         "• 修复崩溃\n• 调整地图\n简要解读：可能影响比赛")

    @patch("qq_cs2_bot.cs2_updates.fetch_updates")
    def test_history_page_has_ten_absolute_entries(self, fetch):
        fetch.return_value = [article(str(n), n) for n in range(25, 0, -1)]
        rows, more = history_page(2)
        self.assertEqual([row["gid"] for row in rows], [str(n) for n in range(15, 5, -1)])
        self.assertTrue(more)

    @patch("qq_cs2_bot.esports_commands.history_page")
    @patch("qq_cs2_bot.cs2_updates.translate_update", return_value="• 修复了一处崩溃。")
    def test_history_number_waits_only_for_first_ai_query(self, translate, listing):
        listing.return_value = ([article(str(n), 200000 - n) for n in range(11, 21)], False)
        reply = command_reply(event(101, "#更新历史 2"), self.store, "token")
        self.assertIn("11｜", reply)
        waits = []
        detail = command_reply(event(102, "#11"), self.store, "token",
                               news_ai_key="key", news_ai_model="model",
                               on_wait=lambda: waits.append("正在查询，请稍后..."))
        self.assertEqual(waits, ["正在查询，请稍后..."])
        self.assertIn("• 修复了一处崩溃。", detail)
        self.assertEqual(command_reply(event(103, "#11"), self.store, "token",
                                       news_ai_key="key", on_wait=lambda: waits.append("again")), detail)
        self.assertEqual(len(waits), 1)
        translate.assert_called_once()

    @patch("qq_cs2_bot.esports_commands.history_page")
    def test_history_missing_ai_key_never_announces_wait(self, listing):
        listing.return_value = ([article("42", 200000)], False)
        command_reply(event(201, "#更新历史"), self.store, "token")
        waits = []
        reply = command_reply(event(202, "#1"), self.store, "token",
                              on_wait=lambda: waits.append("wait"))
        self.assertIn("翻译密钥", reply)
        self.assertFalse(waits)

    @patch("qq_cs2_bot.esports_commands.history_page")
    @patch("qq_cs2_bot.cs2_updates.translate_update")
    def test_history_interpret_switch_is_personal_and_uses_separate_cache(self, translate, listing):
        listing.return_value = ([article("42", 200000)], False)
        translate.side_effect = lambda item, key, model, interpret, **kwargs: (
            "• 修复崩溃\n简要解读：玩家遇到崩溃的概率可能降低。" if interpret else "• 修复崩溃")
        command_reply(event(301, "#更新历史"), self.store, "token")
        self.assertIn("已开", command_reply(event(302, "#更新解读 开"), self.store, "token"))
        enabled = command_reply(event(303, "#1"), self.store, "token", news_ai_key="key")
        self.assertIn("简要解读：", enabled)
        self.assertIn("已关", command_reply(event(304, "#更新解读 关"), self.store, "token"))
        disabled = command_reply(event(305, "#1"), self.store, "token", news_ai_key="key")
        self.assertNotIn("简要解读：", disabled)
        self.assertEqual(command_reply(event(306, "#1"), self.store, "token",
                                       news_ai_key="key"), disabled)
        self.assertEqual(translate.call_count, 2)
        other = event(307, "#更新解读 状态")
        other["user_id"] = 333333333
        self.assertIn("开", command_reply(other, self.store, "token", news_interpret=True))
        self.assertIn("关", command_reply(event(308, "#更新解读 状态"), self.store, "token"))

    @patch("qq_cs2_bot.esports_commands.history_page")
    @patch("qq_cs2_bot.cs2_updates.translate_update")
    def test_translation_switch_can_show_only_interpretation(self, translate, listing):
        listing.return_value = ([article("42", 200000)], False)
        translate.side_effect = lambda item, key, model, interpret, **kwargs: (
            "• 修复崩溃\n简要解读：玩家遇到崩溃的概率可能降低。" if interpret else "• 修复崩溃")
        command_reply(event(401, "#更新历史"), self.store, "token")
        command_reply(event(402, "#更新解读 开"), self.store, "token")
        full = command_reply(event(403, "#1"), self.store, "token", news_ai_key="key")
        self.assertIn("• 修复崩溃", full)
        command_reply(event(404, "#更新原文 关"), self.store, "token")
        only_interpret = command_reply(event(405, "#1"), self.store, "token", news_ai_key="key")
        self.assertIn("简要解读：", only_interpret)
        self.assertNotIn("• 修复崩溃", only_interpret)
        self.assertEqual(only_interpret, "简要解读：玩家遇到崩溃的概率可能降低。")
        self.assertEqual(translate.call_count, 1)
        self.assertIn("关", command_reply(event(406, "#更新译文 状态"), self.store, "token"))
        command_reply(event(407, "#更新解读 关"), self.store, "token")
        self.assertIn("均已关闭", command_reply(event(408, "#1"), self.store, "token"))
        command_reply(event(409, "#更新原文 开"), self.store, "token")
        self.assertIn("• 修复崩溃", command_reply(event(410, "#1"), self.store, "token",
                                            news_ai_key="key"))

    @patch("qq_cs2_bot.cs2_updates.build_opener")
    def test_ai_quota_error_has_actionable_message(self, opener):
        body = BytesIO(b'{"error":{"code":"credit_balance_exhausted"}}')
        error = HTTPError("https://api.openai.com/v1/responses", 429, "quota", {}, body)
        opener.return_value.open.side_effect = error
        with self.assertRaisesRegex(UpdateError, "额度不足"):
            translate_update(article("42", 200000), "secret", "model", False)
        error.close()

    @patch("qq_cs2_bot.cs2_updates.build_opener")
    def test_deepseek_uses_its_fixed_responses_endpoint(self, opener):
        payload = {"status": "completed", "output": [{"type": "message", "content": [
            {"type": "output_text", "text": "修复了一处崩溃。"}]}]}
        opener.return_value.open.return_value = BytesIO(json.dumps(payload).encode())
        result = translate_update(article("42", 200000), "secret", "deepseek-flash", False,
                                  provider="deepseek")
        self.assertIn("• 修复了一处崩溃。", result)
        request = opener.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.deepseek.com/responses")
        self.assertEqual(json.loads(request.data)["reasoning"], {"effort": "none"})
        self.assertNotIn("store", json.loads(request.data))

    @patch.dict("qq_cs2_bot.esports_service.os.environ", {
        "CS2_NEWS_AI_PROVIDER": "deepseek", "DEEPSEEK_API_KEY": "secret",
        "DEEPSEEK_MODEL": "deepseek-flash"})
    def test_deepseek_settings_ignore_openai_key(self):
        key, model, interpret, provider = news_settings()
        self.assertEqual((key, model, provider), ("secret", "deepseek-flash", "deepseek"))


if __name__ == "__main__":
    unittest.main()
