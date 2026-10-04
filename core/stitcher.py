"""News_Clip_Stitcher - engine.

Nối ảnh + video thành 1 video dọc 1080x1920 kiểu news reel:
  - ảnh tĩnh  -> Ken Burns (zoom + pan ngẫu nhiên) + HIỆU ỨNG MÀU ngẫu nhiên
  - video     -> giữ chuyển động gốc, cắt đoạn ngẫu nhiên, zoom nhẹ tuỳ chọn
  - cắt CỨNG giữa các cảnh (đúng như video tham chiếu)
  - tổng thời lượng chính xác (mặc định 15.000s), chia đều có jitter ngẫu nhiên
  - thứ tự + số lượng + hướng chuyển động + màu random mỗi lần render
"""
import math
import os
import random
import shutil
import tempfile
from pathlib import Path

from PIL import Image, ImageOps

try:
    from .ffmpeg_util import (IMG_EXT, VID_EXT, find_ffmpeg, find_ffprobe,
                              probe_duration, probe_size, run_cmd)
except ImportError:  # chạy trực tiếp
    from ffmpeg_util import (IMG_EXT, VID_EXT, find_ffmpeg, find_ffprobe,
                             probe_duration, probe_size, run_cmd)

try:
    from . import facedetect
except ImportError:  # chạy trực tiếp
    import facedetect

try:
    from .cutpool import CutPool, plan_cuts
except ImportError:  # chạy trực tiếp
    from cutpool import CutPool, plan_cuts


class StitchError(Exception):
    pass


# Số lần thử lại khi bốc 1 tập media (rejection sampling). Bốc cả tập nên xác
# suất trúng rất cao; 60 lần là quá đủ kể cả khi pool gần cạn.
_TRIES = 60


def list_media(folder, recursive=False):
    """Quét folder, trả về (danh sách ảnh, danh sách video) đã sort."""
    folder = Path(folder)
    if not folder.is_dir():
        return [], []
    it = folder.rglob("*") if recursive else folder.glob("*")
    imgs, vids = [], []
    for p in it:
        if not p.is_file():
            continue
        ext = p.suffix.lower()
        if ext in IMG_EXT:
            imgs.append(p)
        elif ext in VID_EXT:
            vids.append(p)
    imgs.sort(key=lambda p: p.name.lower())
    vids.sort(key=lambda p: p.name.lower())
    return imgs, vids


def pick_items(imgs, vids, n_min, n_max, use_all, rng):
    """Chọn ngẫu nhiên các file đưa vào video."""
    pool = list(imgs) + list(vids)
    if not pool:
        return []
    if use_all:
        n = len(pool)
    else:
        lo = max(1, int(n_min))
        hi = max(lo, int(n_max))
        n = rng.randint(lo, hi)
    n = min(n, len(pool))
    picked = rng.sample(pool, n)
    rng.shuffle(picked)          # thứ tự ngẫu nhiên
    return picked


def _sample_weighted(pool, n, weights, rng):
    """Lấy n phần tử KHÔNG lặp, xác suất theo trọng số (tự cài vì rng cần)."""
    idx = list(range(len(pool)))
    w = list(weights)
    out = []
    for _ in range(n):
        tot = sum(w)
        if tot <= 0:
            i = rng.randrange(len(idx))
        else:
            r = rng.random() * tot
            acc = 0.0
            i = len(idx) - 1
            for k, ww in enumerate(w):
                acc += ww
                if r <= acc:
                    i = k
                    break
        out.append(pool[idx[i]])
        idx.pop(i)
        w.pop(i)
    return out


