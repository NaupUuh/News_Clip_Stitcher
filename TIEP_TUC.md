# TIẾP TỤC TOOL NÀY — đọc file này trước

Cập nhật: 2026-10-22 · Phiên bản hiện tại: **v1.28.0**

## Cách tiếp tục (1 câu cho trợ lý)

> "Tiếp tục tool News_Clip_Stitcher — đọc `TIEP_TUC.md` trong
> `C:\Users\Admin\Desktop\News_Clip_Stitcher` rồi làm tiếp."

Trợ lý sẽ tự đọc file này + skill `grok-batch-video-tools` (đã có sẵn toàn bộ
kinh nghiệm về tool: khung MC, banner, cắt clip, cập nhật GitHub, sync ổ Z).

## Đường dẫn quan trọng

| Thứ | Ở đâu |
|---|---|
| Tool (bản đang sửa) | `C:\Users\Admin\Desktop\News_Clip_Stitcher` |
| Bản trên ổ Z | `Z:\HQData-2\TOOLS TỔNG HỢP\TOOLS UPDATE CUỐI\News_Clip_Stitcher` |
| Repo GitHub | `https://github.com/NaupUuh/News_Clip_Stitcher` |
| Python | `C:\ReverseEngineering\Scripts\venv\Scripts\python.exe` |
| ffmpeg | `C:\ReverseEngineering\thirdparty\ffmpeg-9.0.2-essentials_build\bin` |
| Folder test | `D:\trumppp0410\2` (ảnh + video) |
| Pool MC | `D:\TIN TUC AUTO\Test MC\` |
| Khung PNG | `D:\TIN TUC AUTO\Khung\` |

## Việc đã xong (đừng làm lại)

- Nối ảnh + video thành reel 9:16, 15s, 4–7 media, chuyển động (Ken Burns)
- Cắt lìa video gốc thành đoạn 2.5–4s dùng hết, tự bỏ đoạn đen đầu/cuối
- Banner BREAKING NEWS + tiêu đề 3 dòng + CTA vàng ở đầu video (hiện 3s cuối)
- Khung MC "NEWS" (PiP): chạy video ĐỘNG, che logo DreamFace, neo xuống góc
  trái-dưới, **lề trái SET CỨNG = mép thanh đỏ BREAKING** (lệch 1px)
- Audio ElevenLabs: ô "thời gian đọc" (mặc định 15s) + tự ép audio khớp đúng
  số giây đó; tốc độ đọc 15.6 ký tự/giây (đo thật 4 giọng)
- **Eleven v4** (14/10/2026): danh sách model có `eleven_v4` + `eleven_v4_turbo`,
  mặc định dùng `eleven_v4`. v4 CHẠY ĐƯỢC với key hiện có (không cần nâng gói).
  v4 chỉ dùng `stability` + `similarity`; KHÔNG có `style`/`speed`, không hỗ trợ
  SSML — nhưng API vẫn nhận `style`/`speed` cũ mà không báo lỗi (bỏ qua im lặng),
  nên `VOICE_SETTINGS` không phải sửa. Điều khiển cách đọc bằng AUDIO TAG đặt
  trong chính câu text: `[whispering]` `[shouting]` `[laughing]` `[sighs]`.
- **Bộ audio tag v4 (14/10/2026, v1.27.0)** — ĐO THẬT, không đoán:
  - Tag PHẢI có ngoặc vuông `[whispers]` mới ăn. Viết trần `whispers …` →
    v4 **ĐỌC TO** chữ đó ra tiếng. Tool tự bắt + cảnh báo + có nút bọc lại.
  - Tag **không bị đọc to** khi đúng dạng (ASR đọc lại sạch).
  - Tag **chỉ áp cho CÂU theo sau nó**, không áp cả file — đo nửa đầu/nửa cuối
    file: tag ở đầu → nửa đầu −25.4 dB / nửa sau −22.8 dB; tag ở giữa →
    nửa đầu −22.9 dB / nửa sau −27.6 dB. → dùng được để đổi giọng theo ngữ cảnh.
  - Biên độ đổi **nhẹ** (~3 dB): `[shouts]` +1.8 dB, `[whispers]` −2.7 dB.
    Đừng trông cậy tag làm to/nhỏ hẳn — muốn mạnh thì viết câu tự nhiên.
  - `[pause]`/`[long pause]` gần như vô dụng (+0.16s) → ngắt nghỉ thật thì
    dùng dấu câu (… , .) hoặc tách câu.
  - 15 tag đã thử đều tạo file OK; `[sighs]` `[laughs]` `[breathing]`
    `[clears throat]` **chèn tiếng động thật** (file dài hơn).
  - **CHỈ v4 / v4 Turbo hiểu tag.** Model cũ (`eleven_multilingual_v2`,
    `eleven_turbo_v2_5`, `eleven_flash_v2_5`) đọc to tag → `synthesize()` tự
    gỡ tag khi model không phải v4 (`go_tag`).
  - GUI: ô "Hiệu ứng" + nút "Chèn vào câu đang chọn" + nút "Tự chèn gợi ý"
    (chèn tag theo từ khoá trong câu; câu tin tức bình thường không gắn tag).
  Giá API: v4 $0.08/1.000 ký tự, v4 Turbo $0.04.
- Tab "Tin nóng 24h": chấm điểm độ nóng tin + Google News
- Tự cập nhật qua GitHub (nút ⬆ Cập nhật trong tool)

## MỚI — CẢNH ĐẦU (tuỳ chọn) ở Tab 1 (22/10/2026, v1.28.0)

- **Yêu cầu**: Tab 1 có thêm 1 mục chọn **folder** chứa ảnh hoặc video ngắn 3-4s.
  Mỗi video con sẽ **nhặt ngẫu nhiên 1 file** trong folder đó ghép làm **cảnh đầu**.
  Tích thì mới thêm; **không tích → chạy y hệt như cũ**, không thêm gì.
- **UI** (`main.py`, khối `1b. Cảnh đầu (tuỳ chọn)` ngay dưới mục 1):
  - `Checkbutton` "Thêm cảnh đầu cho mỗi video" (`intro_var`)
  - `Spinbox` độ dài 0.5–8s, mặc định **3.0** (`intro_sec_var`)
  - `Entry` + nút **Chọn** folder cảnh đầu (`intro_dir_var`), nút ✕ xoá nhanh
  - Dòng ghi chú tự cập nhật: đếm `N ảnh + M video` trong folder
- **Lưu ý**: 3 khoá này nằm trong `DEFAULTS` của `main.py` (`intro_on`, `intro_dir`,
  `intro_sec`) → tự lưu/đọc qua `config.json` như mọi thông số khác.
- **Engine** (`core/stitcher.py`):
  - `plan_folder()`: sau khi có `total_frames`, gọi `_intro_scene()`; cảnh đầu ăn
    vào **`body_frames = total_frames - intro_fr`** → **tổng thời lượng KHÔNG đổi**,
    audio ép đúng `total` giây vẫn khớp. `scenes.insert(0, intro_sc)`.
  - `_intro_scene(folder, rng, fps, total_frames)`: quét ảnh + video (dùng
    `list_media`), `random.choice` **1 file**, trả `(scene, frames)`.
    - Ảnh → scene `kind="image"` có Ken Burns + grade như cảnh thường.
    - Video → lấy **đoạn ĐẦU** (`start=0`, tự bỏ đoạn đen đầu nếu có), cắt đúng
      `intro_sec` giây; nếu file ngắn hơn thì lấy hết file.
    - Trần cứng: cảnh đầu ≤ **40%** tổng thời lượng.
    - Folder trống / không tồn tại / chưa chọn → trả `(None, 0)`, **chạy như cũ,
      không crash**.
  - Scene intro có cờ `"intro": True` để log và để `pool_report` bỏ qua (hàm
    `scan()` trong `pool_report` ép `intro_on=False` — cảnh đầu không lấy media
    từ pool nên không ảnh hưởng con số "số video tối đa").
  - `_intro_scene()` dùng **RNG riêng** (`random.Random()`) → bật/tắt cảnh đầu
    không làm thay đổi cách chọn cảnh của phần thân.
- **Đã kiểm chứng** (`$TEMP/test_intro.py`, `test_intro_full.py`):
  - Pool đủ (video nguồn 60s): TẮT = 450 frame/15.00s, BẬT = 450 frame/15.00s,
    cảnh đầu 3.00s, body 12.00s, render ra đúng **15.000s**.
  - 6 lần lập kế hoạch → cảnh đầu ra 3 tên file khác nhau (đúng random).
  - `intro_sec=2.0` → cảnh đầu 2.00s, tổng vẫn 15.00s.
  - Folder rỗng / không tồn tại → plan y như bản tắt, không crash.
  - Folder chỉ có video → scene đầu `kind=video`, 3.00s.
  - `intro_sec=6` nhưng file intro 3.5s → cắt còn 3.50s (không lỗi).
  - GUI smoke: bật/tắt, ghi chú, `_build_cfg()` trả đúng kiểu `bool`/`float`.
- **Bẫy đã gặp**: `_fit_to_media()` chỉ bù giây cho cảnh **khác** khi video nguồn
  ngắn hơn slot. Nếu video nguồn ngắn (test 6s) thì tổng bản TẮT đã hụt còn 353
  frame/11.77s — **hành vi có sẵn từ trước**, không phải lỗi cảnh đầu. Muốn test
  tổng đúng `total*fps` thì phải dùng video nguồn **dài** (≥ total).

## ĐÃ BỎ (không làm lại)

- ~~Tab "Tìm ảnh theo tin" (mục 7)~~ — **anh yêu cầu GỠ 2026-10-09**, đã bỏ toàn bộ:
  không còn `core/images.py`, không còn nút "Tìm + tải ảnh"/"Ảnh đúng tin", không
  còn RSS báo trực tiếp trong `core/news.py`, không còn chế độ `fit` trong
  `core/stitcher.py`. **Bản có mục 7 vẫn giữ ở nhánh GitHub
  `backup/muc7-anh-dung-tin`** — cần lại thì `git checkout` từ đó.

## LỖI ĐÃ SỬA — `'int' object has no attribute 'bit_count'` (14/10/2026, v1.27.1)

- **Triệu chứng**: máy cài Python 3.9 bấm "KIỂM TRA POOL" hoặc chạy tạo video →
  `❌ Lỗi kiểm tra: 'int' object has no attribute 'bit_count'` và
  `❌ Lỗi: 'int' object has no attribute 'bit_count'`, 0 video thành công.
- **Nguyên nhân đã xác minh**: `core/stitcher.py` dùng `int.bit_count()` — hàm này
  **chỉ có từ Python 3.10**. Máy kia cài **Python 3.9.9**.
- **Vì sao chọn nhầm Python**: `run.bat` chỉ dò **2 đường dẫn CỐ ĐỊNH của máy build**
  (`C:\ReverseEngineering\Scripts\venv\...`, `Python313\python.exe`). Máy khác không
  có 2 đường dẫn đó → rơi xuống `python` trong PATH → trúng Python 3.9.
- **Cách sửa** (2 lớp):
  1. `core/stitcher.py`: thay `(a & b).bit_count()` bằng hàm `_popcount()` — có
     `bit_count()` thì dùng, không có thì `bin(x).count("1")` (chạy mọi Python 3.6+).
     Tổng 4 chỗ thay.
  2. `run.bat`: dò Python theo thứ tự `py -3.14 … -3.10` (py launcher) → các đường
     dẫn phổ biến → PATH. Thêm cảnh báo ghi vào log nếu Python < 3.10.
- **Cách kiểm tra**: `py -0p` (liệt kê Python đã cài) và
  `python -c "import sys;print(sys.version.split()[0],hasattr(0,'bit_count'))"`.
  Đã test thật: chạy `pool_report` + `plan_sequence` 50 video + render 2 video
  trên Python 3.9.0 → PASS, không còn lỗi; trùng ảnh đúng ≤50%.
- **Điều cần tránh**: đừng viết API chỉ có ở Python mới (`bit_count`, `zip(strict=)`,
  `itertools.pairwise`, `tomllib`, `X | Y` không có `from __future__`); đừng để
  `.bat` chỉ trỏ đường dẫn cố định của một máy.

## BẢO MẬT — key ElevenLabs từng bị lộ lên GitHub (14/10/2026)

- File `config.json.bak_tts` **đã bị git theo dõi** và chứa **API key ElevenLabs
  thật**, nằm trên repo **PUBLIC** từ commit `2dd5b4e` (04/10/2026) → lộ 10 ngày.
- **Nguyên nhân**: `.gitignore` có dòng `config.json.bak_*` NHƯNG file đã bị track
  từ trước — **`.gitignore` KHÔNG có tác dụng với file đã được theo dõi**.
- **Đã xử lý**: `git rm --cached config.json.bak_tts` + xoá file khỏi đĩa + commit
  `e0e71e5` + push. Đã xác minh HEAD trên GitHub không còn file, các file đang
  track không còn secret nào. Đã quét lịch sử cả 4 repo (`News_Clip_Stitcher`,
  `Phong_ADung`, `Phong_DHue`, `Vizard_Auto_Clip`) — chỉ repo này dính.
- **CÒN LẠI**: blob cũ vẫn nằm trong lịch sử git của repo public (dù không còn
  trong HEAD). Vì repo **public**, GitHub có thể vẫn phục vụ blob theo SHA.
  **Anh nên thu hồi (revoke) key ElevenLabs đó trên dashboard và tạo key mới** —
  key này trùng với key đang dùng trong `.env` và `config.json`.

## Việc CÒN LẠI / chờ anh quyết

1. **Chọn MC**: hiện anh tự chọn file MC mỗi lần chạy (cố ý, không lưu config).
   Muốn lưu thì nói.
2. **Tự rút từ khoá hay tự gõ** — chưa chốt (tự rút thì tốn phí AI).
3. **Chyron crop / auto-skip** — chưa chốt cách xử lý.
4. **Casing tiêu đề** (HOA toàn bộ hay Hoa Đầu Từ) — chưa chốt.
5. Lỗi MC `WinError 2` — anh đã bỏ qua.

## Lệnh hay dùng

```bash
cd "C:/Users/Admin/Desktop/News_Clip_Stitcher"

