"""Send prepared text through a locally running NapCat OneBot HTTP endpoint."""
from __future__ import annotations

import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class SendError(Exception):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def send_group_text(group_id: str, text: str, *, access_token: str,
                    port: int = 3000) -> str:
    if not re.fullmatch(r"[1-9][0-9]{4,11}", group_id):
        raise ValueError("QQ群号格式无效")
    if not isinstance(text, str) or not text.strip() or len(text) > 4000:
        raise ValueError("群消息为空或过长")
    if not isinstance(access_token, str) or not access_token:
        raise ValueError("未配置 NapCat 访问令牌")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("NapCat 本地端口无效")
    # Keep the token on this computer. A text segment also prevents result names
    # containing CQ codes from becoming executable OneBot message segments.
    payload = {"group_id": group_id,
               "message": [{"type": "text", "data": {"text": text}}]}
    request = Request(f"http://127.0.0.1:{port}/send_group_msg",
                      data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                      headers={"Content-Type": "application/json",
                               "Authorization": "Bearer " + access_token},
                      method="POST")
    try:
        with build_opener(ProxyHandler({}), _NoRedirect()).open(request, timeout=12) as response:
            body = response.read(1_000_001)
    except (HTTPError, URLError, OSError):
        raise SendError("无法确认 NapCat 群消息发送结果") from None
    if len(body) > 1_000_000:
        raise SendError("NapCat 响应过大")
    try:
        result = json.loads(body)
    except ValueError:
        raise SendError("NapCat 响应不是 JSON") from None
    if not isinstance(result, dict) or result.get("status") != "ok" or result.get("retcode") != 0:
        raise SendError("NapCat 未确认群消息发送成功")
    data = result.get("data")
    message_id = data.get("message_id") if isinstance(data, dict) else None
    if isinstance(message_id, bool) or not isinstance(message_id, (str, int)) or str(message_id) in ("", "0"):
        raise SendError("NapCat 没有返回群消息编号")
    return str(message_id)
