# News Clip Stitcher v1.25.0

Nối **ảnh + video** thành video tin tức dọc 9:16 có **hiệu ứng chuyển động**, kiểu news reel.

## Chạy tool

- **`Mo_An.vbs`** (khuyến nghị) — double-click là chạy, **cửa sổ cmd không bao giờ
  hiện ra**, kể cả nhấp nháy. Đóng cửa sổ tool → cmd/python tắt sạch theo.
- **`run.bat`** — cũng chạy ẩn (tự gọi lại chính nó qua VBS). Double-click được.
- **`run.bat debug`** — chạy **CÓ** cửa sổ cmd để đọc lỗi, và giữ cửa sổ lại nếu
  tool crash. Dùng khi tool không mở được.

---

## Cập nhật & cài trên máy khác (GitHub)

Tool tự cập nhật qua GitHub: **`github.com/NaupUuh/News_Clip_Stitcher`**

**Máy mới — chỉ làm 1 lần:**

1. Tải file **`Cai_dat_may_moi.bat`** (gửi qua chat/Drive — chỉ ~2 KB, không phải
   cả tool).
2. Double-click nó → tool tự tải bản mới nhất từ GitHub về, tạo folder
   `News_Clip_Stitcher` cạnh file `.bat`.
3. Từ đó mở tool bằng `Mo_An.vbs` như bình thường.

**Máy đã có tool — mỗi lần có bản mới:**

Mở tool → bấm nút **`⬆ Cập nhật`** (góc phải thanh dưới) → bấm **Có** →
tool tải bản mới, **giữ nguyên cài đặt + key + video cũ**, rồi **tự mở lại**.

- Bản cũ được sao lưu ở `_backup_update/<ngày giờ>/` — hỏng còn lùi được.
- `config.json` (key Vilao, đường dẫn, cài đặt) **không bao giờ** bị ghi đè.
- Chạy tay: `python updater.py` (chỉ kiểm tra) hoặc `python updater.py --apply`.

**Lỗi "Không cập nhật được: CERTIFICATE_VERIFY_FAILED":**

Máy đó thiếu kho chứng chỉ CA nên Python không gọi được HTTPS tới GitHub. Sửa:

1. Copy file **`Sua_loi_cap_nhat.bat`** (+ `Sua_loi_cap_nhat.ps1`) sang máy đó,
   để cạnh `main.py`.
2. Double-click `Sua_loi_cap_nhat.bat` → nó tự sửa rồi cập nhật lên bản mới nhất.
   Giữ nguyên `config.json`.
3. Nếu máy đó không có Internet: copy cả thư mục tool từ ổ `Z:` về, đè lên
   (nhớ giữ `config.json` cũ).

Từ v1.23.0, `updater.py` tự dùng kho chứng chỉ Windows khi máy thiếu CA, nên
các máy đã lên 1.23.0 sẽ không gặp lại lỗi này.

**Phát hành bản mới (chỉ trên máy anh):**

```bash
python release.py 1.20.0 "Mô tả ngắn thay đổi"
```

Script tự bump version trong `main.py` + `version.json`, commit và push. Máy khác
chỉ cần bấm "⬆ Cập nhật".

Repo: <https://github.com/NaupUuh/News_Clip_Stitcher> (public).

## Ô nhập key Vilao (tab 2)

- Ô **🔑 Key Vilao** ngay dưới hàng chọn AI/Model. Gõ key trực tiếp, bấm
  **Lưu key** → ghi vào `config.json`, lần sau mở tool không phải gõ lại.
- **Để trống = đọc từ `.env`** như trước (không đổi hành vi cũ).
- Key gõ tay có **ưu tiên cao nhất** — hơn cả env và `.env`. Dùng khi đổi key
  hoặc key mới chưa kịp cập nhật vào `.env`.
- Ô key **che ký tự**; tích **Hiện** nếu muốn nhìn thấy để kiểm tra.
- Key **không bao giờ** bị in ra log (chỉ báo "đã lưu"/"đã xoá").
- Nút **🔑 Kiểm tra key AI** và nút **⟳** (nạp model) đều dùng đúng key trong ô.
- Chế độ ẩn ghi toàn bộ log ra `%TEMP%\News_Clip_Stitcher_run.log`.

