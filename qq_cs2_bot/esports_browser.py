"""Browse PandaScore series, stages and matches from QQ group messages."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
import time
from urllib.parse import urlencode

from .pandascore_source import SourceError, _fetch_list, fetch_match, today_matches


CITY = {"上海": "shanghai", "巴黎": "paris", "北京": "beijing", "科隆": "cologne",
        "卡托维兹": "katowice", "哥本哈根": "copenhagen", "奥斯汀": "austin",
        "布达佩斯": "budapest", "里约": "rio", "斯德哥尔摩": "stockholm",
        "柏林": "berlin", "波士顿": "boston", "伦敦": "london", "达拉斯": "dallas",
        "悉尼": "sydney", "成都": "chengdu", "重庆": "chongqing"}
STAGES = {"opening stage": "第一阶段（揭幕赛／挑战者组）",
          "elimination stage": "第二阶段（淘汰赛／传奇组）",
          "playoffs": "冠军组（淘汰赛）", "playoff": "冠军组（淘汰赛）",
          "challengers stage": "挑战者组", "legends stage": "传奇组",
          "champions stage": "冠军组", "group stage": "小组赛",
          "groups": "小组赛", "grand final": "总决赛",
          "finals": "决赛", "qualifier": "预选赛", "rmr": "RMR 地区预选赛"}
CN_TIME = timezone(timedelta(hours=8))
PAGE_SIZE = 18
_recent_cache: tuple[float, list[tuple[str, dict]]] | None = None


def _clean(value: object, limit: int = 80) -> str:
    return re.sub(r"[\x00-\x1f\x7f]", " ", str(value or "")).strip()[:limit]


def _normalize(value: str) -> str:
    value = value.lower().replace("major", " major").replace("iem", " iem")
    for cn, en in CITY.items():
        value = value.replace(cn, " " + en + " ")
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", value)


def _city_search(value: str) -> str:
    for cn, en in CITY.items():
        if cn in value:
            return en
    words = re.findall(r"[a-zA-Z]+", value)
    return next((word.lower() for word in words if word.lower() not in ("major", "iem", "blast", "esl")),
                words[0].lower() if words else "")


def _series_title(row: dict) -> str:
    league = row.get("league") or {}
    league_name = _clean(league.get("name") if isinstance(league, dict) else "", 45)
    name = _clean(row.get("name"), 60)
    slug = str(row.get("slug") or "").lower()
    city = next((cn for cn, en in CITY.items() if en in slug and en in name.lower()), "")
    if city and "major" in league_name.lower() and ":" not in name and "qualifier" not in name.lower():
        title = city + " Major"
    elif city and league_name.lower() == "iem":
        title = "IEM " + city
    else:
        title = (league_name + " " + name).strip() or _clean(slug)
    if ":" in name:
        title += " · " + _clean(name.split(":", 1)[1], 35)
    return title + " " + str(row.get("year") or "")


def _stage_title(row: dict) -> str:
    name = _clean(row.get("name"))
    if re.fullmatch(r"Group [A-Z]", name, re.I):
        return name[-1].upper() + "组"
    return STAGES.get(name.lower(), name)


def _when(row: dict) -> str:
    stamp = row.get("begin_at") or row.get("scheduled_at")
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(CN_TIME).strftime("%m-%d %H:%M")
    except (ValueError, AttributeError, TypeError):
        return "时间待定"


def _teams(row: dict) -> tuple[str, str]:
    opponents = row.get("opponents")
    names = []
    for item in opponents[:2] if isinstance(opponents, list) else []:
        team = item.get("opponent") if isinstance(item, dict) else None
        names.append(_clean(team.get("name"), 40) if isinstance(team, dict) else "待定")
    return tuple((names + ["待定", "待定"])[:2])


def _match_title(row: dict) -> str:
    first, second = _teams(row)
    return f"{first} vs {second}｜{_when(row)}"


def today_match_menu(store, group: str, member: str, token: str) -> str:
    start, end, matches = today_matches(token)
    labels = {"not_started": "未开始", "running": "进行中", "finished": "已结束"}
    options = []
    for row in matches:
        first, second = _teams(row)
        time_label = _when(row).split(" ")[-1]
        label = f"{time_label}｜{first} vs {second}｜{labels[row['status']]}"
        options.append((label, {"kind": "match", "id": row["id"]}))
    title = f"今日比赛（北京时间 {start:%m-%d %H:%M} 至 {end:%m-%d %H:%M}）："
    return _menu(store, group, member, title, options)


def _match_detail(row: dict) -> str:
    first, second = _teams(row)
    status = {"finished": "已结束", "running": "进行中", "not_started": "未开始",
              "canceled": "已取消", "postponed": "已延期"}.get(row.get("status"), "状态待定")
    score_by_team = {str(result.get("team_id")): result.get("score") for result in row.get("results") or []
                     if isinstance(result, dict) and type(result.get("score")) is int}
    opponents = row.get("opponents") or []
    ids = [str(x.get("opponent", {}).get("id")) for x in opponents[:2]
           if isinstance(x, dict) and isinstance(x.get("opponent"), dict)]
    if len(ids) == 2 and all(x in score_by_team for x in ids):
        score = f"{score_by_team[ids[0]]}∶{score_by_team[ids[1]]}"
    else:
        score = "比分暂缺"
    league = row.get("league") or {}
    serie = row.get("serie") or {}
    tournament = row.get("tournament") or {}
    stage = _stage_title(tournament) if tournament else "阶段待定"
    event = _series_title({**serie, "league": league}) if serie else _clean(league.get("name"))
    bo = row.get("number_of_games")
    format_text = f"｜BO{bo}" if type(bo) is int and bo > 0 else ""
    lines = [f"【{event} · {stage}】", f"{first} vs {second}｜{score}",
             f"{status}｜北京时间 {_when(row)}{format_text}", f"比赛 ID：{row.get('id')}"]
    lines.append("数据来源：PandaScore；逐图比分和选手数据以数据源权限为准")
    return "\n".join(lines)


def _list(path: str, token: str, page: int = 1) -> list[dict]:
    join = "&" if "?" in path else "?"
    return _fetch_list(path + join + urlencode({"per_page": 100, "page": page}), token)


def _date(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else None
    except ValueError:
        return None


def recent_major_events(store, group: str, member: str, token: str) -> str:
    """Show active or just-finished S/A tier CS2 series, with numbered navigation."""
    global _recent_cache
    if _recent_cache and time.monotonic() - _recent_cache[0] < 300:
        options = _recent_cache[1]
        return _menu(store, group, member, "近期大赛（进行中／结束三天内；S、A级）：", options)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=3)
    params = {"filter[tier]": "s,a", "filter[videogame_title]": "cs-2", "sort": "-begin_at"}
    path = "/csgo/tournaments?" + urlencode(params)
    events: dict[int, dict] = {}
    for page in range(1, 9):
        rows = _fetch_list(path + "&" + urlencode({"per_page": 20, "page": page}), token)
        for row in rows:
            if not isinstance(row, dict) or str(row.get("tier") or "").lower() not in ("s", "a"):
                continue
            serie = row.get("serie")
            if not isinstance(serie, dict) or type(serie.get("id")) is not int:
                continue
            begin = _date(serie.get("begin_at")) or _date(row.get("begin_at"))
            end = _date(serie.get("end_at")) or _date(row.get("end_at"))
            if begin is None or end is None:
                continue
            if begin > now or end < cutoff:
                continue
            state = "进行中" if end >= now else "刚结束"
            previous = events.get(serie["id"])
            if previous is None or (previous["state"] != "进行中" and state == "进行中"):
                events[serie["id"]] = {"serie": serie, "league": row.get("league") or {},
                                        "state": state, "end": end,
                                        "tier": str(row["tier"]).upper()}
        if len(rows) < 20:
            break
        oldest_begin = min((_date(row.get("begin_at")) for row in rows if isinstance(row, dict)
                            and _date(row.get("begin_at")) is not None), default=None)
        if oldest_begin and oldest_begin < now - timedelta(days=45):
            break
    ordered = sorted(events.values(), key=lambda x: (x["state"] != "进行中",
                     x["end"] if x["state"] == "进行中" else -x["end"].timestamp()))
    options = []
    for entry in ordered:
        serie = entry["serie"]
        title = _series_title({**serie, "league": entry["league"]})
        label = f"{title}｜{entry['state']}｜{entry['tier']}级"
        target = {"kind": "series", "row": {key: serie.get(key)
                  for key in ("id", "name", "year", "slug", "league")}}
        target["row"]["league"] = entry["league"]
        options.append((label, target))
    _recent_cache = (time.monotonic(), options)
    return _menu(store, group, member, "近期大赛（进行中／结束三天内；S、A级）：", options)


def _series(token: str, search: str, year: int | None, page: int = 1) -> list[dict]:
    params = {}
    if search:
        params["search[slug]"] = search
    if year:
        params["filter[year]"] = year
    params["sort"] = "-begin_at"
    return _list("/csgo/series?" + urlencode(params), token, page)


def _stages(token: str, serie_id: int) -> list[dict]:
    rows = []
    for page in range(1, 5):
        batch = _list("/csgo/tournaments?" + urlencode({"filter[serie_id]": serie_id}), token, page)
        rows.extend(row for row in batch if isinstance(row, dict) and type(row.get("id")) is int)
        if len(batch) < 100:
            break
    return sorted(rows, key=lambda x: (str(x.get("begin_at") or ""), x["id"]))


def _matches(token: str, tournament_id: int) -> list[dict]:
    rows = []
    for page in range(1, 6):
        batch = _list("/csgo/matches?" + urlencode({"filter[tournament_id]": tournament_id}), token, page)
        rows.extend(row for row in batch if isinstance(row, dict) and type(row.get("id")) is int)
        if len(batch) < 100:
            break
    return sorted(rows, key=lambda x: (str(x.get("begin_at") or x.get("scheduled_at") or ""), x["id"]))


def _menu(store, group: str, member: str, title: str, options: list[tuple[str, dict]],
          offset: int = 0) -> str:
    if not options:
        store.clear_browser(group, member)
        return title + "\n暂无可查询的记录。"
    page = options[offset:offset + PAGE_SIZE]
    numbered = [(label, target) for label, target in page]
    if offset + PAGE_SIZE < len(options):
        numbered.append(("下一页", {"kind": "page", "title": title, "options": options,
                                  "offset": offset + PAGE_SIZE}))
    if offset:
        numbered.append(("上一页", {"kind": "page", "title": title, "options": options,
                                  "offset": max(0, offset - PAGE_SIZE)}))
    store.set_browser(group, member, numbered)
    return title + "\n" + "\n".join(f"{i}. {label}" for i, (label, _) in enumerate(numbered, 1)) + "\n发送 #序号 继续查看（15 分钟有效）。"


def _show_series(store, group: str, member: str, token: str, row: dict,
                 stage_query: str = "", match_query: str = "") -> str:
    stages = _stages(token, row["id"])
    if not stages:
        return _series_title(row) + "：数据源暂无阶段记录。"
    if stage_query:
        norm = _normalize(stage_query)
        matches = [x for x in stages if norm in _normalize(_stage_title(x) + " " + str(x.get("name") or ""))]
        aliases = {"一阶段": "opening stage", "二阶段": "elimination stage",
                   "揭幕赛": "opening stage", "挑战者组": "opening stage",
                   "传奇组": "elimination stage", "冠军组": "playoffs"}
        if not matches and stage_query in aliases:
            norm = _normalize(aliases[stage_query])
            matches = [x for x in stages if norm in _normalize(_stage_title(x) + " " + str(x.get("name") or ""))]
        if not matches:
            return _menu(store, group, member, _series_title(row) + "｜未找到该阶段，可选择：",
                         [(_stage_title(x), {"kind": "stage", "id": x["id"], "event": _series_title(row)}) for x in stages])
        if len(matches) == 1:
            return _show_stage(store, group, member, token, matches[0]["id"], _series_title(row), match_query)
        stages = matches
    return _menu(store, group, member, _series_title(row) + "｜选择赛程阶段：",
                 [(_stage_title(x), {"kind": "stage", "id": x["id"], "event": _series_title(row)}) for x in stages])


def _show_stage(store, group: str, member: str, token: str, tournament_id: int,
                event: str, match_query: str = "") -> str:
    matches = _matches(token, tournament_id)
    if match_query:
        norm = _normalize(match_query)
        matches = [x for x in matches if norm in _normalize(_match_title(x) + " " + str(x.get("name") or ""))]
        if len(matches) == 1:
            store.clear_browser(group, member)
            return _match_detail(matches[0])
    return _menu(store, group, member, event + "｜选择具体比赛：",
                 [(_match_title(x), {"kind": "match", "id": x["id"]}) for x in matches])


def browse_number(store, group: str, member: str, token: str, number: int) -> str | None:
    options = store.get_browser(group, member)
    if options is None:
        return None
    if not 1 <= number <= len(options):
        return f"序号无效，请发送 #1～#{len(options)}，或重新发送“#赛事 大赛名称 年份”。"
    target = options[number - 1][1]
    try:
        if target["kind"] == "page":
            return _menu(store, group, member, target["title"], target["options"], target["offset"])
        if target["kind"] == "query":
            return browse_command(store, group, member, token, target["text"])
        if target["kind"] == "series":
            return _show_series(store, group, member, token, target["row"])
        if target["kind"] == "stage":
            return _show_stage(store, group, member, token, target["id"], target["event"])
        if target["kind"] == "match":
            row = fetch_match(str(target["id"]), token)
            if row:
                store.clear_browser(group, member)
                return _match_detail(row)
    except SourceError:
        return "赛事数据暂不可查，请稍后重试。"
    return "该比赛暂不可查，请重新发送 #赛事 指令。"


def browse_match_id(store, group: str, member: str, token: str, match_id: str) -> str:
    try:
        row = fetch_match(match_id, token)
    except SourceError:
        return "比赛数据暂不可查，请稍后重试。"
    if row is None:
        return "未找到该 PandaScore 比赛 ID。"
    store.clear_browser(group, member)
    return _match_detail(row)


def browse_command(store, group: str, member: str, token: str, text: str) -> str:
    args = text.removeprefix("赛事").strip()
    if not args:
        return "用法：#赛事 大赛名称 年份 [赛程阶段] [具体比赛]。例如：#赛事 上海major 2024；也可输入：#赛事 2024。"
    if re.fullmatch(r"[1-9][0-9]{4,17}", args):
        return browse_match_id(store, group, member, token, args)
    year_match = re.search(r"(?<!\d)(20\d{2})(?!\d)", args)
    year = int(year_match.group(1)) if year_match else None
    name = args[:year_match.start()].strip() if year_match else args
    rest = args[year_match.end():].strip() if year_match else ""
    year_page = 1
    if year and not name and rest:
        page_match = re.fullmatch(r"第([1-9][0-9]?)页", rest)
        if not page_match:
            return "年份目录翻页格式：#赛事 2024 第2页。"
        year_page = int(page_match.group(1))
    if year and not 2012 <= year <= datetime.now(CN_TIME).year + 3:
        return "年份超出可查询范围。"
    if not name and not year:
        return "请提供赛事名称或年份。"
    search = _city_search(name) if name else ""
    if name and not search:
        return "暂不能识别这个赛事名称。可尝试举办地的英文名加 Major／IEM，例如 Shanghai Major。"
    try:
        # A location search is narrow enough to include past CS:GO events such as Paris Major.
        rows = []
        for page in (range(1, 5) if name else (year_page,)):
            batch = _series(token, search, year, page)
            rows.extend(row for row in batch if isinstance(row, dict) and type(row.get("id")) is int)
            if len(batch) < 100:
                break
    except SourceError:
        return "赛事目录暂不可查，请稍后重试。"
    query = _normalize(name)
    if name:
        rows = [row for row in rows if (not year or row.get("year") == year)
                and (not query or all(term in _normalize(str(row.get("slug") or "") + " " +
                    str((row.get("league") or {}).get("name") or ""))
                    for term in re.findall(r"major|iem|blast|esl", query)))]
        if "major" in query and not any(x in query for x in ("rmr", "qualifier", "预选")):
            main = [row for row in rows if ":" not in str(row.get("name") or "")
                    and not any(x in str(row.get("name") or "").lower() for x in ("qualifier", "rmr"))]
            if main:
                rows = main
        if "iem" in query and not any(x in query for x in ("qualifier", "预选")):
            main = [row for row in rows if "qualifier" not in str(row.get("name") or "").lower()]
            if main:
                rows = main
    if not rows:
        store.clear_browser(group, member)
        return "未找到已收录的赛事；尚未举办且数据源未建档的赛事不会提前列出。"
    if len(rows) == 1 and year:
        stage_query, match_query = "", ""
        if rest:
            # Prefer the longest recognized stage prefix; arbitrary stage names may be selected by number.
            for alias in sorted(set(STAGES.values()) | set(STAGES.keys()) |
                                {"一阶段", "二阶段", "揭幕赛", "挑战者组", "传奇组", "冠军组", "小组赛", "决赛"}, key=len, reverse=True):
                if rest.lower().startswith(alias.lower()):
                    stage_query = alias
                    match_query = rest[len(alias):].strip()
                    break
            if not stage_query:
                stage_query = rest
        try:
            return _show_series(store, group, member, token, rows[0], stage_query, match_query)
        except SourceError:
            return "赛事阶段暂不可查，请稍后重试。"
    title = (name + (" " + str(year) if year else "") if name else str(year)) + "｜选择赛事："
    options = [(_series_title(row), {"kind": "series", "row":
                {key: row.get(key) for key in ("id", "name", "year", "slug", "league")}}) for row in rows]
    if not name and len(rows) == 100 and year_page < 99:
        options.append(("下一批年份赛事", {"kind": "query", "text": f"赛事 {year} 第{year_page + 1}页"}))
    return _menu(store, group, member, title, options)
