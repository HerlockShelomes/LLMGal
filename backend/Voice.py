import asyncio
import base64
import copy
import gzip
import json
import logging
import os
import re
import uuid

import requests
import websockets

import config

MESSAGE_TYPES = {11: "audio-only server response", 12: "frontend server response", 15: "error message from server"}
MESSAGE_TYPE_SPECIFIC_FLAGS = {0: "no sequence number", 1: "sequence number > 0",
                               2: "last message from server (seq < 0)", 3: "sequence number < 0"}
MESSAGE_SERIALIZATION_METHODS = {0: "no serialization", 1: "JSON", 15: "custom type"}
MESSAGE_COMPRESSIONS = {0: "no compression", 1: "gzip", 15: "custom compression method"}

# 火山（volcengine）凭据：原先硬编码在源码里（缺陷 B01），现改为从 .env 读取。
appid = config.TTS_VOLC_APPID
token = config.TTS_VOLC_TOKEN
cluster = config.TTS_VOLC_CLUSTER
host = "openspeech.bytedance.com"
api_url = f"wss://{host}/api/v1/tts/ws_binary"
reqid = uuid.uuid4()


def strip_emotion_tags(text: str) -> str:
    """剔除正文开头的情绪括号。

    缺陷 N04：LLM 的原文形如「(高兴)(因为受到邀请)你好呀」，直接送 TTS 会让用户
    亲耳听到「（高兴）（因为受到邀请）」被念出来。只剥离开头的连续括号组，
    正文中间正常使用的括号不受影响。
    """
    if not text:
        return ""
    return re.sub(r'^\s*(?:\([^()]*\)\s*)+', '', text)


# 情绪标签（Integration 用英文）→ 中文演播指令，供 Qwen3-TTS 的 instructions 使用
EMOTION_TO_CHINESE = {
    "neutral": "平静",
    "happy": "开心",
    "sad": "悲伤",
    "fear": "害怕",
    "angry": "生气",
    "surprised": "惊喜",
    "shy": "害羞",
}


def resolve_qwen_voice(volc_voice: str, role: str = "") -> str:
    """决定本次合成用哪个 Qwen3-TTS 音色。

    优先级：显式 Qwen 音色名 > 角色名登记的专属音色 > 火山音色 ID 映射 > 全局默认。

    前端原先对所有角色都发同一个 voiceCate，四个角色说话一模一样。
    现在以角色为主键，未登记的角色仍走原来的 voiceCate 映射，行为不变。

    注意第一条不能省：调用方直接给 Qwen 音色名时（试听样本、手动指定）必须原样使用。
    否则它会落到 VOLC_TO_QWEN_VOICE 里查 key（那是火山 ID 的表）→ 查不到 → 回落到
    全局默认音色。试听样本曾因此 24 条全部用 Cherry 合成，听起来完全一样。
    """
    if volc_voice and volc_voice in config.QWEN_VOICE_CATALOG:
        return volc_voice
    role_voice = config.resolve_role_voice(role, "")
    if role_voice:
        return role_voice
    return config.VOLC_TO_QWEN_VOICE.get(volc_voice, config.TTS_QWEN_DEFAULT_VOICE)


# version: b0001 (4 bits)
# header size: b0001 (4 bits)
# message type: b0001 (Full client request) (4bits)
# message type specific flags: b0000 (none) (4bits)
# message serialization method: b0001 (JSON) (4 bits)
# message compression: b0001 (gzip) (4bits)
# reserved data: 0x00 (1 byte)
default_header = bytearray(b'\x11\x10\x11\x00')



def request_confirmation(voice, emo, text_content):
    match voice:
        case 0:
            selected_voice = "zh_female_tianxinxiaomei_emo_v2_mars_bigtts"
        case 1:
            selected_voice = "zh_male_yourougongzi_emo_v2_mars_bigtts"
        case 2:
            selected_voice = "zh_female_gaolengyujie_emo_v2_mars_bigtts"
        case 3:
            selected_voice = "zh_male_ruyayichen_emo_v2_mars_bigtts"
        case _:
            selected_voice = "zh_female_tianxinxiaomei_emo_v2_mars_bigtts"

    match emo:
        case 0, 1, 4, 5, 6:
            selected_emo = "neutral"
        case 2:
            selected_emo = "sad"
        case 3:
            selected_emo = "fear"
        case _:
            selected_emo = "neutral"

    text = text_content

    return selected_voice, selected_emo, text


