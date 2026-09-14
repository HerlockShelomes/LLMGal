"""角色清点用例（TC-LIST-*）。

背景（真实缺陷）：前端 localStorage 里的自定义角色只是缓存，磁盘才是真相源。
删除中途被刷新打断时 `purgeRole` 没机会执行，缓存里便留下一个磁盘上早已不存在的
角色 —— 用户看到的是「明明删了，下拉框里还在，再点删除又像是没反应」。

因此后端必须能给出权威名单（`Create_New_Role.list_custom_roles()` +
`GET /api/roles/list`），前端才能对账。

本文件的闸门是**对称性**：清点认得的产物，必须与 `delete_role` 会清掉的产物
一一对应。两边范围一旦漂移，就会出现「删了但清单里还在」或
「清单说还在、其实文件早没了」两种假象 —— 而且两种都不报错，只会静默骗人。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.responses import JSONResponse

import config
import Connect
import Create_New_Role


BUILTIN = config.BUILTIN_ROLES[0]      # 仓库自带角色，不该出现在清单里
FULL = "林亦"                          # 产物齐全的角色
OTHER = "Another"                      # 只在 voice/<角色>/ 留下痕迹
VOICE_ONLY = "VoiceOnly"               # 只在 custom_role_voices.json 留下痕迹

# assets 下与角色无关、但躺在被扫描目录里的内部目录名
INTERNAL_DIRS = ("Role_Description", "temp", "_samples", "_mock")


def _make_skeleton(assets: Path) -> None:
    for sub in ("roles", "pictures/Role_Description", "pictures/temp", "voice", "voice/_samples"):
        (assets / sub).mkdir(parents=True, exist_ok=True)


@pytest.fixture
def role_workspace(monkeypatch, tmp_path):
    """搭一份 assets 目录骨架，按「每类产物各一个角色」铺开，用于真值表。"""
    backend_dir = tmp_path / "backend"
    assets = tmp_path / "frontend" / "src" / "assets"
    backend_dir.mkdir()
    _make_skeleton(assets)

    # 产物齐全的角色
    (assets / "pictures" / FULL).mkdir()
    (assets / "pictures" / FULL / f"{FULL}_neutral.jpg").write_bytes(b"JPG")
    (assets / "roles" / f"{FULL}.txt").write_text(f"角色名称：{FULL}", encoding="utf-8")
    (assets / "pictures" / "Role_Description" / f"{FULL}.txt").write_text("Subject", encoding="utf-8")
    (assets / "pictures" / "temp" / f"{FULL}_0.jpg").write_bytes(b"JPG")
    (assets / "voice" / FULL).mkdir()
    (assets / "voice" / FULL / f"{FULL}_0_Stream.wav").write_bytes(b"WAV")

    # 唯一痕迹是 voice/<角色>/
    (assets / "voice" / OTHER).mkdir()
    (assets / "voice" / OTHER / f"{OTHER}_0_Stream.wav").write_bytes(b"WAV")

    # 内置角色的哨兵：清点必须把它排除
    (assets / "pictures" / BUILTIN).mkdir()
    (assets / "pictures" / BUILTIN / f"{BUILTIN}_neutral.jpg").write_bytes(b"JPG")

    voices = tmp_path / "custom_role_voices.json"
    voices.write_text(
        json.dumps({FULL: "Mia", VOICE_ONLY: "Kai"}, ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setattr(config, "CUSTOM_ROLE_VOICES_PATH", str(voices))
    monkeypatch.setattr(config, "_custom_role_voices_cache", {"mtime": -1.0, "data": {}})
    monkeypatch.setattr(Create_New_Role, "ROLE_CREATION_STATUS", {})
    monkeypatch.chdir(backend_dir)
    return assets, voices


@pytest.fixture
def bare_workspace(monkeypatch, tmp_path):
    """只有目录骨架、没有任何角色产物的工作区；每次调用前可反复清空重建。"""
    backend_dir = tmp_path / "backend"
    assets = tmp_path / "frontend" / "src" / "assets"
    backend_dir.mkdir()
    _make_skeleton(assets)

    empty_voices = tmp_path / "empty_voices.json"
    empty_voices.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(config, "CUSTOM_ROLE_VOICES_PATH", str(empty_voices))
    monkeypatch.setattr(config, "_custom_role_voices_cache", {"mtime": -1.0, "data": {}})
    monkeypatch.chdir(backend_dir)

    def reset() -> None:
        # 只重建「承载角色产物」的目录，内部目录（_samples 等）留着但清空内容
        shutil.rmtree(assets / "pictures", ignore_errors=True)
        shutil.rmtree(assets / "voice", ignore_errors=True)
        shutil.rmtree(assets / "roles", ignore_errors=True)
        _make_skeleton(assets)

    return assets, reset


# ---------------------------------------------------------------------------
# 清单内容
# ---------------------------------------------------------------------------
def test_tc_list_01_finds_full_role(role_workspace):
    """TC-LIST-01：产物齐全的角色出现在清单里。"""
    assert FULL in Create_New_Role.list_custom_roles()


def test_tc_list_02_any_trace_is_enough(role_workspace):
    """TC-LIST-02：只剩部分产物（甚至只剩音色登记）也要认得出来。

    删除失败或中途被打断时，文件往往只剩一半；只看音色登记会漏掉这些半残留。
    """
    roles = Create_New_Role.list_custom_roles()
    assert FULL in roles          # 六类探针齐全
    assert OTHER in roles         # 只靠 voice/<角色>/ 认出
    assert VOICE_ONLY in roles    # 只靠 custom_role_voices.json 认出


def test_tc_list_03_probe_matrix(bare_workspace):
    """TC-LIST-03：逐类产物单独放一个角色，每一类都必须能被单独认出来。

    这是「探针覆盖齐全」的直接证据 —— 少一类，那一类残留就成了查不到的幽灵。
    """
    assets, reset = bare_workspace

    scenarios = {
        "OnlyRolesTxt": lambda: (assets / "roles" / "OnlyRolesTxt.txt").write_text("x", encoding="utf-8"),
        "OnlyDescTxt": lambda: (assets / "pictures" / "Role_Description" / "OnlyDescTxt.txt").write_text("x", encoding="utf-8"),
        "OnlyPictureDir": lambda: (assets / "pictures" / "OnlyPictureDir").mkdir(),
        "OnlyTempImage": lambda: (assets / "pictures" / "temp" / "OnlyTempImage_0.jpg").write_bytes(b"JPG"),
        "OnlyVoiceDir": lambda: (assets / "voice" / "OnlyVoiceDir").mkdir(),
        "OnlyMockVoiceDir": lambda: (assets / "voice" / "_mock" / "OnlyMockVoiceDir").mkdir(parents=True),
    }

    for expected, build in scenarios.items():
        reset()
        build()
        got = Create_New_Role.list_custom_roles()
        assert expected in got, f"探针漏了「{expected}」这一路：{got}"


def test_tc_list_04_builtin_excluded(role_workspace):
    """TC-LIST-04：内置角色不进清单。

    前端拿这份名单判断「能不能删」，混进内置角色就会给出一个必然 403 的删除入口。
    """
    assert BUILTIN not in Create_New_Role.list_custom_roles()


def test_tc_list_05_internal_dirs_excluded(role_workspace):
    """TC-LIST-05：内部目录不能被当成角色名。

    `pictures/Role_Description`、`pictures/temp`、`voice/_samples`、`voice/_mock`
    都躺在被扫描的目录里，必须显式排除。
    """
    roles = Create_New_Role.list_custom_roles()
    for internal in INTERNAL_DIRS:
        assert internal not in roles


def test_tc_list_06_missing_dirs_is_empty_not_crash(monkeypatch, tmp_path):
    """TC-LIST-06：assets 目录整片不存在时返回空表，不抛异常（首次启动的常态）。"""
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    monkeypatch.setattr(config, "CUSTOM_ROLE_VOICES_PATH", str(tmp_path / "nope.json"))
    monkeypatch.chdir(backend_dir)

    assert Create_New_Role.list_custom_roles() == []


def test_tc_list_07_broken_voices_json_still_lists_files(role_workspace, monkeypatch, tmp_path):
    """TC-LIST-07：音色登记文件坏掉（非法 JSON）时不让整个清点失败。

    六路探针互相独立：一路读不出来，其余五路仍要照常工作。
    """
    broken = tmp_path / "broken.json"
    broken.write_text("{ this is not json", encoding="utf-8")
    monkeypatch.setattr(config, "CUSTOM_ROLE_VOICES_PATH", str(broken))

    roles = Create_New_Role.list_custom_roles()
    assert FULL in roles      # 由文件探针认出，不依赖音色登记
    assert OTHER in roles


# ---------------------------------------------------------------------------
# 对称性：清点范围 == 删除范围
# ---------------------------------------------------------------------------
def test_tc_list_08_removed_role_disappears(role_workspace):
    """TC-LIST-08：删除后该角色必须从清单里消失（对称性闸门）。

    整组用例里最关键的一条：只要 delete_role 清掉的东西多于 list_custom_roles
    认得的，就会留下「清单里还有、其实已经删了」的幽灵角色。
    """
    assert FULL in Create_New_Role.list_custom_roles()

    Create_New_Role.delete_role(FULL)

    assert FULL not in Create_New_Role.list_custom_roles()


def test_tc_list_09_delete_does_not_affect_others(role_workspace):
    """TC-LIST-09：删一个角色不影响清单里别的角色。"""
    Create_New_Role.delete_role(FULL)

    roles = Create_New_Role.list_custom_roles()
    assert OTHER in roles
    assert VOICE_ONLY in roles


# ---------------------------------------------------------------------------
# REST 接口
# ---------------------------------------------------------------------------
def test_tc_list_10_endpoint_shape(role_workspace):
    """TC-LIST-10：GET /api/roles/list 返回 {"roles": [...]}，与函数结果一致。"""
    resp = Connect.api_list_roles()

    assert not isinstance(resp, JSONResponse)
    assert resp["roles"] == Create_New_Role.list_custom_roles()
    assert isinstance(resp["roles"], list)


def test_tc_list_11_endpoint_502_on_failure(monkeypatch):
    """TC-LIST-11：清点内部出错时返回 502，而不是把异常抛给客户端。"""
    def boom():
        raise OSError("模拟磁盘不可读")

    monkeypatch.setattr(Create_New_Role, "list_custom_roles", boom)

    resp = Connect.api_list_roles()
    assert isinstance(resp, JSONResponse)
    assert resp.status_code == 502
