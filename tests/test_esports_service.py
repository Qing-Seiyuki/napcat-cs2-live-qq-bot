import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from qq_cs2_bot.esports_commands import command_reply
from qq_cs2_bot.esports_service import poll_once
from qq_cs2_bot.esports_subscriptions import SubscriptionStore
from qq_cs2_bot.pandascore_source import today_window, today_matches
from test_pandascore_source import fixture


def event(message_id, text):
    return {"post_type": "message", "message_type": "group", "group_id": 123456789,
            "user_id": 111111111, "self_id": 222222222, "message_id": message_id,
            "message": [{"type": "text", "data": {"text": text}}]}


class EsportsServiceTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = SubscriptionStore(Path(folder.name) / "esports.sqlite3")

    @patch("qq_cs2_bot.esports_commands.fetch_match", return_value={"id": 123, "status": "not_started"})
    def test_group_member_can_subscribe_cancel_and_duplicates_do_not_repeat(self, fetch):
        self.assertIn("已订阅", command_reply(event(1, "#赛事订阅 123"), self.store, "fake-token"))
        self.assertIsNone(command_reply(event(1, "#赛事订阅 123"), self.store, "fake-token"))
        self.assertIn("123", command_reply(event(2, "#我的赛事"), self.store, "fake-token"))
        self.assertIn("已取消", command_reply(event(3, "#赛事取消 123"), self.store, "fake-token"))
        self.assertEqual(self.store.active_matches("pandascore"), [])
        fetch.assert_called_once()

    @patch("qq_cs2_bot.esports_service.send_group_text", return_value="msg-1")
    @patch("qq_cs2_bot.esports_service.fetch_match", return_value=fixture())
    def test_finished_match_sends_once_per_group(self, fetch, send):
        self.store.subscribe("napcat", "123456789", "alice", "pandascore", "123")
        self.store.subscribe("napcat", "123456789", "bob", "pandascore", "123")
        self.assertEqual(poll_once(self.store, "source-token", "napcat-token"), 1)
        self.assertEqual(poll_once(self.store, "source-token", "napcat-token"), 0)
        send.assert_called_once()
        fetch.assert_called_once()

    def test_help_requires_prefix_or_mention_of_this_bot(self):
        self.assertIsNone(command_reply(event(1, "help"), self.store, "token"))
        self.assertIsNone(command_reply(event(2, "赛事订阅 123"), self.store, "token"))
        self.assertIn("#今日比赛", command_reply(event(3, "#help"), self.store, "token"))
        mentioned = event(4, " help")
        mentioned["message"].insert(0, {"type": "at", "data": {"qq": "222222222"}})
        self.assertIn("#近期赛事", command_reply(mentioned, self.store, "token"))
        other = event(5, " help")
        other["message"].insert(0, {"type": "at", "data": {"qq": "333333333"}})
        self.assertIsNone(command_reply(other, self.store, "token"))

    @patch("qq_cs2_bot.esports_commands.link_for_request", return_value="https://bot.example.com/verify/" + "a" * 32)
    def test_group_member_can_request_steam_verification_link(self, lookup):
        reply = command_reply(event(50, "#绑定链接 " + "a" * 32), self.store, "token")
        self.assertIn("https://bot.example.com/verify/", reply)
        self.assertIsNone(command_reply(event(50, "#绑定链接 " + "a" * 32), self.store, "token"))
        lookup.assert_called_once_with("a" * 32)

    @patch("qq_cs2_bot.esports_commands.today_match_menu", return_value="今日比赛测试")
    def test_today_command_only_with_prefix(self, menu):
        self.assertIsNone(command_reply(event(1, "今日比赛"), self.store, "token"))
        self.assertEqual(command_reply(event(2, "#今日比赛"), self.store, "token"), "今日比赛测试")
        menu.assert_called_once()

    def test_today_window_changes_at_noon_and_filters_edges(self):
        before = datetime(2026, 10, 23, 3, 59, tzinfo=timezone.utc)
        at_noon = datetime(2026, 10, 23, 4, 0, tzinfo=timezone.utc)
        self.assertEqual(today_window(before)[0].isoformat(), "2026-10-22T12:00:00+08:00")
        self.assertEqual(today_window(at_noon)[0].isoformat(), "2026-10-23T12:00:00+08:00")
        rows = [{"id": 1, "begin_at": "2026-10-23T03:59:59Z", "status": "finished"},
                {"id": 2, "begin_at": "2026-10-23T04:00:00Z", "status": "finished"},
                {"id": 3, "begin_at": "2026-10-24T03:59:59Z", "status": "not_started"},
                {"id": 4, "begin_at": "2026-10-24T04:00:00Z", "status": "not_started"},
                {"id": 5, "begin_at": "2026-10-23T08:00:00Z", "status": "canceled"}]
        with patch("qq_cs2_bot.pandascore_source._fetch_list", return_value=rows) as fetch:
            _, _, found = today_matches("token", at_noon)
        self.assertEqual([row["id"] for row in found], [2, 3])
        self.assertIn("range%5Bbegin_at%5D", fetch.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
