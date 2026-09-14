"""集中配置与密钥管理。

背景：原先的密钥（火山 ACCESS/SECRET、中转站 sk-、TTS token）全部硬编码在
Text.py / Voice.py / Image.py 里，既泄露又无法切换厂商。这里统一改为从
环境变量 / backend/.env 读取（缺陷 B01）。

用法：
    复制 .env.example 为 .env，填入自己的密钥即可。
    未填任何密钥时，所有 AI 调用会以「缺少密钥」的明确报错失败，
    而不会悄悄发出一个写死在源码里的请求。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
ENV_PATH = BACKEND_DIR / ".env"


def _load_dotenv(path: Path = ENV_PATH) -> None:
    """最小化 .env 解析，避免为此引入额外依赖。

    已有同名环境变量优先（不覆盖），方便 CI / 部署时用真实环境变量覆盖 .env。
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()


def _get(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _get_int(key: str, default: int) -> int:
    try:
        return int(_get(key, str(default)))
    except ValueError:
        return default


def _get_bool(key: str, default: bool = False) -> bool:
    value = _get(key, "1" if default else "0").lower()
    return value in ("1", "true", "yes", "on")


# --------------------------------------------------------------------------
# 文本大模型（统一 OpenAI 兼容协议，切换厂商只改 TEXT_PROVIDER）
# --------------------------------------------------------------------------
TEXT_PROVIDER = _get("TEXT_PROVIDER", "zhipu").lower()  # zhipu | deepseek | qwen | custom

TEXT_PRESETS = {
    # 智谱：flash 档最便宜、延迟最低。注意 2026-09 实测该账号下可用模型为
    # glm-4.5 / 4.5-air / 4.6 / 4.7 / 5 / 5-turbo / 5.1 / 5.2 / 5.3 / 5.3-flash，
    # 并不存在 glm-4.7-flash 这个 ID（会报 1211 模型不存在）。
    "zhipu": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4/",
        "model": "glm-5.3-flash",
        "api_key": "ZHIPU_API_KEY",
        "reasoning_effort": "low",
    },
    # DeepSeek：付费兜底最低价档，国内直连。
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "api_key": "DEEPSEEK_API_KEY",
    },
    # 阿里百炼（通义）：每月免费额度，与语音 Qwen3-TTS 同账号。
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
        "api_key": "DASHSCOPE_API_KEY",
    },
    # 自定义 OpenAI 兼容端点。
    "custom": {
        "base_url": _get("TEXT_BASE_URL", ""),
        "model": _get("TEXT_MODEL", ""),
        "api_key": "TEXT_API_KEY",
    },
}

_TEXT_PRESET = TEXT_PRESETS.get(TEXT_PROVIDER, TEXT_PRESETS["zhipu"])
TEXT_BASE_URL = _get("TEXT_BASE_URL") or _TEXT_PRESET["base_url"]
TEXT_MODEL = _get("TEXT_MODEL") or _TEXT_PRESET["model"]
TEXT_API_KEY = _get(_TEXT_PRESET["api_key"]) or _get("TEXT_API_KEY")

# 思考强度：智谱 flash 档是推理模型，思考过程同样计费。
# 实测（glm-5.3-flash，同一句提问）：
#   默认（开启思考）→ reasoning 197 字、66 tokens、2.7s
#   reasoning_effort=low → reasoning 0 字、20 tokens、0.7s
# 省约 3 倍 token、快 4 倍。想要更强的角色一致性可改成 high 或留空（成本约 3 倍）。
# 非推理型 provider（DeepSeek/通义）请留空，避免传入不支持的参数。
TEXT_REASONING_EFFORT = _get(
    "TEXT_REASONING_EFFORT",
    _TEXT_PRESET.get("reasoning_effort", ""),
)

# 生成参数
TEXT_TEMPERATURE = float(_get("TEXT_TEMPERATURE", "0.9"))
TEXT_MAX_TOKENS = _get_int("TEXT_MAX_TOKENS", 1024)
TEXT_TIMEOUT = _get_int("TEXT_TIMEOUT", 90)

# 多轮上下文：最多带多少条历史消息进 prompt（含 user/assistant 双方）
CONTEXT_MAX_MESSAGES = _get_int("CONTEXT_MAX_MESSAGES", 40)

