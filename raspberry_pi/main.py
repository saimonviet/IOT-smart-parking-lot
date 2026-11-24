"""Chương trình chính trên Raspberry Pi 3: 2 cổng (siêu âm + rào servo), đèn LED từng ô, màn TFT, stream camera bãi.

Mọi quyết định (ô nào trống, cho xe vào/ra, đọc biển số) do pc_server đưa ra qua kênh WebSocket bảo mật.

Chạy:  python main.py [--config config.yaml]
"""
import argparse
import signal
import threading

from core.gate import Gate
from core.link import PiLink
from core.screen import Screen
from hardware import load_config, make_barrier, make_camera, make_leds, make_sensor, make_tft

GATES = ("in", "out")


def cpu_temp():
    try:
        return round(int(open("/sys/class/thermal/thermal_zone0/temp").read()) / 1000, 1)
    except OSError:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    cfg = load_config(ap.parse_args().config)

    # ---- phần cứng: màn hình và camera lỗi thì vẫn chạy tiếp, cổng + đèn là bắt buộc
    tft = camera = None
    try:
        tft = make_tft(cfg)
        tft.message(["Đang khởi động..."])
    except Exception as e:
        print("[!] Màn hình TFT không khởi tạo được:", e)
    screen = Screen(tft)
    leds = make_leds(cfg)
    leds.chase(0.05)   # đèn chạy một vòng lúc khởi động = báo đã cắm đúng
    try:
        camera = make_camera(cfg).start()
        print(f"[camera] stream tại http://<ip-pi>:{cfg['camera']['port']}/stream.mjpg")
    except Exception as e:
        print("[!] Camera không chạy:", e)
    sensors = {g: make_sensor(cfg, g).start() for g in GATES}
    barriers = {g: make_barrier(cfg, g) for g in GATES}

    # ---- kết nối server
    srv = cfg["server"]
    link = PiLink(srv["url"], srv["key"], srv.get("reconnect_s", 3), fingerprint=srv.get("fingerprint"),
                  device=srv.get("device", "raspberry-pi-3"))
    link.hello = {"type": "hello", "device": "raspberry-pi-3", "version": "2.0", "barrier": "servo",
                  "stream_port": cfg["camera"]["port"] if camera else None}
    gates = {g: Gate(g, sensors[g], barriers[g], link, screen, cfg) for g in GATES}

    def on_state(msg):       # trạng thái các ô -> đèn + màn chờ
        leds.apply_slots(msg["slots"])
        screen.set_online(True)
        screen.set_counts(msg["free"], msg["total"], msg["slots"])

    def on_layout(msg):      # sơ đồ bãi -> màn hình vẽ đường đi
        if msg.get("lot"):
            screen.set_lot(msg["lot"])
            print(f"[pi] nhận sơ đồ bãi: {len(msg['lot'].get('slots', []))} ô")

    def on_command(msg):     # lệnh từ dashboard
        cmd, gate = msg.get("cmd"), msg.get("gate")
        if gate not in gates:
            return
        if cmd == "open_barrier":
            gates[gate].force_open()
        elif cmd == "close_barrier":
            gates[gate].force_close()
        elif cmd == "gate_result" and isinstance(msg.get("result"), dict):
            gates[gate].apply_result(msg["result"])

    link.on_state, link.on_layout, link.on_command = on_state, on_layout, on_command
    link.start()
    for g in gates.values():
        g.start()
    screen.refresh()

    # ---- vòng lặp chính: gửi số liệu mỗi 2 giây, theo dõi mất/có kết nối
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *a: stop.set())
    signal.signal(signal.SIGTERM, lambda *a: stop.set())
    print("[pi] đang chạy. Ctrl+C để dừng.")
    while not stop.wait(2):
        link.send({"type": "telemetry", "data": {
            "dist_in_cm": round(sensors["in"].distance, 1), "dist_out_cm": round(sensors["out"].distance, 1),
            "barrier_in": barriers["in"].state, "barrier_out": barriers["out"].state,
            "gate_in": gates["in"].state, "gate_out": gates["out"].state,
            "cam_fps": camera.stats()["fps"] if camera else 0, "cpu_temp": cpu_temp()}})
        screen.set_online(link.connected)

    # ---- tắt: đóng rào, nhả GPIO
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
    if tft:
        tft.clear()
    if camera:
        camera.stop()
    link.stop()


if __name__ == "__main__":
    main()
