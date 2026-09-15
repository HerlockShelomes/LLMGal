"""新角色创建：音色试听样本、形象生成、角色定稿。

路径约定（与 Image.py / Text.py / Integration.py 一致）：
    全部以 **backend 为工作目录** 的相对路径读写 ../frontend/src/assets/...
    —— 项目要在不同服务器上复现，写死绝对路径必然换机器就挂。

产生的文件：
    frontend/src/assets/roles/<角色>.txt                         人设 / 性格
    frontend/src/assets/pictures/Role_Description/<角色>.txt      形象描述
    frontend/src/assets/pictures/<角色>/<角色>_original.jpg        用户选中的原始形象
    frontend/src/assets/pictures/<角色>/<角色>_<情绪>.jpg          7 张情绪图
    frontend/src/assets/pictures/temp/<角色>_<index>.jpg          生成中的候选形象（定稿后清理）
    frontend/src/assets/voice/_samples/<音色>.wav                 音色试听样本
    backend/custom_role_voices.json                              角色 -> 音色 映射
"""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import traceback

import config
import Image
from Text import get_llm_raw_response
from Voice import Voice_Generation_through_http

# --------------------------------------------------------------------------
# 路径（全部相对，且以 backend 为工作目录）
# --------------------------------------------------------------------------
PICTURES_DIR = '../frontend/src/assets/pictures'
ROLES_DIR = '../frontend/src/assets/roles'
VOICE_DIR = '../frontend/src/assets/voice'
TEMP_DIR = f'{PICTURES_DIR}/temp'
DESC_DIR = f'{PICTURES_DIR}/Role_Description'
SAMPLES_DIR = f'{VOICE_DIR}/_samples'

# 文本扩写用的画风标签（写进 LLM 提示词、也回传给前端做展示）。
# 真正出图用的画风前缀统一由 Image.build_style_head() 提供 —— 取
# config.IMAGE_STYLE_PROMPT（默认二次元动漫原画）；改这里的文案不影响出图风格。
DEFAULT_STYLE = '二次元动漫原画'

# 7 种情绪，与 Image.emo_image 保持同一套（顺序即生成顺序，neutral 打底）
EMOTIONS = [emo for emo, _desc in Image.emo_image]

# --------------------------------------------------------------------------
# 音色试听样本：每个音色一句贴合自身人设的台词
# --------------------------------------------------------------------------
VOICE_SAMPLE_TEXTS = {
    "Cherry": "你好呀！今天天气这么好，要不要一起出去走走？",
    "Serena": "你好，我是苏瑶。有什么想聊的，慢慢说就好。",
    "Ethan": "嗨！我是晨煦，今天也一起元气满满地加油吧！",
    "Chelsie": "欢迎回来～千雪一直在这里等着你哦。",
    "Momo": "哼哼～再不理我的话，我可就要闹脾气啦！",
    "Vivian": "喂，看什么呢？有话快说，我可没那么多耐心。",
    "Moon": "哟，来了？走吧，别磨磨蹭蹭的。",
    "Maia": "你好，我是四月。想聊点什么都可以，我听着呢。",
    "Kai": "很高兴见到你，愿这段时光让你感到放松。",
    "Nofish": "你好，我是不吃鱼。今天也要好好做设计呀。",
    "Bella": "哇！你终于来啦，萌宝等你好久好久啦！",
    "Katerina": "哎呀，来得正好。陪我聊会儿吧，别急着走。",
    "Mia": "嗯……你好，我是乖小妹，以后请多多关照。",
    "Nini": "你来啦！今天能不能陪我玩一会儿嘛～",
    "Bunny": "呀！你好呀，萌小姬超开心的！",
    "Mochi": "你好，我是沙小弥。有什么事，我们可以好好商量。",
    "Neil": "您好，这里是阿闻。接下来为您播报今日要点。",
    "Eldric Sage": "年轻人，坐吧。且听老夫说上几句。",
    "Vincent": "嘿，兄弟。来了就别客气，坐下喝一杯。",
    "Bellona": "准备好了吗？跟我一起，向前冲！",
    "Elias": "今天我们来讲一个耐人寻味的故事。",
    "Jennifer": "Hello，我是詹妮弗。很高兴与你相遇。",
    "Ryan": "灯光就位——那么，好戏开场了！",
    "Aiden": "嗨！今天想吃点什么？我来给你露一手。",
    "Arthur": "哎，来啦？坐吧坐吧，我给你摇一段村里的老故事，保准你没听过。",
    "Seren": "晚安。把眼睛闭上，让今天的疲惫一点一点散掉，好好睡一觉吧。",
    "Pip": "嘻嘻！你来抓我呀——抓不到抓不到，我跑得可比你快多啦！",
}