# 模型白名单：前端设置面板里选到的模型 ID 会原样透传到这一层并直接发给厂商。
# 而前端默认列表沿用了旧中转站的命名（deepseek-ai/DeepSeek-V3 之类），
# 这类 ID 在智谱根本不存在，请求会直接 1211「模型不存在」，整轮对话失败。
# 这里做一次收敛：不在白名单内的一律回落到 .env 的 TEXT_MODEL，而不是让请求报错。
_PROVIDER_KNOWN_MODELS = {
    "zhipu": {
        # 2026-09 实测 open.bigmodel.cn 该账号下 /models 返回的真实 ID，
        # 注意没有 glm-4.7-flash 这种组合。
        "glm-4.5", "glm-4.5-air", "glm-4.6", "glm-4.7",
        "glm-5", "glm-5-turbo", "glm-5.1", "glm-5.2", "glm-5.3", "glm-5.3-flash",
    },
    "deepseek": {"deepseek-chat", "deepseek-reasoner"},
    "qwen": {"qwen-plus", "qwen-turbo", "qwen-max", "qwen-flash"},
}


def _build_model_allowlist() -> set:
    allow = {TEXT_MODEL}
    allow |= _PROVIDER_KNOWN_MODELS.get(TEXT_PROVIDER, set())
    extra = [m.strip() for m in _get("TEXT_MODEL_ALLOWLIST", "").split(",") if m.strip()]
    allow |= set(extra)
    return allow


TEXT_MODEL_ALLOWLIST = _build_model_allowlist()


def resolve_text_model(requested) -> str:
    """把模型名收敛到当前 provider 实际可用的模型。

    - 空值 / 非字符串 -> 用 .env 的 TEXT_MODEL（前端选「跟随后端配置」走这条）
    - provider=custom -> 原样放行（端点由用户自定，后端无从预知可用模型）
    - 命中白名单 -> 原样使用（允许前端在合规范围内切模型）
    - 其余 -> 回落 TEXT_MODEL 并告警，避免一次误选就让整轮对话失败
    """
    if not requested or not isinstance(requested, str):
        return TEXT_MODEL
    name = requested.strip()
    if not name:
        return TEXT_MODEL
    if TEXT_PROVIDER == "custom" or name in TEXT_MODEL_ALLOWLIST:
        return name
    logging.warning(
        "请求的模型 %r 不在 provider=%s 的可用列表内，已回落到 %s。"
        "确认该模型可用后，可把它加进 backend/.env 的 TEXT_MODEL_ALLOWLIST。",
        name, TEXT_PROVIDER, TEXT_MODEL,
    )
    return TEXT_MODEL


# --------------------------------------------------------------------------
# 语音合成
# --------------------------------------------------------------------------
# qwen  = 阿里百炼 Qwen3-TTS，每月 100 万字符免费，国内免信用卡（默认，最省）
# volcengine = 火山豆包 TTS 2.0，自然度更好但按字数计费
TTS_PROVIDER = _get("TTS_PROVIDER", "qwen").lower()
# 官方端点：DashScope 多模态生成接口（非 OpenAI 的 /audio/speech，实测后者返回 404）
TTS_QWEN_ENDPOINT = _get(
    "TTS_QWEN_ENDPOINT",
    "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
)
TTS_QWEN_MODEL = _get("TTS_QWEN_MODEL", "qwen3-tts-flash")
# 支持自然语言演播指令的模型，用于情绪控制（开启 TTS_QWEN_USE_INSTRUCTIONS 时使用）
TTS_QWEN_INSTRUCT_MODEL = _get("TTS_QWEN_INSTRUCT_MODEL", "qwen3-tts-instruct-flash")
TTS_QWEN_LANGUAGE = _get("TTS_QWEN_LANGUAGE", "Chinese")
# 单条文本上限：qwen3-tts 系列为 600 字符，超出会被拒
TTS_QWEN_MAX_CHARS = _get_int("TTS_QWEN_MAX_CHARS", 600)
# 是否把情绪作为指令一起发送（需厂商支持 instructions 参数，默认关闭以免报错）
TTS_QWEN_USE_INSTRUCTIONS = _get_bool("TTS_QWEN_USE_INSTRUCTIONS", False)

# 火山（volcengine）配置，仅在 TTS_PROVIDER=volcengine 时使用
TTS_VOLC_APPID = _get("TTS_VOLC_APPID", "")
TTS_VOLC_TOKEN = _get("TTS_VOLC_TOKEN", "")
TTS_VOLC_CLUSTER = _get("TTS_VOLC_CLUSTER", "volcano_tts")

