"""文本大模型接入层。

改动要点（对照缺陷清单）：
- N02：角色人设改用 role="system" 承载。原先塞进 assistant，模型会把「你是 Wendy，性格……」
       当成自己说过的台词，人格约束直接减半。
- N03：人设文件缺失时不再静默降级成空 prompt 照发请求，而是明确抛错，
       避免「角色扮演完全失效但零错误信号」。
- B01：密钥 / 模型 / 端点全部来自 config（.env），不再硬编码。
- 新增：多轮上下文（history）。项目此前零多轮记忆，模型窗口再长也只收到一条。
"""

from __future__ import annotations

import logging
from pathlib import Path

from openai import OpenAI

import config

# 人设与静态资源仍按「以 backend 为工作目录」的相对路径读取。
# 注意：不要改成基于 __file__ 的绝对路径，测试用例依赖这一约定（chdir 到临时 backend 后
# 在 ../frontend/src/assets 下放置 fixtures）。
ROLE_PROMPT_PATH = '../frontend/src/assets/roles/{role}.txt'

Emotion_Prompt = """

在正式的文字回复之前，请用独立的两个括号描述自己的情绪。第一个括号内简短描述针对用户提供输入的情绪回复，从以下表达中选择一个
'中性'，'高兴'，'悲伤'，'害怕'，'生气'，'惊喜'，'害羞'，
第二个括号内解释自己情绪产生的原因，字数不超过30字。
例如: (高兴)(因为受到了朋友的邀请)。请注意使用英语括号。
消息整体不得超过150字"""

# 最近一次真实调用返回的 token 用量（provider 未返回时为 None）。
# Connect 侧优先取这里的真实值，取不到再退回按字数估算。
LAST_USAGE: dict | None = None

# 最近一次真实调用返回的「思考内容」（推理模型如 DeepSeek-R1 / 智谱推理档才有）。
# 前端经 WebSocket 流式展示思考过程时，主要靠 on_reasoning 回调实时推送；
# 这里额外落一份全局变量，便于后端日志与调试回溯。无思考内容时为 None。
LAST_REASONING: str | None = None


def get_role_prompt(role_name: str) -> str:
    """读取角色人设并追加情绪输出约束。

    N03：文件缺失或读取失败时抛错，而不是返回空串让请求静默发出。
    """
    path = Path(ROLE_PROMPT_PATH.format(role=role_name))
    try:
        with open(path, 'r', encoding='utf-8') as file:
            role_prompt = file.read()
    except FileNotFoundError:
        raise FileNotFoundError(
            f"角色人设文件缺失：{path}。请在 frontend/src/assets/roles/ 下创建 "
            f"{role_name}.txt，或换一个已存在的角色。"
        )
    except OSError as error:
        raise OSError(f"角色人设文件读取失败：{path}（{error}）")

    if not role_prompt.strip():
        raise ValueError(f"角色人设文件为空：{path}")

    return "".join([role_prompt, Emotion_Prompt])


def normalize_message(prompt) -> dict:
    """把用户消息统一成 OpenAI 消息对象。

    兼容两种历史形态：裸字符串（早期前端）与 {role, content} 对象（现行契约）。
    """
    if isinstance(prompt, dict):
        content = prompt.get("content", "")
        role = prompt.get("role", "user")
    else:
        content = "" if prompt is None else str(prompt)
        role = "user"

    return {"role": role if role in ("user", "assistant", "system") else "user",
            "content": content}


