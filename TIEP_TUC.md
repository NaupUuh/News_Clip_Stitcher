# TIẾP TỤC TOOL NÀY — đọc file này trước

Cập nhật: 2026-10-09 · Phiên bản hiện tại: **v1.24.2**

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
- Tab "Tin nóng 24h": chấm điểm độ nóng tin + Google News
- Tự cập nhật qua GitHub (nút ⬆ Cập nhật trong tool)
- **Tab 2 · Mục 7 "Tìm ảnh theo tin"**: tự tải ảnh stock theo từ khoá tin,
  **KHÔNG cần API key** (`core/images.py`). Nút "⬅ Lấy từ tin đang chọn" lấy
  luôn `item['keyword']` mà AI đã sinh sẵn. Nguồn: Wikimedia Commons.
  Chỉ nhận ảnh CC0 / Public Domain / CC-BY (bỏ BY-SA, ND, NC); tự ghi
  `credits.txt` (file | license | tác giả | nguồn | trang gốc) cạnh ảnh.
  Tự thêm folder ảnh vào danh sách nguồn video tab 1.

## Việc CÒN LẠI / chờ anh quyết

1. **Chọn MC**: hiện anh tự chọn file MC mỗi lần chạy (cố ý, không lưu config).
   Muốn lưu thì nói.
2. **Tự rút từ khoá hay tự gõ** — ĐÃ CÓ nút "⬅ Lấy từ tin đang chọn" (lấy
   `item['keyword']` AI sinh sẵn, KHÔNG tốn thêm phí). Vẫn gõ tay được.
3. ~~Key Pexels~~ — **KHÔNG CẦN NỮA**: mục 7 dùng Wikimedia Commons, miễn phí,
   không cần đăng ký. Openverse có code sẵn nhưng mặc định TẮT (xem dưới).
4. **Chyron crop / auto-skip** — chưa chốt cách xử lý.
5. **Casing tiêu đề** (HOA toàn bộ hay Hoa Đầu Từ) — chưa chốt.
6. ~~Tab "Tìm ảnh theo tin"~~ — **ĐÃ XONG** (tab 2, mục 7).
7. Lỗi MC `WinError 2` — anh đã bỏ qua.

## Bài học mục 7 (đọc trước khi sửa `core/images.py`)

- **Video là khung DỌC 9:16 và ảnh bị cover-crop** → bề ngang thật chỉ còn
  `h*9/16`. Ảnh 1920x1080 chỉ còn 607px rồi bị phóng 1.8x = **mờ**. Vì vậy
  lọc theo `_eff_w()` (bề ngang sau crop), KHÔNG theo bề ngang ảnh gốc.
  Ngưỡng: `min_eff=700` (từ khoá) — ảnh phải phóng ≤ ~1.1x mới nét.
- **Openverse mặc định TẮT**: chủ yếu là ảnh Flickr cũ 500-1024px, sau crop
  dọc chỉ còn <600px → luôn mờ. Code vẫn giữ, bật bằng `SOURCES`.
- **Wikimedia chặn 429 khi gọi dồn** → `_open_req()` tự thử lại 3 lần, chờ
  theo `Retry-After`. Triệu chứng 429 giống hệt "không có kết quả" nên rất
  khó lần ra; đừng bỏ retry.
- **Wikimedia trả `thumburl` = file GỐC** khi ảnh nhỏ hơn bề ngang yêu cầu
  (`iiurlwidth`) → tự nhiên tải file 10-20MB. Đã xử lý trong `download()`:
  nếu bản tải về < `target_w` thì thử lại file gốc.
- **Lỗi tải phải HIỆN RA** (log `! bỏ qua ảnh: ...`). Trước đây im lặng nên
  chỉ thấy "0 ảnh" mà không biết vì sao (429 / ảnh >15MB / ảnh nhỏ).
- **CC-BY-SA bị loại** vì share-alike sẽ buộc cả video theo CC-BY-SA — rủi ro
  cho kênh kiếm tiền. ND cũng loại (video luôn crop/zoom = tạo tác phẩm phái
  sinh). Muốn dùng BY-SA thì phải ghi credit theo đúng điều khoản.
- **Test KHÔNG được để bẩn `config.json`**: `App._img_fetch()` gọi
  `save_config()`. Khi test phải `app.save_config = lambda: None`, và không
  đặt `im_out`/`im_kw` vào giá trị thật rồi để nó ghi lại.

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
