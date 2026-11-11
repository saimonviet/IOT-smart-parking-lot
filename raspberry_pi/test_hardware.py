"""Kiểm tra từng linh kiện của Raspberry Pi — chạy TRƯỚC khi chạy main.py.

    python test_hardware.py            # menu tương tác
    python test_hardware.py leds       # chạy một bài test
    python test_hardware.py all        # chạy lần lượt tất cả và in bảng kết quả

Bài test: leds | ledson | ultrasonic | barrier | servo | near | oled | birthday | camera | all
  birthday = màn hình động "Happy Birthday Thúy Hèng": bánh kem, nến, bóng bay, tim, confetti (30s)
  servo  = quét góc 0→180→0° rồi mở/đóng từng servo
  ledson = bật sáng tất cả đèn, giữ tới khi bạn nhấn Enter / Ctrl+C
  near   = "đến gần thì mở rào": đưa tay/vật lại gần cảm biến thì rào tương ứng mở, bỏ ra thì đóng
"""
import argparse
import statistics
import sys
import time

from hardware import (load_config, make_barrier, make_camera, make_display, make_leds,
                      make_sensor)

OK, FAIL = "\033[92mPASS\033[0m", "\033[91mFAIL\033[0m"


def ask(prompt):
    return input(f"   ? {prompt} [y/n]: ").strip().lower().startswith("y")


# ------------------------------------------------------------------ LED
def test_leds(cfg):
    leds = make_leds(cfg)
    try:
        n = len(leds)
        print(f"   Chạy đèn lần lượt 1 → {n} (mỗi đèn 0.3s)...")
        leds.chase(0.3)
        print(f"   Chạy ngược {n} → 1...")
        leds.chase(0.15, reverse=True)
        print("   Tất cả sáng 2s, rồi nhấp nháy 3 lần...")
        leds.hold_override(True)
        leds.all(True)
        time.sleep(2)
        for _ in range(3):
            leds.all(False); time.sleep(0.25); leds.all(True); time.sleep(0.25)
        leds.all(False)
        leds.hold_override(False)
        return ask(f"Cả {n} đèn đã sáng đúng thứ tự 1→{n} chứ?"), "người dùng xác nhận"
    finally:
        leds.cleanup()


def test_ledson(cfg):
    """Bật sáng toàn bộ đèn và giữ nguyên cho tới khi người dùng dừng (Enter hoặc Ctrl+C)."""
    leds = make_leds(cfg)
    labels = ["A1", "A2", "A3", "B1", "B2", "B3", "C1", "C2", "C3", "C4"]
    try:
        leds.hold_override(True)
        leds.all(True)
        print("   Đang bật TẤT CẢ đèn:")
        for lb, p in zip(labels, cfg["leds"]["pins"]):
            print(f"     {lb}: GPIO {p}")
        try:
            input("   Kiểm tra từng đèn, nhấn Enter (hoặc Ctrl+C) để tắt...")
        except (KeyboardInterrupt, EOFError):
            print()
        return ask("Tất cả đèn đều sáng chứ?"), "người dùng xác nhận"
    finally:
        leds.cleanup()


# ------------------------------------------------------------------ siêu âm
def test_ultrasonic(cfg, seconds=10):
    sensors = {g: make_sensor(cfg, g) for g in ("in", "out")}
    try:
        print(f"   Đo {seconds}s. Hãy đưa tay lại gần/ra xa từng cảm biến (ngưỡng "
              f"{cfg['gates']['in']['trigger_cm']} cm).")
        data = {g: [] for g in sensors}
        t0 = time.time()
        while time.time() - t0 < seconds:
            line = []
            for g, s in sensors.items():
                d = s.us.read_median(3)
                data[g].append(d)
                bar = "█" * min(int(d / 5), 30) if d < 150 else "(xa/không thấy)"
                line.append(f"{g.upper():>3}: {d:6.1f} cm {bar:<30}")
            print("   " + " | ".join(line), end="\r")
            time.sleep(0.1)
        print()
        ok, detail = True, []
        for g, vals in data.items():
            valid = [v for v in vals if v < 400]
            if not valid:
                ok = False
                detail.append(f"{g}: không đọc được (kiểm tra dây TRIG/ECHO + cầu chia áp)")
            else:
                detail.append(f"{g}: {len(valid)}/{len(vals)} mẫu hợp lệ, nhỏ nhất {min(valid):.0f}cm, "
                              f"σ={statistics.pstdev(valid):.1f}")
        return ok, "; ".join(detail)
    finally:
        for s in sensors.values():
            s.us.close()


