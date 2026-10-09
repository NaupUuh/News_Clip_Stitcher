"""
Tìm + tải ảnh stock theo từ khoá tin — KHÔNG cần API key.

Nguồn (đều miễn phí, không cần đăng ký):
  - Wikimedia Commons : ảnh chính phủ Mỹ (PD-USGov) — hợp tin chính trị nhất,
                        ví dụ "Donald Trump official portrait" là ảnh Công.
  - Openverse         : gom Flickr / Wikimedia / museums... (mặc định TẮT, xem
                        SOURCES: ảnh Flickr chỉ 500-1024px, crop dọc là mờ).

QUAN TRỌNG — ảnh phải đủ TO. Video là khung dọc 9:16 và ảnh bị cover-crop
(cắt 2 bên): ảnh 1920x1080 chỉ còn 607px bề ngang rồi bị phóng 1.8x = mờ.
Vì vậy lọc theo `_eff_w()` chứ không theo bề ngang ảnh gốc.

Vì sao không dùng Pexels: Pexels bắt buộc API key + giới hạn 200 req/giờ.
2 nguồn trên chạy được ngay, không cần anh xin key.

GIẤY PHÉP: mặc định chỉ lấy ảnh dùng thương mại được (CC0 / Public Domain /
CC-BY). CC-BY cần ghi tên tác giả — mỗi ảnh tải về đều kèm 1 dòng credit trong
`credits.txt` cạnh ảnh, để anh dán vào phần mô tả nếu cần.
"""
import base64
import html as html_mod
import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

__all__ = ["SOURCES", "search", "search_openverse", "search_wikimedia",
           "download", "find_for_keywords", "find_for_articles",
           "resolve_gnews", "article_images", "safe_name", "IMG_EXT"]

UA = ("NewsClipStitcher/1.24 (Windows; tin tuc 9:16; "
      "+https://github.com/NaupUuh/News_Clip_Stitcher)")

IMG_EXT = (".jpg", ".jpeg", ".png", ".webp")
# Mặc định CHỈ Wikimedia. Openverse (chủ yếu Flickr cũ) trả ảnh 500-1024px;
# cover-crop vào khung 9:16 chỉ còn dưới 600px bề ngang -> phóng >1.8x = mờ,
# không dùng được cho video dọc. Code openverse vẫn giữ để bật lại khi cần
# (SOURCES = ("wikimedia", "openverse")) nhưng không bật mặc định.
SOURCES = ("wikimedia",)

# Ảnh được COVER-CROP vào khung 9:16 (xem stitcher._prepare_image): ảnh ngang
# bị cắt 2 bên nên bề ngang thật chỉ còn ~ h*9/16. Vì vậy phải xin bản to:
# ảnh 1024px sau khi cắt chỉ còn 576px -> phóng to 1.9x là mờ.
THUMB_W = 2400

# Giấy phép cho phép dùng thương mại. by-sa bị loại vì share-alike sẽ buộc
# cả video phải theo CC-BY-SA — rủi ro cho kênh kiếm tiền. nd (no-deriv) cũng
# loại: video tin tức luôn crop/zoom ảnh = tạo tác phẩm phái sinh.
OK_LICENSES = {"cc0", "pdm", "public domain", "cc-by", "by", "pd"}
BAD_LICENSES = ("sa", "nd", "nc", "gfdl", "fair use", "non-commercial")


def _lic_ok(lic: str) -> bool:
    """True nếu giấy phép dùng thương mại + cắt ghép được.

    Lọc theo CẢ chuỗi hiển thị ('CC BY-SA 4.0') lẫn mã ('by'): Wikimedia trả
    tên đầy đủ còn Openverse trả mã ngắn, nên phải chặn ở cả 2 dạng.
    """
    # '_' -> ' ' để "cc_by" (Openverse) và "CC BY 2.0" (Wikimedia) cùng khớp.
    s = str(lic or "").strip().lower().replace("_", " ")
    if not s:
        return True                      # thiếu thông tin -> để người dùng xem
    if any(b in s for b in BAD_LICENSES):
        return False
    if "by" in s and "sa" not in s and "nd" not in s:
        return True
    if any(k in s for k in ("cc0", "pdm", "public domain", "pd-", "cc-by")):
        return True
    return any(p in f" {s} " for p in (" by ", " pd "))


