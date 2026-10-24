"""PandaScore's licensed CS2 fixtures feed: schedule and series results."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .esports_result import SeriesResult


BASE = "https://api.pandascore.co"


class SourceError(Exception):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _fetch_list(path: str, token: str) -> list[dict]:
    if not isinstance(token, str) or not token:
        raise ValueError("未配置 PandaScore 访问令牌")
    request = Request(BASE + path,
                      headers={"Accept": "application/json", "Authorization": "Bearer " + token})
    try:
        with build_opener(_NoRedirect()).open(request, timeout=15) as response:
            body = response.read(2_000_001)
    except (HTTPError, URLError, OSError):
        raise SourceError("PandaScore 比赛列表暂不可用") from None
    if len(body) > 2_000_000:
        raise SourceError("PandaScore 响应过大")
    try:
        rows = json.loads(body)
    except ValueError:
        raise SourceError("PandaScore 返回了无效数据") from None
    if not isinstance(rows, list):
        raise SourceError("PandaScore 比赛列表格式异常")
    return rows


def fetch_match(match_id: str, token: str) -> dict | None:
    """Get one exact match from the all-plan list endpoint; None means not found."""
    if not isinstance(match_id, str) or not re.fullmatch(r"[1-9][0-9]{0,17}", match_id):
        raise ValueError("PandaScore 比赛 ID 无效")
    rows = _fetch_list(f"/csgo/matches?filter%5Bid%5D={match_id}&per_page=1", token)
    return next((row for row in rows if isinstance(row, dict) and str(row.get("id")) == match_id), None)


def upcoming_matches(token: str) -> list[dict]:
    """Small list used to discover the IDs accepted by the subscription command."""
    rows = _fetch_list("/csgo/matches/upcoming?per_page=10", token)
    return [row for row in rows if isinstance(row, dict) and type(row.get("id")) is int]


CHINA_TIME = timezone(timedelta(hours=8))


def today_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    """The bot's 'today' runs from 12:00 China time to 12:00 the next day."""
    local = (now or datetime.now(timezone.utc)).astimezone(CHINA_TIME)
    start = local.replace(hour=12, minute=0, second=0, microsecond=0)
    if local < start:
        start -= timedelta(days=1)
    return start, start + timedelta(days=1)


def today_matches(token: str, now: datetime | None = None) -> tuple[datetime, datetime, list[dict]]:
    start, end = today_window(now)
    params = {"range[begin_at]": start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") + "," +
              end.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "filter[videogame_title]": "cs-2", "sort": "begin_at"}
    rows = []
    for page in range(1, 26):
        query = params | {"per_page": 20, "page": page}
        batch = _fetch_list("/csgo/matches?" + urlencode(query), token)
        for row in batch:
            if not isinstance(row, dict) or type(row.get("id")) is not int:
                continue
            try:
                moment = datetime.fromisoformat(row["begin_at"].replace("Z", "+00:00")).astimezone(CHINA_TIME)
            except (KeyError, AttributeError, ValueError):
                continue
            if start <= moment < end and row.get("status") in ("not_started", "running", "finished"):
                rows.append(row)
        if len(batch) < 20:
            break
    rows.sort(key=lambda row: (row.get("begin_at") or "", row["id"]))
    return start, end, rows


def finished_result(match: dict) -> SeriesResult | None:
    """Only produce a report when a complete two-team final score is present."""
    if not isinstance(match, dict) or match.get("status") != "finished":
        return None
    opponents = match.get("opponents")
    results = match.get("results")
    if not isinstance(opponents, list) or len(opponents) != 2 or not isinstance(results, list):
        return None
    teams = []
    for entry in opponents:
        if not isinstance(entry, dict) or not isinstance(entry.get("opponent"), dict):
            return None
        item = entry["opponent"]
        if type(item.get("id")) is not int or not isinstance(item.get("name"), str) or not item["name"]:
            return None
        teams.append((item["id"], item["name"]))
    score_by_team = {}
    for entry in results:
        if not isinstance(entry, dict) or type(entry.get("team_id")) is not int:
            continue
        score = entry.get("score")
        if type(score) is int and score >= 0:
            score_by_team[entry["team_id"]] = score
    if len(score_by_team) < 2 or any(team_id not in score_by_team for team_id, _ in teams):
        return None
    tournament = match.get("tournament")
    league = match.get("league")
    event = (tournament.get("name") if isinstance(tournament, dict) else None) or (
        league.get("name") if isinstance(league, dict) else None) or "职业比赛"
    if score_by_team[teams[0][0]] == score_by_team[teams[1][0]] == 0:
        return None
    return SeriesResult(str(match.get("id", "")), str(event), teams[0][1], teams[1][1],
                        score_by_team[teams[0][0]], score_by_team[teams[1][0]],
                        source_url="https://www.pandascore.co/")
