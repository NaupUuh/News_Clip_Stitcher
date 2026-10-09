# -*- coding: utf-8 -*-
"""Lấy tin hot 24h + nhờ Gemini viết lại thành tiêu đề 3 dòng.

NGUỒN TIN = Google News RSS (miễn phí, không cần key, có timestamp thật).
Gemini = chỉ VIẾT LẠI tiêu đề + gợi ý từ khoá tìm ảnh, KHÔNG được bịa tin.

Lý do thiết kế (đã đo thực tế, 2026-10-02):
  * Gemini grounding (google_search) trả HTTP 429 với mọi model -> KHÔNG dùng
    được làm nguồn tin.
  * Khi không có nguồn, Gemini TỰ BỊA tin (trả về tin không tồn tại). Vì vậy
    mọi tiêu đề đều phải xuất phát từ RSS và được kiểm tra lại độ trung thực.

API key: đọc từ env GEMINI_API_KEY / GOOGLE_API_KEY, rồi .env của hermes,
rồi config.json của tool (mục gemini_keys). KHÔNG BAO GIỜ in giá trị key.
"""
from __future__ import annotations

import html
import json
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ── Hằng số ────────────────────────────────────────────────────────────────
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"

# Thứ tự ưu tiên: model rẻ/nhanh trước, dự phòng khi 429/503.
# (gemini-2.5-* đã bị Google khai tử với key mới -> trả 404, không đưa vào.)
GEMINI_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.5-flash",
    "gemini-flash-lite-latest",
    "gemini-flash-latest",
    "gemini-3-flash-preview",
]

ENV_FILES = [
    Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / ".env",
    Path.home() / ".hermes" / ".env",
]

