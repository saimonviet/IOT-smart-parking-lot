# PC Server — AI + giao diện quản lý

FastAPI (API + WebSocket) · SQLite · OpenCV/YOLOv8 · giao diện React (Vite).

## Chạy nhanh (không cần phần cứng)

```powershell
cd pc_server
pip install -r requirements.txt
cd web; npm install; npm run build; cd ..          # cần Node.js 18+ (https://nodejs.org)
python tools/seed_demo.py                           # (tuỳ chọn) dữ liệu lịch sử giả để xem biểu đồ
$env:DETECTOR="background"; python run.py          # HTTP :8000 (máy này) + HTTPS/WSS :8443 (Pi, LAN)
python simulator/mock_pi.py --auto                  # cửa sổ khác: Pi giả (wss + HMAC như Pi thật), xe tự ra vào
```
Mở http://localhost:8000 → đăng nhập **admin / admin123** (đổi bằng biến `ADMIN_PASSWORD` trước lần chạy đầu).
Hoặc chạy `scripts\demo.ps1` ở thư mục gốc để mở cả hai cùng lúc.

Dev giao diện (hot reload): `cd web; npm run dev` → http://localhost:5173 (proxy sang :8000).

`mock_pi.py` không có `--auto` sẽ cho gõ lệnh: `in` (xe tới cổng vào), `park N`, `leave N`, `out`, `fill`, `clear`.

## Bộ nhận diện (biến môi trường `DETECTOR`)

| Giá trị | Cách hoạt động | Dùng khi |
|---|---|---|
| `classifier` | Mô hình phân loại từng ô (MobileNetV3, `models/occupancy.pt` + `.json`), cắt khung bao ROI và cho xác suất "có xe" | camera thật, **sau khi** đã kiểm tra/chỉnh ngưỡng bằng `tools/classifier_probe.py` |
| `yolo` (mặc định) | YOLOv8n COCO: ô có xe khi box xe phủ ≥ `YOLO_OVERLAP` ROI hoặc tâm box nằm trong ROI | xe thật, ảnh/video bãi xe |
| `background` | So sánh từng ROI với ảnh nền bãi trống (`BG_THRESHOLD`, `BG_RATIO`) | **xe mô hình / hộp đồ chơi** — không phụ thuộc loại vật |
| `none` | Tắt; dùng nút "Đặt tay" trên giao diện | debug |

**Với xe mô hình**: YOLO COCO thường nhận kém khi nhìn từ trên xuống. Cách làm:
1. Thử `YOLO_CLASSES=` (rỗng = mọi lớp) và hạ `YOLO_CONF=0.15`; nếu vẫn kém →
2. Dùng `DETECTOR=background`: bãi **trống** → trang *Thiết bị* → "Chụp ảnh nền". Giữ ánh sáng ổn định.
3. Về sau muốn chính xác hơn: chụp ~200 ảnh xe mô hình, gán nhãn, fine-tune YOLOv8n rồi đặt `YOLO_MODEL=best.pt`.

### Mô hình phân loại (`DETECTOR=classifier`)

- Model nằm ở `models/occupancy.pt` (TorchScript, đầu ra logits `[N, 2]` = `[empty, occupied]`) và `models/occupancy.json`
  (`img_size`, `mean`, `std`, `threshold`, `temperature`). Thay model = chép đè **cả hai** file; dùng file khác: `CLASSIFIER_MODEL=đường\dẫn\model.pt` (file `.json` cùng tên, cùng thư mục).
- Model hiện tại train trên CNRPark (camera bãi xe thật), chưa fine-tune trên camera của dự án. Trên ảnh Pi giả nó nhận **ngược**
  (ROC-AUC ≈ 0.02) → demo bằng Pi giả vẫn dùng `background`.
- Trước khi dùng với camera thật, đo trên ảnh chụp từ đúng camera đó (liệt kê ô **có xe** sau dấu `=`, `=` rỗng = bãi trống):
  ```powershell
  python tools/classifier_probe.py http://<ip-pi>:8081/snapshot.jpg                 # chỉ xem xác suất
  python tools/classifier_probe.py trong.jpg= xe1.jpg=A1,B2 xe2.jpg=A3,C1,C4         # đề xuất ngưỡng
  python tools/classifier_probe.py trong.jpg= xe1.jpg=A1,B2 xe2.jpg=A3,C1,C4 --save  # ghi ngưỡng vào occupancy.json
  ```
  Nếu tool báo "chồng lấn" hoặc "nhận NGƯỢC" thì chỉnh ngưỡng không cứu được — cần fine-tune model trên ảnh crop từ camera này.
  Chỉnh ngưỡng tạm thời không sửa file: `CLASSIFIER_THRESHOLD=0.5`.

