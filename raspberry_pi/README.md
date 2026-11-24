# Raspberry Pi 3 — bãi đỗ xe thông minh

Pi làm 4 việc: đọc 2 cảm biến siêu âm ở cổng, điều khiển 2 rào chắn servo, bật/tắt đèn LED từng ô + màn TFT ở cổng vào,
và stream camera bãi đỗ cho server. Mọi quyết định (ô nào trống, cho xe vào/ra, đọc biển số bằng ESP32-CAM) do
`pc_server` đưa ra qua kênh WebSocket bảo mật. Pi chỉ báo "có xe ở cổng" rồi làm theo kết quả.

## Cấu trúc

```
raspberry_pi/
├── main.py              # khởi tạo linh kiện, nối với server, vòng lặp gửi số liệu
├── config.yaml          # chân cắm, góc servo, địa chỉ + khóa server (nguồn duy nhất về số chân)
├── requirements.txt
├── test_hardware.py     # test từng linh kiện, không cần server
├── core/                # logic, không phụ thuộc phần cứng
│   ├── gate.py          #   máy trạng thái 1 cổng: chờ xe → hỏi server → mở/giữ rào → đóng
│   ├── screen.py        #   điều phối màn hình: màn chờ / hướng dẫn xe vào / thông báo
│   ├── link.py          #   kết nối wss tới server, tự kết nối lại
│   └── secure_channel.py#   bắt tay HMAC + ký từng tin (bản giống hệt pc_server/app/secure_channel.py)
└── hardware/            # driver từng linh kiện, tạo từ config.yaml qua hardware/__init__.py
    ├── ultrasonic.py    #   HC-SR04
    ├── barrier.py       #   rào servo SG90
    ├── leds.py          #   đèn từng ô
    ├── tft.py           #   màn TFT SPI (ILI9341/ST7735/ST7789)
    └── camera.py        #   Pi Camera → MJPEG :8081
```

## 1. Đấu nối

