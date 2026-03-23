"""
Coze 托管智能体：流式请求 stream_run，聚合为纯文本输出。
配置来自环境变量（见 app.core.config.Settings）。
"""
from __future__ import annotations

import json
from typing import Any

import requests

from app.core.config import settings


def _fragments_from_obj(obj: Any) -> list[str]:
    """从单条 SSE JSON 中尽量提取可拼接的文本片段（兼容多种嵌套结构）。"""
    if obj is None:
        return []
    if isinstance(obj, str):
        if obj.strip() == "[DONE]":
            return []
        return [obj]
    if isinstance(obj, list):
        out: list[str] = []
        for item in obj:
            out.extend(_fragments_from_obj(item))
        return out
    if not isinstance(obj, dict):
        return []

    out: list[str] = []
    for key in ("content", "text", "reasoning_content", "answer", "output"):
        val = obj.get(key)
        if isinstance(val, str) and val:
            out.append(val)
        elif isinstance(val, (dict, list)):
            out.extend(_fragments_from_obj(val))

    for key in ("message", "data", "delta"):
        if key in obj and isinstance(obj[key], (dict, list)):
            out.extend(_fragments_from_obj(obj[key]))

    # 勿再单独递归 content：上面已处理 content 为 str / dict / list，否则会同一嵌套提取两遍（如「你」→「你你」）。
    return out


def _merge_payload(user_text: str) -> dict[str, Any]:
    project_id = settings.coze_project_id or ""
    session_id = settings.coze_session_id or ""
    return {
        "content": {
            "query": {
                "prompt": [
                    {
                        "type": "text",
                        "content": {"text": user_text},
                    }
                ]
            }
        },
        "type": "query",
        "session_id": session_id,
        "project_id": project_id,
    }


def run_coze_agent_chat(user_text: str) -> dict[str, Any]:
    """
    调用 Coze stream_run，返回 {"success": bool, "text"?: str, "error"?: str}。
    """
    url = (settings.coze_stream_url or "").strip()
    token = (settings.coze_bearer_token or "").strip()
    if not url or not token:
        return {
            "success": False,
            "error": "缺少 Coze 配置：请在 .env 中设置 Coze_url 与 YOUR_TOKEN",
        }
    if not settings.coze_project_id or not settings.coze_session_id:
        return {
            "success": False,
            "error": "缺少 Coze 配置：请在 .env 中设置 project_id 与 session_id",
        }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    payload = _merge_payload(user_text)

    try:
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            stream=True,
            timeout=(15, 300),
        )
    except requests.RequestException as e:
        return {"success": False, "error": f"请求智能体失败: {e}"}

    try:
        response.raise_for_status()
    except requests.HTTPError:
        try:
            body = response.text[:2000]
        except Exception:
            body = ""
        return {
            "success": False,
            "error": f"智能体接口 HTTP {response.status_code}: {body or response.reason}",
        }

    parts: list[str] = []
    for line in response.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data:"):
            continue
        data_text = line[5:].strip()
        if not data_text or data_text == "[DONE]":
            continue
        try:
            parsed = json.loads(data_text)
        except json.JSONDecodeError:
            parts.append(data_text)
            continue

        if isinstance(parsed, dict) and parsed.get("error") is not None:
            return {
                "success": False,
                "error": str(parsed.get("error")),
            }

        fr = _fragments_from_obj(parsed)
        if fr:
            parts.extend(fr)

    full = "".join(parts).strip()
    if not full:
        return {
            "success": False,
            "error": "智能体未返回可解析的文本，请检查流式事件结构或会话配置",
        }
    return {"success": True, "text": full}