# Chủ đề tin. Mỗi chủ đề là (kiểu, giá trị):
#   ("t", <topic id>)  → Google News topic chuẩn
#   ("q", <truy vấn>)  → Google News search
#
# LƯU Ý QUAN TRỌNG (đã kiểm chứng 2026-10-03): Google News KHÔNG có topic
# "Politics" riêng. Trang chủ chỉ có: Top stories / U.S. / World / Business /
# Technology / Entertainment / Sports / Science / Health.
# ID cũ của "Chính trị Mỹ" thực ra trỏ vào "Top stories" (feed tổng hợp) nên
# tin THỂ THAO lọt vào bảng. ID "Khoa học" cũ thì 404 (chết hẳn).
# → "Chính trị Mỹ" giờ dùng SEARCH có lọc từ khoá, đã đo: 0/60 tin thể thao.
TOPICS = {
    "Chính trị Mỹ": ("q", "(politics OR congress OR senate OR white house OR election) when:1d"),
    "Thế giới":     ("t", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx1YlY4U0FtVnVHZ0pWVXlnQVAB"),
    "Kinh tế":      ("t", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtVnVHZ0pWVXlnQVAB"),
    "Khoa học":     ("t", "CAAqJggKIiBDQkFTRWdvSUwyMHZNRFp0Y1RjU0FtVnVHZ0pWVXlnQVAB"),
}

# ── RSS TRỰC TIẾP CỦA BÁO (nguồn tin "sạch") ───────────────────────────────
# Vì sao cần: RSS của Google News KHÔNG kèm ảnh, và <link> là
# news.google.com/rss/articles/<blob> — blob mã hoá AES nên KHÔNG giải ra URL
# báo được (đã đo: batchexecute của Google chặn theo IP, không dùng được cho
# tool chạy nhiều máy). Muốn "ảnh ĐÚNG TIN" thì phải lấy tin từ RSS của chính
# báo: link là URL thật VÀ <media:content>/<enclosure> có sẵn ảnh của bài.
# Đo thật 2026-10-09: 22/35 feed sống, ảnh to (NPR 6000x4000, Politico
# 4000x2666) — 12% đủ nét để tràn viền 9:16, 88% còn lại dùng chế độ "nền mờ"
# của stitcher (ảnh hiện trọn vẹn, vẫn nét).
DIRECT_FEEDS = {
    "Chính trị Mỹ": [
        # (đo 2026-10-09: feed sống + có ảnh trong RSS)
        "https://rss.nytimes.com/services/xml/rss/nyt/Politics.xml",
        "https://rss.nytimes.com/services/xml/rss/nyt/US.xml",
        "https://feeds.npr.org/1014/rss.xml",
        "https://feeds.npr.org/1001/rss.xml",
        "https://thehill.com/news/feed/",
        "https://thehill.com/homenews/feed/",
        "https://nypost.com/news/feed/",
        "https://nypost.com/us-news/feed/",
        "https://www.theguardian.com/us-news/rss",
        "https://www.theguardian.com/world/rss",
        "https://abcnews.go.com/abcnews/politicsheadlines",
        "https://abcnews.go.com/abcnews/topstories",
        "https://rss.politico.com/politics-news.xml",
        "https://rss.politico.com/congress.xml",
        "https://moxie.foxnews.com/google-publisher/politics.xml",
        "https://moxie.foxnews.com/google-publisher/us.xml",
        "http://rss.cnn.com/rss/cnn_allpolitics.rss",
        "http://rss.cnn.com/rss/cnn_us.rss",
        "https://feeds.skynews.com/feeds/rss/us.xml",
        "https://feeds.skynews.com/feeds/rss/world.xml",
        "https://www.thedailybeast.com/arc/outboundfeeds/rss/",
        "https://www.theblaze.com/feeds/feed.rss",
        "https://feeds.bbci.co.uk/news/world/us_and_canada/rss.xml",
        "https://www.cbsnews.com/latest/rss/politics",
        "https://www.cbsnews.com/latest/rss/main",
        "https://feeds.washingtonpost.com/rss/politics",
        "https://feeds.washingtonpost.com/rss/national",
        "https://www.pbs.org/newshour/feeds/rss/politics",
        "https://www.pbs.org/newshour/feeds/rss/headlines",
        "https://fortune.com/feed/",
        "https://www.nydailynews.com/feed/",
        "https://www.upi.com/rss/Top_News/",
        "https://www.upi.com/rss/US/",
        "https://www.newsweek.com/rss",
        "https://www.axios.com/feeds/feed.rss",
        "https://www.usatoday.com/rss/news/",
        "https://www.washingtonexaminer.com/feed",
        "https://www.independent.co.uk/news/world/americas/rss",
        "https://www.nbcnews.com/feed/politics",
        "https://www.nbcnews.com/feed/us",
        "https://www.cnbc.com/id/10000113/device/rss/rss.html",
        "https://www.latimes.com/politics/rss2.0.xml",
        "https://slate.com/feeds/all.rss",
        "https://www.salon.com/feed/",
        "https://www.huffpost.com/section/politics/feed",
        "https://www.rawstory.com/feed/",
        "https://www.mediaite.com/feed/",
        "https://www.chicagotribune.com/feed/",
        "https://www.theatlantic.com/feed/all/",
        "https://time.com/feed/",
        "https://www.jurist.org/feed/",
    ],
}
# Dấu hiệu ảnh trong 1 <item> của RSS, theo thứ tự ưu tiên (ảnh to trước).
_RSS_IMG_PATTERNS = (
    r'<media:content[^>]+url=["\']([^"\']+)',
    r'<enclosure[^>]+url=["\']([^"\']+)',
    r'<media:thumbnail[^>]+url=["\']([^"\']+)',
    r'<img[^>]+src=["\']([^"\']+)',
)

# Lưới an toàn: chặn tin thể thao lọt vào chủ đề chính trị.
# Search đã sạch (đo thật: 0/60), lưới này chỉ là DỰ PHÒNG — nên phải SIẾT CHẶT,
# chỉ giữ từ gần như chắc chắn là thể thao. Đừng thêm từ mơ hồ kiểu "coach",
# "stadium", "bracket", "tournament", "man city" — chúng bắt oan tin chính trị
# (vd "Trump Stadium rally", "Congress eyes NFL antitrust hearing" là tin thật).
# Khớp theo WORD BOUNDARY để "nba" không dính vào giữa từ khác.
SPORT_WORDS = [
    # giải đấu / tổ chức
    "wnba", "nba", "nfl", "mlb", "nhl", "mls", "ncaa", "ufc", "espn", "cbs sports",
    "premier league", "la liga", "serie a", "world cup", "super bowl",
    "olympic", "olympics", "college gameday", "transfer portal", "fantasy football",
    # thuật ngữ chỉ có trong thể thao
    "playoff", "playoffs", "touchdown", "quarterback", "linebacker", "slugger",
    "home run", "grand slam", "hat-trick", "semifinal", "semifinals", "quarterfinal",
    # đội bóng cụ thể
    "valkyries", "lakers", "celtics", "yankees", "dodgers", "cowboys", "chiefs",
    "49ers", "patriots", "man utd",
]
_SPORT_RE = re.compile(r"\b(?:%s)\b" % "|".join(re.escape(w) for w in SPORT_WORDS),
                       re.IGNORECASE)


def _is_sport(title: str) -> bool:
    """True nếu tiêu đề có dấu hiệu thể thao (dùng cho lưới an toàn)."""
    return bool(_SPORT_RE.search(title))

STOP = {"the", "a", "an", "of", "in", "to", "for", "on", "and", "with", "as",
        "at", "by", "from", "is", "are", "was", "were", "be", "been", "his",
        "her", "its", "that", "this", "after", "over", "into", "amid"}

# Từ "hook" — model được phép CHÈN vào tiêu đề để tăng tò mò/kịch tính.
# Chúng nằm trong STOP nên KHÔNG bị tính là bịa (faith không tụt oan).
# Cố ý KHÔNG có từ chỉ cảm xúc trống rỗng kiểu "WOW/AMAZING" — chỉ giữ những
# từ thực sự tạo sức nặng tin tức hoặc tạo khoảng trống tò mò.
HOOK = {
    # sức nặng tin tức
    "breaking", "urgent", "just", "now", "finally", "revealed", "exposed",
    "shocking", "stunning", "bombshell", "explosive", "chaos", "crisis",
    "warning", "alert", "panic", "backlash", "slams", "blasts", "destroys",
    "humiliates", "brutal", "savage", "furious", "outrage", "scandal",
    "meltdown", "collapse", "disaster", "threat", "danger", "emergency",
    # tạo khoảng trống tò mò
    "secret", "hidden", "leaked", "caught", "exposed", "nobody", "everyone",
    "why", "how", "what", "this", "these", "here", "watch", "look",
    "truth", "real", "reason", "moment", "seconds", "before", "after",
    "suddenly", "unexpectedly", "silent", "quiet", "mistake", "wrong",
    # leo thang
    "insane", "unbelievable", "incredible", "terrifying", "devastating",
    "massive", "huge", "major", "final", "last", "never", "stop",
}
STOP = STOP | HOOK

# Từ "sức nặng tin tức": ĐƯỢC TÍNH là hook NHƯNG **KHÔNG** được phép chèn.
# Cố ý để ngoài HOOK/STOP: nếu model tự thêm mà tiêu đề gốc không có thì
# `faithfulness` sẽ bắt được ngay (coi là bịa). Chỉ tính điểm khi CÓ THẬT.
HOOK_WEIGHT = {
    "banned", "ban", "bans", "barred", "blocked", "halts", "halted",
    "cuts", "slashes", "surge", "surges", "plunge", "plunges", "crash",
    "crashes", "spike", "spikes", "record", "historic", "arrest", "arrested",
    "indicted", "charged", "convicted", "guilty", "sentenced", "fired",
    "quits", "resigns", "dies", "dead", "killed", "death", "war", "battle",
    "showdown", "clash", "warns", "warned", "orders", "ordered", "probe",
    "lawsuit", "sues", "sued", "fraud", "scam", "hacked", "breach",
    "shutdown", "layoffs", "layoff", "tariffs", "inflation", "recession",
    "default", "veto", "impeach", "impeached", "deport", "deported",
    "border", "migrant", "migrants", "shortage", "crisis", "collapse",
    "scandal", "threat", "backlash", "leak", "exposed",
}

# Ngưỡng hook tối thiểu để tin được coi là "đạt". Tin dưới ngưỡng -> gọi ép lại
# 1 lượt nữa (xem _enforce_hook). Đo thật: model có lúc quên hook hoàn toàn và
# chỉ chia dòng lại (hook 0.28, faith 1.00) -> vòng ép kéo lên 0.5+.
HOOK_MIN = 0.35
_hook_retry = True                 # đặt False để chạy nhanh/tiết kiệm khi cần


# ── Key ────────────────────────────────────────────────────────────────────
def _read_env_file(p: Path) -> dict:
    out = {}
    try:
        for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass
    return out


# Nơi khác trên máy từng lưu key Gemini (tool khác) — dò thêm cho tiện
KEY_SOURCES = [
    Path("C:/Users/Admin/Desktop/Video_Highlight_Finder/config.json"),
    Path("C:/Users/Admin/Desktop/News_Clip_Stitcher/config.json"),
]


def _key_from_json(p: Path) -> str:
    """Đọc key trong config tool khác: gemini_keys / gemini_key / api_key."""
    try:
        c = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return ""
    for fld in ("gemini_keys", "gemini_key", "GEMINI_API_KEY", "gemini_api_key"):
        v = c.get(fld)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, list):
            for x in v:
                if str(x).strip():
                    return str(x).strip()
    return ""


def find_gemini_key(extra_config=None) -> tuple[str, str]:
    """Trả về (key, nguồn). Không bao giờ in giá trị key ra ngoài."""
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY"):
        v = (os.environ.get(name) or "").strip()
        if v:
            return v, f"env {name}"
    for f in ENV_FILES:
        if f.is_file():
            d = _read_env_file(f)
            for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY"):
                v = (d.get(name) or "").strip()
                if v:
                    return v, f"file {f.name}"
    cands = []
    if extra_config:
        cands.append(Path(extra_config))
    cands += [c for c in KEY_SOURCES if c not in cands]
    for p in cands:
        if p.is_file():
            v = _key_from_json(p)
            if v:
                return v, f"config {p.parent.name}"
    return "", ""


def mask(k: str) -> str:
    return (k[:6] + "..." + k[-4:]) if len(k) > 12 else "(ngắn)"


# ── Gemini ─────────────────────────────────────────────────────────────────
class Gemini:
    """Gọi Gemini có retry + đổi model. Không log key."""

    def __init__(self, key: str, models=None, log=print):
        self.key = key
        self.models = list(models or GEMINI_MODELS)
        self.log = log
        self.last_model = ""

    def _post(self, model: str, prompt: str, timeout: int = 180) -> tuple[int, str]:
        url = f"{GEMINI_BASE}/models/{model}:generateContent"
        body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "x-goog-api-key": self.key,
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                j = json.loads(r.read().decode("utf-8", "replace"))
            cands = j.get("candidates") or []
            if not cands:
                return 200, ""
            parts = (cands[0].get("content") or {}).get("parts") or []
            return 200, "".join(p.get("text", "") for p in parts)
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = json.loads(e.read().decode("utf-8", "replace"))
                detail = (detail.get("error") or {}).get("message", "")[:90]
            except Exception:
                pass
            return e.code, detail
        except Exception as e:
            return -1, str(e)[:90]

    def ask(self, prompt: str, tries: int = 3) -> str:
        """Trả về text. Ném RuntimeError nếu mọi model đều hỏng."""
        last = ""
        for attempt in range(tries):
            for m in self.models:
                code, txt = self._post(m, prompt)
                if code == 200 and txt.strip():
                    self.last_model = m
                    return txt
                if code in (429, 500, 503):
                    last = f"{m}: {code}"
                    continue          # thử model kế tiếp
                last = f"{m}: {code} {txt}"
                break                 # lỗi khác (400/404) -> đổi prompt, không đổi model
            time.sleep(2 + attempt * 3)
        raise RuntimeError(f"Gemini không phản hồi ({last})")

    def ok(self) -> tuple[bool, str]:
        """Kiểm tra key còn sống không."""
        code, txt = self._post(self.models[0], "Tra loi dung 2 chu: OK", timeout=60)
        if code == 200:
            return True, f"OK ({self.models[0]})"
        return False, f"HTTP {code} {txt}"


# ── Vilao (OpenAI-compatible) ──────────────────────────────────────────────
VILAO_BASE = "https://api.vilao.ai/v1"

# Model mặc định. Đo thật 2026-10-03 (8 tin chính trị, lặp 5 vòng = 40 tin,
# dùng CHÍNH rewrite_titles của tool):
#   deepseek-v4.1-flash : TB  5.3s, hook TB 0.700 (92% >=0.5), faith 0.877
#   gpt-5.6-luna        : TB 95.6s, hook TB 0.619 (88% >=0.5), faith 0.937
#   gpt-6-luna          : TB 23.3s, từ khoá tìm ảnh đều tay hơn (100% dạng
#                         "a, b, c" vs 67% của 5.6)
# Cả 3 đều 0 bịa số / 0 lọt tên báo / 0 dòng quá 40 ký tự.
# -> mặc định deepseek-v4.1-flash: hook cao nhất VÀ nhanh hơn 5.6 gần 18 lần
#    (quan trọng khi chạy hàng loạt). 5.6 làm dự phòng 1, 6 làm dự phòng 2.
#    User vẫn gõ tay được model khác trong GUI (nút ⟳ nạp list sống từ Vilao).
VILAO_MODELS = ["deepseek-v4.1-flash", "gpt-5.6-luna", "gpt-6-luna"]


def find_vilao_key(extra_config=None, user_key: str = "") -> tuple[str, str]:
    """Trả về (key, nguồn) cho Vilao. Không bao giờ in giá trị key ra ngoài.

    user_key: key gõ tay trong ô GUI. Ưu tiên CAO NHẤT — user nhập tay nghĩa là
    muốn dùng đúng key đó (đổi key / key mới chưa kịp vào .env), không thì phải
    sửa .env mới chạy được.
    """
    uk = (user_key or "").strip()
    if uk:
        return uk, "ô nhập trong tool"
    for name in ("VILAO_API_KEY", "HERMES_CUSTOM_API_VILAO_AI_API_KEY",
                 "VILAO_AI_API_KEY"):
        v = (os.environ.get(name) or "").strip()
        if v:
            return v, f"env {name}"
    for f in ENV_FILES:
        if f.is_file():
            d = _read_env_file(f)
            for name in ("VILAO_API_KEY", "HERMES_CUSTOM_API_VILAO_AI_API_KEY",
                         "VILAO_AI_API_KEY"):
                v = (d.get(name) or "").strip()
                if v:
                    return v, f"file {f.name}"
    cands = []
    if extra_config:
        cands.append(Path(extra_config))
    cands += [c for c in KEY_SOURCES if c not in cands]
    for p in cands:
        if p.is_file():
            try:
                d = json.loads(p.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                continue
            for fld in ("vilao_key", "vilao_keys", "VILAO_API_KEY"):
                v = d.get(fld)
                if isinstance(v, list) and v:
                    v = v[0]
                if isinstance(v, str) and v.strip():
                    return v.strip(), f"config {p.parent.name}"
    return "", ""


def list_vilao_models(key: str, timeout: int = 30) -> list[str]:
    """Nạp danh sách model SỐNG từ Vilao (GET /v1/models).

    Vilao thêm/bớt model liên tục nên KHÔNG hardcode danh sách — gọi hàm này
    để lấy tên thật. Trả [] nếu lỗi (không raise, để GUI vẫn chạy).
    """
    if not key:
        return []
    url = f"{VILAO_BASE}/models"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            j = json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return []
    data = j.get("data") or j.get("models") or []
    out = []
    if isinstance(data, list):
        for m in data:
            if isinstance(m, dict):
                v = m.get("id") or m.get("name") or ""
            elif isinstance(m, str):
                v = m
            else:
                v = ""
            if str(v).strip():
                out.append(str(v).strip())
    return sorted(out)


class Vilao:
    """Gọi Vilao (OpenAI-compatible) có retry + đổi model. Không log key.

    Giao diện giống hệt Gemini (.ask/.ok) nên rewrite_titles dùng chung được.
    """

    def __init__(self, key: str, models=None, log=print):
        self.key = key
        self.models = list(models or VILAO_MODELS)
        self.log = log
        self.last_model = ""

    def _post(self, model: str, prompt: str, timeout: int = 180,
              max_tokens: int = 4000) -> tuple[int, str]:
        url = f"{VILAO_BASE}/chat/completions"
        body = json.dumps({
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                j = json.loads(r.read().decode("utf-8", "replace"))
            ch = j.get("choices") or []
            if not ch:
                return 200, ""
            msg = ch[0].get("message") or {}
            txt = msg.get("content") or ""
            # vài model trả phần suy nghĩ riêng; chỉ dùng khi content rỗng
            if not txt.strip():
                txt = msg.get("reasoning_content") or ""
            return 200, txt
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = json.loads(e.read().decode("utf-8", "replace"))
                detail = ((detail.get("error") or {}).get("message", "")
                          or str(detail))[:90]
            except Exception:
                pass
            return e.code, detail
        except Exception as e:
            return -1, str(e)[:90]

    def ask(self, prompt: str, tries: int = 3) -> str:
        """Trả về text. Ném RuntimeError nếu mọi model đều hỏng."""
        last = ""
        for attempt in range(tries):
            for m in self.models:
                code, txt = self._post(m, prompt)
                if code == 200 and txt.strip():
                    self.last_model = m
                    return txt
                if code in (429, 500, 503):
                    last = f"{m}: {code}"
                    continue          # thử model kế tiếp
                last = f"{m}: {code} {txt}"
                break                 # lỗi khác (400/404) -> đổi prompt, không đổi model
            time.sleep(2 + attempt * 3)
        raise RuntimeError(f"Vilao không phản hồi ({last})")

    def ok(self) -> tuple[bool, str]:
        """Kiểm tra key còn sống không."""
        code, txt = self._post(self.models[0], "Tra loi dung 2 chu: OK",
                               timeout=60, max_tokens=64)
        if code == 200:
            return True, f"OK ({self.models[0]})"
        return False, f"HTTP {code} {txt}"


# ── RSS ────────────────────────────────────────────────────────────────────
def _parse_age(s: str):
    try:
        dt = datetime.strptime(s.strip(), "%a, %d %b %Y %H:%M:%S %Z")
        dt = dt.replace(tzinfo=timezone.utc)
        return round((datetime.now(timezone.utc) - dt).total_seconds() / 3600.0, 1)
    except Exception:
        return None


# Tên báo cho đẹp (tra theo host của feed). Không có trong bảng thì lấy phần
# tên miền chính (vd "example.com" -> "example").
FEED_NAMES = {
    "rss.nytimes.com": "New York Times", "feeds.npr.org": "NPR",
    "thehill.com": "The Hill", "nypost.com": "New York Post",
    "theguardian.com": "The Guardian", "abcnews.go.com": "ABC News",
    "rss.politico.com": "Politico", "moxie.foxnews.com": "Fox News",
    "rss.cnn.com": "CNN", "feeds.skynews.com": "Sky News",
    "thedailybeast.com": "Daily Beast", "theblaze.com": "TheBlaze",
    "feeds.bbci.co.uk": "BBC", "cbsnews.com": "CBS News",
    "feeds.washingtonpost.com": "Washington Post", "pbs.org": "PBS",
    "fortune.com": "Fortune", "nydailynews.com": "NY Daily News",
    "upi.com": "UPI", "newsweek.com": "Newsweek", "axios.com": "Axios",
    "usatoday.com": "USA Today", "washingtonexaminer.com": "Wash. Examiner",
    "independent.co.uk": "The Independent", "nbcnews.com": "NBC News",
    "cnbc.com": "CNBC", "latimes.com": "LA Times", "slate.com": "Slate",
    "salon.com": "Salon", "huffpost.com": "HuffPost",
    "rawstory.com": "Raw Story", "mediaite.com": "Mediaite",
    "chicagotribune.com": "Chicago Tribune", "theatlantic.com": "The Atlantic",
    "time.com": "TIME", "jurist.org": "JURIST",
}


def _feed_name(url: str) -> str:
    host = url.split("/")[2].lower()
    if host.startswith("www."):
        host = host[4:]
    if host in FEED_NAMES:
        return FEED_NAMES[host]
    parts = host.split(".")
    return parts[-2].capitalize() if len(parts) >= 2 else host


def _item_image(raw_item: str) -> str:
    """Ảnh TO NHẤT của 1 <item> RSS.

    Nhiều báo (Guardian...) liệt kê cùng 1 ảnh ở nhiều cỡ qua nhiều thẻ
    <media:content width="140|460|700">. Lấy thẻ đầu là lấy bản 140px -> vô
    dụng cho video. Nên: gom mọi thẻ có `width`, chọn width lớn nhất; không
    thẻ nào ghi width thì lấy thẻ đầu (media:content -> enclosure ->
    media:thumbnail -> img).
    """
    best_u, best_w = "", -1
    for m in re.finditer(r"<(?:media:content|media:thumbnail|enclosure|img)\b[^>]*>",
                         raw_item, re.I):
        tag = m.group(0)
        um = re.search(r'url=["\']([^"\']+)', tag, re.I) or \
            re.search(r'src=["\']([^"\']+)', tag, re.I)
        if not um:
            continue
        wm = re.search(r'width=["\']?(\d+)', tag, re.I)
        w = int(wm.group(1)) if wm else 0
        if w > best_w:
            best_w, best_u = w, html.unescape(um.group(1)).strip()
    if best_u:
        return best_u
    # dự phòng: ảnh nhúng trong <description>
    for pat in _RSS_IMG_PATTERNS:
        m = re.search(pat, raw_item, re.I)
        if m:
            return html.unescape(m.group(1)).strip()
    return ""


def fetch_direct(topics=None, hours: int = 24, per_topic: int = 60,
                 log=print) -> list[dict]:
    """Lấy tin từ RSS TRỰC TIẾP của báo — có LINK THẬT + ẢNH của bài.

    Khác fetch_rss (Google News): mỗi item ở đây có thêm khóa "image" (URL ảnh
    đúng của bài) và "link" là URL báo thật -> tab "Tìm ảnh theo tin" lấy được
    ĐÚNG ảnh của tin đang chọn mà không phải đi tìm kiếm.
    """
    topics = topics or ["Chính trị Mỹ"]
    feeds = []
    for t in topics:
        for u in DIRECT_FEEDS.get(t, []):
            if u not in feeds:
                feeds.append(u)
    if not feeds:
        return []

    def grab(u):
        try:
            req = urllib.request.Request(u, headers={
                "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/124.0.0.0 Safari/537.36"),
                "Accept-Language": "en-US,en;q=0.9",
            })
            with urllib.request.urlopen(req, timeout=25) as r:
                return u, r.read(3_000_000).decode("utf-8", "replace")
        except Exception:
            return u, ""

    import concurrent.futures as _cf
    with _cf.ThreadPoolExecutor(max_workers=12) as ex:
        pages = list(ex.map(grab, feeds))

    out, seen = [], set()
    n_ok = n_img = 0
    for u, raw in pages:
        if not raw:
            continue
        n_ok += 1
        src = _feed_name(u)
        for it in re.findall(r"<item[ >](.*?)</item>", raw, re.S):
            tm = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>",
                           it, re.S)
            lm = re.search(r"<link>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</link>",
                           it, re.S)
            dm = re.search(r"<pubDate>(.*?)</pubDate>", it, re.S)
            if not (tm and lm):
                continue
            age = _parse_age(dm.group(1)) if dm else None
            if age is None or age > hours:
                continue
            title = clean_title(html.unescape(tm.group(1)).strip(), src)
            if _is_sport(title):
                continue
            key = re.sub(r"\W+", "", title.lower())[:60]
            if not key or key in seen:
                continue
            seen.add(key)
            img = _item_image(it)
            if img:
                n_img += 1
            out.append({
                "title": title,
                "source": src,
                "age_h": age,
                "link": html.unescape(lm.group(1)).strip(),
                "topic": topics[0],
                "image": img,
            })
    log(f"  RSS báo trực tiếp: {n_ok}/{len(feeds)} feed sống, "
        f"{len(out)} tin ({n_img} có sẵn ảnh)")
    return out[:per_topic] if per_topic else out


def fetch_rss(topics=None, hours: int = 24, per_topic: int = 60,
              log=print) -> list[dict]:
    """Lấy tin từ Google News RSS. Trả list dict: title, source, age_h, link, topic."""
    topics = topics or ["Chính trị Mỹ"]
    out, seen = [], set()
    n_skip_sport = 0
    for name in topics:
        spec = TOPICS.get(name)
        if not spec:
            log(f"  ! chủ đề lạ: {name}")
            continue
        kind, val = spec
        if kind == "q":
            url = ("https://news.google.com/rss/search?q=%s&hl=en-US&gl=US&ceid=US:en"
                   % urllib.parse.quote(val))
        else:
            url = ("https://news.google.com/rss/topics/%s?hl=en-US&gl=US&ceid=US:en"
                   % val)
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/124.0.0.0 Safari/537.36"),
                "Accept-Language": "en-US,en;q=0.9",
            })
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read().decode("utf-8", "replace")
        except Exception as e:
            log(f"  ! lỗi tải RSS {name}: {e}")
            continue
        n_before = len(out)
        for it in re.findall(r"<item>(.*?)</item>", raw, re.S):
            tm = re.search(r"<title>(.*?)</title>", it, re.S)
            if not tm:
                continue
            title = html.unescape(tm.group(1)).strip()
            sm = re.search(r"<source[^>]*>(.*?)</source>", it, re.S)
            dm = re.search(r"<pubDate>(.*?)</pubDate>", it, re.S)
            lm = re.search(r"<link>(.*?)</link>", it, re.S)
            age = _parse_age(dm.group(1)) if dm else None
            if age is None or age > hours:
                continue
            src = html.unescape(sm.group(1)).strip() if sm else ""
            title = clean_title(title, src)
            # Lưới an toàn: chủ đề chính trị không nhận tin thể thao.
            if name == "Chính trị Mỹ" and _is_sport(title):
                n_skip_sport += 1
                continue
            key = re.sub(r"\W+", "", title.lower())[:60]
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "title": title,
                "source": src,
                "age_h": age,
                "link": lm.group(1).strip() if lm else "",
                "topic": name,
            })
        log(f"  {name}: +{len(out) - n_before} tin (<={hours}h)")
    if n_skip_sport:
        log(f"  (đã loại {n_skip_sport} tin thể thao lạc chủ đề)")
    out.sort(key=lambda x: x["age_h"])
    return out[:per_topic] if per_topic else out