# 创建任务状态：{角色名: {"status": "creating"|"ready"|"failed", "step": str, "error": str}}
ROLE_CREATION_STATUS: dict[str, dict] = {}
_status_lock = threading.Lock()


def _set_status(role_name: str, status: str, step: str = "", error: str = "") -> None:
    with _status_lock:
        ROLE_CREATION_STATUS[role_name] = {
            "status": status,
            "step": step,
            "error": error,
        }


def get_status(role_name: str) -> dict:
    with _status_lock:
        return dict(ROLE_CREATION_STATUS.get(role_name, {"status": "unknown", "step": "", "error": ""}))


# --------------------------------------------------------------------------
# 音色试听样本
# --------------------------------------------------------------------------
def safe_voice_id(voice_id: str) -> str:
    """音色 ID -> 安全文件名（"Eldric Sage" 这种带空格的 id 不能直接做文件名）。"""
    return re.sub(r'[^0-9A-Za-z_-]', '_', (voice_id or '').strip()).strip('_') or 'voice'


def voice_sample_path(voice_id: str) -> str:
    return f'{SAMPLES_DIR}/{safe_voice_id(voice_id)}.wav'


def ensure_voice_sample(voice_id: str, force: bool = False) -> str:
    """确保该音色的试听样本存在；不存在就现合成一份。

    :return: 样本文件路径；失败返回空串。
    """
    if not voice_id:
        return ""
    path = voice_sample_path(voice_id)
    if not force and os.path.exists(path) and os.path.getsize(path) > 0:
        return path

    text = VOICE_SAMPLE_TEXTS.get(voice_id) or f"你好，我是{voice_id}，很高兴认识你。"
    os.makedirs(SAMPLES_DIR, exist_ok=True)
    try:
        # role 参数对样本没有意义，落盘位置由 save_path 指定
        return Voice_Generation_through_http(
            '_samples', voice_id, 'neutral', text, safe_voice_id(voice_id),
            save_path=path,
        )
    except Exception:
        traceback.print_exc()
        return ""


def generate_all_voice_samples(force: bool = False) -> dict:
    """给音色目录里每一个音色都生成试听样本。"""
    results = {}
    for voice_id in config.QWEN_VOICE_CATALOG:
        path = ensure_voice_sample(voice_id, force=force)
        results[voice_id] = bool(path)
        print(f"[{'完成' if path else '失败'}] 音色={voice_id:<14} -> {path}")
    return results


# --------------------------------------------------------------------------
# 形象描述：扩写 / 想象
# --------------------------------------------------------------------------
_EXPAND_SYSTEM = """你是一位资深的二次元角色立绘提示词工程师，负责把用户零散的想法
整理成文生图模型能稳定出图的高质量英文提示词。你只输出规定格式的两行内容，
不输出任何解释、标题或多余文字。"""

_EXPAND_TEMPLATE = """请把下面「用户描述」扩写为角色立绘提示词，严格按以下两行输出：

Subject Description: <一句话概括角色的身份、气质与整体印象>
Appearance Details: <发型发色、瞳色、五官、服装、配饰、身材等外貌细节，用逗号分隔的英文短语>

约束：
1. 全部使用英文；两行都以指定前缀开头，不能增删行。
2. 画风：{style}。除用户明确指定外，一律二次元动画风格。
3. 只描述单个人物，不要出现文字、水印、多人、复杂背景；也不要出现摄影/写实类词汇
   （photo、photograph、realistic、photorealistic、3D、render、studio lighting 等）。
4. 不要输出思考过程或任何解释性文字。

角色名称：{name}
角色性格：{personality}
音色/声线：{voice_label}
用户描述：{user_desc}"""

