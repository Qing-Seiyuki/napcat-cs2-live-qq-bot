"""OneBot group commands for selecting professional matches to follow."""
from __future__ import annotations

import re

from .cs2_updates import UpdateError, history_detail, history_page, render_history
from .esports_subscriptions import SubscriptionStore
from .binding_link import link_for_request
from .pandascore_source import SourceError, fetch_match
from .esports_browser import (browse_command, browse_number, browse_match_id,
                              recent_major_events, today_match_menu, _match_title)


MATCH_ID = re.compile(r"[1-9][0-9]{0,17}\Z")
HELP = ("指令帮助：\n"
        "#今日比赛  显示今日正午至次日正午的比赛\n"
        "#近期赛事  近期举行大赛\n"
        "#赛事 赛事名称 年份  按赛事浏览，如 #赛事 上海major 2024\n"
        "#赛事 比赛ID  查具体比赛；列表用 #数字 选择\n"
        "#赛事订阅 比赛ID  赛后播报\n"
        "#我的赛事／#赛事取消 比赛ID：查看／取消订阅\n"
        "#更新播报 开／关／状态  群主或管理员管理本群官方更新播报\n"
        "#播报解读／#播报原文 开／关／状态  群管理员设播报内容\n"
        "#更新历史 [页码]  每页10条；#序号 查 AI 整理的中文要点\n"
        "#更新解读 开／关／状态  切换自己查看更新时的简要解读\n"
        "#更新原文 开／关／状态  切换中文译文；关后可只看解读\n"
        "首次查询需等待，机器人会先提示“正在查询，请稍后...”\n"
        "#绑定链接 申请编号：取得 Steam 验证链接\n"
        "#help 或 @机器人 help：查看此菜单")


