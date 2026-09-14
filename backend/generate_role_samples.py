"""为每个角色用它自己的音色重新生成一句打招呼音频。

产物：frontend/src/assets/voice/<角色>/<角色>_test_Stream.wav
前端设置面板「这个角色在向你打招呼」的试听按钮播的就是它，
重新生成后四个角色的音色区别可以直接听出来。

用法（必须在 backend 目录下执行，静态资源用的是相对路径）：
    python generate_role_samples.py              # 全部角色
    python generate_role_samples.py Wendy        # 只重生成指定角色
"""

import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from Voice import Voice_Generation_through_http, resolve_qwen_voice

# 台词贴合各自人设，这样音色差异听起来更明显
GREETINGS = {
    "Wendy": "你好呀，我是温蒂。今天过得还好吗？要不要一起出去走走？",
    "Testificate": "喵！我是修勾，你的好伙伴！今天也要一起加油哦！",
    "Testificate_Boy": "嗨，我是艾瑞克。最近在忙什么？有空的话一起打两局？",
    "GirlProgrammer": "……你好，我是凯特。有什么想聊的，直接说就好。",
}

SAMPLE_INDEX = "test"


def main() -> int:
    wanted = sys.argv[1:] or list(GREETINGS)
    failed = []

    print(f"TTS provider = {config.TTS_PROVIDER}")
    print("-" * 60)

    for role in wanted:
        text = GREETINGS.get(role)
        if not text:
            print(f"[跳过] {role}：没有配置打招呼台词")
            continue

        voice = config.resolve_role_voice(role, "") or resolve_qwen_voice("ElderSister", role)
        try:
            path = Voice_Generation_through_http(role, "ElderSister", "neutral", text, SAMPLE_INDEX)
        except Exception:
            traceback.print_exc()
            failed.append(role)
            continue

        if not path:
            failed.append(role)
            print(f"[失败] {role}：语音服务未返回音频")
            continue

        size = os.path.getsize(path) if os.path.exists(path) else 0
        print(f"[完成] {role:<18} 音色={voice:<8} -> {path}（{size / 1024:.0f} KB）")

    print("-" * 60)
    if failed:
        print(f"失败角色：{', '.join(failed)}")
        return 1
    print("全部生成完毕。刷新前端页面即可在设置面板试听。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
