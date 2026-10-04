# -*- coding: utf-8 -*-
"""Sync Desktop -> Z (chi file code, KHONG copy config.json) + doi chieu MD5."""
import os, shutil, hashlib
from pathlib import Path

SRC = Path(r"C:\Users\Admin\Desktop\News_Clip_Stitcher")
DST = Path(r"Z:\HQData-2\TOOLS TỔNG HỢP\TOOLS UPDATE CUỐI\News_Clip_Stitcher")

SKIP_DIRS = {"output", "__pycache__", "_backup_update", ".git", "models"}


def _skip(fn: str) -> bool:
    """Bo config + moi thu la ban sao luu cua no.

    Truoc day chi bo dung ten "config.json.bak" nen "config.json.bak_tts" (backup
    tam khi sua config) lot lên o Z. Bo theo TIEN TO cho het.
    """
    if fn == "config.json" or fn.startswith("config.json."):
        return True
    return fn.endswith((".log", ".bak", ".part", ".tmp"))

def md5(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()

copied = []
for root, dirs, files in os.walk(SRC):
    dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
    rel = Path(root).relative_to(SRC)
    for fn in files:
        if _skip(fn):
            continue
        s = Path(root) / fn
        d = DST / rel / fn
        d.parent.mkdir(parents=True, exist_ok=True)
        if not d.exists() or md5(s) != md5(d):
            shutil.copy2(s, d)
            copied.append(str(rel / fn))

print("Da copy %d file:" % len(copied))
for c in copied:
    print("  ", c)

# doi chieu MD5 toan bo
print("\n=== DOI CHIEU MD5 (bo qua config.json) ===")
ok = bad = 0
for root, dirs, files in os.walk(SRC):
    dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
    rel = Path(root).relative_to(SRC)
    for fn in files:
        if _skip(fn):
            continue
        s = Path(root) / fn
        d = DST / rel / fn
        if not d.exists():
            print("  THIEU:", rel / fn); bad += 1; continue
        if md5(s) == md5(d):
            ok += 1
        else:
            print("  LECH :", rel / fn); bad += 1
print("\n==== %d/%d MD5 KHOP ====" % (ok, ok + bad))