def command_reply(event: dict, store: SubscriptionStore, token: str | None,
                  *, translation_ready: bool = False, news_ai_key: str = "",
                  news_ai_model: str = "gpt-5.6-luna", news_interpret: bool = False,
                  news_ai_provider: str = "openai", on_wait=None) -> str | None:
    if event.get("post_type") != "message" or event.get("message_type") != "group":
        return None
    group, member, self_id, message_id = (event.get("group_id"), event.get("user_id"),
                                          event.get("self_id"), event.get("message_id"))
    if any(type(value) is not int or value <= 0 for value in (group, member, self_id, message_id)) or member == self_id:
        return None
    segments = event.get("message")
    if not isinstance(segments, list):
        return None
    text = "".join(segment.get("data", {}).get("text", "") for segment in segments
                   if isinstance(segment, dict) and segment.get("type") == "text"
                   and isinstance(segment.get("data"), dict)
                   and isinstance(segment["data"].get("text"), str)).strip()
    at_self = any(segment.get("type") == "at" and isinstance(segment.get("data"), dict)
                  and str(segment["data"].get("qq")) == str(self_id)
                  for segment in segments if isinstance(segment, dict))
    at_help = at_self and text.lower() == "help"
    if not text.startswith("#") and not at_help:
        return None
    text = text[1:].strip() if text.startswith("#") else "help"
    parts = text.split()
    is_recent = text in ("近期赛事", "近期大赛", "赛事 近期")
    is_browser = bool(parts) and (parts[0] == "赛事" or (len(parts) == 1 and parts[0].isdigit())) and not is_recent
    if not parts or (parts[0] not in ("今日比赛", "赛事订阅", "赛事取消", "我的赛事", "绑定链接", "更新播报", "播报解读", "播报原文", "播报译文", "更新历史", "历史更新", "更新解读", "更新原文", "更新译文", "help") and not is_browser and not is_recent):
        return None
    app, group_id, member_id = "napcat", str(group), str(member)
    if not store.claim_event(app, group_id, str(message_id)):
        return None
    if text.lower() == "help":
        return HELP
    if parts[0] == "更新播报" and len(parts) == 3 and parts[1] in ("解读", "原文", "译文"):
        parts = ["播报" + parts[1], parts[2]]
    if parts[0] == "更新解读":
        if len(parts) != 2 or parts[1] not in ("开", "关", "状态"):
            return "请发送：#更新解读 开、#更新解读 关 或 #更新解读 状态。"
        if parts[1] == "状态":
            preference = store.news_interpret_preference(group_id, member_id)
            enabled = news_interpret if preference is None else preference
            return f"你在本群查看更新时的 AI 简要解读：{'开' if enabled else '关'}。"
        store.set_news_interpret_preference(group_id, member_id, parts[1] == "开")
        return f"你在本群查看更新时的 AI 简要解读已{parts[1]}。发送 #更新历史 后用 #序号 查看。"
    if parts[0] in ("更新原文", "更新译文"):
        if len(parts) != 2 or parts[1] not in ("开", "关", "状态"):
            return "请发送：#更新原文 开、#更新原文 关 或 #更新原文 状态。这里的原文指中文译文。"
        if parts[1] == "状态":
            visible = store.news_translation_visible(group_id, member_id)
            return f"你在本群查看更新时的中文译文显示：{'开' if visible else '关'}。"
        store.set_news_translation_visible(group_id, member_id, parts[1] == "开")
        return f"你在本群查看更新时的中文译文显示已{parts[1]}。关闭后可用 #更新解读 开 只看解读。"
    if parts[0] in ("播报解读", "播报原文", "播报译文"):
        if len(parts) != 2 or parts[1] not in ("开", "关", "状态"):
            return f"请发送：#{parts[0]} 开、#{parts[0]} 关 或 #{parts[0]} 状态。"
        interpreted, show_translation = store.news_broadcast_settings(group_id, news_interpret)
        is_interpret = parts[0] == "播报解读"
        label = "AI 解读" if is_interpret else "中文译文"
        if parts[1] == "状态":
            return f"本群更新播报的{label}显示：{'开' if (interpreted if is_interpret else show_translation) else '关'}。"
        sender = event.get("sender")
        if not isinstance(sender, dict) or sender.get("role") not in ("admin", "owner"):
            return "仅群主或管理员可以切换本群更新播报内容。"
        interpreted = parts[1] == "开" if is_interpret else interpreted
        show_translation = parts[1] == "开" if not is_interpret else show_translation
        if not interpreted and not show_translation:
            return "群播报至少要显示中文译文或 AI 解读；请先开启另一项。"
        store.set_news_broadcast_settings(group_id, interpreted, show_translation)
        return f"本群更新播报的{label}显示已{parts[1]}。"
    if parts[0] in ("更新历史", "历史更新"):
        if len(parts) > 2 or (len(parts) == 2 and not parts[1].isdigit()):
            return "请发送：#更新历史 [页码]，页码从 1 开始。"
        page = int(parts[1]) if len(parts) == 2 else 1
        if not 1 <= page <= 20:
            return "历史更新页码须为 1～20。"
        try:
            articles, has_more = history_page(page)
        except UpdateError:
            return "CS2 历史更新暂不可查，请稍后重试。"
        if articles:
            for article in articles:
                store.cache_history_article(article)
            store.set_news_menu(group_id, member_id, page, [a["gid"] for a in articles])
        return render_history(page, articles, has_more)
    if parts[0] == "更新播报":
        if len(parts) != 2 or parts[1] not in ("开", "关", "状态"):
            return "请发送：#更新播报 开、#更新播报 关 或 #更新播报 状态。"
        if parts[1] == "状态":
            state = "开" if store.news_enabled(group_id) else "关"
            config = "中文翻译已配置" if translation_ready else "尚未配置中文翻译密钥"
            return f"本群 CS2 更新播报：{state}；{config}。"
        sender = event.get("sender")
        if not isinstance(sender, dict) or sender.get("role") not in ("admin", "owner"):
            return "仅群主或管理员可以切换本群更新播报。"
        if parts[1] == "开" and not translation_ready:
            key_name = "DEEPSEEK_API_KEY" if news_ai_provider == "deepseek" else "OPENAI_API_KEY"
            return f"尚未配置中文翻译密钥，不能开启。请维护者先在 .env 配置 {key_name}。"
        store.set_news_enabled(group_id, parts[1] == "开")
        return f"本群 CS2 官方更新播报已{parts[1]}。新公告会自动以中文播报。"
    if parts[0] == "绑定链接":
        if len(parts) != 2 or not re.fullmatch(r"[0-9a-f]{32}", parts[1]):
            return "请发送：#绑定链接 申请编号。申请编号可从官方机器人的绑定回复查看。"
        link = link_for_request(parts[1])
        return ("Steam 账号验证：" + link + "\n请用申请绑定的 Steam 账号登录。"
                if link else "未找到待验证申请；请在官方机器人处发送“我的绑定”检查。")
    if is_browser:
        if len(parts) == 1 and parts[0].isdigit() and len(parts[0]) <= 3:
            selected = store.news_menu_selection(group_id, member_id, int(parts[0]))
            if selected is not None:
                if not selected:
                    return "序号不在本页，请按列表中的编号发送，或用 #更新历史 翻页。"
                preference = store.news_interpret_preference(group_id, member_id)
                interpret = news_interpret if preference is None else preference
                return history_detail(store, selected, ai_key=news_ai_key,
                                      ai_model=news_ai_model, interpret=interpret,
                                      show_translation=store.news_translation_visible(group_id, member_id),
                                      provider=news_ai_provider, on_wait=on_wait)
        if not token:
            return "赛事数据源尚未配置。"
        if len(parts) == 1 and parts[0].isdigit():
            if len(parts[0]) >= 5:
                return browse_match_id(store, group_id, member_id, token, parts[0])
            return browse_number(store, group_id, member_id, token, int(parts[0]))
        return browse_command(store, group_id, member_id, token, text)
    if is_recent:
        if not token:
            return "赛事数据源尚未配置。"
        try:
            return recent_major_events(store, group_id, member_id, token)
        except SourceError:
            return "近期大赛暂不可查，请稍后重试。"
    if parts[0] == "今日比赛":
        if len(parts) != 1:
            return "请发送：#今日比赛"
        if not token:
            return "赛事数据源尚未配置。"
        try:
            return today_match_menu(store, group_id, member_id, token)
        except (SourceError, OSError):
            return "今日比赛暂不可查，请稍后重试。"
    if parts[0] == "我的赛事":
        if len(parts) != 1:
            return "请发送：#我的赛事"
        rows = store.list_member(app, group_id, member_id)
        return ("本群订阅的比赛：\n" + "\n".join(row["match_id"] for row in rows)
                if rows else "你在本群尚未订阅比赛。")
    if len(parts) != 2 or not MATCH_ID.fullmatch(parts[1]):
        return "请发送：#赛事订阅 比赛ID，或 #赛事取消 比赛ID。可先用 #今日比赛 查看 ID。"
    match_id = parts[1]
    if parts[0] == "赛事取消":
        removed = store.unsubscribe(app, group_id, member_id, "pandascore", match_id)
        return "已取消你在本群对这场比赛的订阅。" if removed else "你在本群没有订阅这场比赛。"
    if not token:
        return "赛事数据源尚未配置，暂不能订阅。"
    try:
        match = fetch_match(match_id, token)
    except (SourceError, OSError):
        return "暂时无法核对这场比赛，请稍后重试。"
    if match is None:
        return "未找到这个 PandaScore 比赛 ID，可先发送 #今日比赛 查看。"
    if match.get("status") in ("finished", "canceled"):
        return "这场比赛已结束或取消，无法订阅赛后提醒。"
    try:
        created = store.subscribe(app, group_id, member_id, "pandascore", match_id)
    except ValueError:
        return "这场比赛的群播报已经处理，无法重复订阅。"
    return ("已订阅：" if created else "你已订阅：") + match_id + "｜" + _match_title(match)
