"""Màn hình TFT màu SPI (ILI9341 / ST7735 / ST7789) qua luma.lcd. Cùng giao diện với Oled nên main.py không phải đổi.

Font DejaVu có đủ dấu tiếng Việt nên chữ hiển thị nguyên dấu (không cần bỏ dấu như OLED).
Bố cục vẽ cho màn 320x240, màn nhỏ hơn thì tự co theo tỉ lệ.
Khi đã nhận sơ đồ bãi từ server (show_map: true), màn chờ vẽ sơ đồ với màu từng ô,
màn hướng dẫn vẽ đường đi từ cổng vào tới ô được chỉ định.
"""
import math

from luma.core.interface.serial import spi
from luma.core.render import canvas
from luma.lcd.device import ili9341, st7735, st7789

from .oled import _font, draw_arrow

DRIVERS = {"ili9341": ili9341, "st7735": st7735, "st7789": st7789}

FG, DIM = "white", (140, 140, 140)
HEADER, OK, BAD, HILITE = (0, 90, 180), (0, 200, 80), (230, 40, 40), (255, 210, 0)
# màu sơ đồ
MAP_BG, LANE, PILLAR, ROUTE = (18, 18, 22), (62, 62, 68), (110, 95, 20), (0, 220, 255)
SLOT_FILL = {"free": (0, 135, 60), "occupied": (175, 35, 35), "reserved": (190, 140, 0)}
SLOT_UNKNOWN = (70, 70, 70)
TURN_VI = {"left": "rẽ TRÁI", "right": "rẽ PHẢI"}


def step_text(st):
    """Một bước rẽ (từ server) thành câu tiếng Việt có dấu."""
    n, t = st.get("straight", 0), st.get("turn")
    if t == "straight":
        return "Đi thẳng vào ô"
    turn = TURN_VI.get(t, str(t))
    return f"Thẳng {n} ngã, {turn}" if n else turn[0].upper() + turn[1:]


def _wrap(d, text, font, width):
    lines, cur = [], ""
    for word in text.split():
        cand = f"{cur} {word}".strip()
        if cur and d.textlength(cand, font=font) > width:
            lines.append(cur)
            cur = word
        else:
            cur = cand
    return lines + ([cur] if cur else [])