# kiểm tra cú pháp trước khi phát hành
"C:/ReverseEngineering/Scripts/venv/Scripts/python.exe" -m py_compile main.py core/*.py

# phát hành bản mới (tự bump version + commit + push)
"C:/ReverseEngineering/Scripts/venv/Scripts/python.exe" release.py 1.24.2 "Mô tả thay đổi"

# đồng bộ lên ổ Z + đối chiếu MD5 (phải ra "N/N MD5 KHỚP")
"C:/ReverseEngineering/Scripts/venv/Scripts/python.exe" sync_z.py
```

## Luật không được quên

- **config.json / output / video KHÔNG bao giờ lên GitHub.** Sync Z bỏ mọi file
  tên bắt đầu bằng `config.json.` — đừng để file rác (mp3/bak/tmp) lọt lên Z.
- **Đo trên frame thật 1080×1920**, không đo trên ảnh chụp màn hình (đã thu nhỏ
  → số sai). Xem `references/news-pip-mc-frame.md` trong skill.
- Sửa xong phải: `py_compile` → `release.py` → `git push` → xác minh bằng API
  GitHub → `sync_z.py` → đối chiếu MD5.
- Mọi reply cho anh bằng tiếng Việt, nhãn/log trong tool cũng tiếng Việt.
- Không bao giờ in giá trị API key (ElevenLabs / Gemini / Vilao).
