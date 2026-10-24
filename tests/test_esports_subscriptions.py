import tempfile
import unittest
from pathlib import Path

from qq_cs2_bot.esports_result import MapResult, PlayerResult, SeriesResult, render_series
from qq_cs2_bot.esports_subscriptions import SubscriptionStore


class SubscriptionTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = SubscriptionStore(Path(folder.name) / "esports.sqlite3")

    def test_two_members_one_group_delivery(self):
        self.assertTrue(self.store.subscribe("app", "group", "alice", "pandascore", "123"))
        self.assertTrue(self.store.subscribe("app", "group", "bob", "pandascore", "123"))
        self.assertFalse(self.store.subscribe("app", "group", "bob", "pandascore", "123"))
        self.assertTrue(self.store.queue_if_subscribed("app", "group", "pandascore", "123"))
        self.assertFalse(self.store.queue_if_subscribed("app", "group", "pandascore", "123"))
        self.assertEqual(self.store.ready_groups("pandascore", "123"), [("app", "group")])
        self.assertTrue(self.store.claim_delivery("app", "group", "pandascore", "123"))
        self.assertFalse(self.store.claim_delivery("app", "group", "pandascore", "123"))
        self.store.finish_delivery("app", "group", "pandascore", "123", "message-1")
        self.assertEqual(self.store.ready_groups("pandascore", "123"), [])
        with self.assertRaises(ValueError):
            self.store.subscribe("app", "group", "charlie", "pandascore", "123")

    def test_cancel_only_own_subscription_and_prevent_delivery_without_members(self):
        self.store.subscribe("app", "group", "alice", "pandascore", "123")
        self.store.subscribe("app", "group", "bob", "pandascore", "123")
        self.store.queue_if_subscribed("app", "group", "pandascore", "123")
        self.assertTrue(self.store.unsubscribe("app", "group", "alice", "pandascore", "123"))
        self.assertEqual(self.store.ready_groups("pandascore", "123"), [("app", "group")])
        self.assertTrue(self.store.unsubscribe("app", "group", "bob", "pandascore", "123"))
        self.assertEqual(self.store.ready_groups("pandascore", "123"), [])

    def test_unknown_send_result_is_not_retried(self):
        self.store.subscribe("app", "group", "alice", "pandascore", "123")
        self.store.queue_if_subscribed("app", "group", "pandascore", "123")
        self.store.claim_delivery("app", "group", "pandascore", "123")
        self.store.finish_delivery("app", "group", "pandascore", "123", None)
        self.assertFalse(self.store.claim_delivery("app", "group", "pandascore", "123"))

    def test_source_validation(self):
        with self.assertRaises(ValueError):
            self.store.subscribe("app", "group", "alice", "hltv", "123")
        with self.assertRaises(ValueError):
            self.store.subscribe("app", "group", "alice", "pandascore", "bad")


class ResultTests(unittest.TestCase):
    def test_only_available_data_are_rendered(self):
        match = SeriesResult("123", "赛事", "A", "B", 2, 1,
                             (MapResult("Nuke", 13, 8),),
                             (PlayerResult("选手", "A", 20, 14, 1.25),))
        text = render_series(match)
        self.assertIn("A 2∶1 B", text)
        self.assertIn("Nuke 13∶8", text)
        self.assertIn("20/14｜Rating 1.25", text)


if __name__ == "__main__":
    unittest.main()
