"""画风一致性用例（TC-STYLE-*）。

背景（2026-09-14）：项目要求出图风格统一为「二次元动漫原画」。但立绘与
情绪扩展图原先各自手写提示词 —— 立绘走 Image.build_portrait_prompt，
情绪图 emotional_bro 自己写了一段 `Positive Prompt: best quality, masterpiece,
ultra-high resolution` 的 SD 标签脚手架，两处画风对不上，实测情绪图偏写实。

修法：画风收敛成 `Image.build_style_head()` 单一入口，默认取
`config.IMAGE_STYLE_PROMPT`（项目底层默认值 = 二次元动漫原画）。

本文件就是这条约定的回归闸门：
  · 画风只能从 build_style_head 取，两条出图路径必须共享同一个头；
  · 正面提示词里不得再出现摄影/写实词汇或 SD 标签脚手架。
"""
from __future__ import annotations

import pytest

import config
import Image


# 摄影 / 写实 / SD 脚手架词汇：正面提示词里一旦出现就会把指令式模型
# （CogView / Seedream）拉向写实人像，属于禁用词。
BANNED_IN_POSITIVE = (
    "photo",
    "realistic",
    "photorealistic",
    "3d render",
    "3d",
    "studio lighting",
    "ultra-high resolution",
    "masterpiece",
    "positive prompt",
    "negative prompt",
    "sharp focus",
)


def _positive_part(prompt: str) -> str:
    """剥掉末尾的负面提示词，只检查正面部分。

    PORTRAIT_NEGATIVE_HINT 里本身带有 "no photo / no photorealism / no 3D render"
    这类否定表述，必须在检查前移除，否则会误报。
    """
    return prompt.replace(Image.PORTRAIT_NEGATIVE_HINT, "").lower()


# --------------------------------------------------------------------------
# 底层默认值
# --------------------------------------------------------------------------
def test_tc_style_01_config_default_is_anime():
    """项目底层默认画风是二次元动漫。"""
    assert "anime" in config.IMAGE_STYLE_PROMPT.lower()
    assert config.IMAGE_STYLE_PROMPT.strip()


def test_tc_style_02_style_head_falls_back_to_config():
    """不传 style 时，画风头 == config.IMAGE_STYLE_PROMPT。"""
    assert Image.build_style_head() == config.IMAGE_STYLE_PROMPT.strip()


def test_tc_style_03_explicit_style_wins(monkeypatch):
    """用户显式指定的画风优先于项目默认。"""
    assert Image.build_style_head("  watercolor painting  ") == "watercolor painting"


def test_tc_style_04_empty_config_falls_back_to_builtin(monkeypatch):
    """config 被清空时仍要有画风可用（内置兜底常量）。"""
    monkeypatch.setattr(config, "IMAGE_STYLE_PROMPT", "   ")
    assert Image.build_style_head() == Image.ANIME_STYLE_HEAD
    assert "anime" in Image.build_style_head().lower()


def test_tc_style_05_config_is_overridable(monkeypatch):
    """改 config.IMAGE_STYLE_PROMPT（.env 的 IMAGE_STYLE_PROMPT）能整体换画风。"""
    monkeypatch.setattr(config, "IMAGE_STYLE_PROMPT", "ink wash painting")
    assert Image.build_style_head() == "ink wash painting"
    assert Image.build_portrait_prompt("a girl", "long hair").startswith("ink wash painting")


# --------------------------------------------------------------------------
# 两条出图路径必须共享同一个画风头
# --------------------------------------------------------------------------
def test_tc_style_06_portrait_and_expression_share_style_head():
    """立绘与情绪扩展图的画风前缀必须完全一致。

    这是本次缺陷的核心断言：两处各自手写画风时会静默跑偏，
    只有断言「共享同一个头」才能钉死。
    """
    portrait = Image.build_portrait_prompt("a girl", "long black hair")
    expression = Image.build_expression_prompt("happy", "she likes you")

    head = Image.build_style_head()
    assert portrait.startswith(head)
    assert expression.startswith(head)