async def test_submit(r,v,e,t, i):
    Role = r
    selected_voice_type = v
    selected_emotion = e

    request_json = {
        "app": {
            "appid": appid,
            "token": token,
            "cluster": cluster
        },
        "user": {
            "uid": "388808087185088"
        },
        "audio": {
            "voice_type": selected_voice_type,
            "enable_emotion": True,
            "emotion": selected_emotion,
            "emotion_scale": 5,
            "encoding": "mp3",
            "speed_ratio": 1.0,
            "explicit_language": "zh",
            "volume_ratio": 1.0,
            "pitch_ratio": 1.0,
        },
        "request": {
            "reqid": reqid,
            "text": t,
            "text_type": "plain",
            "operation": "submit",
            "disable_markdown_filter": True
        },

        "extra_param": json.dumps({"cache_config": {"text_type": 1, "use_cache": True}})

    }
    submit_request_json = copy.deepcopy(request_json)
    submit_request_json["audio"]["voice_type"] = selected_voice_type
    submit_request_json["request"]["reqid"] = str(uuid.uuid4())
    submit_request_json["request"]["operation"] = "submit"
    payload_bytes = str.encode(json.dumps(submit_request_json))
    payload_bytes = gzip.compress(payload_bytes)  # if no compression, comment this line
    full_client_request = bytearray(default_header)
    full_client_request.extend((len(payload_bytes)).to_bytes(4, 'big'))  # payload size(4 bytes)
    full_client_request.extend(payload_bytes)  # payload
    print("\n------------------------ test 'submit' -------------------------")
    print("request json: ", submit_request_json)
    print("\nrequest bytes: ", full_client_request)

    savePath = f"../frontend/src/assets/voice/{Role}/{Role}_{i}_Stream.mp3"
    os.makedirs(os.path.dirname(savePath), exist_ok=True)
    file_to_save = open(savePath, "wb")
    async with websockets.connect(api_url, extra_headers={"Authorization": f"Bearer; {token}"}, ping_interval=None) as ws:
        await ws.send(full_client_request)
        while True:
            res = await ws.recv()
            done = parse_response(res, file_to_save)
            if done:
                file_to_save.close()
                break
        print("\nclosing the connection...")

def parse_response(res, file):
   print("--------------------------- response ---------------------------")
   # print(f"response raw bytes: {res}")
   protocol_version = res[0] >> 4
   header_size = res[0] & 0x0f
   message_type = res[1] >> 4
   message_type_specific_flags = res[1] & 0x0f
   serialization_method = res[2] >> 4
   message_compression = res[2] & 0x0f
   reserved = res[3]
   header_extensions = res[4:header_size * 4]
   payload = res[header_size * 4:]
   print(f"            Protocol version: {protocol_version:#x} - version {protocol_version}")
   print(f"                 Header size: {header_size:#x} - {header_size * 4} bytes ")
   print(f"                Message type: {message_type:#x} - {MESSAGE_TYPES[message_type]}")
   print(
      f" Message type specific flags: {message_type_specific_flags:#x} - {MESSAGE_TYPE_SPECIFIC_FLAGS[message_type_specific_flags]}")
   print(
      f"Message serialization method: {serialization_method:#x} - {MESSAGE_SERIALIZATION_METHODS[serialization_method]}")
   print(f"         Message compression: {message_compression:#x} - {MESSAGE_COMPRESSIONS[message_compression]}")
   print(f"                    Reserved: {reserved:#04x}")
   if header_size != 1:
      print(f"           Header extensions: {header_extensions}")
   if message_type == 0xb:  # audio-only server response
      if message_type_specific_flags == 0:  # no sequence number as ACK
         print("                Payload size: 0")
         return False
      else:
         sequence_number = int.from_bytes(payload[:4], "big", signed=True)
         payload_size = int.from_bytes(payload[4:8], "big", signed=False)
         payload = payload[8:]
         print(f"             Sequence number: {sequence_number}")
         print(f"                Payload size: {payload_size} bytes")
      file.write(payload)
      if sequence_number < 0:
         return True
      else:
         return False
   elif message_type == 0xf:
      code = int.from_bytes(payload[:4], "big", signed=False)
      msg_size = int.from_bytes(payload[4:8], "big", signed=False)
      error_msg = payload[8:]
      if message_compression == 1:
         error_msg = gzip.decompress(error_msg)
      error_msg = str(error_msg, "utf-8")
      print(f"          Error message code: {code}")
      print(f"          Error message size: {msg_size} bytes")
      print(f"               Error message: {error_msg}")
      return True
   elif message_type == 0xc:
      msg_size = int.from_bytes(payload[:4], "big", signed=False)
      payload = payload[4:]
      if message_compression == 1:
         payload = gzip.decompress(payload)
      print(f"            Frontend message: {payload}")
   else:
      print("undefined message type!")
      return True

