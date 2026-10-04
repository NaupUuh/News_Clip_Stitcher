# -*- coding: utf-8 -*-
"""Chấm điểm "độ nóng" của tin — dùng tín hiệu MIỄN PHÍ, đo được thật.

Đã đo thực tế 2026-10-03 trên máy user:
  * Google News RSS search + `when:1d` -> đếm được SỐ BÁO khác nhau đưa cùng 1 tin.
    Ví dụ đo được: "Christa Pike … botched lethal injection" -> 38 nguồn;
    "Hawaii Hōlei Sea Arch collapses" -> 20 nguồn; tin vặt -> 3-4 nguồn.
  * Google Trends daily RSS (trends.google.com/trending/rss?geo=US) -> ~10 từ khoá
    đang trending, CÓ timestamp. Lấy được, không cần key.
  * Reddit / Bluesky / YouTube engagement API: **403/404/500 — KHÔNG dùng được.**

CẢNH BÁO TRUNG THỰC — module này KHÔNG dự đoán viral:
  * Chỉ đo MỨC ĐỘ BÁO CHÍ ĐƯA TIN (newsroom attention), không đo người xem.
  * Không có view/watch-time/share thật -> không thể học được cái gì viral.
  * Trần chính trị trên Facebook: Meta hạ recommend video chính trị với người
    chưa follow -> trần viral thấp bất kể tin nóng cỡ nào.
  Nói với user: điểm cao = "đáng làm", KHÔNG PHẢI "sẽ viral".
"""
from __future__ import annotations

import html
import re
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# Từ dừng: bỏ khi rút từ khoá truy vấn
_STOP = {
    "the", "a", "an", "of", "in", "to", "for", "on", "and", "with", "as", "at",
    "by", "from", "is", "are", "was", "were", "be", "been", "his", "her", "its",
    "that", "this", "after", "over", "into", "amid", "says", "said", "will",
    "would", "could", "has", "have", "had", "not", "but", "who", "why", "how",
    "new", "out", "off", "up", "down", "amid", "than", "then", "they", "their",
    "its", "it's", "he", "she", "we", "you", "i", "my", "our",
}