## Giao diện

- **2 tab**: `🎬 1. Nối ảnh + video` và `📰 2. Breaking News`
- **Mục "2. Thông số video" chỉ để lại thứ hay đổi** (thời lượng, số file/cảnh,
  3 ô tích). Các thông số đã tối ưu sẵn (FPS, kích thước, zoom ảnh/video, mạnh
  màu, số đoạn, cảnh ngắn/dài, CRF, preset) gom vào nút
  **▸ Mở rộng thông số nâng cao** — ẩn mặc định cho bố cục gọn, bấm mở khi cần
  chỉnh tay, bấm lại để thu gọn.
- **Thanh hành động + Log ghim ở ĐÁY** cửa sổ → thu nhỏ cửa sổ thế nào nút
  `BẮT ĐẦU` / `BURN BANNER` vẫn luôn bấm được.
- Phần thông số **cuộn dọc** được (chuột lăn trong vùng nội dung), các mục dài
  san thành **2 cột** cho gọn.
- Cửa sổ tối thiểu `900x560` (nhỏ hơn nữa thì widget bị bóp méo).
- Cỡ chữ mặc định **11pt** cho dễ đọc.

## Mục 0 — Tin nóng 24h (tab 2)

Lấy tin **đang hot trong 24h** rồi đổ thẳng vào ô tiêu đề banner.

1. Chọn **chủ đề** (Chính trị Mỹ / Thế giới / Kinh tế / Khoa học), **số tin**, **số giờ**
   - **AI viết lại tiêu đề**: chọn `vilao` (mặc định) / `gemini` / `auto` (thử Vilao
     trước, lỗi thì tự chuyển Gemini). Key đọc từ env rồi `.env`.
     Nút **🔑 Kiểm tra key AI** để test key đang chọn.
     - **Model**: ô **gõ tay** được tên model — Vilao thêm/bớt model liên tục nên
       tool KHÔNG hardcode danh sách. Bấm **⟳** để nạp danh sách model **sống**
       từ Vilao (`GET /v1/models`), rồi chọn hoặc gõ tay. Để trống = dùng mặc định.
       Mặc định: **`deepseek-v4.1-flash`**, dự phòng `gpt-5.6-luna` → `gpt-6-luna`.
     - Đo thật (8 tin chính trị × 5 vòng = 40 tin, đúng hàm `rewrite_titles`):
       `deepseek-v4.1-flash` **5.3s** · hook TB **0.700** (92% đạt ≥0.5) ·
       `gpt-5.6-luna` **95.6s** · hook 0.619 (88%) · `gpt-6-luna` **23.3s**.
       Cả 3 đều **0 bịa số · 0 lọt tên báo · 0 dòng quá 40 ký tự**.
   - **Chính trị Mỹ** lọc theo từ khoá (politics / congress / senate / white house / election)
     và tự loại tin **thể thao** lạc chủ đề (Google News không có mục Politics riêng —
     mục "Politics" cũ thực ra là feed tổng hợp nên hay dính WNBA/NFL).
2. Tích **Chấm điểm độ nóng** (mặc định BẬT) nếu muốn tool tự xếp tin đáng làm lên đầu
3. Bấm **🔄 Lấy tin nóng 24h**
4. Danh sách tin hiện trong bảng **cuộn được** (lăn chuột hoặc thanh cuộn; kéo ngang được)
5. Chọn 1 tin → **⬆ Dùng tin này cho banner** (hoặc nháy đúp vào dòng).
   Bấm 1 dòng để xem **giải thích vì sao tin đó đáng làm**
6. Bấm **📰 BURN BANNER** như bình thường

Cột trong bảng: **Độ nóng** (`🔥 88 nguồn · Trends`) · **Hook** · **Nguồn** (báo đăng) · **Giờ** (tuổi tin).

### Tiêu đề viết theo hướng HOOK

AI không còn chỉ chia lại tiêu đề — nó viết lại thành tiêu đề truyền hình
**giật, gây tò mò** theo 4 chiêu: mở đầu tạo sốc (`JUST IN` / `BREAKING` /
`NOW`), tạo vòng lặp tò mò (dồn phần "được gì" xuống dòng cuối), ngắt nhịp
bằng `?`/`:`, và đẩy con số/số liệu gây sốc lên trước.