def sanitize_history(history) -> list[dict]:
    """清洗多轮历史，只保留合法且成对的消息，并限制长度。"""
    if not history:
        return []
    if not isinstance(history, list):
        return []

    cleaned: list[dict] = []
    for item in history[-config.CONTEXT_MAX_MESSAGES:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role not in ("user", "assistant"):
            continue
        if not isinstance(content, str) or not content.strip():
            continue
        cleaned.append({"role": role, "content": content})
    return cleaned


def build_client() -> OpenAI:
    """按 config 构造 OpenAI 兼容客户端。

    未配置密钥时只告警不拦截：真实 SDK 在构造/请求阶段自己会报 api_key 错误，
    而单元测试用替身客户端时不该被这层校验挡住。
    """
    if not config.TEXT_API_KEY:
        logging.warning(
            "未配置文本模型密钥（provider=%s）。请在 backend/.env 填写对应 API Key，"
            "详见 .env.example；当前调用会失败。",
            config.TEXT_PROVIDER,
        )
    return OpenAI(
        api_key=config.TEXT_API_KEY,
        base_url=config.TEXT_BASE_URL,
        timeout=config.TEXT_TIMEOUT,
    )


def get_llm_response(model, role, prompt, history=None, on_reasoning=None):
    """调用文本大模型生成回复。

    :param model: 模型名称；留空或 None 时使用 config.TEXT_MODEL
    :param role: 角色名称，用于读取人设
    :param prompt: 用户消息（字符串或 {role, content} 对象）
    :param history: 可选，多轮历史消息列表
    :param on_reasoning: 可选回调，每次收到思考内容增量片段时调用（流式展示用）。
                         非推理模型不会触发；回调异常不影响主流程。
    :return: 模型生成的文本
    """
    global LAST_USAGE, LAST_REASONING
    LAST_USAGE = None
    LAST_REASONING = None

    answer_content = ""
    reasoning_content = ""
    role_pro = get_role_prompt(role)

    # N02：人设必须用 system 承载。
    messages = [{"role": "system", "content": role_pro}]
    messages.extend(sanitize_history(history))
    messages.append(normalize_message(prompt))

    client = build_client()
    # 前端下拉框里可能是旧的中转站 ID（如 deepseek-ai/DeepSeek-V3），
    # 直接发给厂商会 1211「模型不存在」。这里收敛一次：不在当前 provider
    # 白名单内就回落到 .env 的 TEXT_MODEL，而不是让整轮对话失败。
    request_kwargs = {
        "model": config.resolve_text_model(model),
        "stream": True,
        "temperature": config.TEXT_TEMPERATURE,
        "max_tokens": config.TEXT_MAX_TOKENS,
        "messages": messages,
    }
    # 智谱 flash 是推理模型，思考过程同样计费；low 档实测可省约 3 倍 token。
    # 不支持该参数的 provider 保持留空即可。
    if config.TEXT_REASONING_EFFORT:
        request_kwargs["reasoning_effort"] = config.TEXT_REASONING_EFFORT

    completion = client.chat.completions.create(**request_kwargs)

    for chunk in completion:
        # 流结束时部分 provider 会返回一个只带 usage 的块
        usage = getattr(chunk, "usage", None)
        if usage is not None:
            try:
                LAST_USAGE = {
                    "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                    "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
                    "total_tokens": getattr(usage, "total_tokens", 0) or 0,
                }
            except Exception:  # pragma: no cover - usage 结构异常不应中断生成
                LAST_USAGE = None

        choices = getattr(chunk, "choices", None)
        if not choices:
            continue
        delta = getattr(choices[0], "delta", None)
        content = getattr(delta, "content", None) if delta is not None else None
        if content:
            answer_content += content

        # 推理模型的思考过程随 delta.reasoning_content 流式下发；非推理模型该字段恒为空，
        # 不会进入此分支，也不会影响正式回复的拼接。
        reasoning = getattr(delta, "reasoning_content", None) if delta is not None else None
        if reasoning:
            reasoning_content += reasoning
            if on_reasoning is not None:
                try:
                    on_reasoning(reasoning)
                except Exception:  # pragma: no cover - 回调异常不应中断生成
                    logging.exception("on_reasoning 回调异常（已忽略，不影响主回复）")

    LAST_REASONING = reasoning_content or None
    return answer_content


def get_llm_raw_response(system_prompt: str, user_prompt: str, model=None) -> str:
    """不带角色人设的原始调用。

    get_llm_response 会去读 frontend/src/assets/roles/{role}.txt 当人设，
    而「创建新角色」流程里这个角色还不存在（文件尚未落盘），
    扩写形象描述、生成打招呼台词等场景必须能独立发一次请求。
    """
    global LAST_USAGE
    LAST_USAGE = None

    client = build_client()
    request_kwargs = {
        "model": config.resolve_text_model(model),
        "stream": True,
        "temperature": config.TEXT_TEMPERATURE,
        "max_tokens": config.TEXT_MAX_TOKENS,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if config.TEXT_REASONING_EFFORT:
        request_kwargs["reasoning_effort"] = config.TEXT_REASONING_EFFORT

    answer_content = ""
    completion = client.chat.completions.create(**request_kwargs)
    for chunk in completion:
        usage = getattr(chunk, "usage", None)
        if usage is not None:
            try:
                LAST_USAGE = {
                    "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                    "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
                    "total_tokens": getattr(usage, "total_tokens", 0) or 0,
                }
            except Exception:  # pragma: no cover
                LAST_USAGE = None

        choices = getattr(chunk, "choices", None)
        if not choices:
            continue
        delta = getattr(choices[0], "delta", None)
        content = getattr(delta, "content", None) if delta is not None else None
        if content:
            answer_content += content

    return answer_content


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    print(config.describe())
    print(get_llm_response(config.TEXT_MODEL, "Testificate", {"role": "user", "content": "有时间一块桌游吗？"}))