_IMAGINE_TEMPLATE = """用户没有提供形象描述。请根据下面的角色设定，原创一个符合大众认知、
辨识度高的经典形象，严格按以下两行输出：

Subject Description: <一句话概括角色的身份、气质与整体印象>
Appearance Details: <发型发色、瞳色、五官、服装、配饰、身材等外貌细节，用逗号分隔的英文短语>

约束：
1. 全部使用英文；两行都以指定前缀开头，不能增删行。
2. 画风：{style}。除用户明确指定外，一律二次元动画风格。
3. 形象要与性格、声线气质相称（例如萝莉音色对应娇小可爱，御姐音色对应成熟高挑）。
4. 只描述单个人物，不要出现文字、水印、多人、复杂背景；也不要出现摄影/写实类词汇
   （photo、photograph、realistic、photorealistic、3D、render、studio lighting 等）。
5. 不要输出思考过程或任何解释性文字。

角色名称：{name}
角色性格：{personality}
音色/声线：{voice_label}"""


def voice_label_of(voice_id: str) -> str:
    """音色 ID -> 用于提示词的中文描述（"Serena" -> "苏瑶（女，温柔小姐姐）"）。"""
    info = config.QWEN_VOICE_CATALOG.get(voice_id)
    if not info:
        return voice_id or "未指定"
    name, gender, desc = info
    return f"{name}（{gender}，{desc}）"


def parse_description(text: str, fallback_name: str) -> tuple[str, str]:
    """从模型输出里解析 Subject / Appearance 两行；解析不出就整体兜底。"""
    subject = ''
    appearance = ''
    match = re.search(r'Subject Description:\s*(.+)', text)
    if match:
        subject = match.group(1).strip()
    match = re.search(r'Appearance Details:\s*(.+)', text, re.DOTALL)
    if match:
        appearance = match.group(1).strip()

    if not subject and not appearance:
        # 模型没按格式来：整段当外貌描述，主题用角色名兜底，避免出图提示词为空
        subject = f'an anime character named {fallback_name}'
        appearance = re.sub(r'\s+', ' ', text).strip()
    elif not appearance:
        appearance = subject
    elif not subject:
        subject = f'an anime character named {fallback_name}'

    return subject, appearance


def build_description(role_name: str, personality: str, voice_id: str,
                      user_desc: str, style: str = '') -> tuple[str, str]:
    """得到 (Subject Description, Appearance Details)。

    用户给了描述就扩写，没给就依据角色名 + 性格 + 音色想象一个。
    """
    style = style or DEFAULT_STYLE
    voice_label = voice_label_of(voice_id)
    if (user_desc or '').strip():
        template = _EXPAND_TEMPLATE
        user_part = user_desc.strip()
    else:
        template = _IMAGINE_TEMPLATE
        user_part = "（用户未提供，请自行设计）"

    prompt = template.format(
        name=role_name,
        personality=(personality or '').strip() or '（未填写）',
        voice_label=voice_label,
        style=style,
        user_desc=user_part,
    )
    raw = get_llm_raw_response(_EXPAND_SYSTEM, prompt)
    return parse_description(raw, role_name)


def format_description(subject: str, appearance: str) -> str:
    """拼成 Role_Description 文件的标准内容（Image.get_role_image_prompt 依赖该格式）。"""
    return f"Subject Description: {subject}\nAppearance Details: {appearance}"


def save_description_file(role_name: str, subject: str, appearance: str) -> str:
    os.makedirs(DESC_DIR, exist_ok=True)
    path = f'{DESC_DIR}/{role_name}.txt'
    with open(path, 'w', encoding='utf-8') as file:
        file.write(format_description(subject, appearance))
    return path


# --------------------------------------------------------------------------
# 形象生成（候选图落到 temp）
# --------------------------------------------------------------------------
def build_image_prompt(subject: str, appearance: str, style: str = '',
                       expression: str = 'neutral, calm with a smile on the face') -> str:
    """形象生成的提示词。

    实际写法统一在 `Image.build_portrait_prompt`：默认二次元动漫，
    且不使用 SD 标签脚手架（`[Photography: ...]` 那类摄影词会把 CogView 拉向写实）。
    """
    return Image.build_portrait_prompt(
        subject, appearance, expression=expression, style=style,
    )


def next_temp_index(role_name: str) -> int:
    """候选图从 0 开始编号，返回下一个可用序号。"""
    if not os.path.isdir(TEMP_DIR):
        return 0
    pattern = re.compile(rf'^{re.escape(role_name)}_(\d+)\.jpg$')
    indexes = []
    for filename in os.listdir(TEMP_DIR):
        match = pattern.match(filename)
        if match:
            indexes.append(int(match.group(1)))
    return (max(indexes) + 1) if indexes else 0


