import asyncio
import base64
import websockets
import uuid
import json
import gzip
import copy
import os
import requests

MESSAGE_TYPES = {11: "audio-only server response", 12: "frontend server response", 15: "error message from server"}
MESSAGE_TYPE_SPECIFIC_FLAGS = {0: "no sequence number", 1: "sequence number > 0",
                               2: "last message from server (seq < 0)", 3: "sequence number < 0"}
MESSAGE_SERIALIZATION_METHODS = {0: "no serialization", 1: "JSON", 15: "custom type"}
MESSAGE_COMPRESSIONS = {0: "no compression", 1: "gzip", 15: "custom compression method"}

appid = "7535590105"
token = "_SRNKZhKXevBrx72wklF-D8NX7LGigGs"
cluster = "volcano_tts"
host = "openspeech.bytedance.com"
api_url = f"wss://{host}/api/v1/tts/ws_binary"
reqid = uuid.uuid4()


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
    async with websockets.connect(api_url, extra_headers={"Authorization": "Bearer; _SRNKZhKXevBrx72wklF-D8NX7LGigGs"}, ping_interval=None) as ws:
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

def save_audio_from_base64(audio: str, role, index) -> str:
    try:
        savePath = f"../frontend/src/assets/voice/{role}/{role}_{index}_Stream.mp3"
        os.makedirs(os.path.dirname(savePath), exist_ok=True)
        audio_data = base64.b64decode(audio)
        with open(savePath, 'wb') as audio_file:
            audio_file.write(audio_data)

        print("音频已保存: ", savePath)
        return savePath

    except Exception as e:
        print("音频转码出错: ", e)
        return ""


def Voice_Generation_through_http(r, v, e, t, i):

    httpurl = "https://openspeech.bytedance.com/api/v1/tts"

    theHeaders = {
        "Content-Type": "application/json",
        "Authorization": "Bearer; _SRNKZhKXevBrx72wklF-D8NX7LGigGs",
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
    Voice_Generation_through_http('Testificate', 'zh_female_tianxinxiaomei_emo_v2_mars_bigtts', 'neutral','猎人大人好喵！今天我们一起去狩猎萌宝吧！','test')