def fetch_news(topics=None, hours: int = 24, per_topic: int = 60,
               log=print) -> list[dict]:
    """Nguồn tin MẶC ĐỊNH: RSS báo trực tiếp (có link thật + ảnh) TRƯỚC,
    thiếu thì bù bằng Google News RSS.

    Vì sao ưu tiên báo trực tiếp: tin có "image" + "link" thật -> tab "Tìm ảnh
    theo tin" lấy được ĐÚNG ảnh của bài. Google News chỉ là nguồn bù vì không
    kèm ảnh và link là blob mã hoá không giải được.
    """
    direct = fetch_direct(topics, hours=hours, per_topic=per_topic, log=log)
    if len(direct) >= per_topic:
        return direct[:per_topic]
    seen = {re.sub(r"\W+", "", d["title"].lower())[:60] for d in direct}
    need = per_topic - len(direct)
    rest = fetch_rss(topics, hours=hours, per_topic=need * 3, log=log)
    for r in rest:
        k = re.sub(r"\W+", "", r["title"].lower())[:60]
        if k in seen:
            continue
        seen.add(k)
        r.setdefault("image", "")
        direct.append(r)
        if len(direct) >= per_topic:
            break
    direct.sort(key=lambda x: x.get("age_h", 99))
    log(f"  tổng {len(direct)} tin "
        f"({sum(1 for d in direct if d.get('image'))} có sẵn ảnh)")
    return direct


