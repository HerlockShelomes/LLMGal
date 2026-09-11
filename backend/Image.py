"""Image generation adapters and static emotion-image management."""

from __future__ import annotations

import os
import re
from pathlib import Path

import requests


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PICTURES_DIR = REPOSITORY_ROOT / "frontend" / "src" / "assets" / "pictures"
ROLE_DESCRIPTION_DIR = PICTURES_DIR / "Role_Description"

EMOTION_IMAGES = [
    ("neutral", "calm with a smile on the face"),
    ("happy", "happy to hear your response"),
    (
        "sad",
        "very sad because you hurt the person's feelings and there are tears on the face",
    ),
    ("fear", "scared because you said something too scary"),
    ("angry", "angry because you said something too rude"),
    ("surprised", "surprised because your response is quite unexpected"),
    ("shy", "shy because the person likes you as well, with reddish cheeks"),
]
# Backwards-compatible name retained for existing callers.
emo_image = [list(item) for item in EMOTION_IMAGES]


def save_image_from_url(url: str, save_path: str | Path) -> bool:
    path = Path(save_path)
    try:
        response = requests.get(url, stream=True, timeout=30)
        if response.status_code != 200:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as output:
            for chunk in response.iter_content(1024):
                if chunk:
                    output.write(chunk)
    except (requests.exceptions.RequestException, OSError):
        return False
    return True


def create_role_image_prompt(
    role_name: str, subject_description: str, appearance_details: str
) -> bool:
    path = Path(ROLE_DESCRIPTION_DIR) / f"{role_name}.txt"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "Subject Description: "
            + subject_description
            + "\nAppearance Details: "
            + appearance_details,
            encoding="utf-8",
        )
    except OSError:
        return False
    return True


def get_role_image_prompt(role_name: str) -> tuple[str, str]:
    path = Path(ROLE_DESCRIPTION_DIR) / f"{role_name}.txt"
    try:
        content = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError) as exc:
        raise ValueError(f"角色 {role_name!r} 的图片描述文件不可读") from exc

    subject = re.search(
        r"Subject Description:\s*(.+?)(?=\nAppearance Details:|$)",
        content,
        re.DOTALL,
    )
    appearance = re.search(r"Appearance Details:\s*(.+?)$", content, re.DOTALL)
    if subject is None or appearance is None:
        raise ValueError(f"角色 {role_name!r} 的图片描述格式无效")
    return subject.group(1).strip(), appearance.group(1).strip()


def _create_visual_service():
    from volcengine.visual.VisualService import VisualService

    access_key = os.getenv("LLMGAL_IMAGE_ACCESS_KEY")
    secret_key = os.getenv("LLMGAL_IMAGE_SECRET_KEY")
    if not access_key or not secret_key:
        raise RuntimeError(
            "缺少环境变量 LLMGAL_IMAGE_ACCESS_KEY 或 LLMGAL_IMAGE_SECRET_KEY"
        )
    service = VisualService()
    service.set_ak(access_key)
    service.set_sk(secret_key)
    return service


def original_image_generation(nameRole: str, image_emotion: str, index: str) -> str:
    subject, appearance = get_role_image_prompt(nameRole)
    prompt = (
        "best quality, masterpiece, Japanese anime portrait, white background. "
        f"Subject Description: {subject}. Appearance Details: {appearance}. "
        f"Expression Adjustment: {image_emotion}."
    )
    response = _create_visual_service().cv_process(
        {
            "req_key": "high_aes_general_v20_L",
            "prompt": prompt,
            "seed": -1,
            "scale": 3.5,
            "ddim_steps": 16,
            "width": 512,
            "height": 512,
            "use_sr": True,
            "use_pre_llm": True,
            "return_url": True,
        }
    )
    image_url = response["data"]["image_urls"][0]
    save_path = Path(PICTURES_DIR) / nameRole / f"{nameRole}_{index}.jpg"
    save_image_from_url(image_url, save_path)
    return image_url


def emotional_bro(
    image_url: str,
    role_name: str,
    emotion: list[str],
    index: str,
    model_value: str,
) -> str:
    if model_value not in {"high_aes_ip_v20", "byteedit_v2.0"}:
        return original_image_generation(
            role_name, f"{emotion[0]} because {emotion[1]}", index
        )

    prompt = (
        "Maintain the image style, person, and white background; "
        f"alter the expression so the person looks {emotion[0]} because {emotion[1]}."
    )
    form = {
        "req_key": model_value,
        "image_urls": [image_url],
        "prompt": prompt,
        "seed": -1,
        "return_url": True,
    }
    if model_value == "high_aes_ip_v20":
        form.update(
            {
                "desc_pushback": True,
                "scale": 3.5,
                "ddim_steps": 9,
                "width": 512,
                "height": 512,
                "cfg_rescale": 0.7,
                "ref_ip_weight": 0.9,
                "ref_id_weight": 0.36,
                "use_sr": True,
            }
        )
    else:
        form.update({"negative_prompt": "low quality, watermark", "scale": 0.5})

    response = _create_visual_service().cv_process(form)
    generated_url = response["data"]["image_urls"][0]
    save_path = Path(PICTURES_DIR) / role_name / f"{role_name}_{index}.jpg"
    save_image_from_url(generated_url, save_path)
    return generated_url


def static_images(roleCall: str, picture_model: str) -> str:
    folder = Path(PICTURES_DIR) / roleCall
    folder.mkdir(parents=True, exist_ok=True)
    expected_files = {f"{roleCall}_{emotion}.jpg" for emotion, _ in EMOTION_IMAGES}
    present_files = {path.name for path in folder.iterdir() if path.is_file()}
    if expected_files.issubset(present_files):
        return ""

    initial_url = original_image_generation(
        roleCall, EMOTION_IMAGES[0][1], EMOTION_IMAGES[0][0]
    )
    for emotion, description in EMOTION_IMAGES[1:]:
        emotional_bro(
            initial_url,
            roleCall,
            [emotion, description],
            emotion,
            picture_model,
        )
    return initial_url
