"""
News Clip Stitcher v1.0.0
Nối ảnh + video thành video tin tức dọc 9:16 với hiệu ứng chuyển động (Ken Burns).

- Ảnh tĩnh  -> zoom/pan ngẫu nhiên
- Video     -> giữ chuyển động gốc, cắt đoạn ngẫu nhiên
- Cắt CỨNG giữa cảnh (giống news reel)
- Thời lượng tổng chính xác (mặc định 15s), chia đều có jitter
- Random thứ tự + số lượng + hướng chuyển động MỖI LẦN RENDER
"""
import json
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))

from core.stitcher import Stitcher, StitchError, list_media  # noqa: E402
from core.banner import BANNER_DEFAULTS  # noqa: E402
from core import eleven  # noqa: E402
from core import news as news_mod  # noqa: E402
from core import images as images_mod  # noqa: E402
from core.ffmpeg_util import (VID_EXT, set_ffmpeg_dir, ffmpeg_dir,  # noqa: E402
                              find_ffmpeg, find_ffprobe)

APP_VERSION = "1.24.2"
OUTPUT = BASE / "output"
CONFIG_F = BASE / "config.json"
OUTPUT.mkdir(exist_ok=True)

Z_BACKUP = Path(r"Z:\HQData-2\TOOLS TỔNG HỢP\TOOLS UPDATE CUỐI")
DESKTOP = Path(os.path.expanduser("~")) / "Desktop"

# Vị trí gốc đo từ video mẫu (tỉ lệ khung) — dùng cho nút "Về mặc định"
_REF_POS = {k: BANNER_DEFAULTS[k] for k in
            ("red_x", "red_y", "red_w", "red_h",
             "white_x", "white_y", "white_w", "white_h")}