### Chọn mô hình trên web

Trang **Thiết bị → Mô hình nhận diện** (tài khoản quản lý) liệt kê: mô hình phân loại (mọi cặp `tên.pt` + `tên.json`
trong `models/`), mô hình YOLO (các `.pt` còn lại trong `pc_server/` và `models/`) và so sánh ảnh nền. Chọn rồi bấm
**Áp dụng** — server tải thử mô hình mới (lỗi thì giữ bộ cũ), đổi ngay không cần khởi động lại, và nhớ lựa chọn ở
`data/detector.json` (xóa file này để quay về `DETECTOR` / `CLASSIFIER_MODEL` / `YOLO_MODEL` trong biến môi trường).
Với mô hình phân loại có thanh chỉnh ngưỡng và xác suất có xe của từng ô theo thời gian thực để chỉnh cho khớp camera.

Chống nhấp nháy: ô chỉ đổi trạng thái sau `CONFIRM_FRAMES` (3) khung liên tiếp cho cùng kết quả.

## Nguồn video (`VIDEO_SOURCE`)

- `auto` (mặc định): lấy `http://<ip-pi>:8081/stream.mjpg` ngay khi Pi kết nối.
- URL / đường dẫn video / ảnh bất kỳ — test YOLO không cần Pi: `$env:VIDEO_SOURCE="C:\data\bai_xe.mp4"`.
- **Camera điện thoại** (thay tạm Pi Camera):
  - Android, app **IP Webcam** → *Start server* → `$env:VIDEO_SOURCE="http://<ip-điện-thoại>:8080/video"`
    (ảnh tĩnh cho `roi_calibrate.py` / `collect_crops.py`: `http://<ip-điện-thoại>:8080/shot.jpg`).
  - Android/iPhone, app **DroidCam** hoặc **Iriun Webcam** (cài thêm phần mềm trên PC) → điện thoại thành webcam của máy tính:
    `$env:VIDEO_SOURCE="0"` (thử `"1"` nếu laptop có webcam sẵn).
  - Khi đặt `VIDEO_SOURCE` cụ thể, server không lấy camera từ Pi nữa; Pi vẫn lo cảm biến, rào, đèn, OLED như bình thường.

## Chỉnh sơ đồ bãi và vùng ROI trên web (khuyến nghị)

Đăng nhập tài khoản quản lý → menu **Sơ đồ bãi**:
1. **Mẫu có sẵn**: một dãy, hai dãy đối diện, nhiều làn dọc, đỗ xéo — chỉnh số ô rồi bấm *Dùng mẫu này*.
2. **Sơ đồ**: kéo thả ô và nút đường đi, nối/bỏ làn, chọn nút cổng vào/ra, đổi tên ô (không dấu, ≤ 6 ký tự cho OLED).
3. **Vùng camera**: bấm 4 góc từng ô trên ảnh camera thật (ô chưa vẽ có viền cam đứt nét).
4. **Lưu & áp dụng**: server kiểm tra (tên trùng, ô không có đường từ cổng vào…), ghi `config/layout.json`
   (bản trước giữ ở `config/layout.prev.json`) và nạp lại bộ nhận diện ngay, không cần khởi động lại.

Sơ đồ (`map`, `nodes`, `slots[].map`) và vùng camera (`frame`, `slots[].roi`) là hai hệ tọa độ riêng, nên kéo ô
trên sơ đồ không làm lệch vùng nhận diện. Số đèn LED trên Pi đặt bằng `LED_COUNT` (mặc định 10) để cảnh báo khi bãi nhiều ô hơn.
`simulator/mock_pi.py` đọc layout lúc khởi động — chạy lại sau khi đổi sơ đồ.

## Vẽ vùng ROI bằng công cụ dòng lệnh

```powershell
pip install opencv-python        # bản có cửa sổ GUI (gỡ bản headless trước)
python tools/roi_calibrate.py http://<ip-pi>:8081/snapshot.jpg
```
Bấm 4 góc cho mỗi ô theo thứ tự A1, A2, A3, B1 … C4. Kết quả ghi vào `config/layout.json` (cùng file định nghĩa đường đi để tìm ô gần nhất —
chỉnh `nodes`/`lane`/`slots[].node` nếu bố cục bãi khác).

## Nghiệp vụ