class Tft:
    def __init__(self, driver="ili9341", width=320, height=240, rotate=0, dc=2, rst=16, backlight=None,
                 spi_port=0, spi_device=0, speed_mhz=32, bgr=False, show_map=True):
        serial = spi(port=spi_port, device=spi_device, gpio_DC=dc, gpio_RST=rst, bus_speed_hz=int(speed_mhz * 1_000_000))
        # backlight=None: chân LED/BL của màn nối thẳng 3.3V. Phải truyền hàm rỗng, nếu không luma.lcd tự chiếm GPIO 18 (LED A3).
        kw = {"gpio_LIGHT": backlight} if backlight is not None else {"backlight": lambda on: None}
        if bgr:
            kw["bgr"] = True
        self.device = DRIVERS[driver](serial, width=width, height=height, rotate=rotate, **kw)
        self.w, self.h = self.device.width, self.device.height
        self.k = k = min(self.w / 320, self.h / 240)
        self.f_small, self.f_mid, self.f_big, self.f_huge = (_font(round(s * k)) for s in (18, 24, 40, 80))
        self.f_tiny = _font(round(14 * k))
        self.show_map = show_map
        self._fonts = {}

    def clear(self):
        self.device.clear()

    def _center(self, d, y, text, font, fill):
        d.text(((self.w - d.textlength(text, font=font)) / 2, y), text, font=font, fill=fill)

    def _font_px(self, px):
        px = max(8, int(px))
        if px not in self._fonts:
            self._fonts[px] = _font(px)
        return self._fonts[px]

    # --- vẽ sơ đồ bãi ---
    def _draw_lot(self, d, lot, statuses, region, target=None, route=None):
        """Vẽ sơ đồ `lot` (từ server) vừa khung `region` (x0, y0, x1, y1), giữ tỉ lệ."""
        x0, y0, x1, y1 = region
        d.rectangle(region, fill=MAP_BG)
        nodes = lot.get("nodes", {})
        xs = [0, lot["width"]] + [p[0] for p in nodes.values()]
        ys = [0, lot["height"]] + [p[1] for p in nodes.values()]
        bx0, bx1, by0, by1 = min(xs), max(xs), min(ys), max(ys)
        pad = 3 * self.k
        s = min((x1 - x0 - 2 * pad) / max(1, bx1 - bx0), (y1 - y0 - 2 * pad) / max(1, by1 - by0))
        ox = x0 + (x1 - x0 - (bx1 - bx0) * s) / 2 - bx0 * s
        oy = y0 + (y1 - y0 - (by1 - by0) * s) / 2 - by0 * s

        def P(x, y):
            return (ox + x * s, oy + y * s)

        # làn đường
        lane_w = max(3, int(60 * s))
        for a, b in lot.get("edges", []):
            if a in nodes and b in nodes:
                d.line([P(*nodes[a]), P(*nodes[b])], fill=LANE, width=lane_w)
        for p in nodes.values():  # bo tròn chỗ giao nhau
            cx, cy = P(*p)
            r = lane_w / 2
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=LANE)
        pillar = lot.get("decor", {}).get("pillar")
        if pillar:
            d.polygon([P(*p) for p in pillar], fill=PILLAR)

        # các ô
        for i, sl in enumerate(lot.get("slots", [])):
            x, y, w, h, rot = (list(sl["box"]) + [0])[:5]
            cx, cy, a = x + w / 2, y + h / 2, math.radians(rot or 0)
            ca, sa = math.cos(a), math.sin(a)
            poly = [P(cx + dx * ca - dy * sa, cy + dx * sa + dy * ca)
                    for dx, dy in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2))]
            is_target = sl["id"] == target
            st = statuses[i] if i < len(statuses) else None
            fill = HILITE if is_target else SLOT_FILL.get(st, SLOT_UNKNOWN)
            d.polygon(poly, fill=fill, outline=FG if is_target else (205, 205, 205))
            if is_target:  # viền dày cho ô đích
                d.line(poly + [poly[0]], fill=FG, width=max(2, int(3 * self.k)))
            font = self._font_px(min(w, h) * s * 0.42)
            label = sl.get("label", str(sl["id"]))
            tx, ty = P(cx, cy)
            d.text((tx, ty), label, font=font, fill="black" if is_target else FG, anchor="mm")

        # cổng vào / ra
        f = self._font_px(12 * self.k)
        for key, text, color in (("entrance", "VÀO", OK), ("exit", "RA", BAD)):
            n = lot.get(key)
            if n in nodes:
                cx, cy = P(*nodes[n])
                r = 4 * self.k
                d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)
                tw = d.textlength(text, font=f)
                tx = min(max(cx - tw / 2, x0 + 1), x1 - tw - 1)
                ty = cy + r + 1 if cy + r + 14 * self.k < y1 else cy - r - 14 * self.k
                d.text((tx, ty), text, font=f, fill=color)

        # đường đi: dừng mũi tên ở mép ô đích để không che tên ô
        if route and len(route) >= 2:
            route = [list(p) for p in route]
            box = next((sl["box"] for sl in lot.get("slots", []) if sl["id"] == target), None)
            if box:
                (px, py), (qx, qy) = route[-2], route[-1]
                seg = math.hypot(qx - px, qy - py)
                cut = min(box[2], box[3]) * 0.38
                if seg > cut:
                    route[-1] = [qx - (qx - px) * cut / seg, qy - (qy - py) * cut / seg]
            pts = [P(*p) for p in route]
            rw = max(3, int(5 * self.k))
            d.line(pts, fill=ROUTE, width=rw, joint="curve")
            (ax, ay), (bx, by) = pts[-2], pts[-1]
            n = math.hypot(bx - ax, by - ay) or 1
            ux, uy = (bx - ax) / n, (by - ay) / n
            hl = 11 * self.k
            d.polygon([(bx + ux * hl * 0.3, by + uy * hl * 0.3),
                       (bx - ux * hl - uy * hl * 0.6, by - uy * hl + ux * hl * 0.6),
                       (bx - ux * hl + uy * hl * 0.6, by - uy * hl - ux * hl * 0.6)], fill=ROUTE)
            sx, sy = pts[0]
            d.ellipse((sx - rw, sy - rw, sx + rw, sy + rw), fill=ROUTE)

    def _use_map(self, lot):
        return bool(self.show_map and lot and lot.get("slots"))

    # --- các màn hình ---
    def idle(self, free, total, online=True, lot=None, statuses=None):
        if self._use_map(lot):
            return self._idle_map(free, total, online, lot, statuses or [])
        k = self.k
        with canvas(self.device) as d:
            d.rectangle((0, 0, self.w, 40 * k), fill=HEADER)
            self._center(d, 6 * k, "SMART PARKING", self.f_mid, FG)
            self._center(d, 52 * k, f"{free}/{total}", self.f_huge, OK if free else BAD)
            self._center(d, 145 * k, "ô trống" if free else "BÃI ĐÃ ĐẦY", self.f_mid, FG)
            status, color = ("Sẵn sàng", OK) if online else ("OFFLINE", BAD)
            d.ellipse((10 * k, 208 * k, 24 * k, 222 * k), fill=color)
            d.text((32 * k, 204 * k), status, font=self.f_small, fill=DIM)

    def _idle_map(self, free, total, online, lot, statuses):
        k = self.k
        with canvas(self.device) as d:
            d.rectangle((0, 0, self.w, 30 * k), fill=HEADER)
            d.text((8 * k, 4 * k), "SMART PARKING", font=self.f_small, fill=FG)
            txt = f"{free}/{total} trống" if free else "BÃI ĐẦY"
            d.text((self.w - 8 * k - d.textlength(txt, font=self.f_small), 4 * k), txt,
                   font=self.f_small, fill=OK if free else BAD)
            self._draw_lot(d, lot, statuses, (0, 31 * k, self.w - 1, self.h - 22 * k))
            # chân trang: trạng thái kết nối + chú thích màu
            fy = self.h - 19 * k
            status, color = ("Sẵn sàng", OK) if online else ("OFFLINE", BAD)
            d.ellipse((6 * k, fy + 3 * k, 16 * k, fy + 13 * k), fill=color)
            d.text((20 * k, fy), status, font=self.f_tiny, fill=DIM)
            x = self.w - 6 * k
            for name, st in (("Giữ chỗ", "reserved"), ("Có xe", "occupied"), ("Trống", "free")):
                x -= d.textlength(name, font=self.f_tiny)
                d.text((x, fy), name, font=self.f_tiny, fill=DIM)
                x -= 14 * k
                d.rectangle((x, fy + 3 * k, x + 10 * k, fy + 13 * k), fill=SLOT_FILL[st])
                x -= 8 * k

    def _guidance_map(self, title, lines, arrow, lot, statuses, route, target, steps, plate=None):
        k = self.k
        texts = [step_text(st) for st in steps] if steps else list(lines)
        with canvas(self.device) as d:
            d.rectangle((0, 0, self.w, 40 * k), fill=HEADER)
            d.text((8 * k, 0), title, font=self.f_big, fill=HILITE)
            sub, font = (plate, self.f_mid) if plate else ("Đi theo vạch xanh", self.f_tiny)  # biển số xe đang được dẫn
            d.text((self.w - 8 * k - d.textlength(sub, font=font), (8 if plate else 13) * k), sub, font=font, fill=FG)
            panel_x = 218 * k
            self._draw_lot(d, lot, statuses, (0, 41 * k, panel_x - 2 * k, self.h - 1), target=target, route=route)
            # cột phải: mũi tên bước đầu + các bước
            pcx = (panel_x + self.w) / 2
            draw_arrow(d, arrow, cx=pcx, cy=72 * k, s=1.0 * k, fill=HILITE)
            y, maxw = 102 * k, self.w - panel_x - 6 * k
            for i, t in enumerate(texts, 1):
                rows = _wrap(d, f"{i}. {t}", self.f_tiny, maxw)
                if y + len(rows) * 17 * k > self.h:
                    break
                for row in rows:
                    d.text((panel_x + 2 * k, y), row, font=self.f_tiny, fill=HILITE if i == 1 else FG)
                    y += 17 * k
                y += 5 * k

    def guidance(self, title, lines, arrow, lot=None, statuses=None, route=None, target=None, steps=None,
                 label=None, plate=None):
        """Có sơ đồ: vẽ sơ đồ + đường đi tới ô. Không có: tiêu đề + mũi tên + các bước rẽ."""
        if self._use_map(lot):
            return self._guidance_map(f"Ô {label}" if label else title, lines, arrow, lot,
                                      statuses or [], route, target, steps, plate=plate)
        k = self.k
        with canvas(self.device) as d:
            d.rectangle((0, 0, self.w, 60 * k), fill=HEADER)
            d.text((12 * k, 8 * k), title, font=self.f_big, fill=HILITE)
            draw_arrow(d, arrow, cx=self.w - 40 * k, cy=30 * k, s=1.0 * k, fill=HILITE)
            y = 72 * k
            if plate:  # biển số xe đang được dẫn
                d.text((12 * k, y), plate, font=self.f_mid, fill=HILITE)
                y += 40 * k
            for i, ln in enumerate(lines[:4 - bool(plate)], 1):
                d.text((12 * k, y), f"{i}. {ln}", font=self.f_mid, fill=FG)
                y += 40 * k

    def message(self, lines, big=False):
        with canvas(self.device) as d:
            font = self.f_big if big else self.f_mid
            step = (56 if big else 36) * self.k
            y = (self.h - len(lines) * step) / 2
            for i, ln in enumerate(lines):
                self._center(d, y, str(ln), font, HILITE if big and i == 0 else FG)
                y += step

    def test_pattern(self):
        colors = ["red", "lime", "blue", "yellow", "cyan", "magenta", "white"]
        bw = self.w / len(colors)
        with canvas(self.device) as d:
            for i, c in enumerate(colors):
                d.rectangle((i * bw, 0, (i + 1) * bw, self.h * 0.6), fill=c)
            d.rectangle((0, 0, self.w - 1, self.h - 1), outline=FG)
            self._center(d, self.h * 0.7, "TFT OK — Tiếng Việt", self.f_mid, FG)
