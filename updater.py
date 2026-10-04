# -*- coding: utf-8 -*-
"""Cập nhật News Clip Stitcher từ GitHub.

Cách dùng:
    python updater.py            # chỉ kiểm tra, in ra bản mới nếu có
    python updater.py --apply    # kiểm tra rồi cập nhật luôn

Cơ chế: đọc version.json trên repo (raw.githubusercontent), so với APP_VERSION
trong main.py. Nếu repo mới hơn -> tải zip của nhánh main -> ghi đè mã nguồn.

AN TOÀN: KHÔNG bao giờ ghi đè
    - config.json   (cài đặt + key của người dùng)
    - output/       (video đã render)
    - models/       (model AI tải về)
    - __pycache__/  (rác)
Trước khi ghi đè, tự sao lưu toàn bộ file sắp thay vào _backup_update/.
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

REPO = "NaupUuh/News_Clip_Stitcher"
BRANCH = "main"
BASE = Path(__file__).resolve().parent

# Đọc version.json qua API (KHÔNG bị CDN cache như raw.githubusercontent) —
# raw.githubusercontent giữ cache ~5 phút nên máy khác bấm ngay sau khi push
# sẽ thấy bản CŨ. API trả dữ liệu tươi; raw chỉ dùng làm phương án dự phòng.
VERSION_API = (f"https://api.github.com/repos/{REPO}/contents/version.json"
               f"?ref={BRANCH}")
VERSION_URL = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/version.json"
ZIP_URL = f"https://github.com/{REPO}/archive/refs/heads/{BRANCH}.zip"
COMMITS_URL = (f"https://api.github.com/repos/{REPO}/commits?"
               f"sha={BRANCH}&per_page=20")

# Không bao giờ ghi đè / không copy từ repo về
KEEP_NAMES = {"config.json", "config.json.bak"}
KEEP_DIRS = {"output", "__pycache__", "_backup_update", "models",
             ".git", "Test_19A2V", "Test_JPE"}
KEEP_SUFFIX = {".log", ".bak"}

TIMEOUT = 25


# ---------------------------------------------------------------- tiện ích

def read_local_version() -> str:
    """Đọc APP_VERSION trong main.py (không import để tránh mở GUI)."""
    f = BASE / "main.py"
    try:
        m = re.search(r'^APP_VERSION\s*=\s*["\']([^"\']+)["\']',
                      f.read_text(encoding="utf-8", errors="replace"),
                      re.MULTILINE)
        return m.group(1) if m else "0.0.0"
    except Exception:
        return "0.0.0"


def _vtuple(v: str) -> tuple:
    """'1.18.0' -> (1, 18, 0). Chịu được hậu tố như '1.18.0-beta'."""
    parts = re.findall(r"\d+", str(v or ""))
    return tuple(int(x) for x in parts[:4]) or (0,)


def is_newer(remote: str, local: str) -> bool:
    return _vtuple(remote) > _vtuple(local)


def _get(url: str, timeout: int = TIMEOUT) -> bytes:
    req = urllib.request.Request(
        url, headers={"User-Agent": "NewsClipStitcher-Updater",
                      "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _read_version_json() -> dict:
    """Đọc version.json từ repo. Ưu tiên API (tươi), lỗi thì dùng raw.

    Trả dict; ném Exception kèm lý do nếu cả hai đường đều hỏng.
    """
    last = None
    # 1) API contents -> trả base64 trong JSON
    try:
        j = json.loads(_get(VERSION_API).decode("utf-8", "replace"))
        import base64
        raw = base64.b64decode(j.get("content", "")).decode("utf-8", "replace")
        return json.loads(raw)
    except urllib.error.HTTPError as e:
        last = e
        if e.code == 404:
            raise
    except Exception as e:
        last = e
    # 2) raw.githubusercontent (có thể bị cache tới ~5 phút)
    try:
        return json.loads(_get(VERSION_URL).decode("utf-8", "replace"))
    except Exception:
        raise last if last is not None else RuntimeError("không đọc được version.json")


# ---------------------------------------------------------------- kiểm tra

def check_update(use_api: bool = True) -> dict:
    """Trả về dict mô tả bản cập nhật.

    {"ok": True,  "has_update": bool, "local":.., "remote":.., "notes":..,
     "zip":.., "commits": [str, ...]}
    {"ok": False, "error": "<lý do>"}
    """
    local = read_local_version()
    out = {"ok": True, "has_update": False, "local": local,
           "remote": local, "notes": "", "zip": ZIP_URL, "commits": []}

    # 1) version.json trên repo
    try:
        data = _read_version_json()
        out["remote"] = str(data.get("version") or "").strip()
        out["notes"] = str(data.get("notes") or "").strip()
        out["zip"] = str(data.get("zip") or "").strip() or ZIP_URL
    except urllib.error.HTTPError as e:
        if e.code == 404:
            out.update(ok=False,
                       error="Repo chưa có version.json (hoặc chưa tạo repo).")
            return out
        out.update(ok=False, error=f"HTTP {e.code} khi đọc version.json")
        return out
    except Exception as e:
        out.update(ok=False, error=f"Không kết nối được GitHub: {e}")
        return out

    if not out["remote"]:
        out.update(ok=False, error="version.json thiếu trường 'version'.")
        return out

    out["has_update"] = is_newer(out["remote"], local)

    # 2) danh sách commit (tuỳ chọn — lỗi thì bỏ qua, không chặn cập nhật)
    if use_api and out["has_update"]:
        try:
            cs = json.loads(_get(COMMITS_URL).decode("utf-8", "replace"))
            out["commits"] = [
                (c.get("commit", {}).get("message", "") or "").split("\n")[0]
                for c in cs[:8] if isinstance(c, dict)
            ]
        except Exception:
            pass
    return out


# ---------------------------------------------------------------- cập nhật

def _target_ok(rel: Path) -> bool:
    """True nếu được phép ghi file này (rel = đường dẫn tương đối)."""
    parts = rel.parts
    if not parts:
        return False
    if parts[0] in KEEP_DIRS or parts[0] in KEEP_NAMES:
        return False
    if any(p in KEEP_DIRS for p in parts[:-1]):
        return False
    if rel.name in KEEP_NAMES:
        return False
    if rel.suffix.lower() in KEEP_SUFFIX:
        return False
    return True


def apply_update(zip_url: str = "", log=print) -> dict:
    """Tải zip nhánh main và ghi đè mã nguồn. Trả {"ok":bool, ...}."""
    url = zip_url or ZIP_URL
    log(f"Đang tải {url} ...")
    try:
        blob = _get(url, timeout=120)
    except Exception as e:
        return {"ok": False, "error": f"Tải thất bại: {e}"}
    log(f"Đã tải {len(blob) / 1024:.0f} KB. Đang giải nén...")

    try:
        zf = zipfile.ZipFile(io.BytesIO(blob))
    except Exception as e:
        return {"ok": False, "error": f"File zip hỏng: {e}"}

    names = zf.namelist()
    if not names:
        return {"ok": False, "error": "Zip rỗng."}

    # zip của GitHub bọc trong 1 thư mục gốc: <repo>-<branch>/
    root = names[0].split("/")[0] + "/"
    backup_dir = BASE / "_backup_update" / time.strftime("%Y%m%d_%H%M%S")
    written, skipped, failed = [], [], []

    for info in zf.infolist():
        if info.is_dir():
            continue
        rel = Path(info.filename[len(root):]) if info.filename.startswith(root) \
            else Path(info.filename)
        if not _target_ok(rel):
            skipped.append(str(rel))
            continue
        dst = BASE / rel
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            # sao lưu bản cũ trước khi ghi đè
            if dst.is_file():
                b = backup_dir / rel
                b.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dst, b)
            dst.write_bytes(zf.read(info))
            written.append(str(rel))
        except Exception as e:
            failed.append(f"{rel}: {e}")

    log(f"Ghi đè {len(written)} file, giữ nguyên {len(skipped)} file.")
    if failed:
        for f in failed[:5]:
            log(f"  LỖI {f}")
        return {"ok": False, "error": f"{len(failed)} file lỗi",
                "written": written, "failed": failed,
                "backup": str(backup_dir)}

    # xoá cache .pyc để Python dùng code mới
    for pc in (BASE / "__pycache__", BASE / "core" / "__pycache__"):
        if pc.is_dir():
            shutil.rmtree(pc, ignore_errors=True)

    new_v = read_local_version()
    return {"ok": True, "written": written, "skipped": skipped,
            "version": new_v, "backup": str(backup_dir)}


def rollback(backup_path: str, log=print) -> dict:
    """Khôi phục từ thư mục _backup_update/<timestamp>."""
    src = Path(backup_path)
    if not src.is_dir():
        return {"ok": False, "error": f"Không thấy {src}"}
    n = 0
    for f in src.rglob("*"):
        if f.is_file():
            rel = f.relative_to(src)
            dst = BASE / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dst)
            n += 1
    log(f"Đã khôi phục {n} file từ {src}")
    return {"ok": True, "restored": n}


# ---------------------------------------------------------------- CLI

def main() -> int:
    apply_it = "--apply" in sys.argv or "-y" in sys.argv
    local = read_local_version()
    print(f"Bản đang dùng : v{local}")

    r = check_update()
    if not r["ok"]:
        print(f"LỖI: {r['error']}")
        return 1

    print(f"Bản trên GitHub: v{r['remote']}")
    if not r["has_update"]:
        print("Bạn đang dùng bản mới nhất.")
        return 0

    print(f"\n>>> CÓ BẢN MỚI v{r['remote']}")
    if r["notes"]:
        print(f"    {r['notes']}")
    for c in r["commits"]:
        print(f"    - {c}")

    if not apply_it:
        print("\nThêm --apply để cập nhật.")
        return 0

    res = apply_update(r["zip"], log=print)
    if not res["ok"]:
        print(f"\nCẬP NHẬT THẤT BẠI: {res['error']}")
        return 1
    print(f"\nĐÃ CẬP NHẬT lên v{res['version']}. Mở lại tool để dùng.")
    print(f"(Bản cũ sao lưu ở {res['backup']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
