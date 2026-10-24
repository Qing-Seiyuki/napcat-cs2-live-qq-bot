import os
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from qq_cs2_bot.binding_link import link_for_request


class BindingLinkTests(unittest.TestCase):
    def test_only_pending_request_in_configured_database_gets_link(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bindings.sqlite3"
            with closing(sqlite3.connect(path)) as db:
                with db:
                    db.execute("CREATE TABLE bindings (request_id TEXT, status TEXT)")
                    db.executemany("INSERT INTO bindings VALUES (?, ?)", [
                        ("a" * 32, "pending"), ("b" * 32, "verified")])
            settings = {"QQ_BINDINGS_DB": str(path),
                        "STEAM_VERIFY_PUBLIC_URL": "https://bot.example.com"}
            with patch.dict(os.environ, settings):
                self.assertEqual(link_for_request("a" * 32),
                                 "https://bot.example.com/verify/" + "a" * 32)
                self.assertIsNone(link_for_request("b" * 32))
                self.assertIsNone(link_for_request("c" * 32))
                self.assertIsNone(link_for_request("../"))


if __name__ == "__main__":
    unittest.main()