# ── Nhờ Gemini viết lại ────────────────────────────────────────────────────
def clean_title(title: str, source: str = "") -> str:
    """Bỏ đuôi ' - Tên báo' mà Google News gắn vào tiêu đề."""
    t = title.strip()
    tail = t.rsplit(" - ", 1)
    if len(tail) == 2:
        last = tail[1].strip()
        src = (source or "").strip()
        looks_like_media = (len(last) <= 42 and not last.endswith((".", "?", "!", ","))
                            and (not src or last.lower() == src.lower()
                                 or src.lower().startswith(last.lower()[:10])
                                 or last.lower() in src.lower()))
        if looks_like_media:
            t = tail[0].strip()
    return t


def _toks(s: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in STOP and len(w) > 2}


def _covered(tok: str, pool: set) -> bool:
    """Khớp tiền tố: 'tenn' ~ 'tennessee', 'kati' ~ 'katie'."""
    if tok in pool:
        return True
    stem = tok[:4]
    return any(p.startswith(stem) or tok.startswith(p[:4]) for p in pool if len(p) >= 4)


def faithfulness(src: str, lines: list[str]) -> float:
    """Tỉ lệ từ khoá trong các dòng được TIÊU ĐỀ GỐC chống lưng (0..1).

    Dùng hướng "chống lưng" (mỗi từ của output phải có trong nguồn) thay vì
    so trùng tập hợp: Gemini được phép viết TẮT ('Tennessee' -> 'TENN.') nên
    so trùng tập hợp sẽ phạt oan. Cái cần chặn là BỊA thêm chi tiết mới.
    """
    pool = _toks(src)
    body = _toks(" ".join(lines))
    if not body:
        return 0.0
    return round(sum(1 for t in body if _covered(t, pool)) / len(body), 2)


