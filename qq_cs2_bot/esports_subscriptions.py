"""Persistent, group-scoped subscriptions for professional CS2 matches.

No network requests or messages are sent from this module. Delivery is tracked per
group and match, so multiple group members receive a single group report.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import re
import sqlite3
import time


DB_PATH = Path(__file__).resolve().parent.parent / "data" / "esports.sqlite3"
MATCH_ID = re.compile(r"[1-9][0-9]{0,17}\Z")


class SubscriptionStore:
    def __init__(self, path: Path = DB_PATH):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS subscriptions (
                app TEXT NOT NULL, group_id TEXT NOT NULL, member TEXT NOT NULL,
                provider TEXT NOT NULL, match_id TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(app, group_id, member, provider, match_id))""")
            db.execute("""CREATE TABLE IF NOT EXISTS deliveries (
                app TEXT NOT NULL, group_id TEXT NOT NULL,
                provider TEXT NOT NULL, match_id TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('ready','sending','sent','unknown')),
                external_message_id TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(app, group_id, provider, match_id))""")
            db.execute("""CREATE TABLE IF NOT EXISTS command_events (
                app TEXT NOT NULL, group_id TEXT NOT NULL, message_id TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(app, group_id, message_id))""")
            db.execute("""CREATE TABLE IF NOT EXISTS browser_menus (
                group_id TEXT NOT NULL, member TEXT NOT NULL, options TEXT NOT NULL,
                expires_at INTEGER NOT NULL, PRIMARY KEY(group_id, member))""")
            db.execute("""CREATE TABLE IF NOT EXISTS cs2_news_meta (
                key TEXT PRIMARY KEY, value TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS cs2_news_groups (
                group_id TEXT PRIMARY KEY, enabled INTEGER NOT NULL,
                enabled_at INTEGER NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS cs2_news_articles (
                gid TEXT PRIMARY KEY, published INTEGER NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('seen','pending','ready')),
                message TEXT)""")
            db.execute("""CREATE TABLE IF NOT EXISTS cs2_news_deliveries (
                group_id TEXT NOT NULL, gid TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('ready','sending','sent','unknown')),
                external_message_id TEXT, message TEXT,
                PRIMARY KEY(group_id,gid))""")
            delivery_columns = {row["name"] for row in db.execute("PRAGMA table_info(cs2_news_deliveries)")}
            if "message" not in delivery_columns:
                db.execute("ALTER TABLE cs2_news_deliveries ADD COLUMN message TEXT")
            db.execute("""CREATE TABLE IF NOT EXISTS cs2_news_broadcast_preferences (
                group_id TEXT PRIMARY KEY, interpret INTEGER NOT NULL,
                show_translation INTEGER NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS cs2_news_history (
                gid TEXT PRIMARY KEY, published INTEGER NOT NULL,
                title TEXT NOT NULL, contents TEXT NOT NULL, url TEXT NOT NULL,
                message TEXT)""")
            columns = {row["name"] for row in db.execute("PRAGMA table_info(cs2_news_history)")}
            if "message_interpreted" not in columns:
                db.execute("ALTER TABLE cs2_news_history ADD COLUMN message_interpreted TEXT")
            db.execute("""UPDATE cs2_news_history SET message_interpreted=message,message=NULL
                WHERE message LIKE '%简要解读：%' AND message_interpreted IS NULL""")
            db.execute("""CREATE TABLE IF NOT EXISTS cs2_news_menus (
                group_id TEXT NOT NULL, member TEXT NOT NULL,
                page INTEGER NOT NULL, gids TEXT NOT NULL, expires_at INTEGER NOT NULL,
                PRIMARY KEY(group_id,member))""")
            db.execute("""CREATE TABLE IF NOT EXISTS cs2_news_preferences (
                group_id TEXT NOT NULL, member TEXT NOT NULL, interpret INTEGER NOT NULL,
                PRIMARY KEY(group_id,member))""")
            db.execute("""CREATE TABLE IF NOT EXISTS cs2_news_display_preferences (
                group_id TEXT NOT NULL, member TEXT NOT NULL, show_translation INTEGER NOT NULL,
                PRIMARY KEY(group_id,member))""")

    def cache_history_article(self, article: dict) -> None:
        with self.transaction() as db:
            db.execute("""INSERT OR IGNORE INTO cs2_news_history
                (gid,published,title,contents,url) VALUES(?,?,?,?,?)""",
                (article["gid"], article["date"], str(article.get("title") or ""),
                 str(article.get("contents") or ""), str(article.get("url") or "")))

    def get_history_article(self, gid: str) -> dict | None:
        with self.transaction() as db:
            row = db.execute("""SELECT gid,published AS date,title,contents,url,message,message_interpreted
                FROM cs2_news_history WHERE gid=?""", (gid,)).fetchone()
            return dict(row) if row else None

    def set_history_message(self, gid: str, message: str, *, interpret: bool = False) -> None:
        with self.transaction() as db:
            column = "message_interpreted" if interpret else "message"
            db.execute(f"UPDATE cs2_news_history SET {column}=? WHERE gid=?", (message, gid))

    def news_interpret_preference(self, group: str, member: str) -> bool | None:
        with self.transaction() as db:
            row = db.execute("""SELECT interpret FROM cs2_news_preferences
                WHERE group_id=? AND member=?""", (group, member)).fetchone()
            return bool(row["interpret"]) if row else None

    def set_news_interpret_preference(self, group: str, member: str, enabled: bool) -> None:
        with self.transaction() as db:
            db.execute("""INSERT INTO cs2_news_preferences(group_id,member,interpret)
                VALUES(?,?,?) ON CONFLICT(group_id,member) DO UPDATE SET
                interpret=excluded.interpret""", (group, member, int(enabled)))

    def news_translation_visible(self, group: str, member: str) -> bool:
        with self.transaction() as db:
            row = db.execute("""SELECT show_translation FROM cs2_news_display_preferences
                WHERE group_id=? AND member=?""", (group, member)).fetchone()
            return bool(row["show_translation"]) if row else True

    def set_news_translation_visible(self, group: str, member: str, visible: bool) -> None:
        with self.transaction() as db:
            db.execute("""INSERT INTO cs2_news_display_preferences(group_id,member,show_translation)
                VALUES(?,?,?) ON CONFLICT(group_id,member) DO UPDATE SET
                show_translation=excluded.show_translation""", (group, member, int(visible)))

    def set_news_menu(self, group: str, member: str, page: int, gids: list[str]) -> None:
        with self.transaction() as db:
            db.execute("""INSERT INTO cs2_news_menus(group_id,member,page,gids,expires_at)
                VALUES(?,?,?,?,?) ON CONFLICT(group_id,member) DO UPDATE SET
                page=excluded.page,gids=excluded.gids,expires_at=excluded.expires_at""",
                (group, member, page, json.dumps(gids), int(time.time()) + 900))
            db.execute("DELETE FROM browser_menus WHERE group_id=? AND member=?", (group, member))

    def news_menu_selection(self, group: str, member: str, number: int) -> str | None:
        """None means no menu, empty string means invalid number, otherwise a gid."""
        with self.transaction() as db:
            row = db.execute("""SELECT page,gids,expires_at FROM cs2_news_menus
                WHERE group_id=? AND member=?""", (group, member)).fetchone()
            if row is None or row["expires_at"] < int(time.time()):
                return None
            gids = json.loads(row["gids"])
            index = number - (row["page"] - 1) * 10 - 1
            return gids[index] if 0 <= index < len(gids) else ""

    def news_enabled(self, group: str) -> bool:
        with self.transaction() as db:
            row = db.execute("SELECT enabled FROM cs2_news_groups WHERE group_id=?", (group,)).fetchone()
            return bool(row and row["enabled"])

    def set_news_enabled(self, group: str, enabled: bool) -> None:
        with self.transaction() as db:
            db.execute("""INSERT INTO cs2_news_groups(group_id,enabled,enabled_at)
                VALUES(?,?,?) ON CONFLICT(group_id) DO UPDATE SET
                enabled=excluded.enabled,enabled_at=excluded.enabled_at""",
                (group, int(enabled), int(time.time())))
            if not enabled:
                db.execute("DELETE FROM cs2_news_deliveries WHERE group_id=? AND status='ready'", (group,))

    def news_broadcast_settings(self, group: str, default_interpret: bool = False) -> tuple[bool, bool]:
        with self.transaction() as db:
            row = db.execute("""SELECT interpret,show_translation FROM cs2_news_broadcast_preferences
                WHERE group_id=?""", (group,)).fetchone()
            return (bool(row["interpret"]), bool(row["show_translation"])) if row else (default_interpret, True)

    def set_news_broadcast_settings(self, group: str, interpret: bool, show_translation: bool) -> None:
        if not interpret and not show_translation:
            raise ValueError("群播报至少要显示中文译文或 AI 解读")
        with self.transaction() as db:
            db.execute("""INSERT INTO cs2_news_broadcast_preferences(group_id,interpret,show_translation)
                VALUES(?,?,?) ON CONFLICT(group_id) DO UPDATE SET
                interpret=excluded.interpret,show_translation=excluded.show_translation""",
                (group, int(interpret), int(show_translation)))

    def news_audience_settings(self, published: int, default_interpret: bool = False) -> dict[str, tuple[bool, bool]]:
        with self.transaction() as db:
            rows = db.execute("""SELECT g.group_id,p.interpret,p.show_translation
                FROM cs2_news_groups g LEFT JOIN cs2_news_broadcast_preferences p
                ON p.group_id=g.group_id WHERE g.enabled=1 AND g.enabled_at<=?""", (published,)).fetchall()
            return {row["group_id"]: (bool(row["interpret"]) if row["interpret"] is not None
                                      else default_interpret,
                                      bool(row["show_translation"]) if row["show_translation"] is not None
                                      else True) for row in rows}

    def news_initialized(self) -> bool:
        with self.transaction() as db:
            return db.execute("SELECT 1 FROM cs2_news_meta WHERE key='initialized'").fetchone() is not None

    def seed_news(self, articles: list[dict]) -> None:
        with self.transaction() as db:
            for article in articles:
                db.execute("""INSERT OR IGNORE INTO cs2_news_articles(gid,published,status)
                    VALUES(?,?,'seen')""", (article["gid"], article["date"]))
            db.execute("INSERT OR IGNORE INTO cs2_news_meta(key,value) VALUES('initialized','1')")

    def add_news(self, article: dict, *, eligible: bool) -> None:
        with self.transaction() as db:
            db.execute("""INSERT OR IGNORE INTO cs2_news_articles(gid,published,status)
                VALUES(?,?,?)""", (article["gid"], article["date"],
                                   "pending" if eligible else "seen"))

    def pending_news(self) -> list[dict]:
        with self.transaction() as db:
            rows = db.execute("""SELECT gid,published FROM cs2_news_articles
                WHERE status='pending' ORDER BY published LIMIT 30""").fetchall()
            return [dict(row) for row in rows]

    def news_has_audience(self, published: int) -> bool:
        with self.transaction() as db:
            return db.execute("""SELECT 1 FROM cs2_news_groups
                WHERE enabled=1 AND enabled_at<=? LIMIT 1""", (published,)).fetchone() is not None

    def skip_news(self, gid: str) -> None:
        with self.transaction() as db:
            db.execute("UPDATE cs2_news_articles SET status='seen' WHERE gid=? AND status='pending'", (gid,))

    def prepare_news(self, gid: str, messages: dict[str, str]) -> None:
        with self.transaction() as db:
            row = db.execute("SELECT published FROM cs2_news_articles WHERE gid=? AND status='pending'",
                             (gid,)).fetchone()
            if row is None:
                return
            db.execute("UPDATE cs2_news_articles SET status='ready' WHERE gid=?", (gid,))
            for group, message in messages.items():
                db.execute("""INSERT OR IGNORE INTO cs2_news_deliveries(group_id,gid,status,message)
                    SELECT group_id,?,'ready',? FROM cs2_news_groups
                    WHERE group_id=? AND enabled=1 AND enabled_at<=?""",
                    (gid, message, group, row["published"]))

    def ready_news_deliveries(self) -> list[dict]:
        with self.transaction() as db:
            rows = db.execute("""SELECT d.group_id,d.gid,COALESCE(d.message,a.message) AS message FROM cs2_news_deliveries d
                JOIN cs2_news_articles a ON a.gid=d.gid
                JOIN cs2_news_groups g ON g.group_id=d.group_id
                WHERE d.status='ready' AND g.enabled=1 AND g.enabled_at<=a.published
                ORDER BY a.published LIMIT 30""").fetchall()
            return [dict(row) for row in rows]

    def claim_news_delivery(self, group: str, gid: str) -> bool:
        with self.transaction() as db:
            result = db.execute("""UPDATE cs2_news_deliveries SET status='sending'
                WHERE group_id=? AND gid=? AND status='ready'
                AND EXISTS (SELECT 1 FROM cs2_news_groups g JOIN cs2_news_articles a
                    ON a.gid=cs2_news_deliveries.gid WHERE g.group_id=cs2_news_deliveries.group_id
                    AND g.enabled=1 AND g.enabled_at<=a.published)""", (group, gid))
            return bool(result.rowcount)

    def finish_news_delivery(self, group: str, gid: str, message_id: str | None) -> None:
        with self.transaction() as db:
            db.execute("""UPDATE cs2_news_deliveries SET status=?,external_message_id=?
                WHERE group_id=? AND gid=? AND status='sending'""",
                ("sent" if message_id else "unknown", message_id, group, gid))

    def set_browser(self, group: str, member: str, options: list) -> None:
        import time
        with self.transaction() as db:
            db.execute("""INSERT INTO browser_menus(group_id,member,options,expires_at)
                VALUES(?,?,?,?) ON CONFLICT(group_id,member) DO UPDATE SET
                options=excluded.options,expires_at=excluded.expires_at""",
                (group, member, json.dumps(options, ensure_ascii=False), int(time.time()) + 900))
            db.execute("DELETE FROM cs2_news_menus WHERE group_id=? AND member=?", (group, member))

    def get_browser(self, group: str, member: str) -> list | None:
        import time
        with self.transaction() as db:
            row = db.execute("SELECT options,expires_at FROM browser_menus WHERE group_id=? AND member=?",
                             (group, member)).fetchone()
            if row is None or row["expires_at"] < int(time.time()):
                return None
            return json.loads(row["options"])

    def clear_browser(self, group: str, member: str) -> None:
        with self.transaction() as db:
            db.execute("DELETE FROM browser_menus WHERE group_id=? AND member=?", (group, member))

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def subscribe(self, app: str, group: str, member: str, provider: str, match_id: str) -> bool:
        if not all(isinstance(x, str) and x for x in (app, group, member)):
            raise ValueError("缺少可信群或成员身份")
        if provider not in ("pandascore", "grid") or not isinstance(match_id, str) or not MATCH_ID.fullmatch(match_id):
            raise ValueError("赛事来源或比赛 ID 无效")
        with self.transaction() as db:
            existing = db.execute("""SELECT 1 FROM subscriptions WHERE
                app=? AND group_id=? AND member=? AND provider=? AND match_id=?""",
                (app, group, member, provider, match_id)).fetchone()
            if existing:
                return False
            member_count = db.execute("""SELECT COUNT(*) FROM subscriptions WHERE
                app=? AND group_id=? AND member=?""", (app, group, member)).fetchone()[0]
            group_count = db.execute("""SELECT COUNT(DISTINCT provider || ':' || match_id)
                FROM subscriptions WHERE app=? AND group_id=?""", (app, group)).fetchone()[0]
            if member_count >= 10 or group_count >= 30:
                raise ValueError("订阅数量已达上限")
            old = db.execute("""SELECT status FROM deliveries
                WHERE app=? AND group_id=? AND provider=? AND match_id=?""",
                (app, group, provider, match_id)).fetchone()
            if old and old["status"] in ("sending", "sent", "unknown"):
                raise ValueError("这场比赛的群播报已经处理，不能再次订阅")
            inserted = db.execute("""INSERT OR IGNORE INTO subscriptions
                (app,group_id,member,provider,match_id) VALUES(?,?,?,?,?)""",
                (app, group, member, provider, match_id))
            return bool(inserted.rowcount)

    def claim_event(self, app: str, group: str, message_id: str) -> bool:
        with self.transaction() as db:
            db.execute("DELETE FROM command_events WHERE created_at < datetime('now', '-7 days')")
            inserted = db.execute("""INSERT OR IGNORE INTO command_events
                (app,group_id,message_id) VALUES(?,?,?)""", (app, group, message_id))
            return bool(inserted.rowcount)

    def unsubscribe(self, app: str, group: str, member: str, provider: str, match_id: str) -> bool:
        with self.transaction() as db:
            deleted = db.execute("""DELETE FROM subscriptions WHERE
                app=? AND group_id=? AND member=? AND provider=? AND match_id=?""",
                (app, group, member, provider, match_id))
            remaining = db.execute("""SELECT 1 FROM subscriptions WHERE
                app=? AND group_id=? AND provider=? AND match_id=? LIMIT 1""",
                (app, group, provider, match_id)).fetchone()
            if not remaining:
                db.execute("""DELETE FROM deliveries WHERE
                    app=? AND group_id=? AND provider=? AND match_id=? AND status='ready'""",
                    (app, group, provider, match_id))
            return bool(deleted.rowcount)

    def list_member(self, app: str, group: str, member: str) -> list[dict]:
        with self.transaction() as db:
            rows = db.execute("""SELECT provider,match_id,created_at FROM subscriptions
                WHERE app=? AND group_id=? AND member=? ORDER BY created_at,provider,match_id""",
                (app, group, member)).fetchall()
            return [dict(row) for row in rows]

    def active_matches(self, provider: str) -> list[str]:
        with self.transaction() as db:
            rows = db.execute("""SELECT DISTINCT s.match_id FROM subscriptions s WHERE
                s.provider=? AND NOT EXISTS (SELECT 1 FROM deliveries d WHERE
                d.app=s.app AND d.group_id=s.group_id AND d.provider=s.provider
                AND d.match_id=s.match_id AND d.status IN ('sending','sent','unknown'))
                ORDER BY s.match_id""", (provider,)).fetchall()
            return [row["match_id"] for row in rows]

    def subscribed_groups(self, provider: str, match_id: str) -> list[tuple[str, str]]:
        with self.transaction() as db:
            rows = db.execute("""SELECT DISTINCT app,group_id FROM subscriptions
                WHERE provider=? AND match_id=?""", (provider, match_id)).fetchall()
            return [(row["app"], row["group_id"]) for row in rows]

    def queue_if_subscribed(self, app: str, group: str, provider: str, match_id: str) -> bool:
        with self.transaction() as db:
            subscribed = db.execute("""SELECT 1 FROM subscriptions WHERE
                app=? AND group_id=? AND provider=? AND match_id=? LIMIT 1""",
                (app, group, provider, match_id)).fetchone()
            if not subscribed:
                return False
            inserted = db.execute("""INSERT OR IGNORE INTO deliveries
                (app,group_id,provider,match_id,status) VALUES(?,?,?,?,'ready')""",
                (app, group, provider, match_id))
            return bool(inserted.rowcount)

    def ready_groups(self, provider: str, match_id: str) -> list[tuple[str, str]]:
        with self.transaction() as db:
            rows = db.execute("""SELECT d.app,d.group_id FROM deliveries d WHERE
                d.provider=? AND d.match_id=? AND d.status='ready' AND EXISTS (
                SELECT 1 FROM subscriptions s WHERE s.app=d.app AND s.group_id=d.group_id
                AND s.provider=d.provider AND s.match_id=d.match_id)""",
                (provider, match_id)).fetchall()
            return [(row["app"], row["group_id"]) for row in rows]

    def claim_delivery(self, app: str, group: str, provider: str, match_id: str) -> bool:
        """Only one worker may send; uncertain outcomes are never blindly retried."""
        with self.transaction() as db:
            changed = db.execute("""UPDATE deliveries SET status='sending',updated_at=CURRENT_TIMESTAMP
                WHERE app=? AND group_id=? AND provider=? AND match_id=? AND status='ready'
                AND EXISTS (SELECT 1 FROM subscriptions s WHERE s.app=deliveries.app
                    AND s.group_id=deliveries.group_id AND s.provider=deliveries.provider
                    AND s.match_id=deliveries.match_id)""",
                (app, group, provider, match_id))
            return bool(changed.rowcount)

    def finish_delivery(self, app: str, group: str, provider: str, match_id: str,
                        message_id: str | None) -> None:
        status = "sent" if message_id else "unknown"
        with self.transaction() as db:
            changed = db.execute("""UPDATE deliveries SET status=?,external_message_id=?,
                updated_at=CURRENT_TIMESTAMP WHERE app=? AND group_id=? AND provider=?
                AND match_id=? AND status='sending'""",
                (status, message_id, app, group, provider, match_id))
            if not changed.rowcount:
                raise ValueError("播报任务未处于发送中状态")
