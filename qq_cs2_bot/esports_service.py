"""Run match subscriptions with PandaScore fixtures and a local NapCat account."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time

from websockets.exceptions import ConnectionClosed, WebSocketException
from websockets.sync.client import connect

from .esports_commands import command_reply
from .cs2_updates import UpdateError, poll_updates
from .esports_result import render_series
from .esports_subscriptions import SubscriptionStore
from .napcat_sender import SendError, send_group_text
from .pandascore_source import SourceError, fetch_match, finished_result


ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def _env_values() -> dict[str, str]:
    values = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, sep, value = line.partition("=")
            if sep:
                values[key.strip()] = value.strip().strip('"\'')
    return values


def news_settings() -> tuple[str, str, bool, str]:
    values = _env_values()
    provider = os.environ.get("CS2_NEWS_AI_PROVIDER", values.get("CS2_NEWS_AI_PROVIDER", "openai")).lower()
    if provider not in ("openai", "deepseek"):
        raise ValueError("CS2_NEWS_AI_PROVIDER 只支持 openai 或 deepseek")
    if provider == "deepseek":
        key = os.environ.get("DEEPSEEK_API_KEY", values.get("DEEPSEEK_API_KEY", ""))
        model = os.environ.get("DEEPSEEK_MODEL", values.get("DEEPSEEK_MODEL", "deepseek-flash"))
    else:
        key = os.environ.get("OPENAI_API_KEY", values.get("OPENAI_API_KEY", ""))
        model = os.environ.get("CS2_NEWS_AI_MODEL", values.get("CS2_NEWS_AI_MODEL", "gpt-5.6-luna"))
    interpret = os.environ.get("CS2_NEWS_AI_INTERPRET", values.get("CS2_NEWS_AI_INTERPRET", "0"))
    return key, model, interpret.lower() in ("1", "true", "yes", "on"), provider


def settings() -> tuple[str, str, int, int]:
    values = _env_values()
    source_token = os.environ.get("PANDASCORE_TOKEN", values.get("PANDASCORE_TOKEN", ""))
    napcat_token = os.environ.get("NAPCAT_ACCESS_TOKEN", values.get("NAPCAT_ACCESS_TOKEN", ""))
    if not source_token or not napcat_token:
        raise ValueError("请先在 .env 配置 PANDASCORE_TOKEN 和 NAPCAT_ACCESS_TOKEN")
    http_port = int(os.environ.get("NAPCAT_HTTP_PORT", values.get("NAPCAT_HTTP_PORT", "3000")))
    ws_port = int(os.environ.get("NAPCAT_WS_PORT", values.get("NAPCAT_WS_PORT", "3001")))
    if not 1 <= http_port <= 65535 or not 1 <= ws_port <= 65535:
        raise ValueError("NapCat 本地端口无效")
    return source_token, napcat_token, http_port, ws_port


def poll_once(store: SubscriptionStore, source_token: str, napcat_token: str,
              http_port: int = 3000) -> int:
    sent = 0
    for match_id in store.active_matches("pandascore"):
        try:
            match = fetch_match(match_id, source_token)
        except SourceError:
            continue
        result = finished_result(match) if match is not None else None
        if result is None:
            continue
        text = render_series(result)
        for app, group in store.subscribed_groups("pandascore", match_id):
            if app != "napcat":
                continue
            store.queue_if_subscribed(app, group, "pandascore", match_id)
            if not store.claim_delivery(app, group, "pandascore", match_id):
                continue
            try:
                message_id = send_group_text(group, text, access_token=napcat_token, port=http_port)
            except SendError:
                store.finish_delivery(app, group, "pandascore", match_id, None)
            else:
                store.finish_delivery(app, group, "pandascore", match_id, message_id)
                sent += 1
    return sent


def run(poll_seconds: int = 120) -> None:
    if not 60 <= poll_seconds <= 3600:
        raise ValueError("轮询间隔须为 60～3600 秒")
    source_token, napcat_token, http_port, ws_port = settings()
    ai_key, ai_model, interpret, ai_provider = news_settings()
    store = SubscriptionStore()
    ws_url = f"ws://127.0.0.1:{ws_port}"
    next_poll = time.monotonic()
    next_news_poll = time.monotonic()
    while True:
        try:
            with connect(ws_url, additional_headers={"Authorization": "Bearer " + napcat_token},
                         open_timeout=10, close_timeout=3, max_size=1_000_000) as ws:
                print("赛事订阅服务已连接本机 NapCat。", flush=True)
                while True:
                    if time.monotonic() >= next_poll:
                        count = poll_once(store, source_token, napcat_token, http_port)
                        if count:
                            print(f"已确认发送 {count} 条赛事结果。", flush=True)
                        next_poll = time.monotonic() + poll_seconds
                    if time.monotonic() >= next_news_poll:
                        try:
                            count = poll_updates(store, ai_key=ai_key, ai_model=ai_model,
                                                 napcat_token=napcat_token, http_port=http_port,
                                                 interpret=interpret, provider=ai_provider)
                        except UpdateError as error:
                            print(f"CS2 更新检查失败：{error}", flush=True)
                        else:
                            if count:
                                print(f"已确认发送 {count} 条 CS2 官方更新。", flush=True)
                        next_news_poll = time.monotonic() + 300
                    try:
                        event = json.loads(ws.recv(timeout=min(1, max(0.1, next_poll - time.monotonic()))))
                    except TimeoutError:
                        continue
                    except ValueError:
                        continue
                    if not isinstance(event, dict):
                        continue
                    def announce_wait():
                        try:
                            send_group_text(str(event["group_id"]), "正在查询，请稍后...",
                                            access_token=napcat_token, port=http_port)
                        except SendError:
                            print("更新查询等待提示未确认。", flush=True)

                    reply = command_reply(event, store, source_token,
                                          translation_ready=bool(ai_key),
                                          news_ai_key=ai_key, news_ai_model=ai_model,
                                          news_interpret=interpret, news_ai_provider=ai_provider,
                                          on_wait=announce_wait)
                    if reply:
                        try:
                            send_group_text(str(event["group_id"]), reply,
                                            access_token=napcat_token, port=http_port)
                        except SendError:
                            print("赛事指令回复未确认，请在群内核对订阅状态。", flush=True)
        except (ConnectionClosed, ConnectionError, OSError, WebSocketException):
            print("NapCat 连接中断，稍后重连。", flush=True)
            time.sleep(10)


def main() -> None:
    parser = argparse.ArgumentParser(description="CS2 职业赛事订阅与赛后群播报")
    parser.add_argument("--poll-seconds", type=int, default=120)
    args = parser.parse_args()
    try:
        run(args.poll_seconds)
    except (ValueError, KeyboardInterrupt) as error:
        if isinstance(error, KeyboardInterrupt):
            print("已停止赛事订阅服务。")
        else:
            parser.exit(1, f"配置错误：{error}\n")


if __name__ == "__main__":
    main()
