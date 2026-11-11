"""Chương trình chính trên Raspberry Pi 3: cổng vào/ra, rào chắn, LED, màn hình TFT/OLED, camera.

Chạy:  python main.py [--config config.yaml]
"""
import argparse
import json
import signal
import threading
import time
from pathlib import Path

from hardware import (load_config, make_barrier, make_camera, make_display, make_leds,
                      make_sensor)
from link import PiLink

LOT_CACHE = Path(__file__).resolve().parent / ".lot_cache.json"  # sơ đồ bãi lần trước, để mất server vẫn vẽ được


class Display:
    """Điều phối màn hình (TFT/OLED): màn hình 'dính' (hướng dẫn cho xe vào) > màn hình chờ; cổng ra chỉ hiện thoáng qua."""

    def __init__(self, oled):
        self.oled = oled
        self.lock = threading.RLock()
        self.free, self.total, self.online = 0, 12, False
        self.statuses = []      # trạng thái từng ô (free/occupied/reserved), cùng thứ tự với lot["slots"]
        self.lot = None         # sơ đồ bãi do server gửi (TFT vẽ lên màn hình)
        self.sticky = None      # hàm vẽ giữ nguyên cho tới khi bị gỡ
        self._token = 0
        try:
            self.lot = json.loads(LOT_CACHE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass

    def set_lot(self, lot):
        with self.lock:
            self.lot = lot
            try:
                LOT_CACHE.write_text(json.dumps(lot), encoding="utf-8")
            except OSError:
                pass
            self.refresh()

    def refresh(self):
        with self.lock:
            if not self.oled:
                return
            if self.sticky:
                self.sticky()
            else:
                self.oled.idle(self.free, self.total, self.online, lot=self.lot, statuses=self.statuses)

    def set_counts(self, free, total, statuses=None):
        with self.lock:
            statuses = list(statuses or [])
            changed = (free, total, statuses) != (self.free, self.total, self.statuses)
            self.free, self.total, self.statuses = free, total, statuses
            # đang hướng dẫn mà có sơ đồ thì vẽ lại để màu các ô luôn đúng
            if changed and (not self.sticky or self.lot):
                self.refresh()

    def set_sticky(self, fn):
        with self.lock:
            self.sticky = fn
            self._token += 1
            self.refresh()

    def clear_sticky(self):
        with self.lock:
            self.sticky = None
            self._token += 1
            self.refresh()

    def flash(self, fn, seconds=3.0):
        with self.lock:
            self._token += 1
            token = self._token
            if self.oled:
                fn()

        def back():
            time.sleep(seconds)
            with self.lock:
                if token == self._token:
                    self.refresh()
        threading.Thread(target=back, daemon=True).start()


class Gate(threading.Thread):
    """Máy trạng thái của một cổng: IDLE -> (xe tới) -> OPEN -> (xe đi khuất) -> CLOSING -> IDLE."""

    def __init__(self, name, sensor, barrier, link, display, cfg):
        super().__init__(daemon=True)
        self.name, self.sensor, self.barrier = name, sensor, barrier
        self.link, self.display, self.cfg = link, display, cfg
        self.clear_delay = cfg["gates"]["clear_delay_s"]
        # cảm biến trống ít nhất bấy nhiêu giây rồi lại có vật -> coi là XE MỚI (xe sau nối đuôi khi rào còn mở)
        self.new_car_gap = cfg["gates"].get("new_car_gap_s", 1.0)
        self.timeout = cfg["server"]["request_timeout_s"]
        self.offline_open = cfg.get("offline", {}).get("policy", "open") == "open"
        self.state = "IDLE"
        self.clear_since = None
        self.stop_flag = False

    def force_open(self):
        self.barrier.open()
        self.state = "OPEN"
        self.clear_since = None

    def force_close(self):
        if not self.sensor.present:
            self.barrier.close()
            self.state = "CLOSING"

    def run(self):
        while not self.stop_flag:
            time.sleep(0.1)
            try:
                self.step()
            except Exception as e:  # không để một lỗi làm chết cổng
                print(f"[gate {self.name}] lỗi: {e}")
                self.link.send({"type": "log", "level": "error", "message": f"Cổng {self.name}: {e}"})

    def step(self):
        present = self.sensor.present
        if self.state == "IDLE" and present:
            self.on_arrival()
        elif self.state == "DENIED":
            if self._clear_for(present, self.clear_delay):
                if self.barrier.state != "closed":   # bị từ chối lúc rào đang mở (xe nối đuôi) -> đóng lại
                    self.barrier.close()
                    self.state = "CLOSING"
                else:
                    self.display.clear_sticky()
                    self.state = "IDLE"
        elif self.state == "OPEN":
            if present and self._gap() >= self.new_car_gap:
                # xe trước đã đi khuất, xe sau tới khi rào chưa kịp đóng -> hỏi server cấp ô MỚI
                self.on_arrival()
            elif self._clear_for(present, self.clear_delay):
                self.barrier.close()
                self.state = "CLOSING"
        elif self.state == "CLOSING":
            if present:
                # xe sau tới khi rào đang đóng: mở lại ngay để không kẹp xe, rồi coi như một lượt xe mới
                self.barrier.open()
                self.state = "OPEN"
                self.on_arrival()
            elif self.barrier.state == "closed":
                self.state = "IDLE"
                if self.name == "in":
                    self.display.clear_sticky()

    def _gap(self):
        """Cảm biến đã trống liên tục bao nhiêu giây (0 nếu đang có vật)."""
        return time.time() - self.clear_since if self.clear_since else 0.0

    def _clear_for(self, present, seconds):
        if present:
            self.clear_since = None
            return False
        if self.clear_since is None:
            self.clear_since = time.time()
        return time.time() - self.clear_since >= seconds

    def on_arrival(self):
        self.clear_since = None
        print(f"[gate {self.name}] phát hiện xe ({self.sensor.distance:.0f} cm)")
        res = self.link.request(self.name, self.timeout)
        if self.name == "in":
            self._entry(res)
        else:
            self._exit(res)

    def _entry(self, res):
        if res is None:  # mất server -> chế độ offline
            self.display.online = False
            if self.offline_open:
                self.display.set_sticky(lambda: self.display.oled.message(["OFFLINE", "Moi xe vao"], big=True))
                self._open()
            else:
                self.display.set_sticky(lambda: self.display.oled.message(["OFFLINE", "Tam dung"], big=True))
                self.state = "DENIED"
            return
        self.display.online = True
        o = res["oled"]
        if res.get("allowed"):
            dp = self.display
            self.display.set_sticky(lambda: dp.oled.guidance(
                o["title"], o["lines"], o["arrow"], lot=dp.lot, statuses=dp.statuses,
                route=res.get("points"), target=res.get("slot"), steps=res.get("steps"), label=res.get("label"),
                plate=res.get("display")))
            self._open()
        else:
            self.display.set_sticky(lambda: self.display.oled.message([o["title"], *o["lines"]], big=True))
            self.state = "DENIED"

    def _exit(self, res):
        if res is None and not self.offline_open:
            self.display.flash(lambda: self.display.oled.message(["OFFLINE", "Tam dung"], big=True))
            self.state = "DENIED"
            return
        o = (res or {}).get("oled") or {"title": "Hen gap lai!", "lines": []}
        msg = [o["title"], *o["lines"]]
        if res is not None and not res.get("allowed", True):
            # biển số không đọc được / không khớp lượt vào -> giữ rào đóng, chờ xe lùi ra hoặc bảo vệ xử lý
            self.display.flash(lambda: self.display.oled.message(msg, big=True), 6)
            self.state = "DENIED"
            return
        self.display.flash(lambda: self.display.oled.message(msg, big=True), 5)
        self._open()

    def apply_result(self, res):
        """Kết quả do quản lý xử lý tay trên dashboard (nhập biển số khi camera đọc không được)."""
        self.clear_since = None
        if self.name == "in":
            self._entry(res)
        else:
            self._exit(res)

    def _open(self):
        self.barrier.open()
        self.state = "OPEN"


def cpu_temp():
    try:
        return round(int(open("/sys/class/thermal/thermal_zone0/temp").read()) / 1000, 1)
    except OSError:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    args = ap.parse_args()
    cfg = load_config(args.config)

    oled = leds = camera = None
    try:
        oled = make_display(cfg)
    except Exception as e:
        print("[!] Màn hình không khởi tạo được:", e)
    leds = make_leds(cfg)
    display = Display(oled)
    if oled:
        oled.message(["Dang khoi dong..."])
    leds.chase(0.05)

    try:
        camera = make_camera(cfg).start()
        print(f"[camera] stream tại http://<ip-pi>:{cfg['camera']['port']}/stream.mjpg")
    except Exception as e:
        print("[!] Camera không chạy:", e)

    srv = cfg["server"]
    link = PiLink(srv["url"], srv["key"], srv.get("reconnect_s", 3), fingerprint=srv.get("fingerprint"),
                  device=srv.get("device", "raspberry-pi-3"))
    link.hello = {"type": "hello", "device": "raspberry-pi-3", "version": "1.0",
                  "barrier": "servo", "stream_port": cfg["camera"]["port"] if camera else None}

    sensors = {g: make_sensor(cfg, g).start() for g in ("in", "out")}
    barriers = {g: make_barrier(cfg, g) for g in ("in", "out")}
    gates = {g: Gate(g, sensors[g], barriers[g], link, display, cfg) for g in ("in", "out")}

    def on_state(msg):
        leds.apply_slots(msg["slots"])
        display.online = True
        display.set_counts(msg["free"], msg["total"], msg["slots"])

    def on_layout(msg):
        if msg.get("lot"):
            display.set_lot(msg["lot"])
            print(f"[pi] nhận sơ đồ bãi: {len(msg['lot'].get('slots', []))} ô")

    def on_command(msg):
        cmd, gate = msg.get("cmd"), msg.get("gate")
        if cmd == "open_barrier" and gate in gates:
            gates[gate].force_open()
        elif cmd == "close_barrier" and gate in gates:
            gates[gate].force_close()
        elif cmd == "gate_result" and gate in gates and isinstance(msg.get("result"), dict):
            gates[gate].apply_result(msg["result"])
        elif cmd == "led_test":
            threading.Thread(target=leds.chase, daemon=True).start()

    link.on_state, link.on_layout, link.on_command = on_state, on_layout, on_command
    link.start()
    for g in gates.values():
        g.start()
    display.refresh()

    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *a: stop.set())
    signal.signal(signal.SIGTERM, lambda *a: stop.set())
    print("[pi] đang chạy. Ctrl+C để dừng.")
    last_conn = None
    while not stop.wait(2):
        link.send({"type": "telemetry", "data": {
            "dist_in_cm": round(sensors["in"].distance, 1), "dist_out_cm": round(sensors["out"].distance, 1),
            "barrier_in": barriers["in"].state, "barrier_out": barriers["out"].state,
            "gate_in": gates["in"].state, "gate_out": gates["out"].state,
            "cam_fps": camera.stats()["fps"] if camera else 0, "cpu_temp": cpu_temp()}})
        if link.connected != last_conn:
            last_conn = link.connected
            display.online = link.connected
            display.refresh()

    print("[pi] đang tắt...")
    for g in gates.values():
        g.stop_flag = True
    for b in barriers.values():
        b.close()
        b.wait_idle()
        b.cleanup()
    for s in sensors.values():
        s.stop()
    leds.cleanup()
    if oled:
        oled.clear()
    if camera:
        camera.stop()
    link.stop()


if __name__ == "__main__":
    main()
