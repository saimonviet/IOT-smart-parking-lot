# Bãi đỗ xe thông minh (IoT + AI)

Hệ thống nhận diện ô trống bằng camera + AI, tự chỉ ô gần nhất cho xe vào, điều khiển rào/đèn/màn hình TFT trên Raspberry Pi 3
và có giao diện web cho người quản lý.

```
 Pi Camera ──MJPEG──┐
 2× siêu âm ────────┤                      WebSocket                 ┌──────────────────────────┐
 2× servo rào ◄─────┤   Raspberry Pi 3  ◄───────────────────────►   │  PC: FastAPI + YOLO      │
 10× LED ◄──────────┤   (raspberry_pi/)                             │  (pc_server/)            │
 TFT 2.8" ◄─────────┘                                               │  + React dashboard       │
                                                                    └──────────────────────────┘
```

| Thư mục | Nội dung |
|---|---|
| [pc_server/](pc_server/README.md) | Server + nhận diện (YOLO / ảnh nền) + tìm ô gần nhất + giao diện React + Pi giả (`simulator/mock_pi.py`) |
| [raspberry_pi/](raspberry_pi/README.md) | Chương trình chính, sơ đồ đấu nối, **`test_hardware.py`** kiểm tra từng linh kiện |
| [esp32_cam/](esp32_cam/esp32_cam.ino) | Firmware ESP32-CAM chụp biển số cho cả cổng vào và cổng ra |
| `D:\model_training` | Huấn luyện mô hình ô trống + **nhận diện biển số** (`train_plate.ipynb`, xem README trong đó) |
| `scripts/demo.ps1` | Chạy thử cả hệ thống trên PC không cần phần cứng |

## Hướng dẫn cắm chân (Raspberry Pi 3)

Bãi có **10 ô** (A1–A3, B1–B3, C1–C4). Rào chắn dùng **2 servo SG90**. Số chân khớp với `raspberry_pi/config.yaml`
(đổi chân thì sửa file đó, không cần sửa code).

### Bảng chân

| Linh kiện | Tín hiệu | GPIO (BCM) | Chân vật lý |
|---|---|---|---|
| **LED ô A1 / A2 / A3** | → điện trở → LED(+) | 14 / 15 / 18 | 8 / 10 / 12 |
| **LED ô B1 / B2 / B3** | → điện trở → LED(+) | 20 / 21 / 4 | 38 / 40 / 7 |
| **LED ô C1 / C2 / C3 / C4** | → điện trở → LED(+) | 17 / 27 / 22 / 3 | 11 / 13 / 15 / 5 |
| **Servo rào VÀO** | dây tín hiệu (cam) | 12 | 32 |
| **Servo rào RA** | dây tín hiệu (cam) | 24 | 18 |
| **Siêu âm VÀO** (HC-SR04) | TRIG / ECHO* | 5 / 25 | 29 / 22 |
| **Siêu âm RA** (HC-SR04) | TRIG / ECHO* | 7 / 1 | 26 / 28 |
| **TFT 2.8" ILI9341** (SPI0) | SCK | 11 (SCLK) | 23 |
| | SDI (MOSI) | 10 (MOSI) | 19 |
| | CS | 8 (CE0) | 24 |
| | DC | 2 | 3 |
| | RESET | 16 | 36 |
| | VCC / LED (đèn nền) / GND | 3.3V / 3.3V / GND | 1 / 17 / 20 |
| **Pi Camera** | cáp dẹt | — | khe CSI |

\* ECHO **bắt buộc** qua cầu chia áp (xem dưới).
Các chân SDO (MISO), T_CLK, T_CS, T_DIN, T_DO, T_IRQ (cảm ứng) và chân thẻ SD trên module TFT **để trống**.

### Sơ đồ header 40 chân