Cột **Hook** chấm 0.00–1.00 (`⚡` = từ 0.75): có từ hook + có ngắt nhịp ( `:` `?` ) + có
con số cụ thể. **Đây là thước đo nội bộ của tiêu đề, KHÔNG phải dự đoán viral.**

**Chống bịa:** prompt cấm model thêm bất kỳ dữ kiện/số/tên nào không có trong
tiêu đề gốc, cấm dùng từ khẳng định nguồn tin (`LEAKED`/`REVEALED`/`EXPOSED`)
khi bản gốc không có. Sau khi viết lại, tool tự kiểm 4 lớp:
`faith` (mọi từ phải được tiêu đề gốc chống lưng) · `fab_numbers` (số trong
bài phải có trong tiêu đề gốc) · `strip_source_tail` (bỏ tên báo model tự gắn
vào cuối) · `_clamp_lines` (ép đúng 3 dòng × 40 ký tự, không tràn khung).

Nếu model trả về y nguyên tiêu đề (quên hook), tool **gọi ép lại 1 lượt**; vẫn
chưa đạt thì chèn `:` vào dòng 1 — thuần dấu câu, không thêm chữ nào nên không
thể bịa.

Đo thật 8 tin × 5 vòng: hook TB **0.58** (so với **0.28** khi chỉ chia dòng),
**85%** tin đạt hook ≥ 0.5, faith TB **0.95**, **0** tin bịa số, **0** dòng
quá 40 ký tự.

**Banner KHÔNG còn dính nguồn + giờ** (`BBC · 5.8H AGO`) — banner chỉ còn đúng
tiêu đề. Nguồn/giờ vẫn hiện trong bảng ở tab 2 để anh chọn tin.

Nút phụ:

- **🔑 Kiểm tra key Gemini** — xem key có hợp lệ không (không in key ra)
- **⬆ Làm video cho TẤT CẢ tin** — burn banner lần lượt cho từng tin trong danh sách
- **📋 Xuất JSON** — lưu danh sách tin ra file
- **📂 Mở link gốc** — mở bài báo gốc trên trình duyệt

### Chấm điểm độ nóng — đo được gì, KHÔNG đo được gì

Điểm **0–100** tính từ 3 tín hiệu miễn phí:

- **70% độ phủ báo chí** — đếm số **báo KHÁC NHAU** đưa cùng tin trong 24h
  (tra Google News RSS, chỉ tính bài thật sự trùng tin). 40+ nguồn là bão hoà.
- **20% Google Trends** — tin có mặt trong từ khoá trending US hôm nay không
- **10% độ mới** — tin càng mới càng cao

**NÓI THẲNG — đây KHÔNG phải dự đoán viral:**

- Chỉ đo **mức độ báo chí đưa tin**, không đo **người xem**. Muốn dự đoán viral
  phải có view/watch-time của video anh đã đăng — hiện chưa thu được.
- Facebook / X / TikTok **chặn hết** API số view/like/share miễn phí
  (Reddit 403, Bluesky 403, YouTube feed 500/404 — đã thử thật 2026-10-03).
- **Trần chính trị trên Facebook**: Meta hạ recommend video chính trị Mỹ với
  người chưa follow → trần viral thấp bất kể tin nóng cỡ nào.
- Điểm cao = **"đáng làm"**, KHÔNG PHẢI "sẽ viral".

Google Trends chi tiết (interest over time) bị 429/400 — cần `pytrends` + proxy
trả phí. Chỉ dùng được bản daily RSS (10 từ khoá/ngày, miễn phí).


### Nguồn tin lấy từ đâu

**Google News RSS** — miễn phí, **không cần key**, có **giờ đăng thật**
(độ mới `0.7h`, `1.9h`… tính từ lúc đăng). Đây mới là chỗ có tin thật.

**Gemini** chỉ làm 2 việc: **chia tiêu đề thành 3 dòng ngắn** (≤ ~25 ký tự/dòng
cho vừa thanh trắng) và **gợi ý từ khoá ảnh**. Gemini **KHÔNG được phép thêm tin
nào ngoài danh sách RSS** — nếu không siết, nó tự bịa tin từ trí nhớ.

