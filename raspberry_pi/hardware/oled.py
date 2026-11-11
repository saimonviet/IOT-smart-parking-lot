"""Màn hình OLED SSD1306 128x64 (I2C). Chỉ hiển thị ASCII nên chữ tiếng Việt được bỏ dấu."""
import unicodedata

from luma.core.interface.serial import i2c
from luma.core.render import canvas
from luma.oled.device import sh1106, ssd1306
from PIL import ImageFont

DRIVERS = {"ssd1306": ssd1306, "sh1106": sh1106}  # màn 0.96" thường là ssd1306, 1.3" thường là sh1106

_FONT_PATHS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
               "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]


def fold(text):
    text = str(text).replace("đ", "d").replace("Đ", "D")
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def draw_arrow(d, kind, cx=100, cy=42, s=1.0, fill=1):
    """Mũi tên trái/phải/thẳng, tâm (cx, cy), tỉ lệ s (1.0 ≈ 44px). Dùng chung cho OLED và TFT."""
    shapes = {
        "left": [(-22, 0), (-2, -18), (-2, -8), (22, -8), (22, 8), (-2, 8), (-2, 18)],
        "right": [(22, 0), (2, -18), (2, -8), (-22, -8), (-22, 8), (2, 8), (2, 18)],
        "straight": [(0, -22), (-16, -2), (-6, -2), (-6, 20), (6, 20), (6, -2), (16, -2)],
    }
    shape = shapes.get("straight" if kind == "up" else kind)
    if shape:
        d.polygon([(cx + x * s, cy + y * s) for x, y in shape], fill=fill)


def _font(size):
    for p in _FONT_PATHS:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


class Oled:
    def __init__(self, port=1, address=0x3C, width=128, height=64, rotate=0, driver="ssd1306"):
        self.device = DRIVERS[driver](i2c(port=port, address=address), width=width, height=height, rotate=rotate)
        self.device.contrast(255)
        self.w, self.h = width, height
        self.f_small, self.f_mid, self.f_big = _font(10), _font(14), _font(26)

    def clear(self):
        self.device.clear()

    # --- các màn hình ---
    def idle(self, free, total, online=True, **_):  # OLED nhỏ: bỏ qua sơ đồ
        with canvas(self.device) as d:
            d.text((2, 0), "SMART PARKING", font=self.f_small, fill=1)
            d.line((0, 13, self.w, 13), fill=1)
            d.text((6, 18), f"{free}/{total}", font=self.f_big, fill=1)
            d.text((78, 26), "o trong", font=self.f_mid, fill=1)
            d.text((2, 52), "San sang" if online else "OFFLINE", font=self.f_small, fill=1)

    def guidance(self, title, lines, arrow, **_):
        """Tiêu đề (ô được chỉ định) + mũi tên của bước đầu tiên ở góc phải, các bước rẽ ở dưới."""
        with canvas(self.device) as d:
            d.text((2, 0), fold(title), font=self.f_mid, fill=1)
            draw_arrow(d, arrow, cx=self.w - 14, cy=9, s=0.4)
            d.line((0, 17, self.w, 17), fill=1)
            y = 20
            for i, ln in enumerate(lines[:3], 1):
                d.text((2, y), f"{i}.{fold(ln)}", font=self.f_small, fill=1)
                y += 14

    def message(self, lines, big=False):
        with canvas(self.device) as d:
            n = len(lines)
            font = self.f_mid if big else self.f_small
            step = 20 if big else 14
            y = (self.h - n * step) // 2
            for ln in lines:
                t = fold(ln)
                w = d.textlength(t, font=font)
                d.text(((self.w - w) / 2, y), t, font=font, fill=1)
                y += step

    def test_pattern(self):
        with canvas(self.device) as d:
            d.rectangle((0, 0, self.w - 1, self.h - 1), outline=1, fill=0)
            d.line((0, 0, self.w - 1, self.h - 1), fill=1)
            d.line((0, self.h - 1, self.w - 1, 0), fill=1)
            d.text((40, 28), "OLED OK", font=self.f_mid, fill=1)