def generate_candidate_image(role_name: str, personality: str, voice_id: str,
                             user_desc: str, style: str = '') -> dict:
    """生成一张候选形象到 pictures/temp，返回给前端的描述信息。

    :return: {index, filename, url, subject, appearance, description}
    """
    subject, appearance = build_description(role_name, personality, voice_id, user_desc, style)

    index = next_temp_index(role_name)
    filename = f'{role_name}_{index}.jpg'
    os.makedirs(TEMP_DIR, exist_ok=True)
    save_path = f'{TEMP_DIR}/{filename}'

    prompt = build_image_prompt(subject, appearance, style)
    Image.generate_image_openai_compatible(prompt, save_path, size=config.IMAGE_ROLE_SIZE)

    return {
        "index": index,
        "filename": filename,
        "url": f'/static/pictures/temp/{filename}',
        "subject": subject,
        "appearance": appearance,
        "description": format_description(subject, appearance),
        "style": style or DEFAULT_STYLE,
    }


def list_temp_images(role_name: str) -> list:
    """列出 temp 中该角色的全部候选形象（按 index 升序）。"""
    if not os.path.isdir(TEMP_DIR):
        return []
    pattern = re.compile(rf'^{re.escape(role_name)}_(\d+)\.jpg$')
    items = []
    for filename in os.listdir(TEMP_DIR):
        match = pattern.match(filename)
        if match:
            items.append({
                "index": int(match.group(1)),
                "filename": filename,
                "url": f'/static/pictures/temp/{filename}',
            })
    items.sort(key=lambda item: item["index"])
    return items


# --------------------------------------------------------------------------
# 角色定稿
# --------------------------------------------------------------------------
def register_custom_voice(role_name: str, voice_id: str) -> None:
    """把 角色->音色 写进 backend/custom_role_voices.json，让对话时用的是选定音色。"""
    data = {}
    if os.path.exists(config.CUSTOM_ROLE_VOICES_PATH):
        try:
            with open(config.CUSTOM_ROLE_VOICES_PATH, 'r', encoding='utf-8') as file:
                loaded = json.load(file)
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, ValueError):
            data = {}
    data[role_name] = voice_id
    with open(config.CUSTOM_ROLE_VOICES_PATH, 'w', encoding='utf-8') as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def save_role_personality(role_name: str, personality: str) -> str:
    """人设 / 性格 -> frontend/src/assets/roles/<角色>.txt"""
    os.makedirs(ROLES_DIR, exist_ok=True)
    path = f'{ROLES_DIR}/{role_name}.txt'
    with open(path, 'w', encoding='utf-8') as file:
        file.write(f"角色名称：{role_name}\n{personality.strip()}\n")
    return path


def _cleanup_temp(role_name: str, keep_filename: str = '') -> list:
    """删除 temp 中该角色未被选中的候选图。"""
    removed = []
    for item in list_temp_images(role_name):
        if item["filename"] == keep_filename:
            continue
        try:
            os.remove(f'{TEMP_DIR}/{item["filename"]}')
            removed.append(item["filename"])
        except OSError:
            traceback.print_exc()
    return removed