### Key Gemini

Đọc theo thứ tự, **không bao giờ in giá trị key ra log**:

1. biến môi trường `GEMINI_API_KEY` / `GOOGLE_API_KEY` / `GOOGLE_GENAI_API_KEY`
2. file `.env` (`C:\Users\Admin\AppData\Local\hermes\.env`)
3. `config.json` của tool `Video_Highlight_Finder` (khoá `gemini_keys`)
4. `config.json` của chính tool này

**Không có key vẫn dùng được**: tool tự chia dòng bằng code nội bộ, giữ nguyên
tiêu đề gốc từ RSS.

### Giới hạn đã đo thật

- **Grounding (Gemini tự đi tìm tin trên Google)** → **429 với key này**, không
  dùng được. Đó là lý do phải lấy tin từ RSS.
- **Gemini gọi dồn dập sẽ nghen** (429) ở request thứ 2. Tool tự **nghỉ 10 giây**
  giữa các request và **đổi model** khi bị 429/503.
- Model khả dụng đo được: `gemini-3.5-flash-lite`, `gemini-3.5-flash`,
  `gemini-flash-latest`, `gemini-2.0-flash-lite`… (Gemini 2.5 đã bị khai tử với key này).

### Mục 7 — Ảnh ĐÚNG TIN + ảnh stock (KHÔNG cần API key)

Lấy ảnh cho phần ẢNH trong reel. Không cần đăng ký, không cần key.

**Ô "Kiểu lấy ảnh" có 3 chế độ:**

- **`news` (mặc định) — Ảnh ĐÚNG BÀI BÁO.** Lấy ảnh của **chính bài báo** đang
  hiện trong bảng "Tin nóng 24h": ảnh có sẵn trong RSS của báo, thiếu thì lấy
  `og:image` của bài. Ảnh đúng nhân vật/đúng sự kiện, không phải ảnh stock
  chung chung. Nút **📰 Ảnh đúng tin (cả loạt)** tải cho toàn bộ tin đang có.
- **`keyword` — ảnh stock** theo từ khoá (Wikimedia Commons).
- **`both` — cả hai**, gộp chung vào folder ảnh.

**Nguồn tin cho ảnh `news`:** tool lấy **RSS trực tiếp của ~51 báo** (đo thật:
39-41 feed sống, ~99 tin/24h, **~88-100% tin có ảnh sẵn**). Ảnh báo thường là
bản lớn (NPR 6000x4000, Politico 4000x2666, Guardian 1200x630).

**Ô "Hiển thị ảnh":**

- **`auto` (mặc định)** — tự chọn cho từng ảnh: ảnh đủ to thì **tràn viền**,
  ảnh ngang nhỏ thì **nền mờ** (ảnh hiện ở 1080x567 = thu nhỏ 0.9x nên vẫn nét).
  Đây là chế độ luôn nét nhất.
- `cover` — luôn tràn viền (ảnh 1200x630 sẽ chỉ còn 354px rồi phóng 3x = mờ).
- `blur` — luôn nền mờ.

- Bấm **⬅ Lấy từ tin đang chọn** để lấy từ khoá từ tin đang chọn trong bảng
  "Tin nóng 24h" — dùng luôn `keyword` mà AI đã sinh sẵn, **không tốn thêm phí**.
  Hoặc gõ tay, nhiều từ khoá cách nhau bằng dấu phẩy.
- Nguồn stock: **Wikimedia Commons** (ảnh chính phủ Mỹ = Public Domain, hợp
  tin chính trị nhất).
- Chỉ nhận ảnh dùng thương mại được: **CC0 / Public Domain / CC-BY**. Tự bỏ
  CC BY-SA (share-alike sẽ buộc cả video theo CC-BY-SA), ND và NC.
- **Chỉ nhận ảnh đủ nét sau khi cắt dọc 9:16.** Video là khung 9:16 và ảnh bị
  cover-crop (cắt 2 bên), nên ảnh 1920x1080 chỉ còn 607px bề ngang rồi bị
  phóng to 1.8x = mờ. Tool lọc theo bề ngang **sau khi cắt**, không theo bề
  ngang ảnh gốc.