def test_tc_style_07_empty_style_still_unifies(monkeypatch):
    """显式传空 style 时两条路径仍然同头（防止有人把默认值写死在一处）。"""
    monkeypatch.setattr(config, "IMAGE_STYLE_PROMPT", "")
    portrait = Image.build_portrait_prompt("a girl", "long hair", style="")
    expression = Image.build_expression_prompt("sad", "you hurt her", style="")
    assert portrait.startswith(Image.ANIME_STYLE_HEAD)
    assert expression.startswith(Image.ANIME_STYLE_HEAD)


# --------------------------------------------------------------------------
# 正面提示词里不得残留摄影 / 写实词汇
# --------------------------------------------------------------------------
def test_tc_style_08_portrait_prompt_has_no_photographic_words():
    positive = _positive_part(Image.build_portrait_prompt("a girl", "long black hair"))
    assert "anime" in positive
    for word in BANNED_IN_POSITIVE:
        assert word not in positive, f"立绘正面提示词混入禁用词：{word}"


def test_tc_style_09_expression_prompt_has_no_photographic_words():
    positive = _positive_part(Image.build_expression_prompt("angry", "you were rude"))
    assert "anime" in positive
    for word in BANNED_IN_POSITIVE:
        assert word not in positive, f"情绪图正面提示词混入禁用词：{word}"


# --------------------------------------------------------------------------
# emotional_bro 实际下发的 payload 也要带上统一画风
# --------------------------------------------------------------------------
class _FakeVisual:
    def __init__(self):
        self.forms = []

    def cv_process(self, form):
        self.forms.append(form)
        return {"data": {"image_urls": ["http://example.invalid/a.jpg"]}}


def test_tc_style_10_emotional_bro_payload_carries_style(monkeypatch):
    """图生图接口收到的 prompt 必须带统一画风头，且不含 SD 脚手架。"""
    fake = _FakeVisual()
    monkeypatch.setattr(Image, "_volc_service", lambda: fake)
    monkeypatch.setattr(Image, "save_image_from_url", lambda *a, **k: True)

    Image.emotional_bro(
        "http://example.invalid/ref.jpg",
        "Wendy",
        ["happy", "she likes you"],
        "happy",
        "byteedit_v2.0",
    )

    assert fake.forms, "未调用图生图接口"
    prompt = fake.forms[0]["prompt"]
    assert prompt.startswith(Image.build_style_head())
    assert "Positive Prompt" not in prompt
    assert "ultra-high resolution" not in prompt


def test_tc_style_11_emotional_bro_high_aes_keeps_negative(monkeypatch):
    """high_aes_ip_v20 分支仍要把负面词拼进 prompt（原有行为不能丢）。"""
    fake = _FakeVisual()
    monkeypatch.setattr(Image, "_volc_service", lambda: fake)
    monkeypatch.setattr(Image, "save_image_from_url", lambda *a, **k: True)

    Image.emotional_bro(
        "http://example.invalid/ref.jpg", "Wendy",
        ["sad", "you hurt her"], "sad", "high_aes_ip_v20",
    )
    prompt = fake.forms[0]["prompt"]
    assert prompt.startswith(Image.build_style_head())
    assert "Negative prompt" in prompt
    assert Image.EXPRESSION_NEGATIVE in prompt


# --------------------------------------------------------------------------
# 新角色流程复用同一画风
# --------------------------------------------------------------------------
def test_tc_style_12_create_role_prompt_reuses_portrait_builder():
    """新角色候选图的提示词 == Image.build_portrait_prompt 的结果。"""
    import Create_New_Role

    expected = Image.build_portrait_prompt("a girl", "long hair", expression="smiling")
    actual = Create_New_Role.build_image_prompt("a girl", "long hair", expression="smiling")
    assert actual == expected
    assert actual.startswith(Image.build_style_head())


def test_tc_style_13_create_role_default_style_is_anime():
    """扩写模板里的默认画风标签是二次元，且模板明确禁掉摄影词。"""
    import Create_New_Role

    assert "二次元" in Create_New_Role.DEFAULT_STYLE
    for template in (Create_New_Role._EXPAND_TEMPLATE, Create_New_Role._IMAGINE_TEMPLATE):
        assert "二次元" in template
        assert "studio lighting" in template  # 作为「禁止出现」的示例被列出
