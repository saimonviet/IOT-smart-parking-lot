"""Màn hình chúc mừng sinh nhật có hiệu ứng động cho màn TFT màu (vẽ bằng Pillow, không cần file ảnh).

Gồm: chữ "Happy Birthday" cầu vồng nhấp nhô, tên người nhận, bánh kem 2 tầng với nến lửa lung linh,
bóng bay đung đưa, trái tim bay lên, sao lấp lánh và confetti rơi.
Bố cục vẽ cho 320x240, màn khác cỡ thì tự co theo tỉ lệ.
"""
import math
import random
import time

from PIL import Image, ImageDraw

from .oled import _font

BG_TOP, BG_BOTTOM = (18, 8, 48), (85, 22, 90)
RAINBOW = [(255, 90, 90), (255, 165, 60), (255, 228, 80), (110, 225, 120),
           (80, 195, 255), (175, 130, 255), (255, 120, 200)]
PINK, PINK_DARK, PINK_LIGHT = (255, 125, 180), (215, 70, 135), (255, 190, 215)
CREAM, WHITE, GOLD = (255, 240, 220), (255, 255, 255), (255, 215, 90)
PLATE, CHERRY, WICK = (205, 205, 220), (220, 20, 50), (60, 40, 30)
FLAME_OUT, FLAME_IN = (255, 140, 30), (255, 245, 150)


def _mix(a, b, t):
    return tuple(int(x + (y - x) * t) for x, y in zip(a, b))


def heart(d, cx, cy, r, fill):
    """Trái tim tâm (cx, cy); r = bán kính mỗi nửa trên."""
    d.ellipse((cx - 2 * r, cy - r, cx, cy + r), fill=fill)
    d.ellipse((cx, cy - r, cx + 2 * r, cy + r), fill=fill)
    d.polygon([(cx - 1.95 * r, cy + 0.35 * r), (cx + 1.95 * r, cy + 0.35 * r), (cx, cy + 2.3 * r)], fill=fill)


def star(d, cx, cy, r, fill):
    pts = []
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5
        rr = r if i % 2 == 0 else r * 0.45
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    d.polygon(pts, fill=fill)


