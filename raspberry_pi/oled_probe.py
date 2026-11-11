"""Thử OLED với nhiều loại chip / kích thước để biết màn hình là loại nào.

Chạy:  python oled_probe.py [địa chỉ, mặc định 0x3C]
Lần thử nào làm màn hình trắng xoá + hiện số thứ tự -> ghi driver/width/height tương ứng vào config.yaml (mục oled).
"""
import sys
import time

from luma.core.interface.serial import i2c
from luma.core.render import canvas
from luma.oled.device import sh1106, sh1107, ssd1306, ssd1309

address = int(sys.argv[1], 16) if len(sys.argv) > 1 else 0x3C

TRIALS = [  # (driver, width, height)
    ("ssd1306", ssd1306, 128, 64),
    ("sh1106", sh1106, 128, 64),
    ("ssd1306", ssd1306, 128, 32),
    ("ssd1309", ssd1309, 128, 64),
    ("sh1107", sh1107, 128, 128),
]

for i, (name, drv, w, h) in enumerate(TRIALS, 1):
    print(f"[{i}] {name} {w}x{h} (0x{address:02X}) ... ", end="", flush=True)
    try:
        dev = drv(i2c(port=1, address=address), width=w, height=h)
        dev.contrast(255)
        dev.show()
        with canvas(dev) as d:
            d.rectangle((0, 0, w - 1, h - 1), outline=1, fill=1)
            d.text((w // 2 - 3, h // 2 - 5), str(i), fill=0)
        print("đang hiển thị 5s - màn hình có trắng xoá không?")
        time.sleep(5)
        dev.clear()
    except Exception as e:
        print("lỗi:", e)
print("Xong. Ghi lại số [n] nào làm màn hình sáng.")
