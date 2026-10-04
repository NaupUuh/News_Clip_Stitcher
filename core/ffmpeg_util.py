"""News_Clip_Stitcher - ffmpeg/ffprobe helpers + media probing."""
import os
import shutil
import subprocess

# Thư mục ffmpeg ưu tiên (bản mới nhất trước)
_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FFMPEG_DIRS = [
    os.path.join(_BASE, "ffmpeg", "bin"),        # bản đóng gói cạnh tool
    r"C:\ReverseEngineering\thirdparty\ffmpeg-9.0.2-essentials_build\bin",
    r"C:\ffmpeg-9.0.2-essentials_build\bin",
    r"C:\ffmpeg-9.0.1-essentials_build\bin",
    r"C:\ffmpeg\bin",
]

# Thư mục do người dùng chỉ định trong GUI (config["ffmpeg_dir"]).
# Ưu tiên cao hơn danh sách dò tự động ở trên.
_USER_DIR = {"dir": ""}

# .jpe là biến thể hợp lệ của JPEG (một số máy ảnh / trang tin đặt tên vậy).
IMG_EXT = {".jpg", ".jpeg", ".jpe", ".jfif", ".png", ".webp", ".bmp", ".tif",
           ".tiff"}
VID_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".wmv", ".flv",
           ".ts", ".mpg", ".mpeg", ".m2ts", ".3gp"}


def set_ffmpeg_dir(path):
    """Đặt thư mục ffmpeg người dùng chỉ định. Trả về thư mục đã nhận ("" nếu bỏ).

    Nhận cả đường dẫn tới file ffmpeg.exe (tự lấy thư mục cha). Bọc trong dấu
    nháy kép khi dán từ Explorer cũng được.
    """
    p = (path or "").strip().strip('"').strip("'")
    if p and os.path.isfile(p):
        p = os.path.dirname(p)
    if p and os.path.isdir(p) and os.path.isfile(os.path.join(p, "ffmpeg.exe")):
        _USER_DIR["dir"] = p
    else:
        _USER_DIR["dir"] = ""
    return _USER_DIR["dir"]


def ffmpeg_dir():
    """Thư mục đang thực sự dùng để chạy ffmpeg ("" nếu không tìm thấy)."""
    f = find_ffmpeg()
    return os.path.dirname(f) if f else ""


def _find(name):
    exe = name + ".exe"
    dirs = ([_USER_DIR["dir"]] if _USER_DIR["dir"] else []) + FFMPEG_DIRS
    for d in dirs:
        p = os.path.join(d, exe)
        if os.path.isfile(p):
            return p
    return shutil.which(name) or shutil.which(exe)


def find_ffmpeg():
    return _find("ffmpeg")


def find_ffprobe():
    return _find("ffprobe")


_DUR_CACHE = {}


def probe_duration(path, ffprobe=None):
    """Trả về thời lượng (giây) của media, 0.0 nếu không đọc được.

    Có cache: bước "kiểm tra pool" lập kế hoạch hàng nghìn lần trên cùng một
    folder, không cache thì mỗi lần lại mở 1 tiến trình ffprobe cho mỗi video.
    """
    key = str(path)
    if key in _DUR_CACHE:
        return _DUR_CACHE[key]
    fp = ffprobe or find_ffprobe()
    if not fp:
        return 0.0
    try:
        r = subprocess.run(
            [fp, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=60)
        d = float(r.stdout.strip())
    except Exception:
        d = 0.0
    _DUR_CACHE[key] = d
    return d


def probe_size(path, ffprobe=None):
    """Trả về (width, height) của stream video đầu tiên, hoặc None."""
    fp = ffprobe or find_ffprobe()
    if not fp:
        return None
    try:
        r = subprocess.run(
            [fp, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-of", "csv=s=x:p=0", str(path)],
            capture_output=True, text=True, timeout=60)
        m = r.stdout.strip().splitlines()[0] if r.stdout.strip() else ""
        if "x" in m:
            w, h = m.split("x")[:2]
            return int(w), int(h)
    except Exception:
        pass
    return None


def run_cmd(cmd, log=None, timeout=None):
    """Chạy lệnh, stream từng dòng ra log. Raise RuntimeError nếu fail."""
    if log:
        log("RUN: " + " ".join(str(c) for c in cmd))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace",
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    for line in proc.stdout:
        line = line.rstrip()
        if line and log:
            log(line)
    proc.wait(timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg fail (%d): %s" % (proc.returncode, " ".join(map(str, cmd))))
    return proc.returncode