```
                 TRÁI (lẻ)                          PHẢI (chẵn)
 TFT VCC     ← 3.3V      [ 1] [ 2]  5V        → VCC siêu âm VÀO
 TFT DC      ← GPIO2     [ 3] [ 4]  5V        → VCC siêu âm RA
 LED C4      ← GPIO3     [ 5] [ 6]  GND       → GND siêu âm VÀO
 LED B3      ← GPIO4     [ 7] [ 8]  GPIO14    → LED A1
               GND       [ 9] [10]  GPIO15    → LED A2
 LED C1      ← GPIO17    [11] [12]  GPIO18    → LED A3
 LED C2      ← GPIO27    [13] [14]  GND       → GND siêu âm RA
 LED C3      ← GPIO22    [15] [16]  GPIO23    (không cắm được, bỏ trống)
 TFT LED     ← 3.3V      [17] [18]  GPIO24    → SERVO RA
 TFT SDI     ← GPIO10    [19] [20]  GND       → TFT GND
  (MISO)       GPIO9     [21] [22]  GPIO25    → ECHO VÀO*
 TFT SCK     ← GPIO11    [23] [24]  GPIO8     → TFT CS
               GND       [25] [26]  GPIO7     → TRIG RA
               GPIO0     [27] [28]  GPIO1     → ECHO RA*
 TRIG VÀO    ← GPIO5     [29] [30]  GND       → GND nguồn servo (nối chung)
  (hỏng)       GPIO6     [31] [32]  GPIO12    → SERVO VÀO
  (hỏng)       GPIO13    [33] [34]  GND
  (hỏng)       GPIO19    [35] [36]  GPIO16    → TFT RESET
  (hỏng)       GPIO26    [37] [38]  GPIO20    → LED B1
 GND chung LED ← GND     [39] [40]  GPIO21    → LED B2
```
Chân 16, 31, 33, 35, 37 trên Pi này không cắm được nên bỏ trống. GPIO 9 (chân 21) là MISO của SPI, để trống. Tránh dùng GPIO 0 (chân 27, dành cho EEPROM của HAT).
GPIO 2/3 có sẵn điện trở kéo lên trên bo mạch: lúc Pi đang khởi động (chưa chạy chương trình) LED C4 có thể sáng mờ, đó là bình thường.

### Cách nối từng loại

```
LED (×10):   GPIO ──[330–470Ω]──(+)LED(−)── GND    (chân dài (+) về phía điện trở)

HC-SR04:     VCC → 5V      GND → GND      TRIG → GPIO trực tiếp
             ECHO ──[1kΩ]──┬── GPIO          ← BẮT BUỘC chia áp, ECHO ra 5V
                           └──[2kΩ]── GND

Servo SG90:  cam/vàng → GPIO 12 (vào, chân 32) / GPIO 24 (ra, chân 18)
             đỏ → +5V nguồn RIÊNG (≥1A)
             nâu/đen → GND nguồn riêng, NỐI CHUNG với GND của Pi (chân 30)

TFT 2.8":    VCC → 3.3V (chân 1)      GND → chân 20       CS → GPIO8 (chân 24)
(ILI9341)    RESET → GPIO16 (chân 36) DC → GPIO2 (chân 3)
             SDI(MOSI) → GPIO10 (chân 19)   SCK → GPIO11 (chân 23)
             LED → 3.3V (chân 17)     SDO(MISO), T_*, SD_* → để trống
```

### Cấu hình Pi bắt buộc cho bộ chân này (làm một lần)

TFT dùng SPI0 phần cứng nhưng **chỉ 1 chân CS** (`spi0-1cs`), để GPIO 7 (thường là CE1) vẫn dùng cho
TRIG RA. **Không** bật SPI bằng raspi-config (cách đó chiếm luôn GPIO 7). GPIO 14/15 (thường là UART) dùng cho LED A1, A2:

```bash
sudo raspi-config nonint do_spi 1             # tắt SPI kiểu mặc định (CE0 + CE1)
sudo raspi-config nonint do_i2c 1             # tắt I2C → GPIO 2/3 dùng cho TFT DC và LED C4
echo "dtoverlay=spi0-1cs" | sudo tee -a /boot/firmware/config.txt   # bản OS cũ: /boot/config.txt
sudo raspi-config nonint do_serial_cons 1     # tắt console serial  ┐ GPIO 14/15 dùng cho LED A1, A2
sudo raspi-config nonint do_serial_hw 1       # tắt UART phần cứng  ┘ (bản raspi-config cũ: do_serial 1)
sudo reboot
# sau khi khởi động lại:
ls /dev/spidev*                               # phải thấy ĐÚNG MỘT thiết bị: /dev/spidev0.0
```