def hook_score(lines: list[str]) -> float:
    """Đo độ HOOK của tiêu đề đã viết lại (0..1). Để kiểm chứng bằng số.

    Cộng 3 tín hiệu:
      - có từ hook (sức nặng / tò mò)          -> tối đa 0.5
      - có DẤU CÂU tạo nhịp (?, !, :, —)      -> tối đa 0.25
      - có con số cụ thể (1,400 / 2026 / 3)   -> tối đa 0.25
    Tính CẢ HOOK_WEIGHT (từ sức nặng có thật trong tin gốc) — trước đây bỏ sót
    nên tin kiểu 'CNN BANNED FROM WHITE HOUSE' chỉ được 0.25 dù rất mạnh.
    Đây là thước đo nội bộ, KHÔNG phải dự đoán viral.
    """
    body = " ".join(lines or [])
    if not body.strip():
        return 0.0
    toks = set(re.findall(r"[a-z0-9]+", body.lower()))
    n_hook = len(toks & (HOOK | HOOK_WEIGHT))
    s_hook = min(0.5, 0.25 * n_hook)
    s_punc = 0.25 if re.search(r"[?!:]|--|—", body) else 0.0
    s_num = 0.25 if re.search(r"\b\d[\d,.]*\b", body) else 0.0
    return round(min(1.0, s_hook + s_punc + s_num), 2)


