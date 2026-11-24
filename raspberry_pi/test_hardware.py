"""Test từng linh kiện trên Pi, KHÔNG cần server. Dùng đúng driver + số chân trong config.yaml.

Chạy (dừng main.py / service parking trước, nếu không sẽ tranh GPIO):
    python test_hardware.py            # menu chọn linh kiện
    python test_hardware.py sensor     # hoặc: servo | led | tft | camera | all
"""
import argparse
import sys
import time

from hardware import load_config, make_barrier, make_camera, make_leds, make_sensor, make_tft

LED_NAMES = ["A1", "A2", "A3", "B1", "B2", "B3", "C1", "C2", "C3", "C4"]


def test_sensor(cfg):
    """In khoảng cách 2 cảm biến liên tục; đưa tay lại gần để thấy 'CÓ XE'."""
    sensors = {g: make_sensor(cfg, g).start() for g in ("in", "out")}
    print(f"Ngưỡng có xe: vào {cfg['gates']['in']['trigger_cm']} cm, ra {cfg['gates']['out']['trigger_cm']} cm."
          " Ctrl+C để dừng.")
    try:
        while True:
            parts = [f"{g.upper():>3}: {s.distance:6.1f} cm {'CÓ XE' if s.present else '     '}"
                     for g, s in sensors.items()]
            print("   ".join(parts), end="\r", flush=True)
            time.sleep(0.2)
    except KeyboardInterrupt:
        print()
    finally:
        for s in sensors.values():
            s.stop()


def test_servo(cfg):
    """Mở / đóng từng rào 2 lần."""
    for g in ("in", "out"):
        b = make_barrier(cfg, g)
        print(f"Rào {g} (GPIO {cfg['barrier'][f'{g}_pin']}): "
              f"đóng {b.closed_angle}° / mở {b.open_angle}°")
        try:
            for _ in range(2):
                print("  mở...")
                b.open()
                b.wait_idle()
                time.sleep(1)
                print("  đóng...")
                b.close()
                b.wait_idle()
                time.sleep(1)
        finally:
            b.cleanup()


def test_led(cfg):
    """Sáng lần lượt từng đèn (có in tên ô), rồi bật tất cả, rồi tắt."""
    leds = make_leds(cfg)
    pins = cfg["leds"]["pins"]
    try:
        leds._override = True          # tạm dừng luồng nhấp nháy nền
        leds._all(False)
        for i, led in enumerate(leds.leds):
            name = LED_NAMES[i] if i < len(LED_NAMES) else f"#{i + 1}"
            print(f"  {name}: GPIO {pins[i]}")
            led.on()
            time.sleep(0.6)
            led.off()
        print("  bật tất cả 2 giây")
        leds._all(True)
        time.sleep(2)
        leds._all(False)
    finally:
        leds.cleanup()


def test_tft(cfg):
    """Hiện vài màn mẫu: chữ, màn chờ, hướng dẫn."""
    tft = make_tft(cfg)
    try:
        print("  màn thông báo")
        tft.message(["TEST TFT", "Tiếng Việt: ăn ơ ư đ"])
        time.sleep(3)
        print("  màn chờ (7/10 ô trống)")
        tft.idle(7, 10, online=True)
        time.sleep(3)
        print("  màn hướng dẫn")
        tft.guidance("Ô B2", ["Đi thẳng 1 ngã", "Rẽ phải"], "right", plate="51A-123.45")
        time.sleep(3)
    finally:
        tft.clear()


def test_camera(cfg):
    """Bật stream MJPEG, xem từ máy tính ở http://<ip-pi>:<port>/stream.mjpg."""
    cam = make_camera(cfg).start()
    print(f"  stream: http://<ip-pi>:{cfg['camera']['port']}/stream.mjpg  (Ctrl+C để dừng)")
    try:
        while True:
            time.sleep(2)
            print(f"  fps: {cam.stats()['fps']}", end="\r", flush=True)
    except KeyboardInterrupt:
        print()
    finally:
        cam.stop()


TESTS = {"sensor": test_sensor, "servo": test_servo, "led": test_led, "tft": test_tft, "camera": test_camera}


def run(name, cfg):
    print(f"\n=== {name} ===")
    try:
        TESTS[name](cfg)
        print(f"=== {name}: xong ===")
    except KeyboardInterrupt:
        print(f"\n=== {name}: dừng ===")
    except Exception as e:
        print(f"[!] {name} lỗi: {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("part", nargs="?", choices=[*TESTS, "all"])
    ap.add_argument("--config", default=None)
    args = ap.parse_args()
    cfg = load_config(args.config)

    if args.part == "all":
        for n in ("led", "servo", "tft", "sensor", "camera"):
            run(n, cfg)
        return
    if args.part:
        run(args.part, cfg)
        return
    keys = list(TESTS)
    while True:
        print("\n" + "  ".join(f"{i + 1}={k}" for i, k in enumerate(keys)) + "  q=thoát")
        c = input("Chọn: ").strip().lower()
        if c in ("q", ""):
            return
        if c.isdigit() and 1 <= int(c) <= len(keys):
            run(keys[int(c) - 1], cfg)
        elif c in TESTS:
            run(c, cfg)


if __name__ == "__main__":
    sys.exit(main())
