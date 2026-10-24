import json
import unittest
from unittest.mock import patch

from qq_cs2_bot.napcat_sender import SendError, send_group_text


class _Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, limit):
        return self.payload[:limit]


class SenderTests(unittest.TestCase):
    @patch("qq_cs2_bot.napcat_sender.build_opener")
    def test_local_sender_uses_plain_text_segment(self, opener):
        opener.return_value.open.return_value = _Response({"status": "ok", "retcode": 0,
                                                            "data": {"message_id": 123}})
        self.assertEqual(send_group_text("123456789", "[CQ:at,qq=all]", access_token="fake"), "123")
        request = opener.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:3000/send_group_msg")
        body = json.loads(request.data)
        self.assertEqual(body["message"], [{"type": "text", "data": {"text": "[CQ:at,qq=all]"}}])

    @patch("qq_cs2_bot.napcat_sender.build_opener")
    def test_failed_response_is_not_treated_as_delivered(self, opener):
        opener.return_value.open.return_value = _Response({"status": "failed", "retcode": 100,
                                                            "data": None})
        with self.assertRaises(SendError):
            send_group_text("123456789", "战报", access_token="fake")


if __name__ == "__main__":
    unittest.main()