# 音色映射：Integration.request_confirmation 返回的火山音色 ID -> Qwen3-TTS 音色名
# （Integration 侧保持返回火山音色 ID 以维持既有契约，映射在 Voice.py 内完成）
VOLC_TO_QWEN_VOICE = {
    "zh_female_tianxinxiaomei_emo_v2_mars_bigtts": _get("TTS_QWEN_VOICE_GIRLFRIEND", "Cherry"),
    "zh_male_yourougongzi_emo_v2_mars_bigtts": _get("TTS_QWEN_VOICE_BOYFRIEND", "Ethan"),
    "zh_female_gaolengyujie_emo_v2_mars_bigtts": _get("TTS_QWEN_VOICE_ELDERSISTER", "Serena"),
    "zh_male_ruyayichen_emo_v2_mars_bigtts": _get("TTS_QWEN_VOICE_LITERATUREGUY", "Chelsie"),
}
TTS_QWEN_DEFAULT_VOICE = _get("TTS_QWEN_VOICE", "Cherry")


# --------------------------------------------------------------------------
# 角色 -> 音色映射（让每个角色发音各不相同）
# --------------------------------------------------------------------------
# 背景：前端原先对所有角色都发同一个 voiceCate="ElderSister"，
# 落到 Qwen3-TTS 上就是清一色的 Serena，四个角色说话一模一样。
# 这里改成以「角色名」为主键决定音色，voiceCate 退化为兜底。
#
# 覆盖方式（backend/.env，逗号分隔，角色名区分大小写）：
#   ROLE_VOICE_MAP=Wendy:Cherry,Testificate:Bunny
#   ROLE_VOICE_MAP_VOLC=Wendy:zh_female_tianxinxiaomei_emo_v2_mars_bigtts

# Qwen3-TTS 常用音色目录（voice 名 -> [中文名, 性别, 描述]），供前端下拉与校验使用
QWEN_VOICE_CATALOG = {
    "Cherry": ("芊悦", "女", "阳光积极、亲切自然的小姐姐"),
    "Serena": ("苏瑶", "女", "温柔小姐姐"),
    "Ethan": ("晨煦", "男", "阳光温暖、活力朝气，带一点北方口音"),
    "Chelsie": ("千雪", "女", "二次元虚拟女友"),
    "Momo": ("茉兔", "女", "撒娇搞怪，逗你开心"),
    "Vivian": ("十三", "女", "拽拽的、可爱的小暴躁"),
    "Moon": ("月白", "男", "率性帅气"),
    "Maia": ("四月", "女", "知性与温柔的碰撞"),
    "Kai": ("凯", "男", "耳朵的一场 SPA，温润顺滑"),
    "Nofish": ("不吃鱼", "男", "不会翘舌音的设计师"),
    "Bella": ("萌宝", "女", "喝酒不打醉拳的小萝莉"),
    "Katerina": ("卡捷琳娜", "女", "御姐音色，韵律回味十足"),
    "Mia": ("乖小妹", "女", "温顺如春水，乖巧如初雪"),
    "Nini": ("邻家妹妹", "女", "软糯黏人的甜嗓"),
    "Bunny": ("萌小姬", "女", "萌属性爆棚的小萝莉"),
    "Mochi": ("沙小弥", "男", "聪明伶俐的小大人"),
    "Neil": ("阿闻", "男", "字正腔圆的新闻主播"),
    "Eldric Sage": ("沧明子", "男", "沉稳睿智的老者"),
    "Vincent": ("田叔", "男", "沙哑烟嗓，江湖气"),
    "Bellona": ("燕铮莺", "女", "字正腔圆、热血铿锵"),
    "Elias": ("墨讲师", "女", "严谨又擅长叙事"),
    "Jennifer": ("詹妮弗", "女", "电影质感的美语女声"),
    "Ryan": ("甜茶", "男", "节奏拉满、戏感炸裂"),
    "Aiden": ("艾登", "男", "精通厨艺的美语大男孩"),
    # 2026-09-14 补全：对照官方《Qwen-TTS 音色列表》，qwen3-tts-flash 实际支持 27 个音色，
    # 上面原有 24 个全部有效，以下 3 个此前漏收（Arthur / Seren / Pip）。
    "Arthur": ("徐大爷", "男", "质朴沙哑的乡土老者，满村奇闻异事"),
    "Seren": ("小婉", "女", "温和舒缓的助眠女声"),
    "Pip": ("顽屁小孩", "男", "调皮捣蛋、充满童真的小男孩"),
}

