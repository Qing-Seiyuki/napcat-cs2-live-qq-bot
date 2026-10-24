import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from qq_cs2_bot.esports_commands import command_reply
from qq_cs2_bot import esports_browser
from qq_cs2_bot.esports_subscriptions import SubscriptionStore


def event(message_id, text, member=111):
    return {"post_type": "message", "message_type": "group", "group_id": 123456789,
            "user_id": member, "self_id": 222, "message_id": message_id,
            "message": [{"type": "text", "data": {"text": text}}]}


SERIES = {"id": 8751, "name": "Shanghai Major", "year": 2024,
          "slug": "cs-go-perfect-world-major-shanghai-major-2024",
          "league": {"name": "Perfect World Major"}}
STAGES = [{"id": 1, "name": "Opening Stage", "begin_at": "2024-12-01T00:00:00Z"},
          {"id": 2, "name": "Elimination Stage", "begin_at": "2024-12-04T00:00:00Z"},
          {"id": 3, "name": "Playoffs", "begin_at": "2024-12-12T00:00:00Z"}]
MATCH = {"id": 1079435, "status": "finished", "begin_at": "2024-12-15T09:00:00Z",
         "opponents": [{"opponent": {"id": 1, "name": "Spirit"}},
                       {"opponent": {"id": 2, "name": "FaZe"}}],
         "results": [{"team_id": 1, "score": 2}, {"team_id": 2, "score": 1}],
         "league": SERIES["league"], "serie": SERIES,
         "tournament": STAGES[2]}


class BrowserTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = SubscriptionStore(Path(folder.name) / "esports.db")

    @patch("qq_cs2_bot.esports_browser.fetch_match", return_value=MATCH)
    @patch("qq_cs2_bot.esports_browser._matches", return_value=[MATCH])
    @patch("qq_cs2_bot.esports_browser._stages", return_value=STAGES)
    @patch("qq_cs2_bot.esports_browser._series", return_value=[SERIES])
    def test_number_navigation_and_direct_match_id(self, series, stages, matches, fetch):
        reply = command_reply(event(1, "#赛事 上海major 2024"), self.store, "token")
        self.assertIn("3. 冠军组", reply)
        self.assertIsNone(command_reply(event(2, "#3", 333), self.store, "token"))
        reply = command_reply(event(3, "#3"), self.store, "token")
        self.assertIn("1. Spirit vs FaZe", reply)
        reply = command_reply(event(4, "#1"), self.store, "token")
        self.assertIn("Spirit vs FaZe｜2∶1", reply)
        self.assertIsNone(command_reply(event(5, "#1"), self.store, "token"))
        reply = command_reply(event(6, "#赛事 1079435"), self.store, "token")
        self.assertIn("比赛 ID：1079435", reply)
        reply = command_reply(event(7, "#1079435"), self.store, "token")
        self.assertIn("比赛 ID：1079435", reply)
        self.assertEqual(fetch.call_count, 3)

    @patch("qq_cs2_bot.esports_browser._stages", return_value=STAGES)
    @patch("qq_cs2_bot.esports_browser._series", return_value=[SERIES])
    def test_stage_alias_and_year_choice(self, series, stages):
        reply = command_reply(event(1, "#赛事 上海major"), self.store, "token")
        self.assertIn("1. 上海 Major 2024", reply)
        reply = command_reply(event(2, "#1"), self.store, "token")
        self.assertIn("第一阶段", reply)
        with patch("qq_cs2_bot.esports_browser._matches", return_value=[MATCH]):
            reply = command_reply(event(3, "#赛事 上海major 2024 冠军组"), self.store, "token")
        self.assertIn("Spirit vs FaZe", reply)

    def test_recent_major_filters_time_and_tier_and_keeps_number_navigation(self):
        now = datetime.now(timezone.utc)
        def tournament(id, tier, start_days, end_days):
            return {"id": id, "tier": tier, "begin_at": (now + timedelta(days=start_days)).isoformat(),
                    "end_at": (now + timedelta(days=end_days)).isoformat(),
                    "name": "Playoffs", "league": {"name": "IEM"},
                    "serie": {"id": id, "name": "Beijing", "slug": f"cs-go-iem-beijing-{id}",
                              "year": 2026, "begin_at": (now + timedelta(days=start_days)).isoformat(),
                              "end_at": (now + timedelta(days=end_days)).isoformat()}}
        rows = [tournament(1, "s", -2, 2), tournament(2, "a", -6, -2),
                tournament(3, "b", -2, 2), tournament(4, "s", -8, -4),
                tournament(5, "s", 1, 3)]
        esports_browser._recent_cache = None
        with patch("qq_cs2_bot.esports_browser._fetch_list", return_value=rows):
            reply = command_reply(event(10, "#近期赛事"), self.store, "token")
        self.assertIn("1. IEM 北京 2026｜进行中｜S级", reply)
        self.assertIn("2. IEM 北京 2026｜刚结束｜A级", reply)
        self.assertNotIn("B级", reply)
        with patch("qq_cs2_bot.esports_browser._stages", return_value=STAGES):
            reply = command_reply(event(11, "#1"), self.store, "token")
        self.assertIn("选择赛程阶段", reply)
        esports_browser._recent_cache = None


if __name__ == "__main__":
    unittest.main()