def finalize_role(role_name: str, personality: str, description: str,
                  voice_id: str, selected_image: str, style: str = '') -> dict:
    """把用户确认的内容全部落盘（耗时，放在后台线程里跑）。

    :param description: 选中形象对应的描述（"Subject Description: ...\nAppearance Details: ..."）。
                        为空时按角色设定重新想象一份。
    :param selected_image: temp 里被选中的文件名。
    """
    _set_status(role_name, "creating", step="保存角色信息")
    try:
        # 1) 人设
        save_role_personality(role_name, personality)

        # 2) 形象描述（用户可能一张图都没生成，此时自己想象一份）
        subject, appearance = '', ''
        if (description or '').strip():
            subject, appearance = parse_description(description, role_name)
        if not subject and not appearance:
            _set_status(role_name, "creating", step="生成形象描述")
            subject, appearance = build_description(role_name, personality, voice_id, '', style)
        save_description_file(role_name, subject, appearance)

        # 3) 选中形象移入角色专属目录（原始形象保留一份，便于回溯）
        role_dir = f'{PICTURES_DIR}/{role_name}'
        os.makedirs(role_dir, exist_ok=True)
        original_path = f'{role_dir}/{role_name}_original.jpg'
        if selected_image:
            src = f'{TEMP_DIR}/{selected_image}'
            if os.path.exists(src):
                with open(src, 'rb') as src_file:
                    payload = src_file.read()
                with open(original_path, 'wb') as dst_file:
                    dst_file.write(payload)

        # 4) 清理未被选中的候选图
        _set_status(role_name, "creating", step="清理临时图片")
        _cleanup_temp(role_name, keep_filename=selected_image or '')

        # 5) 7 张情绪图（已有就跳过，不重复烧钱）
        _set_status(role_name, "creating", step="生成情绪图片")
        pic2pic = "high_aes_ip_v20" if config.IMAGE_PROVIDER == "volcengine" else ""
        Image.static_images(role_name, pic2pic)

        # 6) 登记音色 + 生成该角色的打招呼语音
        _set_status(role_name, "creating", step="生成角色语音")
        if voice_id:
            register_custom_voice(role_name, voice_id)
        Voice_Generation_through_http(
            role_name, voice_id or '', 'neutral',
            f"你好，我是{role_name}。很高兴认识你，以后请多多关照。",
            'test',
        )

        _set_status(role_name, "ready", step="完成")
        return {"status": "ready", "role": role_name}
    except Exception as error:
        traceback.print_exc()
        _set_status(role_name, "failed", step="创建失败", error=str(error))
        return {"status": "failed", "role": role_name, "error": str(error)}


def start_finalize(role_name: str, personality: str, description: str,
                   voice_id: str, selected_image: str, style: str = '') -> None:
    """后台线程定稿，不阻塞前端。"""
    _set_status(role_name, "creating", step="排队中")
    thread = threading.Thread(
        target=finalize_role,
        args=(role_name, personality, description, voice_id, selected_image, style),
        name=f"create-role-{role_name}",
        daemon=True,
    )
    thread.start()


# --------------------------------------------------------------------------
# 删除角色
# --------------------------------------------------------------------------
class RoleBusyError(RuntimeError):
    """角色正在创建中：此刻删除会被后台定稿线程重新写回，因此拒绝。"""


# 与 MockMode.MOCK_VOICE_DIRNAME 同值。这里独立声明是为了不把 Create_New_Role
# 和 MockMode 绑在一起（两者没有其它交集）。
MOCK_VOICE_DIRNAME = '_mock'

# 对话轮转记录（角色 -> Recent_Url / index），与 Integration.RECORDS_PATH 同一个文件。
# 独立声明的原因同上：Connect 同时依赖两个模块，互相 import 会成环。
RECORDS_PATH = '../frontend/src/assets/Records.txt'


def safe_role_name(role_name: str) -> str:
    """校验角色名，挡住路径穿越 —— 删除是破坏性操作，名字必须严格可控。

    拒收：空、`.`/`..`、含路径分隔符或 `:`、以下划线开头
    （`_samples`/`_mock` 这类内部目录就是下划线命名，撞名会连带删掉别人的东西）。
    """
    name = (role_name or '').strip()
    if not name:
        raise ValueError("角色名称不能为空")
    if name in ('.', '..'):
        raise ValueError(f"非法角色名称：{name}")
    if any(ch in name for ch in ('/', '\\', ':', '\0')):
        raise ValueError(f"角色名称不能包含路径分隔符：{name}")
    if name.startswith('_'):
        raise ValueError(f"角色名称不能以下划线开头：{name}")
    return name


def _rel(path: str) -> str:
    """把相对路径压成从 assets 起的短路径，便于回执展示。"""
    prefix = '../frontend/src/assets/'
    return path[len(prefix):] if path.startswith(prefix) else path