class BirthdayScene:
    def __init__(self, width, height, name="Thúy Hèng", title="Happy Birthday"):
        self.w, self.h = width, height
        self.k = k = min(width / 320, height / 240)
        self.cx = width / 2
        self.name, self.title = name, title
        self.f_title = _font(round(30 * k))
        self.f_name = _font(round(36 * k))

        # nền gradient vẽ sẵn 1 lần
        self.bg = Image.new("RGB", (width, height))
        bd = ImageDraw.Draw(self.bg)
        for y in range(height):
            bd.line((0, y, width, y), fill=_mix(BG_TOP, BG_BOTTOM, y / max(1, height - 1)))

        rnd = random.Random(2024)
        self.stars = [(rnd.uniform(0, width), rnd.uniform(0, height * 0.75), rnd.uniform(1.5, 3.5) * k,
                       rnd.uniform(0, 6.28)) for _ in range(22)]
        self.sprinkles = [(rnd.uniform(-56, 56), rnd.uniform(188, 218), rnd.choice(RAINBOW)) for _ in range(26)]
        self.particles = [self._new_particle(rnd, initial=True) for _ in range(34)]
        self.rnd = rnd
        self._last_t = 0.0

    # --- tọa độ thiết kế (320x240, gốc x ở giữa màn) -> pixel ---
    def X(self, dx):
        return self.cx + dx * self.k

    def Y(self, y):
        return y * self.k

    def _new_particle(self, rnd, initial=False):
        kind = "heart" if rnd.random() < 0.25 else "confetti"
        y = rnd.uniform(0, self.h) if initial else (self.h + 10 if kind == "heart" else -10)
        return {"kind": kind, "x": rnd.uniform(0, self.w), "y": y,
                "v": rnd.uniform(18, 45) * self.k * (-0.6 if kind == "heart" else 1),
                "c": rnd.choice(RAINBOW), "s": rnd.uniform(2.5, 4.5) * self.k,
                "spin": rnd.uniform(0, 6.28), "sway": rnd.uniform(0, 6.28)}

    # --- các phần của cảnh ---
    def _particles(self, d, t, dt):
        for i, p in enumerate(self.particles):
            p["y"] += p["v"] * dt
            if p["y"] > self.h + 12 or p["y"] < -12:
                self.particles[i] = p = self._new_particle(self.rnd)
            x = p["x"] + math.sin(t * 2 + p["sway"]) * 6 * self.k
            if p["kind"] == "heart":
                heart(d, x, p["y"], p["s"] * 0.9, p["c"])
            else:  # mảnh giấy lật: bề ngang co giãn theo cos
                sw = abs(math.cos(t * 5 + p["spin"])) * p["s"] + 0.8
                d.rectangle((x - sw, p["y"] - p["s"] * 0.6, x + sw, p["y"] + p["s"] * 0.6), fill=p["c"])

    def _stars(self, d, t):
        for x, y, r, ph in self.stars:
            b = 0.5 + 0.5 * math.sin(t * 3 + ph)
            if b > 0.15:
                star(d, x, y, r * (0.6 + 0.4 * b), _mix(BG_TOP, (255, 250, 200), b))

    def _balloon(self, d, dx, base_y, color, t, phase):
        k = self.k
        cx = self.X(dx) + math.sin(t * 1.3 + phase) * 4 * k
        cy = self.Y(base_y) + math.sin(t * 1.7 + phase) * 4 * k
        rx, ry = 16 * k, 20 * k
        string = [(cx + math.sin(t * 2 + phase + i * 0.7) * 2.5 * k, cy + ry + 4 * k + i * 7 * k) for i in range(14)]
        d.line(string, fill=(225, 225, 235), width=max(1, round(k)))
        d.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=color)
        d.polygon([(cx, cy + ry - 2 * k), (cx - 4 * k, cy + ry + 5 * k), (cx + 4 * k, cy + ry + 5 * k)], fill=color)
        d.ellipse((cx - rx * 0.6, cy - ry * 0.65, cx - rx * 0.2, cy - ry * 0.15), fill=_mix(color, WHITE, 0.55))

    def _frosting(self, d, x0, x1, y, drip_len, color):
        X, Y, k = self.X, self.Y, self.k
        d.rectangle((X(x0), Y(y - 3), X(x1), Y(y + 4)), fill=color)
        n = int((x1 - x0) / 11)
        for i in range(n + 1):
            x = x0 + 4 + i * (x1 - x0 - 8) / max(1, n)
            ln = drip_len * (1.0 if i % 2 == 0 else 0.55)
            d.rounded_rectangle((X(x) - 3.5 * k, Y(y), X(x) + 3.5 * k, Y(y + 4 + ln)), radius=3.5 * k, fill=color)

    def _cake(self, d, t):
        X, Y, k = self.X, self.Y, self.k
        d.ellipse((X(-78), Y(214), X(78), Y(234)), fill=PLATE)                      # đĩa
        d.rectangle((X(-62), Y(180), X(62), Y(222)), fill=PINK)                     # tầng dưới
        d.rectangle((X(-62), Y(205), X(62), Y(209)), fill=PINK_DARK)
        for sx, sy, c in self.sprinkles:                                            # cốm màu
            d.rectangle((X(sx) - 1.5 * k, Y(sy) - 1 * k, X(sx) + 1.5 * k, Y(sy) + 1 * k), fill=c)
        self._frosting(d, -62, 62, 180, 7, CREAM)
        d.rectangle((X(-42), Y(150), X(42), Y(180)), fill=PINK_LIGHT)                # tầng trên
        for i in range(-3, 4):                                                       # tim trắng xen chấm bi
            x = X(i * 11)
            if i % 2:
                heart(d, x, Y(164), 1.8 * k, WHITE)
            else:
                d.ellipse((x - 2 * k, Y(167) - 2 * k, x + 2 * k, Y(167) + 2 * k), fill=PINK_DARK)
        self._frosting(d, -42, 42, 150, 5, WHITE)
        for dx in (-34, 34):                                                         # anh đào
            d.ellipse((X(dx) - 5 * k, Y(141), X(dx) + 5 * k, Y(151)), fill=CHERRY)
            d.ellipse((X(dx) - 3 * k, Y(143), X(dx) - 1 * k, Y(145)), fill=(255, 150, 160))

        for i, dx in enumerate((-20, 0, 20)):                                        # nến
            c = RAINBOW[(i * 2) % len(RAINBOW)]
            for j, y in enumerate(range(120, 148, 5)):
                d.rectangle((X(dx - 3), Y(y), X(dx + 3), Y(min(y + 5, 148))), fill=c if j % 2 == 0 else WHITE)
            d.line((X(dx), Y(114), X(dx), Y(120)), fill=WICK, width=max(1, round(1.5 * k)))
            f = 1 + 0.18 * math.sin(t * 13 + i * 2.1) + 0.08 * math.sin(t * 31 + i)
            sway = math.sin(t * 7 + i) * 1.2 * k
            fx, fy = X(dx) + sway, Y(108)
            d.ellipse((fx - 9 * k * f, fy - 9 * k * f, fx + 9 * k * f, fy + 9 * k * f),
                      fill=_mix(BG_TOP, (150, 70, 60), 0.6))                         # quầng sáng
            d.ellipse((fx - 4.5 * k * f, fy - 9 * k * f, fx + 4.5 * k * f, fy + 6 * k), fill=FLAME_OUT)
            d.ellipse((fx - 2.2 * k * f, fy - 4 * k * f, fx + 2.2 * k * f, fy + 5 * k), fill=FLAME_IN)

    def _texts(self, d, t):
        k = self.k
        # "Happy Birthday": từng chữ một màu cầu vồng, chạy màu + nhấp nhô như sóng
        widths = [d.textlength(ch, font=self.f_title) for ch in self.title]
        x = (self.w - sum(widths)) / 2
        shift = int(t * 6)
        for i, (ch, cw) in enumerate(zip(self.title, widths)):
            if ch != " ":
                y = 6 * k + math.sin(t * 4 + i * 0.55) * 3 * k
                d.text((x + 2 * k, y + 2 * k), ch, font=self.f_title, fill=(40, 10, 50))
                d.text((x, y), ch, font=self.f_title, fill=RAINBOW[(i + shift) % len(RAINBOW)])
            x += cw
        # tên: chữ vàng có bóng hồng, 2 trái tim đập hai bên
        nw = d.textlength(self.name, font=self.f_name)
        nx, ny = (self.w - nw) / 2, 46 * k
        d.text((nx + 2 * k, ny + 2 * k), self.name, font=self.f_name, fill=PINK_DARK)
        d.text((nx, ny), self.name, font=self.f_name, fill=GOLD)
        r = (6.5 + 1.5 * math.sin(t * 6)) * k
        hy = ny + 18 * k
        gap = 2 * 8 * k + 5 * k  # nửa bề ngang tim lúc to nhất + khoảng hở
        heart(d, nx - gap, hy - r * 0.5, r, (255, 70, 110))
        heart(d, nx + nw + gap, hy - r * 0.5, r, (255, 70, 110))

    def render(self, t):
        dt = min(0.25, max(0.0, t - self._last_t))
        self._last_t = t
        img = self.bg.copy()
        d = ImageDraw.Draw(img)
        self._stars(d, t)
        self._particles(d, t, dt)
        for dx, by, c, ph in ((-128, 112, (255, 80, 90), 0.0), (-98, 138, (255, 205, 60), 1.4),
                              (98, 140, (90, 180, 255), 2.3), (128, 114, (190, 120, 255), 3.1)):
            self._balloon(d, dx, by, c, t, ph)
        self._cake(d, t)
        self._texts(d, t)
        return img


def play(device, seconds=30, name="Thúy Hèng", fps=15):
    """Phát cảnh trên `device` (luma, chế độ RGB). seconds=None/0 = chạy tới khi Ctrl+C. Trả về số khung hình đã vẽ."""
    scene = BirthdayScene(device.width, device.height, name=name)
    t0, frames = time.time(), 0
    try:
        while not seconds or time.time() - t0 < seconds:
            start = time.time()
            device.display(scene.render(start - t0))
            frames += 1
            time.sleep(max(0.0, 1 / fps - (time.time() - start)))
    except KeyboardInterrupt:
        pass
    return frames