def fab_numbers(src: str, lines: list[str]) -> list[str]:
    """Liệt kê SỐ/CON SỐ trong output KHÔNG có trong tiêu đề gốc.

    Đây mới là thứ nguy hiểm: bịa số liệu ('1,400' khi gốc không có) là sai
    sự thật. Còn câu hỏi hook ('WHAT COMES NEXT?') không phải bịa — nên tách
    riêng khỏi `faithfulness`.
    """
    src_nums = {re.sub(r"[^\d]", "", x) for x in re.findall(r"\d[\d,.]*", src)}
    bad = []
    for x in re.findall(r"\d[\d,.]*", " ".join(lines or [])):
        if re.sub(r"[^\d]", "", x) not in src_nums:
            bad.append(x)
    return bad


_MEDIA_WORDS = {
    "abc", "news", "cnn", "fox", "nbc", "cbs", "bbc", "msnbc", "ap", "reuters",
    "npr", "pbs", "usa", "today", "times", "post", "washington", "new", "york",
    "guardian", "bloomberg", "politico", "axios", "hill", "daily", "mail",
    "telegraph", "independent", "sky", "jazeera", "dw", "wsj", "journal",
    "associated", "press", "global", "local", "breaking", "live", "now",
    "national", "public", "radio", "network", "media", "watch", "world",
    "report", "morning", "evening", "star", "tribune", "herald", "gazette",
    "on", "your", "side", "com", "the", "and", "of",
}


# Cụm từ KHÔNG được cắt đôi giữa 2 dòng. Đo thật: model cho ra
# "TRUMP TAPS JAY CLAYTON AS WHITE / HOUSE AI CZAR" -> lên banner trông
# nghiệp dư. Sửa bằng cách kéo 2 từ về cùng 1 dòng.
_KEEP_TOGETHER = {
    ("white", "house"), ("new", "york"), ("supreme", "court"),
    ("los", "angeles"), ("san", "francisco"), ("united", "states"),
    ("united", "nations"), ("wall", "street"), ("vice", "president"),
    ("prime", "minister"), ("secret", "service"), ("air", "force"),
    ("national", "guard"), ("homeland", "security"),
    ("justice", "department"), ("state", "department"),
    ("treasury", "department"), ("federal", "reserve"),
    ("capitol", "hill"), ("times", "square"), ("las", "vegas"),
    ("north", "korea"), ("south", "korea"), ("saudi", "arabia"),
    ("hong", "kong"), ("new", "jersey"), ("new", "mexico"),
    ("north", "carolina"), ("south", "carolina"), ("rhode", "island"),
    ("new", "hampshire"), ("press", "conference"), ("white", "house's"),
    ("donald", "trump"), ("joe", "biden"), ("kamala", "harris"),
    ("jay", "clayton"), ("elon", "musk"), ("vladimir", "putin"),
}


def _fix_phrase_breaks(lines: list[str], max_chars: int) -> list[str]:
    """Không để 1 cụm từ bị cắt đôi giữa 2 dòng ('WHITE / HOUSE').

    Với mỗi ranh giới dòng, nếu từ cuối dòng trên + từ đầu dòng dưới tạo
    thành cụm trong `_KEEP_TOGETHER` thì kéo từ cuối XUỐNG dòng dưới; nếu
    dòng dưới quá dài thì đẩy từ đầu dòng dưới LÊN dòng trên.
    """
    out = [str(x).strip() for x in (lines or []) if str(x).strip()]
    for i in range(len(out) - 1):
        a, b = out[i].split(), out[i + 1].split()
        if not a or not b:
            continue
        pair = (a[-1].lower().strip(".,:;!?\"'"), b[0].lower().strip(".,:;!?\"'"))
        if pair not in _KEEP_TOGETHER:
            continue
        # (1) kéo từ cuối dòng trên xuống đầu dòng dưới
        cand_b = " ".join([a[-1]] + b)
        if len(cand_b) <= max_chars:
            out[i] = " ".join(a[:-1])
            out[i + 1] = cand_b
        # (2) ngược lại: kéo từ đầu dòng dưới lên cuối dòng trên
        elif len(" ".join(a + [b[0]])) <= max_chars:
            out[i] = " ".join(a + [b[0]])
            out[i + 1] = " ".join(b[1:])
    return [x for x in out if x.strip()]


