"""从后端真实删除「林彻」角色，并在删除前后各打印一次落盘状态。

走的是 `Create_New_Role.delete_role()` 这条**真实代码路径**（与
POST /api/roles/delete 完全同一份实现），不是手工 rm。

用法（cwd 必须是 backend/）：
    cd backend
    PYTHONDONTWRITEBYTECODE=1 E:/Anaconda/envs/vue-fastapi/python.exe ../artifacts/delete_role_probe.py
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT / "backend")          # 强制 backend 为 cwd，相对路径才成立

import Create_New_Role  # noqa: E402

ROLE = "林彻"
ASSETS = ROOT / "frontend" / "src" / "assets"


def snapshot():
    rows = []
    for label, path in [
        ("pictures/<角色>/", ASSETS / "pictures" / ROLE),
        ("pictures/Role_Description/<角色>.txt",
         ASSETS / "pictures" / "Role_Description" / f"{ROLE}.txt"),
        ("roles/<角色>.txt", ASSETS / "roles" / f"{ROLE}.txt"),
        ("voice/<角色>/", ASSETS / "voice" / ROLE),
        ("voice/_mock/<角色>/", ASSETS / "voice" / "_mock" / ROLE),
    ]:
        if path.is_dir():
            rows.append((label, sorted(p.name for p in path.iterdir())))
        elif path.is_file():
            rows.append((label, f"{path.stat().st_size} bytes"))
        else:
            rows.append((label, "（不存在）"))

    temp_dir = ASSETS / "pictures" / "temp"
    rows.append((
        "pictures/temp/<角色>_*.jpg",
        sorted(p.name for p in temp_dir.glob(f"{ROLE}_*.jpg")) if temp_dir.is_dir() else [],
    ))

    records = ASSETS / "Records.txt"
    rows.append((
        "Records.txt 含该角色段",
        f"{ROLE}:" in records.read_text(encoding="utf-8") if records.is_file() else False,
    ))

    voices = ROOT / "backend" / "custom_role_voices.json"
    rows.append((
        "custom_role_voices.json",
        json.loads(voices.read_text(encoding="utf-8")) if voices.is_file() else {},
    ))
    return rows


def dump(title):
    print("=" * 72)
    print(title)
    for label, value in snapshot():
        print(f"  {label:38} {value}")


dump("删除前")
result = Create_New_Role.delete_role(ROLE)
print("=" * 72)
print("delete_role() 回执：")
print(json.dumps(result, ensure_ascii=False, indent=2))
dump("删除后")

print("=" * 72)
gone = all([
    not (ASSETS / "pictures" / ROLE).exists(),
    not (ASSETS / "pictures" / "Role_Description" / f"{ROLE}.txt").exists(),
    not (ASSETS / "roles" / f"{ROLE}.txt").exists(),
    not (ASSETS / "voice" / ROLE).exists(),
    not list((ASSETS / "pictures" / "temp").glob(f"{ROLE}_*.jpg")),
    f"{ROLE}:" not in (ASSETS / "Records.txt").read_text(encoding="utf-8"),
    ROLE not in json.loads(
        (ROOT / "backend" / "custom_role_voices.json").read_text(encoding="utf-8")),
])
print("残留检查（逐项确认已清空）:", "全部清空" if gone else "仍有残留")
print("VERDICT:", "PASS" if (gone and result["found"]) else "FAIL")
