import os
import re
import threading
import traceback

import config
import MockMode
from Text import get_llm_response
from Voice import Voice_Generation_through_http
from Image import emotional_bro
from Image import static_images
from Image import original_image_generation

RECORDS_PATH = '../frontend/src/assets/Records.txt'

# 同一角色的「读取槽位 -> 推进槽位 -> 写回」必须是原子的。
# 否则并发请求会读到同一个 index，共用同一份图片/语音资源并相互覆盖。
_role_locks: dict[str, threading.Lock] = {}
_role_locks_guard = threading.Lock()


def _lock_for(roleName: str) -> threading.Lock:
    """按角色名分片加锁，不同角色之间不互相阻塞。"""
    with _role_locks_guard:
        return _role_locks.setdefault(roleName, threading.Lock())


def _read_records_lines():
    """读取 Records 全部行；文件不存在时返回空列表而不抛异常。"""
    try:
        with open(RECORDS_PATH, 'r', encoding='utf-8') as file:
            return file.readlines()
    except FileNotFoundError:
        return []


def _write_records_lines(lines):
    """写回 Records，必要时创建其所在目录。"""
    directory = os.path.dirname(RECORDS_PATH)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(RECORDS_PATH, 'w', encoding='utf-8') as writeFile:
        writeFile.writelines(lines)


def _advance_index_only(roleName, newIndex):
    """只推进 index 行（不动 Recent_Url），用于并发下的槽位原子占位。

    角色记录不存在时不做任何事：该场景已由调用方降级处理，
    真正落盘交给流程末尾的 updateLinks 补齐。
    """
    lines = _read_records_lines()
    for i in range(len(lines)):
        if f"{roleName}:\n" in lines[i] and i + 2 < len(lines):
            lines[i + 2] = f'index:{newIndex}\n'
            _write_records_lines(lines)
            return

# class MultimodalAdapter:
#     def __init__(self, provider: str):
#         self.provider = provider  # "openai"/"volcengine"/"localai"
#
#     def call(self, input: dict):
#         # 文本处理
#         if input["modality"] == "text":
#             if self.provider == "openai":
#                 yield from self._openai_text(input)
#             elif self.provider == "volcengine":
#                 yield from self._volc_text(input)
#
#         # 图像生成
#         elif input["modality"] == "image":
#             if self.provider == "openai":
#                 yield from self._dalle_api(input)
#             elif self.provider == "volcengine":
#                 yield from self._volc_image(input)
#
#         # 语音合成
#         elif input["modality"] == "audio":
#
#
# # 使用示例（前端无需修改）
# adapter = MultimodalAdapter("volcengine")
# for chunk in adapter.call({"text": "你好", "modality": "voice"}):
#     websocket.send(chunk)

def request_confirmation(voice, emo):
    """
    :param voice: 指示此次前端选择的语音模型
    :param emo: 指示本次大语言模型回复的情绪状态
    :return: 返回根据声音选择和情绪状态输入得到的转换：具体声音类型字符串、回复声音情绪状态、情绪图片标题[0]及具体描述。
    """
    match voice:
        case "GirlFriend":
            selected_voice = "zh_female_tianxinxiaomei_emo_v2_mars_bigtts"
        case "BoyFriend":
            selected_voice = "zh_male_yourougongzi_emo_v2_mars_bigtts"
        case "ElderSister":
            selected_voice = "zh_female_gaolengyujie_emo_v2_mars_bigtts"
        case "LiteratureGuy":
            selected_voice = "zh_male_ruyayichen_emo_v2_mars_bigtts"
        case _:
            selected_voice = "zh_female_tianxinxiaomei_emo_v2_mars_bigtts"
        # 前端调整之后这里或许可以直接获取对应的数值，但这段代码还是先保留吧。
    match emo:
        case '中性':
            selected_emo_voice = "neutral"
            selected_emo_image = ["neutral", "calm with a smile on the face"]
        case '高兴':
            # 原先高兴/生气/惊喜/害羞四种情绪全被压成 neutral，
            # 换再好的语音模型也表现不出来（等于白花钱升级）。
            selected_emo_voice = "happy"
            selected_emo_image = ["happy", "happy to hear your response"]
        case '悲伤':
            selected_emo_voice = "sad"
            selected_emo_image = ["sad", "very sad because you hurt the person's feelings and there are tears on the face"]
        case '害怕':
            selected_emo_voice = "fear"
            selected_emo_image = ["fear", "scared because you said something too scary"]
        case '生气':
            selected_emo_voice = "angry"
            selected_emo_image = ["angry", "angry because you said something too rude"]
        case '惊喜':
            selected_emo_voice = "surprised"
            selected_emo_image = ["surprised", "surprised because your response is quite unexpected"]
        case '害羞':
            selected_emo_voice = "shy"
            selected_emo_image = ["shy", "shy due to the truth that the person likes you as well, and cheeks are red"]
        case _:
            selected_emo_voice = "neutral"
            selected_emo_image = ["neutral", "calm with a smile on the face"]

    return selected_voice, selected_emo_voice, selected_emo_image