# ------------------------------------------------------------------ rào chắn (không cần cảm biến)
def test_barrier(cfg):
    ok_all = True
    for gate in ("in", "out"):
        b = make_barrier(cfg, gate)
        try:
            print(f"   Rào {'VÀO' if gate == 'in' else 'RA'}: mở...")
            b.open(); b.wait_idle(15)
            time.sleep(1)
            print("   ...đóng.")
            b.close(); b.wait_idle(15)
            ok_all &= ask(f"Rào {gate.upper()} đã mở rồi đóng đúng chiều chứ? (sai góc: chỉnh barrier.{gate}_open_angle / {gate}_closed_angle)")
        finally:
            b.cleanup()
    return ok_all, "người dùng xác nhận"


# ------------------------------------------------------------------ servo: quét góc
def test_servo(cfg):
    """Quét toàn hành trình rồi mở/đóng để chỉnh góc."""
    from hardware import barrier_angles
    from hardware.servo import ServoBarrier
    s = cfg["barrier"]
    ok_all = True
    for gate in ("in", "out"):
        pin = s[f"{gate}_pin"]
        closed, opened = barrier_angles(cfg, gate)
        print(f"   Servo {'VÀO' if gate == 'in' else 'RA'} (GPIO {pin})")
        b = ServoBarrier(pin, closed, opened)
        try:
            print("   Quét góc 0° → 90° → 0°...")
            for a in list(range(0, 91, 15)) + list(range(75, -1, -15)):
                b.servo.angle = a
                print(f"     {a:>3}°", end="\r")
                time.sleep(0.4)
            print()
            for _ in range(2):
                print(f"   Mở ({opened}°)..."); b.open(); b.wait_idle(); time.sleep(1)
                print(f"   Đóng ({closed}°)..."); b.close(); b.wait_idle(); time.sleep(1)
            ok_all &= ask(f"Servo {gate.upper()} quay đủ góc và mở/đóng đúng chứ? "
                          f"(sai góc: chỉnh barrier.{gate}_open_angle / {gate}_closed_angle)")
        finally:
            b.cleanup()
    return ok_all, "người dùng xác nhận"


# ------------------------------------------------------------------ đến gần thì mở rào
def test_near(cfg, seconds=40):
    sensors = {g: make_sensor(cfg, g).start() for g in ("in", "out")}
    barriers = {g: make_barrier(cfg, g) for g in ("in", "out")}
    clear_delay = cfg["gates"]["clear_delay_s"]
    opened = {"in": False, "out": False}
    last_seen = {"in": 0, "out": 0}
    try:
        print(f"   Trong {seconds}s: đưa vật lại gần cảm biến thì rào mở, bỏ ra {clear_delay}s thì rào đóng. (Ctrl+C để dừng)")
        t0 = time.time()
        try:
            while time.time() - t0 < seconds:
                for g, s in sensors.items():
                    if s.present:
                        last_seen[g] = time.time()
                        if barriers[g].state in ("closed", "closing"):
                            print(f"\n   [{g}] phát hiện {s.distance:.0f} cm -> MỞ rào")
                            barriers[g].open(); opened[g] = True
                    elif barriers[g].state in ("open", "opening") and time.time() - last_seen[g] > clear_delay:
                        print(f"\n   [{g}] không còn vật -> ĐÓNG rào")
                        barriers[g].close()
                print(f"   in: {sensors['in'].distance:6.1f} cm [{barriers['in'].state:<8}]   "
                      f"out: {sensors['out'].distance:6.1f} cm [{barriers['out'].state:<8}]", end="\r")
                time.sleep(0.1)
        except KeyboardInterrupt:
            pass
        print()
        return all(opened.values()), f"rào đã mở: vào={opened['in']}, ra={opened['out']}"
    finally:
        for b in barriers.values():
            b.close(); b.wait_idle(15); b.cleanup()
        for s in sensors.values():
            s.stop()