- Openverse có sẵn trong tool nhưng **mặc định TẮT**: chủ yếu là ảnh Flickr cũ
  500-1024px, sau crop dọc chỉ còn dưới 600px → luôn mờ. Chọn trong ô "Nguồn"
  nếu vẫn muốn dùng.
- Mỗi ảnh tải về đều ghi `credits.txt` cạnh ảnh:
  `tên_file | license | tác giả | nguồn | trang gốc` (ảnh báo ghi domain báo +
  link bài). CC-BY cần ghi tên tác giả — dán dòng tương ứng vào phần mô tả
  video nếu cần.
- Tự thêm folder ảnh vào danh sách nguồn video ở tab 1 (bỏ tick nếu không muốn).

## Cách dùng

1. Chạy `run.bat`
2. **Thêm folder** — mỗi folder = 1 video đầu ra
   - `Thêm folder cha (batch)`: trỏ vào folder cha, mỗi folder con = 1 video
3. Bấm **🎬 BẮT ĐẦU**
4. Video lưu vào thư mục ở mục 4 (mặc định `output/`)

## Tab 2 — Breaking News (chèn banner)

Sau khi có video ở tab 1, chuyển sang tab **📰 2. Breaking News**:

1. **Thêm folder** chứa video đã render (quét cả folder con nếu cần)
2. **Sửa chữ trực tiếp** trên banner:
   - `Ô đỏ` — chữ trong ô đỏ (mặc định `BREAKING NEWS`)
   - `Chữ trắng (tiêu đề)` — **tiêu đề tin, anh gõ gì cũng được**
   - `Logo` + checkbox hiện/ẩn
3. **Chữ CTA — “FULL STORY IN THE FIRST COMMENT”** (mục 2b): mặc định
   `FULL STORY IN` / `THE FIRST COMMENT`, chữ vàng `#ECFA1E` viền đen, căn giữa,
   **nằm ở ĐẦU video** (đo từ ảnh mẫu: đỉnh 4.94%H, cao 1 dòng 4.31%H, rộng 62.8%W).
   **Chỉ hiện N giây cuối** (mặc định 3s) — tắt được.
4. **Vị trí & kích thước** — tỉ lệ khung, nút `↺ Về mặc định` trả về đúng video mẫu
5. **Khung MC "NEWS"** (mục 5) — xem bên dưới
6. **Màu** (hex) cho từng thành phần
7. `👁 Xem trước` xem 1 frame, `📰 BURN BANNER` chạy hàng loạt (đa luồng)

### Mục 5 — Khung MC "NEWS" (PiP trên banner)

Khung nhỏ chứa **người dẫn (MC)** nằm **ngay TRÊN** khung BREAKING NEWS, có
nhãn đỏ `NEWS` ở góc trên-trái — giống layout CNN.

- **Ô tích `Có MC → bật khung trên banner`**: tích = có khung MC, bỏ tích = không khung.
  Chọn xong file MC thì ô này **tự tích**, khỏi phải tích tay.
- **Ảnh/video MC**: chọn **từng lần chạy** bằng nút `📄` (cố ý KHÔNG lưu vào
  config — mở tool lên ô luôn trống để anh chọn file mới).
- **Hoặc folder MC**: trỏ vào folder nhiều MC → **mỗi video bốc ngẫu nhiên 1 file**.
- **Cắt lề nguồn (4 cạnh)**: cắt bớt viền ảnh/video nguồn trước khi đưa vào khung.
  Mặc định **cắt 16% đáy** để che watermark `DreamFace / Animated with AI`
  của app tạo video MC (đo trên video 538×720: chữ nằm ở y 86.5%–96.4%).
- **Ảnh MC luôn được COVER + crop** → bó cứng trong khung, **không méo, không tràn**.
- **Tự neo ngay trên banner**: khung MC luôn bám sát mép trên thanh đỏ, banner
  đổi vị trí cỡ nào khung vẫn nằm trên, không bao giờ đè lên.
- Nếu bật khung mà **quên chọn MC**, tool hỏi ngay trước khi burn hàng loạt.