Muốn quay lại màn OLED cũ: đặt `display: oled` trong `raspberry_pi/config.yaml`, cắm OLED vào GPIO 2/3 (chân 3/5) và bật I2C
(`sudo raspi-config nonint do_i2c 0`).

### Lưu ý khi cắm

- **Điện trở LED 330–470Ω**, không dùng 220Ω (nhiều LED cùng sáng sẽ vượt giới hạn dòng tổng của GPIO).
- **Không cấp nguồn servo từ chân 5V của Pi** — dùng nguồn 5V riêng và nối chung GND.
- GPIO 1 (ECHO ra) là chân ID_SC dành cho HAT: dùng được khi không cắm HAT. Nếu cảm biến RA đọc chập chờn, đổi sang GPIO 5/6/23
  (sửa `gates.out.echo` trong `config.yaml`).
- Servo rung khi đứng yên: code đã ngắt xung sau mỗi lần quay; nếu vẫn rung, chỉnh `min/max_pulse_width` trong `hardware/servo.py`.

## Hướng dẫn chạy project

### A. Chạy thử trên máy tính, chưa cần phần cứng

Yêu cầu: Python 3.10+ và Node.js 18+ (https://nodejs.org).

> Môi trường ảo `pc_server/.venv` và `pc_server/web/node_modules` đã được cài sẵn, giao diện đã build (`web/dist`).
> Chỉ cần kích hoạt môi trường ảo ở mỗi cửa sổ PowerShell mới: `cd pc_server; .\.venv\Scripts\Activate.ps1`
> rồi chạy từ bước 3. Cài lại từ đầu thì làm đủ bước 1–2.

```powershell
# 1) Tạo môi trường ảo và cài thư viện Python
cd pc_server
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2) Build giao diện React (làm một lần, hoặc sau khi sửa code giao diện)
cd web
npm install
npm run build
cd ..

# 3) (Tuỳ chọn) Tạo dữ liệu lịch sử giả để biểu đồ Thống kê có số liệu
python tools/seed_demo.py

# 4) Chạy server (HTTP :8000 cho máy này + HTTPS/WSS :8443 cho Pi). Pi giả vẽ xe là hình khối nên dùng DETECTOR=background
$env:DETECTOR="background"
python run.py

# 5) Mở một cửa sổ PowerShell khác, chạy Pi giả (xe tự ra vào)
cd pc_server
python simulator/mock_pi.py --auto
```

Mở http://localhost:8000 và đăng nhập **admin / admin123**.
Chạy nhanh cả hai bước 4–5 bằng một lệnh: `powershell -ExecutionPolicy Bypass -File scripts\demo.ps1`.

Muốn tự điều khiển xe thay vì `--auto`: chạy `python simulator/mock_pi.py` rồi gõ `in` (xe tới cổng vào),
`leave 3` (xe rời ô 3), `park 5`, `fill`, `clear`.

Sửa giao diện có hot reload: `cd pc_server\web; npm run dev`, rồi mở http://localhost:5173 (server vẫn chạy ở cổng 8000).

### B. Chạy với phần cứng thật

**Bước 1. Chuẩn bị Pi** (Raspberry Pi OS, đã cắm đủ linh kiện theo bảng trên, đã làm mục *Cấu hình Pi bắt buộc* ở trên)

```bash
sudo apt update && sudo apt install -y python3-picamera2 python3-venv python3-spidev python3-rpi.gpio
cd raspberry_pi
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Bước 2. Kiểm tra từng linh kiện** (chưa cần server)

```bash
python test_hardware.py all        # hoặc: leds | ultrasonic | barrier | near | oled (màn TFT) | camera
```

Làm tới khi tất cả **PASS**. Bài `near` cho phép thử "đưa tay lại gần cảm biến thì rào mở".
Bài `camera` đo fps và độ ổn định, lưu ảnh mẫu `camera_test.jpg`. Cách xử lý khi FAIL nằm trong `raspberry_pi/README.md`.

**Bước 3. Chạy server trên máy tính**

Máy tính và Pi phải cùng mạng Wi-Fi/LAN và cho phép cổng **8443** qua tường lửa.

```powershell
cd pc_server
$env:DETECTOR="yolo"            # xe thật; xe mô hình / hộp đồ chơi thì dùng "background"; mô hình tự train: "classifier"
python run.py                   # lần đầu tự tạo chứng chỉ TLS (data/tls/) và khóa Pi (data/pi.key)
python tools/pi_secret.py       # cửa sổ khác: in đoạn cấu hình `server:` cho Pi (url wss://, key, fingerprint)
```

**Bước 4. Chạy chương trình chính trên Pi**

```bash
nano config.yaml                 # dán đè mục server: bằng đoạn pi_secret.py vừa in
python main.py                   # thấy "[link] đã xác thực với server (HMAC hai chiều, TLS đã ghim chứng chỉ)" là được
```

Kênh Pi ↔ server được bảo mật (xem mục *Bảo mật kênh Pi ↔ server* trong `pc_server/README.md`):
mã hóa TLS, xác thực hai chiều bằng khóa bí mật, mọi gói tin được ký chống sửa / phát lại.

Trên dashboard, thanh trên cùng sẽ báo Raspberry Pi và Camera chuyển sang xanh. Server tự lấy luồng camera từ Pi, không cần cấu hình thêm.

**Bước 5. Cho AI nhận diện đúng**

1. Vào trang **Thiết bị**.
2. Với `DETECTOR=background`: dọn bãi trống, bấm **Chụp ảnh nền**.
3. Nếu camera nghiêng khác bố cục mặc định hoặc bãi có bố cục khác: vào **Sơ đồ bãi** (tài khoản quản lý), chọn mẫu / chỉnh sơ đồ,
   vẽ lại vùng từng ô ở tab **Vùng camera** rồi **Lưu & áp dụng** (không cần khởi động lại server).
   Vẫn dùng được công cụ cũ `python tools/roi_calibrate.py http://<ip-pi>:8081/snapshot.jpg` (cần khởi động lại server).
4. Với `DETECTOR=classifier`: chụp vài ảnh bãi trống và có xe từ camera, chạy `python tools/classifier_probe.py ...`
   để kiểm tra và chọn ngưỡng (xem mục *Mô hình phân loại* trong `pc_server/README.md`).
5. Đặt thử xe mô hình vào ô, xem ô đó trên sơ đồ và LED trên Pi đổi trạng thái.

**Bước 6. (Tuỳ chọn) Tự chạy Pi khi bật nguồn:** xem mục systemd trong `raspberry_pi/README.md`.

### Xử lý sự cố nhanh

| Hiện tượng | Cách xử lý |
|---|---|
| Dashboard báo Raspberry Pi offline | Kiểm tra `server.url` (`wss://<ip>:8443`), `key`, `fingerprint` trong `config.yaml` (chạy lại `tools/pi_secret.py`), ping thử, mở tường lửa cổng 8443. Xem nhật ký sự kiện `security` trên dashboard |
| Pi báo "vân tay chứng chỉ không khớp" | Server đã tạo chứng chỉ mới (hoặc đang bị giả mạo): chạy lại `tools/pi_secret.py`, cập nhật `fingerprint` |
| Camera mất tín hiệu | Mở `http://<ip-pi>:8081/stream.mjpg` bằng trình duyệt; chạy `python test_hardware.py camera` |
| Ô trống nhưng báo có xe (hoặc ngược lại) | Chụp lại ảnh nền, chỉnh `BG_THRESHOLD`/`BG_RATIO`, hoặc vẽ lại ROI |
| Không tải được YOLO | `pip install ultralytics`, lần đầu cần Internet để tải `yolov8n.pt` |
| Rào mở sai góc / ngược chiều | Đổi `barrier.open_angle` / `closed_angle` trong `config.yaml` |
| Quên mật khẩu admin | Xoá `pc_server/data/parking.db` (mất lịch sử), hoặc đặt `ADMIN_PASSWORD` rồi tạo DB mới |

## Nhận diện biển số (ESP32-CAM)

Mỗi xe ra/vào đều phải được đọc biển số. Một ESP32-CAM đặt nhìn được cả hai làn; server chỉ lấy ảnh khi Pi báo có xe.

```
 xe tới cổng ─► Pi (siêu âm) ──"arrive"──► server ──GET /capture──► ESP32-CAM
                                            │  cắt vùng làn vào/ra → YOLO tìm biển → CRNN đọc chữ → bỏ phiếu 2–4 ảnh
                                            ▼
             vào: biển mới → ghi lượt + cấp ô  │  ra: khớp lượt vào (lệch ≤1 ký tự) → tính phí → mở rào
             không đọc được / trùng xe / không có lượt vào → giữ rào, màn hình báo, bảo vệ xử lý tay trên dashboard
```

1. **Nạp firmware** `esp32_cam/esp32_cam.ino` (hướng dẫn ở đầu file): sửa WiFi và `CAM_KEY`, xem IP trên Serial Monitor.
2. **Mô hình**: train trong `D:\model_training` (`prepare_plates.py` → `train_plate.ipynb`), notebook tự chép
   `plate_det.pt`, `plate_ocr.pt`, `plate_ocr.json` vào `pc_server/models/`.
3. **Dashboard → Thiết bị → Camera biển số**: nhập `http://<ip-esp32>` và khóa, bấm *Chụp xem*, chỉnh vùng cổng vào
   (xanh) / cổng ra (đỏ) bao chỗ xe dừng, *Lưu*, rồi *Đọc thử*.
4. **Pi**: chép `main.py`, `link.py`, `hardware/tft.py` mới; trong `config.yaml` đặt `server.request_timeout_s: 6`
   (server cần 1–3 giây đọc biển; Pi chờ quá hạn sẽ chuyển chế độ offline).
5. Trang **Xe ra vào**: các lần đọc gần nhất kèm ảnh bằng chứng, nhập biển tay khi camera không đọc được
   (*Cho vào* / *Cho ra* — hệ thống ghi lượt, tính phí và mở rào), sửa biển đọc sai, kết thúc lượt treo.

| Biến môi trường (server) | Mặc định | Ý nghĩa |
|---|---|---|
| `PLATE_REQUIRED` | `1` | `1` = không đọc được biển thì không mở rào; `0` = vẫn cho qua, chỉ ghi cảnh báo |
| `PLATE_MIN_CONF` | `0.5` | dưới ngưỡng tin cậy này coi như không đọc được |
| `PLATE_MATCH_DIST` | `1` | cổng ra chấp nhận lệch tối đa n ký tự so với lúc vào (khi chỉ có 1 xe khớp) |
| `PLATE_BUDGET` | `4.0` | giây tối đa để đọc biển (tự rút ngắn theo `request_timeout_s` của Pi) |
| `PLATE_CAM_URL` | (trống) | địa chỉ ESP32-CAM ban đầu; có thể là **thư mục ảnh** để chạy thử không cần ESP32 |

Chạy thử không cần ESP32: `$env:PLATE_CAM_URL="D:\model_training\data\plates\det\images\test"` — mỗi lượt xe dùng ảnh tiếp theo.

## Thứ tự làm đề xuất

1. **PC trước**: chạy `scripts\demo.ps1`, xem dashboard, thử các trang.
2. **Pi — kiểm tra linh kiện**: `python test_hardware.py all` đến khi tất cả PASS.
3. **Camera → AI**: stream camera lên PC, chụp ảnh nền / thử YOLO, chỉnh ROI bằng `tools/roi_calibrate.py`.
4. **Ghép**: chạy `raspberry_pi/main.py` trỏ về IP máy tính, đi xe mô hình qua cổng.

## Quyết định thiết kế đáng chú ý

- **Pi 3 không chạy AI**: chỉ stream ảnh; YOLO chạy trên PC.
- **ESP32-CAM chụp theo yêu cầu** (không stream liên tục) → mát, ổn định; có khóa truy cập. Phí thu ở cổng ra tính
  theo **lượt xe** (cổng vào → cổng ra, theo biển số), lịch sử từng ô vẫn giữ để thống kê.
- **Dùng WebSocket thay MQTT**: bớt phải cài broker; Pi tự kết nối lại. Giao thức nằm trong `pc_server/README.md`.
- **Pi vẫn chạy khi mất server** (rào mở theo cảm biến), và rào không bao giờ đóng lên xe.
- **21 GPIO** được dùng: 10 LED, 2 servo, 2 cảm biến siêu âm, TFT trên SPI0 (5 chân: SCK, MOSI, CS, DC, RESET).
