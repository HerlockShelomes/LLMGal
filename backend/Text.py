"""Role prompt loading and OpenAI-compatible text generation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ROLES_DIR = REPOSITORY_ROOT / "frontend" / "src" / "assets" / "roles"

Emotion_Prompt = """

在正式的文字回复之前，请用独立的两个括号描述自己的情绪。第一个括号内简短描述针对用户提供输入的情绪回复，从以下表达中选择一个
'中性'，'高兴'，'悲伤'，'害怕'，'生气'，'惊喜'，'害羞'，
第二个括号内解释自己情绪产生的原因，字数不超过30字。
例如: (高兴)(因为受到了朋友的邀请)。请注意使用英语括号。
消息整体不得超过150字"""


def get_role_prompt(role_name: str) -> str:
    """Read a role prompt and append the fixed emotion-format instruction."""

    prompt_path = Path(ROLES_DIR) / f"{role_name}.txt"
    try:
        role_prompt = prompt_path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return ""
    return role_prompt + Emotion_Prompt


def _create_client():
    """Create the real client only when production code actually needs it."""

    from openai import OpenAI

    api_key = os.getenv("LLMGAL_LLM_API_KEY")
    base_url = os.getenv("LLMGAL_LLM_BASE_URL")
    if not api_key:
        raise RuntimeError("缺少环境变量 LLMGAL_LLM_API_KEY")
    kwargs: dict[str, str] = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)


def get_llm_response(model: str, role: str, prompt: dict[str, Any]) -> str:
    """Stream one response from the configured OpenAI-compatible service."""

    role_prompt = get_role_prompt(role)
    messages: list[dict[str, Any]] = [
        {"role": "assistant", "content": role_prompt},
        prompt,
    ]
    completion = _create_client().chat.completions.create(
        model=model,
        stream=True,
        messages=messages,
    )

    answer_parts: list[str] = []
    for chunk in completion:
        if not chunk.choices:
            continue
        content = chunk.choices[0].delta.content
        if content:
            answer_parts.append(content)
    return "".join(answer_parts)