Số chân (BCM) lấy theo `config.yaml`. Sơ đồ header 40 chân và cách nối từng loại linh kiện ở
[README chính](../README.md#hướng-dẫn-cắm-chân-raspberry-pi-3). Nếu cắm khác, chỉ cần sửa `config.yaml`, không phải sửa code.

| Linh kiện | Mục trong config.yaml |
|---|---|
| Siêu âm cổng vào / ra (ECHO qua cầu chia áp 1kΩ/2kΩ) | `gates.in`, `gates.out` |
| Servo rào vào / ra (nguồn 5V riêng, GND chung) | `barrier.in_pin`, `barrier.out_pin` + góc đóng/mở |
| Đèn LED từng ô, theo thứ tự ô trên server | `leds.pins` |
| Màn TFT 2.8" (SPI0: SCK 11, MOSI 10, CS 8) | `tft.dc`, `tft.rst` |
| Pi Camera | khe CSI, mục `camera` |

## 2. Cài đặt (Raspberry Pi OS)

```bash
# SPI0 chỉ 1 CS cho TFT (qua overlay spi0-1cs, GPIO 7 vẫn dùng được cho LED A2);
# tắt I2C (GPIO 2/3 dùng cho TFT DC, LED C4) và serial (GPIO 14/15 dùng cho siêu âm cổng ra)
sudo raspi-config nonint do_spi 1
sudo raspi-config nonint do_i2c 1
echo "dtoverlay=spi0-1cs" | sudo tee -a /boot/firmware/config.txt   # bản OS cũ: /boot/config.txt
sudo raspi-config nonint do_serial_cons 1
sudo raspi-config nonint do_serial_hw 1
sudo reboot                                    # rồi SSH lại
sudo apt update && sudo apt install -y python3-picamera2 python3-venv python3-spidev python3-rpi.gpio \
    python3-gpiozero python3-lgpio python3-yaml python3-pil python3-websocket fonts-dejavu-core
ls /dev/spidev*                                # phải thấy đúng một thiết bị: /dev/spidev0.0 (TFT)

cd raspberry_pi                                # KHÔNG dùng sudo cho các lệnh python/pip bên dưới
python3 -m venv --system-site-packages .venv   # --system-site-packages để dùng được picamera2, gpiozero, lgpio
source .venv/bin/activate
pip install -r requirements.txt
nano config.yaml                               # mục server: dán đoạn do `python tools/pi_secret.py` (máy chạy pc_server) in ra
```

## 3. Chạy

```bash
python main.py
```

Lúc khởi động: màn TFT hiện "Đang khởi động", đèn chạy một vòng theo thứ tự ô (thấy ngay đèn nào cắm sai),
log in địa chỉ stream camera. Linh kiện nào lỗi thì in `[!] ...` kèm lý do. Màn hình và camera lỗi vẫn chạy tiếp được,
cảm biến, rào và đèn là bắt buộc.

### Test từng linh kiện (không cần server)

```bash
python test_hardware.py            # menu: 1=sensor 2=servo 3=led 4=tft 5=camera
python test_hardware.py sensor     # hoặc servo | led | tft | camera | all
```
Dừng `main.py` / service `parking` trước để không tranh GPIO.

### Luồng một cổng (`core/gate.py`)

```
IDLE ──siêu âm thấy xe──► hỏi server ──cho phép──► OPEN ──xe đi khuất ≥ clear_delay_s──► CLOSING ──rào đóng xong──► IDLE
                                     └─từ chối───► DENIED ──xe lùi đi──────────────────────────────────────────────► IDLE
```
- **Cổng vào**: server đọc biển, chọn ô gần nhất → TFT hiện ô + đường đi trên sơ đồ + biển số → mở rào.
  Bãi đầy / không đọc được biển / xe đã ở trong bãi → TFT báo lý do, rào **không** mở.
- **Cổng ra**: server đọc biển, khớp lượt vào, tính phí → mở rào (TFT không hiện gì thêm). Không khớp → TFT báo lý do, giữ rào.
- Rào **không bao giờ đóng khi cảm biến còn thấy xe**; xe chen vào lúc rào đang đóng → mở lại, tính là lượt mới.
- Xe nối đuôi khi rào còn mở (cảm biến trống ≥ `new_car_gap_s` rồi lại có xe) → hỏi server lượt mới.
- Quản lý mở/đóng rào hoặc nhập biển tay trên dashboard → server gửi lệnh `open_barrier` / `close_barrier` / `gate_result`.
- **Mất server** → `offline.policy`: `open` vẫn mở rào theo cảm biến, `deny` giữ rào đóng. Màn hình vẫn vẽ sơ đồ lần trước
  (`.lot_cache.json`), tự đồng bộ khi có lại mạng.
- Đèn: sáng = ô trống, tắt = có xe, nhấp nháy = đang giữ chỗ cho xe vừa vào.

### Xử lý sự cố

- **Siêu âm không đọc được**: kiểm tra cầu chia áp ở ECHO, VCC 5V, tráo TRIG/ECHO. Xem khoảng cách trên trang *Thiết bị & AI*.
- **Servo không quay / sai góc**: nguồn 5V riêng + GND chung; chỉnh `barrier.*_open_angle` / `*_closed_angle`.
  Servo rung: `sudo pigpiod` và chạy với `GPIOZERO_PIN_FACTORY=pigpio`.
- **LED báo "GPIO đang bị ... chiếm"**: chưa tắt I2C / serial / chưa đặt `spi0-1cs` (mục 2).
- **TFT trắng xoá**: kiểm tra `ls /dev/spidev0.0`, dây SCK/SDI/CS/DC/RESET; thử `tft.speed_mhz: 16`.
  **Tối đen**: chân LED (đèn nền) chưa nối 3.3V. **Sai màu** (đỏ ↔ xanh dương): `tft.bgr: true`. **Ngược chiều**: đổi `tft.rotate` (0–3).
- **Camera không chạy**: `rpicam-hello -t 5000` (bản cũ: `libcamera-hello`), kiểm tra cáp CSI; giảm `camera.fps` / độ phân giải.
  Xem stream từ máy tính: `http://<ip-pi>:8081/stream.mjpg`.
- **Không kết nối được server**: xem mục xử lý sự cố ở README chính (`server.url`, `key`, `fingerprint`, tường lửa cổng 8443).

### Tự chạy khi bật nguồn (systemd)

```ini
# /etc/systemd/system/parking.service
[Unit]
Description=Smart Parking Pi
After=network-online.target
Wants=network-online.target

[Service]
User=pi
WorkingDirectory=/home/pi/raspberry_pi
ExecStart=/home/pi/raspberry_pi/.venv/bin/python main.py
Restart=always

[Install]
WantedBy=multi-user.target
```
`sudo systemctl enable --now parking`

Cập nhật code từ bản cũ: chép đè cả thư mục rồi **xóa** các file cũ ở thư mục gốc (`link.py`, `secure_channel.py`,
`demo_flow.py`, `oled_probe.py`, `update_config.py`) và `hardware/oled.py`, `hardware/servo.py`,
`hardware/cam_mount.py`, `hardware/birthday.py`.
