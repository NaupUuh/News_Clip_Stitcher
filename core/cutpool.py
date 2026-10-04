# -*- coding: utf-8 -*-
"""CAT LIA VIDEO GOC THANH NHIEU DOAN — moi doan dung 1 lan, het thi dung anh.

Luat CU (<= v1.19.0): moi video con dung DUNG 1 phan canh video goc + phan con
lai la anh. Het ngan sach cua so -> video con sau chuyen sang TOAN ANH.

Luat MOI (v1.20.0, theo yeu cau user):
  1. Video goc dai bao nhieu thi CAT LIA THANH NHIEU DOAN, chia LIEN TIEP
     khong chong nhau, phu het do dai video goc.
  2. Moi doan chi dung DUNG 1 LAN (khong quay vong, khong cat lai).
  3. Mot video con = NHIEU doan video (mac dinh 5-6) + vai anh.
  4. Het doan video -> cac video con sau dung TOAN ANH.

Cach lam: CON TRO TUAN TU. Moi video nguon co 1 con tro chay tu 0 den het.
Moi lan lay = cat tu con tro mot doan dai DUNG BANG do dai slot can, roi day
con tro len. Nho vay:
  - cac doan noi tiep nhau, khong chong, khong ho frame nao;
  - do dai doan khop CHINH XAC voi slot -> tong thoi luong video con khong doi;
  - het video (con lai < slot) -> tra ve None, nguoi goi chuyen sang anh.

Vi sao khong chia truoc thanh danh sach co dinh: do dai slot co gian (2.5-4s)
nen chia truoc se phai cat bot doan (hao video) hoac keo dai doan (lech tong
thoi luong). Con tro tu dong khop moi do dai.
"""
import math


def plan_cuts(duration, d_min=2.5, d_max=4.0, fps=30.0, max_seg=None):
    """UOC LUONG so doan se cat duoc tu 1 video (dung de BAO cho nguoi dung).

    Khong dung de cat that (viec cat do CutPool lam theo do dai slot thuc te).
    Tra ve so doan nguyen.
    """
    duration = float(duration or 0.0)
    if duration <= 0.05:
        return 0
    d_min = max(0.20, float(d_min or 2.5))
    d_max = max(d_min, float(d_max or 4.0))
    d_tb = (d_min + d_max) / 2.0
    n = max(1, int(round(duration / d_tb)))
    if n > 1 and duration / n < d_min:
        n = max(1, int(math.floor(duration / d_min)))
    if n > 1 and duration / n > d_max:
        n = max(1, int(math.ceil(duration / d_max)))
    if max_seg:
        n = min(n, max(1, int(max_seg)))
    return n


