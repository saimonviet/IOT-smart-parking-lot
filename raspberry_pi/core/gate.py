"""Máy trạng thái của một cổng (vào hoặc ra).

IDLE --(siêu âm thấy xe)--> hỏi server --cho phép--> OPEN --(xe đi khuất clear_delay_s)--> CLOSING --> IDLE
                                       --từ chối---> DENIED --(xe lùi đi)--> IDLE

- Rào không bao giờ đóng khi cảm biến còn thấy xe; xe chen vào lúc đang đóng -> mở lại và coi là lượt mới.
- Xe sau nối đuôi khi rào còn mở (cảm biến trống >= new_car_gap_s rồi lại có xe) -> hỏi server cấp lượt mới.
- Mất server: theo offline.policy (open = vẫn mở rào, deny = giữ rào đóng).
Server lo đọc biển số (ESP32-CAM) và chọn ô; Pi chỉ gửi "có xe ở cổng" rồi làm theo kết quả.
"""
import threading
import time


class Gate(threading.Thread):
    def __init__(self, name, sensor, barrier, link, screen, cfg):
        super().__init__(daemon=True, name=f"gate-{name}")
        self.name, self.sensor, self.barrier = name, sensor, barrier
        self.link, self.screen = link, screen
        self.clear_delay = cfg["gates"]["clear_delay_s"]
        self.new_car_gap = cfg["gates"].get("new_car_gap_s", 1.0)
        self.timeout = cfg["server"]["request_timeout_s"]
        self.offline_open = cfg.get("offline", {}).get("policy", "open") == "open"
        self.state = "IDLE"
        self.clear_since = None
        self.stop_flag = False

    # --- lệnh từ dashboard ---
    def force_open(self):
        self.barrier.open()
        self.state = "OPEN"
        self.clear_since = None

    def force_close(self):
        if not self.sensor.present:   # không hạ rào xuống đầu xe
            self.barrier.close()
            self.state = "CLOSING"

    def apply_result(self, res):
        """Kết quả do quản lý xử lý tay trên dashboard (nhập biển số khi camera đọc không được)."""
        self.clear_since = None
        self._decide(res)

    # --- vòng lặp ---
    def run(self):
        while not self.stop_flag:
            time.sleep(0.1)
            try:
                self.step()
            except Exception as e:  # không để một lỗi làm chết cổng
                print(f"[gate {self.name}] lỗi: {e}")
                self.link.send({"type": "log", "level": "error", "message": f"Cổng {self.name}: {e}"})
                time.sleep(2)   # lỗi lặp lại thì cũng không dồn dập hỏi server / ghi log

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
                    if self.name == "in":
                        self.screen.release()
                    self.state = "IDLE"
        elif self.state == "OPEN":
            if present and self._gap() >= self.new_car_gap:
                self.on_arrival()                     # xe sau nối đuôi khi rào chưa kịp đóng
            elif self._clear_for(present, self.clear_delay):
                self.barrier.close()
                self.state = "CLOSING"
        elif self.state == "CLOSING":
            if present:
                self.barrier.open()                   # xe chen vào lúc rào đang đóng: mở lại ngay
                self.state = "OPEN"
                self.on_arrival()
            elif self.barrier.state == "closed":
                self.state = "IDLE"
                if self.name == "in":
                    self.screen.release()

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

    # --- một lượt xe ---
    def on_arrival(self):
        self.clear_since = None
        print(f"[gate {self.name}] phát hiện xe ({self.sensor.distance:.0f} cm)")
        t0 = time.time()
        res = self.link.request(self.name, self.timeout)   # None = mất server / quá hạn
        t_res = time.time()
        self._decide(res)
        self._log_timing(res, t0, t_res)

    def _decide(self, res):   # KHÔNG đặt tên _handle: Python 3.13 Thread đã dùng self._handle
        if self.name == "in":
            self._entry(res)
        else:
            self._exit(res)

    def _entry(self, res):
        sc = self.screen
        if res is None:
            sc.set_online(False)
            if self.offline_open:
                sc.hold(sc.message(["OFFLINE", "Mời xe vào"]))
                self._open()
            else:
                sc.hold(sc.message(["OFFLINE", "Tạm dừng"]))
                self.state = "DENIED"
            return
        sc.set_online(True)
        if res.get("allowed"):
            sc.hold(sc.guidance(res))
            self._open()
        else:   # bãi đầy / không đọc được biển / xe đã ở trong bãi
            s = res["screen"]
            sc.hold(sc.message([s["title"], *s["lines"]]))
            self.state = "DENIED"

    def _exit(self, res):
        sc = self.screen
        if res is None and not self.offline_open:
            sc.flash(sc.message(["OFFLINE", "Tạm dừng"]))
            self.state = "DENIED"
            return
        if res is not None and not res.get("allowed", True):
            # biển số không đọc được / không khớp lượt vào -> giữ rào đóng, chờ xe lùi ra hoặc quản lý xử lý
            s = res.get("screen") or {"title": "Chờ bảo vệ", "lines": []}
            sc.flash(sc.message([s["title"], *s["lines"]]), 6)
            self.state = "DENIED"
            return
        self._open()   # cho ra: chỉ mở rào, màn hình giữ nguyên (không hiện lời chào tạm biệt)

    def _open(self):
        self.barrier.open()
        self.state = "OPEN"

    def _log_timing(self, res, t0, t_res):
        """In thời gian một lượt xe: server xử lý (đọc biển...) và mạng -> quyết định mở rào."""
        t = (res or {}).get("timing") or {}
        srv = f"server {t['total_ms']} ms" if "total_ms" in t else ("mất server" if res is None else "server ?")
        if "read_ms" in t:
            srv += f" (đọc biển {t['read_ms']} ms, {t.get('frames', 0)} ảnh)"
        net = (t_res - t0) * 1000 - t.get("total_ms", 0)
        verdict = "MỞ RÀO" if self.state == "OPEN" else "giữ rào"
        print(f"[timing {self.name}] {verdict} sau {time.time() - t0:.2f}s: {srv}, mạng ~{max(0, net):.0f} ms")
