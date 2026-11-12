# Raspberry Pi 3 — bãi đỗ xe thông minh

Pi làm 4 việc: đọc 2 cảm biến siêu âm, điều khiển 2 rào chắn, bật/tắt 10 đèn LED (ô A1–C4) + màn hình TFT 2.8", và stream camera.
Mọi quyết định (ô nào trống, chỉ ô nào cho xe vào) do `pc_server` đưa ra qua WebSocket.

## 1. Đấu nối

Bảng chân, sơ đồ header 40 chân và cách nối từng linh kiện nằm ở [README chính](../README.md#hướng-dẫn-cắm-chân-raspberry-pi-3).
Tóm tắt (GPIO / chân vật lý):

| Linh kiện | GPIO | Chân vật lý |
|---|---|---|
| LED A1, A2, A3 | 14, 15, 18 | 8, 10, 12 |
| LED B1, B2, B3 | 20, 21, 4 | 38, 40, 7 |
| LED C1, C2, C3, C4 | 17, 27, 22, 3 | 11, 13, 15, 5 |
| Servo vào / ra | 12 / 24 | 32 / 18 |
| Servo xoay ESP32-CAM (biển số) | 23 | 16 |
| Siêu âm vào TRIG / ECHO* | 5 / 25 | 29 / 22 |
| Siêu âm ra TRIG / ECHO* | 7 / 1 | 26 / 28 |
| TFT 2.8" ILI9341 SCK / SDI(MOSI) / CS (SPI0) | 11 / 10 / 8 | 23 / 19 / 24 |
| TFT DC / RESET | 2 / 16 | 3 / 36 |
| TFT VCC / LED (đèn nền) / GND | 3.3V / 3.3V / GND | 1 / 17 / 20 |

\* ECHO qua cầu chia áp 1kΩ/2kΩ. Servo và LED: xem lưu ý về nguồn và điện trở trong README chính.

## 2. Cài đặt (Raspberry Pi OS)

```bash
# Cấu hình chân (bắt buộc với bộ chân này): SPI0 chỉ 1 CS cho TFT (GPIO 7 vẫn là TRIG RA); tắt serial (GPIO 14, 15 dùng cho LED)
sudo raspi-config nonint do_spi 1
sudo raspi-config nonint do_i2c 1             # tắt I2C: GPIO 2/3 dùng cho TFT DC và LED C4
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
nano config.yaml                               # mục server: dán đoạn do `python tools/pi_secret.py` (trên máy chạy pc_server) in ra
```

## 3. Kiểm tra linh kiện TRƯỚC (`test_hardware.py`)

```bash
python test_hardware.py            # menu: chọn từng bài hoặc 'a' = chạy tất cả
python test_hardware.py leds       # đèn sáng lần lượt A1 → C4, rồi ngược lại, rồi nhấp nháy
python test_hardware.py ledson     # bật sáng TẤT CẢ đèn, giữ tới khi nhấn Enter / Ctrl+C
python test_hardware.py ultrasonic # in khoảng cách realtime của 2 cảm biến, đánh giá độ nhiễu
python test_hardware.py barrier    # mở/đóng từng rào
python test_hardware.py servo      # chỉ test 2 servo SG90: quét 0→90→0°, rồi mở/đóng 2 lần
python test_hardware.py near       # ĐẾN GẦN THÌ MỞ RÀO: đưa tay vào cảm biến → rào mở; bỏ ra 2s → đóng
python test_hardware.py oled       # màn hình TFT: dải màu, màn chờ, mũi tên trái/phải/thẳng, "BÃI ĐẦY", tiếng Việt
python test_hardware.py birthday   # màn hình động "Happy Birthday Thúy Hèng": bánh kem + nến + bóng bay + confetti (30s)
python test_hardware.py camera     # 15s đo fps + khoảng đứng hình; lưu camera_test.jpg; PASS nếu fps ≥ 80% mục tiêu
python test_hardware.py all        # tất cả + bảng PASS/FAIL cuối cùng
```

Gợi ý chẩn đoán:
- **Siêu âm không đọc được**: kiểm tra cầu chia áp ở ECHO, VCC 5V, tráo TRIG/ECHO.
- **Servo không quay / sai góc**: kiểm tra nguồn 5V riêng + GND chung; chỉnh `barrier.open_angle` / `closed_angle`.
- **TFT trắng xoá**: chưa nhận lệnh, kiểm tra `ls /dev/spidev0.0`, dây SCK/SDI/CS/DC/RESET; thử `tft.speed_mhz: 16`.
- **TFT tối đen**: chân LED (đèn nền) chưa nối 3.3V.
- **TFT sai màu** (đỏ ↔ xanh dương): đặt `tft.bgr: true`. **Ngược chiều / lật hình**: đổi `tft.rotate` (0–3).
- Dùng lại OLED cũ: `display: oled` trong `config.yaml`, bật I2C (`sudo raspi-config nonint do_i2c 0`), `i2cdetect -y 1` thấy 3c.
- **Camera FAIL**: `libcamera-hello` thử trước; giảm `camera.fps`/độ phân giải; kiểm tra cáp CSI cắm đúng chiều.
  Xem stream từ máy tính: `http://<ip-pi>:8081/stream.mjpg`.

### Demo luồng xe (không cần server / model)

```bash
python demo_flow.py              # siêu âm < 10cm → mở rào; đo > 10cm liên tục 2s → đóng; LED sáng hết; màn hình "Xin chào"
python demo_flow.py --cm 15 --clear 3
```

## 4. Chạy chương trình chính

```bash
python main.py
```

Luồng hoạt động mỗi cổng: `IDLE → (siêu âm thấy xe) → hỏi server → mở rào → (xe đi khuất ≥ 2s) → đóng rào → IDLE`.
- Cổng **vào**: server trả ô gần nhất → TFT hiện số ô + hướng rẽ → rào mở. Bãi đầy → TFT "BAI DA DAY", rào **không** mở.
- Rào **không bao giờ đóng khi cảm biến còn thấy xe**; nếu có xe chen vào lúc đang đóng, rào mở lại.
- **Mất kết nối server** → chế độ offline (`offline.policy`): vẫn mở rào theo cảm biến, đèn giữ trạng thái cuối, tự đồng bộ khi có lại mạng.
- Đèn: sáng = ô trống, tắt = có xe, nhấp nháy = đang giữ chỗ cho xe vừa vào.

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