def updateLinks(roleName, updatedUrl, updatedIndex):
    lines = _read_records_lines()
    for i in range(len(lines)):
        if f"{roleName}:\n" in lines[i] and i + 2 < len(lines):
            lines[i+1] = f'Recent_Url:{updatedUrl}\n'
            lines[i+2] = f'index:{updatedIndex}\n'
            break
    else:
        # 角色记录缺失（文件不存在或没有该角色块）：补一份最小记录再写入。
        # 否则降级分支走完之后仍会在写回阶段抛 FileNotFoundError，整个请求白做。
        if lines and not lines[-1].endswith('\n'):
            lines[-1] += '\n'
        lines.extend([
            f'{roleName}:\n',
            f'Recent_Url:{updatedUrl}\n',
            f'index:{updatedIndex}\n',
        ])
    _write_records_lines(lines)


def Response_Collection(textModel, imageModel, roleName, voiceName, realTimeGeneration, text, history=None, sessionId=None, on_reasoning=None):
    """
    现阶段设计下，模型应该只支持中文对话。后续应当如何更改提升泛化能力？
    :param textModel: 指示此次生成所使用的文本模型。
    :param imageModel: 指示此次生成所使用的图生图模型。
    :param roleName: 指示此次生成回复所使用的角色。
    :param voiceName: 指示此次回复应当使用的声音。
    :param realTimeGeneration: 指示此次是否需要实时生成图片。为二元布尔值。
    注意，实时生成的图片，因为保持人物的样式需要使用图片url，有效期为24小时，
    因此此处采取一个判断。
    前端记录最近文件的url，并尝试调用此url用于图生图模型姿态调整。
    如果成功，那就使用以此法生成的新图片。
    如果失败，就调用文生图模型生成新的形象。
    静态资源和实时生成资源需要区分开。
    :param text: 指示此次的用户输入提示词。
    :param history: 可选，多轮历史消息（[{role, content}, ...]），用于让模型记住上下文。
    :param sessionId: 可选，会话标识，便于日志追踪。
    :return: (回复文本, 资源序号, 情绪标签, 本次新生成的图片 url, 处理状态)
             状态为 success / partial：语音或图片任一失败即降级为 partial，
             不再像缺陷 009 那样失败也谎报 success。
    """

    # Mock 版：AI 不下场。必须放在最前面 —— 角色锁、Records 读写、LLM、TTS、
    # 图像生成，一个都不能碰。这样「切到 mock 后不再产生任何厂商调用」是结构上
    # 的事实，而不是靠调用方自觉。返回契约与正式版完全一致，前端无需区分。
    if config.is_mock():
        return MockMode.build_mock_response(
            roleName, text, voiceName, history, sessionId
        )

    with _lock_for(roleName):
        try:
            with open(RECORDS_PATH, 'r', encoding='utf-8') as file:
                content = file.read()
            # 捕获组放宽为 [^\n]*：非法索引（如 "abc"）也应先被取出，
            # 交由后续 int(index) 以 ValueError 失败，而不是在此处提前失配导致 IndexError。
            pattern = fr'{roleName}:\nRecent_Url:\s*([^\n]*)\nindex:([^\n]*)'
            matches = re.findall(pattern, content, flags=re.MULTILINE)
            if matches:
                imgurl, index = matches[0]
            else:
                # 角色记录缺失：按与文件缺失相同的策略降级，
                # 而不是让 matches[0] 抛出未受控的 IndexError。
                print(f"未找到角色 {roleName} 的记录。将调用静态默认模型代替")
                realTimeGeneration = False
                imgurl = ""
                index = "0"

        except FileNotFoundError:
            print("文件未找到，请检查文件路径。将调用静态默认模型代替")
            realTimeGeneration = False
            imgurl = ""
            index = "0"
        except IOError:
            print("发生IO错误，无法读取文件。将调用静态默认模型代替。")
            realTimeGeneration = False
            imgurl = ""
            index = "0"

        # 原子占位：在锁内把槽位推进一位，后来的并发请求就不会读到同一个 index。
        # 非数字索引在此不抛异常，留到原位置由 int(index) 以 ValueError 报出，
        # 以保持「外部副作用先发生、转换失败在后」的既有契约。
        try:
            _advance_index_only(roleName, str((int(index) + 1) % 10))
        except ValueError:
            pass
    # index: 指示此次生成所对应的角色资源序号。（从0-9，超出9就复归0重新计数）

    # 项目此前零多轮记忆：只发当前这一句，模型窗口再大也用不上。
    # 现在把前端传来的历史一并交给模型（清洗与长度限制在 Text.sanitize_history 内）。
    # on_reasoning 透传给 LLM 层：推理模型每产生一段思考内容就实时回调，
    # 由 Connect 侧经 WebSocket 推给前端做流式展示；非推理模型不会触发。
    answer = get_llm_response(textModel, roleName, text, history, on_reasoning)

    pattern = r'\((.*?)\)'
    try:
        match = re.findall(pattern, answer)
        if len(match) >= 2:
            emotion = match[0]
            emo_desc = match[1]
        elif len(match) == 1:
            emotion = match[0]
            emo_desc = ''
        else:
            emotion = '中性'
            emo_desc = ''
        print("人物情绪：", emotion)
        print("具体描述：", emo_desc)
    except:
        emotion = '中性'
        emo_desc = ''
        print("情绪提取不成功……，复归默认值")

    voiceType, voiceEmotion, imageEmotion = request_confirmation(voiceName, emotion)

    # 角色音色优先：让每个角色的发音各不相同。
    # 前端原先对所有角色都发同一个 voiceCate，四个角色说话一模一样；
    # voiceCate 现在只作为角色未登记音色时的兜底。
    voiceType = config.resolve_role_voice_volc(roleName, voiceType)

    # 缺陷 009：TTS 失败时不能再谎报 success。这里记录结果并降级状态。
    # 注意 N04：Voice 内部会剥掉开头的情绪括号，用户不会听到「（高兴）」被念出来。
    voice_path = ""
    try:
        voice_path = Voice_Generation_through_http(roleName, voiceType, voiceEmotion, answer, index)
    except Exception:
        traceback.print_exc()
        voice_path = ""
    voice_ok = bool(voice_path)
    # 注意此处：role的名称尚未提取，可以使用正则表达式提取；
    # 此处更改了规范，以role的名称索引对应的角色提示词和形象生成词。
    # 角色提示词规范，后续还需要继续优化。
    # 一旦更新了index，那么前端应当调用的音频序号，就是当前index-1.同时如果index==0，那么调用音频的index就是9.
    # 此处为了调用的一致性，index统一跟随音频index变换，不做实时渲染和音频序号的区分。

    updatedUrl = ""
    image_ok = True
    print("是否进行实时图片生成: ", realTimeGeneration)
    if (realTimeGeneration):
        print("实时图片生成调用")
        # do something...此处需要获取最新的url用于图片的生成。
        # 如果没有url或者url失效（代码层面，这两者产生的效果相同，都是invalid url）
        # 那就调用原始图像生成模型使用提示词创建一个，
        # 将其存储后反馈前端。
        try:
            updatedUrl = emotional_bro(imgurl, roleName, [emotion, emo_desc], index, imageModel)
        except Exception as exception:
            print("Url out of date, regenerating...")
            traceback.print_exc()
            try:
                updatedUrl = original_image_generation(roleName, "".join([emotion, " because ", emo_desc]), index)
            except Exception:
                traceback.print_exc()
                updatedUrl = ""
                image_ok = False
        # 一旦更新了index，那么前端应当调用的图片，就是当前index-1.同时如果index==0，那么调用图片的index就是9.

        # 将最新的index和url更新入文本文档内

    else:
        # 不采取实时图片渲染模式，就直接从静态图片库中检查图片。
        # 如果角色新创建，一张图片都没有，就调用静态图片生成函数原地生成。
        # 这只是一层保险，一般而言创建角色初期就应当完成静态图片的全部生成。

        # 后续和前端协作时，需要注意转到角色创建界面时，
        # 先使用函数生成单张图片确定符合用户预期效果，
        # 再转入情绪图片生成。或许也不必一次生成所有图片，而是需要用户确认一张图片情绪符合自己需求后再转入下一张？
        # 不用了，暂时在确认基本需求的一张图片之后，就把所有情绪图片一把生成出来吧，也算是给用户留一点悬念？
        # 指定文件夹路径
        # 现阶段采取一个很暴力的纠错方式。
        # 如果发现角色名称下静态资源图片不全，就调用模型立刻生成一波新的图片。
        # 这个纠错模式不是不可行，但是很明显有更节省资源的方法。
        # 但是现阶段先将东西做出来再说优化吧。
        print("静态图片生成调用")
        try:
            updatedUrl = static_images(roleName, imageModel)
        except Exception:
            traceback.print_exc()
            updatedUrl = ""
            image_ok = False

    index = int(index)
    index = (index + 1) % 10
    updatedIndex = str(index)

    # 缺陷 B07：本次没有新生成图片时（静态资源已存在），绝不能用空串覆盖
    # Records 里已有的 Recent_Url。否则参考图链条一断，之后每轮都会退化成
    # 昂贵的文生图重生成，100 元预算会瞬间烧光。
    recordsUrl = updatedUrl if updatedUrl else imgurl

    # 缺陷 N01：写回必须和「读取槽位」处在同一把角色锁内。
    # 原先 updateLinks 在锁外执行，并发下两个请求会各自读到旧值再互相覆盖，
    # 导致 index 回退、不同请求复用同一个资源槽位并覆盖彼此的图片/语音。
    with _lock_for(roleName):
        updateLinks(roleName, recordsUrl, updatedIndex)

    print("运行到这里了，Check!")

    # 缺陷 009：语音或图片任一失败，都要如实降级为 partial。
    status = "success" if (voice_ok and image_ok) else "partial"

    return answer, str((index-1)%10), imageEmotion[0], updatedUrl, status
    #此处返回的index必须-1，或者归为9(index==0时)，才能正确索引应使用图片及语音。




