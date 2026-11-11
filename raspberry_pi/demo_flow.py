"""Demo luồng xe ra/vào, KHÔNG cần server/model.

- Cảm biến siêu âm cổng vào/ra đo < --cm (mặc định 10cm) -> mở rào cổng đó.
- Sau khi mở, chờ tới khi đo > --cm liên tục --clear giây (mặc định 2s) -> đóng rào;
  có xe chen vào lúc đang đóng -> mở lại.
- 10 đèn LED sáng tất cả (chưa có model nhận diện ô).
- Màn hình hiện "Xin chào" + số xe trong bãi (đếm theo lượt vào/ra).

Chạy:  python demo_flow.py [--cm 10] [--clear 2]
"""
import argparse
import signal
import threading
import time

from hardware import load_config, make_barrier, make_display, make_leds, make_sensor


class Screen:
    """Màn hình (TFT/OLED): 'Xin chào' cỡ lớn (DejaVu có đủ dấu tiếng Việt) + dòng trạng thái nhỏ. Không có màn thì bỏ qua."""

    def __init__(self, oled):
        self.oled = oled
        self.lock = threading.Lock()
        if oled:
            from hardware.oled import _font
            self.k = oled.h / 64                     # bố cục gốc cho 128x64, màn TFT lớn hơn thì phóng theo chiều cao
            self.f_big, self.f_small = _font(round(22 * self.k)), _font(round(11 * self.k))

    def show(self, status):
        if not self.oled:
            return
        from luma.core.render import canvas
        try:
            with self.lock, canvas(self.oled.device) as d:
                w, k = self.oled.w, self.k
                t = "Xin chào"
                d.text(((w - d.textlength(t, font=self.f_big)) / 2, 8 * k), t, font=self.f_big, fill="white")
                d.line((0, 40 * k, w, 40 * k), fill="white")
                d.text(((w - d.textlength(status, font=self.f_small)) / 2, 46 * k), status, font=self.f_small, fill="white")
        except Exception as e:  # màn hình lỏng dây giữa chừng -> không làm dừng demo
            print("[!] Màn hình lỗi:", e)


class DemoGate:
    """IDLE -> (đo < cm) -> OPEN -> (đo > cm liên tục clear_s giây) -> CLOSING -> IDLE."""

    def __init__(self, name, sensor, barrier, cm, clear_s, on_pass):
        self.name, self.sensor, self.barrier = name, sensor, barrier
        self.cm, self.clear_s, self.on_pass = cm, clear_s, on_pass
        self.state = "IDLE"
        self.clear_since = None
        self.label = "VÀO" if name == "in" else "RA"

    def step(self):
        near = self.sensor.distance < self.cm
        if self.state == "IDLE" and near and self.sensor.present:  # present: đã xác nhận 3 lần đo, chống nhiễu
            print(f"[{self.label}] {self.sensor.distance:.1f} cm < {self.cm:g} cm -> mở rào")
            self.barrier.open()
            self.state, self.clear_since = "OPEN", None
            self.on_pass(self.name)
        elif self.state == "OPEN":
            if near:  # xe vẫn còn -> đếm lại từ đầu
                self.clear_since = None
            elif self.clear_since is None:
                print(f"[{self.label}] {self.sensor.distance:.1f} cm > {self.cm:g} cm -> {self.clear_s:g}s nữa đóng rào")
                self.clear_since = time.time()
            elif time.time() - self.clear_since >= self.clear_s:
                print(f"[{self.label}] xe đã qua -> đóng rào")
                self.barrier.close()
                self.state = "CLOSING"
        elif self.state == "CLOSING":
            if near:  # không đóng rào lên xe
                print(f"[{self.label}] có xe chen vào -> mở lại")
                self.barrier.open()
                self.state, self.clear_since = "OPEN", None
            elif self.barrier.state == "closed":
                self.state = "IDLE"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--cm", type=float, default=10.0, help="dưới mức này thì mở rào (cm)")
    ap.add_argument("--clear", type=float, default=2.0, help="đo vượt --cm bao lâu thì đóng rào (giây)")
    args = ap.parse_args()
    cfg = load_config(args.config)
    for g in ("in", "out"):
        cfg["gates"][g]["trigger_cm"] = args.cm

    oled = None
    try:
        oled = make_display(cfg)
    except Exception as e:
        print("[!] Màn hình không khởi tạo được:", e)
    screen = Screen(oled)

    leds = make_leds(cfg)
    leds.apply_slots(["free"] * len(leds))  # sáng tất cả

    sensors = {g: make_sensor(cfg, g).start() for g in ("in", "out")}
    barriers = {g: make_barrier(cfg, g) for g in ("in", "out")}

    cars = 0

    def on_pass(gate):
        nonlocal cars
        cars = cars + 1 if gate == "in" else max(0, cars - 1)
        print(f"    -> trong bãi: {cars} xe")
        screen.show(f"{'Mời vào' if gate == 'in' else 'Hẹn gặp lại'} - {cars} xe")

    gates = {g: DemoGate(g, sensors[g], barriers[g], args.cm, args.clear, on_pass) for g in ("in", "out")}
    screen.show("Sẵn sàng - 0 xe")

    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *a: stop.set())
    signal.signal(signal.SIGTERM, lambda *a: stop.set())
    print(f"[demo] chạy. Đưa vật lại gần cảm biến < {args.cm:g} cm để mở rào. Ctrl+C để dừng.")

    try:
        last_print = 0
        while not stop.wait(0.1):
            for g in gates.values():
                g.step()
            if time.time() - last_print >= 1:
                last_print = time.time()
                print(f"  khoảng cách  vào: {sensors['in'].distance:6.1f} cm [{gates['in'].state:7}]"
                      f"   ra: {sensors['out'].distance:6.1f} cm [{gates['out'].state:7}]")
    finally:
        print("[demo] đang tắt...")
        for b in barriers.values():
            b.close()
            b.wait_idle()
            b.cleanup()
        for s in sensors.values():
            s.stop()
        leds.cleanup()
        if oled:
            oled.clear()


if __name__ == "__main__":
    main()
