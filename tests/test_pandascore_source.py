import json
import unittest
from unittest.mock import patch

from qq_cs2_bot.pandascore_source import fetch_match, finished_result


class _Response:
    def __init__(self, value):
        self.body = json.dumps(value).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, limit):
        return self.body[:limit]


def fixture():
    return {"id": 123, "status": "finished", "opponents": [
        {"opponent": {"id": 1, "name": "A"}},
        {"opponent": {"id": 2, "name": "B"}}],
        "results": [{"team_id": 1, "score": 2}, {"team_id": 2, "score": 1}],
        "tournament": {"name": "测试赛事"}}


class PandaScoreTests(unittest.TestCase):
    @patch("qq_cs2_bot.pandascore_source.build_opener")
    def test_fetch_exact_id_with_bearer_header(self, opener):
        opener.return_value.open.return_value = _Response([{"id": 999}, fixture()])
        self.assertEqual(fetch_match("123", "private-token")["id"], 123)
        request = opener.return_value.open.call_args.args[0]
        self.assertIn("filter%5Bid%5D=123", request.full_url)
        self.assertEqual(request.get_header("Authorization"), "Bearer private-token")
        self.assertNotIn("private-token", request.full_url)

    def test_waits_for_complete_result(self):
        match = fixture()
        match["status"] = "running"
        self.assertIsNone(finished_result(match))
        match["status"] = "finished"
        match["results"] = [{"team_id": 1, "score": 2}]
        self.assertIsNone(finished_result(match))
        match["results"].append({"team_id": 2, "score": 1})
        result = finished_result(match)
        self.assertEqual((result.first_score, result.second_score), (2, 1))
        self.assertEqual(result.players, ())


if __name__ == "__main__":
    unittest.main()
