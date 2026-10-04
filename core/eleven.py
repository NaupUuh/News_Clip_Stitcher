"""ElevenLabs TTS — tạo giọng đọc cho video tin tức.

Key đọc theo thứ tự:
  1) biến môi trường ELEVENLABS_API_KEY
  2) C:\\Users\\Admin\\AppData\\Local\\hermes\\.env

DANH SÁCH GIỌNG đã được TEST THẬT bằng key hiện có (xem cột tier):
  - "free" : chạy được ngay cả khi tài khoản ở gói free
  - "paid" : giọng thư viện, API trả 402 paid_plan_required với gói free

Muốn dùng nhóm "paid" (Rachel, Clyde...) thì cần nâng tài khoản ElevenLabs.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from urllib import error, request

HERMES_ENV = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "hermes" / ".env"
API_BASE = "https://api.elevenlabs.io"

# ── giọng đọc — ghi rõ GIỐNG KIỂU NHÀ ĐÀI NÀO ─────────────────────────
# LƯU Ý THẬT: ElevenLabs KHÔNG có giọng mang tên CNN/Fox/BBC. Cột "kieu"
# là nhãn MÔ TẢ CHẤT GIỌNG gần với phong cách nhà đài đó nhất, để dễ chọn
# — không phải bản sao giọng MC thật của đài.
#
# (tên, giới tính, voice_id, kiểu nhà đài, mô tả chất giọng, tier)
VOICES = [
    # ★★ NAM — MC tin tức
    ("Brian",   "nam", "nPczCjzI2devNBz1zQrb", "CNN / NBC Nightly",
     "★ Trầm, dày, đọc tin chậm rãi — kiểu MC bản tin tối Mỹ", "free"),
    ("Daniel",  "nam", "onwK4e9ZLuTAKqWW03F9", "BBC News",
     "★ Giọng Anh chuẩn, trang trọng — kiểu newsreader BBC", "free"),
    ("Adam",    "nam", "pNInz6obpgDQGcFmaJgB", "NBC / CBS Evening",
     "★ Trầm ấm, chắc — kiểu dẫn bản tin tối", "free"),
    ("George",  "nam", "JBFqnCBsd6RMkjVDRZzb", "BBC Radio 4",
     "Ấm, điềm đạm, giọng Anh — kiểu radio nhà đài", "free"),
    ("Callum",  "nam", "N2lVS1w4EtoT3dr4eOWO", "Fox News",
     "Căng, gắt, nhấn mạnh — kiểu bản tin giờ vàng Fox", "free"),
    ("Liam",    "nam", "TX3LPaxmHKxFdv7VOQHJ", "Sky News",
     "Rõ chữ, dứt khoát, tiết tấu nhanh — kiểu tin liên tục", "free"),
    ("Arnold",  "nam", "VR6AewLTigWG4xSOukaG", "Bloomberg TV",
     "Crisp, dứt khoát — kiểu MC bản tin tài chính", "free"),
    ("Charlie", "nam", "IKne3meq5aSn9XLyUdCD", "CNN Digital",
     "Tự nhiên, đời thường — kiểu dẫn tin online", "free"),
    ("Antoni",  "nam", "ErXwobaYiN019PkySvjV", "MSNBC",
     "Tròn trịa, cân bằng — kiểu dẫn tin chính luận", "free"),
    ("Eric",    "nam", "cjVigY5qzO86Huf0OWal", "CNBC",
     "Mượt, lịch sự — kiểu MC tin kinh tế", "free"),
    ("Chris",   "nam", "iP95p4xoKVk53GoZ742B", "ABC News",
     "Tự nhiên, thân mật — kiểu dẫn tin sáng", "free"),
    ("Roger",   "nam", "CwhRBWXzGAHq8TQ4Fs17", "NPR",
     "Thoải mái, kể chuyện — kiểu radio công cộng", "free"),
    ("Will",    "nam", "bIHbv24MWmeRgasZH58o", "Al Jazeera English",
     "Thân thiện, trung tính — kiểu tin quốc tế", "free"),
    # ★★ NỮ — MC / phóng viên
    ("Sarah",   "nu",  "EXAVITQu4vr4xnSDxMaL", "CNN / PBS NewsHour",
     "★ Chín chắn, điềm — kiểu MC nữ bản tin tối", "free"),
    ("Matilda", "nu",  "XrExE9yKIg1WjnnlVkGX", "NBC News",
     "★ Ấm, dễ nghe — kiểu MC nữ bản tin sáng", "free"),
    ("Alice",   "nu",  "Xb7hH8MSUJpSbSDYk0k2", "BBC World",
     "Tự tin, rõ ràng, giọng Anh — kiểu dẫn tin thế giới", "free"),
    ("Lily",    "nu",  "pFZP5JQG7iQjIQuC4Bku", "Sky News UK",
     "Giọng Anh, gọn — kiểu phóng viên bản tin UK", "free"),
    ("Laura",   "nu",  "FGY2WhTYpPnrIDTdsKH5", "ABC Good Morning",
     "Tươi, nhanh — kiểu MC bản tin sáng", "free"),
    ("River",   "nu",  "SAz9YHcvj6GT2YYXdXww", "Reuters TV",
     "Trung tính, điềm — kiểu đọc tin khách quan", "free"),
    ("Jessica", "nu",  "cgSgspJ2msm6clMCkdW9", "E! News",
     "Tươi tắn — kiểu MC tin giải trí", "free"),
    # ── GIỌNG THƯ VIỆN — CẦN GÓI TRẢ PHÍ ─────────────────────────────
    ("Rachel",  "nu",  "21m00Tcm4TlvDq8ikWAM", "NPR / documentary",
     "★★ Nữ kinh điển, điềm nhất — kiểu đọc tin/narration", "paid"),
    ("Clyde",   "nam", "2EiwWnXFnvU5JabPnv8n", "Fox News / trailer",
     "★★ Trầm gắt, kịch tính — kiểu giật tít, hype tin nóng", "paid"),
    ("Josh",    "nam", "TxGEqnHWrfWFTfGW9XjX", "CNN Newsroom",
     "Trẻ, sâu — kiểu MC tin liên tục", "paid"),
    ("Sam",     "nam", "yoZ06aMxZJJ28mfd3POQ", "Fox Business",
     "Khàn, gai — kiểu MC tin nóng", "paid"),
    ("Domi",    "nu",  "AZnzlk1XvdvUeBnXmlld", "MSNBC",
     "Mạnh mẽ, quyết — kiểu MC chính luận", "paid"),
    ("Elli",    "nu",  "MF3mGyEYCl7XYWbV9V6O", "CNN Breaking",
     "Biểu cảm, dồn dập — kiểu đưa tin nóng", "paid"),
    ("Freya",   "nu",  "jsCqWAovK2LkecY7zXl4", "Sky News",
     "Biểu cảm — kiểu phóng viên hiện trường", "paid"),
    ("Grace",   "nu",  "oWAxZDx7w5VEj9dCyTzz", "ABC News (US South)",
     "Miền Nam US — kiểu phóng viên địa phương", "paid"),
    ("Nicole",  "nu",  "z9fAnlkpzviPz146aGWa", "podcast news",
     "Thì thầm — kiểu kể tin podcast", "paid"),
]


def voice_label(v) -> str:
    """Nhãn hiển thị trong combobox: Tên · nam/nữ · kiểu nhà đài (mô tả)."""
    name, g, vid, kieu, desc, tier = v
    flag = "" if tier == "free" else "  [TRẢ PHÍ]"
    return f"{name} · {g} · {kieu}{flag}"

MODELS = [
    ("eleven_multilingual_v2", "Multilingual v2 — chất lượng cao (1 credit/ký tự)", 1.0),
    ("eleven_turbo_v2_5",      "Turbo v2.5 — nhanh (0.5 credit/ký tự)",            0.5),
    ("eleven_flash_v2_5",      "Flash v2.5 — nhanh nhất (0.5 credit/ký tự)",       0.5),
]

DEFAULT_MODEL = "eleven_multilingual_v2"

# ── thời gian đọc ─────────────────────────────────────────────────────
# Video tin tức dài 15s -> audio cũng phải ~15s thì khớp. ElevenLabs KHÔNG
# nhận "độ dài mong muốn", nó đọc hết text nên dài ngắn tuỳ số ký tự. Vì vậy
# sau khi tạo xong phải ÉP về đúng số giây bằng ffmpeg (atempo co giãn giữ
# cao độ) — xem fit_duration().
DEFAULT_READ_SECONDS = 15.0

# Ước lượng tốc độ đọc của MC tin tức tiếng Anh, để hiện gợi ý số ký tự nên
# nhập. ĐO THẬT 4 giọng ElevenLabs (eleven_multilingual_v2, text tin tức 181
# ký tự): Brian 17.1, Daniel 13.4, Adam 14.5, George 17.4 -> trung bình 15.6
# ký tự/giây. Đặt 15.6 để gợi ý khỏi hụt (14.5 cũ hụt 7% -> audio ra ngắn rồi
# bị làm chậm nghe lê). Số thật vẫn đo lại và lưu vào config (khoá "tts_cps")
# sau mỗi lần tạo nên gợi ý ngày càng sát giọng đang dùng.
CHARS_PER_SEC_HINT = 15.6


def chars_for_seconds(secs: float, cps: float | None = None) -> int:
    """Số ký tự nên nhập để đọc vừa `secs` giây."""
    try:
        s = float(secs or 0)
    except Exception:
        return 0
    if s <= 0:
        return 0
    return int(round(s * float(cps or CHARS_PER_SEC_HINT)))


def _atempo_chain(ratio: float) -> str:
    """Chuỗi atempo cho hệ số bất kỳ (mỗi mắt chỉ nhận 0.5–2.0)."""
    parts, r = [], float(ratio)
    while r > 2.0:
        parts.append("atempo=2.0")
        r /= 2.0
    while r < 0.5:
        parts.append("atempo=0.5")
        r /= 0.5
    parts.append("atempo=%.6f" % r)
    return ",".join(parts)


def fit_duration(path, target_s: float, ffmpeg=None, log=None) -> dict:
    """Ép file audio về ĐÚNG `target_s` giây, GIỮ CAO ĐỘ (atempo, không méo giọng).

    - audio dài hơn đích -> đọc nhanh lên (atempo > 1)
    - audio ngắn hơn đích -> đọc chậm lại rồi đệm im lặng cho đủ
    Ghi đè chính file đó (mp3). Không raise — trả dict trạng thái.
    """
    try:
        target = float(target_s or 0)
    except Exception:
        target = 0.0
    if target <= 0.2:
        return {"ok": False, "msg": "thời gian đọc không hợp lệ"}
    try:
        from .ffmpeg_util import (find_ffmpeg, find_ffprobe, probe_duration,
                                  run_cmd)
    except ImportError:  # chạy trực tiếp không qua package
        from ffmpeg_util import (find_ffmpeg, find_ffprobe, probe_duration,
                                 run_cmd)
    path = Path(path)
    if not path.is_file():
        return {"ok": False, "msg": "không thấy file audio"}
    fp = find_ffprobe()
    d0 = float(probe_duration(str(path), fp) or 0.0)
    if d0 <= 0:
        return {"ok": False, "msg": "không đọc được thời lượng audio"}
    if abs(d0 - target) <= 0.06:
        return {"ok": True, "before": d0, "after": d0, "tempo": 1.0,
                "action": "đã đúng, giữ nguyên", "path": str(path)}
    exe = ffmpeg or find_ffmpeg()
    if not exe:
        return {"ok": False, "msg": "không tìm thấy ffmpeg"}
    ratio = d0 / target                      # >1: audio dài hơn đích
    af = _atempo_chain(ratio) + ",apad"      # apad bù im lặng nếu vẫn thiếu
    tmp = path.with_name(path.stem + ".fit.mp3")
    try:
        from .ffmpeg_util import _DUR_CACHE as _DC
    except ImportError:
        from ffmpeg_util import _DUR_CACHE as _DC
    # probe_duration CACHE THEO ĐƯỜNG DẪN, mà file tạm luôn cùng tên
    # (<tên>.fit.mp3) nên lần ép thứ hai trở đi sẽ đọc lại số giây CŨ của lần
    # trước -> tưởng ép hỏng (ép 15s->30s báo "ra 15.00s" dù file thật đúng 30s).
    # Xoá cache của cả file tạm lẫn file đích trước khi đo.
    _DC.pop(str(tmp), None)
    _DC.pop(str(path), None)
    try:
        tmp.unlink()                         # dọn file tạm còn sót của lần trước
    except Exception:
        pass
    cmd = [exe, "-y", "-v", "error", "-i", str(path), "-filter:a", af,
           "-t", "%.4f" % target,
           "-c:a", "libmp3lame", "-b:a", "192k", str(tmp)]
    try:
        run_cmd(cmd, log=None)
    except Exception as e:
        try:
            tmp.unlink()
        except Exception:
            pass
        return {"ok": False, "msg": "ffmpeg lỗi: %s" % e}
    d1 = float(probe_duration(str(tmp), fp) or 0.0)
    if not d1 or abs(d1 - target) > 0.25:
        try:
            tmp.unlink()
        except Exception:
            pass
        return {"ok": False, "msg": "ép thời lượng thất bại (ra %.2fs)" % (d1 or 0)}
    try:
        tmp.replace(path)
    except Exception as e:
        return {"ok": False, "msg": "không ghi đè được file: %s" % e}
    # probe_duration có cache theo đường dẫn -> phải xoá, không thì lần sau
    # vẫn đọc ra số giây CŨ của file trước khi ép.
    try:
        from .ffmpeg_util import _DUR_CACHE
    except ImportError:
        from ffmpeg_util import _DUR_CACHE
    _DUR_CACHE.pop(str(path), None)
    if ratio > 1.0001:
        act = "đọc nhanh %.3fx" % ratio
    elif ratio < 0.9999:
        act = "đọc chậm %.3fx + đệm im lặng" % ratio
    else:
        act = "giữ nguyên"
    # cảnh báo khi phải co giãn quá mạnh -> nghe gấp/lê thấy rõ
    warn = ""
    if ratio > 1.35:
        warn = "  ⚠ text DÀI hơn nhiều so với %gs — nên rút ngắn nội dung" % target
    elif ratio < 0.72:
        warn = "  ⚠ text NGẮN hơn nhiều so với %gs — nên viết thêm nội dung" % target
    if warn and log:
        log("   " + warn.strip())
    return {"ok": True, "before": d0, "after": d1, "tempo": ratio,
            "action": act + warn, "path": str(path)}


# cấu hình giọng mặc định — thiên về đọc tin (ổn định, ít "diễn")
VOICE_SETTINGS = {
    "stability": 0.45,
    "similarity_boost": 0.80,
    "style": 0.30,
    "use_speaker_boost": True,
}


# ── API key ───────────────────────────────────────────────────────────
def load_key() -> str:
    """Đọc key từ env hoặc file .env của Hermes."""
    k = (os.environ.get("ELEVENLABS_API_KEY") or "").strip()
    if k:
        return k
    try:
        if HERMES_ENV.is_file():
            for line in HERMES_ENV.read_text(encoding="utf-8").splitlines():
                if line.lstrip().startswith("#"):
                    continue
                m = re.match(r"^\s*ELEVENLABS_API_KEY\s*=\s*(.+?)\s*$", line)
                if m:
                    return m.group(1).strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


def save_key(key: str) -> Path:
    """Ghi key vào .env của Hermes (giữ nguyên các dòng khác)."""
    key = (key or "").strip()
    HERMES_ENV.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    if HERMES_ENV.is_file():
        try:
            lines = HERMES_ENV.read_text(encoding="utf-8").splitlines()
        except Exception:
            lines = []
    out, done = [], False
    for ln in lines:
        if re.match(r"^\s*ELEVENLABS_API_KEY\s*=", ln):
            out.append(f"ELEVENLABS_API_KEY={key}")
            done = True
        else:
            out.append(ln)
    if not done:
        out.append(f"ELEVENLABS_API_KEY={key}")
    HERMES_ENV.write_text("\n".join(out) + "\n", encoding="utf-8")
    return HERMES_ENV


def voice_by_id(vid: str):
    for v in VOICES:
        if v[2] == vid:
            return v
    return None


# ── API ───────────────────────────────────────────────────────────────
def _req(url: str, key: str, data=None, method="GET", timeout=120):
    headers = {"xi-api-key": key}
    if data is not None:
        headers["Content-Type"] = "application/json"
        headers["Accept"] = "audio/mpeg"
    r = request.Request(url, data=data, headers=headers, method=method)
    with request.urlopen(r, timeout=timeout) as resp:
        return resp.read()


def key_info(key: str) -> dict:
    """Kiểm tra key + lấy quyền/hạn mức. Không raise — trả dict trạng thái."""
    key = (key or "").strip()
    if not key:
        return {"ok": False, "msg": "chưa có key"}
    try:
        raw = _req(API_BASE + "/v1/user/subscription", key, timeout=45)
        d = json.loads(raw.decode("utf-8"))
        used = d.get("character_count", 0)
        lim = d.get("character_limit", 0)
        tier = d.get("tier", "?")
        return {"ok": True, "tier": tier, "used": used, "limit": lim,
                "msg": f"gói {tier} · đã dùng {used:,}/{lim:,} ký tự"}
    except error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        if "missing_permissions" in body:
            # key hạn chế quyền đọc -> vẫn có thể TTS
            return {"ok": True, "tier": "?", "msg": "key hạn chế quyền đọc (vẫn tạo được audio)"}
        if e.code == 401:
            return {"ok": False, "msg": "key sai hoặc đã bị thu hồi (401)"}
        return {"ok": False, "msg": f"lỗi {e.code}"}
    except Exception as e:
        return {"ok": False, "msg": f"{type(e).__name__}: {e}"}


def synthesize(key: str, voice_id: str, model_id: str, text: str,
               out_path: str | Path, settings: dict | None = None,
               speed: float = 1.0) -> dict:
    """Tạo MP3. Raise RuntimeError với thông báo tiếng Việt khi lỗi.

    `speed` (0.7–1.2 khuyến nghị) chỉnh tốc độ đọc ngay tại ElevenLabs.
    Mặc định 1.0 = giọng gốc; muốn khớp đúng số giây thì để nguyên 1.0 rồi
    dùng fit_duration() sau khi tạo.
    """
    text = (text or "").strip()
    if not text:
        raise RuntimeError("chưa nhập nội dung đọc")
    if not key:
        raise RuntimeError("chưa có API key ElevenLabs")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    st = dict(VOICE_SETTINGS)
    if settings:
        st.update(settings)
    try:
        sp = float(speed)
    except Exception:
        sp = 1.0
    if abs(sp - 1.0) > 0.001:
        st["speed"] = max(0.7, min(1.2, sp))
    body = json.dumps({
        "text": text,
        "model_id": model_id or DEFAULT_MODEL,
        "voice_settings": st,
    }).encode("utf-8")

    url = f"{API_BASE}/v1/text-to-speech/{voice_id}"
    t0 = time.time()
    try:
        data = _req(url, key, data=body, method="POST", timeout=180)
    except error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            msg = json.loads(raw)["detail"]["message"]
        except Exception:
            msg = raw[:200]
        if "paid_plan_required" in raw:
            raise RuntimeError(
                f"giọng này là giọng thư viện, gói free không dùng được qua API.\n"
                f"→ Nâng tài khoản ElevenLabs, hoặc chọn giọng nhóm ★ không có "
                f"chữ 'cần trả phí'.\n({msg})")
        raise RuntimeError(f"ElevenLabs lỗi {e.code}: {msg}")
    except Exception as e:
        raise RuntimeError(f"không gọi được ElevenLabs: {type(e).__name__}: {e}")
    if len(data) < 512:
        raise RuntimeError("ElevenLabs trả về dữ liệu rỗng")
    out_path.write_bytes(data)
    try:
        from .ffmpeg_util import probe_duration
    except ImportError:
        from ffmpeg_util import probe_duration
    secs = round(float(probe_duration(str(out_path)) or 0.0), 2)
    return {"bytes": len(data), "chars": len(text), "seconds": secs,
            "elapsed_s": round(time.time() - t0, 2), "path": str(out_path)}

