"""Khởi tạo linh kiện từ config.yaml. Mỗi linh kiện tạo độc lập để lỗi một chỗ không kéo theo chỗ khác."""
from pathlib import Path

import yaml

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config.yaml"


def load_config(path=None):
    with open(path or DEFAULT_CONFIG, encoding="utf-8") as f:
        return yaml.safe_load(f)


def make_sensor(cfg, gate):
    from .ultrasonic import GateSensor
    g = cfg["gates"][gate]
    return GateSensor(g["trig"], g["echo"], g["trigger_cm"], cfg["gates"].get("sample_hz", 10), name=gate)


def make_barrier(cfg, gate):
    from .servo import ServoBarrier
    return ServoBarrier(cfg["barrier"][f"{gate}_pin"], *barrier_angles(cfg, gate))


def barrier_angles(cfg, gate):
    """(góc đóng, góc mở) của từng cổng: ưu tiên in_/out_closed_angle, không có thì dùng closed_angle/open_angle chung."""
    b = cfg["barrier"]
    return (b.get(f"{gate}_closed_angle", b.get("closed_angle", 0)),
            b.get(f"{gate}_open_angle", b.get("open_angle", 90)))


def make_leds(cfg):
    from .leds import LedBank
    return LedBank(cfg["leds"]["pins"], cfg["leds"].get("active_high", True))


def make_display(cfg):
    """Màn hình theo `display` trong config: tft (mặc định) hoặc oled. Hai lớp có cùng các hàm idle/guidance/message."""
    if cfg.get("display", "tft") == "tft":
        from .tft import Tft
        return Tft(**cfg["tft"])
    from .oled import Oled
    o = cfg["oled"]
    return Oled(o["port"], o["address"], o["width"], o["height"], o.get("rotate", 0), o.get("driver", "ssd1306"))


def make_camera(cfg):
    from .camera import CameraStreamer
    c = cfg["camera"]
    return CameraStreamer(c["width"], c["height"], c["fps"], c["port"], c.get("hflip", False), c.get("vflip", False))