def _aspect_ok(w: int, h: int, max_ratio: float = 2.6) -> bool:
    """Loại ảnh quá dài/dẹt — crop vào khung 9:16 sẽ mất gần hết ảnh.

    2.6 là mức đo thật: ảnh 1920x633 (tỉ lệ 3.0) khi cắt vào khung dọc chỉ
    còn 356/1920 px bề ngang — mất 81% ảnh. 16:9 (1.78) và ảnh vuông vẫn qua.
    """
    if not w or not h:
        return True
    r = max(w / h, h / w)
    return r <= max_ratio


def _eff_w(w: int, h: int, out_ratio: float = 9.0 / 16.0) -> int:
    """Bề ngang CÒN LẠI sau khi cover-crop vào khung dọc 9:16.

    Đây mới là con số quyết định ảnh có nét hay không: ảnh 1920x1080 chỉ còn
    607px bề ngang -> phóng 1.78x = mờ, dù ảnh gốc "1920px" nghe to.
    """
    if not w or not h:
        return 0
    return int(h * out_ratio) if (w / h) > out_ratio else w

_CTX = ssl.create_default_context()


def _get(url: str, timeout: int = 25):
    """GET -> JSON. Lỗi mạng/JSON trả None (không ném ra ngoài)."""
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/json",
    })
    try:
        with _open_req(req, timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return None


def _open_req(req, timeout: int = 25, tries: int = 3):
    """urlopen + TỰ THỬ LẠI khi bị chặn tạm thời (429/5xx).

    Wikimedia chặn 429 khi gọi dồn dập — gặp là mất ảnh luôn, mà triệu chứng
    lại giống hệt "không có kết quả" nên rất khó lần ra. Chờ theo Retry-After,
    không có thì 2s/4s.
    """
    last = None
    for i in range(tries):
        try:
            return urllib.request.urlopen(req, timeout=timeout, context=_CTX)
        except urllib.error.HTTPError as e:
            last = e
            if e.code not in (429, 500, 502, 503, 504):
                raise
            try:
                wait = float(e.headers.get("Retry-After") or 0)
            except Exception:
                wait = 0
            if i < tries - 1:
                time.sleep(min(wait, 15) if wait > 0 else 2.0 * (i + 1))
        except Exception as e:
            last = e
            if i >= tries - 1:
                raise
            time.sleep(1.5 * (i + 1))
    raise last if last else RuntimeError("không mở được")


def safe_name(s: str, maxlen: int = 60) -> str:
    """Đổi tiêu đề ảnh thành tên file an toàn trên Windows."""
    s = re.sub(r"[^\w\s\-]", "", str(s or ""), flags=re.UNICODE)
    s = re.sub(r"\s+", "_", s.strip())
    return (s[:maxlen].strip("_") or "image")


# ─────────────────────────── Wikimedia Commons ───────────────────────────
def search_wikimedia(query: str, n: int = 8, min_w: int = 800,
                     timeout: int = 25, min_eff: int = 700) -> list[dict]:
    """Ảnh trên Wikimedia Commons. Nhiều ảnh chính phủ Mỹ = Public Domain.

    `url` trả về là bản thu nhỏ 1600px (không phải file gốc): file gốc hay
    10-20MB, tải rất chậm mà ảnh chỉ dùng ở 1080x1920.
    """
    u = ("https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "query", "format": "json",
        "generator": "search", "gsrsearch": query, "gsrnamespace": 6,
        "gsrlimit": max(1, min(50, n * 3)),
        "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata",
        "iiurlwidth": THUMB_W,
    }))
    js = _get(u, timeout)
    pages = ((js or {}).get("query") or {}).get("pages") or {}
    out = []
    for p in pages.values():
        ii = (p.get("imageinfo") or [{}])[0]
        if not ii:
            continue
        mime = str(ii.get("mime") or "")
        if mime not in ("image/jpeg", "image/png", "image/webp"):
            continue
        w, h = int(ii.get("width") or 0), int(ii.get("height") or 0)
        if w < min_w or h < min_w // 2 or not _aspect_ok(w, h):
            continue
        if _eff_w(w, h) < min_eff:
            continue
        em = ii.get("extmetadata") or {}

        def _v(k):
            return str((em.get(k) or {}).get("value") or "")

        lic = _v("LicenseShortName") or _v("License")
        if not _lic_ok(lic):
            continue
        artist = re.sub(r"<[^>]+>", "", _v("Artist")).strip()
        out.append({
            "url": ii.get("thumburl") or ii.get("url") or "",
            "thumb": ii.get("thumburl") or ii.get("url") or "",
            "title": p.get("title", "").replace("File:", ""),
            "creator": artist,
            "license": lic,
            "license_url": _v("LicenseUrl"),
            "source": "Wikimedia",
            "page": "https://commons.wikimedia.org/wiki/" +
                    urllib.parse.quote(str(p.get("title") or "").replace(" ", "_")),
            "w": w, "h": h,
        })
    return out[:n]


