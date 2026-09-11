"""Business orchestration for text, speech, image, and role resource state."""

from __future__ import annotations

import re
import threading
import traceback
from pathlib import Path

from Image import emotional_bro, original_image_generation, static_images
from Text import get_llm_response
from Voice import Voice_Generation_through_http


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RECORDS_PATH = REPOSITORY_ROOT / "frontend" / "src" / "assets" / "Records.txt"


class RecordStateError(ValueError):
    """Raised when an existing role record is missing or malformed."""


_records_file_lock = threading.RLock()
_role_locks_guard = threading.Lock()
_role_locks: dict[str, threading.Lock] = {}


def _get_role_lock(role_name: str) -> threading.Lock:
    with _role_locks_guard:
        return _role_locks.setdefault(role_name, threading.Lock())


def _find_role_record(lines: list[str], role_name: str) -> tuple[int, str, int]:
    header = f"{role_name}:"
    positions = [index for index, line in enumerate(lines) if line.strip() == header]
    if not positions:
        raise RecordStateError(f"Records.txt 中不存在角色 {role_name!r} 的记录")
    if len(positions) > 1:
        raise RecordStateError(f"Records.txt 中角色 {role_name!r} 的记录重复")

    position = positions[0]
    if position + 2 >= len(lines):
        raise RecordStateError(f"角色 {role_name!r} 的记录不完整")

    url_line = lines[position + 1]
    index_line = lines[position + 2]
    if not url_line.startswith("Recent_Url:") or not index_line.startswith("index:"):
        raise RecordStateError(f"角色 {role_name!r} 的记录格式不正确")

    recent_url = url_line.partition(":")[2].strip()
    raw_index = index_line.partition(":")[2].strip()
    if not raw_index.isdecimal():
        raise RecordStateError(f"角色 {role_name!r} 的 index 必须是 0 到 9 的整数")

    index = int(raw_index)
    if not 0 <= index <= 9:
        raise RecordStateError(f"角色 {role_name!r} 的 index 必须是 0 到 9 的整数")
    return position, recent_url, index


def _read_role_record(role_name: str) -> tuple[str, int]:
    path = Path(RECORDS_PATH)
    with _records_file_lock:
        lines = path.read_text(encoding="utf-8").splitlines()
    _, recent_url, index = _find_role_record(lines, role_name)
    return recent_url, index


def request_confirmation(voice: str, emotion: str) -> tuple[str, str, list[str]]:
    voice_map = {
        "GirlFriend": "zh_female_tianxinxiaomei_emo_v2_mars_bigtts",
        "BoyFriend": "zh_male_yourougongzi_emo_v2_mars_bigtts",
        "ElderSister": "zh_female_gaolengyujie_emo_v2_mars_bigtts",
        "LiteratureGuy": "zh_male_ruyayichen_emo_v2_mars_bigtts",
    }
    emotion_map = {
        "中性": ("neutral", ["neutral", "calm with a smile on the face"]),
        "高兴": ("neutral", ["happy", "happy to hear your response"]),
        "悲伤": (
            "sad",
            [
                "sad",
                "very sad because you hurt the person's feelings and there are tears on the face",
            ],
        ),
        "害怕": ("fear", ["fear", "scared because you said something too scary"]),
        "生气": ("neutral", ["angry", "angry because you said something too rude"]),
        "惊喜": (
            "neutral",
            ["surprised", "surprised because your response is quite unexpected"],
        ),
        "害羞": (
            "neutral",
            [
                "shy",
                "shy due to the truth that the person likes you as well, and cheeks are red",
            ],
        ),
    }
    selected_voice = voice_map.get(voice, voice_map["GirlFriend"])
    voice_emotion, image_emotion = emotion_map.get(emotion, emotion_map["中性"])
    return selected_voice, voice_emotion, image_emotion


def updateLinks(roleName: str, updatedUrl: str, updatedIndex: str) -> None:
    """Atomically update or create one role record.

    An empty URL preserves a non-empty existing URL. This prevents static-image
    requests from destroying the latest URL needed by later real-time requests.
    """

    path = Path(RECORDS_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _records_file_lock:
        if not path.exists():
            path.write_text(
                f"{roleName}:\nRecent_Url:{updatedUrl}\nindex:{updatedIndex}\n",
                encoding="utf-8",
            )
            return

        lines = path.read_text(encoding="utf-8").splitlines()
        try:
            position, current_url, _ = _find_role_record(lines, roleName)
        except RecordStateError as exc:
            if "不存在角色" not in str(exc):
                raise
            if lines and lines[-1].strip():
                lines.append("")
            lines.extend(
                [roleName + ":", "Recent_Url:" + updatedUrl, "index:" + updatedIndex]
            )
        else:
            effective_url = updatedUrl or current_url
            lines[position + 1] = "Recent_Url:" + effective_url
            lines[position + 2] = "index:" + updatedIndex

        temporary_path = path.with_suffix(path.suffix + ".tmp")
        temporary_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        temporary_path.replace(path)


def _extract_emotion(answer: str) -> tuple[str, str]:
    matches = re.findall(r"\((.*?)\)", answer)
    if len(matches) >= 2:
        return matches[0], matches[1]
    if len(matches) == 1:
        return matches[0], ""
    return "中性", ""


def Response_Collection(
    textModel: str,
    imageModel: str,
    roleName: str,
    voiceName: str,
    realTimeGeneration: bool,
    text: dict,
) -> tuple[str, str, str, str]:
    """Execute one request while reserving the role's resource slot."""

    with _get_role_lock(roleName):
        path = Path(RECORDS_PATH)
        if path.exists():
            image_url, index = _read_role_record(roleName)
        else:
            image_url, index = "", 0
            realTimeGeneration = False

        # Validate state before any external dependency can create side effects.
        index_string = str(index)
        answer = get_llm_response(textModel, roleName, text)
        emotion, emotion_reason = _extract_emotion(answer)
        voice_type, voice_emotion, image_emotion = request_confirmation(
            voiceName, emotion
        )
        Voice_Generation_through_http(
            roleName, voice_type, voice_emotion, answer, index_string
        )

        updated_url = ""
        if realTimeGeneration:
            try:
                updated_url = emotional_bro(
                    image_url,
                    roleName,
                    [emotion, emotion_reason],
                    index_string,
                    imageModel,
                )
            except Exception:
                traceback.print_exc()
                updated_url = original_image_generation(
                    roleName,
                    f"{emotion} because {emotion_reason}",
                    index_string,
                )
        else:
            updated_url = static_images(roleName, imageModel)

        next_index = (index + 1) % 10
        updateLinks(roleName, updated_url or image_url, str(next_index))
        return answer, index_string, image_emotion[0], updated_url