def _clamp_lines(lines: list[str], max_lines: int, max_chars: int) -> list[str]:
    """Ép số dòng + số ký tự đúng giới hạn banner.

    Model hay vượt 40 ký tự (đo thật: 3/40 dòng) -> chữ tràn khỏi khung. Dàn
    đều chữ vào đúng max_lines dòng, mỗi dòng <= max_chars, cắt tại ranh giới
    TỪ. Chỉ cắt bớt chữ khi tổng độ dài vượt sức chứa (bất khả kháng).
    """
    words = " ".join(" ".join(lines or []).split()).split()
    if not words:
        return []
    cap = max_lines * max_chars
    total = len(" ".join(words))
    if total > cap:                      # bất khả kháng: bỏ bớt từ cuối
        while words and len(" ".join(words)) > cap:
            words.pop()
    total = len(" ".join(words))
    # thử dàn đều trước, nếu vẫn quá số dòng thì mới dùng hết bề ngang
    for target in (max(8, -(-total // max_lines)), max_chars):
        out, cur = [], ""
        for w in words:
            if cur and len(cur) + 1 + len(w) > target:
                out.append(cur)
                cur = w
            else:
                cur = (cur + " " + w).strip()
        if cur:
            out.append(cur)
        if len(out) <= max_lines and all(len(x) <= max_chars for x in out):
            return _fix_phrase_breaks(out, max_chars)
    return _fix_phrase_breaks(out[:max_lines], max_chars)


def strip_source_tail(lines: list[str], source: str = "") -> list[str]:
    """Bỏ đuôi TÊN BÁO mà model tự gắn vào dòng cuối ('... - ABC NEWS').

    User yêu cầu banner CHỈ có tiêu đề, không nguồn không giờ. Chỉ cắt khi
    phần đuôi (sau - | – —) gồm >=2 từ VÀ toàn bộ đều là từ tên báo — để
    không cắt oan nội dung thật (vd 'TRUMP - PUTIN TALKS').
    """
    if not lines:
        return lines
    out = list(lines)
    src = set(re.findall(r"[a-z0-9]+", (source or "").lower()))
    m = re.search(r"\s*[-–—|]\s*([^-–—|]+)$", out[-1])
    if m:
        tw = set(re.findall(r"[a-z0-9]+", m.group(1).lower()))
        # >=2 từ thì phải toàn từ tên báo; 1 từ thì phải khớp ĐÚNG tên nguồn.
        hit = ((len(tw) >= 2 and tw <= (_MEDIA_WORDS | src))
               or (len(tw) == 1 and tw <= src))
        if hit:
            out[-1] = out[-1][:m.start()].rstrip()
    return [x for x in out if x.strip()]


def _extract_json(txt: str):
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def rewrite_titles(items: list[dict], gem: Gemini, max_lines: int = 3,
                   max_chars: int = 40, batch: int = 8,
                   log=print) -> list[dict]:
    """Thêm 'lines' (list[str]) + 'keyword' + 'faith' vào từng item.

    Prompt được siết chặt: chỉ chia lại tiêu đề CÓ SẴN, cấm thêm tin ngoài
    danh sách. Đã kiểm nghiệm: nếu không siết, model lôi tin từ trí nhớ ra
    (bịa). Sau khi viết lại, từng dòng được chấm độ trùng ý với tiêu đề gốc.
    """
    for i in range(0, len(items), batch):
        chunk = items[i:i + batch]
        listing = "\n".join("%d) %s" % (n + 1, it["title"]) for n, it in enumerate(chunk))
        prompt = (
            "You are the headline writer for the most-watched TV news show in\n"
            "America. You get REAL news headlines from the last 24 hours. A viewer\n"
            "scrolls past in 1 second - you must make them STOP.\n\n"
            "1) Rewrite each headline into AT MOST %d lines, ALL CAPS, each line at\n"
            "   most %d characters, using EXACTLY this shape:\n\n"
            "     LINE 1 = OPENER + the sharpest fact. The opener MUST be one of:\n"
            "              JUST IN: / BREAKING: / NOW: / WARNING: / NEW:\n"
            "              (if none fits, start with the key noun phrase then ':')\n"
            "     LINE 2 = the concrete detail, plain, no opener\n"
            "     LINE 3 = the consequence, or a question ending with '?'\n\n"
            "   Every headline MUST also do at least ONE of these:\n"
            "     - have ':' on line 1\n"
            "     - have '?' or a concrete number somewhere\n\n"
            "   WORKED EXAMPLES (copy the shape, not the words):\n"
            "     in : A gut punch in Ohio: Nearly 1,400 laid off at truck factory\n"
            "          just days before Trump rally\n"
            "     out: JUST IN: NEARLY 1,400 / LAID OFF AT TRUCK FACTORY / DAYS\n"
            "          BEFORE TRUMP RALLY\n"
            "     in : Trump heads back to Texas on Wednesday as GOP fights to keep\n"
            "          state red\n"
            "     out: NOW: TRUMP RETURNS / TO TEXAS WEDNESDAY / CAN THE GOP HOLD IT?\n"
            "     in : DOJ Argues CNN & Other Outlets Can Be Banned From White House\n"
            "     out: BREAKING: DOJ MOVES / ON CNN AND OTHERS / BAN FROM THE WHITE\n"
            "          HOUSE?\n\n"
            "   HARD RULES (breaking these is worse than being boring):\n"
            "     - NEVER invent facts, numbers, names, quotes or outcomes. Every\n"
            "       FACT must come from the original headline. You may only ADD the\n"
            "       opener words (JUST IN / BREAKING / NOW / WARNING / NEW) and the\n"
            "       curiosity words WHY / WHO / HOW / NOBODY / EVERYONE.\n"
            "     - NEVER invent a number. If the original has no number, your\n"
            "       headline has no number.\n"
            "     - NEVER use LEAKED / REVEALED / EXPOSED / INSIDER unless the\n"
            "       original already has it.\n"
            "     - Keep the exact meaning. Do not flip who did what to whom.\n"
            "     - No fake death, no fake arrest, no invented scandal, no quote.\n"
            "     - Do NOT write the source name or the time (no 'BBC', no '5H AGO').\n\n"
            "2) Suggest 3-4 ENGLISH keywords for finding a stock photo, comma\n"
            "   separated, concrete and visual (people, place, object).\n\n"
            "You must NOT invent any headline that is not in the list.\n"
            'Return JSON only: {"tin":[{"stt":N,"dong":["d1","d2","d3"],"keyword":"..."}]}\n'
            "No explanation.\n\nLIST:\n" + listing
        ) % (max_lines, max_chars)
        try:
            data = _extract_json(gem.ask(prompt))
        except Exception as e:
            log(f"  ! Gemini lỗi (lô {i // batch + 1}): {e}")
            data = None
        got = {}
        if data:
            for it in data.get("tin", []):
                try:
                    got[int(it["stt"])] = it
                except Exception:
                    pass
        for n, it in enumerate(chunk, 1):
            g = got.get(n) or {}
            lines = [str(x).strip() for x in (g.get("dong") or []) if str(x).strip()]
            if not lines:                      # model hỏng -> tự chia theo từ
                lines = _split_fallback(it["title"], max_lines, max_chars)
            lines = strip_source_tail(lines, it.get("source", ""))
            lines = _clamp_lines(lines, max_lines, max_chars)
            it["lines"] = lines[:max_lines]
            it["keyword"] = (g.get("keyword") or "").strip() or _kw_fallback(it["title"])
            it["faith"] = round(faithfulness(it["title"], it["lines"]), 2)
            it["hook"] = hook_score(it["lines"])
            it["fabnum"] = fab_numbers(it["title"], it["lines"])

        # VONG EP LAI: model co luc bo qua chi dan hook va chi chia dong lai
        # (do that: hook tut ve 0.28, faith 1.00). Ep lai dung nhung tin chua dat.
        weak = [it for it in chunk if it.get("hook", 0) < HOOK_MIN]
        if weak and _hook_retry:
            try:
                _enforce_hook(weak, gem, max_lines, max_chars, log)
            except Exception as e:
                log(f"  ! ép hook lỗi (lô {i // batch + 1}): {e}")

        if i + batch < len(items):
            time.sleep(1.2)                    # tránh nghen quota
    return items


def _enforce_hook(items, gem, max_lines, max_chars, log=print):
    """Ép lại CHỈ những tin chưa đạt hook (1 lượt gọi thêm, gộp 1 lô).

    Model có lúc chỉ chia dòng lại mà quên hook. Lượt 1 không đủ thì lượt 2
    nói thẳng vào mặt nó là "bạn quên hook" + đưa ví dụ đúng/sai ngay cạnh.
    Giữ nguyên chống bịa: vẫn chỉ được dùng từ trong tiêu đề gốc.
    """
    if not items:
        return
    lines_txt = []
    for k, it in enumerate(items, 1):
        lines_txt.append("%d) ORIGINAL: %s" % (k, it["title"]))
        lines_txt.append("   YOU WROTE (NOT GOOD ENOUGH): %s" % " / ".join(it["lines"]))
    prompt = (
        "You are a broadcast headline editor. Your job below was REJECTED.\n"
        "It just split the original into lines and did NOT add a hook.\n\n"
        "Rewrite each one so it MUST contain at least one hook move:\n"
        "  A. OPEN with JUST IN: / BREAKING: / NEW: / NOW:  (pick one, only if\n"
        "     the fact is really news)\n"
        "  B. OPEN LOOP - put the question or the consequence on the LAST line\n"
        "     so the viewer must read to the end\n"
        "  C. SHARP BEAT - use a colon : or a question ? to cut the rhythm\n"
        "  D. CONCRETE SHOCK - pull the sharpest number or name to line 1\n\n"
        "BAD -> GOOD:\n"
        "  BAD : TRUMP TO NAME JAY CLAYTON / AS NEW AI CZAR / REPORT SAYS\n"
        "  GOOD: JUST IN: TRUMP'S NEW / AI CZAR NAMED / WHO IS HE?\n"
        "  BAD : DOJ ARGUES CNN CAN / BE BANNED FROM / WHITE HOUSE\n"
        "  GOOD: DOJ MOVES ON CNN: / BAN FROM THE WHITE HOUSE / IF TRUMP DECIDES\n\n"
        "HARD RULES (unchanged, breaking these is worse than being boring):\n"
        f"  - at most {max_lines} lines, each at most {max_chars} chars, ALL CAPS\n"
        "  - NEVER invent facts, numbers, names or outcomes. Every FACT must come\n"
        "    from the ORIGINAL line. You may only add the hook words from A.\n"
        "  - NEVER use LEAKED / REVEALED / EXPOSED / INSIDER unless it is already\n"
        "    in the ORIGINAL.\n"
        "  - Keep the exact meaning. No source name, no time.\n\n"
        "Return JSON only: {\"tin\":[{\"stt\":N,\"dong\":[\"d1\",\"d2\",\"d3\"]}]}\n"
        "No explanation.\n\n" + "\n".join(lines_txt)
    )
    data = None
    try:
        data = _extract_json(gem.ask(prompt))
    except Exception as e:
        log(f"  ! ép hook: {e}")
    got = {}
    if data:
        for it in data.get("tin", []):
            try:
                got[int(it["stt"])] = it
            except Exception:
                pass
    for k, it in enumerate(items, 1):
        g = got.get(k) or {}
        new = [str(x).strip() for x in (g.get("dong") or []) if str(x).strip()]
        if not new:
            continue
        new = new[:max_lines]
        new = strip_source_tail(new, it.get("source", ""))
        new = _clamp_lines(new, max_lines, max_chars)
        h_new = hook_score(new)
        f_new = round(faithfulness(it["title"], new), 2)
        # chỉ nhận nếu hook TỐT HƠN, vẫn trung thực, và KHÔNG bịa số
        if (h_new > it.get("hook", 0) and f_new >= 0.85
                and not fab_numbers(it["title"], new)):
            it["lines"] = new
            it["hook"] = h_new
            it["faith"] = f_new

    # CHOT HA: van con tin hook thap (model tra ve nguyen van tieu de goc).
    # Chen ':' vao dong 1 — thuan dau cau, KHONG them chu nao -> khong the bia.
    # Do that truoc khi co buoc nay: 5/40 tin hook=0.
    for it in items:
        if it.get("hook", 0) >= HOOK_MIN or len(it.get("lines") or []) < 2:
            continue
        cur = list(it["lines"])
        head, tail = cur[0], cur[1]
        if ":" not in head and len(head) + 1 < max_chars:
            cur[0] = (head + ":").strip()
        elif "?" not in tail and len(tail) + 1 <= max_chars:
            cur[1] = (tail + "?").strip()
        else:
            continue
        h = hook_score(cur)
        if h > it.get("hook", 0):
            it["lines"] = cur
            it["hook"] = h


def _split_fallback(title: str, n: int, mx: int) -> list[str]:
    """Chia tiêu đề thành n dòng khi Gemini không trả lời được."""
    words, lines, cur = title.split(), [], ""
    target = max(8, len(title) // max(1, n))
    for w in words:
        if cur and len(cur) + 1 + len(w) > min(mx, target + 8):
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    while len(lines) > n:                      # gộp phần dư vào dòng cuối
        lines[-2] = (lines[-2] + " " + lines[-1]).strip()
        lines.pop()
    return [x.upper() for x in lines]


def _kw_fallback(title: str) -> str:
    ws = [w for w in re.findall(r"[A-Za-z0-9']+", title) if w.lower() not in STOP][:4]
    return " ".join(ws)


def build_plan(topics=None, hours: int = 24, limit: int = 8,
               use_gemini: bool = True, config_path=None,
               ai: str = "vilao", model: str = "", vilao_key: str = "",
               log=print
               ) -> tuple[list[dict], str]:
    """Toàn bộ quy trình: RSS -> AI viết lại. Trả (danh sách tin, ghi chú).

    ai: "vilao" (mặc định) | "gemini" | "auto" (thử Vilao trước, Gemini sau).
    model: tên model gõ tay cho Vilao (vd "deepseek-v4.1-flash"). Để trống thì
    dùng VILAO_MODELS (gpt-5.6-luna, dự phòng gpt-6-luna).
    vilao_key: key gõ tay trong ô GUI, ưu tiên hơn env/.env (để trống = dò như cũ).
    """
    config_path = Path(config_path) if config_path else None
    log(f"→ Lấy tin {hours}h qua: {', '.join(topics or ['Chính trị Mỹ'])}")
    # fetch_news = RSS báo trực tiếp (có link thật + ảnh) trước, Google bù sau.
    # Nhờ vậy mỗi item có "image"/"link" -> tab "Tìm ảnh theo tin" lấy được
    # ĐÚNG ảnh của bài thay vì ảnh stock chung chung.
    items = fetch_news(topics, hours=hours, per_topic=80, log=log)
    if not items:
        return [], "Không lấy được tin nào từ RSS (kiểm tra mạng)."
    log(f"  tổng {len(items)} tin trong {hours}h")

    note = "Chưa dùng AI (tiêu đề giữ nguyên từ RSS)."
    if use_gemini:
        order = {"vilao": ["vilao"], "gemini": ["gemini"],
                 "auto": ["vilao", "gemini"]}.get(ai, ["vilao"])
        errs = []
        for which in order:
            if which == "vilao":
                key, src = find_vilao_key(config_path, user_key=vilao_key)
                label, mk = "Vilao", Vilao
            else:
                key, src = find_gemini_key(config_path)
                label, mk = "Gemini", Gemini
            if not key:
                errs.append(f"{label}: không tìm thấy key")
                log(f"  ! không tìm thấy key {label}")
                continue
            # model go tay (chi Vilao): dat len dau, giu model con lai lam du phong
            if which == "vilao" and model.strip():
                mlist = [model.strip()] + [m for m in VILAO_MODELS
                                           if m != model.strip()]
                cli = mk(key, models=mlist, log=log)
            else:
                cli = mk(key, log=log)
            alive, msg = cli.ok()
            if not alive:
                errs.append(f"{label}: {msg}")
                log(f"  ! key {label} không dùng được ({msg})")
                continue
            log(f"  {label} sẵn sàng ({msg}), key từ {src}")
            try:
                items = rewrite_titles(items[:limit], cli, log=log)
            except Exception as e:
                errs.append(f"{label}: {str(e)[:60]}")
                log(f"  ! {label} lỗi khi viết lại: {e}")
                continue
            note = (f"Đã nhờ {label} viết lại {len(items)} tiêu đề "
                    f"(model {cli.last_model}).")
            log("  " + note)
            return items, note
        note = ("AI không dùng được (" + "; ".join(errs) +
                ") — giữ tiêu đề gốc từ RSS." if errs else note)
        log("  ! " + note)

    # không có AI -> tự chia dòng
    items = items[:limit]
    for it in items:
        it["lines"] = _split_fallback(it["title"], 3, 40)
        it["keyword"] = _kw_fallback(it["title"])
        it["faith"] = 1.0
    return items, note
