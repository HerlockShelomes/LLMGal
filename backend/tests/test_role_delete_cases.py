"""删除角色用例（TC-DEL-*）。

需求：删除角色要清掉**全部**相关记录 —— 角色信息、形象 / 情绪图片、语音、
Records.txt 里的轮转段、后端音色登记、创建进度缓存。

三条硬约束（本文件就是它们的闸门）：
  · 内置角色不可删（后端 403）；角色名必须挡得住路径穿越；
  · 删一个角色不能碰到别的角色的任何东西（尤其是 Records.txt 的其它段落）；
  · 正在创建中的角色不能删 —— 后台定稿线程会把文件重新写回来。

所有用例都在 tmp 工作区里跑，`custom_role_voices.json` 会指向临时文件，
绝不会碰到仓库里的真实登记。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.responses import JSONResponse

import config
import Connect
import Create_New_Role


ROLE = "林彻"          # 用中文名，顺带覆盖编码路径
OTHER = "Testificate"


def _force_mode(monkeypatch, tmp_path, mode: str) -> None:
    """真实写一份开关文件并把 MODE_PATH 指过去（不 monkeypatch get_mode，避免测替身）。"""
    path = tmp_path / "runtime_mode.json"
    path.write_text(json.dumps({"mode": mode}), encoding="utf-8")
    monkeypatch.setattr(config, "MODE_PATH", str(path))


@pytest.fixture
def role_workspace(monkeypatch, tmp_path):
    """搭一份「林彻」的全部落盘产物 + 一个内置角色的哨兵文件。"""
    backend_dir = tmp_path / "backend"
    assets = tmp_path / "frontend" / "src" / "assets"
    backend_dir.mkdir()
    (assets / "roles").mkdir(parents=True)
    (assets / "pictures" / ROLE).mkdir(parents=True)
    (assets / "pictures" / "Role_Description").mkdir(parents=True)
    (assets / "pictures" / "temp").mkdir(parents=True)
    (assets / "voice" / ROLE).mkdir(parents=True)
    (assets / "voice" / "_mock" / ROLE).mkdir(parents=True)

    # 角色自身的产物（每一项都覆盖一个删除分支）
    (assets / "roles" / f"{ROLE}.txt").write_text(
        f"角色名称：{ROLE}\n温柔沉稳\n", encoding="utf-8"
    )
    (assets / "pictures" / "Role_Description" / f"{ROLE}.txt").write_text(
        "Subject Description: a young man\nAppearance Details: black hair",
        encoding="utf-8",
    )
    for name in ("original", "neutral", "happy", "sad"):
        (assets / "pictures" / ROLE / f"{ROLE}_{name}.jpg").write_bytes(b"JPG")
    (assets / "pictures" / "temp" / f"{ROLE}_0.jpg").write_bytes(b"JPG")
    (assets / "pictures" / "temp" / f"{ROLE}_1.jpg").write_bytes(b"JPG")
    (assets / "voice" / ROLE / f"{ROLE}_test_Stream.wav").write_bytes(b"WAV")
    (assets / "voice" / "_mock" / ROLE / f"{ROLE}_0_Stream.wav").write_bytes(b"WAV")

    # 另一个角色的哨兵：删除过程中一个字节都不该被动
    (assets / "pictures" / OTHER).mkdir()
    (assets / "pictures" / OTHER / f"{OTHER}_neutral.jpg").write_bytes(b"KEEP")

    records = assets / "Records.txt"
    records.write_text(
        "Wendy:\nRecent_Url:\nindex:7\n\n"
        f"{ROLE}:\nRecent_Url:http://example.invalid/a.jpg\nindex:3\n\n"
        f"{OTHER}:\nRecent_Url:testificate_boy\nindex:0\n",
        encoding="utf-8",
    )

    voices = tmp_path / "custom_role_voices.json"
    voices.write_text(
        json.dumps({ROLE: "Mia", "Another": "Kai"}, ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setattr(config, "CUSTOM_ROLE_VOICES_PATH", str(voices))
    monkeypatch.setattr(config, "_custom_role_voices_cache", {"mtime": -1.0, "data": {}})
    # 创建进度是模块级全局，逐用例隔离
    monkeypatch.setattr(Create_New_Role, "ROLE_CREATION_STATUS", {})
    monkeypatch.chdir(backend_dir)
    return assets, records, voices


# ---------------------------------------------------------------------------
# 删除范围
# ---------------------------------------------------------------------------
def test_tc_del_01_removes_every_artifact(role_workspace):
    """TC-DEL-01：角色的每一类落盘产物都被清掉，且不碰其它角色。"""
    assets, _records, _voices = role_workspace

    result = Create_New_Role.delete_role(ROLE)

    assert result["status"] == "deleted"
    assert result["found"] is True
    assert not (assets / "pictures" / ROLE).exists()
    assert not (assets / "pictures" / "Role_Description" / f"{ROLE}.txt").exists()
    assert not (assets / "roles" / f"{ROLE}.txt").exists()
    assert not (assets / "voice" / ROLE).exists()
    assert not (assets / "voice" / "_mock" / ROLE).exists()
    assert list((assets / "pictures" / "temp").glob(f"{ROLE}_*.jpg")) == []
    # 哨兵：别的角色的图片完好
    assert (assets / "pictures" / OTHER / f"{OTHER}_neutral.jpg").read_bytes() == b"KEEP"


def test_tc_del_02_records_entry_removed_others_intact(role_workspace):
    """TC-DEL-02：Records.txt 整段摘除，其它角色段落与前后的空行都不受影响。"""
    _assets, records, _voices = role_workspace

    Create_New_Role.delete_role(ROLE)

    text = records.read_text(encoding="utf-8")
    assert f"{ROLE}:" not in text
    assert "Wendy:\nRecent_Url:\nindex:7" in text
    assert f"{OTHER}:\nRecent_Url:testificate_boy\nindex:0" in text
    assert "\n\n\n" not in text          # 不留连续空行


def test_tc_del_03_voice_mapping_removed_and_cache_invalidated(role_workspace):
    """TC-DEL-03：音色登记被摘掉，且 config 的 mtime 缓存同步失效。"""
    _assets, _records, voices = role_workspace
    assert config.resolve_role_voice(ROLE, "fallback") == "Mia"

    Create_New_Role.delete_role(ROLE)

    data = json.loads(voices.read_text(encoding="utf-8"))
    assert ROLE not in data
    assert data.get("Another") == "Kai"
    assert config.resolve_role_voice(ROLE, "fallback") == "fallback"


def test_tc_del_04_status_cache_cleared(role_workspace):
    """TC-DEL-04：创建进度缓存也要清，否则删除后仍能查到该角色的状态。"""
    Create_New_Role._set_status(ROLE, "ready", step="完成")

    Create_New_Role.delete_role(ROLE)

    assert Create_New_Role.get_status(ROLE)["status"] == "unknown"


# ---------------------------------------------------------------------------
# 拒绝删除的情形
# ---------------------------------------------------------------------------
def test_tc_del_05_builtin_role_refused(role_workspace):
    """TC-DEL-05：内置角色拒绝删除，且没有产生任何副作用。"""
    _assets, records, _voices = role_workspace
    before = records.read_text(encoding="utf-8")

    with pytest.raises(PermissionError):
        Create_New_Role.delete_role("Wendy")

    assert records.read_text(encoding="utf-8") == before
    assert config.BUILTIN_ROLES, "内置角色表不能为空"


@pytest.mark.parametrize(
    "bad",
    ["", "   ", "..", "../Wendy", "a/b", "a\\b", "C:evil", "_samples", "_mock"],
)
def test_tc_del_06_unsafe_names_rejected(role_workspace, bad):
    """TC-DEL-06：空名 / 路径穿越 / 与内部目录撞名，一律拒收且不误删。"""
    assets = role_workspace[0]

    with pytest.raises(ValueError):
        Create_New_Role.delete_role(bad)

    assert (assets / "roles" / f"{ROLE}.txt").exists()


def test_tc_del_07_busy_role_refused(role_workspace):
    """TC-DEL-07：正在创建中的角色不能删 —— 后台线程会把文件写回来。"""
    assets = role_workspace[0]
    Create_New_Role._set_status(ROLE, "creating", step="生成情绪图片")

    with pytest.raises(Create_New_Role.RoleBusyError):
        Create_New_Role.delete_role(ROLE)

    assert (assets / "roles" / f"{ROLE}.txt").exists()


def test_tc_del_08_unknown_role_is_not_an_error(role_workspace):
    """TC-DEL-08：查无此角色不报错（前端还要清自己的 localStorage，不能卡在这一步）。"""
    result = Create_New_Role.delete_role("Nobody")

    assert result["status"] == "deleted"
    assert result["found"] is False
    assert result["removed"] == []
    assert any("Nobody" in item for item in result["missing"])


def test_tc_del_09_second_delete_idempotent(role_workspace):
    """TC-DEL-09：重复删除幂等，第二次 found=False 但不抛异常。"""
    Create_New_Role.delete_role(ROLE)

    again = Create_New_Role.delete_role(ROLE)

    assert again["status"] == "deleted"
    assert again["found"] is False


# ---------------------------------------------------------------------------
# REST 层
# ---------------------------------------------------------------------------
def test_tc_del_10_rest_status_codes(role_workspace):
    """TC-DEL-10：400 非法名 / 403 内置角色 / 409 创建中 / 200 正常删除。"""
    assert Connect.api_delete_role(Connect.DeleteRoleRequest(roleName="")).status_code == 400
    assert Connect.api_delete_role(Connect.DeleteRoleRequest(roleName="Wendy")).status_code == 403
    assert Connect.api_delete_role(Connect.DeleteRoleRequest(roleName="../x")).status_code == 400

    Create_New_Role._set_status(ROLE, "creating")
    busy = Connect.api_delete_role(Connect.DeleteRoleRequest(roleName=ROLE))
    assert isinstance(busy, JSONResponse) and busy.status_code == 409

    Create_New_Role._set_status(ROLE, "ready")
    ok = Connect.api_delete_role(Connect.DeleteRoleRequest(roleName=ROLE))
    assert isinstance(ok, dict)
    assert ok["status"] == "deleted" and ok["found"] is True


def test_tc_del_11_delete_is_not_blocked_in_mock_mode(role_workspace, monkeypatch, tmp_path):
    """TC-DEL-11：删除是纯本地文件操作，mock 版（AI 旁路）下同样可用。"""
    _force_mode(monkeypatch, tmp_path, config.MODE_MOCK)
    assert config.is_mock()

    result = Connect.api_delete_role(Connect.DeleteRoleRequest(roleName=ROLE))

    assert isinstance(result, dict)
    assert result["status"] == "deleted"
    assert result["found"] is True


def test_tc_del_12_relative_paths_stay_inside_workspace(role_workspace):
    """TC-DEL-12：删除范围全部落在 assets 下（回执里的 removed 不该出现绝对路径）。"""
    result = Create_New_Role.delete_role(ROLE)

    assert result["removed"]
    for item in result["removed"]:
        assert not Path(item.split(":")[0].strip()).is_absolute(), item