# ───────────────────────────── Openverse ─────────────────────────────
def search_openverse(query: str, n: int = 8, min_w: int = 800,
                     timeout: int = 25, min_eff: int = 700) -> list[dict]:
    """Openverse (WordPress). Lọc sẵn theo giấy phép dùng thương mại được."""
    u = "https://api.openverse.org/v1/images/?" + urllib.parse.urlencode({
        "q": query, "page_size": max(1, min(50, n * 2)),
        "license_type": "commercial",
        "mature": "false",
    })
    js = _get(u, timeout)
    out = []
    for r in ((js or {}).get("results") or []):
        w, h = int(r.get("width") or 0), int(r.get("height") or 0)
        if w and w < min_w:
            continue
        if not _aspect_ok(w, h):
            continue
        # Openverse hay THIẾU width/height. Thiếu thì KHÔNG loại ở đây (tải về
        # kiểm sau) — nếu loại thì mất sạch kết quả, như đã từng xảy ra.
        if w and h and _eff_w(w, h) < min_eff:
            continue
        if not _lic_ok(r.get("license")):
            continue
        url = r.get("url") or ""
        if not url:
            continue
        # Openverse `thumbnail` chỉ 640px -> KHÔNG dùng. url là bản gốc, to hơn
        # hẳn; `thumb` để trống nên download() đi thẳng vào url.
        out.append({
            "url": url,
            "thumb": "",
            "title": r.get("title") or "",
            "creator": r.get("creator") or "",
            "license": (str(r.get("license") or "").upper() +
                        (" " + str(r.get("license_version") or "")).strip()).strip(),
            "license_url": r.get("license_url") or "",
            "source": "Openverse/" + str(r.get("source") or ""),
            "page": r.get("foreign_landing_url") or "",
            "w": w, "h": h,
        })
    return out[:n]


# ─────────────── ảnh ĐÚNG TIN: lấy từ chính bài báo nguồn ───────────────
# Vì sao cần: ảnh stock (Wikimedia) chỉ đúng CHỦ ĐỀ, không đúng TIN. Tin
# "Trump họp báo ở Nhà Trắng hôm nay" mà ảnh lại là chân dung Trump 2017 —
# người xem thấy sai ngay. Ảnh trên chính bài báo thì đúng người/đúng việc/
# đúng thời điểm.
#
# Luồng: link Google News -> (giải mã) -> link bài thật -> og:image.
#
# CẢNH BÁO CHẤT LƯỢNG: og:image của báo gần như luôn là ảnh NGANG (1200x630,
# 1920x1080). Cover-crop vào khung dọc 9:16 chỉ còn 354-607px bề ngang ->
# phóng 1.8-3.0x = MỜ. Muốn nét phải để ảnh VỪA KHUNG + NỀN MỜ (stitcher
# `img_fit="blur"`): ảnh 1200x630 hiện ở 1080x567 = thu nhỏ 0.9x -> nét.
# Đó là lý do stitcher có thêm chế độ fit "blur".

