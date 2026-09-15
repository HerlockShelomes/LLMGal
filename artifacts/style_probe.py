"""画风验证探针：同一角色描述，分别出「基准立绘」与「情绪扩展图」。

用途：确认 Image.build_style_head() 收敛后，两条出图路径的风格一致，
且提示词里不含摄影/写实词汇。产物落在 artifacts/ 下，便于肉眼比对。

运行（cwd 必须是 backend/）：
    cd backend
    PYTHONDONTWRITEBYTECODE=1 E:/Anaconda/envs/vue-fastapi/python.exe ../artifacts/style_probe.py
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import config  # noqa: E402
import Image  # noqa: E402

SUBJECT = "a calm and gentle young woman, the eldest daughter of a noble family"
APPEARANCE = (
    "long straight silver hair with a single braid, light blue eyes, "
    "fair skin, a simple white and navy dress with lace trim"
)

OUT = ROOT / "artifacts"


def main() -> int:
    base_prompt = Image.build_portrait_prompt(
        SUBJECT, APPEARANCE, expression="neutral, calm with a smile on the face"
    )
    emo_prompt = Image.build_expression_prompt("happy", "she is glad to see you")

    print("=" * 78)
    print("provider :", config.IMAGE_PROVIDER, config.IMAGE_ZHIPU_MODEL)
    print("style head:", Image.build_style_head())
    print("-" * 78)
    print("[基准立绘 prompt]\n" + base_prompt)
    print("-" * 78)
    print("[情绪扩展 prompt]\n" + emo_prompt)
    print("=" * 78)

    targets = [
        ("style_unified_base.jpg", base_prompt),
        ("style_unified_emotion.jpg", emo_prompt),
    ]
    for filename, prompt in targets:
        path = OUT / filename
        print(f"[生成] {filename} ...")
        Image.generate_image_openai_compatible(prompt, str(path), size=config.IMAGE_ROLE_SIZE)
        print(f"[完成] {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
