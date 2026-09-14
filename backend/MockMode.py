"""Mock 版（AI 旁路）的固定响应。

设计前提见 config.py 的「运行时模式」段：Mock 版只验证「前端展示 + 后端处理 +
前后端连接」三件事，LLM / TTS / 图像三个厂商接口一个都不能碰。

因此本模块的三条硬约束，改动前先读：
1. 不 import Text / Voice / Image 中任何会发网络请求的函数。Mock 版「AI 不下场」
   必须是可验证的事实，而不是「碰巧没触发」。
2. 语音只从磁盘上**已有的**测试样本复制一份到 mock 专属槽位，绝不现场合成。
   样本也不存在时返回空串，由调用方降级为 partial，不偷偷去调 TTS。
   槽位在 `voice/_mock/{角色}/` 下，**与正式版的 `voice/{角色}/` 完全隔离**：
   mock 一秒钟都不该改写正式版会读的文件（代价与原因见 _copy_fixed_audio）。
3. 图像不生成，只把情绪固定为 neutral，让前端去取 <角色>_neutral.jpg
   （前端 ChatInput 用 emotion 当文件名索引，因此「固定情绪」即「固定图像」）。

路径沿用与 Image.py / Voice.py / Integration.py 相同的约定：**以 backend 为
工作目录**的相对路径。MockMode 只在对话链路里被调用，cwd 与它们必然一致。
"""

from __future__ import annotations

import datetime
import os
import re
import shutil
import threading

import config

ASSETS_DIR = '../frontend/src/assets'
VOICE_DIR = f'{ASSETS_DIR}/voice'
SAMPLES_DIR = f'{VOICE_DIR}/_samples'
PICTURES_DIR = f'{ASSETS_DIR}/pictures'

# 固定槽位：Mock 版每轮都用 index=0，前端拿到的音频地址因此完全固定。
# 同时**不**推进 Records.txt 里的 index —— mock 不该污染正式版的资源轮转。
FIXED_INDEX = "0"
FIXED_EMOTION = "neutral"

# mock 音频的专属目录名：voice/_mock/{角色}/，与正式版的 voice/{角色}/ 并列
# （与既有 voice/_samples/ 同为「下划线开头的内部目录」约定）。
# 前端按响应里下发的 mode 选目录前缀，因此两个目录同名文件互不干扰。
MOCK_VOICE_DIRNAME = "_mock"

# 回显用户输入的最大长度：聊天气泡不需要把整段长文再抄一遍
ECHO_LIMIT = 60


def _rel(path: str) -> str:
    """把内部相对路径压成从 assets 起的短路径，供回执展示。"""
    prefix = f'{ASSETS_DIR}/'
    return path[len(prefix):] if path.startswith(prefix) else path


def _safe_name(value: str) -> str:
    """音色 ID -> 安全文件名（与 Create_New_Role.safe_voice_id 同规则）。

    这里重复实现而不是 import，是为了让 MockMode 不依赖创建角色模块——
    那条链会牵进 Image / Voice 的厂商调用，属于本模块明令隔离的范围。
    """
    return re.sub(r'[^0-9A-Za-z_-]', '_', (value or '').strip()).strip('_') or 'voice'


def _audio_candidates(role_name: str, voice_name: str) -> list[str]:
    """本地已有音频的候选列表，按优先级排列（全部是磁盘路径，不产生合成请求）。

    注意方向：这里列的是**源**（正式版目录下的角色自测音频、以及音色试听样本），
    全程只读；写出去的目标永远在 MOCK_VOICE_DIRNAME 那个隔离目录里。
    """
    candidates = []
    for suffix in ('test_Stream.wav', 'test_Stream.mp3', 'test.wav', 'test.mp3'):
        candidates.append(f'{VOICE_DIR}/{role_name}/{role_name}_{suffix}')

    # 角色没留测试音频时，退到该角色专属音色的试听样本
    # （resolve_role_voice 查的是「内置映射 -> .env 覆盖 -> 自定义角色 JSON」）
    voice_id = config.resolve_role_voice(role_name, '')
    if voice_id:
        candidates.append(f'{SAMPLES_DIR}/{_safe_name(voice_id)}.wav')
    return candidates


# 同一角色的固定槽位是**单一文件**，多个标签页 / 并发请求会同时写它。
# 不加锁的话 A 写到一半 B 重新截断覆盖，前端可能读到半个文件 ——
# mock 只是测试用途，但不该因此制造「音频偶发损坏」这种更难查的问题。
_audio_lock = threading.Lock()


def _ensure_fixed_audio(role_name: str, voice_name: str) -> tuple[str, str]:
    """把已存在的测试音频复制到 mock 专属固定槽位，让前端能按约定的路径取到。

    槽位 = `voice/_mock/{角色}/{角色}_0_Stream.{ext}`，与正式版目录隔离。

    :return: (槽位路径, 给日志看的一句话说明)；无可用源时返回 ("", 原因)。
    """
    with _audio_lock:
        return _copy_fixed_audio(role_name, voice_name)


