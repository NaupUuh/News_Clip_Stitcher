"""Khung BREAKING NEWS — dựng overlay theo form CNN (lower-third).

VỊ TRÍ lấy từ `MELANIA ADMITS DEFEAT ON TRUMP.mp4` (360x640) bằng cách quét
pixel hình chữ nhật đặc trên frame sạch (không đoán bằng mắt):

    red box  : x  24..147  y 471..498   -> rong 124, cao 28
    white bar: x  28..335  y 499..535   -> rong 308, cao 37
    tong khoi banner cao 65px = 10.2% chieu cao frame
    day banner cach mep duoi 105px = 16.4%  (chua vung caption cua nen tang)

FORM (bố cục bên trong) lấy từ ảnh lower-third CNN do user gửi (493x137)
+ video mẫu MELANIA, đo lại bằng pixel (không đoán bằng mắt):

    thanh do    : rong 34.4% khung (o nho ben TRAI), cao 4.4% khung
                  chu "BREAKING NEWS" chiem 97% be rong thanh, cao 82% thanh
    thanh trang : rong 85.6% khung, cao 5.8% khung
                  chu tieu de CAN TRAI, chiem ~80% cao thanh
    logo        : O DO chu TRANG o cuoi ben PHAI thanh trang
                  rong 12.9% thanh trang, cao 76% thanh trang

LUU Y: KHONG dung 2 thanh cung be rong 95.2% — do la cach doc sai anh crop
525x99 tu session truoc, trai nguoc voi ca 2 nguon tham chieu.

Moi toa do luu dang TI LE (chia cho 360/640) nen dung duoc cho moi do phan
giai: 1080x1920 chi la nhan 3.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .ffmpeg_util import find_ffmpeg, probe_duration

# ── toa do goc do tu video mau (pixel tren khung 360x640) ──────────────
REF_W, REF_H = 360.0, 640.0
_REF = {
    "red_x": 24.0, "red_y": 471.0, "red_w": 124.0, "red_h": 28.0,
    "white_x": 28.0, "white_y": 499.0, "white_w": 308.0, "white_h": 37.0,
}

BANNER_DEFAULTS = {
    # ── khoi banner: thanh do NHO ben trai + thanh trang DAI (form CNN) ─
    "red_x": _REF["red_x"] / REF_W,        # 6.7%  — le trai thanh do
    "red_y": _REF["red_y"] / REF_H,        # 73.6%
    "red_w": _REF["red_w"] / REF_W,        # 34.4% — KHONG phai full width
    "red_h": _REF["red_h"] / REF_H,        # 4.4%
    "white_x": _REF["white_x"] / REF_W,    # 7.8%
    "white_y": _REF["white_y"] / REF_H,    # 78.0%
    "white_w": _REF["white_w"] / REF_W,    # 85.6%
    "white_h": _REF["white_h"] / REF_H,    # 5.8%
    # ── thang hang le trai: o trang co BAM mep trai o do khong ─────────
    # Mau CNN/BBC that: o do va o trang THANG LE TRAI. Do tu MELANIA.mp4 thi
    # red_x=24 con white_x=28 -> lech 4px/360 = 12px/1080 (user thay "chua bang
    # nhau"). "red" = mep trai o trang bam mep trai o do; "none" = dung white_x.
    "white_align_x": "red",
    # ── le + co chu (ti le so voi CHINH thanh do / thanh trang) ────────
    # Do tren MELANIA 360x640: thanh do h28 -> chu trang cao 14px = 50%;
    # chieu rong chu = 92% be rong thanh (chu gan lap day thanh).
    "red_pad_x": 0.0750,     # le trai "BREAKING NEWS" = 7.5% be rong thanh do
    "red_text_h": 0.500,     # cao chu do = 50% cao thanh do (mau CNN)
    "red_text_w": 0.920,     # chu do chiem toi da 92% be rong thanh do
    "white_pad_x": 0.0140,   # le trai tieu de = 1.4% be rong thanh trang
    "white_pad_r": 0.0140,
    "white_lines": 2,        # so dong tieu de toi da
    "white_line_h": 0.480,   # cao 1 dong tieu de = 48% cao thanh trang
    "white_text_h": 0.920,   # tong khoi tieu de toi da = 92% cao thanh trang
    "text_upper": True,      # in hoa toan bo (form CNN)
    # ── logo: O DO + chu TRANG ─────────────────────────────────────────
    "logo_w": 0.1290,        # be rong o logo = 12.9% be rong thanh trang
    "logo_h": 0.7600,        # cao o logo = 76% cao thanh trang
    "logo_pad_r": 0.0120,
    # chu (SUA DUOC)
    "red_text": "BREAKING NEWS",
    "white_text": "MELANIA EXPOSES TRUMP'S BIZARRE MEALS",
    "logo_text": "CNN",
    "show_logo": True,
    # mau
    "red_color": [204, 0, 0],
    "white_color": [255, 255, 255],
    "red_text_color": [255, 255, 255],
    "white_text_color": [12, 12, 12],
    "logo_color": [204, 0, 0],
    "logo_text_color": [255, 255, 255],
    # font (rong = tu tim)
    "font": "",
    "shadow": True,
    # ── CTA: "FULL STORY IN THE FIRST COMMENT" ──
    # Do lai tu anh tham chieu user gui 2026-10-02 (465x789, chu vang tren nen
    # troi, NGAY TREN DINH video — khong phai tren banner):
    #   dong 1 "FULL STORY IN"    y  39.. 72  x 123..323
    #   dong 2 "THE FIRST COMMENT" y 88..121  x  81..373
    #   -> cao 1 chu 34px = 4.31%H ; nhip 2 dong 49px = 6.21%H ; khe 2 dong
    #      36px -> cta_line_gap = 36/34 = 1.06  (gap tinh theo CHIEU CAO CHU)
    #   -> dinh khoi y 39px = 4.94%H ; day khoi y 121px = 15.34%H
    #   -> dong dai 292px = 62.8%W ; tam ngang 48.8% (gan giua)
    #   -> mau chu vang #ECFA1E ; vien den day ~5px/465W
    # TRUOC DAY cta_y=0.6328 (nam ngay TREN banner, nhu video mau MELANIA cu).
    "cta_enabled": True,
    "cta_line1": "FULL STORY IN",
    "cta_line2": "THE FIRST COMMENT",
    "cta_dur": 3.0,
    "cta_y": 0.0494,         # dinh khoi chu (do tu anh tham chieu)
    "cta_h": 0.0862,         # = 2 x cao chu -> chia doi ra cao 1 dong 4.31%H
    "cta_line_gap": 0.44,    # khe 2 dong = 0.44 x cao chu (do: 15px / 34px)
    "cta_squeeze": 0.873,    # bop NGANG: anh mau hep hon Impact (8.59 vs 9.84)
    "cta_color": [236, 250, 30],
    "cta_outline": [0, 0, 0],
    "cta_outline_w": 5,
    "cta_w": 0.850,          # be rong toi da (anh mau: dong dai 62.8%W)
    "cta_center_x": 0.5,
    # ── KHUNG MC "NEWS" (PiP) — nam NGAY TREN khung BREAKING NEWS ──────
    # HINH DANG do tu anh tham chieu CNN 485x877 do user gui (do bang pixel,
    # khong doan):  khung MC (vien xanh) x 6..231  y 430..678
    #               nhan do "NEWS"         x 11..110 y 468..511
    #   -> khung MC  = 46.4%W x 28.3%H cua khung hinh
    #   -> nhan NEWS = le trai 2.2% / dinh 15.3% / rong 43.8% / cao 17.3%
    #                  TINH THEO CHINH KHUNG MC (khong theo ca anh) nen doi
    #                  kich thuoc khung MC thi nhan van dung cho.
    # VI TRI DOC: KHONG hard-code theo anh tham chieu — neo theo day thanh do
    # cua banner THUC trong tool (red_y = 73.6%H), cach nhau `pip_gap`. Neu
    # hard-code theo anh tham chieu (78.4%) thi khung MC de len thanh do.
    "pip_enabled": False,
    "pip_x": 0.012,          # le trai khung MC (dung khi pip_align_x="none")
    # THANG HANG LE TRAI: "red" = bang mep trai o do BREAKING, "white" = bang o
    # trang tieu de, "none" = dung pip_x. Mac dinh "red" -> khung MC khong thoa
    # ra ngoai banner nua, nhin gon nhu layout CNN that.
    "pip_align_x": "red",
    "pip_y": None,           # None = tu neo NGAY TREN thanh do banner
    "pip_auto_y": True,      # True = luon neo tren banner (khuyen dung)
    "pip_gap": 0.008,        # khe ho giua day khung MC va dinh thanh do
    "pip_w": 0.325,          # be rong khung MC (70% cua 0.464)
    "pip_h": 0.198,          # cao khung MC (70% cua 0.283)
    "pip_border_w": 0.028,   # do day vien khung (ti le be rong khung hinh)
    "pip_border_color": [10, 30, 105],
    "pip_line_color": [235, 245, 255],
    "pip_line_w": 0.005,     # vien trang manh ben trong vien xanh
    "pip_src": "",           # file anh/video MC le (chon moi lan chay)
    "pip_folder": "",        # hoac folder chua nhieu MC -> boc ngau nhien
    "pip_zoom": 1.00,        # zoom them trong khung (>1 = sat hon)
    "pip_focus_y": 0.35,     # tam doc giu lai khi crop (0.35 = uu tien mat)
    # CAT LE NGUON truoc khi COVER — de che watermark/logo cua app tao video.
    # Do tren video MC DreamFace 538x720: chu "DreamFace / Animated with AI"
    # nam o y 86.5%..96.4% chieu cao -> cat 16% day la che han, van giu du MC.
    "pip_crop_top": 0.0,
    "pip_crop_bottom": 0.16,
    "pip_crop_left": 0.0,
    "pip_crop_right": 0.0,
    # nhan do "NEWS" — toa do TI LE TRONG KHUNG MC (khong phai ca khung hinh)
    # So do tu anh mau: nhan DINH SAT goc tren-trai khung (le trai ~2.7%,
    # dinh ~1.4%, rong ~36%, cao ~10% chieu cao khung) — nhan de LEN vien tren.
    # Truoc day dat pip_tag_y=0.153 -> nhan troi lung lung giua khung, sai form.
    "pip_tag_text": "NEWS",
    "pip_tag_x": 0.020,      # le trai nhan trong khung MC
    "pip_tag_y": -0.022,     # dinh nhan — DE len vien tren khung (nhu anh mau)
    "pip_tag_w": 0.360,      # rong nhan / rong khung MC
    "pip_tag_h": 0.105,      # cao nhan / cao khung MC
    "pip_tag_color": [204, 0, 0],
    "pip_tag_text_color": [255, 255, 255],
    "pip_tag_pad_x": 0.10,   # le trai chu trong nhan (ti le be rong nhan)
    "pip_shadow": True,
}

_FONT_CANDIDATES = [
    # Arial Narrow Bold = font condensed, dung cho lower-third tin tuc
    # (CNN/Fox deu dung condensed bold -> chu gon, khong bi be ngang)
    r"C:\Windows\Fonts\ARIALNB.TTF",
    r"C:\Windows\Fonts\arialnb.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\ARIALBD.TTF",
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\calibrib.ttf",
    r"C:\Windows\Fonts\verdanab.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def find_font(preferred: str = "") -> str:
    """Tim font dam. Tra ve '' neu khong co (PIL se dung font mac dinh)."""
    if preferred and Path(preferred).is_file():
        return preferred
    for p in _FONT_CANDIDATES:
        if Path(p).is_file():
            return p
    # thu quet thu muc font cua Windows
    fd = Path(r"C:\Windows\Fonts")
    if fd.is_dir():
        for pat in ("*bd.ttf", "*bold.ttf", "*.ttf"):
            hits = sorted(fd.glob(pat))
            if hits:
                return str(hits[0])
    return ""


# Font RIENG cho CTA "chu vang vien den" — KHONG dung _FONT_CANDIDATES chung,
# vi banner lower-third can condensed (Arial Narrow) con CTA can DAM/nang
# (Impact) theo anh tham chieu. Tach ra de doi CTA khong lam banner doi theo.
_FONT_CTA = [
    r"C:\Windows\Fonts\impact.ttf",
    r"C:\Windows\Fonts\IMPACT.TTF",
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\ARIALBD.TTF",
    r"C:\Windows\Fonts\ARIALNB.TTF",
    r"C:\Windows\Fonts\segoeuib.ttf",
]


def _cta_font(preferred: str = "") -> str:
    """Font cho CTA. Uu tien `preferred`; neu khong co thi dung Impact (dam)."""
    if preferred and Path(preferred).is_file():
        return preferred
    for p in _FONT_CTA:
        if Path(p).is_file():
            return p
    return find_font("")


def _load_font(font_path: str, size: int):
    try:
        return ImageFont.truetype(font_path, size) if font_path else ImageFont.load_default()
    except Exception:
        return ImageFont.load_default()


def _cap_of(draw, text: str, font):
    """(cao, rong) thuc te cua khoi chu theo bbox."""
    l, t, r, b = draw.textbbox((0, 0), text or " ", font=font)
    return max(1, b - t), max(1, r - l)


def _fit_cap(draw, text: str, font_path: str, target_cap: int, max_w: int):
    """Co chu lon nhat sao cho bbox cao <= target_cap va rong <= max_w."""
    lo, hi, best = 6, max(8, int(target_cap * 4)), 6
    while lo <= hi:
        mid = (lo + hi) // 2
        f = _load_font(font_path, mid)
        ch, cw = _cap_of(draw, text, f)
        if ch <= target_cap and cw <= max_w:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return _load_font(font_path, best)


def _draw_caps(draw, text: str, font, x: int, y: int, fill):
    """Ve chu sao cho DINH bbox nam dung tai y (de can le chuan)."""
    l, t, r, b = draw.textbbox((0, 0), text, font=font)
    draw.text((x - l, y - t), text, font=font, fill=fill)


def _wrap(draw, text: str, font, max_w: int):
    """Ngat dong theo tu (ton trong \\n cua nguoi dung).

    Tu dai hon ca thanh (vd 1 xau 40 ky tu khong co khoang trang) bi cat cung
    theo ky tu — neu khong se tran ra ngoai thanh trang.
    """
    out = []
    for hard in str(text).split("\n"):
        words = hard.split()
        if not words:
            continue
        cur = words[0]
        for wd in words[1:]:
            trial = cur + " " + wd
            try:
                wid = draw.textlength(trial, font=font)
            except Exception:
                wid = len(trial) * 8
            if wid <= max_w:
                cur = trial
            else:
                out.append(cur)
                cur = wd
        out.append(cur)
    # cat cung tung tu qua dai
    fixed = []
    for s in out:
        while True:
            try:
                wid = draw.textlength(s, font=font)
            except Exception:
                wid = len(s) * 8
            if wid <= max_w or len(s) <= 1:
                break
            # tim diem cat ngan nhat con lot
            cut = len(s)
            while cut > 1:
                try:
                    w2 = draw.textlength(s[:cut], font=font)
                except Exception:
                    w2 = cut * 8
                if w2 <= max_w:
                    break
                cut -= 1
            fixed.append(s[:cut])
            s = s[cut:]
        fixed.append(s)
    return fixed or [""]


def _is_source_line(s: str) -> bool:
    """Dòng này là nguồn tin ('THE NEW YORK TIMES · 42M AGO') hay tiêu đề?

    Dấu hiệu: ngắn (<= 44 ký tự), có 'AGO'/'H AGO', hoặc là tên báo đã biết.
    Dùng để tách ra render cỡ nhỏ thay vì chiếm chỗ của tiêu đề.
    """
    t = str(s or "").strip()
    if not t or len(t) > 44:
        return False
    u = t.upper()
    if re.search(r"\b\d+\s*(M|H|MIN|HOUR|PHÚT|GIỜ)\s*AGO\b", u):
        return True
    if u.endswith(" AGO") or u.endswith(" TRƯỚC"):
        return True
    for nm in ("NEW YORK TIMES", "WASHINGTON POST", "ASSOCIATED PRESS",
               "REUTERS", "FOX NEWS", "BBC", "CNN", "NBC", "CBS", "ABC",
               "THE HILL", "POLITICO", "GUARDIAN", "AP NEWS", "BLOOMBERG",
               "CNBC", "ESPN", "AXIOS", "NEWS", "TIMES", "POST"):
        if nm in u:
            return True
    return False


def _fit_lines(draw, text: str, font_path: str, max_w: int, max_h: int,
               max_lines: int, line_cap: int | None = None):
    """Tim (font, lines, cap, pitch): <= max_lines dong, tong cao <= max_h.

    line_cap (neu co) = chieu cao toi da cua MOT dong; tran nay quan trong
    vi lower-third that su khong cho chu phinh to bang ca thanh.
    """
    best = None
    hi_cap = max_h if not line_cap else min(max_h, int(line_cap))
    lo, hi = 6, max(10, int(hi_cap * 2.5))
    while lo <= hi:
        mid = (lo + hi) // 2
        f = _load_font(font_path, mid)
        lines = _wrap(draw, text, f, max_w)
        cap = max(_cap_of(draw, s, f)[0] for s in lines)
        pitch = int(round(cap * 1.35))
        tot = cap + pitch * (len(lines) - 1)
        if len(lines) <= max_lines and tot <= max_h and cap <= hi_cap:
            best = (f, lines, cap, pitch)
            lo = mid + 1
        else:
            hi = mid - 1
    if best is None:
        f = _load_font(font_path, 6)
        lines = _wrap(draw, text, f, max_w)
        cap = max(_cap_of(draw, s, f)[0] for s in lines)
        best = (f, lines, cap, int(round(cap * 1.35)))
    return best


def _fit_font(draw, text: str, font_path: str, max_w: int, max_h: int,
              pad: int = 0) -> ImageFont.FreeTypeFont:
    """Tim co chu lon nhat sao cho `text` nam gon trong (max_w, max_h)."""
    text = text or " "
    lo, hi, best = 6, max(8, max_h * 3), 6
    while lo <= hi:
        mid = (lo + hi) // 2
        try:
            f = ImageFont.truetype(font_path, mid) if font_path else ImageFont.load_default()
        except Exception:
            f = ImageFont.load_default()
        l, t, r, b = draw.textbbox((0, 0), text, font=f)
        if (r - l) <= max(1, max_w - 2 * pad) and (b - t) <= max(1, max_h):
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    try:
        return ImageFont.truetype(font_path, best) if font_path else ImageFont.load_default()
    except Exception:
        return ImageFont.load_default()


def _cover_crop(im: Image.Image, tw: int, th: int, focus_y: float = 0.5,
                zoom: float = 1.0) -> Image.Image:
    """Scale anh theo kieu COVER roi crop dung bang (tw x th).

    COVER = phong to anh sao cho phu KIN khung, phan thua bi cat bo. Nhờ vậy
    anh MC luon lap day khung, KHONG BAO GIO de lai vien trong va cung KHONG
    tran ra ngoai khung.
    """
    tw, th = max(2, int(tw)), max(2, int(th))
    sw, sh = im.size
    if sw < 1 or sh < 1:
        return Image.new("RGB", (tw, th), (0, 0, 0))
    z = max(1.0, float(zoom or 1.0))
    sc = max(tw / float(sw), th / float(sh)) * z
    nw, nh = max(tw, int(round(sw * sc))), max(th, int(round(sh * sc)))
    r = im.convert("RGB").resize((nw, nh), Image.LANCZOS)
    # tam crop: ngang giua, doc theo focus_y (0.35 = uu tien vung mat)
    fx = max(0, min(nw - tw, (nw - tw) // 2))
    fy = max(0, min(nh - th, int(round((nh - th) * float(focus_y or 0.5)))))
    return r.crop((fx, fy, fx + tw, fy + th))


def _src_crop(im: Image.Image, c: dict) -> Image.Image:
    """Cat le NGUON truoc khi COVER — de che watermark/logo cua app lam video.

    Cat theo TI LE 4 canh (pip_crop_top/bottom/left/right). An toan: neu ti le
    sai lam anh < 2px thi bo qua, tra anh goc (khong bao gio crash/trang).
    """
    try:
        W, H = im.size
        t = max(0.0, min(0.49, float(c.get("pip_crop_top", 0.0) or 0.0)))
        b = max(0.0, min(0.49, float(c.get("pip_crop_bottom", 0.0) or 0.0)))
        l = max(0.0, min(0.49, float(c.get("pip_crop_left", 0.0) or 0.0)))
        r = max(0.0, min(0.49, float(c.get("pip_crop_right", 0.0) or 0.0)))
        if t + b >= 0.98 or l + r >= 0.98 or (t + b + l + r) == 0:
            return im
        x0, y0 = int(round(W * l)), int(round(H * t))
        x1, y1 = W - int(round(W * r)), H - int(round(H * b))
        if x1 - x0 < 2 or y1 - y0 < 2:
            return im
        return im.crop((x0, y0, x1, y1))
    except Exception:
        return im


def _load_pip_source(cfg: dict):
    """Anh MC nguon: uu tien pip_src, khong co thi boc ngau nhien trong folder."""
    import random as _rnd
    p = str(cfg.get("pip_src", "") or "").strip()
    if p and Path(p).is_file():
        return Path(p)
    folder = str(cfg.get("pip_folder", "") or "").strip()
    if folder and Path(folder).is_dir():
        exts = (".png", ".jpg", ".jpeg", ".jpe", ".jfif", ".webp", ".bmp", ".mp4", ".mov")
        hits = [f for f in sorted(Path(folder).iterdir())
                if f.is_file() and f.suffix.lower() in exts]
        if hits:
            return _rnd.choice(hits)
    return None


def pip_geom(w: int, h: int, cfg: dict) -> dict:
    """Hinh hoc khung MC: x, y, w, h, bw (vien), lw (vach trang), iw, ih (ruot).

    Dung CHUNG cho overlay TINH (render_pip) va duong burn video DONG
    (apply_banner). Neu hai noi tu tinh rieng thi chi can lech 1px la video MC
    khong con khop lo trong khung.
    """
    c = dict(BANNER_DEFAULTS)
    c.update({k: v for k, v in (cfg or {}).items() if v is not None})
    pw = max(8, int(round(float(c.get("pip_w", 0.325)) * w)))
    ph = max(8, int(round(float(c.get("pip_h", 0.198)) * h)))

    # LE TRAI: "red"/"white" -> bang dung mep trai khoi do / o trang cua banner,
    # de khung MC khong thoa ra ngoai banner (user yeu cau "bo thang hang").
    align = str(c.get("pip_align_x", "red") or "red").strip().lower()
    # Chiu duoc ca NHAN tieng Viet lan MA: config.json cu tung luu nhan
    # "Bằng ô đỏ BREAKING" -> neu chi so sanh voi "red" thi roi vao nhanh else
    # va dung pip_x (lech lai). Map nhan -> ma truoc khi so.
    align = {
        "bằng ô đỏ breaking": "red", "bằng ô trắng tiêu đề": "white",
        "tự đặt lề trái": "none",
    }.get(align, align)
    if align == "red":
        px = int(round(float(c.get("red_x", 0.0667)) * w))
    elif align == "white":
        px = int(round(float(c.get("white_x", 0.0778)) * w))
    else:
        px = int(round(float(c.get("pip_x", 0.012)) * w))
    px = max(0, min(px, w - pw))

    # VI TRI DOC: pip_auto_y=True (mac dinh) -> neo day khung MC ngay TREN dinh
    # thanh do banner. Nho vay khung MC luon nam tren, khong bao gio de len
    # banner du banner doi vi tri (red_y la cau hinh, khong phai hang so).
    # pip_auto_y=False thi dung pip_y nhung van bi chan khong de len banner.
    py_cfg = c.get("pip_y", None)
    auto_y = bool(c.get("pip_auto_y", True)) or (py_cfg is None)
    red_y = int(round(float(c.get("red_y", 0.736)) * h))
    if auto_y:
        gap = int(round(float(c.get("pip_gap", 0.008)) * h))
        py = max(0, red_y - gap - ph)
    else:
        py = int(round(float(py_cfg) * h))
        # chan tren: khong cho khung MC de len thanh do
        if py + ph > red_y:
            py = max(0, red_y - ph)

    bw = max(0, int(round(float(c.get("pip_border_w", 0.028)) * w)))
    lw = max(0, int(round(float(c.get("pip_line_w", 0.005)) * w)))
    return {"x": px, "y": py, "w": pw, "h": ph, "bw": bw, "lw": lw,
            "iw": max(2, pw - 2 * bw), "ih": max(2, ph - 2 * bw)}


PIP_VID_EXT = (".mp4", ".mov", ".avi", ".mkv", ".webm")


def pip_video(cfg: dict):
    """Path video MC neu khung MC dang BAT va nguon la VIDEO (khong phai anh).

    Tra None khi: khung tat, nguon la anh tinh, hoac file khong ton tai.
    """
    c = dict(BANNER_DEFAULTS)
    c.update({k: v for k, v in (cfg or {}).items() if v is not None})
    if not bool(c.get("pip_enabled", False)):
        return None
    src = _load_pip_source(c)
    if src is None or src.suffix.lower() not in PIP_VID_EXT:
        return None
    return src


def render_pip(w: int, h: int, cfg: dict, hole: bool = False) -> Image.Image:
    """Khung MC "NEWS" (PiP) nam NGAY TREN khung BREAKING NEWS.

    MC duoc scale COVER + crop dung bang long khung nen KHONG BAO GIO tran ra
    ngoai. Neu khong tim thay anh MC -> tra overlay trong (khong ve gi).

    hole=True: KHONG dan anh MC, khoet ruot khung thanh TRONG SUOT — danh cho
    duong burn video DONG, ffmpeg tu lot video MC vao dung lo trong nay.
    """
    c = dict(BANNER_DEFAULTS)
    c.update({k: v for k, v in (cfg or {}).items() if v is not None})
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    if not bool(c.get("pip_enabled", False)):
        return img

    g = pip_geom(w, h, c)
    px, py, pw, ph = g["x"], g["y"], g["w"], g["h"]
    bw, lw, iw, ih = g["bw"], g["lw"], g["iw"], g["ih"]

    base = None
    if not hole:
        src = _load_pip_source(c)
        if src is None:
            return img
        # anh MC: COVER + crop trong long khung (bo cung, khong tran)
        try:
            if src.suffix.lower() in PIP_VID_EXT:
                frame = _first_frame(src)
                base = Image.open(frame).convert("RGB") if frame else None
                if frame:
                    try:
                        frame.unlink()
                    except Exception:
                        pass
            else:
                base = Image.open(src).convert("RGB")
            if base is None:
                return img
        except Exception:
            return img

    d = ImageDraw.Draw(img)
    # THU TU VE rat quan trong: vien khung TRUOC, roi moi dan anh MC len tren.
    # Neu dan anh truoc roi ve vien bang fill= thi vien se phu KIN ca anh
    # (khung trong ruot mau xanh) — loi da gap khi kiem tra bang vision.
    if bw > 0:
        d.rectangle([px, py, px + pw - 1, py + ph - 1],
                    fill=_rgb(c.get("pip_border_color"), (10, 30, 105)) + (255,))
    if hole:
        # Khoet ruot khung -> trong suot, de ffmpeg lot video MC vao.
        img.paste((0, 0, 0, 0), (px + bw, py + bw, px + bw + iw, py + bw + ih))
    else:
        tile = _cover_crop(_src_crop(base, c), iw, ih,
                           float(c.get("pip_focus_y", 0.35)),
                           float(c.get("pip_zoom", 1.0)))
        img.paste(tile, (px + bw, py + bw))
    # duong trang manh ben trong: ve TREN anh (form CNN co vach ngan anh/vien)
    if lw > 0:
        ix0, iy0 = px + bw, py + bw
        d.rectangle([ix0, iy0, ix0 + iw - 1, iy0 + ih - 1],
                    outline=_rgb(c.get("pip_line_color"), (235, 245, 255)) + (255,),
                    width=lw)

    # nhan do "NEWS" goc tren-trai khung — toa do TI LE TRONG KHUNG MC
    tag = str(c.get("pip_tag_text", "") or "").upper()
    if tag.strip():
        tx = px + int(round(float(c.get("pip_tag_x", 0.022)) * pw))
        ty = py + int(round(float(c.get("pip_tag_y", 0.153)) * ph))
        tw_ = max(8, int(round(float(c.get("pip_tag_w", 0.438)) * pw)))
        th_ = max(8, int(round(float(c.get("pip_tag_h", 0.173)) * ph)))
        # chan: nhan khong duoc tran ra ngoai khung MC
        tw_ = min(tw_, max(8, px + pw - tx))
        th_ = min(th_, max(8, py + ph - ty))
        if bool(c.get("pip_shadow", True)):
            d.rectangle([tx + 2, ty + 2, tx + tw_ + 2, ty + th_ + 2], fill=(0, 0, 0, 110))
        d.rectangle([tx, ty, tx + tw_ - 1, ty + th_ - 1],
                    fill=_rgb(c.get("pip_tag_color"), (204, 0, 0)) + (255,))
        fp = find_font(c.get("font", ""))
        f = _fit_cap(d, tag, fp, int(th_ * 0.62), int(tw_ * 0.86))
        ch, cw = _cap_of(d, tag, f)
        pad = int(round(tw_ * float(c.get("pip_tag_pad_x", 0.10))))
        _draw_caps(d, tag, f, tx + pad, ty + (th_ - ch) // 2,
                   _rgb(c.get("pip_tag_text_color"), (255, 255, 255)) + (255,))
    return img


def _first_frame(video: Path):
    """Trich 1 frame cua video MC -> PNG tam. Tra Path hoac None."""
    ff = find_ffmpeg()
    if not ff:
        return None
    import tempfile
    tmp = Path(tempfile.gettempdir()) / ("ncs_pip_%d.png" % abs(hash(str(video)) % 10**9))
    p = subprocess.run([ff, "-y", "-v", "error", "-i", str(video),
                        "-frames:v", "1", str(tmp)],
                       capture_output=True, text=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return tmp if (p.returncode == 0 and tmp.is_file()) else None


def _rgb(v, default=(0, 0, 0)):
    """Nhan list/tuple [r,g,b] hoac chuoi hex '#RRGGBB' / '#RGB'."""
    try:
        if isinstance(v, str):
            s = v.strip().lstrip("#")
            if len(s) == 3:
                s = "".join(ch * 2 for ch in s)
            if len(s) >= 6:
                return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
            return default
        return tuple(int(x) for x in list(v)[:3])
    except Exception:
        return default


def render_overlay(w: int, h: int, cfg: dict) -> Image.Image:
    """Dung anh overlay RGBA kich thuoc w x h theo cau hinh banner (form CNN)."""
    c = dict(BANNER_DEFAULTS)
    c.update({k: v for k, v in (cfg or {}).items() if v is not None})
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    font_path = find_font(c.get("font", ""))
    upper = bool(c.get("text_upper", True))

    def fx(xk, wk):
        return (int(round(float(c[xk]) * w)), max(2, int(round(float(c[wk]) * w))))

    def fy(yk, hk):
        return (int(round(float(c[yk]) * h)), max(2, int(round(float(c[hk]) * h))))

    shadow = bool(c.get("shadow", True))
    rx, rw = fx("red_x", "red_w")
    ry, rh = fy("red_y", "red_h")
    wx, ww = fx("white_x", "white_w")
    # THANG HANG LE TRAI (mac dinh): mep trai o trang BAM mep trai o do — dung
    # form CNN/BBC that. Nho vay doi red_x thi o trang tu bam theo, khong lech
    # lai nhu truoc (truoc day lech 12px tren khung 1080).
    if str(c.get("white_align_x", "red") or "red").lower() == "red":
        wx = rx
    wy, wh = fy("white_y", "white_h")

    # ── thanh do: full be rong khoi, chu trang CAN TRAI ────────────────
    if shadow:
        d.rectangle([rx + 2, ry + 2, rx + rw + 2, ry + rh + 2], fill=(0, 0, 0, 90))
    d.rectangle([rx, ry, rx + rw, ry + rh], fill=_rgb(c["red_color"], (204, 0, 0)) + (255,))

    rt = str(c.get("red_text", "") or "")
    if upper:
        rt = rt.upper()
    if rt.strip():
        cap = max(6, int(round(rh * float(c.get("red_text_h", 0.50)))))
        # chu do duoc phep chiem gan het be rong thanh (mau CNN: 92%)
        f = _fit_cap(d, rt, font_path, cap,
                     int(rw * float(c.get("red_text_w", 0.92))))
        ch, cw = _cap_of(d, rt, f)
        pad = int(round(rw * float(c.get("red_pad_x", 0.074))))
        _draw_caps(d, rt, f, rx + pad, ry + (rh - ch) // 2,
                   _rgb(c["red_text_color"], (255, 255, 255)) + (255,))

    # ── thanh trang: tieu de CAN TRAI + logo O DO CHU TRANG ────────────
    if shadow:
        d.rectangle([wx + 2, wy + 2, wx + ww + 2, wy + wh + 2], fill=(0, 0, 0, 90))
    d.rectangle([wx, wy, wx + ww, wy + wh], fill=_rgb(c["white_color"], (255, 255, 255)) + (255,))

    logo = str(c.get("logo_text", "") or "").upper()
    show_logo = bool(c.get("show_logo", True)) and logo.strip() != ""
    logo_zone = 0
    if show_logo:
        lw = max(10, int(round(ww * float(c.get("logo_w", 0.129)))))
        lh = max(10, int(round(wh * float(c.get("logo_h", 0.76)))))
        pad_r = max(0, int(round(ww * float(c.get("logo_pad_r", 0.012)))))
        lx = wx + ww - pad_r - lw
        ly = wy + (wh - lh) // 2
        d.rectangle([lx, ly, lx + lw, ly + lh],
                    fill=_rgb(c["logo_color"], (204, 0, 0)) + (255,))
        f = _fit_cap(d, logo, font_path, int(lh * 0.55), int(lw * 0.85))
        ch, cw = _cap_of(d, logo, f)
        _draw_caps(d, logo, f, lx + (lw - cw) // 2, ly + (lh - ch) // 2,
                   _rgb(c.get("logo_text_color"), (255, 255, 255)) + (255,))
        logo_zone = lw + pad_r

    # ── chu tieu de (SUA DUOC) ─────────────────────────────────────────
    wt = str(c.get("white_text", "") or "")
    if upper:
        wt = wt.upper()
    # Dòng CUỐI nếu là nguồn tin ("THE NEW YORK TIMES · 42M AGO") thì tách ra
    # render cỡ nhỏ — nếu gộp chung, nó ăn mất 1 dòng của tiêu đề và làm font
    # sập xuống không đọc được.
    sub = ""
    _wl = [x for x in wt.split("\n")]
    if len(_wl) >= 2:
        _last = _wl[-1].strip()
        if _is_source_line(_last):
            sub = _last
            wt = "\n".join(_wl[:-1]).strip()
    if wt.strip():
        pad_l = int(round(ww * float(c.get("white_pad_x", 0.020))))
        pad_r2 = int(round(ww * float(c.get("white_pad_r", 0.020))))
        avail_w = max(20, ww - pad_l - pad_r2 - logo_zone - int(round(ww * 0.02)))
        max_lines = max(1, int(c.get("white_lines", 2) or 2))
        # 1 dong cao toi da 48% thanh trang; ca khoi toi da 92% (mau CNN)
        line_cap = max(6, int(round(wh * float(c.get("white_line_h", 0.48)))))
        max_h = max(10, int(round(wh * float(c.get("white_text_h", 0.92)))))
        # có dòng nguồn bên dưới → chừa chỗ cho nó
        if sub:
            max_h = max(10, int(round(max_h * 0.76)))
            line_cap = min(line_cap, max(6, int(round(max_h * 0.62))))
        f, lines, cap, pitch = _fit_lines(d, wt, font_path, avail_w, max_h,
                                          max_lines, line_cap)
        tot = cap + pitch * (len(lines) - 1)
        sub_h = 0
        if sub:
            sub_h = max(8, int(round(wh * 0.16)))
            tot += sub_h + max(2, int(round(wh * 0.04)))
        y = wy + (wh - tot) // 2
        for i, s in enumerate(lines):
            _draw_caps(d, s, f, wx + pad_l, y + i * pitch,
                       _rgb(c["white_text_color"], (12, 12, 12)) + (255,))
        if sub:
            sub_f = _load_font(font_path, sub_h)
            sy = y + cap + pitch * (len(lines) - 1) + max(2, int(round(wh * 0.04)))
            _draw_caps(d, sub, sub_f, wx + pad_l, sy,
                       _rgb(c["white_text_color"], (12, 12, 12)) + (255,))

    # ── KHUNG MC "NEWS" (PiP): ve TRUOC roi chong banner LEN TREN ──────
    # Pip nam ngay tren banner nen khong de nhau; chong theo thu tu nay de
    # neu co sai so toa do thi banner (lop quan trong hon) luon thang.
    if bool(c.get("pip_enabled", False)):
        # Nguon MC la VIDEO -> khoet ruot khung trong suot de ffmpeg lot video
        # dong vao (xem apply_banner); nguon la ANH -> dan tinh nhu cu.
        pip = render_pip(w, h, c, hole=pip_video(c) is not None)
        out = pip.copy()
        out.alpha_composite(img)
        return out

    return img


def render_cta(w: int, h: int, cfg: dict) -> Image.Image:
    """Overlay CTA: 2 dòng vàng viền đen, căn giữa — mặc định ở ĐẦU video.

    Cách dựng (đo từ ảnh tham chiếu 465x789 của user):
      - `cta_h` = cao CẢ KHỐI 2 dòng, chia 2 ra cao 1 dòng. Mỗi dòng tự co giãn
        riêng theo chiều cao -> dòng 1 và dòng 2 cao BẰNG NHAU (đúng ảnh mẫu:
        34px = 34px) dù số ký tự khác nhau.
      - `cta_line_gap` = khe giữa 2 dòng, tính theo CHIỀU CAO CHỮ (0.44 = khe
        15px / chữ 34px), nên đổi cta_h thì khe tự co theo.
      - `cta_squeeze` = bóp NGANG. Font Impact của Windows bè hơn font trong ảnh
        mẫu (tỉ lệ rộng/cao 9.84 so với 8.59) nên phải bóp 0.873 cho khớp.
        Đặt 1.0 = không bóp.
      - `cta_outline_w` theo px @1080W rồi co theo bề rộng thật -> 5px/465W
        trên ảnh mẫu thành 11px trên khung 1080.
    """
    c = dict(BANNER_DEFAULTS)
    c.update({k: v for k, v in (cfg or {}).items() if v is not None})
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    l1 = str(c.get("cta_line1", "") or "")
    l2 = str(c.get("cta_line2", "") or "")
    if not (l1.strip() or l2.strip()):
        return img
    font_path = _cta_font(c.get("font", ""))

    y0 = int(round(float(c.get("cta_y", 0.0494)) * h))
    blk_h = int(round(float(c.get("cta_h", 0.1050)) * h))
    cx = int(round(float(c.get("cta_center_x", 0.5)) * w))
    fill = _rgb(c.get("cta_color"), (236, 250, 30)) + (255,)
    oc = _rgb(c.get("cta_outline"), (0, 0, 0)) + (255,)
    # vien tinh theo ti le be rong khung: 5px tren anh mau 465W -> ~11px @1080W
    ow = int(round(float(c.get("cta_outline_w", 5) or 0) * w / 465.0))

    line_h = max(8, blk_h // 2)
    gap = int(round(float(c.get("cta_line_gap", 0.44) or 0) * line_h))
    sq = min(1.0, max(0.3, float(c.get("cta_squeeze", 1.0) or 1.0)))
    max_w = int(w * float(c.get("cta_w", 0.850)))
    for i, txt in enumerate((l1, l2)):
        if not txt.strip():
            continue
        # do rong THAT khi bop ngang -> `_fit_font` phai biet truoc do bop, neu
        # khong chu se bi bop xong nhung van tran ra ngoai le.
        f = _fit_font(d, txt, font_path, int(max_w / sq), line_h)
        # ve chu len lop rieng (co le vien) roi BOP NGANG, sau do dan vao lop chinh
        l, t, r, b = d.textbbox((0, 0), txt, font=f)
        lw, lh = max(1, r - l), max(1, b - t)
        lay = Image.new("RGBA", (lw + 4 * ow + 8, lh + 4 * ow + 8), (0, 0, 0, 0))
        ld = ImageDraw.Draw(lay)
        ox, oy = 2 * ow + 4, 2 * ow + 4
        if ow > 0:
            for dx in range(-ow, ow + 1):
                for dy in range(-ow, ow + 1):
                    if dx * dx + dy * dy <= ow * ow:
                        ld.text((ox + dx, oy + dy), txt, font=f, fill=oc)
        ld.text((ox, oy), txt, font=f, fill=fill)
        # bbox NET CHU (khong ke le vien) de neo cho dung: PIL dat goc ve o
        # `oy` nhung net chu bat dau o `oy+t`, lech dung bang phan len cua font
        # -> neo theo goc se bi tut xuong (da tung lech 22px @1920).
        ft = oy + t          # dinh net chu trong lop
        fcx = ox + (l + r) / 2.0   # tam ngang net chu trong lop
        tw = max(1, int(round(lay.width * sq)))
        lay = lay.resize((tw, lay.height), Image.LANCZOS)
        tx = cx - int(round(fcx * sq))
        ty = y0 + i * (line_h + gap) - ft
        img.alpha_composite(lay, (tx, ty))
    return img


def probe_video(path):
    """Trả về (w, h) của video, hoặc None nếu không đọc được."""
    from .ffmpeg_util import probe_size
    return probe_size(path)


def preview_png(video: str | Path, out: str | Path, cfg: dict,
                at: float = 1.0) -> Path:
    """Trích 1 frame của video rồi ghép overlay lên -> PNG để xem trước.

    Nếu nguồn MC là VIDEO, ruột khung MC trong overlay là LỖ TRỐNG (để ffmpeg
    lồng video động khi burn) — nên phải tự trích 1 frame của video MC tại cùng
    mốc thời gian rồi lấp vào lỗ, nếu không ảnh xem trước sẽ thấy khung rỗng.
    """
    video, out = Path(video), Path(out)
    ff = find_ffmpeg() or "ffmpeg"
    c = dict(BANNER_DEFAULTS)
    c.update({k: v for k, v in (cfg or {}).items() if v is not None})
    # CTA chi bat o N giay CUOI. Neu `at` dang o giua video thi frame xem truoc
    # se KHONG co CTA -> tu nhay moc ve cuoi video de thay dung cai se burn.
    if bool(c.get("cta_enabled", True)) and float(c.get("cta_dur", 3.0) or 0) > 0:
        try:
            from .ffmpeg_util import probe_duration
            dur = float(probe_duration(video) or 0)
            if dur > 0 and at < dur - float(c.get("cta_dur", 3.0) or 0):
                at = max(0.0, dur - 0.5)
        except Exception:
            pass
    tmp = out.parent / (out.stem + "__f.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    p = subprocess.run([ff, "-y", "-v", "error", "-ss", str(at), "-i", str(video),
                        "-frames:v", "1", str(tmp)],
                       capture_output=True, text=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if p.returncode != 0 or not tmp.is_file():
        raise RuntimeError(f"trich frame that bai: {(p.stderr or '')[-300:]}")
    base = Image.open(tmp).convert("RGB")
    ov = render_overlay(base.width, base.height, cfg)
    comp = Image.alpha_composite(base.convert("RGBA"), ov)

    # CTA chi hien N giay CUOI -> neu xem truoc o moc giua video thi khong thay
    # gi ca, de tuong CTA hong. Neu dang bat CTA thi ghep them lop CTA vao.
    cta_ov = None
    if bool(c.get("cta_enabled", True)) and float(c.get("cta_dur", 3.0) or 0) > 0 \
            and (str(c.get("cta_line1", "")).strip() or str(c.get("cta_line2", "")).strip()):
        cta_ov = render_cta(base.width, base.height, cfg)
        comp = Image.alpha_composite(comp, cta_ov)

    mcv = pip_video(cfg)
    if mcv is not None:
        c = dict(BANNER_DEFAULTS)
        c.update({k: v for k, v in (cfg or {}).items() if v is not None})
        mc_tmp = out.parent / (out.stem + "__mc.png")
        q = subprocess.run([ff, "-y", "-v", "error", "-ss", str(at), "-i", str(mcv),
                            "-frames:v", "1", str(mc_tmp)],
                           capture_output=True, text=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if q.returncode == 0 and mc_tmp.is_file():
            g = pip_geom(base.width, base.height, c)
            tile = _cover_crop(_src_crop(Image.open(mc_tmp).convert("RGB"), c),
                               g["iw"], g["ih"],
                               float(c.get("pip_focus_y", 0.35)),
                               float(c.get("pip_zoom", 1.0)))
            comp.paste(tile, (g["x"] + g["bw"], g["y"] + g["bw"]))
        try:
            mc_tmp.unlink()
        except Exception:
            pass

    comp.convert("RGB").save(out)
    try:
        tmp.unlink()
    except Exception:
        pass
    return out


def _mc_chain(g: dict, c: dict, fps: int = 30) -> str:
    """Chuoi filter lot VIDEO MC vao long khung PiP -> nhan [mc].

    Phai GIONG HET hinh hoc cua `_src_crop` + `_cover_crop` (ban PIL dang dung
    cho anh tinh), neu khong video MC se lech/khong khop lo trong khung:
      crop le nguon (pip_crop_*) -> COVER (phu kin khung, cat phan thua)
      -> cat dung iw x ih, tam doc theo pip_focus_y, phong to theo pip_zoom.
    """
    iw, ih = max(2, int(g["iw"])), max(2, int(g["ih"]))

    def _cl(k):
        return max(0.0, min(0.49, float(c.get(k, 0.0) or 0.0)))

    t, b = _cl("pip_crop_top"), _cl("pip_crop_bottom")
    l, r = _cl("pip_crop_left"), _cl("pip_crop_right")
    z = max(1.0, float(c.get("pip_zoom", 1.0) or 1.0))
    fy = min(1.0, max(0.0, float(c.get("pip_focus_y", 0.35) or 0.35)))

    f = []
    if t + b + l + r > 0 and (t + b) < 0.98 and (l + r) < 0.98:
        f.append("crop=iw*%.6f:ih*%.6f:iw*%.6f:ih*%.6f" % (1 - l - r, 1 - t - b, l, t))
    f.append("scale=%d:%d:force_original_aspect_ratio=increase"
             % (max(2, int(round(iw * z))), max(2, int(round(ih * z)))))
    # CANH BAO: KHONG duoc viet crop=iw:ih — trong chuoi filter, iw/ih la kich
    # thuoc DAU VAO cua chinh filter crop (tuc anh vua scale), nen crop=iw:ih
    # la NO-OP -> ffmpeg dan anh TO HON khung, tran ra ngoai. Phai ghi SO CU THE.
    f.append("crop=%d:%d:(in_w-out_w)/2:(in_h-out_h)*%.6f" % (iw, ih, fy))
    f.append("setsar=1")
    f.append("fps=%d" % fps)
    return "[1:v]" + ",".join(f) + "[mc]"


def apply_banner(video: str | Path, out: str | Path, cfg: dict,
                 w: int, h: int, crf: float = 18.0, preset: str = "veryfast",
                 audio_copy: bool = True, log=None) -> Path:
    """Burn banner (cả video) + CTA (chỉ N giây cuối) lên video.

    Nếu khung MC đang bật và nguồn MC là VIDEO -> lồng hẳn video MC vào khung
    (chạy động), không còn dán ảnh tĩnh.
    """
    video, out = Path(video), Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    c = dict(BANNER_DEFAULTS)
    c.update({k: v for k, v in (cfg or {}).items() if v is not None})

    ov = out.parent / (out.stem + "__ov.png")
    render_overlay(w, h, c).save(ov)

    ff = find_ffmpeg() or "ffmpeg"
    # QUAN TRONG: PNG la input 1-frame. Neu khong loop, overlay chi ve duoc
    # vai frame dau roi tat -> banner "bien mat" sau ~2s. Phai -loop 1 de PNG
    # lap du suot video, va gioi han output bang -t (khong dung -shortest:
    # -shortest voi input loop vo han se treo).
    fps = 30
    dur = probe_duration(video)
    nf = None
    # Dung -frames:v voi SO FRAME THUC cua nguon: -t theo duration se cat mat
    # frame cuoi voi video VFR (duration le 14.9997 -> 447/448 frame thay vi 450).
    if dur:
        nf = max(1, round(dur * fps))
        dur = nf / fps

    mcv = pip_video(c)          # video MC (None neu khung tat / nguon la anh)
    inputs = ["-i", str(video)]
    fc = []
    cur = "[0:v]"
    nidx = 1                    # index input ke tiep
    if mcv is not None:
        # KHONG dung -stream_loop -1: video MC mac dinh da du 15s (bang video
        # chinh) -> chi can cho MC chay THANG het doan, khong lap lai.
        # Neu MC ngan hon thi overlay giu frame cuoi (eof_action=repeat mac dinh).
        inputs += ["-i", str(mcv)]
        g = pip_geom(w, h, c)
        fc.append(_mc_chain(g, c, fps))
        # CANH BAO: lo trong cua overlay nam o (x+bw, y+bw) — lech dung bang be
        # day vien. Neu overlay tai (x, y) thi video MC de LEN vien va tran ra
        # ngoai khung (tung bi: lech 30px).
        fc.append("%s[mc]overlay=%d:%d:format=auto[v0]"
                  % (cur, g["x"] + g["bw"], g["y"] + g["bw"]))
        cur = "[v0]"
        nidx += 1
        if log:
            log("   MC động: lồng video vào khung (%dx%d tại %d,%d)"
                % (g["iw"], g["ih"], g["x"] + g["bw"], g["y"] + g["bw"]))

    inputs += ["-loop", "1", "-framerate", str(fps), "-i", str(ov)]
    fc.append("%s[%d:v]overlay=0:0:format=auto[v1]" % (cur, nidx))
    nidx += 1

    cta_on = bool(c.get("cta_enabled", True))
    cta_dur = float(c.get("cta_dur", 3.0) or 0)
    if cta_on and cta_dur > 0 and (
            str(c.get("cta_line1", "")).strip() or str(c.get("cta_line2", "")).strip()):
        cta = out.parent / (out.stem + "__cta.png")
        render_cta(w, h, c).save(cta)
        inputs += ["-loop", "1", "-framerate", str(fps), "-i", str(cta)]
        # bat CTA trong cta_dur giay CUOI video, tinh theo thoi luong thuc
        st = max(0.0, dur - cta_dur) if dur else 0.0
        fc.append("[v1][%d:v]overlay=0:0:format=auto:"
                  "enable='gte(t,%.3f)'[v]" % (nidx, st))
        nidx += 1
        chain = ";".join(fc)
        cta_file = cta
    else:
        chain = ";".join(fc).replace("[v1]", "[v]")
        cta_file = None

    cmd = [ff, "-y", "-v", "error"] + inputs + [
        "-filter_complex", chain, "-map", "[v]"]
    if nf:
        cmd += ["-frames:v", str(nf)]
    if audio_copy:
        cmd += ["-map", "0:a?", "-c:a", "copy"]
    cmd += ["-c:v", "libx264", "-crf", str(crf), "-preset", preset,
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]
    if log:
        extra = f" + CTA {cta_dur:g}s cuối" if cta_file else ""
        log(f"   ffmpeg: burn banner{extra} -> {out.name}")
    p = subprocess.run(cmd, capture_output=True, text=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    for t in (ov, cta_file):
        try:
            if t:
                t.unlink()
        except Exception:
            pass
    if p.returncode != 0 or not out.is_file():
        raise RuntimeError(f"burn banner that bai: {(p.stderr or '')[-400:]}")
    return out