# ------------------------------------------------------------------ màn hình (TFT hoặc OLED)
# sơ đồ mẫu 6 ô (cùng dạng server gửi) để thử màn sơ đồ mà không cần server
DEMO_LOT = {
    "width": 320, "height": 300, "entrance": "E", "exit": "X",
    "nodes": {"E": [300, 40], "T": [60, 40], "M1": [60, 120], "M2": [60, 200], "M3": [60, 280], "X": [300, 280]},
    "edges": [["E", "T"], ["T", "M1"], ["M1", "M2"], ["M2", "M3"], ["M3", "X"]],
    "slots": [{"id": i + 1, "label": lb, "box": [100 + (i % 2) * 100, 80 + (i // 2) * 80, 100, 80, 0]}
              for i, lb in enumerate(["A1", "B1", "A2", "B2", "A3", "B3"])],
}
DEMO_ST = ["occupied", "free", "free", "reserved", "occupied", "free"]


def test_oled(cfg):
    try:
        o = make_display(cfg)
    except Exception as e:
        hint = ("TFT: kiểm tra `ls /dev/spidev0.0` (cần dtoverlay=spi0-1cs trong config.txt), dây DC/RST/CS"
                if cfg.get("display", "tft") == "tft" else
                "OLED: bật I2C (sudo raspi-config nonint do_i2c 0), kiểm tra `i2cdetect -y 1` thấy 3c")
        return False, f"không khởi tạo được màn hình: {e} ({hint})"
    steps = [
        ("Hình thử", lambda: o.test_pattern()),
        ("Màn hình chờ", lambda: o.idle(7, 12)),
        ("Hướng dẫn: ô A2", lambda: o.guidance("O A2", ["Re TRAI", "Thang 1, Re PHAI"], "left")),
        ("Hướng dẫn: ô C3", lambda: o.guidance("O C3", ["Thang 1, Re TRAI", "Thang 2, Re PHAI"], "left")),
        ("Mũi tên phải / thẳng", lambda: o.guidance("O B1", ["Re PHAI", "Di thang"], "right")),
        ("Sơ đồ bãi (màn chờ)", lambda: o.idle(4, 6, lot=DEMO_LOT, statuses=DEMO_ST)),
        ("Sơ đồ + đường đi tới ô A2", lambda: o.guidance(
            "O A2", ["Re TRAI", "Thang 1, Re TRAI"], "left", lot=DEMO_LOT, statuses=DEMO_ST, target=3, label="A2",
            route=[[300, 40], [60, 40], [60, 200], [150, 200]],
            steps=[{"straight": 0, "turn": "left"}, {"straight": 1, "turn": "left"}])),
        ("Bãi đầy", lambda: o.message(["BAI DA DAY", "Xin quay lai"], big=True)),
        ("Chữ tiếng Việt (OLED tự bỏ dấu)", lambda: o.message(["Chào mừng", "Đỗ xe thông minh"])),
    ]
    try:
        for name, fn in steps:
            print(f"   Màn hình: {name}")
            fn()
            time.sleep(2)
        o.clear()
        return ask("Các màn hình hiển thị rõ, không vỡ hình, mũi tên đúng hướng?"), "người dùng xác nhận"
    finally:
        o.clear()


# ------------------------------------------------------------------ màn hình chúc mừng sinh nhật
def test_birthday(cfg, seconds=30, name="Thúy Hèng"):
    try:
        o = make_display(cfg)
    except Exception as e:
        return False, f"không khởi tạo được màn hình: {e}"
    if getattr(o.device, "mode", "1") != "RGB":  # OLED đen trắng: chỉ hiện chữ (tự bỏ dấu)
        o.message(["Happy Birthday", name])
        time.sleep(5)
        return ask("Màn hình hiện lời chúc rõ chứ?"), "OLED: chỉ chữ"
    from hardware.birthday import play
    print(f"   Happy Birthday {name}! Chạy hiệu ứng {seconds}s (Ctrl+C để dừng sớm)...")
    t0 = time.time()
    frames = play(o.device, seconds, name=name)
    fps = frames / max(0.1, time.time() - t0)
    o.device.persist = True  # giữ khung hình cuối trên màn sau khi thoát
    return ask("Chữ, bánh kem, nến, bóng bay hiển thị đẹp chứ?"), f"{frames} khung hình, ~{fps:.1f} fps"


# ------------------------------------------------------------------ camera
def test_camera(cfg, seconds=15):
    cam = make_camera(cfg)
    try:
        cam.start()
    except Exception as e:
        return False, f"không bật được camera: {e}"
    try:
        target = cfg["camera"]["fps"]
        print(f"   Stream tại http://<ip-pi>:{cfg['camera']['port']}/stream.mjpg — mở trên máy tính để xem.")
        print(f"   Theo dõi {seconds}s (mục tiêu {target} fps)...")
        worst_gap, fps_list = 0.0, []
        for i in range(seconds):
            time.sleep(1)
            st = cam.stats(3)
            if st["max_gap"] is not None:
                worst_gap = max(worst_gap, st["max_gap"])
                fps_list.append(st["fps"])
            print(f"   t={i+1:>2}s  fps={st['fps']:>5}  khoảng trống lớn nhất={st['max_gap']}s", end="\r")
        print()
        frame = cam.snapshot()
        if frame:
            open("camera_test.jpg", "wb").write(frame)
            print("   Đã lưu ảnh mẫu: camera_test.jpg (xem hình có nét, đúng chiều, thấy toàn bộ bãi)")
        avg = statistics.mean(fps_list) if fps_list else 0
        stable = avg >= 0.8 * target and worst_gap < 1.0 and frame is not None
        return stable, (f"fps TB={avg:.1f}/{target}, khoảng trống lớn nhất={worst_gap:.2f}s "
                        f"(ổn định khi fps≥80% mục tiêu và không đứng hình >1s)")
    finally:
        cam.stop()


TESTS = {"leds": test_leds, "ledson": test_ledson, "ultrasonic": test_ultrasonic, "barrier": test_barrier, "servo": test_servo,
         "near": test_near, "oled": test_oled, "birthday": test_birthday, "camera": test_camera}
TITLES = {"leds": "Đèn LED các ô", "ledson": "Bật sáng tất cả đèn (tự dừng)", "ultrasonic": "2 cảm biến siêu âm", "barrier": "2 rào chắn (mở/đóng)",
          "servo": "Servo SG90 (quét góc + mở/đóng)",
          "near": "Đến gần thì mở rào", "oled": "Màn hình TFT/OLED", "birthday": "Màn hình Happy Birthday 🎂",
          "camera": "Camera + độ ổn định"}


def all_tests(cfg):
    return [n for n in TESTS if n not in ("ledson", "birthday")]  # 2 bài này chạy riêng


def run(name, cfg, results):
    print(f"\n=== {TITLES[name]} ===")
    try:
        ok, detail = TESTS[name](cfg)
    except KeyboardInterrupt:
        ok, detail = False, "đã dừng"
    except Exception as e:
        ok, detail = False, f"lỗi: {type(e).__name__}: {e}"
    results.append((TITLES[name], ok, detail))
    print(f"   -> {OK if ok else FAIL}  {detail}")


def summary(results):
    print("\n================ KẾT QUẢ ================")
    for title, ok, detail in results:
        print(f" {OK if ok else FAIL}  {title:<24} {detail}")


def menu(cfg):
    names = list(TESTS)
    results = []
    while True:
        print("\n--- KIỂM TRA LINH KIỆN ---")
        for i, n in enumerate(names, 1):
            print(f" {i}. {TITLES[n]}")
        print(" a. Chạy tất cả   q. Thoát")
        c = input("Chọn: ").strip().lower()
        if c == "q":
            break
        if c == "a":
            for n in all_tests(cfg):
                run(n, cfg, results)
        elif c.isdigit() and 1 <= int(c) <= len(names):
            run(names[int(c) - 1], cfg, results)
        if results:
            summary(results)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("test", nargs="?", choices=[*TESTS, "all"])
    ap.add_argument("--config", default=None)
    args = ap.parse_args()
    cfg = load_config(args.config)
    if not args.test:
        return menu(cfg)
    results = []
    for n in (all_tests(cfg) if args.test == "all" else [args.test]):
        run(n, cfg, results)
    summary(results)
    sys.exit(0 if all(r[1] for r in results) else 1)


if __name__ == "__main__":
    main()