def _copy_fixed_audio(role_name: str, voice_name: str) -> tuple[str, str]:
    """实际执行复制。**只能由 _ensure_fixed_audio 在持锁状态下调用。**"""
    # 先确定源再建目录：一个本地音频都没有时，磁盘上不该留下任何痕迹
    # （连空目录也不建），这样「mock 没有副作用」除了「复制一份已有文件」之外
    # 没有例外，也便于用例直接断言。
    source = next(
        (s for s in _audio_candidates(role_name, voice_name)
         if os.path.isfile(s) and os.path.getsize(s) > 0),
        "",
    )
    if not source:
        return "", (
            f'该角色暂无本地测试音频（{_rel(SAMPLES_DIR)} 下也没有该音色样本；'
            '未合成，mock 不调用 TTS）'
        )

    # 写进 mock 专属目录，而不是正式版的 voice/{角色}/。
    # 正式版每轮覆盖的 {角色}_{index}_Stream.* 是它的工作区，mock 往那儿写会留下
    # 两个后果：① 切回正式版后，引用同一 index 的历史消息会播到 mock 拷进去的
    # 测试音频；② index 相同的两条消息（一条 mock、一条正式）指向同一个文件，
    # 事后无法区分谁是谁。各自一个目录后，前端按消息自带的 mode 选前缀即可。
    role_dir = f'{VOICE_DIR}/{MOCK_VOICE_DIRNAME}/{role_name}'
    try:
        os.makedirs(role_dir, exist_ok=True)
    except OSError:
        return "", f'无法创建音频目录 {role_dir}'

    ext = os.path.splitext(source)[1].lstrip('.') or 'wav'
    target = f'{role_dir}/{role_name}_{FIXED_INDEX}_Stream.{ext}'
    try:
        if os.path.abspath(source) != os.path.abspath(target):
            shutil.copyfile(source, target)
    except OSError as error:
        return "", f'音频落盘失败：{error}'

    # 同槽位的另一个扩展名**不删**。这里踩过一次坑：删除是个破坏性操作，
    # 本机环境注入的 safe-delete 守卫会拦截 os.remove 并 SystemExit(1)，
    # 直接打崩整条 WebSocket 请求；而且「少一个固定音频」远比「打崩请求」轻。
    # 这个槽位现在归 mock 独有，残留只可能来自上一次 mock（不再是正式版素材）。
    # 前端候选列表里 wav 优先，所以只要源是 wav（qwen 档的默认产物）就一定命中
    # 本次写入的文件；只有源为 mp3 而槽上还留着旧 wav 时才会被旧素材抢先 ——
    # 这种情况如实写进回执，不静默掩盖。
    other_ext = 'mp3' if ext == 'wav' else 'wav'
    stale = f'{role_dir}/{role_name}_{FIXED_INDEX}_Stream.{other_ext}'
    if ext != 'wav' and os.path.isfile(stale) and os.path.getsize(stale) > 0:
        return target, (
            f'固定测试音频（复制）：{_rel(source)} -> {_rel(target)}'
            f'；槽上还有 {_rel(stale)} 且 wav 优先，前端可能播到它'
        )

    return target, f'固定测试音频（复制）：{_rel(source)} -> {_rel(target)}'


def _neutral_image_status(role_name: str) -> tuple[bool, str]:
    """检查 neutral 情绪图是否存在（只查不生成）。"""
    path = f'{PICTURES_DIR}/{role_name}/{role_name}_{FIXED_EMOTION}.jpg'
    if os.path.isfile(path) and os.path.getsize(path) > 0:
        return True, f'{role_name}_{FIXED_EMOTION}.jpg'
    return False, f'缺少 {role_name}_{FIXED_EMOTION}.jpg（mock 模式不生成图像）'


def _echo(text) -> str:
    """把用户输入压成一行短文本用于回显。"""
    if isinstance(text, dict):
        text = text.get('content', '')
    raw = re.sub(r'\s+', ' ', str(text or '')).strip()
    if not raw:
        return '（空）'
    return raw if len(raw) <= ECHO_LIMIT else raw[:ECHO_LIMIT] + '…'


def build_mock_response(role_name: str, text, voice_name: str = "",
                        history=None, session_id=None) -> tuple:
    """生成固定响应，返回与 Integration.Response_Collection 完全一致的 5 元组。

    :return: (回复文本, 资源序号, 情绪标签, 本次新生成的图片 url, 处理状态)
             资源序号与情绪都是固定值；url 恒为空串（mock 不生成图片）。
             音频拿不到时降级为 partial，与正式版的降级语义保持一致。
    """
    started = datetime.datetime.now()

    audio_path, audio_note = _ensure_fixed_audio(role_name, voice_name)
    image_ok, image_note = _neutral_image_status(role_name)

    history_count = len(history) if isinstance(history, list) else 0

    lines = [
        f'【{config.mode_label()}】AI 未接入本轮回复，以下为后端状态回执。',
        '',
        f'角色　　：{role_name}',
        f'你的输入：{_echo(text)}',
        f'会话 ID ：{session_id or "（未提供）"}',
        f'上下文　：{history_count} 条历史消息',
        '',
        '── 链路状态 ──',
        '文本模型：已旁路（不调用 LLM，回复内容由后端固定生成）',
        f'语音合成：{audio_note}',
        f'图像生成：{image_note}',
        f'情绪标签：{FIXED_EMOTION}（固定，不解析模型输出）',
        '',
        '── 后端配置 ──',
        f'文本 provider：{config.TEXT_PROVIDER}',
        f'语音 provider：{config.TTS_PROVIDER}',
        f'图像 provider：{config.IMAGE_PROVIDER}',
        '',
        f'请求时间：{started.strftime("%Y-%m-%d %H:%M:%S")}',
        '说明：本模式用于验证前端展示、后端处理与前后端连接；'
        '角色可正常切换，但回复、音频、图像均被固定。',
    ]

    # 语音或图片缺一即降级，让前端照常显示文本 + 一条「语音或图片失败」提示
    status = "success" if (audio_path and image_ok) else "partial"

    print(f"[MockMode] 角色={role_name} 音频={audio_path or '无'} 图像={'有' if image_ok else '无'} 状态={status}")

    # 与正式版返回的 index 语义一致：都是「前端应取用的音频/图片槽位序号」
    return "\n".join(lines), FIXED_INDEX, FIXED_EMOTION, "", status