Thông số (tỉ lệ khung hình, tự scale mọi độ phân giải):
- Khung MC: `x 0.012` · `w 0.325` · `h 0.198` · viền `0.028` màu `#0A1E69`
- Nhãn `NEWS`: nền `#CC0000`, chữ trắng, **dính sát góc trên-trái** khung MC,
  toạ độ **tỉ lệ trong khung MC**: `x 0.014` · `y 0.012` · `w 0.370` · `h 0.100`
  (đo từ ảnh mẫu: lề trái ~2%, đỉnh ~1.4%, cao ~10% chiều cao khung)
- Khe hở khung MC ↔ banner: `0.008`

**Vị trí đo từ video mẫu** (khung 360x640, tự scale theo độ phân giải):
- Ô đỏ `x24 y471 w124 h28` → tỉ lệ `x0.0667 y0.7359 w0.3444 h0.0437`
- Ô trắng `x28 y499 w308 h37` → tỉ lệ `x0.0778 y0.7797 w0.8556 h0.0578`
- CTA 2 dòng `y4.94%..15.34%H` → tỉ lệ `cta_y0.0494 h0.0862` (khối 2 dòng), khe `0.44`, bóp ngang `0.873`
- Chừa **105px (16.4% H)** dưới đáy = vùng an toàn cho caption/subtitle của nền tảng

Video đã có banner sẽ xuất ra tên `..._BN.mp4`, giữ nguyên video gốc.

## Cách hoạt động

| Đầu vào | Xử lý |
|---|---|
| **Ảnh tĩnh** | Ken Burns — zoom/pan ngẫu nhiên (zoom in / out / pan ngang / chéo) + **hiệu ứng màu** |
| **Video** | Giữ chuyển động gốc, **cắt lìa thành đoạn 2.5–4s** (mỗi đoạn dùng 1 lần, phủ hết file), zoom thêm tuỳ chọn, **hiệu ứng màu nhẹ** |
| **Folder trộn ảnh + video** | **Tự xen kẽ**: video → ảnh → video → ảnh… (đổi cảnh liên tục) |
| **Giữa các cảnh** | Cắt CỨNG (hard cut) — giống news reel |

- Tổng thời lượng **chính xác** (mặc định 15.000s = 450 frames @30fps)
- Số cảnh, độ dài mỗi cảnh, thứ tự, hướng chuyển động và **kiểu màu** đều **random mỗi lần render** → tránh bị coi là mass-produced
- Ảnh mọi tỉ lệ (16:9, 9:16, 1:1, dọc dài…) đều được cover-crop, **không bao giờ có viền đen**
- **Tự canh mặt khi crop (ảnh + video)** — ảnh/video ngang (16:9, 4:3) crop sang 9:16 chỉ giữ ~35-45% chiều ngang, nên tool tự tìm mặt chủ thể rồi đặt tâm crop vào đó → **không bị cắt mất mặt, không lấy lệch khỏi nhân vật chính**. Tắt được bằng checkbox.
  - **Ảnh:** chọn mặt theo điểm tổng hợp (diện tích × độ tin cậy × độ gần tâm) → mặt nhỏ ở góc ảnh không kéo khung crop ra khỏi chủ thể.
  - **Video:** lấy mẫu 3 frame (30%/50%/70% đoạn cắt) rồi lấy **trung vị** tâm mặt → không trượt khi nhân vật quay đi/che tay. Video nguồn **đã đúng tỉ lệ khung** (9:16) thì bỏ qua bước này vì crop không cắt gì.
  - Box có độ tin cậy < 0.60 bị loại (đo thật: YuNet hay nhận bàn tay/cử chỉ thành mặt ở mức ~0.5x).
- Ảnh gốc nét (≥1.4x khung) được render nội bộ 2x rồi hạ xuống → nét hơn ~23%

## Thông số