def _remove_records_entry(role_name: str) -> bool:
    """从 Records.txt 摘掉该角色的**整段**记录。

    段落格式固定为「角色名: / Recent_Url:x / index:n」再跟一个空行
    （见 Integration.updateLinks）。这里是整段摘除，而不是只清空内容 ——
    留一个空壳角色，下次启动时仍会被解析成「该角色存在」。
    """
    if not os.path.isfile(RECORDS_PATH):
        return False
    try:
        with open(RECORDS_PATH, 'r', encoding='utf-8') as file:
            lines = file.readlines()
    except OSError:
        traceback.print_exc()
        return False

    target = f'{role_name}:'
    kept, index, hit = [], 0, False
    while index < len(lines):
        if lines[index].strip() == target:
            hit = True
            index += 1
            # 紧随其后的 Recent_Url / index 两行（形如 `键:值`）
            for _ in range(2):
                if index < len(lines) and lines[index].strip() and ':' in lines[index]:
                    index += 1
                else:
                    break
            # 段落尾的空行一并吃掉，避免文件里留下连续空行
            while index < len(lines) and not lines[index].strip():
                index += 1
            continue
        kept.append(lines[index])
        index += 1

    if not hit:
        return False
    try:
        with open(RECORDS_PATH, 'w', encoding='utf-8') as file:
            file.writelines(kept)
    except OSError:
        traceback.print_exc()
        return False
    return True


def unregister_custom_voice(role_name: str) -> bool:
    """从 custom_role_voices.json 摘掉该角色。

    该文件是覆盖写；`config._load_custom_role_voices` 按 mtime 增量读，
    写回后 mtime 变化会自动失效缓存，不必额外通知。
    """
    path = config.CUSTOM_ROLE_VOICES_PATH
    if not os.path.isfile(path):
        return False
    try:
        with open(path, 'r', encoding='utf-8') as file:
            data = json.load(file)
    except (OSError, ValueError):
        traceback.print_exc()
        return False
    if not isinstance(data, dict) or role_name not in data:
        return False
    data.pop(role_name, None)
    try:
        with open(path, 'w', encoding='utf-8') as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
    except OSError:
        traceback.print_exc()
        return False
    return True


def delete_role(role_name: str) -> dict:
    """删除一个自定义角色，并清掉它留下的**全部**记录。

    删除范围（不存在就记进 missing，不算失败）：
        pictures/<角色>/                      选中的原图 + 7 张情绪图
        pictures/Role_Description/<角色>.txt   形象描述（出图提示词的来源）
        pictures/temp/<角色>_*.jpg            未选中的候选图
        roles/<角色>.txt                      人设 / 性格
        voice/<角色>/                         对话语音槽位
        voice/_mock/<角色>/                   Mock 版固定音频
        Records.txt                           该角色的 Recent_Url / index 段
        custom_role_voices.json               角色 -> 音色登记
        ROLE_CREATION_STATUS                  创建进度缓存

    :raises PermissionError: 内置角色不可删（config.BUILTIN_ROLES）
    :raises ValueError:      角色名非法
    :raises RoleBusyError:   角色正在创建中（后台线程会写回，先等它结束）
    :return: {"status", "role", "found", "removed": [...], "missing": [...]}
    """
    name = safe_role_name(role_name)
    if name in config.BUILTIN_ROLES:
        raise PermissionError(f"「{name}」是内置角色，不允许删除")

    if get_status(name).get("status") == "creating":
        raise RoleBusyError(f"角色「{name}」正在创建中，请等创建完成后再删除")

    removed: list = []
    missing: list = []

    def drop_file(path: str) -> None:
        if os.path.isfile(path):
            try:
                os.remove(path)
                removed.append(_rel(path))
            except OSError:
                # 删不掉（被占用 / 权限）时如实记进 missing，别谎报成功
                traceback.print_exc()
                missing.append(_rel(path))
        else:
            missing.append(_rel(path))

    def drop_dir(path: str) -> None:
        if os.path.isdir(path):
            try:
                shutil.rmtree(path)
                removed.append(_rel(path) + '/')
            except OSError:
                traceback.print_exc()
                missing.append(_rel(path) + '/')
        else:
            missing.append(_rel(path) + '/')

    drop_dir(f'{PICTURES_DIR}/{name}')
    drop_file(f'{DESC_DIR}/{name}.txt')
    for item in list_temp_images(name):
        drop_file(f'{TEMP_DIR}/{item["filename"]}')
    drop_file(f'{ROLES_DIR}/{name}.txt')
    drop_dir(f'{VOICE_DIR}/{name}')
    drop_dir(f'{VOICE_DIR}/{MOCK_VOICE_DIRNAME}/{name}')

    if _remove_records_entry(name):
        removed.append(f'Records.txt: {name}')
    else:
        missing.append(f'Records.txt: {name}')

    if unregister_custom_voice(name):
        removed.append(f'custom_role_voices.json: {name}')
    else:
        missing.append(f'custom_role_voices.json: {name}')

    with _status_lock:
        ROLE_CREATION_STATUS.pop(name, None)

    return {
        "status": "deleted",
        "role": name,
        "found": bool(removed),
        "removed": removed,
        "missing": missing,
    }