def estimate_max_videos(pool_size, n_min, n_max=7, max_overlap=0.5, n_imgs=None):
    """Số video tối đa tạo được từ pool mà vẫn giữ ràng buộc trùng (CHỈ ẢNH).

    Lý luận: 2 video cùng dùng n ảnh, trần trùng h = floor(n*max_overlap) -> mỗi
    video sau phải lấy ít nhất (n - h) ẢNH MỚI so với video đầu. Vậy số video
    bị chặn bởi số ảnh còn lại: 1 + (P_anh - n) // (n - h). VIDEO KHÔNG tính
    vào ràng buộc (mỗi lần dùng cắt một cửa sổ thời gian khác nhau).

    n_imgs: số ẢNH thật có trong pool. Truyền vào khi pool trộn ảnh + video —
    nếu bỏ trống thì coi cả pool là ảnh.
    """
    P = int(n_imgs if n_imgs is not None else pool_size)
    n = max(1, int(n_min))
    if P < n:
        return 0
    h = int(math.floor(n * float(max_overlap)))
    need_new = n - h
    if need_new <= 0:
        return P                      # không giới hạn thực chất
    return max(1, 1 + (P - n) // need_new)


def video_window_quota(vids, ffprobe, win):
    """Số CỬA SỔ CẮT còn dùng được của TỪNG video nguồn -> {tên file: số cửa sổ}.

    Video nguồn dài 20s, cửa sổ 5s -> cắt được 4 đoạn KHÁC NHAU (0-5, 5-10,
    10-15, 15-20). Mỗi video con dùng đúng 1 đoạn, nên mỗi video nguồn có ngân
    sách riêng bằng số cửa sổ của nó. Hết ngân sách -> video con sau chuyển
    sang TOÀN ẢNH (không quay vòng lại đoạn đã dùng, tránh trùng khớp).

    Phải theo TỪNG FILE chứ không phải tổng: video 20s có 4 cửa sổ, nếu chỉ
    đếm tổng (2 video -> 8) thì 1 file có thể bị cắt 6 lần, 2 lần cuối kẹp vào
    đuôi video -> đoạn trùng nhau (đã gặp thật ở ca 19 ảnh + 2 video).
    """
    win = float(win) or 5.0
    out = {}
    for p in vids:
        d = probe_duration(p, ffprobe)
        if d <= 0.1:
            out[p.name] = 1       # không đo được -> coi như 1 cửa sổ
        else:
            out[p.name] = max(1, int(math.ceil(d / win)))
    return out


def video_window_total(quota):
    """Tổng số cửa sổ cắt còn lại (dùng để báo cho người dùng)."""
    return sum(max(0, int(v)) for v in (quota or {}).values())


def video_cut_budget(vids, ffprobe, d_min=2.5, d_max=4.0):
    """Số ĐOẠN CẮT được của TỪNG video nguồn -> {tên file: số đoạn}.

    Khác `video_window_quota` (đếm cửa sổ CỐ ĐỊNH rồi mỗi video con lấy 1 cửa
    sổ): ở đây video gốc được CẮT LIA LIÊN TIẾP thành các đoạn dài ~d_min..d_max
    và MỖI ĐOẠN CHỈ DÙNG 1 LẦN. Con số này dùng để báo cho người dùng biết còn
    đủ video cho bao nhiêu cảnh; việc cắt thật do CutPool làm theo độ dài slot.
    """
    out = {}
    for p in vids:
        d = probe_duration(p, ffprobe)
        out[p.name] = plan_cuts(d, d_min, d_max, 30.0) if d > 0.1 else 1
    return out


def pick_items_excluding(imgs, vids, n_min, n_max, use_all, rng,
                         prev_sets=None, max_overlap=0.5, strict=False,
                         spread=True, fixed_n=None, vid_quota=None):
    """Chọn media sao cho KHÔNG TRÙNG QUÁ max_overlap với các video đã tạo.

    prev_sets: list các set(tên file) của những video đã sinh trong cùng folder.
    max_overlap: 0.5 = không được dùng chung quá một nửa số ảnh/video.
    strict: True -> nếu không còn cách chọn hợp lệ thì trả về None
            (dùng để phát hiện "pool không đủ" thay vì tạo video vi phạm).
    spread: True (mặc định) -> trong nhóm file hợp lệ chỉ lấy file ÍT DÙNG NHẤT
            (rải đều pool). Nhờ vậy vét được tối đa công suất của pool mà vẫn
            ngẫu nhiên giữa các file cùng mức dùng.
    fixed_n: ép cỡ cảnh = n (dùng khi cần con số chính xác).

    Cách làm — CHỌN DỰNG DẦN (greedy): ở mỗi bước, chỉ xét những file mà nếu
    thêm vào thì mọi video trước đó vẫn giữ mức trùng ≤ giới hạn.
    """
    pool = list(imgs) + list(vids)
    if not pool:
        return None if strict else []
    if use_all:
        n = len(pool)
    elif fixed_n:
        n = int(fixed_n)
    else:
        lo = max(1, int(n_min))
        hi = max(lo, int(n_max))
        n = rng.randint(lo, hi)
    n = min(n, len(pool))

    prev = [set(p) for p in (prev_sets or [])]
    # TRẦN TRÙNG CHỈ ÁP CHO ẢNH. Video được dùng lại thoải mái vì mỗi lần lấy
    # một CỬA SỔ THỜI GIAN khác bên trong file (xem _split_window) -> hai video
    # con không bao giờ cắt đúng khớp cùng một đoạn.
    ovl = float(max_overlap)

    usage = {}
    for s in prev:
        for name in s:
            usage[name] = usage.get(name, 0) + 1

    if not prev:
        picked = rng.sample(pool, n)
        rng.shuffle(picked)
        return picked

    img_pool = [p for p in pool if p.suffix.lower() in IMG_EXT]
    vid_pool = [p for p in pool if p.suffix.lower() not in IMG_EXT]
    img_bit = {p.name: i for i, p in enumerate(img_pool)}

    # Ảnh của mỗi video trước -> BITMASK + số ảnh. Nhờ vậy phép kiểm tra trùng
    # chỉ còn vài phép đếm bit (nhanh gấp trăm lần so với so set từng phần tử),
    # đủ nhanh để thử lại hàng chục lần cho mỗi video.
    prev_masks = []
    for s in prev:
        m, cnt = 0, 0
        for name in s:
            if Path(name).suffix.lower() in IMG_EXT:
                cnt += 1
                b = img_bit.get(name)
                if b is not None:
                    m |= (1 << b)
        prev_masks.append((m, cnt))

    def overlap_ok(mask, cnt):
        """Chung với MỌI video trước <= floor(50% số ảnh của cặp) hay không."""
        for pm, pc in prev_masks:
            lim = int(math.floor(min(cnt, pc) * ovl))
            if (mask & pm).bit_count() > lim:
                return False
        return True

    # TRỌNG SỐ tính MỘT LẦN cho cả hàm: `usage` không đổi trong lúc chọn, mà
    # mỗi lần bốc lại phải thử tới `_TRIES` lần -> tính lại sẽ tốn hàng nghìn
    # số ngẫu nhiên mỗi video (đo được: pool 61 ảnh mất 11.6s).
    w_img = [rng.uniform(0.75, 1.25) / (1.0 + usage.get(p.name, 0))
             for p in img_pool]
    w_vid = [rng.uniform(0.75, 1.25) / (1.0 + usage.get(p.name, 0))
             for p in vid_pool]

    def draw(k):
        """Bốc k ảnh, ưu tiên ảnh ÍT DÙNG -> rải đều pool, vét tối đa."""
        if k <= 0:
            return [], 0
        got = _sample_weighted(img_pool, min(k, len(img_pool)), w_img, rng)
        m = 0
        for p in got:
            m |= (1 << img_bit[p.name])
        return got, m

    def draw_vid(k):
        if k <= 0:
            return []
        # chỉ bốc trong số video CÒN ngân sách cửa sổ. Trọng số phải dựng lại
        # theo đúng danh sách con này (w_vid dựng theo vid_pool đầy đủ nên chỉ
        # số không khớp -> IndexError).
        w = [rng.uniform(0.75, 1.25) / (1.0 + usage.get(p.name, 0))
             for p in avail_vid]
        return _sample_weighted(avail_vid, min(k, len(avail_vid)), w, rng)

    # BỐC CẢ TẬP MỘT LƯỢT rồi kiểm tra (rejection sampling). Cách "dựng dần
    # từng file" trước đây chấm điểm theo tập ĐANG CHỌN DỞ (nhỏ hơn n) nên trần
    # bị tính quá chặt: 19 ảnh chỉ ra 4-5 video, trong khi sức chứa thật của
    # 19 ảnh ở cỡ cảnh 5 (trần 50%) là hàng chục video. Bốc cả tập rồi thử lại
    # cho ra đúng sức chứa thật mà vẫn giữ nguyên ràng buộc.
    #
    # MỖI VIDEO CON CỐ ĐỊNH 1 PHÂN CẢNH VIDEO GỐC + phần còn lại là ảnh.
    # Hết chỗ cắt trong video gốc (đã vét hết số cửa sổ) -> chuyển hẳn sang
    # TOÀN ẢNH, không quay vòng lại đoạn cũ. `vid_quota` = {tên file: số cửa sổ
    # còn lại} — phải theo TỪNG FILE, nếu chỉ đếm tổng thì 1 video ngắn có thể
    # bị cắt quá số cửa sổ của nó (đã gặp thật: clip 20s bị cắt 6 lần).
    # vid_quota=None -> không giới hạn (giữ hành vi cũ cho chỗ gọi trực tiếp).
    if vid_quota is None:
        avail_vid = list(vid_pool)
    else:
        avail_vid = [p for p in vid_pool if int(vid_quota.get(p.name, 0)) > 0]
    want_vid = 1 if (avail_vid and n >= 1) else 0
    # KHÔNG bù video khi ảnh thiếu. Bù sẽ khiến 1 video con ôm 2-3 phân cảnh
    # video gốc -> tiêu quota gấp đôi, các video con sau hết clip dù quota vẫn
    # còn (đo được thật: quota 4 nhưng chỉ 3 video con có clip). Thiếu ảnh thì
    # để plan_folder trả None -> plan_sequence tự lùi về cỡ cảnh nhỏ hơn.
    want_img = min(n - want_vid, len(img_pool))
    if want_vid and not avail_vid:
        want_vid = 0
        want_img = min(n, len(img_pool))

    for _ in range(_TRIES):
        got_i, m = draw(want_img)
        if len(got_i) + want_vid < n:
            break                      # pool không đủ file cho cỡ cảnh này
        if overlap_ok(m, len(got_i)):
            picked = got_i + draw_vid(want_vid)
            rng.shuffle(picked)
            return picked

    # Ảnh đã cạn phép chọn -> đổi bớt ảnh lấy video. Video KHÔNG tính trùng
    # (mỗi lần cắt một cửa sổ khác nhau) nên cách này kéo dài được chuỗi video.
    # CHỈ làm khi còn quota cửa sổ video gốc; hết quota thì phải giữ TOÀN ẢNH
    # (không được lôi video trở lại rồi cắt lại đoạn cũ).
    if avail_vid:
        for k in range(want_img - 1, -1, -1):
            v_need = min(n - k, len(vid_pool))
            if v_need > 1:
                continue          # giữ đúng 1 phân cảnh video gốc mỗi video
            if k + v_need < n:
                continue
            for _ in range(_TRIES):
                got_i, m = draw(k)
                if overlap_ok(m, len(got_i)):
                    picked = got_i + draw_vid(v_need)
                    rng.shuffle(picked)
                    return picked

    if strict:
        return None               # hết cách chọn hợp lệ -> pool không đủ
    # Không strict (render 1 video lẻ): trả về tập ÍT vi phạm nhất.
    best, best_bad = None, None
    for _ in range(_TRIES):
        got_i, m = draw(want_img)
        if len(got_i) + want_vid < n:
            continue
        bad = 0
        for pm, pc in prev_masks:
            lim = int(math.floor(min(len(got_i), pc) * ovl))
            bad += max(0, (m & pm).bit_count() - lim)
        if best is None or bad < best_bad:
            best, best_bad = got_i + draw_vid(want_vid), bad
            if bad == 0:
                break
    if best is None:
        best = draw(want_img)[0] + draw_vid(want_vid)
    rng.shuffle(best)
    return best





def pick_scene_items(imgs, vids, n_vid, n_img, rng, cutpool,
                     prev_sets=None, max_overlap=0.5, strict=False,
                     spread=True, fps=30.0, min_slot=1.0):
    """Chọn media cho 1 video con: `n_vid` cảnh VIDEO + `n_img` cảnh ẢNH.

    LUẬT MỚI (v1.20.0): video gốc được CẮT LIA thành nhiều đoạn, mỗi đoạn dùng
    1 lần -> MỘT video con có thể dùng NHIỀU đoạn (thường 5-6). Vì vậy CÙNG MỘT
    file video nguồn có thể xuất hiện nhiều lần trong danh sách trả về — mỗi
    lần là một đoạn khác nhau (CutPool.take cắt tuần tự, không lặp).

    Trần trùng 50% CHỈ áp cho ẢNH (giữ nguyên hành vi cũ).

    Trả về list [(Path, is_video), ...] độ dài n_vid + n_img, hoặc None nếu
    strict=True và không chọn đủ.
    """
    rng = rng or random.Random()
    n_vid = max(0, int(n_vid))
    n_img = max(0, int(n_img))
    if n_vid + n_img <= 0:
        return None if strict else []

    prev = [set(p) for p in (prev_sets or [])]
    ovl = float(max_overlap)
    img_pool = [p for p in imgs]
    img_bit = {p.name: i for i, p in enumerate(img_pool)}

    prev_masks = []
    for s in prev:
        m, cnt = 0, 0
        for name in s:
            if Path(name).suffix.lower() in IMG_EXT:
                cnt += 1
                b = img_bit.get(name)
                if b is not None:
                    m |= (1 << b)
        prev_masks.append((m, cnt))

    def overlap_ok(mask, cnt):
        for pm, pc in prev_masks:
            lim = int(math.floor(min(cnt, pc) * ovl))
            if (mask & pm).bit_count() > lim:
                return False
        return True

    usage = {}
    for s in prev:
        for name in s:
            usage[name] = usage.get(name, 0) + 1

    # ── chọn ẢNH (có ràng buộc trùng) ───────────────────────
    def draw_imgs(k):
        if k <= 0:
            return [], 0
        if k > len(img_pool):
            return None, None
        w = [rng.uniform(0.75, 1.25) / (1.0 + usage.get(p.name, 0))
             for p in img_pool]
        got = _sample_weighted(img_pool, k, w, rng) if spread else rng.sample(img_pool, k)
        m = 0
        for p in got:
            m |= (1 << img_bit[p.name])
        return got, m

    got_i = None
    if n_img > 0:
        for _ in range(_TRIES):
            gi, m = draw_imgs(n_img)
            if gi is None:
                break
            if overlap_ok(m, len(gi)):
                got_i = gi
                break
        if got_i is None:
            if strict:
                return None
            # nới: lấy tập ít vi phạm nhất
            best, best_bad = None, None
            for _ in range(_TRIES):
                gi, m = draw_imgs(n_img)
                if gi is None:
                    break
                bad = 0
                for pm, pc in prev_masks:
                    lim = int(math.floor(min(len(gi), pc) * ovl))
                    bad += max(0, (m & pm).bit_count() - lim)
                if best is None or bad < best_bad:
                    best, best_bad = gi, bad
                    if bad == 0:
                        break
            got_i = best if best is not None else []
    else:
        got_i = []

    # ── chọn VIDEO: bốc theo số giây CÒN LẠI (file dài dùng nhiều hơn) ──
    got_v = []
    if n_vid > 0:
        cands = [p for p in vids if cutpool and cutpool.has_any(min_slot)
                 and cutpool.remaining_sec(p.name) >= min_slot - 1e-6]
        if not cands:
            if strict:
                return None
            return None
        for _ in range(n_vid):
            live = [p for p in cands
                    if cutpool.remaining_sec(p.name) >= min_slot - 1e-6]
            if not live:
                break
            # trọng số = số giây còn lại (file dài được dùng nhiều đoạn hơn),
            # nhân thêm hệ số ít-dùng để rải đều giữa các file cùng độ dài.
            ws = [(cutpool.remaining_sec(p.name) ** 1.2) /
                  (1.0 + 0.35 * usage.get(p.name, 0)) for p in live]
            pick = _sample_weighted(live, 1, ws, rng)[0]
            got_v.append(pick)
            usage[pick.name] = usage.get(pick.name, 0) + 1

    if n_vid > 0 and not got_v:
        if strict:
            return None

    items = [(p, False) for p in got_i] + [(p, True) for p in got_v]
    rng.shuffle(items)
    return items


def split_vid_img(n_scenes, n_imgs, n_vid_slots, rng, vid_ratio=(0.6, 0.85)):
    """Chia `n_scenes` cảnh thành bao nhiêu cảnh VIDEO và bao nhiêu cảnh ẢNH.

    Đo từ video mẫu user gửi: 8 cảnh = 6-7 đoạn video + 1-2 ảnh -> video chiếm
    ĐA SỐ (75-88%). Nhưng không được vượt số đoạn video còn cắt được
    (`n_vid_slots`) và không vượt số ảnh có trong pool (`n_imgs`).

    n_scenes: tổng số cảnh của video con.
    n_imgs: số ẢNH thật có trong pool.
    n_vid_slots: số đoạn video còn cắt được (CutPool.video_slots_left).
    vid_ratio: khoảng tỉ lệ cảnh video mong muốn (mặc định 60-85%).

    Trả về (n_vid, n_img) với n_vid + n_img == n_scenes (trừ khi pool quá thiếu).
    """
    n_scenes = max(0, int(n_scenes))
    if n_scenes <= 0:
        return 0, 0
    n_imgs = max(0, int(n_imgs))
    n_vid_slots = max(0, int(n_vid_slots))

    lo_r, hi_r = float(vid_ratio[0]), float(vid_ratio[1])
    lo_r = min(max(0.0, lo_r), 1.0)
    hi_r = min(max(lo_r, hi_r), 1.0)
    n_vid = int(round(n_scenes * rng.uniform(lo_r, hi_r)))
    n_vid = max(0, min(n_vid, n_vid_slots, n_scenes))
    # Giữ tối thiểu 1 cảnh video khi còn đoạn (video mẫu luôn có video).
    if n_vid_slots > 0 and n_vid == 0:
        n_vid = 1
    n_img = n_scenes - n_vid
    # Không đủ ảnh -> bù bằng video (nếu còn đoạn).
    if n_img > n_imgs:
        need = n_img - n_imgs
        n_vid = min(n_scenes, n_vid + min(need, n_vid_slots - n_vid))
        n_img = n_scenes - n_vid
    return n_vid, n_img


def distribute_frames(total_frames, n, rng, lo_frames, hi_frames, weights=None):
    """Chia total_frames thành n phần nguyên, có jitter, tổng CHÍNH XÁC.

    Tự nới lo/hi nếu n quá ít/quá nhiều so với total_frames, để tổng luôn khớp.
    """
    if n <= 0:
        return []

    # n * hi < total  -> phải cho phép cảnh dài hơn
    if n * hi_frames < total_frames:
        hi_frames = int(math.ceil(total_frames / float(n)))
    # n * lo > total  -> phải cho phép cảnh ngắn hơn
    if n * lo_frames > total_frames:
        lo_frames = max(1, total_frames // n)
    lo_frames = max(1, min(lo_frames, hi_frames))

    if weights is None:
        weights = [rng.uniform(0.72, 1.28) for _ in range(n)]
    s = float(sum(weights)) or 1.0
    raw = [total_frames * w / s for w in weights]
    out = [int(math.floor(r)) for r in raw]
    rem = total_frames - sum(out)
    order = sorted(range(n), key=lambda i: -(raw[i] - out[i]))
    for i in order[:max(0, rem)]:
        out[i] += 1

    # clamp vào [lo, hi]
    for i in range(n):
        out[i] = max(lo_frames, min(hi_frames, out[i]))

    # bù trừ để tổng vẫn đúng
    guard = 0
    while sum(out) != total_frames and guard < 5000:
        guard += 1
        diff = total_frames - sum(out)
        if diff > 0:
            cand = [i for i in range(n) if out[i] < hi_frames]
            if not cand:
                break
            i = max(cand, key=lambda k: out[k])
            out[i] += 1
        else:
            cand = [i for i in range(n) if out[i] > lo_frames]
            if not cand:
                break
            i = max(cand, key=lambda k: out[k])
            out[i] -= 1
    return out


def kenburns_params(rng, kb_min, kb_max):
    """Sinh thông số Ken Burns ngẫu nhiên: (zs, ze, px0, px1, py0, py1)."""
    style = rng.choice(["in", "out", "in", "out", "pan", "diag"])
    zmin, zmax = float(kb_min), float(kb_max)

    if style == "in":
        zs, ze = zmin, rng.uniform(zmin + 0.03, zmax)
    elif style == "out":
        zs, ze = rng.uniform(zmin + 0.03, zmax), zmin
    elif style == "pan":
        zs = ze = rng.uniform(zmin + 0.02, zmax)
    else:  # diag
        zs, ze = zmin, rng.uniform(zmin + 0.04, zmax)

    if style == "pan":
        if rng.random() < 0.5:
            px0, px1 = 0.0, 1.0
        else:
            px0, px1 = 1.0, 0.0
        py0 = py1 = rng.choice([0.25, 0.5, 0.5, 0.75])
    elif style == "diag":
        px0, px1 = (0.0, 1.0) if rng.random() < 0.5 else (1.0, 0.0)
        py0, py1 = (0.0, 1.0) if rng.random() < 0.5 else (1.0, 0.0)
    else:
        # zoom tại tâm, lệch nhẹ để không bị "máy móc"
        j = lambda: rng.uniform(0.35, 0.65)
        px0 = px1 = j()
        py0 = py1 = j()
    return zs, ze, px0, px1, py0, py1


def _grade_filter(rng, strength=1.0):
    """Sinh chuỗi filter ffmpeg tạo HIỆU ỨNG MÀU ngẫu nhiên cho 1 cảnh.

    Trả về (chuỗi_filter, tên_kiểu). Mỗi lần render lại random khác nhau
    để video không bị coi là "sản xuất hàng loạt".
    """
    s = float(strength)
    # (tên, filter, trọng số) - trọng số để kiểu nhẹ xuất hiện nhiều hơn
    styles = [
        ("am", "eq=contrast=1.06:brightness=0.015:saturation=1.10:gamma=1.02", 3),
        ("lanh", "colorbalance=bs=0.06:bm=0.03:gs=-0.02", 2),
        ("am-nhe", "colorbalance=rs=0.06:rm=0.03:gm=-0.02", 2),
        ("tuong-phan", "eq=contrast=1.12:brightness=-0.01:saturation=1.04", 2),
        ("phim", "curves=preset=medium_contrast,eq=saturation=0.96", 2),
        ("mo", "eq=brightness=0.03:saturation=1.08:gamma=1.06", 1),
        ("sang", "eq=brightness=0.05:contrast=1.04:saturation=1.06", 1),
        ("trong", "eq=contrast=1.10:brightness=-0.02:saturation=0.94", 1),
    ]
    names = [x[0] for x in styles]
    wts = [x[2] for x in styles]
    i = rng.choices(range(len(styles)), weights=wts, k=1)[0]
    kind, base = styles[i][0], styles[i][1]

    # thêm chút ngẫu nhiên liên tục quanh kiểu đã chọn
    d_sat = 1.0 + rng.uniform(-0.05, 0.05) * s
    d_bri = rng.uniform(-0.012, 0.012) * s
    parts = [base, "eq=saturation=%.3f:brightness=%.3f" % (d_sat, d_bri)]

    # 25% cảnh được vignette tối 4 góc (rất nhẹ)
    if rng.random() < 0.25:
        parts.append("vignette=angle=PI/%.2f" % rng.uniform(9.0, 16.0))
        kind += "+vignette"
    return ",".join(parts), kind


def _internal_size(src_w, src_h, out_w, out_h):
    """Chọn kích thước nội bộ: supersample 2x nếu ảnh gốc đủ nét."""
    if src_w and src_h and src_w >= out_w * 1.4 and src_h >= out_h * 1.4:
        return out_w * 2, out_h * 2
    return out_w, out_h


def _kb_center(v):
    """Đưa tham số x/y của Ken Burns về tâm (0.5) để không cắt lệch chủ thể.

    zoompan crop tại tâm khung; cho x/y lệch tâm sẽ cắt mất mặt khi chủ thể
    nằm gần mép ảnh. Giữ zoom + hướng zoom, bỏ phần lệch tâm.
    """
    try:
        return 0.5 if abs(float(v) - 0.5) < 0.35 else (0.5 + 0.15 * (1 if float(v) > 0.5 else -1))
    except (TypeError, ValueError):
        return 0.5


def _prepare_image(path, out_w, out_h, bg_color, focus=None, use_face=True):
    """Ảnh -> PNG đã cover-crop 9:16, xử lý alpha + EXIF.

    focus: (fx, fy) tỉ lệ 0..1 — tâm vùng cần giữ. None = giữa khung.
    use_face: tự tìm mặt chủ thể để đặt tâm crop (chống cắt mất mặt).
    """
    im = Image.open(path)
    im = ImageOps.exif_transpose(im)
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        base = Image.new("RGB", im.size, tuple(bg_color))
        base.paste(im, mask=im.split()[-1])
        im = base
    else:
        im = im.convert("RGB")

    iw, ih = _internal_size(im.width, im.height, out_w, out_h)
    src_ratio = im.width / im.height
    dst_ratio = iw / ih

    # tâm crop: ưu tiên focus truyền vào, rồi tới mặt tìm được
    if focus is None and use_face:
        fc = facedetect.main_face(im)
        if fc:
            focus = (fc[0], fc[1])

    if src_ratio > dst_ratio:
        # ảnh ngang hơn khung -> cắt hai bên, giữ trọn chiều cao
        nw = int(round(im.height * dst_ratio))
        fx = 0.5 if focus is None else float(focus[0])
        x = int(round(im.width * fx - nw / 2.0))
        x = max(0, min(im.width - nw, x))
        im = im.crop((x, 0, x + nw, im.height))
    elif src_ratio < dst_ratio:
        # ảnh dọc hơn khung -> cắt trên/dưới, giữ trọn chiều ngang
        nh = int(round(im.width / dst_ratio))
        fy = 0.5 if focus is None else float(focus[1])
        y = int(round(im.height * fy - nh / 2.0))
        y = max(0, min(im.height - nh, y))
        im = im.crop((0, y, im.width, y + nh))
    return im.resize((iw, ih), Image.LANCZOS)


def _escape_filter_path(p):
    """Escape path cho filtergraph ffmpeg (dấu \\ và : trên Windows)."""
    s = str(p).replace("\\", "/")
    s = s.replace(":", "\\:")
    s = s.replace("'", "\\'")
    return s


def _split_window(rng, lo, hi, need, cfg, fps):
    """Chia 1 slot video thành 2-3 ĐOẠN NGẮN KHÁC NHAU trong cửa sổ [lo, hi].

    Trả về [(start_giây, số_frame), ...], tổng frame = round(need*fps) — nên
    thời lượng tổng không đổi, chỉ đổi cách lấy.

    Cửa sổ là khái niệm "cắt tăng dần": mỗi video nguồn được chia thành các
    khung dài `seg_window` giây. Lần dùng thứ k lấy trong khung thứ k (do
    plan_folder truyền vào), hết khung thì quay lại khung đầu — nhờ vậy video
    con sau không cắt đúng khớp đoạn mà video con trước đã cắt.
    """
    lo = max(0.0, float(lo))
    hi = max(lo, float(hi))
    need = max(0.05, float(need))
    # cửa sổ phải đủ chứa slot -> trượt về trước nếu thiếu
    if hi - lo < need:
        lo = max(0.0, hi - need)
    span = hi - lo

    s_min = max(1, int(cfg.get("seg_min", 2)))
    s_max = max(s_min, int(cfg.get("seg_max", 3)))
    d_min = max(0.2, float(cfg.get("seg_dur_min", 1.0)))
    d_max = max(d_min, float(cfg.get("seg_dur_max", 3.0)))

    total_f = max(1, int(round(need * fps)))
    lo_f = max(1, int(round(d_min * fps)))
    hi_f = max(lo_f, int(round(d_max * fps)))

    # Số đoạn: ngẫu nhiên trong [seg_min, seg_max] nhưng KHÔNG cố ép. Chỉ tách
    # khi slot thật sự đủ chỗ cho từng đoạn >= seg_dur_min. Hết chỗ -> lấy
    # phần còn lại thành 1 đoạn rồi DỪNG (không bù, không chia nhỏ thêm).
    n = rng.randint(s_min, s_max)
    n = max(1, min(n, int(total_f // lo_f)))
    if span < d_min * 2:
        n = 1
    if n <= 1:
        st = rng.uniform(lo, max(lo, hi - need)) if span > need else lo
        return [(st, total_f)]

    fr = distribute_frames(total_f, n, rng, lo_f, hi_f)
    durs = [f / float(fps) for f in fr]

    if span >= need * 1.15:
        # cửa sổ rộng -> rải đều có KHOẢNG NGHỈ ngẫu nhiên giữa các đoạn.
        # Cách này BẢO ĐẢM không chồng nhau (thử ngẫu nhiên rồi rơi về `lo`
        # sẽ tạo ra 2 đoạn trùng hình — đã gặp thực tế).
        # Chia phần dư thành n+1 khe (trước, giữa, sau) rồi đặt nối tiếp.
        leftover = max(0.0, span - sum(durs))
        wts = [rng.random() + 0.05 for _ in range(len(durs) + 1)]
        tot_w = sum(wts)
        gaps = [leftover * w / tot_w for w in wts]
        picks, cur = [], lo + gaps[0]
        for idx, d in enumerate(durs):
            picks.append((cur, d))
            cur += d + gaps[idx + 1]
        # kẹp lại trong cửa sổ nếu sai số làm trôi
        if picks and picks[-1][0] + picks[-1][1] > hi + 1e-6:
            shift = picks[-1][0] + picks[-1][1] - hi
            picks = [(max(lo, s - shift), d) for s, d in picks]
    else:
        # cửa sổ chật -> nối tiếp nhau, điểm bắt đầu ngẫu nhiên
        st0 = rng.uniform(lo, max(lo, hi - need))
        picks, cur = [], st0
        for d in durs:
            picks.append((cur, d))
            cur += d
    return [(s, f) for (s, _d), f in zip(picks, fr)]


class Stitcher:
    def __init__(self, cfg, log=None, progress=None):
        self.cfg = cfg
        self.log = log or (lambda m: None)
        self.progress = progress or (lambda a, b, c, d: None)
        self.ffmpeg = find_ffmpeg()
        self.ffprobe = find_ffprobe()
        self._ratio_cache = {}     # {path: nguồn đã đúng tỉ lệ khung?}
        if not self.ffmpeg:
            raise StitchError("Không tìm thấy ffmpeg. Kiểm tra thirdparty/ffmpeg.")

    def plan_sequence(self, folder, n_videos, max_overlap=0.5, fixed_n=None,
                      attempts=6, fallback_n=None, stop_on_fail=True,
                      prev_sets=None):
        """Lập kế hoạch cho CẢ CHUỖI video trong 1 folder (tuần tự).

        Đây là nguồn sự thật duy nhất: cả báo "số video tối đa" lẫn render đều
        đi qua hàm này, nên con số báo trước luôn khớp với số render thật.

        Mỗi video thử tối đa `attempts` lần với seed ngẫu nhiên khác nhau — vì
        cách chọn dựng dần có thể kẹt sớm ở một nhánh ngẫu nhiên xấu. Nếu vẫn
        kẹt và có `fallback_n`, thử lại với cỡ cảnh đó (cỡ nhỏ luôn hiệu quả
        hơn) — nhờ vậy đạt được đúng con số đã báo trước.

        prev_sets: nếu truyền vào list, hàm ghi thêm vào đó (để gọi nối tiếp).
        Trả về danh sách plan.
        """
        cfg = self.cfg
        if prev_sets is None:
            prev_sets = []
        plans = []
        segs_used = {}                # {tên file: set đoạn đã cắt} -> không trùng
        # ── NGÂN SÁCH ĐOẠN CẮT DÙNG CHUNG CẢ CHUỖI (v1.20.0) ─────────────
        # Một CutPool duy nhất cho cả folder: con trỏ cắt của mỗi video nguồn
        # chỉ tiến, nên đoạn đã dùng ở video con trước KHÔNG BAO GIỜ được dùng
        # lại. Hết sạch đoạn -> các video con sau tự chuyển sang TOÀN ẢNH
        # (đúng yêu cầu người dùng). Dùng bản CLONE cho mỗi lần thử để nhánh
        # thử thất bại không ăn mất đoạn video.
        _imgs, _vids = list_media(folder, cfg.get("recursive", False))
        cut_pool = CutPool(self._video_durations(_vids))
        for _ in range(max(0, int(n_videos))):
            plan = None
            for _a in range(max(1, int(attempts))):
                trial = cut_pool.clone()
                plan = self.plan_folder(folder, prev_sets=prev_sets,
                                        max_overlap=max_overlap, strict=True,
                                        spread=True, fixed_n=fixed_n,
                                        prev_segs=segs_used,
                                        cut_pool=trial)
                if plan is not None:
                    cut_pool = trial        # chốt: giữ đoạn đã cắt
                    break
            if plan is None and fallback_n and fallback_n != fixed_n:
                for _a in range(max(1, int(attempts))):
                    trial = cut_pool.clone()
                    plan = self.plan_folder(folder, prev_sets=prev_sets,
                                            max_overlap=max_overlap,
                                            strict=True, spread=True,
                                            fixed_n=fallback_n,
                                            prev_segs=segs_used,
                                            cut_pool=trial)
                    if plan is not None:
                        cut_pool = trial
                        break
            if plan is None:
                if stop_on_fail:
                    break
                continue
            names = [s["path"].name for s in plan["scenes"]]
            prev_sets.append(names)
            for nm, st in (plan.get("segs_used") or {}).items():
                segs_used[nm] = st
            plans.append(plan)
        return plans

    def pool_report(self, folder, max_overlap=None, sim_limit=200):
        """Đếm media trong folder + số video tối đa tạo được (không render).

        Chạy THẬT quy trình lập kế hoạch (plan_sequence, không encode nên rất
        nhanh) cho từng cỡ cảnh trong [n_min, n_max] rồi lấy con số CAO NHẤT —
        vì cỡ cảnh nhỏ cho phép tạo nhiều video hơn. Nhờ dùng chung
        plan_sequence, con số này khớp đúng với số video render được.

        sim_limit: đếm tối đa bao nhiêu video. Nếu chạm trần này thì trả về
        `capped=True` và `max_videos=sim_limit` — GUI phải hiển thị dạng "≥ N"
        chứ không được nói đúng N (đó là trần đếm, không phải số thật).

        Trả về dict: {imgs, vids, pool, max_videos, best_n, n_min, n_max,
                      max_overlap, capped}
        """
        cfg = self.cfg
        if max_overlap is None:
            max_overlap = cfg.get("max_overlap", 0.5)
        imgs, vids = list_media(folder, cfg.get("recursive", False))
        pool = len(imgs) + len(vids)
        lo = max(1, int(cfg.get("n_min", 5)))
        hi = max(lo, int(cfg.get("n_max", 7)))
        if pool == 0:
            return {"imgs": 0, "vids": 0, "pool": 0, "max_videos": 0,
                    "best_n": lo, "n_min": lo, "n_max": hi,
                    "max_overlap": float(max_overlap), "capped": False}

        best, best_n = 0, lo

        def scan(seed=None):
            """Trả về (số video lập được, cỡ cảnh) cho từng cỡ cảnh."""
            c = dict(cfg)
            if seed is not None:
                c["seed"] = seed
            q = Stitcher(c, log=lambda m: None)
            out = []
            seen = set()
            for n in range(lo, hi + 1):
                # Pool nhỏ hơn n_min vẫn làm được video (lấy trọn số media có).
                # Dùng cỡ cảnh HIỆU DỤNG = min(n, pool) để không bỏ sót ca
                # "pool < n_min" — trước đây thoát ngay nên báo 0 video trong
                # khi thực tế lập được cả chục.
                n_eff = min(n, pool)
                if n_eff in seen:
                    continue
                seen.add(n_eff)
                # fallback_n: nếu cỡ cảnh n kẹt thì lùi về cỡ nhỏ nhất —
                # đúng bằng cách GUI sẽ lập kế hoạch, nên số khớp render thật.
                made = len(q.plan_sequence(folder, sim_limit,
                                           max_overlap=max_overlap,
                                           fixed_n=n_eff,
                                           fallback_n=min(lo, n_eff),
                                           attempts=3))
                out.append((made, n_eff))
                # Chạm trần đếm -> không cần thử cỡ cảnh khác (cỡ cảnh nhỏ
                # luôn cho nhiều video nhất). Thoát sớm giữ pool lớn không
                # phải lập hàng nghìn kế hoạch vô ích.
                if made >= sim_limit:
                    break
            return out

        for made, n in scan():
            if made > best:
                best, best_n = made, n

        # Chạm trần đếm ngay lượt đầu -> dừng, khỏi quét thêm seed.
        if best < sim_limit:
            # Con số hiển thị phải ỔN ĐỊNH giữa các lần bấm. Vì cách chọn có
            # yếu tố ngẫu nhiên, thử thêm vài seed cố định và lấy kết quả CAO
            # NHẤT — đó là mức chắc chắn đạt được, và lặp lại lần nào cũng ra
            # cùng một số.
            for s in (20260101, 424242):
                for made, n in scan(s):
                    if made > best:
                        best, best_n = made, n
                    if best >= sim_limit:
                        break
                if best >= sim_limit:
                    break

        return {"imgs": len(imgs), "vids": len(vids), "pool": pool,
                "max_videos": best, "best_n": best_n,
                "n_min": lo, "n_max": hi,
                "max_overlap": float(max_overlap),
                # số ĐOẠN CẮT còn dùng được từ video gốc (mỗi đoạn dùng 1 lần;
                # hết đoạn thì các video con sau chuyển sang toàn ảnh)
                "vid_cuts": sum(video_cut_budget(
                    vids, self.ffprobe,
                    cfg.get("seg_dur_min", 2.5),
                    cfg.get("seg_dur_max", 4.0)).values()),
                "vid_windows": sum(video_cut_budget(
                    vids, self.ffprobe,
                    cfg.get("seg_dur_min", 2.5),
                    cfg.get("seg_dur_max", 4.0)).values()),
                "capped": best >= sim_limit}




    # ── public ─────────────────────────────────────────────
    def plan_folder(self, folder, prev_sets=None, max_overlap=0.5, strict=False,
                    spread=True, fixed_n=None, prev_use=None, prev_segs=None,
                    vid_left=None, cut_pool=None):
        """Lập kế hoạch render (chưa encode) — chạy tuần tự để giữ ràng buộc
        không trùng media giữa các video cùng folder.

        strict=True: hết cách chọn mà không vi phạm -> trả về None
        (GUI dùng để báo "pool không đủ" và dừng).
        spread=True: rải đều pool (vét tối đa công suất, vẫn ngẫu nhiên giữa
        các file cùng mức dùng).
        fixed_n: ép cỡ cảnh (dùng khi đếm số video tối đa / để con số báo
        trước khớp với số render thật).
        prev_use: dict {tên file: số lần đã dùng} — giữ để tương thích.
        cut_pool: CutPool — ngân sách ĐOẠN CẮT dùng chung cả chuỗi (v1.20.0).
        Truyền vào thì video gốc được CẮT LIA thành nhiều đoạn, mỗi đoạn dùng
        1 lần, MỘT video con dùng NHIỀU đoạn (luật mới). Không truyền thì tự
        dựng CutPool từ các video trong folder.
        """
        cfg = self.cfg
        rng = random.Random(cfg.get("seed"))
        seed_used = rng.random()
        if cfg.get("seed") is None:
            rng = random.Random(seed_used)

        out_w = int(cfg.get("out_w", 1080))
        out_h = int(cfg.get("out_h", 1920))
        fps = int(cfg.get("fps", 30))
        total = float(cfg.get("total", 15.0))
        total_frames = int(round(total * fps))

        imgs, vids = list_media(folder, cfg.get("recursive", False))
        if not imgs and not vids:
            raise StitchError("Folder không có ảnh/video hợp lệ: %s" % folder)

        # ── LUẬT MỚI (v1.20.0): CẮT LÌA video gốc thành NHIỀU ĐOẠN ───────
        # Mỗi đoạn chỉ dùng 1 lần; MỘT video con dùng NHIỀU đoạn (đo từ video
        # mẫu user gửi: 8 cảnh = 6-7 đoạn video + 1-2 ảnh). Hết đoạn video ->
        # các video con sau dùng TOÀN ẢNH.
        n_min_cfg = int(cfg.get("n_min", 5))
        n_max_cfg = int(cfg.get("n_max", 7))
        segmin = float(cfg.get("seg_dur_min", 0.0) or 0.0)
        lo_frames = max(1, int(round(float(cfg.get("min_clip", 1.2)) * fps)))
        max_clip = float(cfg.get("max_clip", 4.0))
        hi_frames = max(lo_frames, int(round(max_clip * fps)))
        # Có video -> sàn cảnh = seg_dur_min để slot đủ chỗ cho 1 đoạn dài
        # đúng mức tối thiểu người dùng đặt (2.5s).
        if vids and segmin > 0:
            lo_frames = max(lo_frames, int(round(segmin * fps)))
            hi_frames = max(lo_frames, hi_frames)

        if cut_pool is None:
            cut_pool = CutPool(self._video_durations(vids))

        slot_sec = lo_frames / float(fps)
        n_slots = cut_pool.video_slots_left(slot_sec) if vids else 0
        if fixed_n:
            n_scenes = max(1, int(fixed_n))
        else:
            n_scenes = rng.randint(max(1, n_min_cfg), max(1, n_max_cfg))
        # Trần số cảnh khả thi: ảnh có sẵn + số đoạn video còn cắt được.
        n_scenes = max(1, min(n_scenes, max(1, len(imgs) + n_slots)))
        if not imgs and n_slots == 0:
            return None

        n_vid, n_img = split_vid_img(n_scenes, len(imgs), n_slots, rng,
                                     cfg.get("vid_ratio", (0.6, 0.85)))
        n_scenes = n_vid + n_img
        if n_scenes <= 0:
            return None

        items = pick_scene_items(
            imgs, vids, n_vid, n_img, rng, cut_pool,
            prev_sets=prev_sets, max_overlap=max_overlap, strict=strict,
            spread=spread, fps=fps, min_slot=slot_sec)
        if items is None and not strict and imgs:
            # Hết đoạn video -> dùng TOÀN ẢNH (đúng yêu cầu người dùng).
            items = pick_scene_items(
                imgs, [], 0, min(n_scenes, len(imgs)), rng, cut_pool,
                prev_sets=prev_sets, max_overlap=max_overlap, strict=False,
                spread=spread, fps=fps, min_slot=slot_sec)
        if items is None:
            return None
        if not items:
            raise StitchError("Không chọn được file nào.")

        slots = distribute_frames(total_frames, len(items), rng,
                                  lo_frames, hi_frames)
        # Con trỏ cắt chạy TUẦN TỰ nên nhiều cảnh có thể dùng chung 1 file
        # video: phải trừ dần số giây đã lấy mới biết cảnh này còn được bao
        # nhiêu. Lặp vài vòng cho hội tụ (slot ngắn lại thì nhường giây cho
        # cảnh sau cùng file).
        for _ in range(4):
            avail, vpos = [], {}
            for (p, is_v), fr in zip(items, slots):
                if is_v:
                    rem = max(0.0, cut_pool.remaining_sec(p.name)
                              - vpos.get(p.name, 0.0))
                    avail.append(rem)
                    vpos[p.name] = vpos.get(p.name, 0.0) + min(fr / float(fps), rem)
                else:
                    avail.append(None)      # ảnh: không giới hạn
            new_slots = self._fit_to_media(slots, [p for p, _ in items],
                                           avail, fps, lo_frames)
            if new_slots == slots:
                break
            slots = new_slots

        # tham số ngẫu nhiên cho từng cảnh — sinh Ở ĐÂY (tuần tự) để phần render
        # chạy song song vẫn tất định, không phụ thuộc thứ tự luồng
        segs_used = {}
        for kk, vv in (prev_segs or {}).items():
            segs_used[kk] = set(vv)
        scenes = []
        for (p, is_v), fr in zip(items, slots):
            if is_v:
                need = fr / float(fps)
                # CẮT TUẦN TỰ: lấy `need` giây từ con trỏ của CHÍNH file này.
                # Mỗi đoạn chỉ dùng 1 lần — con trỏ chỉ tiến, không quay vòng.
                got = cut_pool.take(p.name, need, fps)
                if got is None:
                    # File hết giữa chừng (chỉ xảy ra khi slot bị kéo dài hơn
                    # dự tính) -> bỏ cảnh video này khỏi kế hoạch.
                    continue
                start, nfr = got
                segs = [(start, nfr)]
                done = segs_used.setdefault(p.name, set())
                sig = tuple((round(a, 2), int(b)) for a, b in segs)
                if set(sig) & done:
                    # Đoạn này đã dùng ở video con trước -> cắt tiếp về sau.
                    for _t in range(12):
                        got2 = cut_pool.take(p.name, need, fps)
                        if got2 is None:
                            break
                        segs = [(got2[0], got2[1])]
                        sig = tuple((round(a, 2), int(b)) for a, b in segs)
                        if not (set(sig) & done):
                            break
                for x in sig:
                    done.add(x)
                grade, kind = _grade_filter(rng, float(cfg.get("grade_strength", 1.0)) * 0.5)
                scenes.append({"kind": "video", "path": p, "frames": nfr,
                               "segs": segs, "start": segs[0][0],
                               "win": (round(start, 2), round(start + need, 2)),
                               "grade": grade, "grade_name": kind})
            else:
                kb = kenburns_params(rng, cfg.get("kb_min", 1.06), cfg.get("kb_max", 1.18))
                zs, ze, px0, px1, py0, py1 = kb
                px0 = _kb_center(px0); px1 = _kb_center(px1)
                py0 = _kb_center(py0); py1 = _kb_center(py1)
                grade, kind = (None, "")
                if cfg.get("grade", True):
                    grade, kind = _grade_filter(rng, cfg.get("grade_strength", 1.0))
                scenes.append({"kind": "image", "path": p, "frames": fr,
                               "kb": (zs, ze, px0, px1, py0, py1),
                               "grade": grade, "grade_name": kind})

        self.log("── %s" % Path(folder).name)
        self.log("   pool: %d ảnh + %d video | chọn %d file"
                 % (len(imgs), len(vids), len(items)))
        self.log("   seed: %.6f" % seed_used)
        parts = []
        for s in scenes:
            if s["kind"] == "video":
                wl, wh = s.get("win", (0, 0))
                nseg = len(s.get("segs", []))
                parts.append("%s %.2fs [%d đoạn, %.1f-%.1fs]"
                             % (s["path"].name[:22], s["frames"] / fps,
                                nseg, wl, wh))
            else:
                parts.append("%s %.2fs" % (s["path"].name[:22], s["frames"] / fps))
        self.log("   " + " → ".join(parts))

        return {"folder": str(folder), "out_w": out_w, "out_h": out_h,
                "fps": fps, "total": total, "scenes": scenes,
                "seed": seed_used, "bg": tuple(cfg.get("bg_color", (0, 0, 0))),
                "segs_used": segs_used}

    def render_plan(self, plan, out_path):
        """Render 1 plan -> file. An toàn khi chạy nhiều luồng cùng lúc."""
        out_w, out_h = plan["out_w"], plan["out_h"]
        fps, total = plan["fps"], plan["total"]
        bg = plan["bg"]
        scenes = plan["scenes"]

        tmp = Path(tempfile.mkdtemp(prefix="stitch_"))
        try:
            clips = []
            n = len(scenes)
            for idx, sc in enumerate(scenes):
                self.progress("clip", idx, n,
                              "%d/%d %s" % (idx + 1, n, sc["path"].name[:40]))
                clip = tmp / ("c%03d.mp4" % idx)
                if sc["kind"] == "video":
                    self._encode_video(sc, clip, out_w, out_h, fps)
                else:
                    self._encode_image(sc, clip, out_w, out_h, fps, bg)
                clips.append(clip)

            self.progress("concat", n, n + 1, "Ghép %d cảnh" % n)
            merged = tmp / "merged.mp4"
            self._concat(clips, merged)

            self.progress("audio", 0, 1, "Xuất file")
            self._finish(merged, Path(out_path), total)
            self.progress("done", 1, 1, "Xong")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        size = os.path.getsize(out_path) if os.path.isfile(out_path) else 0
        return {"out": str(out_path), "clips": len(scenes), "seed": plan["seed"],
                "bytes": size, "duration": total,
                "files": [s["path"].name for s in scenes]}

    def render_folder(self, folder, out_path, prev_sets=None, max_overlap=0.5):
        """Render 1 folder -> 1 video. Trả về dict thông tin."""
        plan = self.plan_folder(folder, prev_sets=prev_sets,
                                max_overlap=max_overlap)
        return self.render_plan(plan, out_path)


    # ── internal ───────────────────────────────────────────
    def _video_durations(self, vids):
        """Độ dài (giây) của từng video nguồn -> {tên file: giây}."""
        out = {}
        for p in vids:
            try:
                d = float(probe_duration(p, self.ffprobe))
            except Exception:
                d = 0.0
            if d > 0.05:
                out[p.name] = d
        return out

    def _fit_to_media(self, slots, items, durations, fps, lo_frames):
        """Video ngắn hơn slot -> cắt slot lại và bù thời gian cho file khác."""
        slots = list(slots)
        n = len(slots)
        for _ in range(8):
            deficit = 0
            for i, (p, dur) in enumerate(zip(items, durations)):
                if dur is None:
                    continue
                avail = int(math.floor(dur * fps)) if dur > 0 else 1
                # File ngắn hơn slot -> CHỈ lấy được `avail` frame. Sàn
                # lo_frames KHÔNG áp được (file không đủ dài), phải hạ slot
                # xuống avail và ghi nhận phần thiếu để bù cho cảnh khác.
                # (Bug cũ: kẹp ở max(lo_frames, avail) nhưng vẫn trừ theo
                # `avail` -> mỗi vòng lặp cộng dồn phần bù, tổng vượt 450.)
                if slots[i] > avail:
                    deficit += slots[i] - avail
                    slots[i] = max(1, avail)
            if deficit <= 0:
                break
            head = [i for i, d in enumerate(durations)
                    if d is None or int(math.floor(d * fps)) > slots[i]]
            if not head:
                break
            share = deficit // len(head)
            if share <= 0:
                share = 1
            for i in head:
                room = (10 ** 9) if durations[i] is None else \
                    int(math.floor(durations[i] * fps)) - slots[i]
                add = min(share, room)
                slots[i] += add
                deficit -= add
            if deficit > 0:
                for i in head:
                    room = (10 ** 9) if durations[i] is None else \
                        int(math.floor(durations[i] * fps)) - slots[i]
                    if room > 0:
                        slots[i] += 1
                        deficit -= 1
                        if deficit <= 0:
                            break
        return slots

    def _common_enc(self, fps):
        cfg = self.cfg
        return ["-c:v", "libx264", "-preset", str(cfg.get("preset", "veryfast")),
                "-crf", str(cfg.get("crf", 18)), "-pix_fmt", "yuv420p",
                "-profile:v", "high", "-level", "4.0",
                "-r", str(fps), "-fps_mode", "cfr",
                "-g", str(fps * 2), "-keyint_min", str(fps), "-sc_threshold", "0",
                "-an", "-movflags", "+faststart"]

    def _encode_image(self, sc, out, out_w, out_h, fps, bg):
        path = sc["path"]
        frames = sc["frames"]
        im = _prepare_image(path, out_w, out_h, bg,
                            use_face=self.cfg.get("face_focus", True))
        iw, ih = im.size
        tmp_png = Path(str(out) + ".png")
        im.save(tmp_png)

        zs, ze, px0, px1, py0, py1 = sc["kb"]
        d = max(1, frames - 1)
        z = "%.5f+(%.5f-%.5f)*on/%d" % (zs, ze, zs, d)
        x = "(iw-iw/zoom)*(%.4f+(%.4f-%.4f)*on/%d)" % (px0, px1, px0, d)
        y = "(ih-ih/zoom)*(%.4f+(%.4f-%.4f)*on/%d)" % (py0, py1, py0, d)
        vf = ("zoompan=z='%s':x='%s':y='%s':d=%d:s=%dx%d:fps=%d,"
              "setsar=1" % (z, x, y, frames, out_w, out_h, fps))
        if sc.get("grade"):
            vf += "," + sc["grade"]
            self.log("      màu: %s" % sc.get("grade_name", ""))
        vf += ",format=yuv420p"
        cmd = [self.ffmpeg, "-y", "-v", "error", "-i", str(tmp_png),
               "-vf", vf] + self._common_enc(fps) + [str(out)]
        try:
            run_cmd(cmd, log=None)
        finally:
            try:
                tmp_png.unlink()
            except OSError:
                pass
        return "image"

    def _ratio_fits(self, path, sw, sh):
        """True nếu video nguồn đã cùng tỉ lệ khung đích (crop không cắt gì).

        Dùng tỉ lệ chứ không dùng kích thước tuyệt đối: video 720x1280 và
        1080x1920 đều khớp khung 9:16.
        """
        key = str(path)
        if key in self._ratio_cache:
            return self._ratio_cache[key]
        ok = False
        try:
            sz = probe_size(path, self.ffprobe)
            if sz and sz[0] > 0 and sz[1] > 0:
                src = sz[0] / float(sz[1])
                dst = sw / float(sh)
                ok = abs(src - dst) <= 0.01 * dst      # lệch < 1%
        except Exception:
            ok = False
        self._ratio_cache[key] = ok
        return ok

    def _sample_focus(self, path, t0, dur, sw, sh):
        """Tìm mặt trong đoạn [t0, t0+dur]: lấy mẫu vài frame rồi lấy TRUNG VỊ.

        Một frame đơn dễ trượt (nhân vật quay đi, che tay, chuyển cảnh) — đo
        thật trên video nguồn: frame giữa đoạn có lúc KHÔNG thấy mặt dù các
        frame lân cận thấy rõ. Lấy 3 mẫu (30%/50%/70%) rồi trung vị nên chắc
        hơn hẳn mà chi phí vẫn nhỏ (chỉ cắt 1 frame mỗi lần).

        Trả về (fx, fy) tỉ lệ 0..1 theo khung ĐÃ SCALE — đúng hệ quy chiếu của
        filter crop. None nếu không frame nào thấy mặt.
        """
        d = Path(tempfile.mkdtemp(prefix="vface_"))
        try:
            hits = []
            for frac in (0.30, 0.50, 0.70):
                png = d / ("f%d.png" % len(hits))
                t = t0 + dur * frac
                cmd = [self.ffmpeg, "-y", "-v", "error"]
                if t > 0:
                    cmd += ["-ss", "%.3f" % t]
                cmd += ["-i", str(path),
                        "-vf", ("scale=%d:%d:force_original_aspect_ratio=increase:"
                                "flags=lanczos" % (sw, sh)),
                        "-frames:v", "1", str(png)]
                try:
                    run_cmd(cmd, log=None)
                    if png.is_file():
                        fc = facedetect.main_face(Image.open(png))
                        if fc:
                            hits.append((fc[0], fc[1]))
                except Exception:
                    pass
                if len(hits) >= 2:
                    break       # 2 mẫu khớp là đủ chắc, khỏi tốn thêm
            if not hits:
                return None
            xs = sorted(h[0] for h in hits)
            ys = sorted(h[1] for h in hits)
            return (xs[len(xs) // 2], ys[len(ys) // 2])
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def _encode_video(self, sc, out, out_w, out_h, fps):
        path = sc["path"]
        frames = sc["frames"]
        need = frames / float(fps)
        segs = sc.get("segs") or [(float(sc.get("start", 0.0)), frames)]
        zamt = float(self.cfg.get("video_zoom", 0.0))
        use_face = bool(self.cfg.get("face_focus", True))

        def build_chain(seg):
            st, nfr = float(seg[0]), int(seg[1])
            sw, sh = (out_w * 2, out_h * 2) if zamt > 0.001 else (out_w, out_h)
            # tâm crop: tìm mặt -> nhân vật chính không bị cắt khỏi khung dọc
            # khi video nguồn quay lệch. Video ĐÃ đúng tỉ lệ khung thì crop
            # không cắt gì -> bỏ qua, đỡ tốn ffmpeg và đỡ false positive.
            focus = None
            if use_face and not self._ratio_fits(path, sw, sh):
                focus = self._sample_focus(path, st, nfr / float(fps), sw, sh)
            if focus:
                xf = "clip(%.5f*iw-out_w/2,0,iw-out_w)" % focus[0]
                yf = "clip(%.5f*ih-out_h/2,0,ih-out_h)" % focus[1]
                self.log("      canh mặt (video): tâm %.2f, %.2f" % focus)
            else:
                xf, yf = "(iw-out_w)/2", "(ih-out_h)/2"
            chain = ("scale=%d:%d:force_original_aspect_ratio=increase:flags=lanczos,"
                     "crop=%d:%d:'%s':'%s',setsar=1"
                     % (sw, sh, sw, sh, xf, yf))
            if zamt > 0.001:
                d = max(1, frames - 1)
                z = "1+%.4f*on/%d" % (zamt, d)
                chain += (",zoompan=z='%s':x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2'"
                          ":d=1:s=%dx%d:fps=%d" % (z, out_w, out_h, fps))
            # áp hiệu ứng màu nhẹ cho video để tông màu đồng nhất với cảnh ảnh
            if sc.get("grade"):
                chain += "," + sc["grade"]
            return chain + ",format=yuv420p"

        def one(seg, dest):
            # seg = (start_giây, số_frame) — số frame đã tính sẵn ở _split_window
            st, nfr = float(seg[0]), int(seg[1])
            f = max(1, nfr)
            cmd = [self.ffmpeg, "-y", "-v", "error"]
            if st > 0:
                cmd += ["-ss", "%.3f" % st]
            cmd += ["-i", str(path),
                    "-vf", build_chain(seg),
                    # -frames:v (KHÔNG dùng -t): số giây lẻ làm ffmpeg làm tròn LÊN
                    # -> mỗi đoạn dư 1 frame, ghép 2-3 đoạn là lệch 2-3 frame.
                    "-frames:v", str(f)]
            cmd += self._common_enc(fps) + [str(dest)]
            run_cmd(cmd, log=None)

        if sc.get("grade"):
            self.log("      màu (video): %s" % sc.get("grade_name", ""))

        if len(segs) <= 1:
            one(segs[0], out)
            return "video"

        # 2-3 đoạn ngắn KHÁC NHAU trong cùng video -> encode riêng rồi ghép lại,
        # tổng frame giữ đúng bằng slot.
        tmp = Path(tempfile.mkdtemp(prefix="vseg_"))
        try:
            parts = []
            for i, seg in enumerate(segs):
                cp = tmp / ("s%02d.mp4" % i)
                one(seg, cp)
                parts.append(cp)
            self._concat(parts, out)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        return "video"

    def _concat(self, clips, out):
        listf = Path(str(out) + ".txt")
        with open(listf, "w", encoding="utf-8") as f:
            for c in clips:
                f.write("file '%s'\n" % str(c).replace("\\", "/").replace("'", "'\\''"))
        cmd = [self.ffmpeg, "-y", "-v", "error", "-f", "concat", "-safe", "0",
               "-i", str(listf), "-c", "copy", str(out)]
        run_cmd(cmd, log=None)
        return out

    def _finish(self, merged, out, total):
        audio = self.cfg.get("audio")
        out.parent.mkdir(parents=True, exist_ok=True)
        if audio and os.path.isfile(audio):
            # Audio chay DUNG 1 LUOT, KHONG lap lai (khong dung -stream_loop -1).
            # Audio ngan hon video -> chay het roi im lang, khong phat lai tu dau.
            adur = probe_duration(audio)
            if adur and adur < total - 0.05:
                self.log("  audio %.2fs < video %.2fs -> chay 1 luot, "
                         "phan con lai im lang" % (adur, total))
            end = total if not adur else min(adur, total)
            fade = min(0.6, end / 4.0)
            st = max(0.0, end - fade)
            af = ("afade=t=in:st=0:d=0.25,afade=t=out:st=%.2f:d=%.2f,apad"
                  % (st, fade))
            cmd = [self.ffmpeg, "-y", "-v", "error", "-i", str(merged),
                   "-i", str(audio),
                   "-filter_complex", "[1:a]%s[a]" % af,
                   "-map", "0:v:0", "-map", "[a]",
                   "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                   "-t", "%.4f" % total, "-movflags", "+faststart", str(out)]
            run_cmd(cmd, log=None)
        else:
            shutil.copyfile(str(merged), str(out))
        return out