| Thông số | Mặc định | Ý nghĩa |
|---|---|---|
| Thời lượng | 15s | Tổng độ dài video, luôn chính xác |
| FPS | 30 | |
| Kích thước | 1080x1920 | 9:16 dọc |
| Số file/cảnh | 5–7 | 5–7 file → ~2.1–3s mỗi cảnh cho 15s |
| Độ dài cảnh | 1.4–4.0s | Tự nới nếu folder ít/quá nhiều file |
| Zoom ảnh | 1.06–1.18 | Mức zoom Ken Burns |
| Zoom video | 0.05 | Zoom thêm cho video (0 = giữ nguyên) |
| Canh mặt | BẬT | Tự đặt tâm crop vào mặt chủ thể |
| Hiệu ứng màu | BẬT | Áp tông màu ngẫu nhiên cho từng cảnh (8 kiểu + vignette) |
| Mạnh màu | 1.0 | 0 = nhẹ nhất, 1.5 = đậm |
| Xen kẽ ảnh/video | BẬT | Folder trộn → video/ảnh đổi cảnh liên tục |
| Số video mỗi folder | 5 | Tạo nhiều video từ cùng 1 folder media |
| Số luồng song song | 3 | Render nhiều video cùng lúc (nhanh hơn) |
| Độ dài mỗi đoạn video | 2.5–4.0s | Clip gốc bị cắt lìa thành các đoạn dài trong khoảng này |
| Trùng tối đa | 0.5 | **Chỉ áp cho ẢNH** — video nguồn dùng lại được |
| CRF | 18 | Nhỏ = nét hơn, file to hơn |
| Preset | veryfast | veryfast ~1.3s/video 15s |

## Tạo nhiều video từ 1 folder

Muốn đăng hàng loạt mà không bị coi là nội dung trùng lặp, mỗi folder có thể ra
nhiều video khác nhau:

- **Số video mỗi folder** — số video cần tạo từ folder đó.
- **Trùng tối đa** — **chỉ áp cho ẢNH**: 2 video bất kỳ không được dùng chung quá
  mức này (0.5 = 1 nửa) số ảnh. **Video nguồn không bị giới hạn** — dùng lại thoải
  mái, vì mỗi lần lấy một **đoạn thời gian khác** bên trong file (xem bên dưới).
- **Số luồng chạy song song** — render nhiều video cùng lúc. Phần chọn media luôn
  chạy tuần tự trước để giữ ràng buộc không trùng, chỉ phần encode chạy song song.
- **🔍 Kiểm tra pool** — bấm trước khi chạy: tool đếm media mỗi folder và báo **số
  video tối đa tạo được**. Nếu ít hơn số anh muốn, tool tự **cảnh báo** và chỉ tạo
  đến mức tối đa (không tạo video vi phạm ràng buộc).

### Một video con = NHIỀU đoạn video + vài ảnh

Clip gốc bị **cắt lìa liên tiếp** thành nhiều đoạn dài 2.5–4s, phủ hết chiều dài
file (clip 1 phút → ~18 đoạn). **Mỗi đoạn chỉ dùng 1 lần** — không có đoạn nào
lặp lại. Đoạn ĐEN đầu/cuối clip (đài chưa vào hình) **tự động bị bỏ** nên video
con không bao giờ mở màn bằng khung đen. Một video con lấy **nhiều đoạn video +
vài ảnh** (mặc định 60–85% số cảnh là video), nên video ra có chuyển động liên
tục thay vì 1 đoạn video rồi toàn ảnh.

**Hết đoạn video thì các video con sau chuyển hẳn sang TOÀN ẢNH** — không quay
vòng lại đoạn cũ. Ví dụ: 10 ảnh + 1 clip 97s → 39 đoạn → 11 video con dùng hết
đoạn video, các video sau đó toàn ảnh.

### Cắt video nguồn: đoạn 2.5–4s, cắt lìa liên tiếp

Con trỏ cắt chạy **tuần tự từ đầu file tới hết**: đoạn 1 = `0–3.2s`, đoạn 2 =
`3.2–6.5s`, đoạn 3 = `6.5–10.1s`… Độ dài mỗi đoạn ngẫu nhiên trong khoảng đã đặt
(2.5–4s). Đoạn cuối cùng sát đuôi file có thể ngắn hơn — vẫn dùng, không bỏ phí.

**Đoạn nào ra đoạn nấy, đúng độ dài**: cảnh video được cắt **đúng bằng** độ dài
đoạn đã chia, không kéo dài/thu ngắn cho vừa slot. Nhờ vậy video ra dài **chính
xác 15.000s** và dùng hết đoạn video có trong file nguồn.