def _break_lines(text: str, n: int = 3, mx: int = 34) -> list[str]:
    """Chia tiêu đề thành n đòng ngắn, ưu tiên cắt ở ranh giới từ.

    Dùng khi Gemini không khả dụng: tiêu đề tiếng Anh dài 60-90 ký tự phải
    nằm gọn trong 3 dòng của thanh trắng (ô chữ có giới hạn chiều rộng).
    """
    words = str(text).split()
    if not words:
        return []
    target = max(10, min(mx, len(text) // max(1, n) + 4))
    lines, cur = [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > target:
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


def _hook_label(v) -> str:
    """Nhãn cột 'Hook' cho bảng tin. Đo nội bộ, KHÔNG phải dự đoán viral."""
    if v is None:
        return "—"
    try:
        v = float(v)
    except Exception:
        return "—"
    if v >= 0.75:
        return "⚡ %.2f" % v
    if v >= 0.5:
        return "· %.2f" % v
    return "  %.2f" % v


def _hex_rgb(v, default=(0, 0, 0)):
    """'#RRGGBB' hoặc [r,g,b] -> (r,g,b). Sai định dạng thì trả mặc định."""
    try:
        if isinstance(v, (list, tuple)):
            return tuple(int(x) for x in list(v)[:3])
        s = str(v).strip().lstrip("#")
        if len(s) == 3:
            s = "".join(c * 2 for c in s)
        if len(s) == 6:
            return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        pass
    return default

DEFAULTS = {
    "total": 15.0,
    "fps": 30,
    "out_w": 1080,
    "out_h": 1920,
    "n_min": 5,
    "n_max": 7,
    "use_all": False,
    "min_clip": 1.4,
    "max_clip": 4.0,
    "kb_min": 1.06,
    "kb_max": 1.18,
    "video_zoom": 0.05,
    "face_focus": True,
    "grade": True,
    "grade_strength": 1.0,
    "interleave": True,
    "seg_window": 5.0,
    "seg_min": 2,
    "seg_max": 3,
    "seg_dur_min": 2.5,
    "seg_dur_max": 4.0,
    "vid_ratio": [0.6, 0.85],
    "n_videos": 5,
    "threads": 3,
    "max_overlap": 0.5,
    "crf": 18,
    "preset": "veryfast",
    "recursive": False,
    "audio": "",
    "audio_dir": "",
    "tts_key": "",
    "tts_voice": "Brian",
    "tts_model": "eleven_multilingual_v2",
    "tts_text": "",
    "tts_dir": "",
    "tts_dir_in": "",
    "tts_read_seconds": 15.0,
    "tts_fit": True,
    "tts_cps": 15.6,
    "out_dir": str(OUTPUT),
    "ffmpeg_dir": "",
    "copy_z": False,
    # tab 2: tin nóng 24h
    "news_use_gemini": True,
    "news_limit": 8,
    "news_hours": 24,
    "news_topics": ["Chính trị Mỹ"],
    # mục 7: tìm ảnh theo tin (Wikimedia, KHÔNG cần API key)
    "img_keywords": "",
    "img_dir": "",
    "img_per_kw": 3,
    "img_sources": "wikimedia",
    "img_add_folder": True,
}


class App:
    def __init__(self, root):
        self.root = root
        self.root.title(f"News Clip Stitcher v{APP_VERSION} — nối ảnh + video có chuyển động")
        self.root.geometry("1060x900")
        # Chặn thu nhỏ quá mức: dưới ngưỡng này các hàng widget bị bóp méo
        self.root.minsize(900, 560)
        self._setup_style()
        self.cfg = dict(DEFAULTS)
        self.load_config()
        # Áp thư mục ffmpeg đã lưu (nếu có) trước khi dựng UI
        _fd = str(self.cfg.get("ffmpeg_dir") or "")
        if _fd:
            set_ffmpeg_dir(_fd)
        # Nạp lại folder đã lưu (config có "folders") để mở tool là chạy tiếp được
        self.folders = [f for f in self.cfg.get("folders", [])
                        if isinstance(f, str) and Path(f).is_dir()]
        self.busy = False
        self.cancel = False
        self._img_busy = False       # mục 7 đang tìm ảnh
        self.vars = {}
        self.bvars = {}          # biến của tab 2 (breaking news)
        # cấu hình banner lưu riêng trong config["banner"]
        self.bcfg = dict(BANNER_DEFAULTS)
        _b = self.cfg.get("banner")
        if isinstance(_b, dict):
            self.bcfg.update(_b)
        self.bn_folders = [f for f in self.bcfg.get("folders", [])
                           if isinstance(f, str) and Path(f).is_dir()]

        # Notebook 2 tab. Tab 1 giữ nguyên 100% hành vi cũ: mọi widget cũ pack
        # vào self.tab1 nên code _build không phải sửa gì ngoài tên parent.
        self.nb = ttk.Notebook(root)
        self.nb.pack(fill="both", expand=True)
        self.tab1 = ttk.Frame(self.nb)
        self.tab2 = ttk.Frame(self.nb)
        self.nb.add(self.tab1, text="  🎬 1. Nối ảnh + video  ")
        self.nb.add(self.tab2, text="  📰 2. Breaking News  ")

        self._build()
        self._build_banner_tab()
        self.log("Sẵn sàng. Chọn folder đầu vào rồi bấm BẮT ĐẦU.")

    # ── config ─────────────────────────────────────────────
    def load_config(self):
        if CONFIG_F.is_file():
            try:
                self.cfg.update(json.loads(CONFIG_F.read_text(encoding="utf-8")))
            except Exception:
                pass

    def save_config(self):
        for k, v in self.vars.items():
            try:
                self.cfg[k] = v.get()
            except Exception:
                pass
        # ô nhập số giây là StringVar -> phải cất thành SỐ, không cất chuỗi
        # (config.json dễ đọc + đọc lại không phải parse lại).
        try:
            self.cfg["tts_read_seconds"] = max(
                0.5, min(3600.0, float(str(self.cfg.get("tts_read_seconds"))
                                       .replace(",", "."))))
        except Exception:
            self.cfg["tts_read_seconds"] = eleven.DEFAULT_READ_SECONDS
        self.cfg["folders"] = self.folders
        # tab 2: tuỳ chọn lấy tin nóng (widget riêng, không nằm trong bvars)
        if getattr(self, "nw_tree", None) is not None:
            self._news_save_cfg()
        # ffmpeg: ô nhập riêng (không nằm trong self.vars)
        try:
            self.cfg["ffmpeg_dir"] = set_ffmpeg_dir(self.ff_var.get())
        except Exception:
            pass
        # tab 2: gom từ widget rồi cất vào cfg["banner"] (giữ nguyên tab 1)
        if getattr(self, "bvars", None):
            try:
                b = dict(self.bcfg)
                for k, v in self.bvars.items():
                    if isinstance(v, tk.BooleanVar):
                        b[k] = bool(v.get())
                    elif isinstance(v, tk.DoubleVar):
                        b[k] = float(v.get())
                    else:
                        b[k] = v.get()
                b["folders"] = list(self.bn_folders)
                # MC: KHONG luu file da chon — user muon tu chon file MC moi lan
                # chay. Giu nguyen phan con lai (toa do, mau, co bat/tat).
                b["pip_src"] = ""
                b["pip_folder"] = ""
                # Le trai khung MC nay SET CUNG theo mep trai thanh do banner
                # (xem pip_geom). Xoa khoa cu de config.json khong con lua chon
                # gay lech khung MC (bug: chon "Tự đặt lề trái" -> lech 52px).
                for k in ("pip_align_x", "pip_x"):
                    b.pop(k, None)
                # O tich "Co MC" nghia la CO MC -> khong co MC thi tat luon, keo
                # lan sau mo tool thay tich san ma khung trong.
                b["pip_enabled"] = False
                self.cfg["banner"] = b
                self.bcfg = b
            except Exception:
                pass
        try:
            CONFIG_F.write_text(json.dumps(self.cfg, ensure_ascii=False, indent=2),
                                encoding="utf-8")
        except Exception:
            pass

    # ── UI ─────────────────────────────────────────────────
    def _setup_style(self):
        """Cỡ chữ to hơn mặc định — user yêu cầu dễ đọc."""
        st = ttk.Style()
        try:
            st.theme_use("vista")
        except Exception:
            pass
        base = ("Segoe UI", 11)
        st.configure(".", font=base)
        st.configure("TLabel", font=base)
        st.configure("TButton", font=("Segoe UI", 11))
        st.configure("TCheckbutton", font=base)
        st.configure("TRadiobutton", font=base)
        st.configure("TLabelframe.Label", font=("Segoe UI", 11, "bold"))
        st.configure("TNotebook.Tab", font=("Segoe UI", 11, "bold"), padding=(12, 6))
        st.configure("TCombobox", font=base)
        # Spinbox là widget tk cổ điển -> chỉnh qua option database
        self.root.option_add("*Font", base)
        self.root.option_add("*TCombobox*Listbox.font", base)

    def _scroll_area(self, parent):
        """Vùng cuộn dọc — trả về frame con để pack nội dung vào.

        Cần thiết vì cửa sổ có thể bị thu nhỏ: không cuộn thì các mục phía
        dưới bị cắt mất, không bấm được.
        """
        outer = ttk.Frame(parent)
        outer.pack(fill="both", expand=True)
        cv = tk.Canvas(outer, highlightthickness=0, bd=0)
        sb = ttk.Scrollbar(outer, orient="vertical", command=cv.yview)
        inner = ttk.Frame(cv)
        win = cv.create_window((0, 0), window=inner, anchor="nw")
        cv.configure(yscrollcommand=sb.set)
        cv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        inner.bind("<Configure>",
                   lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.bind("<Configure>",
                lambda e: cv.itemconfigure(win, width=e.width))

        def wheel(e):
            cv.yview_scroll(int(-1 * (e.delta / 120)), "units")

        # Chỉ bắt con lăn khi chuột đang ở trong vùng này, để tab kia không bị ảnh hưởng
        cv.bind("<Enter>", lambda e: cv.bind_all("<MouseWheel>", wheel))
        cv.bind("<Leave>", lambda e: cv.unbind_all("<MouseWheel>"))
        return inner

    def _build(self):
        pad = {"padx": 8, "pady": 4}
        t = self.tab1

        # Thanh hành động + Log ghim ở ĐÁY (pack side="bottom" TRƯỚC vùng cuộn)
        # -> thu nhỏ cửa sổ thế nào nút BẮT ĐẦU vẫn luôn nhìn thấy.
        f = ttk.Frame(t); f.pack(side="bottom", fill="x", **pad)
        self.go_btn = ttk.Button(f, text="🎬 BẮT ĐẦU", command=self._run)
        self.go_btn.pack(side="left", padx=3, ipadx=14, ipady=5)
        self.stop_btn = ttk.Button(f, text="⏹ Dừng", command=self._stop, state="disabled")
        self.stop_btn.pack(side="left", padx=3)
        self.prog = ttk.Progressbar(f, length=300, maximum=100)
        self.prog.pack(side="left", padx=12)
        self.status_var = tk.StringVar(value="Sẵn sàng")
        ttk.Label(f, textvariable=self.status_var, width=34).pack(side="left")

        # Cập nhật từ GitHub: máy nào cũng chỉ cần bấm nút này, KHÔNG phải gửi
        # lại file rồi cài đặt từ đầu (config.json + output luôn được giữ).
        self.upd_btn = ttk.Button(f, text="⬆ Cập nhật",
                                  command=self._check_update)
        self.upd_btn.pack(side="right", padx=3)

        lg = ttk.LabelFrame(t, text="Log", padding=3)
        lg.pack(side="bottom", fill="x", padx=8, pady=(0, 8))
        self.log_box = tk.Text(lg, height=7, state="disabled", bg="#12121c",
                               fg="#d0d0d0", font=("Consolas", 10), wrap="word")
        self.log_box.pack(fill="both", expand=True)

        body = self._scroll_area(t)

        # 1. Đầu vào
        g = ttk.LabelFrame(body, text="1. Đầu vào (folder chứa ảnh + video)", padding=6)
        g.pack(fill="x", **pad)
        f = ttk.Frame(g); f.pack(fill="x")
        ttk.Button(f, text="➕ Thêm folder", command=self._add_folder).pack(side="left", padx=3)
        ttk.Button(f, text="➕ Thêm nhiều", command=self._add_multi).pack(side="left", padx=3)
        ttk.Button(f, text="📂 Thêm folder cha (batch)", command=self._add_parent).pack(side="left", padx=3)
        ttk.Button(f, text="✕ Xoá chọn", command=self._del_folder).pack(side="left", padx=3)
        ttk.Button(f, text="🗑 Xoá hết", command=self._clear_folders).pack(side="left", padx=3)
        self.rec_var = tk.BooleanVar(value=self.cfg.get("recursive", False))
        ttk.Checkbutton(f, text="Quét cả folder con", variable=self.rec_var).pack(side="left", padx=10)

        lb = ttk.Frame(g); lb.pack(fill="both", expand=True, pady=(4, 0))
        self.listbox = tk.Listbox(lb, height=6, font=("Consolas", 10))
        self.listbox.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(lb, orient="vertical", command=self.listbox.yview)
        sb.pack(side="right", fill="y")
        self.listbox.config(yscrollcommand=sb.set)
        self.count_var = tk.StringVar(value="0 folder")
        ttk.Label(g, textvariable=self.count_var, foreground="#0a6").pack(anchor="w")

        # 2. Thông số — CHỈ để lại thứ hay đổi. Phần đã tối ưu sẵn gom hết vào
        # khối "Nâng cao" (ẩn mặc định) -> bố cục chính gọn, đỡ rối mắt.
        g = ttk.LabelFrame(body, text="2. Thông số video", padding=6)
        g.pack(fill="x", **pad)

        f = ttk.Frame(g); f.pack(fill="x", pady=2)
        self._spin(f, "Thời lượng (giây):", "total", 3, 120, 1, 6)
        self._spin(f, "Số file/cảnh — ít nhất:", "n_min", 1, 60, 1, 4)
        self._spin(f, "nhiều nhất:", "n_max", 1, 60, 1, 4)

        f = ttk.Frame(g); f.pack(fill="x", pady=2)
        self.face_var = tk.BooleanVar(value=bool(self.cfg.get("face_focus", True)))
        ttk.Checkbutton(f, text="Tự canh mặt khi crop (ảnh ngang không bị cắt mất mặt)",
                        variable=self.face_var).pack(side="left")

        f = ttk.Frame(g); f.pack(fill="x", pady=2)
        self.grade_var = tk.BooleanVar(value=bool(self.cfg.get("grade", True)))
        ttk.Checkbutton(f, text="Hiệu ứng màu ngẫu nhiên từng cảnh",
                        variable=self.grade_var).pack(side="left", padx=(0, 12))
        self.ileave_var = tk.BooleanVar(value=bool(self.cfg.get("interleave", True)))
        ttk.Checkbutton(f, text="Folder trộn ảnh+video: xen kẽ video → ảnh → video…",
                        variable=self.ileave_var).pack(side="left")

        # Nút mở/đóng khối nâng cao
        f = ttk.Frame(g); f.pack(fill="x", pady=(6, 0))
        self.adv_btn = ttk.Button(f, text="▸  Mở rộng thông số nâng cao",
                                  width=31, command=self._toggle_adv)
        self.adv_btn.pack(side="left")
        ttk.Label(f, text="  (đã tối ưu sẵn — chỉ mở khi cần chỉnh tay)",
                  foreground="#666").pack(side="left")

        # Khối nâng cao: tạo sẵn nhưng CHƯA pack -> ẩn. Bấm Mở rộng mới hiện.
        self.adv = ttk.Frame(g)
        row = ttk.Frame(self.adv); row.pack(fill="x")
        colL = ttk.Frame(row); colL.pack(side="left", fill="both", expand=True)
        colR = ttk.Frame(row); colR.pack(side="left", fill="both", expand=True)

        f = ttk.Frame(colL); f.pack(fill="x", pady=2)
        self._spin(f, "FPS:", "fps", 24, 60, 1, 4)
        ttk.Label(f, text="   Kích thước:").pack(side="left")
        self.w_var = tk.IntVar(value=self.cfg.get("out_w", 1080))
        self.h_var = tk.IntVar(value=self.cfg.get("out_h", 1920))
        ttk.Entry(f, textvariable=self.w_var, width=6).pack(side="left", padx=2)
        ttk.Label(f, text="x").pack(side="left")
        ttk.Entry(f, textvariable=self.h_var, width=6).pack(side="left", padx=2)

        f = ttk.Frame(colL); f.pack(fill="x", pady=2)
        self.all_var = tk.BooleanVar(value=self.cfg.get("use_all", False))
        ttk.Checkbutton(f, text="Dùng TẤT CẢ file",
                        variable=self.all_var).pack(side="left", padx=2)

        f = ttk.Frame(colL); f.pack(fill="x", pady=2)
        self._spin(f, "Cảnh — ngắn nhất (s):", "min_clip", 0.5, 20, 0.1, 5)
        self._spin(f, "dài nhất (s):", "max_clip", 0.5, 20, 0.1, 5)

        f = ttk.Frame(colL); f.pack(fill="x", pady=2)
        self._spin(f, "Ảnh — zoom nhỏ nhất:", "kb_min", 1.0, 2.0, 0.01, 5)
        self._spin(f, "lớn nhất:", "kb_max", 1.0, 2.5, 0.01, 5)

        f = ttk.Frame(colR); f.pack(fill="x", pady=2)
        self._spin(f, "Mạnh màu:", "grade_strength", 0.0, 1.5, 0.1, 4)
        self._spin(f, "Video — zoom thêm:", "video_zoom", 0.0, 0.4, 0.01, 5)
        ttk.Label(f, text="(0 = giữ nguyên)", foreground="#666").pack(side="left")

        # Cắt lìa video nguồn thành nhiều đoạn, mỗi đoạn dùng 1 lần
        f = ttk.Frame(colR); f.pack(fill="x", pady=2)
        self._spin(f, "Đoạn video dài:", "seg_dur_min", 0.5, 6.0, 0.5, 4)
        self._spin(f, "tới:", "seg_dur_max", 0.5, 6.0, 0.5, 4)
        ttk.Label(f, text="giây", foreground="#666").pack(side="left", padx=(2, 0))

        ttk.Label(colR,
                  text="Clip gốc bị CẮT LÌA liên tiếp thành nhiều đoạn dài trong khoảng\n"
                       "trên; mỗi đoạn chỉ dùng 1 lần. Một video con lấy nhiều đoạn\n"
                       "video + vài ảnh. Hết đoạn video thì các video sau dùng toàn ảnh.",
                  foreground="#666", justify="left").pack(anchor="w", pady=(2, 0))

        f = ttk.Frame(colR); f.pack(fill="x", pady=2)
        self._spin(f, "Chất lượng CRF:", "crf", 12, 30, 1, 4)
        ttk.Label(f, text="   Preset:").pack(side="left", padx=(6, 2))
        self.preset_var = tk.StringVar(value=self.cfg.get("preset", "veryfast"))
        ttk.Combobox(f, textvariable=self.preset_var, width=11, state="readonly",
                     values=["ultrafast", "veryfast", "faster", "fast", "medium"]).pack(side="left")
        ttk.Label(colR, text="CRF nhỏ = nét hơn, file to hơn", foreground="#666").pack(anchor="w")

        # 3. Chạy hàng loạt — tách RIÊNG khỏi khối nâng cao vì đây là thứ hay đổi
        g = ttk.LabelFrame(body, text="3. Chạy hàng loạt (batch)", padding=6)
        g.pack(fill="x", **pad)

        f = ttk.Frame(g); f.pack(fill="x", pady=2)
        ttk.Label(f, text="Số video mỗi folder:").pack(side="left", padx=(2, 2))
        self.nvid_var = tk.IntVar(value=int(self.cfg.get("n_videos", 5)))
        self.vars["n_videos"] = self.nvid_var
        tk.Spinbox(f, from_=1, to=200, increment=1, textvariable=self.nvid_var,
                   width=5).pack(side="left", padx=(0, 14))
        ttk.Label(f, text="Luồng song song:").pack(side="left", padx=(2, 2))
        self.thread_var = tk.IntVar(value=int(self.cfg.get("threads", 3)))
        self.vars["threads"] = self.thread_var
        tk.Spinbox(f, from_=1, to=16, increment=1, textvariable=self.thread_var,
                   width=4).pack(side="left", padx=(0, 14))
        ttk.Label(f, text="Trùng tối đa:").pack(side="left", padx=(2, 2))
        self.ovl_var = tk.DoubleVar(value=float(self.cfg.get("max_overlap", 0.5)))
        self.vars["max_overlap"] = self.ovl_var
        tk.Spinbox(f, from_=0.0, to=1.0, increment=0.1, textvariable=self.ovl_var,
                   width=4).pack(side="left", padx=(0, 6))
        ttk.Button(f, text="🔍 Kiểm tra pool", width=14,
                   command=self._check_pool).pack(side="left", padx=(6, 2))

        ttk.Label(g, text="Trùng tối đa: 0.5 = 2 video không dùng chung quá 1 nửa số ẢNH\n"
                          "(video nguồn dùng lại được — mỗi lần lấy 1 đoạn khác)",
                  foreground="#666", justify="left").pack(anchor="w")

        # 3. Audio
        g = ttk.LabelFrame(body, text="4. Audio (tuỳ chọn)", padding=6)
        g.pack(fill="x", **pad)
        f = ttk.Frame(g); f.pack(fill="x", pady=2)
        ttk.Label(f, text="1 file cho tất cả:", width=18).pack(side="left")
        self.audio_var = tk.StringVar(value=self.cfg.get("audio", ""))
        ttk.Entry(f, textvariable=self.audio_var, width=54).pack(side="left", padx=3)
        ttk.Button(f, text="Chọn", width=7, command=self._pick_audio).pack(side="left", padx=2)
        ttk.Button(f, text="✕", width=3, command=lambda: self.audio_var.set("")).pack(side="left")

        f = ttk.Frame(g); f.pack(fill="x", pady=2)
        ttk.Label(f, text="hoặc folder audio:", width=18).pack(side="left")
        self.audio_dir_var = tk.StringVar(value=self.cfg.get("audio_dir", ""))
        ttk.Entry(f, textvariable=self.audio_dir_var, width=54).pack(side="left", padx=3)
        ttk.Button(f, text="Chọn", width=7, command=self._pick_audio_dir).pack(side="left", padx=2)
        ttk.Label(g, text="Folder audio: khớp tên file audio với tên folder con (VD: 001.mp3 ↔ 001/)",
                  foreground="#666").pack(anchor="w")

        # 3b. ElevenLabs — tạo giọng đọc tin
        g = ttk.LabelFrame(body, text="4b. Giọng đọc tin (ElevenLabs) — tạo audio từ text",
                           padding=6)
        g.pack(fill="x", **pad)

        f = ttk.Frame(g); f.pack(fill="x", pady=2)
        ttk.Label(f, text="API key:", width=9).pack(side="left")
        self.tts_key_var = tk.StringVar(value=self.cfg.get("tts_key", "") or "")
        self.vars["tts_key"] = self.tts_key_var
        tk.Entry(f, textvariable=self.tts_key_var, width=44, show="•").pack(side="left", padx=3)
        self.tts_key_state = tk.StringVar(value="…")
        ttk.Label(f, textvariable=self.tts_key_state, foreground="#666").pack(side="left", padx=6)
        ttk.Button(f, text="Nạp từ .env", width=12,
                   command=self._tts_load_key).pack(side="left", padx=2)
        ttk.Button(f, text="Lưu vào .env", width=12,
                   command=self._tts_save_key).pack(side="left", padx=2)
        ttk.Button(f, text="Kiểm tra", width=9,
                   command=self._tts_check_key).pack(side="left", padx=2)

        f = ttk.Frame(g); f.pack(fill="x", pady=2)
        ttk.Label(f, text="Giọng đọc:", width=9).pack(side="left")
        self.tts_voice_var = tk.StringVar(value=self.cfg.get("tts_voice", "Brian"))
        self.vars["tts_voice"] = self.tts_voice_var
        self.tts_voice_cb = ttk.Combobox(f, textvariable=self.tts_voice_var,
                                         width=54, state="readonly",
                                         values=[eleven.voice_label(v) for v in eleven.VOICES])
        self.tts_voice_cb.pack(side="left", padx=3)
        ttk.Label(f, text="Model:").pack(side="left", padx=(10, 2))
        self.tts_model_var = tk.StringVar(value=self.cfg.get("tts_model", eleven.DEFAULT_MODEL))
        self.vars["tts_model"] = self.tts_model_var
        ttk.Combobox(f, textvariable=self.tts_model_var, width=22, state="readonly",
                     values=[m[0] for m in eleven.MODELS]).pack(side="left")
        # ghi rõ giọng này giống kiểu nhà đài nào
        self.tts_voice_note = tk.StringVar(value="")
        ttk.Label(g, textvariable=self.tts_voice_note, foreground="#0a6",
                  wraplength=900, justify="left").pack(anchor="w")
        self.tts_voice_cb.bind("<<ComboboxSelected>>", lambda e: self._tts_voice_info())

        f = ttk.Frame(g); f.pack(fill="x", pady=2)
        ttk.Label(f, text="Nội dung:", width=9).pack(side="left", anchor="n")
        self.tts_text = tk.Text(f, height=4, wrap="word", font=("Segoe UI", 10))
        self.tts_text.pack(side="left", fill="x", expand=True, padx=3)
        if self.cfg.get("tts_text"):
            self.tts_text.insert("1.0", str(self.cfg.get("tts_text")))

        self.tts_text.bind("<KeyRelease>", lambda e: self._tts_len_hint())

        # Thời gian đọc — video 15s thì audio cũng phải ~15s mới khớp.
        # ElevenLabs không nhận "độ dài", nó đọc hết text -> phải ép về số
        # giây này sau khi tạo (xem eleven.fit_duration).
        f = ttk.Frame(g); f.pack(fill="x", pady=2)
        ttk.Label(f, text="Thời gian đọc:", width=14).pack(side="left")
        try:
            _rs = float(self.cfg.get("tts_read_seconds", 15.0) or 15.0)
        except Exception:
            _rs = 15.0
        if _rs <= 0:
            _rs = 15.0
        self.tts_secs_var = tk.StringVar(value=("%g" % _rs))
        self.vars["tts_read_seconds"] = self.tts_secs_var
        _sp = tk.Spinbox(f, from_=1, to=600, increment=1, width=6,
                         textvariable=self.tts_secs_var,
                         command=self._tts_len_hint)
        _sp.pack(side="left", padx=3)
        _sp.bind("<KeyRelease>", lambda e: self._tts_len_hint())
        ttk.Label(f, text="giây  (mặc định 15 — khớp video 15s)",
                  foreground="#666").pack(side="left", padx=(0, 10))
        self.tts_fit_var = tk.BooleanVar(value=bool(self.cfg.get("tts_fit", True)))
        self.vars["tts_fit"] = self.tts_fit_var
        ttk.Checkbutton(f, text="Ép đúng số giây khi tạo",
                        variable=self.tts_fit_var,
                        command=self._tts_len_hint).pack(side="left", padx=4)

        f = ttk.Frame(g); f.pack(fill="x", pady=2)
        self.tts_len_var = tk.StringVar(value="")
        ttk.Label(f, textvariable=self.tts_len_var, foreground="#0a6",
                  wraplength=900, justify="left").pack(anchor="w")

        f = ttk.Frame(g); f.pack(fill="x", pady=2)
        ttk.Label(f, text="Lưu audio:", width=9).pack(side="left")
        self.tts_dir_var = tk.StringVar(value=self.cfg.get("tts_dir", "") or str(OUTPUT / "tts"))
        self.vars["tts_dir"] = self.tts_dir_var
        tk.Entry(f, textvariable=self.tts_dir_var, width=44).pack(side="left", padx=3)
        ttk.Button(f, text="Chọn", width=7, command=self._tts_pick_dir).pack(side="left", padx=2)
        self.tts_name_var = tk.StringVar(value="voice")
        ttk.Label(f, text="Tên file:").pack(side="left", padx=(8, 2))
        tk.Entry(f, textvariable=self.tts_name_var, width=16).pack(side="left")
        ttk.Label(f, text=".mp3").pack(side="left")
        self.tts_gen_btn = ttk.Button(f, text="🎙 Tạo audio", command=self._tts_generate)
        self.tts_gen_btn.pack(side="left", padx=8)
        ttk.Button(f, text="▶ Nghe thử", width=11,
                   command=self._tts_play).pack(side="left", padx=2)

        # tạo hàng loạt: mỗi folder con 1 file .txt -> 1 file audio
        f = ttk.Frame(g); f.pack(fill="x", pady=2)
        ttk.Label(f, text="Hàng loạt:", width=9).pack(side="left")
        self.tts_batch_var = tk.StringVar(value=self.cfg.get("tts_dir_in", "") or "")
        self.vars["tts_dir_in"] = self.tts_batch_var
        tk.Entry(f, textvariable=self.tts_batch_var, width=44).pack(side="left", padx=3)
        ttk.Button(f, text="Chọn", width=7,
                   command=self._tts_pick_batch).pack(side="left", padx=2)
        ttk.Button(f, text="📄 Đọc folder .txt → tạo audio",
                   command=self._tts_batch).pack(side="left", padx=8)
        ttk.Label(g, text="Hàng loạt: mỗi file .txt trong folder → 1 file .mp3 cùng tên. "
                          "File audio tạo ra nằm ở ô \"Lưu audio\" và khớp được với "
                          "\"folder audio\" ở mục 3.",
                  foreground="#666", wraplength=900, justify="left").pack(anchor="w")
        self._tts_voice_info()
        self._tts_len_hint()

        # 4. Xuất
        g = ttk.LabelFrame(body, text="5. Nơi lưu", padding=6)
        g.pack(fill="x", **pad)
        f = ttk.Frame(g); f.pack(fill="x", pady=2)
        ttk.Label(f, text="Lưu vào:", width=10).pack(side="left")
        self.out_var = tk.StringVar(value=self.cfg.get("out_dir", str(OUTPUT)))
        ttk.Entry(f, textvariable=self.out_var, width=58).pack(side="left", padx=3)
        ttk.Button(f, text="Chọn", width=7, command=self._pick_out).pack(side="left", padx=2)
        ttk.Button(f, text="Mở", width=5, command=self._open_out).pack(side="left", padx=2)

        f = ttk.Frame(g); f.pack(fill="x", pady=2)
        ttk.Button(f, text="📁 Desktop", width=11,
                   command=lambda: self.out_var.set(str(DESKTOP))).pack(side="left", padx=3)
        ttk.Button(f, text="📁 Thư mục tool", width=14,
                   command=lambda: self.out_var.set(str(OUTPUT))).pack(side="left", padx=3)
        self.z_var = tk.BooleanVar(value=self.cfg.get("copy_z", False))
        ttk.Checkbutton(f, text="Sao chép thêm vào Z:\\...\\TOOLS UPDATE CUỐI",
                        variable=self.z_var).pack(side="left", padx=12)

        # 5. ffmpeg
        g = ttk.LabelFrame(body, text="6. ffmpeg (bộ xử lý video)", padding=6)
        g.pack(fill="x", **pad)
        f = ttk.Frame(g); f.pack(fill="x", pady=2)
        ttk.Label(f, text="Thư mục ffmpeg:", width=16).pack(side="left")
        self.ff_var = tk.StringVar(value=str(self.cfg.get("ffmpeg_dir") or ""))
        ttk.Entry(f, textvariable=self.ff_var, width=46).pack(side="left", padx=3)
        ttk.Button(f, text="Chọn", width=7,
                   command=self._pick_ffmpeg).pack(side="left", padx=2)
        ttk.Button(f, text="Mở", width=5,
                   command=self._open_ffmpeg).pack(side="left", padx=2)
        ttk.Button(f, text="Tự dò", width=8,
                   command=self._auto_ffmpeg).pack(side="left", padx=2)
        self.ff_status = ttk.Label(g, text="", foreground="#0a7", wraplength=900,
                                   justify="left")
        self.ff_status.pack(anchor="w")
        ttk.Label(g, text="Bấm “Chọn” để trỏ tới thư mục chứa ffmpeg.exe — hộp chọn "
                          "mở sẵn ở thư mục tool đang dùng. Để trống = tự dò.",
                  foreground="#666").pack(anchor="w")
        self._ff_refresh()

        # (Mục 5 Hành động + Log đã ghim ở ĐÁY tab1 trong _build — xem đầu hàm)

        # Đồng bộ listbox với folder đã nạp từ config (không gọi save_config ở
        # đây để tránh ghi đè config ngay khi vừa mở tool)
        self.listbox.delete(0, "end")
        for f in self.folders:
            self.listbox.insert("end", f)
        self.count_var.set(f"{len(self.folders)} folder")

    def _toggle_adv(self):
        """Mở/đóng khối thông số nâng cao (ẩn mặc định cho gọn bố cục)."""
        if self.adv.winfo_ismapped():
            self.adv.pack_forget()
            self.adv_btn.config(text="▸  Mở rộng thông số nâng cao")
        else:
            self.adv.pack(fill="x", pady=(6, 0))
            self.adv_btn.config(text="▾  Thu gọn thông số nâng cao")

    def _spin(self, parent, label, key, lo, hi, inc, width):
        ttk.Label(parent, text=label).pack(side="left", padx=(2, 2))
        v = tk.DoubleVar(value=self.cfg.get(key, DEFAULTS[key]))
        self.vars[key] = v
        tk.Spinbox(parent, from_=lo, to=hi, increment=inc, textvariable=v,
                   width=width).pack(side="left", padx=(0, 10))

    # ══════════════════ TAB 2: BREAKING NEWS ══════════════════
    def _bn_spin(self, parent, label, key, lo, hi, inc, width=7):
        ttk.Label(parent, text=label).pack(side="left", padx=(4, 2))
        v = tk.DoubleVar(value=float(self.bcfg.get(key, BANNER_DEFAULTS[key])))
        self.bvars[key] = v
        tk.Spinbox(parent, from_=lo, to=hi, increment=inc, textvariable=v,
                   width=width, format="%.4f").pack(side="left", padx=(0, 8))

    def _bn_entry(self, parent, label, key, width=34, side="left"):
        ttk.Label(parent, text=label).pack(side=side, padx=(4, 2))
        v = tk.StringVar(value=str(self.bcfg.get(key, BANNER_DEFAULTS.get(key, ""))))
        self.bvars[key] = v
        e = tk.Entry(parent, textvariable=v, width=width)
        e.pack(side=side, padx=(0, 8))
        return e

    def _build_banner_tab(self):
        pad = {"padx": 8, "pady": 4}
        t = self.tab2

        # Thanh hành động ghim ĐÁY (pack side="bottom" trước vùng cuộn)
        f = ttk.Frame(t); f.pack(side="bottom", fill="x", **pad)
        self.bn_prev_btn = ttk.Button(f, text="👁 Xem trước", command=self._bn_preview)
        self.bn_prev_btn.pack(side="left", padx=3, ipadx=8, ipady=4)
        self.bn_go_btn = ttk.Button(f, text="📰 BURN BANNER", command=self._bn_run)
        self.bn_go_btn.pack(side="left", padx=3, ipadx=14, ipady=5)
        self.bn_stop_btn = ttk.Button(f, text="⏹ Dừng", command=self._stop, state="disabled")
        self.bn_stop_btn.pack(side="left", padx=3)
        self.bn_prog = ttk.Progressbar(f, length=260, maximum=100)
        self.bn_prog.pack(side="left", padx=12)
        self.bn_status = tk.StringVar(value="Sẵn sàng")
        ttk.Label(f, textvariable=self.bn_status, width=30).pack(side="left")

        # Log ghim đáy, ngay dưới thanh hành động
        lg = ttk.LabelFrame(t, text="Log", padding=3)
        lg.pack(side="bottom", fill="x", padx=8, pady=(0, 8))
        self.bn_log_box = tk.Text(lg, height=7, state="disabled", bg="#12121c",
                                  fg="#d0d0d0", font=("Consolas", 10), wrap="word")
        self.bn_log_box.pack(fill="both", expand=True)

        body = self._scroll_area(t)

        # 0. Tin nóng 24h — lấy tin rồi đổ thẳng vào ô banner
        g = ttk.LabelFrame(body, text="0. Tin nóng 24h (AI + Google News)", padding=6)
        g.pack(fill="x", **pad)
        f = ttk.Frame(g); f.pack(fill="x", pady=2)
        self.nw_use = tk.BooleanVar(value=bool(self.cfg.get("news_use_gemini", True)))
        ttk.Checkbutton(f, text="Dùng AI viết lại tiêu đề",
                        variable=self.nw_use).pack(side="left", padx=(0, 8))
        ttk.Label(f, text="AI:").pack(side="left")
        self.nw_ai = tk.StringVar(value=str(self.cfg.get("news_ai", "vilao")))
        cb = ttk.Combobox(f, textvariable=self.nw_ai, width=13,
                          values=("vilao", "gemini", "auto"))
        cb.pack(side="left", padx=3)
        ttk.Label(f, text="Model:").pack(side="left", padx=(8, 0))
        self.nw_model = tk.StringVar(value=str(self.cfg.get("news_model", "")))
        # KHONG hardcode danh sach model: Vilao them/bot lien tuc. O nay GO TAY
        # duoc; bam '⟳' de nap danh sach THAT tu Vilao (/v1/models).
        self.nw_mbox = ttk.Combobox(f, textvariable=self.nw_model, width=22,
                                    values=tuple(self.cfg.get("news_models_cache")
                                                 or ()))
        self.nw_mbox.pack(side="left", padx=3)
        ttk.Button(f, text="⟳", width=3,
                   command=self._news_load_models).pack(side="left")
        ttk.Label(f, text="(gõ tay tên model, để trống = mặc định)",
                  foreground="#666").pack(side="left", padx=(4, 0))
        ttk.Label(f, text="Số tin:").pack(side="left", padx=(8, 0))
        self.nw_n = tk.IntVar(value=int(self.cfg.get("news_limit", 8) or 8))
        tk.Spinbox(f, from_=1, to=30, textvariable=self.nw_n, width=4).pack(side="left", padx=3)
        ttk.Label(f, text="  Trong vòng (giờ):").pack(side="left")
        self.nw_h = tk.IntVar(value=int(self.cfg.get("news_hours", 24) or 24))
        tk.Spinbox(f, from_=1, to=168, textvariable=self.nw_h, width=4).pack(side="left", padx=3)

        f = ttk.Frame(g); f.pack(fill="x", pady=2)
        ttk.Label(f, text="🔑 Key Vilao:").pack(side="left")
        # Key go tay: uu tien hon env/.env -> doi key khong phai sua .env.
        # Luu vao config.json nen lan sau mo tool khong phai go lai.
        self.nw_key = tk.StringVar(value=str(self.cfg.get("vilao_key", "") or ""))
        self.nw_key_ent = tk.Entry(f, textvariable=self.nw_key, width=34,
                                   show="*")
        self.nw_key_ent.pack(side="left", padx=3)
        self.nw_key_show = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, text="Hiện", variable=self.nw_key_show,
                        command=self._news_toggle_key).pack(side="left")
        ttk.Label(f, text="(để trống = đọc từ .env)", foreground="#666"
                  ).pack(side="left", padx=(6, 0))
        ttk.Button(f, text="Lưu key", command=self._news_save_key).pack(
            side="left", padx=(6, 0))

        f = ttk.Frame(g); f.pack(fill="x", pady=2)
        ttk.Label(f, text="Chủ đề:").pack(side="left")
        self.nw_topics = {}
        for nm in ("Chính trị Mỹ", "Thế giới", "Kinh tế", "Khoa học"):
            v = tk.BooleanVar(value=nm in (self.cfg.get("news_topics") or ["Chính trị Mỹ"]))
            self.nw_topics[nm] = v
            ttk.Checkbutton(f, text=nm, variable=v).pack(side="left", padx=3)

        f = ttk.Frame(g); f.pack(fill="x", pady=3)
        self.nw_btn = ttk.Button(f, text="🔄 Lấy tin nóng 24h",
                                 command=self._news_fetch)
        self.nw_btn.pack(side="left", padx=2, ipadx=8)
        self.nw_test_btn = ttk.Button(f, text="🔑 Kiểm tra key AI",
                                      command=self._news_test_key)
        self.nw_test_btn.pack(side="left", padx=2)
        self.nw_score = tk.BooleanVar(value=bool(self.cfg.get("news_score", True)))
        ttk.Checkbutton(f, text="Chấm điểm độ nóng",
                        variable=self.nw_score).pack(side="left", padx=(8, 0))
        self.nw_status = ttk.Label(f, text="", foreground="#0a6", wraplength=700,
                                   justify="left")
        self.nw_status.pack(side="left", padx=8)

        # Danh sách tin — Treeview để CUỘN ĐƯỢC (chuột + thanh cuộn)
        lw = ttk.Frame(g); lw.pack(fill="both", expand=True, pady=3)
        cols = ("hot", "hook", "src", "age")
        self.nw_tree = ttk.Treeview(lw, columns=cols, show="tree headings",
                                    height=9, selectmode="extended")
        self.nw_tree.heading("#0", text="Tin nóng")
        self.nw_tree.heading("hot", text="Độ nóng")
        self.nw_tree.heading("hook", text="Hook")
        self.nw_tree.heading("src", text="Nguồn")
        self.nw_tree.heading("age", text="Giờ")
        self.nw_tree.column("#0", width=430, stretch=True, anchor="w")
        self.nw_tree.column("hot", width=140, stretch=False, anchor="w")
        self.nw_tree.column("hook", width=62, stretch=False, anchor="w")
        self.nw_tree.column("src", width=120, stretch=False, anchor="w")
        self.nw_tree.column("age", width=50, stretch=False, anchor="e")
        sbv = ttk.Scrollbar(lw, orient="vertical", command=self.nw_tree.yview)
        sbh = ttk.Scrollbar(g, orient="horizontal", command=self.nw_tree.xview)
        self.nw_tree.configure(yscrollcommand=sbv.set, xscrollcommand=sbh.set)
        self.nw_tree.pack(side="left", fill="both", expand=True)
        sbv.pack(side="right", fill="y")
        sbh.pack(fill="x")
        # lăn chuột trong khung tin
        self.nw_tree.bind("<MouseWheel>",
                          lambda e: self.nw_tree.yview_scroll(int(-e.delta / 120), "units"))
        self.nw_tree.bind("<Double-Button-1>", lambda e: self._news_use_one())
        self.nw_tree.bind("<ButtonRelease-1>", lambda e: self._news_show_why())

        f = ttk.Frame(g); f.pack(fill="x", pady=2)
        ttk.Button(f, text="⬆ Dùng tin này cho banner",
                   command=self._news_use_one).pack(side="left", padx=2)
        ttk.Button(f, text="⬆ Làm video cho TẤT CẢ tin",
                   command=self._news_use_all).pack(side="left", padx=2)
        ttk.Button(f, text="📋 Xuất JSON", command=self._news_export).pack(side="left", padx=2)
        ttk.Button(f, text="📂 Mở link gốc", command=self._news_open_link).pack(side="left", padx=2)
        self.nw_why = ttk.Label(g, text="", foreground="#06c", wraplength=900,
                                justify="left")
        self.nw_why.pack(anchor="w")
        ttk.Label(g, text="Nguồn tin: Google News RSS (miễn phí, có giờ đăng thật). "
                          "Gemini chỉ chia lại tiêu đề + gợi ý từ khoá ảnh — "
                          "không được phép bịa tin.\n"
                          "Độ nóng = đếm số BÁO khác nhau đưa cùng tin (24h) + Google Trends. "
                          "Đây là mức độ báo chí đưa tin — KHÔNG phải dự đoán viral.",
                  foreground="#666").pack(anchor="w")

        # 1. Nguồn video
        g = ttk.LabelFrame(body, text="1. Nguồn video (folder chứa mp4 đã render)", padding=6)
        g.pack(fill="x", **pad)
        f = ttk.Frame(g); f.pack(fill="x")
        ttk.Button(f, text="➕ Thêm folder", command=self._bn_add).pack(side="left")
        ttk.Button(f, text="➖ Xoá mục chọn", command=self._bn_del).pack(side="left", padx=4)
        ttk.Button(f, text="🗑 Xoá hết", command=self._bn_clear).pack(side="left")
        self.bn_count = tk.StringVar(value="0 folder")
        ttk.Label(f, textvariable=self.bn_count, foreground="#0a6").pack(side="left", padx=10)
        self.bn_list = tk.Listbox(g, height=5, selectmode="extended")
        self.bn_list.pack(fill="x", pady=3)
        f2 = ttk.Frame(g); f2.pack(fill="x")
        self.bn_rec = tk.BooleanVar(value=False)
        ttk.Checkbutton(f2, text="Quét cả folder con", variable=self.bn_rec).pack(side="left")
        ttk.Label(f2, text="   Video đã có banner sẽ bị ghi đè").pack(side="left")

        # 2. Chữ trên banner  ← PHẦN SỬA ĐƯỢC
        g = ttk.LabelFrame(body, text="2. Chữ trên banner (sửa trực tiếp)", padding=6)
        g.pack(fill="x", **pad)
        f = ttk.Frame(g); f.pack(fill="x")
        self._bn_entry(f, "Ô đỏ:", "red_text", width=22)
        self._bn_entry(f, "Logo:", "logo_text", width=8)
        self.bn_logo = tk.BooleanVar(value=bool(self.bcfg.get("show_logo", True)))
        self.bvars["show_logo"] = self.bn_logo
        ttk.Checkbutton(f, text="Hiện logo", variable=self.bn_logo).pack(side="left", padx=6)
        f = ttk.Frame(g); f.pack(fill="x", pady=(4, 0))
        self._bn_entry(f, "Chữ trắng (tiêu đề):", "white_text", width=68)
        ttk.Label(f, text="  Số dòng:").pack(side="left")
        self.bn_wlines = tk.IntVar(value=int(self.bcfg.get("white_lines", 2) or 2))
        self.bvars["white_lines"] = self.bn_wlines
        tk.Spinbox(f, from_=1, to=4, textvariable=self.bn_wlines,
                   width=3).pack(side="left", padx=3)

        # 2b. CTA — "FULL STORY IN THE FIRST COMMENT" (mặc định ở ĐẦU video)
        g = ttk.LabelFrame(body, text="2b. Chữ CTA — “FULL STORY IN THE FIRST COMMENT”", padding=6)
        g.pack(fill="x", **pad)
        self.bn_cta = tk.BooleanVar(value=bool(self.bcfg.get("cta_enabled", True)))
        self.bvars["cta_enabled"] = self.bn_cta
        f = ttk.Frame(g); f.pack(fill="x")
        ttk.Checkbutton(f, text="Bật CTA", variable=self.bn_cta).pack(side="left", padx=(0, 6))
        self._bn_entry(f, "Dòng 1:", "cta_line1", width=26)
        self._bn_entry(f, "Dòng 2:", "cta_line2", width=26)
        f = ttk.Frame(g); f.pack(fill="x", pady=(3, 0))
        self._bn_spin(f, "Số giây cuối hiện:", "cta_dur", 0.5, 20, 0.5, 6)
        self._bn_spin(f, "y (đầu video = 0):", "cta_y", 0, 1, 0.001, 7)
        self._bn_spin(f, "cao cả khối:", "cta_h", 0.02, 0.4, 0.001, 7)
        self._bn_spin(f, "khe 2 dòng:", "cta_line_gap", 0.2, 3, 0.01, 5)
        for lab, k, dflt in (("Chữ:", "cta_color", "#ECFA1E"),
                             ("Viền:", "cta_outline", "#000000")):
            cur = self.bcfg.get(k, BANNER_DEFAULTS.get(k))
            if isinstance(cur, (list, tuple)):
                cur = "#%02X%02X%02X" % tuple(int(x) for x in cur[:3])
            ttk.Label(f, text=lab).pack(side="left", padx=(6, 2))
            v = tk.StringVar(value=str(cur))
            self.bvars[k] = v
            tk.Entry(f, textvariable=v, width=9).pack(side="left")
        self._bn_spin(f, "độ dày viền (px@1080):", "cta_outline_w", 0, 20, 1, 4)
        f = ttk.Frame(g); f.pack(fill="x", pady=(3, 0))
        ttk.Label(f, text="Mặc định: 3s cuối · chữ vàng #ECFA1E viền đen, font Impact, "
                          "nằm Ở TRÊN ĐẦU video (đo từ ảnh mẫu user gửi)",
                  foreground="#777").pack(side="left", padx=4)

        # 3. Vị trí & kích thước (tỉ lệ khung hình) — san 2 CỘT
        g = ttk.LabelFrame(body, text="3. Vị trí & kích thước — tỉ lệ khung (đo từ video mẫu)",
                           padding=6)
        g.pack(fill="x", **pad)
        # colL/colR phải nằm trong 1 hàng riêng: trộn side="left" và side="top"
        # trong cùng khung làm Tk cộng dồn chiều rộng (tràn ngang)
        row = ttk.Frame(g); row.pack(fill="x")
        colL = ttk.Frame(row); colL.pack(side="left", fill="both", expand=True)
        colR = ttk.Frame(row); colR.pack(side="left", fill="both", expand=True)
        f = ttk.Frame(colL); f.pack(fill="x", pady=(2, 0))
        ttk.Label(f, text="Ô ĐỎ  x/y/w/h:", foreground="#c00").pack(side="left", padx=(4, 2))
        f = ttk.Frame(colL); f.pack(fill="x", pady=2)
        for k, hi in (("red_x", 1), ("red_y", 1), ("red_w", 1), ("red_h", 0.3)):
            self._bn_spin(f, k.split("_")[1] + ":", k, 0, hi, 0.001, 7)
        f = ttk.Frame(colR); f.pack(fill="x", pady=(2, 0))
        ttk.Label(f, text="Ô TRẮNG x/y/w/h:", foreground="#666").pack(side="left", padx=(4, 2))
        f = ttk.Frame(colR); f.pack(fill="x", pady=2)
        for k, hi in (("white_x", 1), ("white_y", 1), ("white_w", 1), ("white_h", 0.3)):
            self._bn_spin(f, k.split("_")[1] + ":", k, 0, hi, 0.001, 7)
        f = ttk.Frame(g); f.pack(fill="x", pady=(3, 0))
        ttk.Button(f, text="↺ Về mặc định (đúng video mẫu)",
                   command=self._bn_reset_pos).pack(side="left", padx=4)
        ttk.Label(f, text="   Đo từ MELANIA.mp4: ô đỏ x24 y471 w124 h28 · ô trắng x28 y499 w308 h37 (khung 360x640)",
                  foreground="#777").pack(side="left")

        # 4. Màu — san 2 CỘT
        g = ttk.LabelFrame(body, text="4. Màu (hex)", padding=6)
        g.pack(fill="x", **pad)
        row = ttk.Frame(g); row.pack(fill="x")
        colL = ttk.Frame(row); colL.pack(side="left", fill="both", expand=True)
        colR = ttk.Frame(row); colR.pack(side="left", fill="both", expand=True)
        for i, (lab, k, dflt) in enumerate((("Nền đỏ:", "red_color", "#CC0000"),
                                            ("Nền trắng:", "white_color", "#FFFFFF"),
                                            ("Chữ ô đỏ:", "red_text_color", "#FFFFFF"),
                                            ("Chữ tiêu đề:", "white_text_color", "#0C0C0C"),
                                            ("Logo:", "logo_color", "#CC0000"))):
            cur = self.bcfg.get(k, BANNER_DEFAULTS.get(k))
            if isinstance(cur, (list, tuple)):
                cur = "#%02X%02X%02X" % tuple(int(x) for x in cur[:3])
            f = ttk.Frame(colL if i < 3 else colR); f.pack(fill="x", pady=1)
            ttk.Label(f, text=lab, width=12).pack(side="left", padx=(2, 2))
            v = tk.StringVar(value=str(cur))
            self.bvars[k] = v
            tk.Entry(f, textvariable=v, width=10).pack(side="left")
        self.bn_shadow = tk.BooleanVar(value=bool(self.bcfg.get("shadow", True)))
        self.bvars["shadow"] = self.bn_shadow
        f = ttk.Frame(colR); f.pack(fill="x", pady=1)
        ttk.Checkbutton(f, text="Đổ bóng", variable=self.bn_shadow).pack(side="left", padx=6)

        # 5. KHUNG MC "NEWS" (PiP) — nằm NGAY TRÊN khung BREAKING NEWS
        g = ttk.LabelFrame(body, text="5. Khung MC “NEWS” — nằm trên khung BREAKING NEWS",
                           padding=6)
        g.pack(fill="x", **pad)
        f = ttk.Frame(g); f.pack(fill="x", pady=2)
        self.bn_pip_on = tk.BooleanVar(value=bool(self.bcfg.get("pip_enabled", False)))
        self.bvars["pip_enabled"] = self.bn_pip_on
        ttk.Checkbutton(f, text="Có MC  →  bật khung trên banner",
                        variable=self.bn_pip_on).pack(side="left", padx=(2, 10))
        ttk.Label(f, text="(tích vào là khung MC hiện; bỏ tích = không khung)",
                  foreground="#777").pack(side="left", padx=4)
        f = ttk.Frame(g); f.pack(fill="x", pady=2)
        self._bn_entry(f, "Nhãn ô đỏ:", "pip_tag_text", width=10)

        f = ttk.Frame(g); f.pack(fill="x", pady=2)
        ttk.Label(f, text="Ảnh/video MC:", width=12).pack(side="left", padx=(2, 2))
        self._bn_entry(f, "", "pip_src", width=52)
        ttk.Button(f, text="📄", width=3, command=self._bn_pick_pip_src).pack(side="left", padx=2)
        ttk.Button(f, text="👁 Xem thử khung", command=self._bn_pip_preview).pack(side="left", padx=6)

        f = ttk.Frame(g); f.pack(fill="x", pady=2)
        ttk.Label(f, text="Hoặc folder MC:", width=12).pack(side="left", padx=(2, 2))
        self._bn_entry(f, "", "pip_folder", width=52)
        ttk.Button(f, text="📁", width=3, command=self._bn_pick_pip_folder).pack(side="left", padx=2)
        ttk.Label(f, text="(bốc ngẫu nhiên mỗi video)", foreground="#777").pack(side="left", padx=4)

        # kích thước + vị trí — san 2 cột
        row = ttk.Frame(g); row.pack(fill="x", pady=(3, 0))
        colL = ttk.Frame(row); colL.pack(side="left", fill="both", expand=True)
        colR = ttk.Frame(row); colR.pack(side="left", fill="both", expand=True)
        f = ttk.Frame(colL); f.pack(fill="x", pady=1)
        self._bn_spin(f, "rộng:", "pip_w", 0.05, 1, 0.001, 7)
        self._bn_spin(f, "cao:", "pip_h", 0.05, 1, 0.001, 7)
        f = ttk.Frame(colL); f.pack(fill="x", pady=1)
        ttk.Label(f, text="Lề trái: BẰNG KHUNG BREAKING NEWS (cố định)",
                  foreground="#0A5").pack(side="left", padx=(4, 2))
        self._bn_spin(f, "viền dày:", "pip_border_w", 0, 0.12, 0.001, 7)
        f = ttk.Frame(colL); f.pack(fill="x", pady=1)
        self._bn_spin(f, "zoom:", "pip_zoom", 1, 3, 0.01, 7)
        self._bn_spin(f, "focus dọc:", "pip_focus_y", 0, 1, 0.01, 7)
        # Cắt lề nguồn để che watermark/logo app (DreamFace...) — 4 cạnh
        f = ttk.Frame(colL); f.pack(fill="x", pady=1)
        self._bn_spin(f, "cắt trên:", "pip_crop_top", 0, 0.45, 0.01, 6)
        self._bn_spin(f, "cắt dưới:", "pip_crop_bottom", 0, 0.45, 0.01, 6)
        f = ttk.Frame(colL); f.pack(fill="x", pady=1)
        self._bn_spin(f, "cắt trái:", "pip_crop_left", 0, 0.45, 0.01, 6)
        self._bn_spin(f, "cắt phải:", "pip_crop_right", 0, 0.45, 0.01, 6)
        f = ttk.Frame(colR); f.pack(fill="x", pady=1)
        self.bn_pip_auto = tk.BooleanVar(value=bool(self.bcfg.get("pip_auto_y", True)))
        self.bvars["pip_auto_y"] = self.bn_pip_auto
        ttk.Checkbutton(f, text="Tự neo ngay trên banner (khuyên dùng)",
                        variable=self.bn_pip_auto).pack(side="left", padx=4)
        f = ttk.Frame(colR); f.pack(fill="x", pady=1)
        self._bn_spin(f, "khe hở:", "pip_gap", 0, 0.1, 0.001, 7)
        for lab, k, dflt in (("Viền khung:", "pip_border_color", "#0A1E69"),
                             ("Nền nhãn:", "pip_tag_color", "#CC0000")):
            cur = self.bcfg.get(k, BANNER_DEFAULTS.get(k))
            if isinstance(cur, (list, tuple)):
                cur = "#%02X%02X%02X" % tuple(int(x) for x in cur[:3])
            f = ttk.Frame(colR); f.pack(fill="x", pady=1)
            ttk.Label(f, text=lab, width=11).pack(side="left", padx=(2, 2))
            v = tk.StringVar(value=str(cur))
            self.bvars[k] = v
            tk.Entry(f, textvariable=v, width=9).pack(side="left")
        f = ttk.Frame(g); f.pack(fill="x", pady=(3, 0))
        ttk.Label(f, text="Ảnh MC được COVER + crop đúng khung → luôn bó trong khung, không tràn. "
                          "Khung tự neo cách thanh đỏ 0.8%H.",
                  foreground="#777").pack(side="left", padx=4)

        # 6. Nơi lưu
        g = ttk.LabelFrame(body, text="6. Nơi lưu", padding=6)
        g.pack(fill="x", **pad)
        f = ttk.Frame(g); f.pack(fill="x")
        self.bn_out = tk.StringVar(value=self.bcfg.get("out_dir") or str(OUTPUT))
        self.bvars["out_dir"] = self.bn_out
        tk.Entry(f, textvariable=self.bn_out, width=68).pack(side="left", padx=(2, 4))
        ttk.Button(f, text="📁", width=3, command=self._bn_pick_out).pack(side="left")
        self.bn_copyz = tk.BooleanVar(value=bool(self.bcfg.get("copy_z", False)))
        self.bvars["copy_z"] = self.bn_copyz
        ttk.Checkbutton(f, text="Copy lên Z:", variable=self.bn_copyz).pack(side="left", padx=8)

        self._bn_refresh()

        # 7. Tìm ảnh theo tin — KHÔNG cần API key (Wikimedia + Openverse)
        g = ttk.LabelFrame(body, text="7. Tìm ảnh theo tin (tự tải theo từ khoá AI)",
                           padding=6)
        g.pack(fill="x", **pad)
        f = ttk.Frame(g); f.pack(fill="x", pady=2)
        ttk.Label(f, text="Từ khoá:").pack(side="left")
        self.im_kw = tk.StringVar(value=str(self.cfg.get("img_keywords", "") or ""))
        tk.Entry(f, textvariable=self.im_kw, width=62).pack(side="left", padx=3)
        ttk.Button(f, text="⬅ Lấy từ tin đang chọn",
                   command=self._img_kw_from_news).pack(side="left", padx=3)

        f = ttk.Frame(g); f.pack(fill="x", pady=2)
        ttk.Label(f, text="Nơi lưu:").pack(side="left")
        self.im_out = tk.StringVar(value=str(self.cfg.get("img_dir", "") or ""))
        tk.Entry(f, textvariable=self.im_out, width=52).pack(side="left", padx=3)
        ttk.Button(f, text="📁", width=3, command=self._img_pick_out).pack(side="left")
        ttk.Button(f, text="↗ Mở folder", command=self._img_open_out).pack(
            side="left", padx=3)

        f = ttk.Frame(g); f.pack(fill="x", pady=2)
        ttk.Label(f, text="Số ảnh / từ khoá:").pack(side="left")
        self.im_n = tk.IntVar(value=int(self.cfg.get("img_per_kw", 3) or 3))
        tk.Spinbox(f, from_=1, to=20, textvariable=self.im_n, width=4).pack(
            side="left", padx=3)
        ttk.Label(f, text="Nguồn:").pack(side="left", padx=(10, 0))
        self.im_src = tk.StringVar(value=str(self.cfg.get(
            "img_sources", "wikimedia") or "wikimedia"))
        ttk.Combobox(f, textvariable=self.im_src, width=22, state="readonly",
                     values=("wikimedia+openverse", "wikimedia",
                             "openverse")).pack(side="left", padx=3)
        self.im_addfolder = tk.BooleanVar(value=bool(self.cfg.get(
            "img_add_folder", True)))
        ttk.Checkbutton(f, text="Thêm folder vào danh sách nguồn video",
                        variable=self.im_addfolder).pack(side="left", padx=(10, 0))

        f = ttk.Frame(g); f.pack(fill="x", pady=3)
        self.im_btn = ttk.Button(f, text="🖼 Tìm + tải ảnh",
                                 command=self._img_fetch)
        self.im_btn.pack(side="left", padx=2, ipadx=8)
        self.im_status = ttk.Label(f, text="", foreground="#0a6", wraplength=620,
                                   justify="left")
        self.im_status.pack(side="left", padx=8)
        ttk.Label(g, text="Nguồn miễn phí KHÔNG cần API key: Wikimedia Commons "
                          "(ảnh chính phủ Mỹ = Public Domain). "
                          "Chỉ lấy ảnh CC0 / Public Domain / CC-BY (dùng thương mại "
                          "được); tự bỏ CC BY-SA, ND, NC.\n"
                          "Chỉ nhận ảnh đủ nét sau khi cắt dọc 9:16 (Openverse/Flickr "
                          "thường chỉ 500-1024px -> mờ, nên để TẮT mặc định).\n"
                          "Mỗi ảnh tải về đều ghi nguồn + tác giả vào credits.txt "
                          "trong folder ảnh.",
                  foreground="#666").pack(anchor="w")

    # ── mục 7: tìm ảnh theo tin ────────────────────────────
    def _img_kw_from_news(self):
        """Lấy từ khoá của tin đang chọn (AI đã sinh sẵn trong item['keyword'])."""
        it = self._news_sel()
        if not it:
            self.blog("! Chọn 1 tin trong bảng 'Tin nóng 24h' trước.")
            return
        kw = str(it.get("keyword") or "").strip()
        if not kw:
            kw = str(it.get("title") or "").strip()
        self.im_kw.set(kw)
        self.blog(f"→ Từ khoá: {kw}")

    def _img_sources_sel(self):
        s = str(self.im_src.get() or "").lower()
        if "wikimedia" in s and "openverse" in s:
            return ("wikimedia", "openverse")
        if "wikimedia" in s:
            return ("wikimedia",)
        if "openverse" in s:
            return ("openverse",)
        return images_mod.SOURCES

    def _img_out_dir(self) -> Path:
        p = (self.im_out.get() or "").strip()
        if not p:
            # mặc định: output/Anh_Theo_Tin (cạnh các video đã render)
            p = str(OUTPUT / "Anh_Theo_Tin")
            self.im_out.set(p)
        return Path(p)

    def _img_pick_out(self):
        p = filedialog.askdirectory(title="Chọn folder lưu ảnh")
        if p:
            self.im_out.set(p)
            self.save_config()

    def _img_open_out(self):
        try:
            d = self._img_out_dir()
            d.mkdir(parents=True, exist_ok=True)
            os.startfile(str(d))            # noqa: S606 (Windows)
        except Exception as e:
            self.blog(f"! Không mở được folder: {e}")

    def _img_fetch(self):
        """Tìm + tải ảnh trong luồng nền (mạng chậm, không được treo GUI)."""
        if getattr(self, "_img_busy", False):
            return
        kws = [x.strip() for x in
               re.split(r"[,;\n]+", self.im_kw.get() or "") if x.strip()]
        if not kws:
            self.blog("! Nhập từ khoá trước (hoặc bấm 'Lấy từ tin đang chọn').")
            return
        self._img_busy = True
        self.save_config()
        self.im_btn.config(state="disabled")
        # Đọc widget Tk ở MAIN THREAD (đọc từ thread nền -> Tcl ném lỗi)
        try:
            per = max(1, min(20, int(self.im_n.get())))
        except Exception:
            per = 3
        srcs = self._img_sources_sel()
        add_folder = bool(self.im_addfolder.get())
        out_dir = self._img_out_dir()
        self.im_status.config(text=f"Đang tìm {len(kws)} từ khoá...",
                              foreground="#a60")
        self.blog(f"→ Tìm ảnh: {len(kws)} từ khoá × {per} ảnh → {out_dir}")

        def work():
            ok = 0
            try:
                got = images_mod.find_for_keywords(
                    kws, out_dir, per_kw=per, sources=srcs, log=self.blog)
                ok = len(got)
                if ok:
                    self.blog(f"✓ {ok} ảnh → {out_dir}")
                else:
                    self.blog("! Không tải được ảnh nào — thử từ khoá tiếng Anh "
                              "đơn giản hơn (vd: 'US Capitol').")
            except Exception as e:
                self.blog(f"! Lỗi tìm ảnh: {e}")

            def done():
                self._img_busy = False
                self.im_btn.config(state="normal")
                if ok:
                    self.im_status.config(
                        text=f"✓ {ok} ảnh → {out_dir.name}", foreground="#0a6")
                    # tiện: thêm folder ảnh vào danh sách nguồn video tab 1
                    if add_folder:
                        try:
                            s = str(out_dir)
                            if s not in self.folders:
                                self.folders.append(s)
                                self._refresh()
                                self.log(f"Đã thêm folder ảnh vào nguồn video: {s}")
                        except Exception:
                            pass
                else:
                    self.im_status.config(text="Không có ảnh nào tải được.",
                                          foreground="#c00")
            self.root.after(0, done)
        threading.Thread(target=work, daemon=True).start()

    # ── tab 2: helpers ─────────────────────────────────────
    def blog(self, m):
        def do():
            self.bn_log_box.config(state="normal")
            self.bn_log_box.insert("end", str(m) + "\n")
            self.bn_log_box.see("end")
            self.bn_log_box.config(state="disabled")
        self.root.after(0, do)

    # ── tab 2: TIN NÓNG 24H ────────────────────────────────
    def _news_topics_sel(self):
        sel = [k for k, v in self.nw_topics.items() if v.get()]
        return sel or ["Chính trị Mỹ"]

    def _news_save_cfg(self):
        try:
            self.cfg["news_use_gemini"] = bool(self.nw_use.get())
            self.cfg["news_limit"] = int(self.nw_n.get())
            self.cfg["news_hours"] = int(self.nw_h.get())
            self.cfg["news_topics"] = self._news_topics_sel()
            try:
                self.cfg["news_score"] = bool(self.nw_score.get())
            except Exception:
                pass
            try:
                self.cfg["news_ai"] = str(self.nw_ai.get() or "vilao")
            except Exception:
                pass
            try:
                self.cfg["news_model"] = str(self.nw_model.get() or "").strip()
            except Exception:
                pass
            try:
                self.cfg["vilao_key"] = str(self.nw_key.get() or "").strip()
            except Exception:
                pass
            # mục 7: tìm ảnh theo tin
            for key, var in (("img_keywords", "im_kw"), ("img_dir", "im_out"),
                             ("img_sources", "im_src")):
                try:
                    self.cfg[key] = str(getattr(self, var).get() or "").strip()
                except Exception:
                    pass
            try:
                self.cfg["img_per_kw"] = max(1, min(20, int(self.im_n.get())))
            except Exception:
                pass
            try:
                self.cfg["img_add_folder"] = bool(self.im_addfolder.get())
            except Exception:
                pass
        except Exception:
            pass

    # ── tab 2: KEY VILAO ───────────────────────────────────
    def _news_toggle_key(self):
        """Hiện/ẩn ký tự trong ô key."""
        try:
            self.nw_key_ent.config(show="" if self.nw_key_show.get() else "*")
        except Exception:
            pass

    def _news_save_key(self):
        """Lưu key Vilao vào config.json để lần sau mở tool không phải gõ lại."""
        self._news_save_cfg()
        try:
            CONFIG_F.write_text(json.dumps(self.cfg, ensure_ascii=False, indent=2),
                                encoding="utf-8")
        except Exception as e:
            self.blog(f"! Không ghi được config: {e}")
            return
        # KHONG in gia tri key — chi bao co/khong.
        if (self.nw_key.get() or "").strip():
            self.blog("✓ Đã lưu key Vilao vào config.json.")
            self.nw_status.config(text="Đã lưu key Vilao.", foreground="#0a6")
        else:
            self.blog("✓ Đã xoá key Vilao (dùng .env).")
            self.nw_status.config(text="Đã xoá key — sẽ đọc từ .env.",
                                  foreground="#0a6")

    def _news_load_models(self):
        """Nạp danh sách model THẬT từ Vilao rồi đổ vào ô chọn.

        Vilao thêm model liên tục nên danh sách hardcode sẽ lỗi thời — luôn
        lấy từ /v1/models. Vẫn gõ tay được nếu muốn.
        """
        self.blog("Đang nạp danh sách model từ Vilao (/v1/models)...")
        user_key = (self.nw_key.get() or "").strip() if hasattr(self, "nw_key") else ""

        def work():
            key, src = news_mod.find_vilao_key(user_key=user_key)
            if not key:
                self.blog("! Không tìm thấy key Vilao.")
                self.root.after(0, lambda: self.nw_status.config(
                    text="Không tìm thấy key Vilao", foreground="#c00"))
                return
            models = news_mod.list_vilao_models(key)
            if not models:
                self.blog("! Không nạp được danh sách model (kiểm tra mạng).")
                self.root.after(0, lambda: self.nw_status.config(
                    text="Không nạp được danh sách model", foreground="#c00"))
                return
            self.blog("  %d model: %s" % (len(models), ", ".join(models)))

            def apply():
                self.nw_mbox.config(values=tuple(models))
                self.cfg["news_models_cache"] = list(models)
                try:
                    self._news_save_cfg()      # gom vao cfg
                    CONFIG_F.write_text(       # ghi NGAY ra dia (khong cho
                        json.dumps(self.cfg, ensure_ascii=False, indent=2),
                        encoding="utf-8")      # den luc dong tool moi luu)
                except Exception:
                    pass
                self.nw_status.config(
                    text="Đã nạp %d model từ Vilao — chọn hoặc gõ tay tên model."
                         % len(models), foreground="#0a6")
            self.root.after(0, apply)
        threading.Thread(target=work, daemon=True).start()

    def _news_test_key(self):
        which = self.nw_ai.get() if hasattr(self, "nw_ai") else "vilao"
        model = (self.nw_model.get() or "").strip() if hasattr(self, "nw_model") else ""
        ukey = (self.nw_key.get() or "").strip() if hasattr(self, "nw_key") else ""

        def work():
            out = []
            for name in (("vilao", "gemini") if which == "auto" else (which,)):
                if name == "vilao":
                    key, src = news_mod.find_vilao_key(user_key=ukey)
                    label, mk = "Vilao", news_mod.Vilao
                else:
                    key, src = news_mod.find_gemini_key()
                    label, mk = "Gemini", news_mod.Gemini
                if not key:
                    out.append(f"{label}: không tìm thấy key")
                    self.blog(f"! Không tìm thấy key {label} (env / .env / config).")
                    continue
                self.blog(f"Kiểm tra key {label} từ {src}...")
                # kiem tra dung model dang chon (neu go tay va la Vilao)
                if name == "vilao" and model:
                    mlist = [model] + [m for m in news_mod.VILAO_MODELS
                                       if m != model]
                    cli = mk(key, models=mlist, log=self.blog)
                else:
                    cli = mk(key, log=self.blog)
                ok, msg = cli.ok()
                self.blog(("  ✓ " if ok else "  ✗ ") + f"{label}: {msg}")
                out.append(f"{label}: {'OK' if ok else msg}")
            txt = " · ".join(out)
            ok_any = any("OK" in x and "không" not in x for x in out)
            self.root.after(0, lambda: self.nw_status.config(
                text=txt, foreground="#0a6" if ok_any else "#c00"))
        threading.Thread(target=work, daemon=True).start()

    def _news_fetch(self):
        if getattr(self, "_news_busy", False):
            return
        self._news_busy = True
        self._news_save_cfg()
        self.nw_btn.config(state="disabled")
        self.nw_status.config(text="Đang lấy tin...", foreground="#a60")
        topics = self._news_topics_sel()
        try:
            n = int(self.nw_n.get())
            hrs = int(self.nw_h.get())
        except Exception:
            n, hrs = 8, 24
        use_gem = bool(self.nw_use.get())
        # PHAI doc bien Tk o MAIN THREAD: doc tu thread nen -> Tcl nem
        # "main thread is not in main loop" (da gap that 2026-10-03).
        use_score = bool(self.nw_score.get())
        use_ai = self.nw_ai.get() if hasattr(self, "nw_ai") else "vilao"
        use_model = (self.nw_model.get() or "").strip() if hasattr(self, "nw_model") else ""
        # Key go tay trong o GUI (uu tien hon .env). Doc o MAIN THREAD.
        use_key = (self.nw_key.get() or "").strip() if hasattr(self, "nw_key") else ""

        def work():
            hot_mod = None
            try:
                from core import hotness as _hm
                hot_mod = _hm
            except Exception as e:
                self.blog(f"! Không nạp được module chấm điểm: {e}")
            try:
                items, note = news_mod.build_plan(
                    topics=topics, hours=hrs, limit=n, use_gemini=use_gem,
                    ai=use_ai, model=use_model, vilao_key=use_key, log=self.blog)
                # Chấm điểm độ nóng (đếm số báo đưa tin + Google Trends).
                # Đây là TÍN HIỆU THẬT nhưng KHÔNG dự đoán viral — xem
                # docstring core/hotness.py.
                if hot_mod is not None and use_score and items:
                    try:
                        items = hot_mod.score_items(items, log=self.blog)
                    except Exception as e:
                        self.blog(f"! Chấm điểm lỗi (bỏ qua): {e}")
                self.news_items = items
                def show():
                    self.nw_tree.delete(*self.nw_tree.get_children())
                    for i, it in enumerate(items, 1):
                        f = it.get("faith", 1.0)
                        mark = "" if f >= 0.5 else " ⚠"
                        lab = ""
                        if hot_mod is not None and it.get("sources") is not None:
                            lab = hot_mod.hot_label(it)
                        self.nw_tree.insert(
                            "", "end", iid=str(i - 1),
                            text="%2d. %s%s" % (i, it["title"][:58], mark),
                            values=(lab, _hook_label(it.get("hook")),
                                    it["source"][:16],
                                    "%4.1fh" % it["age_h"]))
                    self.nw_status.config(text=note, foreground="#0a6")
                    self.blog(f"→ {len(items)} tin sẵn sàng. Bấm 'Dùng tin này' để đổ vào banner.")
                self.root.after(0, show)
            except Exception as e:
                self.blog(f"! Lỗi lấy tin: {e}")
                self.root.after(0, lambda: self.nw_status.config(
                    text=f"Lỗi: {e}", foreground="#c00"))
            finally:
                self._news_busy = False
                self.root.after(0, lambda: self.nw_btn.config(state="normal"))
        threading.Thread(target=work, daemon=True).start()

    def _news_show_why(self):
        """Hiện giải thích điểm của tin đang chọn (giải thích, KHÔNG hứa viral)."""
        try:
            from core import hotness as hot_mod
        except Exception:
            return
        it = self._news_sel()
        if not it:
            return
        lab = hot_mod.hot_label(it)
        txt = ("Điểm nóng %.0f/100 — %s" % (it.get("hot") or 0, hot_mod.why(it))
               if lab else "")
        self.nw_why.config(text=txt)

    def _news_sel(self):
        it = getattr(self, "news_items", None) or []
        sel = self.nw_tree.selection()
        if not sel:
            return None
        try:
            i = int(sel[0])
        except Exception:
            return None
        return it[i] if 0 <= i < len(it) else None

    def _news_to_banner(self, item):
        """Đổ tiêu đề + nguồn vào ô banner của tab 2."""
        lines = item.get("lines") or _break_lines(item["title"], 3, 34)
        if len(lines) == 1:
            lines = _break_lines(item["title"], 3, 34)
        # tiêu đề tin thật dài hơn mẫu CNN → mở rộng số dòng cho vừa
        if len(lines) > 2 and "white_lines" in self.bvars:
            try:
                if int(self.bvars["white_lines"].get()) < min(4, len(lines)):
                    self.bvars["white_lines"].set(min(4, len(lines)))
            except Exception:
                pass
        # KHONG noi nguon/gio vao tieu de banner nua (user yeu cau 2026-10-03):
        # banner chi con 3 dong tieu de. Nguon/gio van hien trong bang tab 2.
        txt = "\n".join(lines)
        if "white_text" in self.bvars:
            self.bvars["white_text"].set(txt)
        src = item.get("source") or ""
        age = item.get("age_h")
        info = f" (nguồn {src}" if src else ""
        if age is not None:
            info += (" · %.1fh" % age) if age >= 1 else (" · %dm" % max(1, int(age * 60)))
        info += ")" if info else ""
        self.blog("Đã đổ vào ô 'Chữ trắng (tiêu đề)':\n" + txt + info)

    def _news_use_one(self):
        it = self._news_sel()
        if not it:
            self.blog("! Chọn 1 tin trong danh sách trước (hoặc nháy đúp).")
            return
        self._news_to_banner(it)
        self.nw_status.config(text=f"Đã đổ tin: {it['title'][:60]}", foreground="#0a6")

    def _news_use_all(self):
        it = getattr(self, "news_items", None) or []
        if not it:
            self.blog("! Chưa có tin nào — bấm 'Lấy tin nóng 24h' trước.")
            return
        if not messagebox.askyesno(
                "Làm video cho tất cả tin",
                f"Sẽ đổ tiêu đề của {len(it)} tin vào các folder video nguồn "
                f"theo thứ tự, rồi bấm BURN BANNER cho từng tin.\n\n"
                f"Lưu ý: mỗi lần chạy chỉ burn cho 1 tiêu đề (ô banner dùng chung).\n"
                f"Em sẽ tự chạy lần lượt {len(it)} lượt.\n\nTiếp tục?"):
            return
        self._news_queue = [dict(x) for x in it]
        self._news_queue_i = 0
        self.blog(f"→ Bắt đầu burn {len(self._news_queue)} tin lần lượt.")
        self._news_next()

    def _news_next(self):
        q = getattr(self, "_news_queue", None)
        if not q:
            return
        if self._news_queue_i >= len(q):
            self.blog("✓ Đã burn xong toàn bộ tin trong hàng đợi.")
            self._news_queue = None
            return
        item = q[self._news_queue_i]
        self._news_queue_i += 1
        self.blog(f"\n=== Tin {self._news_queue_i}/{len(q)}: {item['title'][:70]} ===")
        self._news_to_banner(item)
        self.root.after(300, self._bn_run)

    def _news_export(self):
        it = getattr(self, "news_items", None) or []
        if not it:
            self.blog("! Chưa có tin nào để xuất.")
            return
        p = filedialog.asksaveasfilename(
            title="Lưu danh sách tin", defaultextension=".json",
            initialfile="tin_nong_24h.json", initialdir=str(OUTPUT),
            filetypes=[("JSON", "*.json")])
        if not p:
            return
        try:
            Path(p).write_text(json.dumps(it, ensure_ascii=False, indent=2),
                               encoding="utf-8")
            self.blog(f"✓ Đã lưu: {p}")
        except Exception as e:
            self.blog(f"! Lỗi lưu: {e}")

    def _news_open_link(self):
        it = self._news_sel()
        if not it or not it.get("link"):
            self.blog("! Chọn 1 tin có link trước.")
            return
        try:
            os.startfile(it["link"])           # noqa: S606 (Windows)
        except Exception as e:
            self.blog(f"! Không mở được link: {e}")

    def _bn_add(self):
        p = filedialog.askdirectory(title="Chọn folder chứa video cần chèn banner")
        if p and p not in self.bn_folders:
            self.bn_folders.append(p)
            self._bn_refresh()

    def _bn_del(self):
        for i in sorted(self.bn_list.curselection(), reverse=True):
            del self.bn_folders[i]
        self._bn_refresh()

    def _bn_clear(self):
        self.bn_folders = []
        self._bn_refresh()

    def _bn_pick_out(self):
        p = filedialog.askdirectory(title="Chọn nơi lưu video có banner")
        if p:
            self.bn_out.set(p)

    # ── tab 2: chọn ảnh/video MC cho khung "NEWS" ──────────
    def _bn_pick_pip_src(self):
        # mo san folder MC neu co (chi la goi y, KHONG luu thanh mac dinh —
        # moi lan chay van phai chon file MC)
        guess = Path(r"C:\Users\Admin\Downloads\Video\MC")
        p = filedialog.askopenfilename(
            title="Chọn ảnh hoặc video MC",
            initialdir=str(guess) if guess.is_dir() else None,
            filetypes=[("Ảnh / video", "*.png *.jpg *.jpeg *.jpe *.jfif *.webp *.bmp "
                                       "*.mp4 *.mov *.avi *.mkv *.webm"),
                       ("Tất cả", "*.*")])
        if p:
            self.bvars["pip_src"].set(p)
            # chon duoc MC -> tu tich "Co MC" de khung bat luon, khoi phai tich tay
            try:
                self.bn_pip_on.set(True)
            except Exception:
                pass

    def _bn_pick_pip_folder(self):
        p = filedialog.askdirectory(title="Chọn folder chứa nhiều ảnh/video MC")
        if p:
            self.bvars["pip_folder"].set(p)
            try:
                self.bn_pip_on.set(True)
            except Exception:
                pass

    def _bn_pip_preview(self):
        """Xem thử khung MC trên chính video đầu tiên (không cần bật banner)."""
        set_ffmpeg_dir(self.ff_var.get())
        vids = self._bn_videos()
        if not vids:
            messagebox.showwarning("Chưa có video", "Thêm folder chứa video trước đã.")
            return
        c = self._bn_cfg()
        if not c.get("pip_src") and not c.get("pip_folder"):
            messagebox.showwarning("Thiếu ảnh MC",
                                   "Chọn ảnh/video MC (hoặc folder MC) trước đã.")
            return
        c["pip_enabled"] = True
        v = vids[0]
        self.blog(f"👁 Xem thử khung MC trên: {v.name}")
        try:
            from core.banner import preview_png
            out = Path(self.bn_out.get() or OUTPUT) / "preview_pip.png"
            out.parent.mkdir(parents=True, exist_ok=True)
            preview_png(v, out, c)
            self.blog(f"   -> {out}")
            try:
                os.startfile(str(out))
            except Exception:
                pass
        except Exception as e:
            self.blog(f"❌ Lỗi xem thử khung MC: {e}")

    def _bn_refresh(self):
        self.bn_list.delete(0, "end")
        for f in self.bn_folders:
            self.bn_list.insert("end", f)
        self.bn_count.set(f"{len(self.bn_folders)} folder")
        self.save_config()

    def _bn_reset_pos(self):
        for k, v in _REF_POS.items():
            if k in self.bvars:
                try:
                    self.bvars[k].set(v)
                except Exception:
                    pass
        self.blog("↺ Đã trả vị trí về đúng video mẫu.")

    def _bn_cfg(self):
        """Gom cấu hình banner từ widget (gọi trên MAIN thread)."""
        c = dict(BANNER_DEFAULTS)
        c.update(self.bcfg or {})
        for k, v in self.bvars.items():
            try:
                if isinstance(v, tk.BooleanVar):
                    c[k] = bool(v.get())
                elif isinstance(v, tk.DoubleVar):
                    c[k] = float(v.get())
                else:
                    c[k] = v.get()
            except Exception:
                pass
        # Le trai khung MC set cung theo thanh do banner -> khong con combobox.
        c.pop("pip_align_x", None)
        c.pop("pip_x", None)
        for k in ("red_color", "white_color", "red_text_color",
                  "white_text_color", "logo_color", "cta_color", "cta_outline",
                  "pip_border_color", "pip_line_color", "pip_tag_color",
                  "pip_tag_text_color"):
            c[k] = _hex_rgb(c.get(k))
        return c

    def _bn_videos(self):
        out = []
        for folder in self.bn_folders:
            p = Path(folder)
            if not p.is_dir():
                continue
            it = p.rglob("*") if self.bn_rec.get() else p.glob("*")
            for f in sorted(it):
                if f.is_file() and f.suffix.lower() in VID_EXT:
                    out.append(f)
        return out

    def _bn_preview(self):
        set_ffmpeg_dir(self.ff_var.get())
        vids = self._bn_videos()
        if not vids:
            messagebox.showwarning("Chưa có video", "Thêm folder chứa video trước đã.")
            return
        cfg = self._bn_cfg()
        v = vids[0]
        self.blog(f"👁 Xem trước trên: {v.name}")
        try:
            from core.banner import preview_png
            out = Path(self.bn_out.get() or OUTPUT) / "preview_banner.png"
            out.parent.mkdir(parents=True, exist_ok=True)
            preview_png(v, out, cfg)
            self.blog(f"   -> {out}")
            try:
                os.startfile(str(out))
            except Exception:
                pass
        except Exception as e:
            self.blog(f"❌ Lỗi xem trước: {e}")

    def _bn_run(self):
        set_ffmpeg_dir(self.ff_var.get())   # áp ngay, khỏi phải lưu config trước
        vids = self._bn_videos()
        if not vids:
            messagebox.showwarning("Chưa có video", "Thêm folder chứa video trước đã.")
            return
        cfg = self._bn_cfg()
        # Khung MC bat ma chua chon file MC -> hoi ngay, khong de burn ra hang loat
        # video khong co MC roi moi phat hien.
        if cfg.get("pip_enabled") and not (cfg.get("pip_src") or cfg.get("pip_folder")):
            if not messagebox.askyesno(
                    "Chưa chọn MC",
                    "Khung MC “NEWS” đang BẬT nhưng chưa chọn ảnh/video MC.\n\n"
                    "Bấm No để quay lại chọn MC.\n"
                    "Bấm Yes để burn luôn KHÔNG có khung MC."):
                return
            cfg["pip_enabled"] = False
        out_dir = Path(self.bn_out.get() or OUTPUT)
        out_dir.mkdir(parents=True, exist_ok=True)
        copyz = bool(self.bn_copyz.get())
        self.busy = True
        self.cancel = False
        self.bn_go_btn.config(state="disabled")
        self.bn_prev_btn.config(state="disabled")
        self.bn_stop_btn.config(state="normal")
        self.bn_prog.config(value=0, maximum=len(vids))
        threading.Thread(target=self._bn_work,
                         args=(vids, cfg, out_dir, copyz), daemon=True).start()

    def _bn_work(self, vids, cfg, out_dir, copyz):
        from core.banner import apply_banner, probe_video
        n = len(vids)
        self.blog(f"📰 Burn banner cho {n} video -> {out_dir}")
        self.blog(f"   chữ ô đỏ : {cfg.get('red_text')!r}")
        self.blog(f"   chữ tiêu đề: {cfg.get('white_text')!r}")
        ok = fail = 0
        for i, v in enumerate(vids, 1):
            if self.cancel:
                self.blog("⏹ Đã dừng theo yêu cầu.")
                break
            try:
                size = probe_video(v)
                w, h = size if size else (1080, 1920)
                out = out_dir / (v.stem + "_BN.mp4")
                apply_banner(v, out, cfg, w, h,
                             crf=float(self.cfg.get("crf", 18)),
                             preset=str(self.cfg.get("preset", "veryfast")),
                             log=self.blog)
                ok += 1
                if copyz:
                    try:
                        z = Z_BACKUP / out_dir.name
                        z.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(out, z / out.name)
                    except Exception as e:
                        self.blog(f"   ⚠ copy Z lỗi: {e}")
            except Exception as e:
                fail += 1
                self.blog(f"❌ [{i}/{n}] {v.name}: {e}")
            self.root.after(0, lambda i=i: self.bn_prog.config(value=i))
            self.root.after(0, lambda i=i, n=n: self.bn_status.set(f"{i}/{n}"))
        self.blog(f"✅ Xong: {ok} thành công, {fail} lỗi.")
        self.root.after(0, lambda: self.bn_go_btn.config(state="normal"))
        self.root.after(0, lambda: self.bn_prev_btn.config(state="normal"))
        self.root.after(0, lambda: self.bn_stop_btn.config(state="disabled"))
        self.busy = False
        # Có hàng đợi tin nóng? → chạy tiếp tin kế tiếp
        if getattr(self, "_news_queue", None) and not self.cancel:
            self.root.after(1200, self._news_next)

    # ── log ────────────────────────────────────────────────
    def log(self, m):
        def do():
            self.log_box.config(state="normal")
            self.log_box.insert("end", str(m) + "\n")
            self.log_box.see("end")
            self.log_box.config(state="disabled")
        self.root.after(0, do)

    def set_status(self, s):
        self.root.after(0, lambda: self.status_var.set(s))

    # ── folder pickers ─────────────────────────────────────
    def _add_folder(self):
        p = filedialog.askdirectory(title="Chọn folder chứa ảnh/video")
        if p and p not in self.folders:
            self.folders.append(p)
            self._refresh()

    def _add_multi(self):
        # tkinter không hỗ trợ chọn nhiều folder -> dùng cách nhập nhiều lần
        p = filedialog.askdirectory(title="Chọn folder (bấm lại để thêm tiếp)")
        if p and p not in self.folders:
            self.folders.append(p)
            self._refresh()
            self.root.after(150, self._add_multi)

    def _add_parent(self):
        p = filedialog.askdirectory(title="Chọn folder CHA (mỗi folder con = 1 video)")
        if not p:
            return
        subs = []
        for d in sorted(Path(p).iterdir()):
            if d.is_dir():
                imgs, vids = list_media(d, self.rec_var.get())
                if imgs or vids:
                    subs.append(str(d))
        if not subs:
            # folder cha không có folder con hợp lệ -> coi chính nó là 1 folder
            imgs, vids = list_media(p, self.rec_var.get())
            if imgs or vids:
                subs = [p]
        added = 0
        for s in subs:
            if s not in self.folders:
                self.folders.append(s)
                added += 1
        self._refresh()
        self.log(f"Thêm {added} folder con từ: {p}")

    def _del_folder(self):
        for i in reversed(self.listbox.curselection()):
            del self.folders[i]
        self._refresh()

    def _clear_folders(self):
        self.folders = []
        self._refresh()

    def _refresh(self):
        self.listbox.delete(0, "end")
        for f in self.folders:
            self.listbox.insert("end", f)
        self.count_var.set(f"{len(self.folders)} folder")
        self.save_config()

    # ── other pickers ──────────────────────────────────────
    def _pick_audio(self):
        p = filedialog.askopenfilename(title="Chọn audio",
                                       filetypes=[("Audio", "*.mp3 *.wav *.m4a *.aac *.opus *.flac")])
        if p:
            self.audio_var.set(p)

    def _pick_audio_dir(self):
        p = filedialog.askdirectory(title="Chọn folder chứa audio")
        if p:
            self.audio_dir_var.set(p)

    # ── ElevenLabs: giọng đọc tin ──────────────────────────
    def _tts_voice(self):
        """Giọng đang chọn -> tuple trong eleven.VOICES."""
        want = self.tts_voice_var.get().strip()
        for v in eleven.VOICES:
            if eleven.voice_label(v) == want or v[0] == want:
                return v
        return eleven.VOICES[0]

    def _tts_voice_info(self):
        """Ghi rõ giọng này giống kiểu nhà đài nào."""
        v = self._tts_voice()
        tier = "dùng được với gói free" if v[5] == "free" else "CẦN GÓI TRẢ PHÍ"
        self.tts_voice_note.set(
            f"→ {v[0]} ({v[1]}): kiểu {v[3]} — {v[4]}  ·  {tier}")

    def _tts_key(self) -> str:
        return (self.tts_key_var.get() or "").strip() or eleven.load_key()

    def _tts_load_key(self):
        k = eleven.load_key()
        if k:
            self.tts_key_var.set(k)
            self.tts_key_state.set("● đã nạp từ .env")
            self.log("🔑 Đã nạp ELEVENLABS_API_KEY từ .env")
        else:
            self.tts_key_state.set("✗ .env chưa có key")
            self.log("✗ Chưa tìm thấy ELEVENLABS_API_KEY trong .env")

    def _tts_save_key(self):
        k = (self.tts_key_var.get() or "").strip()
        if not k:
            messagebox.showwarning("Thiếu key", "Chưa nhập API key.")
            return
        try:
            p = eleven.save_key(k)
            self.tts_key_state.set("● đã lưu")
            self.log(f"💾 Đã lưu key vào {p}")
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không lưu được key:\n{e}")

    def _tts_check_key(self):
        self.tts_key_state.set("đang kiểm tra…")
        self.root.update_idletasks()
        info = eleven.key_info(self._tts_key())
        self.tts_key_state.set(("✔ " if info.get("ok") else "✗ ") + info.get("msg", ""))
        self.log(("✔ " if info.get("ok") else "✗ ") + "ElevenLabs: " + info.get("msg", ""))

    def _tts_pick_dir(self):
        p = filedialog.askdirectory(title="Chọn thư mục lưu audio")
        if p:
            self.tts_dir_var.set(p)

    def _tts_pick_batch(self):
        p = filedialog.askdirectory(title="Chọn folder chứa file .txt")
        if p:
            self.tts_batch_var.set(p)

    def _tts_text_value(self) -> str:
        try:
            return self.tts_text.get("1.0", "end").strip()
        except Exception:
            return ""

    def _tts_secs(self) -> float:
        """Thời gian đọc đang đặt (giây)."""
        try:
            v = float(str(self.tts_secs_var.get()).strip().replace(",", "."))
        except Exception:
            v = eleven.DEFAULT_READ_SECONDS
        if v <= 0:
            v = eleven.DEFAULT_READ_SECONDS
        return max(0.5, min(3600.0, v))

    def _tts_fit_on(self) -> bool:
        try:
            return bool(self.tts_fit_var.get())
        except Exception:
            return True

    def _tts_cps(self) -> float:
        """Tốc độ đọc thật đo được (ký tự/giây) — càng dùng càng sát."""
        try:
            v = float(self.cfg.get("tts_cps") or eleven.CHARS_PER_SEC_HINT)
        except Exception:
            v = eleven.CHARS_PER_SEC_HINT
        return v if 5.0 <= v <= 40.0 else eleven.CHARS_PER_SEC_HINT

    def _tts_len_hint(self):
        """Hiện gợi ý số ký tự nên nhập cho vừa số giây đang đặt."""
        try:
            secs = self._tts_secs()
            txt = self._tts_text_value()
            cps = self._tts_cps()
            want = eleven.chars_for_seconds(secs, cps)
            cur = len(txt)
            base = (f"→ đọc {secs:g}s: nên nhập ~{want} ký tự "
                    f"(tốc độ đo được ~{cps:.1f} ký tự/giây)")
            if cur <= 0:
                self.tts_len_var.set(base)
                return
            est = cur / cps
            ratio = est / secs if secs else 1.0
            note = base + f"  ·  hiện có {cur} ký tự ≈ {est:.1f}s"
            if not self._tts_fit_on():
                self.tts_len_var.set(note + "  (chưa bật ép → file dài "
                                            f"~{est:.1f}s, KHÔNG khớp video)")
            elif ratio > 1.35:
                self.tts_len_var.set(note + f"  ⚠ DÀI hơn {secs:g}s → phải đọc "
                                            f"nhanh {ratio:.2f}x, nên rút ngắn")
            elif ratio < 0.72:
                self.tts_len_var.set(note + f"  ⚠ NGẮN hơn {secs:g}s → phải đọc "
                                            f"chậm {ratio:.2f}x, nên viết thêm")
            else:
                self.tts_len_var.set(note + "  ✔ vừa")
        except Exception:
            pass

    def _tts_play(self):
        p = Path(self.tts_dir_var.get() or ".") / (self.tts_name_var.get().strip() or "voice")
        p = p.with_suffix(".mp3")
        if p.is_file():
            os.startfile(str(p))
        else:
            self.log(f"✗ Chưa có file: {p.name}")

    def _tts_generate(self):
        """Tạo 1 file audio từ ô nội dung (chạy nền để GUI không đơ)."""
        key = self._tts_key()
        if not key:
            messagebox.showwarning("Thiếu key", "Chưa có API key ElevenLabs.\n"
                                                "Bấm \"Nạp từ .env\" hoặc dán key vào.")
            return
        text = self._tts_text_value()
        if not text:
            messagebox.showwarning("Thiếu nội dung", "Chưa nhập nội dung đọc.")
            return
        v = self._tts_voice()
        model = self.tts_model_var.get().strip() or eleven.DEFAULT_MODEL
        d = Path(self.tts_dir_var.get().strip() or (OUTPUT / "tts"))
        name = self._safe_name(self.tts_name_var.get().strip() or "voice")
        out = d / f"{name}.mp3"
        self.save_config()
        self.tts_gen_btn.config(state="disabled")
        secs = self._tts_secs()
        do_fit = self._tts_fit_on()
        self.log(f"🎙 ElevenLabs: {v[0]} ({v[3]}) · {model} · {len(text)} ký tự"
                 + (f" · ép đọc {secs:g}s" if do_fit else " · không ép thời lượng"))

        def work():
            try:
                r = eleven.synthesize(key, v[2], model, text, out)
                self.log(f"✅ {out.name}  ({r['bytes']/1024:.1f} KB, "
                         f"{r['elapsed_s']}s, {r['chars']} ký tự, "
                         f"dài {r.get('seconds', 0):g}s)")
                # đo tốc độ đọc thật -> lần sau gợi ý số ký tự sát hơn
                if r.get("seconds") and r["seconds"] > 0.5:
                    self.cfg["tts_cps"] = round(r["chars"] / r["seconds"], 2)
                if do_fit:
                    f = eleven.fit_duration(out, secs, log=self.log)
                    if f.get("ok"):
                        self.log(f"   ⏱ ép về {secs:g}s: "
                                 f"{f['before']:.2f}s → {f['after']:.2f}s "
                                 f"({f['action'].strip()})")
                    else:
                        self.log(f"   ⚠ không ép được thời lượng: {f.get('msg')}")
                self.log(f"   → {out}")
                # tiện: nạp luôn vào ô audio của mục 3 để render dùng ngay
                self.root.after(0, lambda: self.audio_var.set(str(out)))
                self.root.after(0, lambda: messagebox.showinfo(
                    "Xong", f"Đã tạo:\n{out}\n\nĐã tự điền vào ô audio ở mục 3."))
            except RuntimeError as e:
                self.log(f"❌ {e}")
                self.root.after(0, lambda: messagebox.showerror("Lỗi", str(e)))
            except Exception as e:
                self.log(f"❌ {type(e).__name__}: {e}")
            finally:
                self.root.after(0, self.save_config)
                self.root.after(0, lambda: self.tts_gen_btn.config(state="normal"))

        threading.Thread(target=work, daemon=True).start()

    def _tts_batch(self):
        """Mỗi file .txt trong folder -> 1 file .mp3 cùng tên."""
        key = self._tts_key()
        if not key:
            messagebox.showwarning("Thiếu key", "Chưa có API key ElevenLabs.")
            return
        src = self.tts_batch_var.get().strip()
        if not src or not os.path.isdir(src):
            messagebox.showwarning("Thiếu folder", "Chưa chọn folder chứa file .txt.")
            return
        txts = sorted(Path(src).glob("*.txt"))
        if not txts:
            messagebox.showwarning("Không có .txt", "Folder không có file .txt nào.")
            return
        v = self._tts_voice()
        model = self.tts_model_var.get().strip() or eleven.DEFAULT_MODEL
        d = Path(self.tts_dir_var.get().strip() or (OUTPUT / "tts"))
        self.save_config()
        self.tts_gen_btn.config(state="disabled")
        secs = self._tts_secs()
        do_fit = self._tts_fit_on()
        self.log(f"📄 Hàng loạt: {len(txts)} file .txt → {d}"
                 + (f"  ·  ép mỗi file về {secs:g}s" if do_fit else ""))

        def work():
            ok = 0
            secs_seen = []
            for i, t in enumerate(txts, 1):
                try:
                    text = t.read_text(encoding="utf-8", errors="replace").strip()
                    if not text:
                        self.log(f"   [{i}/{len(txts)}] {t.name}: rỗng, bỏ qua")
                        continue
                    out = d / f"{self._safe_name(t.stem)}.mp3"
                    r = eleven.synthesize(key, v[2], model, text, out)
                    if r.get("seconds") and r["seconds"] > 0.5:
                        secs_seen.append(r["chars"] / r["seconds"])
                    extra = ""
                    if do_fit:
                        f = eleven.fit_duration(out, secs, log=self.log)
                        if f.get("ok"):
                            extra = (f"  ⏱ {f['before']:.2f}s → "
                                     f"{f['after']:.2f}s")
                        else:
                            extra = f"  ⚠ không ép được: {f.get('msg')}"
                    ok += 1
                    self.log(f"   [{i}/{len(txts)}] ✅ {out.name} "
                             f"({r['bytes']/1024:.1f} KB, {r['chars']} ký tự, "
                             f"dài {r.get('seconds', 0):g}s){extra}")
                except Exception as e:
                    self.log(f"   [{i}/{len(txts)}] ❌ {t.name}: {e}")
            if secs_seen:
                self.cfg["tts_cps"] = round(sum(secs_seen) / len(secs_seen), 2)
            self.log(f"→ Xong {ok}/{len(txts)} file. Audio ở: {d}")
            self.root.after(0, self.save_config)
            self.root.after(0, lambda: messagebox.showinfo(
                "Xong", f"Tạo được {ok}/{len(txts)} file audio.\n{d}"))
            self.root.after(0, lambda: self.tts_gen_btn.config(state="normal"))

        threading.Thread(target=work, daemon=True).start()

    def _pick_out(self):
        p = filedialog.askdirectory(title="Chọn thư mục lưu")
        if p:
            self.out_var.set(p)

    # ── ffmpeg ─────────────────────────────────────────────
    def _ff_refresh(self):
        """Cập nhật dòng trạng thái: đang dùng ffmpeg ở đâu, tìm thấy chưa."""
        d = ffmpeg_dir()
        if not getattr(self, "ff_status", None):
            return
        if d:
            ver = ""
            try:
                r = subprocess.run([find_ffmpeg(), "-version"], capture_output=True,
                                   text=True, timeout=20)
                ver = (r.stdout or "").splitlines()[0][:52]
            except Exception:
                pass
            self.ff_status.config(text=f"✓ Đang dùng: {d}\n   {ver}", foreground="#0a7")
        else:
            self.ff_status.config(
                text="✗ Chưa tìm thấy ffmpeg — chọn thư mục chứa ffmpeg.exe.",
                foreground="#c00")

    def _pick_ffmpeg(self):
        """Mở hộp chọn folder NGAY tại thư mục ffmpeg đang dùng."""
        cur = self.ff_var.get().strip().strip('"')
        start = cur if os.path.isdir(cur) else ffmpeg_dir()
        if not start or not os.path.isdir(start):
            start = r"C:\ReverseEngineering\thirdparty"
        p = filedialog.askdirectory(title="Chọn thư mục chứa ffmpeg.exe",
                                    initialdir=os.path.normpath(start),
                                    mustexist=True)
        if not p:
            return
        got = set_ffmpeg_dir(p)
        if got:
            self.ff_var.set(got)
            self.log(f"✓ ffmpeg: {got}")
        else:
            self.ff_var.set("")
            self.log(f"✗ Không thấy ffmpeg.exe trong: {p}")
            messagebox.showwarning("Không hợp lệ",
                                   f"Thư mục không chứa ffmpeg.exe:\n{p}")
        self._ff_refresh()

    def _open_ffmpeg(self):
        """Mở Explorer ngay thư mục ffmpeg đang dùng."""
        d = self.ff_var.get().strip().strip('"') or ffmpeg_dir()
        if os.path.isdir(d):
            os.startfile(os.path.normpath(d))
        else:
            self.log("Chưa xác định được thư mục ffmpeg.")

    def _auto_ffmpeg(self):
        self.ff_var.set("")
        set_ffmpeg_dir("")
        self._ff_refresh()
        d = ffmpeg_dir()
        self.log(f"✓ Tự dò ffmpeg: {d}" if d else "✗ Tự dò không thấy ffmpeg.")

    def _open_out(self):
        d = self.out_var.get()
        if os.path.isdir(d):
            os.startfile(d)
        else:
            self.log("Thư mục chưa tồn tại.")

    def _stop(self):
        self.cancel = True
        self.log("⏹ Đã yêu cầu dừng — sẽ dừng sau video hiện tại.")

    # ── render ─────────────────────────────────────────────
    def _build_cfg(self, audio=None):
        cfg = {}
        for k, v in self.vars.items():
            cfg[k] = v.get()
        cfg["fps"] = int(cfg["fps"])
        cfg["out_w"] = int(self.w_var.get())
        cfg["out_h"] = int(self.h_var.get())
        cfg["crf"] = int(cfg["crf"])
        cfg["use_all"] = bool(self.all_var.get())
        cfg["recursive"] = bool(self.rec_var.get())
        cfg["preset"] = self.preset_var.get()
        cfg["face_focus"] = bool(self.face_var.get())
        cfg["grade"] = bool(self.grade_var.get())
        cfg["grade_strength"] = float(cfg.get("grade_strength", 1.0))
        cfg["interleave"] = bool(self.ileave_var.get())
        cfg["seed"] = None          # luôn random mỗi lần render
        cfg["bg_color"] = (0, 0, 0)
        cfg["audio"] = audio or ""
        return cfg

    def _find_audio_for(self, folder):
        """Khớp audio theo tên folder con."""
        single = self.audio_var.get().strip()
        if single and os.path.isfile(single):
            return single
        adir = self.audio_dir_var.get().strip()
        if not adir or not os.path.isdir(adir):
            return ""
        name = Path(folder).name.lower()
        exts = [".mp3", ".wav", ".m4a", ".aac", ".opus", ".flac", ".ogg"]
        for p in sorted(Path(adir).iterdir()):
            if p.suffix.lower() in exts and p.stem.lower() == name:
                return str(p)
        return ""

    def _safe_name(self, s):
        s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", str(s)).strip().strip(".")
        return (s[:80] or "video")

    def _check_pool(self):
        """Kiểm tra từng folder: đếm media + số video tối đa tạo được."""
        set_ffmpeg_dir(self.ff_var.get())
        if not self.folders:
            messagebox.showwarning("Thiếu đầu vào", "Chưa chọn folder nào.")
            return
        if self.busy:
            return
        self.busy = True
        self.set_status("Đang kiểm tra pool…")
        # Đọc biến Tk ở MAIN thread rồi truyền vào worker — Tk không cho phép
        # đọc biến từ thread nền ("main thread is not in main loop").
        try:
            n_want = max(1, int(self.nvid_var.get()))
        except (ValueError, tk.TclError):
            n_want = 1
        try:
            max_ovl = min(1.0, max(0.0, float(self.ovl_var.get())))
        except (ValueError, tk.TclError):
            max_ovl = 0.5
        folders = list(self.folders)
        threading.Thread(target=self._check_pool_work,
                         args=(folders, n_want, max_ovl),
                         daemon=True).start()

    def _check_pool_work(self, folders, n_want, max_ovl):
        try:
            self.log("")
            self.log("═══ KIỂM TRA POOL ═══")
            self.log(f"Muốn tạo {n_want} video/folder, trùng tối đa {max_ovl:.0%}")
            total_ok = 0
            for i, folder in enumerate(folders, 1):
                st = Stitcher(self._build_cfg(self._find_audio_for(folder)),
                              log=lambda m: None)
                rep = st.pool_report(folder, max_overlap=max_ovl)
                name = Path(folder).name
                if rep["pool"] == 0:
                    self.log(f"❌ [{i}] {name}: không có ảnh/video hợp lệ")
                    continue
                # capped=True nghĩa là chạm trần đếm -> chỉ được nói "≥ N"
                n_txt = (f"≥ {rep['max_videos']}" if rep.get("capped")
                         else str(rep["max_videos"]))
                line = (f"• [{i}] {name}: {rep['imgs']} ảnh + {rep['vids']} video"
                        f" = {rep['pool']} file → tối đa {n_txt} video")
                # Quy đổi số đoạn cắt thành SỐ VIDEO thật — nói "68 đoạn" gây
                # hiểu lầm là tạo được 68 video, trong khi 1 video con ăn 4-6
                # đoạn nên chỉ ra được ~1/5 số đó.
                vsec = float(rep.get("vid_secs") or 0.0)
                if vsec > 0:
                    total_s = float(self.vars["total"].get() or 15.0)
                    # mỗi video con lấy 60-85% thời lượng là cảnh video
                    v_lo = int(vsec / (total_s * 0.85))
                    v_hi = int(vsec / (total_s * 0.60))
                    line += (f"; clip gốc {vsec:.0f}s → đủ video cho "
                             f"~{v_lo}-{v_hi} video")
                if rep.get("capped"):
                    line += "  (rất nhiều — chạm trần đếm)"
                if rep["max_videos"] < n_want and not rep.get("capped"):
                    line += f"  ⚠ THIẾU (cần {n_want})"
                else:
                    line += "  ✔ đủ"
                self.log(line)
                total_ok += min(rep["max_videos"], n_want)
            self.log(f"→ Tổng tối đa tạo được: {total_ok} video "
                     f"(mục tiêu {n_want * len(self.folders)})")
            self.set_status("Kiểm tra xong")
            self.root.after(0, lambda: messagebox.showinfo(
                "Kiểm tra pool", f"Tối đa tạo được {total_ok} video.\n"
                "Xem chi tiết ở khung nhật ký."))
        except Exception as e:
            self.log(f"❌ Lỗi kiểm tra: {e}")
        finally:
            self.busy = False

    def _run(self):
        if self.busy:
            return
        if not self.folders:
            messagebox.showwarning("Thiếu đầu vào", "Chưa chọn folder nào.")
            return
        set_ffmpeg_dir(self.ff_var.get())   # áp ngay, khỏi phải lưu config trước
        out_dir = Path(self.out_var.get() or OUTPUT)
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không tạo được thư mục lưu:\n{e}")
            return
        self.save_config()
        self.busy = True
        self.cancel = False
        self.go_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.prog["value"] = 0
        # Đọc biến Tk ở MAIN thread rồi truyền vào worker — Tk không cho phép
        # đọc biến từ thread nền ("main thread is not in main loop").
        try:
            n_videos = max(1, int(self.nvid_var.get()))
        except (ValueError, tk.TclError):
            n_videos = 1
        try:
            n_threads = max(1, int(self.thread_var.get()))
        except (ValueError, tk.TclError):
            n_threads = 1
        try:
            max_ovl = min(1.0, max(0.0, float(self.ovl_var.get())))
        except (ValueError, tk.TclError):
            max_ovl = 0.5
        copy_z = bool(self.z_var.get())
        folders = list(self.folders)
        threading.Thread(target=self._work,
                         args=(out_dir, n_videos, n_threads, max_ovl, copy_z,
                               folders),
                         daemon=True).start()

    def _work(self, out_dir, n_videos, threads, max_ovl, copy_z, folders):
        t_all = time.time()
        ok = fail = 0
        used_names = set()
        total = len(folders)

        done = {"n": 0}
        lock = threading.Lock()

        def prog(stage, cur, tot, msg):
            if stage == "clip" and tot:
                with lock:
                    self.root.after(0, lambda: self.prog.config(
                        value=min(99.0, (cur / tot) * 100)))
            self.set_status(msg[:40])

        def unique_out(folder, k):
            name = self._safe_name(Path(folder).name)
            out = out_dir / (f"{name}.mp4" if k == 1 else f"{name}_{k}.mp4")
            with lock:
                n = k + 1
                while str(out).lower() in used_names or out.exists():
                    out = out_dir / f"{name}_{n}.mp4"
                    n += 1
                used_names.add(str(out).lower())
            return out

        def one(job):
            """job = (folder, k, plan, audio) -> (ok?, msg, plan, out)

            Dùng ĐÚNG plan đã lập ở bước tuần tự (không lập lại) — nếu lập lại
            thì seed mới sẽ chọn media khác và ràng buộc không-trùng bị phá.
            """
            folder, k, plan, audio = job
            cfg = self._build_cfg(audio)
            st = Stitcher(cfg, log=self.log, progress=prog)
            out = unique_out(folder, k)
            t0 = time.time()
            res = st.render_plan(plan, out)
            with lock:
                done["n"] += 1
                d = done["n"]
            msg = (f"✅ [{d}] {out.name}  ({res['clips']} cảnh, "
                   f"{res['bytes']/1024/1024:.1f} MB, {time.time()-t0:.1f}s)")
            return (True, msg, plan, out)

        for i, folder in enumerate(folders, 1):
            if self.cancel:
                self.log("⏹ Đã dừng theo yêu cầu.")
                break
            self.log("")
            self.log(f"═══ [{i}/{total}] {folder}")
            audio = self._find_audio_for(folder)
            if audio:
                self.log(f"   audio: {Path(audio).name}")
            self.log(f"   tạo {n_videos} video, {threads} luồng song song, "
                     f"trùng tối đa {max_ovl:.0%}")

            # 1) LẬP KẾ HOẠCH tuần tự — đảm bảo các video trong cùng folder
            #    không dùng chung quá max_ovl số ảnh/video
            jobs = []
            try:
                planner = Stitcher(self._build_cfg(audio), log=lambda m: None)
                rep = planner.pool_report(folder, max_overlap=max_ovl)
                n_txt = (f"≥ {rep['max_videos']}" if rep.get("capped")
                         else str(rep["max_videos"]))
                self.log(f"   pool: {rep['imgs']} ảnh + {rep['vids']} video "
                         f"= {rep['pool']} file → tối đa {n_txt} video"
                         f" (cỡ cảnh {rep['best_n']})")
                if rep["pool"] == 0:
                    self.log("❌ Folder không có ảnh/video hợp lệ.")
                    fail += 1
                    continue

                want = n_videos
                pin_n = None
                # Chạm trần đếm nghĩa là pool rất dư -> không bao giờ thiếu.
                if rep["max_videos"] < want and not rep.get("capped"):
                    self.log(f"⚠ POOL KHÔNG ĐỦ: chỉ tạo được "
                             f"{rep['max_videos']} video thay vì {want} "
                             f"(pool {rep['pool']} file, trùng tối đa "
                             f"{max_ovl:.0%}).")
                    want = rep["max_videos"]
                    pin_n = rep["best_n"]   # ghim cỡ cảnh -> đạt đúng con số
                elif want >= rep["max_videos"]:
                    # Xin đúng/sát mức tối đa: phải ghim cỡ cảnh tối ưu, nếu để
                    # cỡ cảnh ngẫu nhiên thì thường chỉ đạt ít hơn con số đã báo.
                    pin_n = rep["best_n"]
                if want <= 0:
                    self.log("❌ Pool quá nhỏ để tạo video nào.")
                    fail += 1
                    continue

                plans = planner.plan_sequence(folder, want,
                                              max_overlap=max_ovl,
                                              fixed_n=pin_n,
                                              fallback_n=rep["n_min"],
                                              seed=rep.get("best_seed"))
                if len(plans) < want:
                    # cỡ cảnh ngẫu nhiên kém hiệu quả -> ghim cỡ tối ưu + seed
                    # mà báo cáo đã tìm ra để đạt đúng số video đã báo trước
                    plans = planner.plan_sequence(folder, want,
                                                  max_overlap=max_ovl,
                                                  fixed_n=rep["best_n"],
                                                  fallback_n=rep["n_min"],
                                                  seed=rep.get("best_seed"))
                if not plans:
                    self.log("❌ Không lập được kế hoạch nào.")
                    fail += 1
                    continue
                if len(plans) < want:
                    self.log(f"⚠ Chỉ lập được {len(plans)}/{want} kế hoạch "
                             f"(pool cạn sớm hơn dự kiến).")
                jobs = [(folder, k, p, audio)
                        for k, p in enumerate(plans, 1)]
            except StitchError as e:
                self.log(f"❌ {e}")
                fail += 1
                continue
            except Exception as e:
                self.log(f"❌ Lỗi: {e}")
                fail += 1
                continue

            # 2) RENDER song song
            with ThreadPoolExecutor(max_workers=threads) as ex:
                futs = {ex.submit(one, j): j for j in jobs}
                for fu in as_completed(futs):
                    try:
                        good, msg, plan, out = fu.result()
                        self.log(msg)
                        self.log("   " + " → ".join(
                            s["path"].name for s in plan["scenes"]))
                        ok += 1
                        if copy_z:
                            try:
                                Z_BACKUP.mkdir(parents=True, exist_ok=True)
                                shutil.copy2(out, Z_BACKUP / out.name)
                                self.log("   ↳ đã copy sang Z:")
                            except Exception as e:
                                self.log(f"   ⚠ copy Z: lỗi — {e}")
                    except StitchError as e:
                        self.log(f"❌ {e}")
                        fail += 1
                    except Exception as e:
                        self.log(f"❌ Lỗi: {e}")
                        fail += 1

        dt = time.time() - t_all
        self.log("")
        self.log(f"═══ XONG: {ok} thành công, {fail} lỗi — {dt:.0f}s")
        self.log(f"    Lưu tại: {out_dir}")
        self.set_status(f"Xong {ok}")
        self.root.after(0, lambda: self.prog.config(value=0))
        self.root.after(0, lambda: self.go_btn.config(state="normal"))
        self.root.after(0, lambda: self.stop_btn.config(state="disabled"))
        self.busy = False
        if ok:
            self.root.after(0, lambda: messagebox.showinfo(
                "Hoàn tất", f"Đã tạo {ok} video.\nLỗi: {fail}\n\n{out_dir}"))

    # ------------------------------------------------ cập nhật từ GitHub

    def _check_update(self):
        """Kiểm tra GitHub rồi (nếu có bản mới) hỏi trước khi cập nhật."""
        if getattr(self, "busy", False):
            messagebox.showwarning("Đang chạy",
                                   "Tool đang render — đợi xong rồi cập nhật.")
            return
        self.upd_btn.config(state="disabled", text="⬆ Đang kiểm tra...")
        threading.Thread(target=self._update_work, daemon=True).start()

    def _update_work(self):
        try:
            import updater as U
        except Exception as e:
            self.root.after(0, lambda: self._update_fail(f"Thiếu updater.py: {e}"))
            return
        self.blog(f"Bản đang dùng: v{U.read_local_version()}")
        r = U.check_update()
        if not r.get("ok"):
            self.root.after(0, lambda: self._update_fail(r.get("error", "?")))
            return
        if not r.get("has_update"):
            self.root.after(0, lambda: self._update_done(
                f"Bạn đang dùng bản mới nhất (v{r['local']})."))
            return
        self.root.after(0, lambda: self._update_ask(r))

    def _update_ask(self, r):
        notes = (r.get("notes") or "").strip()
        msg = (f"Có bản mới v{r['remote']} (bạn đang dùng v{r['local']}).\n\n"
               + (notes + "\n\n" if notes else "")
               + "Cập nhật NGAY bây giờ?\n"
                 "(Cài đặt + key + video cũ được giữ nguyên.)")
        if not messagebox.askyesno("Có bản cập nhật", msg):
            self._update_done("Đã bỏ qua cập nhật.")
            return
        self.upd_btn.config(text="⬆ Đang tải...")
        threading.Thread(target=self._update_apply, args=(r,), daemon=True).start()

    def _update_apply(self, r):
        try:
            import updater as U
            res = U.apply_update(r.get("zip", ""), log=self.blog)
        except Exception as e:
            self.root.after(0, lambda: self._update_fail(f"Lỗi cập nhật: {e}"))
            return
        if not res.get("ok"):
            self.root.after(0, lambda: self._update_fail(res.get("error", "?")))
            return
        self.root.after(0, lambda: self._update_restart(res))

    def _update_restart(self, res):
        v = res.get("version", "?")
        self.blog(f"Đã cập nhật lên v{v}. Đang khởi động lại tool...")
        if not messagebox.askyesno(
                "Đã cập nhật",
                f"Đã cập nhật lên v{v}.\n\n"
                f"Bản cũ được sao lưu ở:\n{res.get('backup', '')}\n\n"
                "Khởi động lại tool ngay bây giờ?"):
            self._update_done(f"Đã cập nhật v{v} — mở lại tool để dùng bản mới.")
            return
        self._restart()

    def _restart(self):
        """Mở lại chính tool này rồi thoát tiến trình hiện tại."""
        try:
            py = sys.executable or "python"
            me = Path(__file__).resolve()
            # máy Windows: ưu tiên mở ẩn bằng Mo_An.vbs nếu có
            vbs = BASE / "Mo_An.vbs"
            if os.name == "nt" and vbs.is_file():
                subprocess.Popen(["wscript.exe", "//nologo", str(vbs)],
                                 cwd=str(BASE))
            else:
                subprocess.Popen([py, str(me)], cwd=str(BASE))
            self.root.after(300, self.root.destroy)
        except Exception as e:
            self._update_fail(f"Không tự mở lại được ({e}). Mở tool bằng tay.")

    def _update_done(self, msg):
        self.upd_btn.config(state="normal", text="⬆ Cập nhật")
        self.blog(msg)
        self.status_var.set(msg[:60])

    def _update_fail(self, err):
        self.upd_btn.config(state="normal", text="⬆ Cập nhật")
        self.blog(f"LỖI cập nhật: {err}")
        msg = f"Không cập nhật được:\n{err}"
        low = str(err).lower()
        if "certificate" in low or "ssl" in low:
            msg += ("\n\nMáy này thiếu kho chứng chỉ CA.\n"
                    "Cách sửa: bấm đúp file 'Sua_loi_cap_nhat.bat' "
                    "nằm cùng thư mục tool rồi chạy lại.")
        messagebox.showerror("Cập nhật", msg)



if __name__ == "__main__":
    try:
        root = tk.Tk()
        try:
            root.call("tk", "scaling", 1.15)
        except Exception:
            pass
        App(root)
        root.mainloop()
    except Exception:
        import traceback
        tb = traceback.format_exc()
        print(tb)
        try:
            r2 = tk.Tk(); r2.withdraw()
            messagebox.showerror("Lỗi khởi động", tb[-900:])
        except Exception:
            pass
