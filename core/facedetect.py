"""News_Clip_Stitcher - phát hiện mặt để crop 9:16 không cắt mất chủ thể.

Ảnh ngang (16:9, 4:3, 3:2) crop sang 9:16 chỉ giữ được ~35-45% chiều ngang.
Crop giữa khung rất dễ cắt mất mặt khi chủ thể đứng lệch. Module này tìm mặt
lớn nhất (chủ thể chính, không phải đám đông) rồi trả về toạ độ ngang để crop.

Dùng YuNet (ONNX, 230KB) qua cv2.FaceDetectorYN. Model tự tải về lần đầu.
Nếu không có cv2 / model / không thấy mặt -> trả None, tool chạy y như cũ.
"""
import os
import urllib.request
from pathlib import Path

MODEL_NAME = "face_detection_yunet_2023mar.onnx"
MODEL_URL = ("https://github.com/opencv/opencv_zoo/raw/main/"
             "models/face_detection_yunet/" + MODEL_NAME)

_det = None
_det_tried = False


def model_dir():
    return Path(__file__).resolve().parent.parent / "models"


def model_path():
    return model_dir() / MODEL_NAME


def _ensure_model(timeout=60):
    """Tải model nếu chưa có. Trả về path hoặc None."""
    p = model_path()
    if p.is_file() and p.stat().st_size > 100_000:
        return p
    # bản đã tải sẵn ở Temp
    for alt in (Path(os.environ.get("LOCALAPPDATA", "")) / "Temp" / MODEL_NAME,):
        if alt.is_file() and alt.stat().st_size > 100_000:
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(alt.read_bytes())
                return p
            except OSError:
                return alt
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(str(p) + ".part")
        with urllib.request.urlopen(MODEL_URL, timeout=timeout) as r:
            tmp.write_bytes(r.read())
        if tmp.stat().st_size > 100_000:
            tmp.replace(p)
            return p
    except Exception:
        pass
    return None


def _detector():
    global _det, _det_tried
    if _det_tried:
        return _det
    _det_tried = True
    try:
        import cv2
        mp = _ensure_model()
        if not mp:
            return None
        _det = cv2.FaceDetectorYN.create(str(mp), "", (320, 320), 0.5, 0.3, 5000)
    except Exception:
        _det = None
    return _det


def available():
    return _detector() is not None


def main_face(im):
    """Tìm mặt chủ thể chính trong ảnh PIL RGB.

    Trả về (cx, cy, w_ratio) theo tỉ lệ 0..1, hoặc None.
    Chủ thể = mặt LỚN NHẤT, không phải đám đông. Chọn theo điểm tổng hợp
    (diện tích × độ tin cậy × độ gần tâm) để không bị mặt nhỏ ở góc ảnh
    kéo khung crop ra khỏi nhân vật chính.
    """
    det = _detector()
    if det is None:
        return None
    try:
        import numpy as np
        import cv2
    except Exception:
        return None

    try:
        w, h = im.size
        if w < 40 or h < 40:
            return None
        arr = np.asarray(im.convert("RGB"))[:, :, ::-1].copy()
        sc = min(1.0, 720.0 / max(w, h))
        if sc < 1.0:
            arr = cv2.resize(arr, (max(1, int(w * sc)), max(1, int(h * sc))))
        ah, aw = arr.shape[:2]
        det.setInputSize((aw, ah))
        _, faces = det.detect(arr)
        if faces is None or len(faces) == 0:
            return None

        best = None
        best_key = -1.0
        fallback = None
        fb_key = -1.0
        for f in faces:
            fx, fy, fw, fh = (float(v) for v in f[:4])
            score = float(f[-1]) if len(f) > 14 else 1.0
            if fw < 8 or fh < 8:
                continue
            ar = fw / max(fh, 1.0)
            if ar > 1.35 or ar < 0.28:   # box không giống mặt -> bỏ
                continue
            area = fw * fh
            cx = (fx + fw / 2.0) / aw
            cy = (fy + fh / 2.0) / ah
            # chủ thể tin tức thường ở gần giữa khung -> phạt box ở mép
            off = (abs(cx - 0.5) / 0.5) ** 2 + (abs(cy - 0.5) / 0.5) ** 2
            cen = 1.0 - min(1.0, off)
            key = area * (0.35 + 0.65 * score) * (0.55 + 0.45 * cen)
            if key > fb_key:
                fb_key = key
                fallback = (fx, fy, fw, fh, area, score)
            # Đo thật: YuNet hay nhận bàn tay/cử chỉ thành mặt với score ~0.5x
            # -> chỉ nhận box đủ tin cậy, tránh kéo khung crop vào bàn tay.
            if score < 0.60:
                continue
            if key > best_key:
                best_key = key
                best = (fx, fy, fw, fh, area, score)
        if best is None:
            best = fallback      # không box nào đủ tin cậy -> dùng tạm box tốt nhất
        if best is None:
            return None
        fx, fy, fw, fh, _a, _s = best
        return ((fx + fw / 2.0) / aw, (fy + fh / 2.0) / ah, fw / aw)
    except Exception:
        return None