- **Ô gần nhất**: Dijkstra từ cổng vào trên đồ thị làn đường → ô trống có tổng đường đi ngắn nhất.
- **Giữ chỗ**: ô được chỉ định bị khoá `RESERVE_TIMEOUT` (90s) hoặc tới khi xe đỗ; đèn nhấp nháy. Hai xe liên tiếp không bị chỉ cùng 1 ô.
- **Cảnh báo**: xe đỗ sai ô được chỉ định, ô có xe mà không qua cổng, hết hạn giữ chỗ, Pi mất kết nối.
- **Phí**: `RATE_PER_HOUR` (5000đ/giờ) tính theo khối 15 phút, tối thiểu 1 khối.

## Bảo mật kênh Pi ↔ Server

| Lớp | Cách làm | Chống được |
|---|---|---|
| Mã hóa | `wss://` (TLS) cổng 8443, chứng chỉ tự ký `data/tls/`; Pi **ghim vân tay SHA-256** (`server.fingerprint`) | nghe lén, server giả mạo (MITM) |
| Xác thực hai chiều | Challenge–response HMAC-SHA256 với khóa bí mật `data/pi.key` — khóa **không bao giờ** gửi qua mạng | Pi giả, server giả |
| Toàn vẹn + chống phát lại | Mọi tin được bọc `{seq, ts, body, mac}`, ký bằng khóa phiên riêng cho từng kết nối | sửa gói tin, replay (cùng phiên và giữa các phiên), tin cũ |
| Chống dò khóa / phá kết nối | Sai 5 lần / 5 phút → chặn IP 5 phút; tối đa 4 kết nối đang bắt tay; Pi cũ chỉ bị thay khi kết nối mới **đã xác thực** | brute force, kẻ lạ đá Pi thật ra |
| Bắt buộc TLS | Kết nối `ws://` (không mã hóa) chỉ được chấp nhận từ chính máy server (`PI_REQUIRE_TLS=1`) | Pi cấu hình nhầm sang kênh không mã hóa |

Mọi lần xác thực sai / gói tin bị từ chối đều ghi vào nhật ký sự kiện (`security`) trên dashboard.
Giao thức chi tiết: `app/secure_channel.py` (bản giống hệt ở `raspberry_pi/secure_channel.py`).

- Lấy cấu hình cho Pi: `python tools/pi_secret.py`. Đổi khóa: xóa `data/pi.key`, chạy lại server rồi script này.
  Đổi chứng chỉ: xóa thư mục `data/tls/`.
- Demo tấn công cho báo cáo (server đang chạy): `python tools/attack_demo.py [--bruteforce]` — 7 kịch bản
  (khóa mặc định, sai khóa, sửa gói tin, phát lại, phát lại giữa phiên, server giả, dò khóa), in kết quả BỊ CHẶN / KHÔNG.

## Giao thức Pi ↔ Server (`/ws/pi`, JSON bên trong lớp bảo mật ở trên)

| Hướng | Thông điệp |
|---|---|
| Pi → Server | `{"type":"hello","device","barrier","stream_port"}` · `{"type":"arrive","gate":"in"\|"out","timeout"}` (timeout = số giây Pi chờ; server đọc biển số trong thời gian đó) · `{"type":"telemetry","data":{...}}` · `{"type":"log","level","message"}` |
| Server → Pi | `{"type":"state","slots":["free"\|"occupied"\|"reserved"×10, thứ tự A1…C4],"free","total"}` · `{"type":"entry_result","allowed","reason","slot","plate","display","oled":{"title","lines","arrow"}}` · `{"type":"exit_result","allowed","reason","plate","fee","oled"}` · `{"type":"command","cmd":"open_barrier"\|"close_barrier"\|"led_test"\|"gate_result","gate","result"}` (gate_result = quản lý nhập biển tay trên dashboard) |

## Biến môi trường chính

`DETECTOR`, `VIDEO_SOURCE`, `CLASSIFIER_MODEL`, `CLASSIFIER_THRESHOLD`, `YOLO_MODEL`, `YOLO_CLASSES`, `YOLO_CONF`, `YOLO_OVERLAP`, `BG_THRESHOLD`, `BG_RATIO`,
`DETECT_FPS`, `CONFIRM_FRAMES`, `RESERVE_TIMEOUT`, `RATE_PER_HOUR`, `ADMIN_USER`, `ADMIN_PASSWORD`,
`PI_KEY` (mặc định tự sinh vào `data/pi.key`), `PI_REQUIRE_TLS`, `HTTP_HOST`/`HTTP_PORT` (127.0.0.1:8000), `TLS_HOST`/`TLS_PORT` (0.0.0.0:8443), `TLS_CERT`, `TLS_KEY`.