def _get(url: str, timeout: int = 20) -> str | None:
    """GET 1 URL, trả text hoặc None (mọi lỗi đều nuốt — không làm sập tool)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except Exception:
        return None


def _key_terms(title: str, n: int = 4) -> list[str]:
    """Rút n từ khoá hiếm nhất của tiêu đề để truy vấn (bỏ từ dừng).

    Giữ số/viết hoa vì chúng phân biệt tin: 'Pike', 'Hōlei', '500'.
    """
    words = re.findall(r"[A-Za-z0-9\u00C0-\u024F']{3,}", title)
    keep = [w for w in words if w.lower() not in _STOP]
    return keep[:n]


def _overlap(title: str, other: str, k: int = 2) -> bool:
    """True nếu 2 tiêu đề chia sẻ >= k từ khoá (đủ để coi là CÙNG tin)."""
    a = {w.lower() for w in re.findall(r"[A-Za-z0-9\u00C0-\u024F']{3,}", title)
         if w.lower() not in _STOP}
    b = {w.lower() for w in re.findall(r"[A-Za-z0-9\u00C0-\u024F']{3,}", other)
         if w.lower() not in _STOP}
    return len(a & b) >= k


# ── Tín hiệu 1: độ phủ báo chí ─────────────────────────────────────────────
def press_coverage(title: str, when: str = "1d", timeout: int = 20) -> dict:
    """Đếm số BÁO khác nhau đưa cùng tin này trong `when` (mặc định 24h).

    Trả {"sources": int, "items": int, "q": str}. Lỗi mạng -> sources 0.

    Cách làm: rút 4 từ khoá -> tìm trên Google News RSS -> đếm `source` DUY NHẤT,
    nhưng chỉ tính item thật sự TRÙNG TIN (>=2 từ khoá chung), vì truy vấn rộng
    hay kéo về bài lạc đề (đã gặp: tin Sea Arch kéo theo 1 bài về Meghan Markle).
    """
    terms = _key_terms(title, 4)
    if not terms:
        return {"sources": 0, "items": 0, "q": ""}
    q = " ".join(terms)
    url = ("https://news.google.com/rss/search?q="
           + urllib.parse.quote("%s when:%s" % (q, when))
           + "&hl=en-US&gl=US&ceid=US:en")
    xml = _get(url, timeout=timeout)
    if not xml:
        return {"sources": 0, "items": 0, "q": q}
    items = re.findall(r"<item>(.*?)</item>", xml, re.S)
    srcs, n_ok = set(), 0
    for it in items:
        tm = re.search(r"<title>(.*?)</title>", it, re.S)
        sm = re.search(r"<source[^>]*>(.*?)</source>", it, re.S)
        if not tm:
            continue
        t = html.unescape(tm.group(1)).strip()
        # bỏ đuôi " - Tên báo" mà Google gắn thêm
        t = re.sub(r"\s+-\s+[^-]{2,42}$", "", t).strip()
        if not _overlap(title, t, 2):
            continue
        n_ok += 1
        if sm:
            srcs.add(html.unescape(sm.group(1)).strip())
    return {"sources": len(srcs), "items": n_ok, "q": q}


# ── Tín hiệu 2: Google Trends daily ────────────────────────────────────────
def trends_today(geo: str = "US", timeout: int = 20) -> set[str]:
    """Từ khoá đang trending hôm nay (Google Trends daily RSS). Rỗng nếu lỗi."""
    xml = _get("https://trends.google.com/trending/rss?geo=%s" % geo, timeout=timeout)
    if not xml:
        return set()
    out = set()
    for it in re.findall(r"<item>(.*?)</item>", xml, re.S):
        tm = re.search(r"<title>(.*?)</title>", it, re.S)
        if tm:
            out.add(html.unescape(tm.group(1)).strip().lower())
    return out


def in_trends(title: str, trends: set[str]) -> bool:
    """True nếu có từ khoá (>=4 ký tự) của tiêu đề nằm trong trends hôm nay."""
    if not trends:
        return False
    words = {w.lower() for w in re.findall(r"[A-Za-z0-9\u00C0-\u024F]{4,}", title)
             if w.lower() not in _STOP}
    for t in trends:
        tw = {w for w in re.findall(r"[A-Za-z0-9\u00C0-\u024F]{4,}", t)
              if w not in _STOP}
        if tw and words & tw:
            return True
    return False


# ── Chấm điểm ──────────────────────────────────────────────────────────────
def score_items(items: list[dict], log=print, workers: int = 6,
                top_n: int | None = None) -> list[dict]:
    """Thêm `coverage`, `sources`, `trending`, `hot` vào từng tin; xếp lại.

    Điểm `hot` (0..100) = 70% độ phủ nguồn + 20% có trên Trends + 10% độ mới.
    Chỉ chấm `top_n` tin đầu (mặc định: tất cả) để không spam Google.
    Trả list ĐÃ SẮP theo `hot` giảm dần.
    """
    if not items:
        return items
    targets = items[:top_n] if top_n else items
    log("→ Đang chấm điểm %d tin (đếm số báo đưa tin + Google Trends)..." % len(targets))

    trends = trends_today()
    log("  Google Trends US hôm nay: %d từ khoá%s"
        % (len(trends), "" if trends else " (không lấy được)"))

    def job(it):
        try:
            cv = press_coverage(it["title"])
        except Exception:
            cv = {"sources": 0, "items": 0, "q": ""}
        return cv

    with ThreadPoolExecutor(max_workers=workers) as ex:
        cvs = list(ex.map(job, targets))

    for it, cv in zip(targets, cvs):
        it["sources"] = cv["sources"]
        it["coverage"] = cv["items"]
        it["trending"] = in_trends(it["title"], trends)
        it["hot"] = hot_score(it)

    rest = items[len(targets):]
    for it in rest:
        it.setdefault("sources", 0)
        it.setdefault("coverage", 0)
        it.setdefault("trending", False)
        it["hot"] = hot_score(it)

    targets.sort(key=lambda x: -x["hot"])
    rest.sort(key=lambda x: -x["hot"])
    out = targets + rest
    if targets:
        log("  xong. Dẫn đầu: %d nguồn | %s"
            % (targets[0]["sources"], targets[0]["title"][:64]))
    return out


def hot_score(it: dict) -> float:
    """Điểm 0..100. Xem docstring `score_items` để biết trọng số."""
    src = float(it.get("sources") or 0)
    # 0 nguồn -> 0 điểm; 40+ nguồn -> 70 điểm (bão hoà)
    s_cov = 70.0 * min(1.0, src / 40.0)
    s_trend = 20.0 if it.get("trending") else 0.0
    age = it.get("age_h")
    try:
        age = float(age) if age is not None else 24.0
    except Exception:
        age = 24.0
    s_fresh = 10.0 * max(0.0, 1.0 - age / 24.0)
    return round(s_cov + s_trend + s_fresh, 1)


def hot_label(it: dict) -> str:
    """Nhãn ngắn để hiện trong GUI: '🔥 38 nguồn · Trends'."""
    parts = []
    s = int(it.get("sources") or 0)
    if s:
        parts.append("%d nguồn" % s)
    if it.get("trending"):
        parts.append("Trends")
    return ("🔥 " + " · ".join(parts)) if parts else ""


def why(it: dict) -> str:
    """Giải thích điểm cho user — KHÔNG hứa viral."""
    s = int(it.get("sources") or 0)
    bits = []
    if s >= 25:
        bits.append("rất nhiều báo đưa (%d nguồn)" % s)
    elif s >= 10:
        bits.append("nhiều báo đưa (%d nguồn)" % s)
    elif s >= 4:
        bits.append("%d nguồn đưa" % s)
    else:
        bits.append("ít báo đưa (%d nguồn)" % s)
    if it.get("trending"):
        bits.append("đang trending Google US")
    age = it.get("age_h")
    if age is not None and float(age) <= 3:
        bits.append("mới đăng %.1fh" % float(age))
    return " · ".join(bits)