# 默认角色音色：按人设性格配对，四个角色彼此不同
_DEFAULT_ROLE_VOICES = {
    # Wendy：ESFJ，细心温和、语调轻柔的"温暖鼓励型"
    "Wendy": "Serena",
    # 修勾（艾露猫）：开朗活泼、热情洋溢，会化成少女用妹妹口吻说话
    "Testificate": "Momo",
    # Eric：ESFJ 男，和善的务实组织者，爱组局
    "Testificate_Boy": "Ethan",
    # Kate：INTP 女程序员，内向、逻辑强、不擅言语
    "GirlProgrammer": "Maia",
}

# 火山豆包侧的对应音色（TTS_PROVIDER=volcengine 时生效）
_DEFAULT_ROLE_VOICES_VOLC = {
    "Wendy": "zh_female_tianxinxiaomei_emo_v2_mars_bigtts",
    "Testificate": "zh_female_shuangkuaisisi_emo_v2_mars_bigtts",
    "Testificate_Boy": "zh_male_yangguangqingnian_emo_v2_mars_bigtts",
    "GirlProgrammer": "zh_female_gaolengyujie_emo_v2_mars_bigtts",
}


def _load_role_voices(env_key: str, defaults: dict) -> dict:
    """内置默认值 + .env 覆盖（ROLE_VOICE_MAP=角色:音色,角色:音色）。"""
    result = dict(defaults)
    for item in _get(env_key, "").split(","):
        item = item.strip()
        if ":" not in item:
            continue
        role, voice = item.split(":", 1)
        role, voice = role.strip(), voice.strip()
        if role and voice:
            result[role] = voice
    return result


ROLE_VOICES = _load_role_voices("ROLE_VOICE_MAP", _DEFAULT_ROLE_VOICES)
ROLE_VOICES_VOLC = _load_role_voices("ROLE_VOICE_MAP_VOLC", _DEFAULT_ROLE_VOICES_VOLC)

# 内置角色（仓库自带、不可删除）。由静态默认表 _DEFAULT_ROLE_VOICES 派生，
# 单一真相源 —— .env 的 ROLE_VOICE_MAP 只是给角色加音色映射，不代表新增内置角色，
# 因此不参与这里的判定（那些角色没有配套素材，删也删不出东西）。
BUILTIN_ROLES = tuple(_DEFAULT_ROLE_VOICES.keys())

# 前端「创建新角色」产生的角色→音色映射。
# 内置默认与 .env 都是**静态**的，新角色没法往里塞，所以单独落一个 JSON：
# 由 Create_New_Role 写入，运行时按 mtime 增量读取（文件不存在时返回空，行为不变）。
CUSTOM_ROLE_VOICES_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "custom_role_voices.json"
)
_custom_role_voices_cache: dict = {"mtime": -1.0, "data": {}}