# --------------------------------------------------------------------------
# 角色清点：后端磁盘是真相源，前端列表只是缓存
# --------------------------------------------------------------------------
# 与角色无关的内部目录：清点时必须排除，否则会把 `Role_Description`
# 当成一个叫「Role_Description」的角色塞给前端。
_INTERNAL_DIRNAMES = frozenset({'Role_Description', 'temp', '_samples', MOCK_VOICE_DIRNAME})


def _subdirs(base: str) -> list:
    """列出一层子目录名，排除内部目录。目录不存在返回空表（不是错误）。"""
    if not os.path.isdir(base):
        return []
    return [
        name for name in os.listdir(base)
        if os.path.isdir(os.path.join(base, name)) and name not in _INTERNAL_DIRNAMES
    ]


def _txt_stems(base: str) -> list:
    """列出 <base>/*.txt 的文件名主干（去掉 .txt），即角色名。"""
    if not os.path.isdir(base):
        return []
    return [os.path.splitext(name)[0] for name in os.listdir(base) if name.endswith('.txt')]


def list_custom_roles() -> list:
    """列出磁盘上**真实存在**的自定义角色（内置角色不算）。

    为什么需要这个接口：前端 localStorage 里的自定义角色只是一份缓存。
    删除中途失败、在另一个标签页里操作、或者有人直接清过 assets 目录，
    缓存就会和磁盘对不上。典型症状是「角色早就删了，下拉框里却还留着，
    再点删除又因为磁盘上已经没有它的记录，看起来像是没删掉」。

    判存在的探针刻意与 `delete_role` 的清理范围**一一对应**（音色登记、
    人设、形象描述、立绘目录、候选图、语音槽位），任何一处还在就算它还在。
    两边范围一旦漂移，就会出现「清单说没有、文件其实还在」的假删除。
    """
    found = set()

    # ① 音色登记 —— 创建成功的角色一定在这里
    try:
        with open(config.CUSTOM_ROLE_VOICES_PATH, 'r', encoding='utf-8') as file:
            data = json.load(file)
        if isinstance(data, dict):
            found.update(str(key) for key in data)
    except (OSError, ValueError):
        # 文件不存在或不是合法 JSON：不代表没有角色，继续看其它探针
        pass

    # ② 人设文本 roles/<角色>.txt
    found.update(_txt_stems(ROLES_DIR))
    # ③ 形象描述 pictures/Role_Description/<角色>.txt
    found.update(_txt_stems(DESC_DIR))
    # ④ 立绘与情绪图 pictures/<角色>/
    found.update(_subdirs(PICTURES_DIR))
    # ⑤ 未选中的候选图 pictures/temp/<角色>_<index>.jpg
    if os.path.isdir(TEMP_DIR):
        for filename in os.listdir(TEMP_DIR):
            stem = os.path.splitext(filename)[0]
            # 末段是序号，去掉它才是角色名（角色名本身可以含下划线，
            # 如 Testificate_Boy，所以只能从右边切一次）
            if '_' in stem:
                found.add(stem.rsplit('_', 1)[0])
    # ⑥ 语音槽位 voice/<角色>/ 与 voice/_mock/<角色>/
    found.update(_subdirs(VOICE_DIR))
    found.update(_subdirs(os.path.join(VOICE_DIR, MOCK_VOICE_DIRNAME)))

    return sorted(found - set(config.BUILTIN_ROLES) - _INTERNAL_DIRNAMES)


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'samples':
        print(f"TTS provider = {config.TTS_PROVIDER}")
        print("-" * 60)
        result = generate_all_voice_samples(force='--force' in sys.argv)
        failed = [k for k, ok in result.items() if not ok]
        print("-" * 60)
        print("失败音色：" + ", ".join(failed) if failed else "全部生成完毕。")
    else:
        print(__doc__)