**Đọc được cả ảnh `.jpe` / `.jfif`** (biến thể JPEG của một số máy ảnh và trang
tin), kể cả khi đuôi viết HOA.

Con số báo là **cận dưới an toàn**: tool mô phỏng thật quá trình chọn media (không
encode nên rất nhanh) với 3 seed cố định rồi lấy mức cao nhất → lặp lại lần nào
cũng ra cùng một số, và luôn tạo được đúng bằng đó. Pool rất dư thì báo dạng
`≥ 200` (chạm trần đếm) thay vì nói một con số cứng.

Con số **tăng rất mạnh so với trước** vì tool đã sửa cách tính trần trùng: trước
đây trần bị chấm theo *tập đang chọn dở* (nhỏ hơn cỡ cảnh) nên quá chặt — 19 ảnh
chỉ ra 4–5 video. Nay bốc **cả tập một lượt** rồi mới kiểm trần.

Ví dụ (trùng tối đa 50%, chỉ tính ảnh): 19 ảnh → **~42 video** (trước 4–5) ·
pool 10 → 3 · pool 20 → 63. Nếu để trùng tối đa 0% (không dùng chung ảnh nào):
pool 10 → 2 · pool 20 → 4 · pool 50 → 10.

Folder **toàn video** thì không bị trần này chặn — nhưng vẫn giới hạn bởi số cửa
sổ cắt được: 2 video 20s → 8 video con có phân cảnh video, các video sau đó toàn ảnh.

**Hiệu ứng màu** — 8 kiểu, chọn ngẫu nhiên theo trọng số, 25% cảnh thêm vignette tối 4 góc:
`am` (ấm), `lanh` (lạnh), `am-nhe`, `tuong-phan`, `phim` (film), `mo`, `sang`, `trong`.

**Random mỗi lần render:** thứ tự file, số lượng file, độ dài từng cảnh, hướng chuyển động, kiểu màu.
Muốn ra kết quả giống hệt lần trước thì phải tự ghi lại `seed` trong log.

## Tốc độ

~8–10s cho 1 video 15s / 6–7 cảnh (1080x1920, preset veryfast, máy này).

## ffmpeg

Tool tự dò ffmpeg theo thứ tự: `ffmpeg\bin` cạnh tool → `C:\ReverseEngineering\thirdparty\ffmpeg-9.0.2-essentials_build\bin` → `C:\ffmpeg-*\bin` → `PATH`.

Mục **5. ffmpeg** ở tab 1 hiện thư mục đang dùng + phiên bản. Bấm **Chọn** để trỏ tới thư mục chứa `ffmpeg.exe` — hộp chọn **mở sẵn ngay tại thư mục ffmpeg tool đang dùng** (máy đã có sẵn thì vào là thấy). **Mở** để mở Explorer tại thư mục đó. **Tự dò** để quay về mặc định. Gõ/dán đường dẫn trực tiếp cũng được (nhận cả đường dẫn tới `ffmpeg.exe`, có nháy kép cũng được).

Thư mục chọn được lưu vào `config.json` (`ffmpeg_dir`) và nạp lại khi mở tool. Sai đường dẫn thì tool tự bỏ qua và quay về danh sách dò — không lỗi render.

## Cấu trúc

```
News_Clip_Stitcher\
├── main.py                 # GUI
├── run.bat                 # Khởi động
├── config.json             # Tự lưu thông số + danh sách folder
├── models\
│   └── face_detection_yunet_2023mar.onnx   # Model tìm mặt (230KB, tự tải lần đầu)
├── core\
│   ├── ffmpeg_util.py      # Tìm ffmpeg, probe media
│   ├── facedetect.py       # Tìm mặt chủ thể để canh crop
│   ├── banner.py           # Dựng overlay BREAKING NEWS + CTA
│   └── stitcher.py         # Engine render
└── output\                 # Video xuất ra
```

## Tiếp tục tool này sau

**Đọc `TIEP_TUC.md`** trong thư mục tool — có trạng thái hiện tại, việc còn lại,
đường dẫn, lệnh phát hành và các luật không được quên.

## Yêu cầu

- Python 3.13 + Pillow
- ffmpeg (tự tìm ở `C:\ReverseEngineering\thirdparty\ffmpeg-9.0.2-essentials_build\bin`)