# async def submit_voice(r, v, e, t, i):

async def Voice_Generation (role, voiType, emoType, text, i):
    task = [asyncio.create_task(test_submit(role, voiType, emoType, text, i))]
    await asyncio.gather(*task, return_exceptions=True)

def save_audio_from_base64(audio: str, role, index, ext: str = "mp3") -> str:
    try:
        # 合法 Base64 允许按 76 字符折行（RFC 2045），先剥离空白再严格校验，
        # 避免合法换行被 validate 判定为非法字符。
        audio_payload = "".join(audio.split())
        # validate=True：遇到非法字符（如 "%"）抛 binascii.Error，
        # 而不是像默认的 validate=False 那样静默丢弃后解出空字节并照常落盘。
        audio_data = base64.b64decode(audio_payload, validate=True)
        if not audio_data:
            print("音频数据为空，跳过保存")
            return ""

        savePath = f"../frontend/src/assets/voice/{role}/{role}_{index}_Stream.{ext}"
        os.makedirs(os.path.dirname(savePath), exist_ok=True)
        with open(savePath, 'wb') as audio_file:
            audio_file.write(audio_data)

        print("音频已保存: ", savePath)
        return savePath

    except Exception as e:
        print("音频转码出错: ", e)
        return ""


def save_audio_from_bytes(audio: bytes, role, index, ext: str = "mp3") -> str:
    """把已解码的音频字节落盘到前端静态资源目录。

    :param ext: 扩展名。火山返回 mp3；阿里 Qwen3-TTS 实测返回 WAV，
                两者不能混用同一个扩展名，否则浏览器按错误的 MIME 解析。
    """
    if not audio:
        print("音频数据为空，跳过保存")
        return ""

    savePath = f"../frontend/src/assets/voice/{role}/{role}_{index}_Stream.{ext}"
    os.makedirs(os.path.dirname(savePath), exist_ok=True)
    with open(savePath, 'wb') as audio_file:
        audio_file.write(audio)

    print("音频已保存: ", savePath)
    return savePath


def save_audio_file(audio: bytes, path: str) -> str:
    """把音频字节写到**指定路径**（用于音色试听样本等自定义落盘位置）。

    与 save_audio_from_bytes 的区别：后者按「角色/序号」约定拼路径，
    试听样本不属于任何角色，必须允许调用方直接给完整路径。
    """
    if not audio:
        print("音频数据为空，跳过保存")
        return ""

    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, 'wb') as audio_file:
        audio_file.write(audio)

    print("音频已保存: ", path)
    return path