def _load_custom_role_voices() -> dict:
    try:
        mtime = os.path.getmtime(CUSTOM_ROLE_VOICES_PATH)
    except OSError:
        return {}
    if mtime == _custom_role_voices_cache["mtime"]:
        return _custom_role_voices_cache["data"]
    try:
        with open(CUSTOM_ROLE_VOICES_PATH, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    _custom_role_voices_cache.update({"mtime": mtime, "data": data})
    return data


def resolve_role_voice(role: str, fallback: str = "") -> str:
    """按角色取音色；角色未登记时回退到调用方给的值。

    查找顺序：内置/.env 的 ROLE_VOICES -> 前端创建的自定义角色映射 -> fallback。
    """
    if not role:
        return fallback
    if role in ROLE_VOICES:
        return ROLE_VOICES[role]
    custom = _load_custom_role_voices().get(role)
    if custom:
        return custom
    return fallback


def resolve_role_voice_volc(role: str, fallback: str = "") -> str:
    """同上，但取的是火山豆包的音色 ID（TTS_PROVIDER=volcengine 时用）。"""
    if not role:
        return fallback
    return ROLE_VOICES_VOLC.get(role, fallback)


# --------------------------------------------------------------------------
# 图像生成
# --------------------------------------------------------------------------
# zhipu      = 智谱 CogView-3-Flash，免费出图（默认，最省）
# volcengine = 火山 VisualService（high_aes_ip_v20 / byteedit_v2.0），质量更好但计费
# seedream   = 火山方舟 Seedream（OpenAI 兼容），质量验收用
IMAGE_PROVIDER = _get("IMAGE_PROVIDER", "zhipu").lower()

IMAGE_ZHIPU_BASE_URL = _get("IMAGE_ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
IMAGE_ZHIPU_MODEL = _get("IMAGE_ZHIPU_MODEL", "cogview-3-flash")
IMAGE_ZHIPU_SIZE = _get("IMAGE_ZHIPU_SIZE", "1024x1024")
# 新角色立绘：要求「正方形 + 至少高清」，与对话时的实时图尺寸分开配置，
# 免得为了省钱把对话图调小，结果立绘也跟着变糊。
IMAGE_ROLE_SIZE = _get("IMAGE_ROLE_SIZE", "1024x1024")

# 默认画风：二次元动漫原画。这是**项目底层默认值**，所有出图路径（新角色立绘、
# 7 张情绪扩展图、对话实时图）都必须经 Image.build_style_head() 取画风，
# 禁止各处手写 —— 之前 emotional_bro 自己写了一段 SD 标签脚手架，出图风格就和
# 立绘对不上。要整体换画风，改这里（或 .env 的 IMAGE_STYLE_PROMPT）即可。
#
# 刻意不含 photo / realistic / 3D render / studio lighting 等摄影·写实词汇：
# 指令式文生图模型（CogView / Seedream）会被这类词强烈拉向写实人像，实测见
# Image.ANIME_STYLE_HEAD 上方注释。
IMAGE_STYLE_PROMPT = _get(
    "IMAGE_STYLE_PROMPT",
    "2D anime key visual illustration in Japanese anime style, official anime "
    "artwork, cel shading, clean line art, flat colors, vibrant, high quality, detailed",
)

IMAGE_VOLC_ACCESS_KEY = _get("IMAGE_VOLC_ACCESS_KEY", "")
IMAGE_VOLC_SECRET_KEY = _get("IMAGE_VOLC_SECRET_KEY", "")

IMAGE_ARK_BASE_URL = _get("IMAGE_ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
IMAGE_ARK_MODEL = _get("IMAGE_ARK_MODEL", "doubao-seedream-4.0")

IMAGE_ZHIPU_API_KEY = _get("ZHIPU_API_KEY", "")
IMAGE_ARK_API_KEY = _get("ARK_API_KEY", "")


# --------------------------------------------------------------------------
# 服务与安全
# --------------------------------------------------------------------------
# 为空表示不鉴权（开发模式，会打印警告）；填写后 WebSocket 必须带同名 token。
WS_AUTH_TOKEN = _get("WS_AUTH_TOKEN", "")
# 允许的跨域来源，逗号分隔；* 表示全部放行（生产请收紧）
CORS_ALLOW_ORIGINS = _get("CORS_ALLOW_ORIGINS", "*")
HOST = _get("HOST", "127.0.0.1")
PORT = _get_int("PORT", 8000)


# --------------------------------------------------------------------------
# 运行时模式：Mock（AI 旁路）/ 正式版（prod）
# --------------------------------------------------------------------------
# Mock 版只验证「前端展示 + 后端处理 + 前后端连接」这三件事，AI 一律不下场：
#   文本回复 -> 固定的系统状态日志（回显输入 + 各链路状态）
#   语音     -> 固定复用本地已有的测试样本
#   图像     -> 固定返回 neutral（情绪图里的中性那张）
# 开关由前端设置页顶部的按钮经 REST(/api/system/mode) 切换，状态落盘在
# backend/runtime_mode.json —— uvicorn --reload 会重启进程，只放内存里切完就丢。
#
# 注意：文件不存在时即「正式版」，所以开箱默认就是完整功能，不会静默降级。
# 该文件属于运行时状态，不应提交（见根 .gitignore）。
MODE_MOCK = "mock"
MODE_PROD = "prod"
_VALID_MODES = (MODE_MOCK, MODE_PROD)

MODE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "runtime_mode.json")

# .env 的 APP_MODE 只决定「没有任何落盘记录时」的初值，缺省 prod。
_initial_mode = _get("APP_MODE", MODE_PROD).lower()
if _initial_mode not in _VALID_MODES:
    _initial_mode = MODE_PROD


def _read_mode_file() -> str:
    """读落盘的模式；文件缺失/损坏/取值非法一律返回空串（= 用默认值）。"""
    try:
        with open(MODE_PATH, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, ValueError):
        return ""
    if not isinstance(data, dict):
        return ""
    mode = str(data.get("mode", "")).strip().lower()
    return mode if mode in _VALID_MODES else ""


def get_mode() -> str:
    """当前运行时模式（'mock' / 'prod'）。

    每次调用都读一次盘，**不做进程内缓存**。文件只有几十字节，这点开销相比
    一次 LLM 调用可以忽略；而缓存会让下面三种情况「界面与后端各说各话」：
      · 多 worker（`uvicorn --workers N`）——切换只更新了接请求的那个进程；
      · 手工编辑 runtime_mode.json（排障时很常见）；
      · 另一个进程/工具写入。
    落盘用的是「临时文件 + os.replace」，读到的必然是完整的旧值或新值。
    """
    return _read_mode_file() or _initial_mode


def is_mock() -> bool:
    """是否处于 Mock 版（AI 旁路）。对话链路在每个请求上都会问一次。"""
    return get_mode() == MODE_MOCK


def set_mode(mode: str) -> str:
    """切换运行时模式并落盘。非法取值抛 ValueError，由调用方回 400。"""
    value = (mode or "").strip().lower()
    if value not in _VALID_MODES:
        raise ValueError(f"不支持的模式 {mode!r}，只能是 {_VALID_MODES}")
    # 原子落盘：先写临时文件再 replace。reload 期间有并发读，
    # 直接覆写会读到「写了一半」的 JSON，被当成损坏文件而回落到默认模式。
    temp_path = f"{MODE_PATH}.tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as file:
            json.dump({"mode": value}, file, ensure_ascii=False, indent=2)
        os.replace(temp_path, MODE_PATH)
    except OSError as error:
        # 落盘失败就必须让调用方知道：get_mode() 不再有内存态兜底，
        # 静默返回「切换成功」而实际没写进去，等于骗用户。
        logging.exception("运行时模式落盘失败")
        raise RuntimeError(f"模式落盘失败：{error}") from error
    return value


def mode_label() -> str:
    """给人看的模式名称，用于日志、启动自检与 REST 响应。"""
    return "Mock 版（AI 已旁路）" if is_mock() else "正式版（AI 已接入）"


def missing_credentials() -> list[str]:
    """返回尚未填写、会导致功能不可用的配置项，供启动自检使用。"""
    if is_mock():
        # Mock 版一个厂商接口都不调，缺密钥不影响可用性，别在这里误报一次告警。
        return []
    missing = []
    if not TEXT_API_KEY:
        missing.append(f"TEXT_API_KEY（{TEXT_PROVIDER} 文本模型的密钥）")
    if TTS_PROVIDER == "qwen" and not _get("DASHSCOPE_API_KEY"):
        missing.append("DASHSCOPE_API_KEY（Qwen3-TTS 语音，阿里百炼）")
    if TTS_PROVIDER == "volcengine" and not (TTS_VOLC_APPID and TTS_VOLC_TOKEN):
        missing.append("TTS_VOLC_APPID / TTS_VOLC_TOKEN（火山 TTS）")
    if IMAGE_PROVIDER == "zhipu" and not IMAGE_ZHIPU_API_KEY:
        missing.append("ZHIPU_API_KEY（CogView-3-Flash 图像，智谱）")
    if IMAGE_PROVIDER == "volcengine" and not (IMAGE_VOLC_ACCESS_KEY and IMAGE_VOLC_SECRET_KEY):
        missing.append("IMAGE_VOLC_ACCESS_KEY / IMAGE_VOLC_SECRET_KEY（火山图像）")
    if IMAGE_PROVIDER == "seedream" and not IMAGE_ARK_API_KEY:
        missing.append("ARK_API_KEY（Seedream 图像，火山方舟）")
    return missing


def describe() -> str:
    """启动自检信息（不打印密钥本身）。"""
    lines = [
        f"运行模式 : {mode_label()}"
        + (f"  [开关文件 {MODE_PATH}]" if os.path.exists(MODE_PATH) else "  [默认值，未切换过]"),
        f"文本模型 : provider={TEXT_PROVIDER} model={TEXT_MODEL} base_url={TEXT_BASE_URL}",
        f"语音合成 : provider={TTS_PROVIDER}"
        + (f" model={TTS_QWEN_MODEL} voice={TTS_QWEN_DEFAULT_VOICE}" if TTS_PROVIDER == "qwen" else ""),
        f"图像生成 : provider={IMAGE_PROVIDER}"
        + (f" model={IMAGE_ZHIPU_MODEL}" if IMAGE_PROVIDER == "zhipu" else f" model={IMAGE_ARK_MODEL}"),
        f"服务地址 : http://{HOST}:{PORT}  (鉴权: {'开启' if WS_AUTH_TOKEN else '关闭-开发模式'})",
    ]
    missing = missing_credentials()
    if missing:
        lines.append("缺少配置 : " + "；".join(missing))
    return "\n".join(lines)
