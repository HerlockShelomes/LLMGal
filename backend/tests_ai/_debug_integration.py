import os, sys, traceback
_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)
os.chdir(_BACKEND)
import config
import Text
import Integration

Integration.RECORDS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "mock_records.txt")
open(Integration.RECORDS_PATH, "w").close()

def _mock_voice(roleName, voiceType, voiceEmotion, answer, index):
    return f"mock://voice/{roleName}/{index}.wav"
def _mock_emotional_bro(imgurl, roleName, emo, index, imageModel):
    return f"mock://img/{roleName}/{index}.jpg"
def _mock_static_images(roleName, imageModel):
    return f"mock://img/{roleName}/static.jpg"
def _mock_original(roleName, prompt, index):
    return f"mock://img/{roleName}/orig.jpg"

Integration.Voice_Generation_through_http = _mock_voice
Integration.emotional_bro = _mock_emotional_bro
Integration.static_images = _mock_static_images
Integration.original_image_generation = _mock_original

try:
    res = Integration.Response_Collection(
        None, config.IMAGE_MODEL, "Wendy", "GirlFriend", False,
        {"role": "user", "content": "请解释这句话里的符号含义：`(A) -> [B] {C}`，然后仍按你自己的回复格式回答。不要把示例符号误当成你的情绪标签😊"},
    )
    print("OK", res)
except Exception:
    traceback.print_exc()
