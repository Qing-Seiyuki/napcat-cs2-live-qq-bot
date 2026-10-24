"""Format a completed professional CS2 series from a permitted data feed."""
from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class MapResult:
    name: str
    first_score: int
    second_score: int


@dataclass(frozen=True)
class PlayerResult:
    name: str
    team: str
    kills: int | None = None
    deaths: int | None = None
    rating: float | None = None


@dataclass(frozen=True)
class SeriesResult:
    source_id: str
    event_name: str
    first_team: str
    second_team: str
    first_score: int
    second_score: int
    maps: tuple[MapResult, ...] = ()
    players: tuple[PlayerResult, ...] = ()
    source_url: str | None = None


def _label(value: str, limit: int = 70) -> str:
    return re.sub(r"[\x00-\x1f\x7f]", " ", value).strip()[:limit]


def render_series(result: SeriesResult) -> str:
    """Missing map/player statistics are omitted, never invented."""
    if not result.source_id or not result.first_team or not result.second_team:
        raise ValueError("赛事标识或队伍缺失")
    if any(type(score) is not int or score < 0 for score in (result.first_score, result.second_score)):
        raise ValueError("系列赛比分无效")
    lines = ["【CS2 赛事结果】" + _label(result.event_name),
             f"{_label(result.first_team)} {result.first_score}∶{result.second_score} {_label(result.second_team)}"]
    if result.maps:
        lines.append("地图：" + "；".join(
            f"{_label(game.name)} {game.first_score}∶{game.second_score}"
            for game in result.maps))
    else:
        lines.append("地图：当前数据源未提供")
    if result.players:
        lines.append("选手数据：")
        for player in result.players:
            parts = []
            if type(player.kills) is int and type(player.deaths) is int:
                parts.append(f"{player.kills}/{player.deaths}")
            if type(player.rating) in (int, float) and 0 <= player.rating < 10:
                parts.append(f"Rating {player.rating:.2f}")
            lines.append(f"{_label(player.team, 35)} {_label(player.name, 35)}" +
                         ("｜" + "｜".join(parts) if parts else ""))
    else:
        lines.append("选手数据：当前数据源未提供")
    if result.source_url == "https://www.pandascore.co/":
        lines.append("数据来源：PandaScore")
    elif result.source_url and result.source_url.startswith("https://"):
        lines.append("来源：" + result.source_url)
    return "\n".join(lines)