class CutPool:
    """Ngan sach doan cat theo TUNG video nguon (con tro tuan tu).

    durations: {ten file: do dai giay} cua cac video nguon.
    """

    def __init__(self, durations=None, skips=None, keep_min=0.0):
        self.dur = {}
        self.off = {}      # moc BAT DAU that su (bo doan den dau clip)
        for k, v in (durations or {}).items():
            try:
                fv = float(v)
            except (TypeError, ValueError):
                fv = 0.0
            if fv > 0.05:
                key = str(k)
                head, tail = 0.0, 0.0
                try:
                    h, t = (skips or {}).get(key, (0.0, 0.0))
                    head, tail = max(0.0, float(h or 0.0)), max(0.0, float(t or 0.0))
                except (TypeError, ValueError):
                    head, tail = 0.0, 0.0
                # khong bao gio bo qua qua nua file (tranh doan nhan dam)
                if head + tail > fv * 0.5:
                    head, tail = 0.0, 0.0
                # CHOT QUAN TRONG: neu bo den lam clip mat kha nang dung (con lai
                # < keep_min, tuc < do dai doan toi thieu) thi giam bot phan bo —
                # dung clip (du co vai frame den) van hon la mat han 1 doan video.
                try:
                    kmin = float(keep_min or 0.0)
                except (TypeError, ValueError):
                    kmin = 0.0
                if kmin > 0 and (fv - head - tail) < kmin and head + tail > 0:
                    excess = kmin - (fv - head - tail)
                    if excess >= head + tail:
                        head, tail = 0.0, 0.0
                    elif head >= tail:
                        head = max(0.0, head - excess)
                    else:
                        tail = max(0.0, tail - excess)
                self.off[key] = head
                self.dur[key] = max(0.05, fv - head - tail)
        self.pos = {k: 0.0 for k in self.dur}   # con tro TUONG DOI (0 = moc off)
        self.used = {k: 0 for k in self.dur}

    # ── truy van ────────────────────────────────────────────
    def remaining_sec(self, key):
        return max(0.0, self.dur.get(key, 0.0) - self.pos.get(key, 0.0))

    def total_sec(self):
        """Tong so giay video con dung duoc (moi video nguon)."""
        return sum(self.remaining_sec(k) for k in self.dur)

    def remaining(self, key, need_sec=0.0):
        """So doan con lay duoc cua 1 file (uoc luong theo `need_sec`)."""
        rem = self.remaining_sec(key)
        if need_sec and need_sec > 0:
            return int(rem // float(need_sec))
        return int(rem > 0.05)

    def has_any(self, need_sec=0.0):
        """Con file nao du dai de cat 1 doan `need_sec` hay khong."""
        if not need_sec:
            return self.total_sec() > 0.05
        return any(self.remaining_sec(k) >= float(need_sec) - 1e-6
                   for k in self.dur)

    def video_slots_left(self, need_sec):
        """Tong so doan `need_sec` con cat duoc tu TAT CA video nguon."""
        need = float(need_sec or 0.0)
        if need <= 0:
            return int(self.total_sec() > 0.05)
        return int(self.total_sec() // need)

    def keys_with(self, need_sec):
        return [k for k in self.dur
                if self.remaining_sec(k) >= float(need_sec) - 1e-6]

    def used_count(self):
        return sum(self.used.values())

    # ── lay doan ────────────────────────────────────────────
    def take(self, key, need_sec, fps=30.0):
        """Cat 1 doan tu con tro cua `key`, dai DUNG `need_sec`.

        Tra ve (start_giay, so_frame) hoac None neu file khong con du doan dai
        nhu vay (khi do coi nhu file da het -> khong dung lai nua).
        """
        key = str(key)
        d = self.dur.get(key)
        if not d:
            return None
        fps = float(fps or 30.0)
        need = max(1.0 / fps, float(need_sec))
        pos = self.pos.get(key, 0.0)
        avail = d - pos
        if avail < need - 1e-6:
            # KHONG danh dau het: phan con lai co the van du cho slot ngan hon
            # o lan goi sau (vi du slot cuoi cua video con khac). Chi tra None.
            return None
        fr = max(1, int(round(need * fps)))
        self.pos[key] = pos + fr / fps
        self.used[key] = self.used.get(key, 0) + 1
        return (self.off.get(key, 0.0) + pos, fr)   # moc TUYET DOI trong file

    def take_tail(self, key, min_sec, fps=30.0):
        """Lay NOT phan cuoi con lai cua `key` (neu >= min_sec). Dung het video.

        Tra ve (start_giay, so_frame) hoac None.
        """
        key = str(key)
        d = self.dur.get(key)
        if not d:
            return None
        fps = float(fps or 30.0)
        pos = self.pos.get(key, 0.0)
        avail = d - pos
        if avail < float(min_sec) - 1e-6:
            return None
        fr = max(1, int(round(avail * fps)))
        self.pos[key] = d
        self.used[key] = self.used.get(key, 0) + 1
        return (self.off.get(key, 0.0) + pos, fr)   # moc TUYET DOI trong file

    def take_any(self, need_sec, fps=30.0, rng=None, prefer=None):
        """Cat 1 doan tu BAT KY file nao con du dai.

        prefer: danh sach ten file uu tien (vi du file dang dung do).
        rng: random.Random — neu co thi boc theo trong so = so giay con lai
        (file dai duoc dung nhieu hon, tranh 1 file dai bi bo quen).
        Tra ve (ten_file, start, so_frame) hoac None neu het sach.
        """
        cands = self.keys_with(need_sec)
        if not cands:
            return None
        if prefer:
            pref = [k for k in prefer if k in cands]
            if pref:
                cands = pref
        key = None
        if rng is not None and len(cands) > 1:
            ws = [self.remaining_sec(k) for k in cands]
            tot = sum(ws) or 1.0
            r = rng.random() * tot
            acc = 0.0
            for k, w in zip(cands, ws):
                acc += w
                if r <= acc:
                    key = k
                    break
        if key is None:
            key = cands[0]
        got = self.take(key, need_sec, fps)
        if got is None:
            return None
        return (key, got[0], got[1])

    # ── luu / phuc hoi trang thai ───────────────────────────
    def snapshot(self):
        return {"dur": dict(self.dur), "off": dict(self.off),
                "pos": dict(self.pos), "used": dict(self.used)}

    @classmethod
    def restore(cls, snap):
        o = cls()
        snap = snap or {}
        o.dur = {str(k): float(v) for k, v in (snap.get("dur") or {}).items()}
        o.off = {str(k): float(v) for k, v in (snap.get("off") or {}).items()}
        o.pos = {str(k): float(v) for k, v in (snap.get("pos") or {}).items()}
        o.used = {str(k): int(v) for k, v in (snap.get("used") or {}).items()}
        for k in o.dur:
            o.off.setdefault(k, 0.0)
            o.pos.setdefault(k, 0.0)
            o.used.setdefault(k, 0)
        return o

    def clone(self):
        return CutPool.restore(self.snapshot())