# Header Chrome ĐẦY ĐỦ. Nhiều báo (NYT, AP) chặn 403 nếu thiếu sec-ch-ua /
# Sec-Fetch-*; chỉ có User-Agent là KHÔNG đủ (đã thử: 403 với UA thường,
# 200 với bộ header này).
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
BROWSER_HDR = {
    "User-Agent": BROWSER_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


def _get_html(url: str, timeout: int = 25) -> str:
    """GET 1 trang HTML bằng header Chrome đầy đủ. Lỗi -> ''."""
    req = urllib.request.Request(url, headers=BROWSER_HDR)
    with _open_req(req, timeout) as r:
        return r.read(1_500_000).decode("utf-8", "replace")


def resolve_gnews(url: str, timeout: int = 25) -> str:
    """Link Google News -> link bài báo THẬT. Trả '' nếu không giải được.

    Google News không đưa link báo trực tiếp mà bọc qua /rss/articles/<id>.
    Có 2 đời id:
      1. Kiểu CŨ — URL báo nằm ngay trong chuỗi base64, giải tại chỗ, không
         cần mạng.
      2. Kiểu MỚI — id là protobuf, phải gọi batchexecute kèm 2 tham số
         `data-n-a-sg` (chữ ký) + `data-n-a-ts` (thời điểm) lấy từ chính
         trang đó. Thiếu 2 tham số này thì Google trả lỗi.
    """
    if not url:
        return ""
    if "news.google.com" not in url:
        return url                      # đã là link báo thật
    m = re.search(r"/articles/([A-Za-z0-9_\-]+)", url)
    if not m:
        return ""
    cid = m.group(1)

    # (1) kiểu cũ — giải base64
    try:
        raw = base64.urlsafe_b64decode(cid + "=" * (-len(cid) % 4))
        mm = re.search(rb"https?://[^\x00-\x20\"'<>\\]+", raw)
        if mm:
            u = mm.group(0).decode("utf-8", "replace")
            if "news.google.com" not in u:
                return u
    except Exception:
        pass

    # (2) kiểu mới — batchexecute
    try:
        page = _get_html(f"https://news.google.com/rss/articles/{cid}", timeout)
        sg = re.search(r'data-n-a-sg="([^"]+)"', page)
        ts = re.search(r'data-n-a-ts="([^"]+)"', page)
        if not (sg and ts):
            return ""
        inner = ('["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",'
                 'null,1,null,null,null,null,null,0,1],"X","X",1,[1,1,1],1,1,'
                 'null,0,0,null,0],"%s",%s,"%s"]'
                 % (cid, ts.group(1), sg.group(1)))
        body = "f.req=" + urllib.parse.quote(json.dumps([["Fbv4je", inner]]))
        req = urllib.request.Request(
            "https://news.google.com/_/DotsSplashUi/data/batchexecute",
            data=body.encode(),
            headers={**BROWSER_HDR,
                     "Content-Type":
                         "application/x-www-form-urlencoded;charset=UTF-8",
                     "Sec-Fetch-Site": "same-origin"})
        with _open_req(req, timeout) as r:
            txt = r.read().decode("utf-8", "replace")
        arr = json.loads(txt.split("\n\n")[1])
        payload = json.loads(arr[0][2])
        out = payload[1] if isinstance(payload, list) and len(payload) > 1 else ""
        return out if isinstance(out, str) and out.startswith("http") else ""
    except Exception:
        return ""


def _img_from_srcset(v: str):
    """Lấy URL to nhất trong 1 thuộc tính srcset."""
    best, best_w = None, -1
    for part in (v or "").split(","):
        bits = part.strip().split()
        if not bits:
            continue
        w = 0
        if len(bits) > 1 and bits[1].endswith("w"):
            try:
                w = int(bits[1][:-1])
            except ValueError:
                w = 0
        if w > best_w:
            best, best_w = bits[0], w
    return best


def article_images(url: str, timeout: int = 25) -> list[str]:
    """Danh sách ảnh của 1 bài báo, ảnh chính trước.

    Thứ tự: og:image -> twitter:image -> ảnh lớn nhất trong bài. Trả [] nếu
    không lấy được trang hoặc bài không có ảnh.
    """
    try:
        page = _get_html(url, timeout)
    except Exception:
        return []
    if not page:
        return []
    out = []
    # 1. og:image (chuẩn phổ biến nhất, luôn là ảnh đại diện bài)
    for pat in (r'<meta[^>]+(?:property|name)=["\']og:image(?::url)?["\'][^>]+content=["\']([^"\']+)',
                r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']og:image(?::url)?["\']'):
        m = re.search(pat, page, re.I)
        if m:
            out.append(html_mod.unescape(m.group(1).strip()))
            break
    # 2. twitter:image (nhiều báo khai khác og:image)
    for pat in (r'<meta[^>]+(?:property|name)=["\']twitter:image["\'][^>]+content=["\']([^"\']+)',
                r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']twitter:image["\']'):
        m = re.search(pat, page, re.I)
        if m:
            out.append(html_mod.unescape(m.group(1).strip()))
            break
    # 3. ảnh lớn nhất trong bài — chỉ lấy khi có srcset/data-src rõ ràng, vì
    #    <img> trong bài hay là icon/lazy-placeholder 1px.
    cands = []
    for m in re.finditer(r"<img\b[^>]*>", page, re.I):
        tag = m.group(0)
        u = None
        sm = re.search(r'\bsrcset=["\']([^"\']+)', tag, re.I)
        if sm:
            u = _img_from_srcset(sm.group(1))
        if not u:
            for a in ("data-src", "data-original", "data-lazy-src", "src"):
                am = re.search(r'\b%s=["\']([^"\']+)' % a, tag, re.I)
                if am and not am.group(1).startswith("data:"):
                    u = am.group(1)
                    break
        if not u:
            continue
        if re.search(r"(sprite|logo|icon|avatar|placeholder|blank|1x1|pixel)",
                     u, re.I):
            continue
        cands.append(u)
    for u in cands:
        if len(out) >= 4:
            break
        out.append(u)

    # chuẩn hoá + bỏ trùng, giữ thứ tự
    seen, fin = set(), []
    for u in out:
        u = (u or "").strip()
        if u.startswith("//"):
            u = "https:" + u
        elif u.startswith("/"):
            try:
                p = urllib.parse.urlsplit(url)
                u = "%s://%s%s" % (p.scheme, p.netloc, u)
            except Exception:
                continue
        if not u.startswith("http"):
            continue
        k = u.split("?")[0]
        if k in seen:
            continue
        seen.add(k)
        fin.append(u)
    return fin


def article_image(url: str, timeout: int = 25):
    """Ảnh đại diện của 1 bài báo. Trả (url_ảnh, lỗi)."""
    imgs = article_images(url, timeout)
    if imgs:
        return imgs[0], None
    return None, "bài không lấy được ảnh"


def find_for_articles(items, out_dir, per_article: int = 1, log=print,
                      min_w: int = 1200, max_mb: float = 20.0) -> list[dict]:
    """Với mỗi tin: lấy ảnh từ CHÍNH bài báo của tin đó.

    `items` = list dict có 'link' (link Google News hoặc link báo thật) và
    'title'. Trả list {keyword, file, title, creator, license, source, page}
    — CÙNG dạng với find_for_keywords để GUI dùng chung 1 đường.

    `min_w` = BỀ NGANG tối thiểu (không phải cạnh nhỏ nhất): ảnh báo là ảnh
    ngang 1200x630, min(w,h)=630 nhưng bề ngang mới quyết định độ nét khi
    dựng khung dọc. 1200 là mức thấp nhất còn dùng được (hiện ở 1080x567 =
    thu nhỏ 0.9x -> nét). Chất lượng cuối do `img_fit` quyết định ở khâu
    render (xem stitcher._prepare_image).

    Thứ tự ưu tiên ảnh của mỗi tin:
      1. `it["image"]` — ảnh có SẴN trong RSS báo (nhanh, không bị 403).
      2. og:image của bài — dùng khi (1) thiếu hoặc quá nhỏ.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    done, lines, used = [], [], set()
    per_article = max(1, min(4, int(per_article or 1)))
    for it in items or []:
        title = str(it.get("title") or "").strip()
        link = str(it.get("link") or "").strip()
        src = str(it.get("source") or "").strip()
        if not link:
            log("  ! tin không có link — bỏ qua")
            continue
        log(f"📰 {src or '?'} — {title[:60]}")
        real = resolve_gnews(link)
        # Tin lấy từ RSS báo trực tiếp đã có SẴN ảnh của bài ("image") — dùng
        # luôn, khỏi tải lại trang (nhanh hơn + không bị 403 như NYT/AP).
        urls = []
        if it.get("image"):
            urls.append(str(it["image"]))
        if not urls and real:
            urls = article_images(real)
        if not urls:
            log("    ! bài không lấy được ảnh")
            continue
        n_ok, n_err, small = 0, 0, False
        for u in urls:
            if n_ok >= per_article:
                break
            key = u.split("?")[0]
            if key in used:
                continue
            name = f"{safe_name(src or 'bao')}_{safe_name(title)[:30]}"
            p, err = download(u, out_dir, name=name, max_mb=max_mb,
                              min_side=0, min_w=min_w, target_w=0)
            if err:
                if n_err < 2:
                    log(f"    ! bỏ qua ảnh: {err}")
                n_err += 1
                if "bề ngang nhỏ" in err or "ảnh nhỏ" in err:
                    small = True
                continue
            n_ok += 1
            used.add(key)
            done.append({"keyword": title, "file": str(p),
                         "title": f"{src} — {title}"[:90],
                         "creator": src, "license": "ảnh bài báo (dùng nội bộ)",
                         "source": src, "page": real or link})
            lines.append("%s | %s | %s" % (p.name, src or "?", real))
        # Ảnh trong RSS quá nhỏ (Guardian chỉ phát 700px) -> thử og:image
        # của chính bài, thường là bản 1200x630.
        if not n_ok and small and real:
            for u in article_images(real):
                key = u.split("?")[0]
                if key in used:
                    continue
                name = f"{safe_name(src or 'bao')}_{safe_name(title)[:30]}"
                p, err = download(u, out_dir, name=name, max_mb=max_mb,
                                  min_side=0, min_w=min_w, target_w=0)
                if err:
                    if n_err < 3:
                        log(f"    ! og:image bỏ qua: {err}")
                    n_err += 1
                    continue
                n_ok += 1
                used.add(key)
                done.append({"keyword": title, "file": str(p),
                             "title": f"{src} — {title}"[:90],
                             "creator": src,
                             "license": "ảnh bài báo (dùng nội bộ)",
                             "source": src, "page": real or link})
                lines.append("%s | %s | %s" % (p.name, src or "?", real or link))
                break
        log(f"  → {n_ok} ảnh")
        if not n_ok:
            log("  ! không tải được ảnh nào cho tin này")
    if lines:
        try:
            f = out_dir / "credits.txt"
            old = f.read_text(encoding="utf-8") if f.exists() else ""
            f.write_text((old + "\n".join(lines) + "\n").lstrip("\n"),
                         encoding="utf-8")
        except Exception:
            pass
    return done


# ───────────────────────────── gộp 2 nguồn ─────────────────────────────
def search(query: str, n: int = 8, sources=SOURCES, min_w: int = 800,
           log=print, pause: float = 0.0) -> list[dict]:
    """Tìm ở nhiều nguồn, gộp + bỏ trùng theo URL. Ưu tiên Wikimedia trước
    (ảnh chính phủ Mỹ PD nhiều, tỉ lệ dùng được cao hơn cho tin chính trị)."""
    got, seen = [], set()
    for src in sources:
        fn = {"wikimedia": search_wikimedia, "openverse": search_openverse}.get(src)
        if not fn:
            continue
        try:
            res = fn(query, n, min_w=min_w)
        except Exception as e:
            log(f"  ! {src} lỗi: {e}")
            res = []
        if not res:
            log(f"  · {src}: 0 ảnh")
        for r in res:
            key = (r.get("url") or "").split("?")[0]
            if not key or key in seen:
                continue
            seen.add(key)
            got.append(r)
        if pause:
            time.sleep(pause)
    return got[:n]


# ───────────────────────────── tải về ─────────────────────────────
def download(url: str, dest_dir, name: str | None = None,
             max_mb: float = 15.0, min_side: int = 500,
             timeout: int = 40, thumb: str | None = None,
             target_w: int = 1600, min_w: int = 0):
    """Tải 1 ảnh về dest_dir. Trả (path, lỗi).

    Kiểm tra thật bằng Pillow: file hỏng / quá nhỏ / không phải ảnh -> xoá,
    trả lỗi. Không bao giờ để file rác 0 byte nằm lại trong folder output.

    `thumb` = bản thu nhỏ (nếu nguồn có). Luôn thử bản thu nhỏ trước cho
    nhanh; nếu nó lỗi mới quay về file gốc. Video chỉ 1080x1920 nên file gốc
    20MB là phí.
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    # bản thu nhỏ trước, file gốc sau — bỏ qua nếu trùng nhau
    cands = []
    for u in (thumb, url):
        if u and u not in cands:
            cands.append(u)

    data, err, used = None, None, url
    for i, u in enumerate(cands):
        try:
            req = urllib.request.Request(u, headers={"User-Agent": UA})
            with _open_req(req, timeout) as r:
                buf = r.read(int(max_mb * 1024 * 1024) + 1)
            if len(buf) > max_mb * 1024 * 1024:
                err = f"ảnh > {max_mb:.0f}MB"
                continue
            if len(buf) < 4096:
                err = "file quá nhỏ"
                continue
            data, err, used = buf, None, u
            break
        except Exception as e:
            err = f"tải lỗi: {type(e).__name__}"
    if data is None:
        return None, err or "tải lỗi"

    ext = ".jpg"
    m = re.search(r"\.(jpe?g|png|webp)(?:$|\?)", used, re.I)
    if m:
        ext = "." + m.group(1).lower().replace("jpeg", "jpg")
    if name is None:
        name = re.sub(r"\W+", "", used.split("?")[0].rsplit("/", 1)[-1])[:40] or "img"
    path = dest_dir / (safe_name(name) + ext)

    i = 2
    while path.exists():
        path = dest_dir / f"{safe_name(name)}_{i}{ext}"
        i += 1

    try:
        path.write_bytes(data)
    except Exception as e:
        return None, f"ghi lỗi: {e}"

    # kiểm tra ảnh thật — file hỏng thì xoá luôn
    try:
        from PIL import Image
        # Ảnh Wikimedia có cái 100MP+. Bỏ chặn bomb để .verify() không ném
        # DecompressionBombError (đã tự giới hạn 15MB ở trên rồi).
        Image.MAX_IMAGE_PIXELS = None
        with Image.open(path) as im:
            im.verify()
        with Image.open(path) as im:
            w, h = im.size
        if min(w, h) < min_side:
            path.unlink(missing_ok=True)
            return None, f"ảnh nhỏ {w}x{h}"
        # `min_w` lọc theo BỀ NGANG (ảnh BÁO là ảnh ngang: 1200x630 có
        # min(w,h)=630 nhưng bề ngang 1200 mới là thứ quyết định độ nét khi
        # dựng khung dọc). Đừng dùng min_side cho ảnh báo -> loại oan.
        if min_w and w < min_w:
            path.unlink(missing_ok=True)
            return None, f"bề ngang nhỏ {w}px"
        # bản thu nhỏ nhỏ hơn mong đợi -> thử lại bằng file gốc
        if target_w and w < target_w and used != url and url:
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass
            return download(url, dest_dir, name=name, max_mb=max_mb,
                            min_side=min_side, timeout=timeout,
                            thumb=None, target_w=0, min_w=min_w)
    except Exception as e:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
        return None, f"ảnh hỏng: {type(e).__name__}"
    return path, None


def find_for_keywords(keywords: list[str], out_dir, per_kw: int = 3,
                      sources=SOURCES, log=print,
                      min_w: int = 1200) -> list[dict]:
    """Với mỗi từ khoá: tìm + tải `per_kw` ảnh vào out_dir.

    Trả list {keyword, file, title, creator, license, source, page}.
    Ghi kèm `credits.txt` trong out_dir để còn biết nguồn ảnh.

    Ảnh đã tải cho từ khoá trước sẽ bị loại khỏi từ khoá sau — 2 tin khác nhau
    hay ra cùng 1 ảnh (Wikimedia xếp hạng giống nhau), để nguyên thì video sẽ
    lặp ảnh.

    `min_w` = bề ngang tối thiểu của ẢNH GỐC. 1200 vì ảnh còn bị crop vào
    khung dọc: ảnh 1200x800 sau crop còn ~450x800 -> phóng 1.35x, còn nét.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    done, lines, used = [], [], set()
    for kw in keywords:
        kw = (kw or "").strip()
        if not kw:
            continue
        log(f"🔎 {kw}")
        res = search(kw, n=max(per_kw * 4, 10), sources=sources, log=log,
                     min_w=min_w)
        n_ok = 0
        n_err = 0
        for r in res:
            if n_ok >= per_kw:
                break
            key = (r.get("url") or "").split("?")[0]
            if key in used:
                continue
            name = f"{safe_name(kw)}_{n_ok + 1}_{safe_name(r.get('title') or '')[:28]}"
            p, err = download(r["url"], out_dir, name=name, thumb=r.get("thumb"))
            if err:
                # KHÔNG im lặng: trước đây lỗi tải bị bỏ qua nên người dùng chỉ
                # thấy "0 ảnh" mà không biết vì sao (429 / ảnh nhỏ / quá nặng).
                if n_err < 2:
                    log(f"    ! bỏ qua ảnh: {err}")
                n_err += 1
                continue
            n_ok += 1
            used.add(key)
            done.append({"keyword": kw, "file": str(p), "title": r.get("title"),
                         "creator": r.get("creator"), "license": r.get("license"),
                         "source": r.get("source"), "page": r.get("page")})
            lines.append("%s | %s | %s | %s | %s" % (
                p.name, r.get("license") or "?", r.get("creator") or "?",
                r.get("source") or "?", r.get("page") or r.get("url") or ""))
        log(f"  → {n_ok} ảnh")
        if not n_ok:
            log("  ! không tải được ảnh nào cho từ khoá này")
    if lines:
        try:
            f = out_dir / "credits.txt"
            old = f.read_text(encoding="utf-8") if f.exists() else ""
            f.write_text((old + "\n".join(lines) + "\n").lstrip("\n"),
                         encoding="utf-8")
        except Exception:
            pass
    return done