def _tts_qwen(r, v, e, t, i, save_path: str = ""):
    """阿里百炼 Qwen3-TTS（DashScope 多模态生成接口）。

    每月 100 万字符免费，国内账号、免信用卡，是本项目测试期语音成本归零的关键。

    接口要点（与常见猜测不同，均已实测）：
    - 端点不是 OpenAI 的 /compatible-mode/v1/audio/speech（那个返回 404），
      而是 /api/v1/services/aigc/multimodal-generation/generation；
    - 请求体是 {"model", "input": {"text", "voice", "language_type"}}；
    - 非流式响应里 output.audio.data 是空的，真实音频在 output.audio.url（临时 OSS 链接）；
    - 返回的是 WAV 而不是 MP3，落盘扩展名必须跟上。
    """
    if t is None:
        return ""
    text = str(t).strip()
    if not text:
        print("待合成文本为空，跳过语音生成")
        return ""
    if len(text) > config.TTS_QWEN_MAX_CHARS:
        print(f"文本超过 {config.TTS_QWEN_MAX_CHARS} 字符上限，已截断")
        text = text[: config.TTS_QWEN_MAX_CHARS]

    use_instruct = bool(config.TTS_QWEN_USE_INSTRUCTIONS and e)
    model = config.TTS_QWEN_INSTRUCT_MODEL if use_instruct else config.TTS_QWEN_MODEL

    body = {
        "model": model,
        "input": {
            "text": text,
            "voice": resolve_qwen_voice(v, r),
            "language_type": config.TTS_QWEN_LANGUAGE,
        },
    }
    if use_instruct:
        # 情绪标签在 Integration 里是英文，这里换成中文演播指令
        body["input"]["instructions"] = f"用{EMOTION_TO_CHINESE.get(e, '平静')}的语气说话"

    response = requests.post(
        url=config.TTS_QWEN_ENDPOINT,
        headers={
            "Authorization": f"Bearer {os.environ.get('DASHSCOPE_API_KEY', '')}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=60,
    )
    response.raise_for_status()

    audio = ((response.json().get("output") or {}).get("audio") or {})
    audio_url = audio.get("url")
    if audio_url:
        # 非流式响应不回 base64，音频在临时链接上，需二次下载（会过期，立即取）
        audio_resp = requests.get(url=audio_url, timeout=60)
        audio_resp.raise_for_status()
        if save_path:
            return save_audio_file(audio_resp.content, save_path)
        return save_audio_from_bytes(audio_resp.content, r, i, ext="wav")

    if audio.get("data"):
        if save_path:
            return save_audio_file(base64.b64decode("".join(audio["data"].split()), validate=True), save_path)
        return save_audio_from_base64(audio["data"], r, i, ext="wav")

    raise RuntimeError(f"语音服务未返回音频地址：{response.text[:200]}")


def Voice_Generation_through_http(r, v, e, t, i, provider=None, save_path: str = ""):
    """语音合成统一入口。

    :param provider: 覆盖 config.TTS_PROVIDER，可选 "qwen" / "volcengine"。
                     单元测试会显式指定，避免默认 provider 变化影响既有断言。
    :param save_path: 可选。给定时把音频写到该路径，而不是按「角色/序号」拼路径。
                      音色试听样本不属于任何角色，需要这个出口。
    :return: 成功返回音频文件路径，失败返回空串（调用方据此把状态降级为 partial）。
    """
    selected = (provider or config.TTS_PROVIDER or "qwen").lower()
    # N04：无论哪家，送进 TTS 前都要剥掉开头的情绪括号
    clean_text = strip_emotion_tags(t if isinstance(t, str) else str(t or ""))

    try:
        if selected == "volcengine":
            return _tts_volcengine(r, v, e, clean_text, i, save_path=save_path)
        return _tts_qwen(r, v, e, clean_text, i, save_path=save_path)
    except requests.exceptions.RequestException as error:
        print(f'Request Failed: {error}')
        return ''
    except (KeyError, ValueError) as error:
        # 非 JSON 响应等仍然向上抛出，交由调用方判定为处理失败
        print(f'TTS 响应解析失败: {error}')
        raise
    except Exception as error:  # 其余异常不应拖垮整条对话
        logging.exception("语音合成失败")
        print(f'语音合成失败: {error}')
        return ''


def _tts_volcengine(r, v, e, t, i, save_path: str = ""):

    httpurl = "https://openspeech.bytedance.com/api/v1/tts"

    theHeaders = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer; {token}",
    }

    payload_json = {
        "app": {
            "appid": appid,
            "token": token,
            "cluster": cluster
        },
        "user": {
            "uid": "388808087185088"
        },
        "audio": {
            "voice_type": v,
            "enable_emotion": True,
            "emotion": e,
            "emotion_scale": 5,
            "encoding": "mp3",
            "speed_ratio": 1.0,
            "explicit_language": "zh",
            "volume_ratio": 1.0,
            "pitch_ratio": 1.0,
        },
        "request": {
            "reqid": str(reqid),
            "text": t,
            "text_type": "plain",
            "operation": "query",
            "disable_markdown_filter": True
        },

        "extra_param": json.dumps({"cache_config": {"text_type": 1, "use_cache": True}})

    }

    try:
        response = requests.post(url=httpurl, headers=theHeaders, json=payload_json, timeout=30)
        response.raise_for_status()

        response_data = response.json()
        if 'data' in response_data:
            base64_audio = response_data['data']
            if save_path:
                return save_audio_file(
                    base64.b64decode("".join(base64_audio.split()), validate=True), save_path
                )
            return save_audio_from_base64(base64_audio, r, i)
        else:
            print("Error: No Audio Found.")
            return ''

    except requests.exceptions.RequestException as e:
        print(f'Request Failed: {e}')
        return ''
    except KeyError:
        print('Error: Wrong Respond Payload.')
        return ''



if __name__ == "__main__":
    print(config.describe())
    print(Voice_Generation_through_http(
        'Testificate',
        'zh_female_tianxinxiaomei_emo_v2_mars_bigtts',
        'neutral',
        '猎人大人好喵！今天我们一起去狩猎萌宝吧！',
        'test',
    ))